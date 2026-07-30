"""Agent 决策入口模块。

对外暴露 ``run_agent_decision``，作为后端调用 Agent 的唯一入口。
按以下优先级选择 LLM 配置：传入的 ``model_config_id`` > DB 中 ``is_default`` 的 LLMConfig
> 环境变量 ``ANTHROPIC_API_KEY``。配置可用时走真实 LangGraph 决策，否则走规则化 Mock 降级。

工具接入：
- ``enabled_tools`` 中的 DB 工具名，经 ``tool_runner`` 加载为 LangChain ``StructuredTool``。
- ``enabled_kbs`` 非空时追加一个 ``search_knowledge_base`` 工具（内部调 ``kb_retriever``）。

``run_agent_decision`` 返回结果中包含 ``logs``（``[{level, message}]``）便于排查与回传前端。
"""
import json
import logging
from typing import Any, AsyncGenerator, Optional

from pydantic import BaseModel, Field, create_model

from app.config import settings
from app.tools.context_tools import (
    check_subnet,
    check_whitelist,
    get_asset_info,
    get_threat_intel,
)

logger = logging.getLogger(__name__)

# Mock 路径下的默认封禁时长
_DEFAULT_BLOCK_DURATION = "24h"

# 合法的决策值集合
_VALID_DECISIONS = {"block_ip", "ignore", "need_human_approval"}

# parameters_schema 中 type -> Python 类型映射
_TYPE_MAP = {
    "String": str,
    "Number": float,
    "Boolean": bool,
    "Object": dict,
    "Array": list,
}


def _new_log(level: str, message: str) -> dict[str, str]:
    """构造一条日志记录。"""
    return {"level": level, "message": message}


def _load_llm_config(db, model_config_id: Optional[int]):
    """按优先级加载 LLM 配置：指定 id > is_default > None。"""
    from app.models.llm_config import LLMConfig

    if model_config_id is not None:
        cfg = db.query(LLMConfig).filter(LLMConfig.id == model_config_id).first()
        if cfg is not None:
            logger.info("使用指定 LLMConfig: id=%s, name=%s", cfg.id, cfg.name)
            return cfg
        logger.warning("指定 LLMConfig 不存在: id=%s", model_config_id)
    # 取默认配置
    cfg = db.query(LLMConfig).filter(LLMConfig.is_default.is_(True)).first()
    if cfg is not None:
        logger.info("使用默认 LLMConfig: id=%s, name=%s", cfg.id, cfg.name)
        return cfg
    logger.info("未找到 DB LLMConfig，将尝试环境变量 ANTHROPIC_API_KEY")
    return None


def _build_args_model(tool_name: str, parameters_schema: list[dict] | None):
    """根据 parameters_schema 动态构造 pydantic 入参模型。

    schema 元素结构：``{name, type, required, description}``。
    """
    fields: dict[str, Any] = {}
    for param in parameters_schema or []:
        name = param.get("name")
        if not name:
            continue
        ptype = param.get("type", "String")
        py_type = _TYPE_MAP.get(ptype, str)
        required = bool(param.get("required", False))
        desc = param.get("description", "")
        if required:
            fields[name] = (py_type, Field(..., description=desc))
        else:
            fields[name] = (Optional[py_type], Field(None, description=desc))
    safe_name = "".join(c if c.isalnum() else "_" for c in tool_name) or "Tool"
    return create_model(f"{safe_name}Args", **fields)


def _build_db_tools(db, enabled_tools: list[str]) -> list:
    """把启用的 DB 工具加载为 LangChain StructuredTool。

    Args:
        db: 数据库会话。
        enabled_tools: 工具名称列表。

    Returns:
        StructuredTool 实例列表（加载失败的工具被跳过并记录日志）。
    """
    from langchain_core.tools import StructuredTool

    from app.core.tool_runner import load_tool_function
    from app.models.tool import Tool

    tools: list = []
    if not enabled_tools:
        return tools
    for name in enabled_tools:
        tool = db.query(Tool).filter(Tool.name == name, Tool.enabled.is_(True)).first()
        if tool is None:
            logger.warning("DB 工具未找到或未启用: %s", name)
            continue
        try:
            run_fn = load_tool_function(tool)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DB 工具加载失败: %s, error=%s", name, exc)
            continue
        args_model = _build_args_model(tool.name, tool.parameters_schema)

        # 用工厂绑定每次迭代的 run_fn/name，避免闭包延迟捕获导致全部工具共用最后一份引用
        def _make_coroutine(rfn, tname):
            async def _coroutine(**kwargs):
                try:
                    return await rfn(**kwargs)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("工具 %s 执行异常: %s", tname, exc)
                    return {"error": str(exc)}
            return _coroutine

        structured = StructuredTool.from_function(
            name=tool.name,
            description=tool.description or f"DB 工具 {tool.name}",
            args_schema=args_model,
            coroutine=_make_coroutine(run_fn, name),
        )
        tools.append(structured)
        logger.info("已加载 DB 工具为 StructuredTool: %s", name)
    return tools


def _build_kb_tool(enabled_kbs: list[int]):
    """构造知识库检索工具（搜索所有启用知识库）。"""
    if not enabled_kbs:
        return None
    from langchain_core.tools import StructuredTool

    class SearchKBArgs(BaseModel):
        query: str = Field(..., description="检索查询字符串")
        kb_id: Optional[int] = Field(None, description="指定知识库 id；不传则检索所有启用知识库")

    kb_ids = list(enabled_kbs)

    async def _coroutine(query: str, kb_id: Optional[int] = None):
        from app.core.kb_retriever import search_kb

        if kb_id is not None:
            return await search_kb(kb_id, query)
        results: list = []
        for kid in kb_ids:
            results.extend(await search_kb(kid, query))
        return results

    return StructuredTool.from_function(
        name="search_knowledge_base",
        description="在已启用的知识库中检索相关文档。可指定 kb_id，不传则检索所有启用知识库。",
        args_schema=SearchKBArgs,
        coroutine=_coroutine,
    )


def _build_file_query_tool(enabled_kbs: list[int]):
    """构造知识库文件查询工具（读取原始 Excel/CSV 文件，按条件精确查询）。

    与 ``search_knowledge_base``（语义检索）互补：本工具返回结构化表格行列数据，
    适合精确查询 Excel 中的特定 IP、部门、资产等字段值。
    """
    if not enabled_kbs:
        return None
    from langchain_core.tools import StructuredTool

    class FileQueryArgs(BaseModel):
        query: str = Field(
            "",
            description="查询条件。支持关键词（任意列包含即命中）或 '列名=值' 精确过滤。"
            "例如 '192.168.1.1' 或 '部门=研发部'。留空则返回前几行预览。",
        )
        doc_id: Optional[int] = Field(
            None, description="指定文档 id（优先级最高）。不传则在所有启用知识库中搜索。"
        )
        kb_id: Optional[int] = Field(
            None, description="指定知识库 id。不传则搜索所有启用知识库。"
        )
        sheet: Optional[str] = Field(
            None, description="Excel sheet 名（不传则读第一个 sheet）"
        )
        limit: Optional[int] = Field(
            20, description="返回行数上限，默认 20，最大 200"
        )

    kb_ids = list(enabled_kbs)

    async def _coroutine(
        query: str = "",
        doc_id: Optional[int] = None,
        kb_id: Optional[int] = None,
        sheet: Optional[str] = None,
        limit: int = 20,
    ):
        from app.core.kb_file_query import query_kb_file

        return query_kb_file(
            query=query,
            kb_id=kb_id,
            doc_id=doc_id,
            sheet=sheet,
            limit=limit,
            enabled_kbs=kb_ids,
        )

    return StructuredTool.from_function(
        name="query_kb_file",
        description=(
            "查询知识库中的表格文件（Excel/CSV），返回结构化行列数据。"
            "适合精确查询 IP 列表、资产台账、人员信息等结构化数据。"
            "支持按列名=值过滤，或关键词模糊匹配。"
            "与 search_knowledge_base（语义检索）互补：本工具返回原始表格行数据。"
        ),
        args_schema=FileQueryArgs,
        coroutine=_coroutine,
    )


async def _mock_decision(alert_data: dict, logs: list[dict[str, str]]) -> dict:
    """规则化 Mock 决策路径。

    直接调用 4 个上下文工具查询源 IP，并基于规则生成决策。
    无需 LLM 与 API Key，适用于开发与测试环境。

    Args:
        alert_data: 告警数据，含 src_ip / dest_ip / alert_type。
        logs: 日志收集列表（会被追加）。

    Returns:
        与真实路径结构一致的决策结果（含 ``logs`` 字段）。
    """
    src_ip = alert_data.get("src_ip", "unknown")
    logs.append(_new_log("info", f"[Mock] 启动规则化决策, src_ip={src_ip}"))
    logger.info("[Mock] 启动规则化决策, src_ip=%s, alert_data=%s", src_ip, alert_data)

    messages: list = []

    # 1. 查询白名单
    messages.append({"role": "assistant", "content": f"正在查询 src_ip={src_ip} 的白名单..."})
    logs.append(_new_log("info", f"查询白名单, ip={src_ip}"))
    whitelist_hit = await check_whitelist(src_ip)
    messages.append({"role": "tool", "content": f"check_whitelist={whitelist_hit}"})

    # 2. 查询资产信息
    messages.append({"role": "assistant", "content": f"正在查询 src_ip={src_ip} 的资产信息..."})
    logs.append(_new_log("info", f"查询资产信息, ip={src_ip}"))
    asset_info = await get_asset_info(src_ip)
    messages.append({"role": "tool", "content": f"get_asset_info={json.dumps(asset_info, ensure_ascii=False)}"})

    # 3. 查询威胁情报
    messages.append({"role": "assistant", "content": f"正在查询 src_ip={src_ip} 的威胁情报..."})
    logs.append(_new_log("info", f"查询威胁情报, ip={src_ip}"))
    threat_intel = await get_threat_intel(src_ip)
    messages.append({"role": "tool", "content": f"get_threat_intel={json.dumps(threat_intel, ensure_ascii=False)}"})

    # 4. 查询子网信息
    messages.append({"role": "assistant", "content": f"正在查询 src_ip={src_ip} 的子网信息..."})
    logs.append(_new_log("info", f"查询子网信息, ip={src_ip}"))
    subnet_info = await check_subnet(src_ip)
    messages.append({"role": "tool", "content": f"check_subnet={json.dumps(subnet_info, ensure_ascii=False)}"})

    # 5. 基于规则生成决策
    is_malicious = bool(threat_intel.get("is_malicious"))
    is_critical = bool(asset_info.get("is_critical"))
    tags = threat_intel.get("tags", [])

    if whitelist_hit:
        decision = "ignore"
        reason = f"IP {src_ip} 在白名单中，判定为可信内网，无需处置"
        duration = ""
    elif is_malicious and is_critical:
        decision = "need_human_approval"
        reason = f"IP {src_ip} 命中威胁情报（tags={tags}）且为关键资产，需人工确认后处置"
        duration = _DEFAULT_BLOCK_DURATION
    elif is_malicious:
        decision = "block_ip"
        reason = f"威胁情报标记为恶意: {tags}，建议封禁"
        duration = _DEFAULT_BLOCK_DURATION
    else:
        decision = "ignore"
        reason = f"IP {src_ip} 未命中威胁情报，判定为非恶意，无需处置"
        duration = ""

    logs.append(_new_log("info", f"决策完成: {decision}, reason={reason}"))
    action_decision = {
        "decision": decision,
        "target_ip": src_ip,
        "reason": reason,
        "duration": duration,
    }
    messages.append({"role": "assistant", "content": json.dumps(action_decision, ensure_ascii=False)})

    logger.info("[Mock] 决策完成, action_decision=%s", action_decision)
    return {**action_decision, "messages": messages, "logs": logs}


def _parse_action_decision_from_content(content: str, src_ip: str) -> dict:
    """从 LLM 文本回复中解析结构化决策 JSON。

    Args:
        content: LLM 输出的文本，预期包含 JSON。
        src_ip: 默认 target_ip（解析失败时使用）。

    Returns:
        结构化决策字典；解析失败时返回 ``need_human_approval`` 降级决策。
    """
    fallback = {
        "decision": "need_human_approval",
        "target_ip": src_ip,
        "reason": "Agent 输出无法解析为结构化决策，需人工确认",
        "duration": _DEFAULT_BLOCK_DURATION,
    }
    if not content:
        logger.warning("[Parse] LLM 输出为空，使用降级决策")
        return fallback

    candidate = _extract_json_object(content)
    if candidate is None:
        candidate = content.strip()

    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("[Parse] JSON 解析失败: %s, 原文=%s", exc, content)
        return fallback

    decision = data.get("decision")
    if decision not in _VALID_DECISIONS:
        logger.warning("[Parse] 决策值非法: %s，使用降级决策", decision)
        return fallback

    parsed = {
        "decision": decision,
        "target_ip": data.get("target_ip", src_ip),
        "reason": data.get("reason", ""),
        "duration": data.get("duration", _DEFAULT_BLOCK_DURATION),
    }
    logger.info("[Parse] 决策解析成功: %s", parsed)
    return parsed


def _extract_json_object(text: str) -> str | None:
    """从文本中抽取首个完整的 JSON 对象字符串。"""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
    return None


def _messages_to_dict_list(messages: list) -> list:
    """将 LangChain 消息对象列表转为 ``{"role", "content"}`` 字典列表。"""
    result: list = []
    for msg in messages:
        role = getattr(msg, "type", None) or type(msg).__name__
        content = getattr(msg, "content", "")
        result.append({"role": role, "content": content})
    return result


async def _real_langgraph_decision(
    alert_data: dict,
    logs: list[dict[str, str]],
    api_key: str,
    base_url: str = "",
    model_name: str = "",
    tools: Optional[list] = None,
    system_prompt: Optional[str] = None,
    max_iterations: Optional[int] = None,
    temperature: float = 0,
    max_tokens: int = 1024,
    provider: str = "anthropic",
) -> dict:
    """真实 LangGraph 决策路径（按 DB 配置动态构建图）。

    Args:
        alert_data: 告警数据。
        logs: 日志收集列表。
        api_key: LLM API Key。
        base_url: 自定义 Base URL。
        model_name: 模型名。
        tools: 绑定工具列表。
        system_prompt: 系统提示词。
        max_iterations: 最大迭代轮数。
        temperature: 采样温度。
        max_tokens: 最大 token 数。
        provider: LLM 供应商（anthropic/openai 等）。

    Returns:
        结构化决策结果；图构建或执行失败时回退到 Mock 路径。
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agent.graph import SYSTEM_PROMPT, build_agent_graph

    src_ip = alert_data.get("src_ip", "unknown")
    logs.append(_new_log("info", f"[Real] 启动 LangGraph 决策, src_ip={src_ip}"))
    logger.info("[Real] 启动 LangGraph 决策, src_ip=%s, alert_data=%s", src_ip, alert_data)

    prompt = system_prompt or SYSTEM_PROMPT
    try:
        graph = build_agent_graph(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            tools=tools,
            system_prompt=prompt,
            max_iterations=max_iterations,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=provider,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Real] Agent 图构建失败，回退 Mock: %s", exc)
        logs.append(_new_log("warning", f"Agent 图构建失败，回退 Mock: {exc}"))
        return await _mock_decision(alert_data, logs)

    initial_messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=f"告警数据：{json.dumps(alert_data, ensure_ascii=False)}"),
    ]
    initial_state = {
        "alert_data": alert_data,
        "messages": initial_messages,
        "action_decision": {},
        "iteration": 0,
    }

    logs.append(_new_log("info", "调用 agent_graph.ainvoke"))
    try:
        final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 12})
    except Exception as exc:  # noqa: BLE001
        logger.exception("[Real] agent_graph.ainvoke 执行失败: %s", exc)
        logs.append(_new_log("warning", f"LangGraph 执行异常，回退 Mock: {exc}"))
        return await _mock_decision(alert_data, logs)

    final_messages = final_state.get("messages", [])
    logs.append(_new_log("info", f"LangGraph 完成, 消息数={len(final_messages)}, 迭代={final_state.get('iteration')}"))

    # 取最后一条 AIMessage 的文本内容用于解析
    last_content = ""
    for msg in reversed(final_messages):
        msg_type = getattr(msg, "type", None) or type(msg).__name__
        if msg_type in ("ai", "AIMessage"):
            last_content = getattr(msg, "content", "") or ""
            break

    messages_dict = _messages_to_dict_list(final_messages)

    # 自定义 system_prompt 时，不强制 block_ip/ignore/need_human_approval 决策格式，
    # 直接返回 LLM 原始文本作为 response，由调用方自行解释。
    if system_prompt is not None:
        logs.append(_new_log("info", "自定义提示词，跳过决策解析，返回原始响应"))
        logger.info("[Real] 自定义提示词，返回原始响应: %s", last_content[:200])
        return {"response": last_content, "messages": messages_dict, "logs": logs}

    action_decision = _parse_action_decision_from_content(last_content, src_ip)

    logs.append(_new_log("info", f"决策解析完成: {action_decision.get('decision')}"))
    logger.info("[Real] 决策完成, action_decision=%s", action_decision)
    return {**action_decision, "messages": messages_dict, "logs": logs}


async def run_agent_decision(
    alert_data: dict,
    enabled_tools: Optional[list[str]] = None,
    enabled_kbs: Optional[list[int]] = None,
    model_config_id: Optional[int] = None,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_iterations: Optional[int] = None,
    model_name: Optional[str] = None,
) -> dict:
    """Agent 决策入口。

    按优先级确定 LLM 配置：``model_config_id`` > DB 默认 LLMConfig > 环境变量
    ``ANTHROPIC_API_KEY``。配置可用走真实 LangGraph 路径，否则走 Mock 降级。

    Args:
        alert_data: 告警数据。
        enabled_tools: 启用的 DB 工具名称列表（可选）。
        enabled_kbs: 启用的知识库 id 列表（可选，非空则追加知识库检索工具）。
        model_config_id: 指定 LLMConfig id（可选）。
        system_prompt: 自定义系统提示词（可选）。
        temperature: 采样温度（可选）。
        max_tokens: 最大 token 数（可选）。
        max_iterations: 最大迭代轮数（可选）。
        model_name: 显式指定模型名（可选，传入时优先于 LLMConfig.model_name）。

    Returns:
        决策结果::

            {
                "decision": "block_ip" | "ignore" | "need_human_approval",
                "target_ip": "8.8.8.8",
                "reason": "...",
                "duration": "24h",
                "messages": [{"role", "content"}, ...],
                "logs": [{"level", "message"}, ...]
            }
    """
    logger.info("=" * 60)
    logger.info("收到告警决策请求, alert_data=%s", alert_data)
    logs: list[dict[str, str]] = []

    # DB 会话用于读取 LLMConfig / Tool / 知识库
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        llm_config = _load_llm_config(db, model_config_id)
        # 加载 DB 工具与知识库工具
        tools: list = []
        if enabled_tools:
            tools = _build_db_tools(db, enabled_tools)
            logs.append(_new_log("info", f"已加载 {len(tools)} 个 DB 工具"))
        kb_tool = _build_kb_tool(enabled_kbs or [])
        if kb_tool is not None:
            tools.append(kb_tool)
            logs.append(_new_log("info", f"已追加知识库检索工具(kbs={enabled_kbs})"))
        file_query_tool = _build_file_query_tool(enabled_kbs or [])
        if file_query_tool is not None:
            tools.append(file_query_tool)
            logs.append(_new_log("info", f"已追加文件查询工具(Excel/CSV精确查询)"))
    finally:
        db.close()

    # 确定 API Key 与模型配置
    # 显式传入的 model_name 优先于 LLMConfig.model_name
    override_model_name = model_name
    api_key: str = ""
    base_url: str = ""
    cfg_model_name: str = ""
    cfg_provider: str = "anthropic"
    if llm_config is not None and (llm_config.api_key or llm_config.base_url):
        api_key = llm_config.api_key or ""
        base_url = llm_config.base_url or ""
        cfg_model_name = llm_config.model_name or ""
        cfg_provider = (llm_config.provider or "anthropic").lower()
        logs.append(_new_log("info", f"使用 DB LLMConfig: provider={cfg_provider}, model={cfg_model_name or '(default)'}"))
    elif settings.ANTHROPIC_API_KEY:
        api_key = settings.ANTHROPIC_API_KEY
        logs.append(_new_log("info", "使用环境变量 ANTHROPIC_API_KEY"))

    # 显式传入的 model_name 优先；否则用 LLMConfig 的 model_name
    effective_model_name = override_model_name or cfg_model_name
    if override_model_name:
        logs.append(_new_log("info", f"使用显式传入模型名: {override_model_name}"))

    if api_key:
        logs.append(_new_log("info", "走真实 LangGraph 决策路径"))
        return await _real_langgraph_decision(
            alert_data=alert_data,
            logs=logs,
            api_key=api_key,
            base_url=base_url,
            model_name=effective_model_name,
            tools=tools or None,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            temperature=temperature if temperature is not None else 0,
            max_tokens=max_tokens if max_tokens is not None else 1024,
            provider=cfg_provider,
        )

    logs.append(_new_log("info", "未配置 LLM，走 Mock 降级决策路径"))
    return await _mock_decision(alert_data, logs)


async def run_agent_decision_stream(
    alert_data: dict,
    enabled_tools: Optional[list[str]] = None,
    enabled_kbs: Optional[list[int]] = None,
    model_config_id: Optional[int] = None,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_iterations: Optional[int] = None,
    model_name: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    """流式版 Agent 决策，异步生成 SSE 事件。

    与 ``run_agent_decision`` 配置解析逻辑一致，但使用 ``graph.astream_events``
    实现 token 级流式输出，让前端逐字渲染 LLM 回复。

    Yields:
        事件 dict，``type`` 为以下之一：
        - ``status``: 进度状态消息
        - ``token``: LLM 输出的 token（``content`` 字段）
        - ``tool_start`` / ``tool_end``: 工具调用开始/结束
        - ``log``: 执行日志
        - ``done``: 最终结果（``result`` 字段）
        - ``error``: 错误（``message`` 字段）
    """
    logger.info("=" * 60)
    logger.info("收到流式告警决策请求, alert_data=%s", alert_data)
    logs: list[dict[str, str]] = []

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        llm_config = _load_llm_config(db, model_config_id)
        tools: list = []
        if enabled_tools:
            tools = _build_db_tools(db, enabled_tools)
            logs.append(_new_log("info", f"已加载 {len(tools)} 个 DB 工具"))
        kb_tool = _build_kb_tool(enabled_kbs or [])
        if kb_tool is not None:
            tools.append(kb_tool)
            logs.append(_new_log("info", f"已追加知识库检索工具(kbs={enabled_kbs})"))
        file_query_tool = _build_file_query_tool(enabled_kbs or [])
        if file_query_tool is not None:
            tools.append(file_query_tool)
            logs.append(_new_log("info", f"已追加文件查询工具(Excel/CSV精确查询)"))
    finally:
        db.close()

    # 确定 API Key 与模型配置（与 run_agent_decision 逻辑一致）
    override_model_name = model_name
    api_key: str = ""
    base_url: str = ""
    cfg_model_name: str = ""
    cfg_provider: str = "anthropic"
    if llm_config is not None and (llm_config.api_key or llm_config.base_url):
        api_key = llm_config.api_key or ""
        base_url = llm_config.base_url or ""
        cfg_model_name = llm_config.model_name or ""
        cfg_provider = (llm_config.provider or "anthropic").lower()
        logs.append(_new_log("info", f"使用 DB LLMConfig: provider={cfg_provider}, model={cfg_model_name or '(default)'}"))
    elif settings.ANTHROPIC_API_KEY:
        api_key = settings.ANTHROPIC_API_KEY
        logs.append(_new_log("info", "使用环境变量 ANTHROPIC_API_KEY"))

    effective_model_name = override_model_name or cfg_model_name
    if override_model_name:
        logs.append(_new_log("info", f"使用显式传入模型名: {override_model_name}"))

    # 推送初始日志
    for log in logs:
        yield {"type": "log", "log": log}

    if not api_key:
        logs.append(_new_log("info", "未配置 LLM，走 Mock 降级决策路径"))
        yield {"type": "log", "log": logs[-1]}
        result = await _mock_decision(alert_data, logs)
        yield {"type": "done", "result": result}
        return

    # 构建图
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agent.graph import SYSTEM_PROMPT, build_agent_graph

    src_ip = alert_data.get("src_ip", "unknown")
    prompt = system_prompt or SYSTEM_PROMPT
    try:
        graph = build_agent_graph(
            api_key=api_key,
            base_url=base_url,
            model_name=effective_model_name,
            tools=tools or None,
            system_prompt=prompt,
            max_iterations=max_iterations,
            temperature=temperature if temperature is not None else 0,
            max_tokens=max_tokens if max_tokens is not None else 1024,
            provider=cfg_provider,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Stream] Agent 图构建失败，回退 Mock: %s", exc)
        yield {"type": "log", "log": _new_log("warning", f"Agent 图构建失败，回退 Mock: {exc}")}
        result = await _mock_decision(alert_data, logs)
        yield {"type": "done", "result": result}
        return

    initial_messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=f"告警数据：{json.dumps(alert_data, ensure_ascii=False)}"),
    ]
    initial_state = {
        "alert_data": alert_data,
        "messages": initial_messages,
        "action_decision": {},
        "iteration": 0,
    }

    yield {"type": "status", "message": "正在调用工具进行推理..."}

    # 使用 astream_events 实现 token 级流式
    full_text = ""
    final_state: dict | None = None

    try:
        async for event in graph.astream_events(
            initial_state, config={"recursion_limit": 12}, version="v2"
        ):
            kind = event.get("event", "")

            # LLM token 流式输出
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk:
                    token = getattr(chunk, "content", "") or ""
                    if token:
                        full_text += token
                        yield {"type": "token", "content": token}

            # 工具调用事件
            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                yield {"type": "tool_start", "tool_name": tool_name, "message": f"调用工具: {tool_name}"}

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                tool_output = event.get("data", {}).get("output")
                output_str = str(tool_output)[:300] if tool_output else ""
                yield {
                    "type": "tool_end",
                    "tool_name": tool_name,
                    "result": output_str,
                    "message": f"✓ {tool_name} 完成",
                }

            # 捕获根图的最终状态
            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if isinstance(output, dict) and "messages" in output:
                    final_state = output

    except Exception as exc:  # noqa: BLE001
        logger.exception("[Stream] astream_events 执行失败: %s", exc)
        yield {"type": "error", "message": str(exc)}
        return

    # 构建最终结果
    final_messages = (final_state or {}).get("messages", [])
    messages_dict = _messages_to_dict_list(final_messages) if final_messages else []

    # 优先使用流式收集的文本；为空时从 final_state 取最后一条 AIMessage
    last_content = full_text
    if not last_content and final_messages:
        for msg in reversed(final_messages):
            msg_type = getattr(msg, "type", None) or type(msg).__name__
            if msg_type in ("ai", "AIMessage"):
                last_content = getattr(msg, "content", "") or ""
                break

    logs.append(_new_log("info", f"流式决策完成, 回复长度={len(last_content)}"))

    if system_prompt is not None:
        result = {"response": last_content, "messages": messages_dict, "logs": logs}
    else:
        action_decision = _parse_action_decision_from_content(last_content, src_ip)
        # 同时包含 response（流式文本）和 decision 字段，前端优先用 response 展示
        result = {"response": last_content, **action_decision, "messages": messages_dict, "logs": logs}

    yield {"type": "done", "result": result}
