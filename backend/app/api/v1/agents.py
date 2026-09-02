"""智能体 CRUD 与测试路由。"""
import json
import logging
import asyncio
import time
import os
from datetime import datetime
from app.core.timezone import beijing_now, beijing_now_iso

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Any, Optional

from app.database import get_db
from app.dependencies import check_resource_ownership, compute_can_edit_ids, get_current_user, require_permission
from app.models.agent import Agent
from app.models.execution import Execution
from app.models.user import User
from app.schemas.common import paginate, to_dict, to_dict_list
from app.agent.prompt_assembler import assemble_system_prompt

logger = logging.getLogger(__name__)


def _create_llm(agent, db, override: "Optional[ChatOverride]" = None):
    """根据智能体配置创建 LLM 实例（ChatOpenAI / ChatAnthropic）。

    支持会话级参数覆盖：override 非 None 时按字段独立覆盖 agent 配置，
    None 字段不覆盖（按需启用模式，避免覆盖模型默认值）。

    返回 (llm, config_info) 或 (None, error_msg)。
    """
    from app.agent.decision import _load_llm_config
    from app.core.llm_helper import create_llm_from_config

    # 解析 effective model_config_id（override 优先）
    eff_model_config_id = (
        override.model_config_id
        if override and override.model_config_id is not None
        else agent.model_config_id
    )
    # 解析 effective temperature / max_tokens
    eff_temp = (
        override.temperature
        if override and override.temperature is not None
        else (agent.temperature if agent.temperature is not None else 0.7)
    )
    eff_max_tokens = (
        override.max_tokens
        if override and override.max_tokens is not None
        else (agent.max_tokens or 1024)
    )
    # 扩展参数：仅 override 非 None 时透传（None 即不传，使用模型默认）
    extra_kwargs: dict = {}
    if override:
        for k in ("top_p", "frequency_penalty", "presence_penalty", "seed"):
            v = getattr(override, k, None)
            if v is not None:
                extra_kwargs[k] = v

    llm_config = _load_llm_config(db, eff_model_config_id)
    if llm_config is not None and (llm_config.api_key or llm_config.base_url):
        try:
            llm, info = create_llm_from_config(
                llm_config,
                temperature=eff_temp,
                max_tokens=eff_max_tokens,
                **extra_kwargs,
            )
            return llm, info
        except ValueError as exc:
            return None, str(exc)
        except Exception as exc:
            logger.exception("创建 LLM 实例失败: %s", exc)
            return None, f"创建 LLM 实例失败: {exc}"

    # 尝试环境变量（Anthropic）
    from app.core.config import settings
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key:
        return None, "未配置 LLM API Key，请在「模型设置」中配置"

    try:
        from langchain_anthropic import ChatAnthropic
        # 环境变量回退路径：仅支持 top_p（Anthropic 限制），其余扩展参数忽略并告警
        env_kwargs: dict = {
            "model": "claude-3-5-haiku-20241022",
            "api_key": api_key,
            "temperature": eff_temp,
            "max_tokens": eff_max_tokens,
        }
        if "top_p" in extra_kwargs:
            env_kwargs["top_p"] = extra_kwargs["top_p"]
        for k in ("frequency_penalty", "presence_penalty", "seed"):
            if k in extra_kwargs:
                logger.warning("Anthropic 不支持 %s，已忽略", k)
        llm = ChatAnthropic(**env_kwargs)
        return llm, {"provider": "anthropic", "model": "(env)"}
    except Exception as exc:
        logger.exception("创建 LLM 实例失败: %s", exc)
        return None, f"创建 LLM 实例失败: {exc}"

router = APIRouter(
    prefix="/agents",
    tags=["agents"],
    dependencies=[Depends(get_current_user)],
)


def _sanitize_enabled_kbs(db: Session, agent: Agent) -> bool:
    """剔除智能体 enabled_kbs 中已不存在的知识库 ID，并持久化清理。

    场景：用户手动删除知识库时若清理逻辑未覆盖（如历史数据残留），
    enabled_kbs 可能含已不存在的 KB id（如已删除的 KB5），导致前端
    仍展示被删知识库。本函数在读取智能体时防御性过滤，保证配置与
    数据库一致。

    Returns:
        True 表示发生了清理并已提交。
    """
    kbs = list(agent.enabled_kbs or [])
    if not kbs:
        return False
    from app.models.knowledge_base import KnowledgeBase

    # db.query(KnowledgeBase.id).all() 返回 Row 对象列表，取首列
    existing_ids = {row[0] for row in db.query(KnowledgeBase.id).all()}
    new_kbs = [k for k in kbs if k in existing_ids]
    if len(new_kbs) != len(kbs):
        agent.enabled_kbs = new_kbs
        db.commit()
        removed = [k for k in kbs if k not in existing_ids]
        logger.warning(
            "智能体 %s 的 enabled_kbs 含无效知识库引用 %s，已自动清理",
            agent.id, removed,
        )
        return True
    return False


class AgentBase(BaseModel):
    """智能体请求体。"""

    name: str = Field(..., description="智能体名称")
    description: str = Field("", description="智能体描述")
    model_config_id: int | None = Field(None, description="关联的 LLMConfig id")
    system_prompt: str | None = Field(None, description="系统提示词")
    temperature: float = Field(0.7, description="采样温度")
    max_tokens: int = Field(1024, description="最大生成 token 数")
    enabled_tools: list[str] | None = Field(None, description="启用的工具名称列表")
    enabled_kbs: list[int] | None = Field(None, description="启用的知识库 id 列表")
    enabled_asset_types: list[str] | None = Field(None, description="启用的资产类型 code 列表")
    # 启用的技能 id 列表（纯文本指令，注入 system prompt，见 prompt_assembler.py）
    enabled_skills: list[int] | None = Field(None, description="启用的技能 id 列表（注入 system prompt）")
    max_iterations: int = Field(5, description="最大迭代轮数")
    # 基础信息与形象
    avatar: str | None = Field(None, description="头像 URL")
    greeting: str | None = Field(None, description="开场白")
    suggested_questions: list[str] | None = Field(None, description="开场引导问题")
    # 模型参数扩展
    context_turns: int = Field(10, description="上下文轮数")
    # 记忆与高级机制
    enable_memory: bool = Field(False, description="长期记忆开关")
    tone_style: str = Field("professional", description="语气风格")
    variables: dict | None = Field(None, description="自定义变量")
    tool_configs: dict | None = Field(None, description="工具配置（key=工具名, value={timeout, retry, require_confirm}）")
    # 执行引擎：langgraph（默认）| hermes（Hermes 风格 ReAct + 分段并行 + 记忆 + 委派）
    engine: str = Field("langgraph", description="执行引擎：langgraph（默认）| hermes")


class ChatOverride(BaseModel):
    """会话级参数覆盖（仅本次请求生效，不修改 Agent 配置）。

    每个字段独立可选：None 表示不覆盖，使用 Agent 自身配置。
    前端按需启用模式：只有用户开启的参数才写入此对象。
    借鉴 new-api Playground 的设计：避免覆盖模型默认值。
    """

    model_config_id: Optional[int] = Field(None, description="覆盖模型配置 id")
    system_prompt: Optional[str] = Field(None, description="覆盖系统提示词")
    temperature: Optional[float] = Field(None, description="覆盖采样温度")
    top_p: Optional[float] = Field(None, description="覆盖核采样概率")
    max_tokens: Optional[int] = Field(None, description="覆盖最大生成 token 数")
    frequency_penalty: Optional[float] = Field(None, description="覆盖频率惩罚")
    presence_penalty: Optional[float] = Field(None, description="覆盖存在惩罚")
    seed: Optional[int] = Field(None, description="覆盖随机种子")


class AgentTestRequest(BaseModel):
    """智能体测试请求体。"""

    input: str = Field(..., description="测试输入，可为 JSON 字符串或自由文本")
    # 会话 ID：Hermes 引擎按 (agent_id, session_id) 持久化对话历史，
    # 多轮对话（如封禁确认流程）下，下一轮请求加载同 session 的历史注入 LLM 上下文。
    # 前端为每个对话生成 UUID；缺省 "default" 兼容旧调用。
    session_id: str = Field("default", description="会话 ID（多轮对话上下文持久化键）")
    # 会话级参数覆盖：None 时走 Agent 配置（向后兼容）；非 None 时按字段独立覆盖
    override: Optional[ChatOverride] = Field(None, description="会话级参数覆盖（仅本次请求生效）")


class ResumeRequest(BaseModel):
    """恢复中断技能的请求体。"""

    decision: str = Field("approve", description="审批决定：approve | reject")


@router.get("")
def list_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """列出所有智能体。

    每项附带 ``can_edit`` 标志（admin/owner/被授权用户为 True）。
    """
    logger.info("查询智能体列表")
    agents = db.query(Agent).order_by(Agent.created_at.desc()).all()
    # 防御性清理：剔除已不存在的知识库引用（如手动删除 KB 后的残留）
    for agent in agents:
        _sanitize_enabled_kbs(db, agent)
    result = to_dict_list(agents)
    # 资源级 owner 控制：批量查共享授权集合，admin 在调用处直接判 True
    shared_ids = compute_can_edit_ids(db, current_user, "agent", [a.id for a in agents])
    for item, agent in zip(result, agents):
        item["can_edit"] = (
            current_user.role == "admin"
            or agent.created_by == current_user.id
            or agent.id in shared_ids
        )
    return result


@router.get("/{agent_id}")
def get_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """获取单个智能体详情。

    监控页面（AgentMonitor）和前端 agentsApi.get(id) 调用此端点。
    若缺少此 GET 路由，FastAPI 仅有 PUT/DELETE /{agent_id}，GET 请求返回 405。
    附带 ``can_edit`` 标志（admin/owner/被授权用户为 True）。
    """
    logger.info("查询智能体详情: agent_id=%s", agent_id)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    # 防御性清理：剔除已不存在的知识库引用（如手动删除 KB 后的残留）
    _sanitize_enabled_kbs(db, agent)
    data = to_dict(agent)
    shared_ids = compute_can_edit_ids(db, current_user, "agent", [agent.id])
    data["can_edit"] = (
        current_user.role == "admin"
        or agent.created_by == current_user.id
        or agent.id in shared_ids
    )
    return data


@router.post("", status_code=201)
def create_agent(
    body: AgentBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """创建智能体。"""
    logger.info("创建智能体: name=%s", body.name)
    agent = Agent(
        name=body.name,
        description=body.description,
        model_config_id=body.model_config_id,
        system_prompt=body.system_prompt,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        enabled_tools=body.enabled_tools or [],
        enabled_kbs=body.enabled_kbs or [],
        enabled_asset_types=body.enabled_asset_types or [],
        enabled_skills=body.enabled_skills or [],
        max_iterations=body.max_iterations,
        avatar=body.avatar,
        greeting=body.greeting,
        suggested_questions=body.suggested_questions or [],
        context_turns=body.context_turns,
        enable_memory=body.enable_memory,
        tone_style=body.tone_style,
        variables=body.variables or {},
        tool_configs=body.tool_configs or {},
        engine=body.engine or "langgraph",
        created_by=current_user.id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    logger.info("智能体已创建: id=%s, engine=%s", agent.id, agent.engine)
    return to_dict(agent)


@router.put("/{agent_id}")
def update_agent(
    agent_id: int,
    body: AgentBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """更新智能体。"""
    logger.info("更新智能体: id=%s", agent_id)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    # 资源级 owner 校验：仅 admin/owner/被授权用户可编辑
    check_resource_ownership(current_user, db, "agent", agent_id, agent)
    agent.name = body.name
    agent.description = body.description
    agent.model_config_id = body.model_config_id
    agent.system_prompt = body.system_prompt
    agent.temperature = body.temperature
    agent.max_tokens = body.max_tokens
    agent.enabled_tools = body.enabled_tools or []
    agent.enabled_kbs = body.enabled_kbs or []
    agent.enabled_asset_types = body.enabled_asset_types or []
    agent.enabled_skills = body.enabled_skills or []
    agent.max_iterations = body.max_iterations
    agent.avatar = body.avatar
    agent.greeting = body.greeting
    agent.suggested_questions = body.suggested_questions or []
    agent.context_turns = body.context_turns
    agent.enable_memory = body.enable_memory
    agent.tone_style = body.tone_style
    agent.variables = body.variables or {}
    agent.tool_configs = body.tool_configs or {}
    # engine：前端 body 未传 engine 时保留原值（避免误覆盖为 langgraph）
    if body.engine:
        agent.engine = body.engine
    db.commit()
    db.refresh(agent)
    logger.info("智能体已更新: id=%s, engine=%s", agent.id, agent.engine)
    return to_dict(agent)


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """删除智能体。"""
    logger.info("删除智能体: id=%s", agent_id)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    # 资源级 owner 校验：仅 admin/owner/被授权用户可删除
    check_resource_ownership(current_user, db, "agent", agent_id, agent)

    # 先清理智能体的全部关联数据，否则会因外键约束（chat_messages_agent_id_fkey）删除失败，
    # 并避免遗留孤儿数据（executions / agent_files 虽无 DB 约束，也一并清理）。
    try:
        from sqlalchemy import delete as sa_delete

        from app.models.agent_file import AgentFile
        from app.models.chat_message import ChatMessage

        # 该智能体上传/生成的文件（含磁盘文件）
        for rec in db.query(AgentFile).filter(AgentFile.agent_id == agent_id).all():
            try:
                if rec.file_path and os.path.exists(rec.file_path):
                    os.remove(rec.file_path)
            except OSError as exc:
                logger.warning("删除智能体文件磁盘失败: %s, error=%s", rec.file_path, exc)
            db.delete(rec)
        # 对话消息（有 DB 外键约束，必须删除）
        db.execute(sa_delete(ChatMessage).where(ChatMessage.agent_id == agent_id))
        # 执行记录
        db.execute(sa_delete(Execution).where(Execution.agent_id == agent_id))

        db.delete(agent)
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("智能体已删除: id=%s", agent_id)
    return {"ok": True}


@router.post("/{agent_id}/test")
async def test_agent(
    agent_id: int, body: AgentTestRequest, db: Session = Depends(get_db)
) -> dict:
    """测试智能体，返回推理结果与日志。

    - 未勾选工具和知识库时：走纯 LLM 对话路径（不使用安全决策流程）
    - 勾选了工具/知识库时：走 LangGraph Agent 决策路径
    """
    logger.info("测试智能体: id=%s", agent_id)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # 解析输入
    user_input: str = body.input or ""
    try:
        parsed = json.loads(user_input)
        if isinstance(parsed, dict):
            alert_data = parsed
            user_text = user_input
        else:
            alert_data = {"input": user_input}
            user_text = user_input
    except (json.JSONDecodeError, TypeError):
        alert_data = {"input": user_input}
        user_text = user_input

    has_tools = bool(agent.enabled_tools) or bool(agent.enabled_kbs) or bool(agent.enabled_asset_types)

    # ===== 无工具：纯 LLM 对话路径 =====
    if not has_tools:
        llm, err = _create_llm(agent, db)
        if llm is None:
            raise HTTPException(status_code=400, detail=err)

        from langchain_core.messages import HumanMessage, SystemMessage
        # 组装 system prompt：基础提示词 + 启用技能正文（变量替换 + 分段注入）
        system_prompt = assemble_system_prompt(
            db, agent, fallback_prompt="你是一个智能助手，请根据用户输入给出有帮助的回答。"
        )
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_text)]
        try:
            ai_msg = await llm.ainvoke(messages)
            reply = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
        except Exception as exc:
            logger.exception("纯对话调用失败: %s", exc)
            raise HTTPException(status_code=500, detail=f"LLM 调用失败: {exc}")

        # 保存执行记录
        try:
            exec_record = Execution(
                agent_id=agent.id,
                status="success",
                result={"reply": reply, "input": user_text, "mode": "chat"},
                trigger_type="agent_test",
                finished_at=beijing_now(),
            )
            db.add(exec_record)
            db.commit()
        except Exception as exc:
            logger.warning("保存执行记录失败: %s", exc)
            db.rollback()

        return {
            "reply": reply,
            "messages": [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": reply},
            ],
            "logs": [{"level": "info", "message": "纯对话模式（无工具调用）"}],
        }

    # ===== 有工具：走 LangGraph Agent 决策路径 =====
    from app.agent.decision import run_agent_decision

    logger.info("调用 run_agent_decision, alert_data=%s", alert_data)
    result = await run_agent_decision(
        alert_data=alert_data,
        enabled_tools=agent.enabled_tools or [],
        enabled_kbs=agent.enabled_kbs or [],
        enabled_asset_types=agent.enabled_asset_types or [],
        model_config_id=agent.model_config_id,
        # 组装 system prompt：基础提示词 + 启用技能正文。
        # allow_none=True：无 base 且无技能时返回 None，由 decision.py 走默认安全专家提示词
        # + 决策 JSON 解析（保持旧逻辑）；有 base 或技能时返回非 None，跳过决策解析返回原始响应。
        system_prompt=assemble_system_prompt(db, agent, allow_none=True),
        temperature=agent.temperature,
        max_tokens=agent.max_tokens,
        max_iterations=agent.max_iterations,
    )

    # 创建执行记录
    try:
        exec_record = Execution(
            agent_id=agent.id,
            status="success",
            result={
                "decision": result.get("decision"),
                "target_ip": result.get("target_ip"),
                "reason": result.get("reason"),
                "duration": result.get("duration"),
                "input": alert_data,
                "messages_count": len(result.get("messages", [])),
            },
            trigger_type="agent_test",
            finished_at=beijing_now(),
        )
        db.add(exec_record)
        db.commit()
        db.refresh(exec_record)
        logger.info("智能体执行记录已保存: execution_id=%s, agent_id=%s", exec_record.id, agent.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("保存智能体执行记录失败（不影响测试结果）: %s", exc)
        db.rollback()

    return {
        "decision": result.get("decision"),
        "target_ip": result.get("target_ip"),
        "reason": result.get("reason"),
        "duration": result.get("duration"),
        "messages": result.get("messages", []),
        "logs": result.get("logs", []),
    }


@router.post("/{agent_id}/test/stream")
async def test_agent_stream(
    agent_id: int, body: AgentTestRequest, db: Session = Depends(get_db)
):
    """流式测试智能体（SSE），逐 token 返回 LLM 输出。

    无工具时走纯对话流式；有工具时走 Agent 决策（非流式，一次性返回）。
    """
    logger.info("流式测试智能体: id=%s", agent_id)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    user_input = body.input or ""
    has_tools = bool(agent.enabled_tools) or bool(agent.enabled_kbs) or bool(agent.enabled_asset_types)

    async def sse_stream():
        # ===== 无工具：纯对话流式 =====
        if not has_tools:
            llm, err = _create_llm(agent, db, override=body.override)
            if llm is None:
                yield f"data: {json.dumps({'type': 'error', 'message': err}, ensure_ascii=False)}\n\n"
                return

            from langchain_core.messages import HumanMessage, SystemMessage
            # 组装 system prompt：override 优先，否则用 assemble_system_prompt（含技能注入）
            if body.override and body.override.system_prompt is not None:
                system_prompt = body.override.system_prompt
            else:
                system_prompt = assemble_system_prompt(
                    db, agent, fallback_prompt="你是一个智能助手，请根据用户输入给出有帮助的回答。"
                )
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]

            yield f"data: {json.dumps({'type': 'start', 'mode': 'chat'}, ensure_ascii=False)}\n\n"
            full_reply = ""
            token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            try:
                async for chunk in llm.astream(messages):
                    token = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if token:
                        full_reply += token
                        yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0)  # 让出控制权
                    # 捕获 token 用量（astream 最后一个 chunk 包含 usage_metadata）
                    usage_meta = getattr(chunk, "usage_metadata", None)
                    if usage_meta:
                        token_usage = {
                            "input_tokens": getattr(usage_meta, "input_tokens", 0) or usage_meta.get("input_tokens", 0) if isinstance(usage_meta, dict) else 0,
                            "output_tokens": getattr(usage_meta, "output_tokens", 0) or usage_meta.get("output_tokens", 0) if isinstance(usage_meta, dict) else 0,
                            "total_tokens": getattr(usage_meta, "total_tokens", 0) or usage_meta.get("total_tokens", 0) if isinstance(usage_meta, dict) else 0,
                        }
            except Exception as exc:
                logger.exception("流式调用失败: %s", exc)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
                return

            yield f"data: {json.dumps({'type': 'done', 'reply': full_reply, 'usage': token_usage}, ensure_ascii=False)}\n\n"

            # 保存执行记录
            try:
                exec_record = Execution(
                    agent_id=agent.id,
                    status="success",
                    result={"reply": full_reply, "input": user_input, "mode": "chat_stream"},
                    trigger_type="agent_test",
                    finished_at=beijing_now(),
                )
                db.add(exec_record)
                db.commit()
            except Exception as exc:
                db.rollback()
            return

        # ===== 有工具：Agent 决策（流式推送 token） =====
        yield f"data: {json.dumps({'type': 'start', 'mode': 'agent'}, ensure_ascii=False)}\n\n"
        from app.agent.decision import run_agent_decision_stream
        try:
            alert_data = {"input": user_input}
            try:
                parsed = json.loads(user_input)
                if isinstance(parsed, dict):
                    alert_data = parsed
            except (json.JSONDecodeError, TypeError):
                pass

            # 流式 Agent 决策：逐 token 推送 LLM 输出
            # 透传 override：model_config_id/system_prompt/temperature/max_tokens 直接覆盖；
            # top_p/frequency_penalty/presence_penalty/seed 打包为 extra_llm_kwargs
            ov = body.override
            extra_llm_kwargs: dict = {}
            if ov:
                for k in ("top_p", "frequency_penalty", "presence_penalty", "seed"):
                    v = getattr(ov, k, None)
                    if v is not None:
                        extra_llm_kwargs[k] = v

            async for evt in run_agent_decision_stream(
                alert_data=alert_data,
                enabled_tools=agent.enabled_tools or [],
                enabled_kbs=agent.enabled_kbs or [],
                enabled_asset_types=agent.enabled_asset_types or [],
                model_config_id=(ov.model_config_id if ov and ov.model_config_id is not None else agent.model_config_id),
                system_prompt=(
                    ov.system_prompt if ov and ov.system_prompt is not None
                    else assemble_system_prompt(db, agent, allow_none=True)
                ),
                temperature=(ov.temperature if ov and ov.temperature is not None else agent.temperature),
                max_tokens=(ov.max_tokens if ov and ov.max_tokens is not None else agent.max_tokens),
                max_iterations=agent.max_iterations,
                extra_llm_kwargs=extra_llm_kwargs or None,
            ):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)  # 让出控制权，确保前端实时收到
        except Exception as exc:
            logger.exception("Agent 决策失败: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


# ============================================================================
# Hermes 引擎专用端点（仅 engine=hermes 的 Agent 走此路径）
# ============================================================================


def _load_chat_history(db, agent_id: int, session_id: str, context_turns: int) -> list[dict]:
    """加载最近 N 轮对话历史（OpenAI 格式），保持 tool_call/tool_result 配对。

    Hermes 引擎每个 HTTP 请求是无状态的，多轮对话（如封禁确认）需跨请求保留
    上下文。本函数从 chat_messages 表按 (agent_id, session_id) 取最近若干条，
    反转为正序后返回，供 executor.load_history 注入。

    修剪规则：若开头是孤立的 tool 消息（其配对的 assistant tool_calls 被截断掉），
    逐条丢弃直到开头为 user/assistant，避免 OpenAI API 报 tool message 无配对。

    排序稳定性：同一轮持久化的多条消息（assistant + tool + tool）created_at 可能
    完全相同（微秒级并发写入）。仅按 created_at 排序时，PostgreSQL 对相等键的返回
    顺序不确定，可能把 tool 排到 assistant 之前，导致 OpenAPI 报 "tool must be a
    response to a preceding message with tool_calls"。追加 id 作为次级排序键
    （id 为自增主键，反映插入顺序：assistant 永远先于其 tool 结果插入）保证稳定。
    """
    from app.models.chat_message import ChatMessage

    # 每轮约 4-6 条（user + assistant + tool + ...），按 context_turns 估算条数
    limit = max(context_turns * 8, 20)
    records = (
        db.query(ChatMessage)
        .filter(ChatMessage.agent_id == agent_id, ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    if not records:
        return []
    records = list(reversed(records))  # 旧 → 新
    history: list[dict] = []
    for r in records:
        msg: dict = {"role": r.role, "content": r.content or ""}
        if r.role == "assistant" and r.tool_calls:
            msg["tool_calls"] = r.tool_calls
        if r.role == "tool":
            msg["tool_call_id"] = r.tool_call_id or ""
            msg["name"] = r.name or ""
        history.append(msg)
    # 修剪开头的孤立 tool 消息
    while history and history[0].get("role") == "tool":
        history.pop(0)
    return history


def _persist_new_messages(db, agent_id: int, session_id: str, new_messages: list[dict]) -> None:
    """持久化本轮新增消息（user/assistant/tool）到 chat_messages 表。"""
    from app.models.chat_message import ChatMessage

    for m in new_messages:
        role = m.get("role", "user")
        if role not in ("user", "assistant", "tool"):
            continue
        db.add(ChatMessage(
            agent_id=agent_id,
            session_id=session_id,
            role=role,
            content=m.get("content", "") or "",
            tool_calls=m.get("tool_calls") if role == "assistant" else None,
            tool_call_id=m.get("tool_call_id", "") or "" if role == "tool" else "",
            name=m.get("name", "") or "" if role == "tool" else "",
        ))
    db.commit()


@router.post("/{agent_id}/chat")
async def chat_agent(
    agent_id: int,
    body: AgentTestRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("agent", "execute")),
):
    """Hermes 引擎 SSE 对话端点。

    仅 ``engine=hermes`` 的 Agent 走此路径；``engine=langgraph`` 返回 400
    引导用 ``/{agent_id}/test/stream``。

    SSE 事件契约（现有契约的超集）：
    - ``start``: 会话开始
    - ``status``: 状态更新
    - ``token``: LLM 流式 token
    - ``tool_start`` / ``tool_end``: 工具执行
    - ``skill_interrupt``: 技能中断等待审批
    - ``delegate``: 子代理事件
    - ``log``: 日志
    - ``done``: 完成
    - ``error``: 错误
    """
    logger.info("Hermes 引擎对话: agent_id=%s", agent_id)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.engine != "hermes":
        raise HTTPException(
            status_code=400,
            detail="此端点仅支持 engine=hermes 的智能体，请用 /test/stream",
        )

    from app.agent.hermes import HermesAgentExecutor, sse_stream

    # 解析 override.system_prompt：非 None 时覆盖智能体配置（仅本次会话）
    # 注意：override 的 system_prompt 不会经过 assemble_system_prompt 的技能注入，
    # 这是 Playground 调试模式的语义——用户应看到原始 prompt 的效果
    override_sp = (
        body.override.system_prompt
        if body.override and body.override.system_prompt is not None
        else None
    )

    try:
        executor = HermesAgentExecutor(
            db=db, agent=agent, user=current_user,
            override=body.override,             # 透传完整 override（含 model_config_id/temperature 等）
            system_prompt=override_sp,          # 复用 executor 已有的 system_prompt 覆盖参数
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Hermes 执行器创建失败: %s", exc)
        raise HTTPException(status_code=400, detail=f"执行器创建失败: {exc}") from exc

    # 加载历史对话注入 executor（多轮对话上下文持久化）
    session_id = body.session_id or "default"
    try:
        history = _load_chat_history(db, agent.id, session_id, agent.context_turns or 10)
        if history:
            executor.load_history(history)
            logger.info(
                "Hermes 历史注入: agent_id=%s session=%s 历史消息数=%d",
                agent.id, session_id, len(history),
            )
    except Exception:  # noqa: BLE001
        logger.exception("加载对话历史失败，将以无历史模式继续")

    async def sse_stream_with_execution():
        """SSE 流 + Execution 记录追踪。

        Hermes 引擎的每次对话都创建一条 Execution 记录，使监控页面能统计
        对话次数/成功失败率/耗时。LangGraph 的 test/stream 路径已在生成器内
        创建 Execution，Hermes 路径在此补齐。

        DB Session 生命周期优化：不依赖 Depends(get_db) 注入的 session
        （会在整个流式响应期间持有连接，多轮 ReAct 可能数十秒，高并发时
        连接池耗尽）。改用独立短生命周期 session 创建/更新记录，流中间
        不持有任何 DB 连接。
        """
        from app.database import SessionLocal

        # 流开始：独立 session 创建 Execution（用完即关）
        exec_id: int | None = None
        try:
            with SessionLocal() as s:
                rec = Execution(
                    agent_id=agent.id,
                    status="running",
                    trigger_type="agent_test",
                    result={"input": body.input, "engine": "hermes"},
                )
                s.add(rec)
                s.commit()
                s.refresh(rec)
                exec_id = rec.id
            logger.info("Hermes 执行记录已创建: execution_id=%s, agent_id=%s", exec_id, agent.id)
        except Exception:  # noqa: BLE001
            logger.exception("创建 Execution 记录失败，继续流式输出")

        final_reply = ""
        exec_status = "success"
        error_msg = ""
        tool_calls_detail: list[dict] = []
        # 工具调用计时：tool_call_id → 开始时间戳
        tool_timers: dict[str, float] = {}

        try:
            async for chunk in sse_stream(executor, body.input, session_id=session_id):
                # 解析事件以追踪状态（不修改原始 chunk，透传给前端）
                try:
                    if chunk.startswith("data: "):
                        data = json.loads(chunk[6:].strip())
                        etype = data.get("type", "")
                        if etype == "done":
                            final_reply = data.get("content", "") or data.get("reply", "")
                        elif etype == "error":
                            exec_status = "failed"
                            error_msg = data.get("message", "")
                        elif etype == "tool_start":
                            tc_id = data.get("tool_call_id", "")
                            tool_timers[tc_id] = time.monotonic()
                            tool_calls_detail.append({
                                "name": data.get("tool_name", ""),
                                "args": data.get("args"),
                                "status": "running",
                                "started_at": beijing_now_iso(),
                            })
                        elif etype == "tool_end":
                            tc_id = data.get("tool_call_id", "")
                            start_ts = tool_timers.pop(tc_id, None)
                            duration_ms = int((time.monotonic() - start_ts) * 1000) if start_ts else None
                            if tool_calls_detail:
                                tool_calls_detail[-1]["status"] = "done"
                                tool_calls_detail[-1]["result"] = data.get("result")
                                tool_calls_detail[-1]["duration_ms"] = duration_ms
                                tool_calls_detail[-1]["finished_at"] = beijing_now_iso()
                except (json.JSONDecodeError, ValueError):
                    pass
                yield chunk
        except Exception as exc:  # noqa: BLE001
            exec_status = "failed"
            error_msg = str(exc)
            raise
        finally:
            # 流结束：独立 session 更新 Execution 状态（用完即关）
            if exec_id is not None:
                try:
                    with SessionLocal() as s:
                        rec = s.query(Execution).filter(Execution.id == exec_id).first()
                        if rec is not None:
                            rec.status = exec_status
                            rec.finished_at = beijing_now()
                            # 从 executor 实例读取监控元数据
                            model_meta = getattr(executor, "_model_meta", {}) or {}
                            token_usage = getattr(executor, "_token_usage", {}) or {}
                            iteration_count = getattr(executor, "_iteration_count", 0)
                            thinking_chars = getattr(executor, "_thinking_chars", 0)
                            result: dict[str, Any] = {
                                "input": body.input,
                                "engine": "hermes",
                                "reply": final_reply,
                                "model": {
                                    "config_id": model_meta.get("model_config_id"),
                                    "name": model_meta.get("model_name", ""),
                                    "provider": model_meta.get("provider", ""),
                                },
                                "token_usage": token_usage,
                                "iterations": iteration_count,
                                "thinking_chars": thinking_chars,
                            }
                            if error_msg:
                                result["error"] = error_msg
                            if tool_calls_detail:
                                result["tool_calls"] = tool_calls_detail
                            rec.result = result
                            s.commit()
                except Exception:  # noqa: BLE001
                    logger.exception("更新 Execution 记录失败: exec_id=%s", exec_id)

            # 持久化本轮新增对话消息（多轮上下文）。
            # 仅在至少产生了 assistant 回复时持久化（避免错误/中止时存入孤立的 user 消息）。
            try:
                new_msgs = executor.get_new_messages()
                has_assistant = any(m.get("role") == "assistant" for m in new_msgs)
                if has_assistant and new_msgs:
                    with SessionLocal() as s:
                        _persist_new_messages(s, agent.id, session_id, new_msgs)
                    logger.info(
                        "Hermes 对话持久化: agent_id=%s session=%s 新增消息数=%d",
                        agent.id, session_id, len(new_msgs),
                    )
            except Exception:  # noqa: BLE001
                logger.exception("持久化对话消息失败")

    return StreamingResponse(
        sse_stream_with_execution(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.post("/{agent_id}/skills/{skill_run_id}/resume")
async def resume_skill(
    agent_id: int,
    skill_run_id: str,
    body: ResumeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("agent", "execute")),
):
    """恢复被中断的工作流技能。

    审批通过/拒绝后调用此端点恢复技能执行。
    """
    logger.info("恢复技能: agent_id=%s, skill_run_id=%s, decision=%s", agent_id, skill_run_id, body.decision)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    from app.agent.hermes.skill_engine import HermesSkillEngine

    skill_engine = HermesSkillEngine(db, agent, current_user)
    try:
        ctx = await skill_engine.resume_skill(skill_run_id, body.decision)
        return {
            "skill_run_id": ctx.skill_run_id,
            "status": ctx.status,
            "execution_id": ctx.execution_id,
            "node_outputs": ctx.node_outputs,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("技能恢复失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"技能恢复失败: {exc}") from exc


@router.get("/{agent_id}/executions")
def list_agent_executions(
    agent_id: int,
    limit: int = Query(50, ge=1, le=500, description="返回条数上限（不传 page 时生效）"),
    page: int = Query(0, ge=0, description="页码（从1开始）；传0或不传则走旧版 limit 模式"),
    size: int = Query(20, ge=1, le=200, description="每页条数（仅 page>=1 时生效）"),
    db: Session = Depends(get_db),
) -> list[dict] | dict:
    """查询智能体的执行历史记录（含测试记录）。

    支持两种模式：
    - 旧版（page=0）：返回 ``limit`` 条记录的列表（向后兼容）。
    - 分页版（page>=1）：返回 ``{items, total, page, size, pages}`` 分页结构。
    """
    logger.info("查询智能体执行历史: agent_id=%s, page=%s, size=%s", agent_id, page, size)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    base_q = (
        db.query(Execution)
        .filter(Execution.agent_id == agent_id)
        .order_by(Execution.created_at.desc())
    )
    if page >= 1:
        return paginate(base_q, page=page, size=size)
    # 旧版兼容：直接返回 limit 条列表
    return [to_dict(e) for e in base_q.limit(limit).all()]


@router.get("/{agent_id}/monitor")
def agent_monitor_stats(agent_id: int, db: Session = Depends(get_db)) -> dict:
    """返回智能体监控统计数据。

    指标：
    - total: 总执行次数
    - success: 成功次数
    - failed: 失败次数
    - today: 今日执行次数
    - avg_duration_ms: 平均耗时（毫秒，基于 finished_at - created_at）
    - recent_7d: 最近 7 天每日执行次数列表
    """
    from sqlalchemy import func

    logger.info("查询智能体监控统计: agent_id=%s", agent_id)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    query = db.query(Execution).filter(Execution.agent_id == agent_id)
    total = query.count()
    success = query.filter(Execution.status == "success").count()
    failed = query.filter(Execution.status == "failed").count()

    now = beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = query.filter(Execution.created_at >= today_start).count()

    # 平均耗时
    avg_seconds = (
        db.query(func.avg(func.extract("epoch", Execution.finished_at - Execution.created_at)))
        .filter(Execution.agent_id == agent_id)
        .filter(Execution.finished_at.isnot(None))
        .scalar()
    )
    avg_duration_ms = int(float(avg_seconds) * 1000) if avg_seconds else 0

    # 最近 7 天每日执行次数
    from datetime import timedelta
    recent_7d = []
    for i in range(6, -1, -1):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = (
            query.filter(Execution.created_at >= day_start)
            .filter(Execution.created_at < day_end)
            .count()
        )
        recent_7d.append({"date": day_start.strftime("%m-%d"), "count": count})

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "today": today,
        "avg_duration_ms": avg_duration_ms,
        "recent_7d": recent_7d,
    }


# ============================================================================
# 工具搜索状态（tool_search 渐进式披露）
# ============================================================================


@router.get("/{agent_id}/tool-search-status")
def agent_tool_search_status(agent_id: int, db: Session = Depends(get_db)) -> dict:
    """返回智能体的工具搜索状态与装配预览。

    用于前端 AgentEditor 展示：
    - 当前 tool_search 配置（mode / threshold / limits）
    - 工具分类详情（核心 visible / 可延迟 deferrable，按 source 分组）
    - token 估算与是否激活预览

    幂等：只读端点，不修改 agent 状态。
    """
    from app.agent.hermes.tool_engine import HermesToolEngine
    from app.agent.hermes.tool_search import (
        BRIDGE_TOOL_NAMES,
        SOAR_CORE_TOOL_SOURCES,
        SOAR_DEFERRABLE_TOOL_SOURCES,
        estimate_tokens_from_schemas,
        is_deferrable_by_source,
    )

    logger.info("查询工具搜索状态: agent_id=%s", agent_id)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="智能体不存在")

    # 仅 hermes 引擎支持 tool_search；其他引擎返回空状态（前端降级展示）
    if (agent.engine or "hermes") != "hermes":
        return {
            "engine": agent.engine,
            "supported": False,
            "message": "tool_search 仅 Hermes 引擎支持",
            "config": None,
            "classification": {"visible": [], "deferrable": []},
            "stats": {
                "visible_count": 0,
                "deferrable_count": 0,
                "visible_tokens": 0,
                "deferrable_tokens": 0,
                "threshold_tokens": 0,
                "would_activate": False,
                "activated": False,
            },
        }

    # 实例化 tool_engine（轻量，不创建 LLM；_build_registry 完成 source 分类）
    try:
        tool_engine = HermesToolEngine(db, agent)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool_engine 初始化失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"工具引擎初始化失败: {exc}")

    cfg = tool_engine.tool_search_config

    # 触发一次装配（传空 extra，专注 DB 工具分类）
    # 装配会填充 _full_tool_defs / _source_map / _assembly_result
    try:
        tool_engine.get_assembled_openai_tools()
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool_search 装配预览失败: %s", exc)

    # 装配后读取 source_map（_build_source_map 从 _registry 派生，始终最新）
    source_map = tool_engine._build_source_map()
    full_defs = tool_engine._full_tool_defs or []
    assembly = tool_engine._assembly_result

    # 按工具名构建详情列表（含 source + token 估算）
    def _tool_detail(td: dict) -> dict:
        fn = td.get("function") or {}
        name = fn.get("name", "")
        source = source_map.get(name, "unknown")
        # 单工具 token 估算
        tokens = estimate_tokens_from_schemas([td])
        return {
            "name": name,
            "source": source,
            "description": (fn.get("description") or "")[:120],
            "tokens": tokens,
            "deferrable": is_deferrable_by_source(name, source),
        }

    visible_details = []
    deferrable_details = []
    for td in full_defs:
        fn = (td.get("function") or {})
        name = fn.get("name", "")
        # 跳过桥接工具（它们是替代品，不是用户配置的工具）
        if name in BRIDGE_TOOL_NAMES:
            continue
        detail = _tool_detail(td)
        if detail["deferrable"]:
            deferrable_details.append(detail)
        else:
            visible_details.append(detail)

    # 装配统计
    visible_tokens = sum(d["tokens"] for d in visible_details)
    deferrable_tokens = sum(d["tokens"] for d in deferrable_details)
    # context_length 未存库，用 None 表示（前端展示"未知"）
    context_length = None
    threshold_tokens = (
        int(context_length * (cfg.threshold_pct / 100.0)) if context_length else 0
    )
    # auto 模式下是否会激活（基于当前可延迟 token 与阈值）
    # context_length 未知时无法精确判断，前端展示"需运行时确定"
    would_activate = None
    if cfg.enabled == "on":
        # on 模式：只要有可延迟工具就激活
        would_activate = len(deferrable_details) > 0
    elif cfg.enabled == "off":
        would_activate = False
    # auto 模式：context_length 未知，无法预判（返回 None 让前端展示"运行时确定"）

    # 按 source 分组统计
    def _group_by_source(details: list) -> dict:
        groups: dict[str, list] = {}
        for d in details:
            groups.setdefault(d["source"], []).append(d)
        return {
            src: {"count": len(items), "tokens": sum(i["tokens"] for i in items), "tools": items}
            for src, items in groups.items()
        }

    return {
        "engine": "hermes",
        "supported": True,
        "config": {
            "enabled": cfg.enabled,
            "threshold_pct": cfg.threshold_pct,
            "search_default_limit": cfg.search_default_limit,
            "max_search_limit": cfg.max_search_limit,
        },
        "classification": {
            "visible": visible_details,
            "deferrable": deferrable_details,
            "visible_by_source": _group_by_source(visible_details),
            "deferrable_by_source": _group_by_source(deferrable_details),
        },
        "stats": {
            "visible_count": len(visible_details),
            "deferrable_count": len(deferrable_details),
            "visible_tokens": visible_tokens,
            "deferrable_tokens": deferrable_tokens,
            "threshold_pct": cfg.threshold_pct,
            "threshold_tokens": threshold_tokens,
            "context_length": context_length,
            "would_activate": would_activate,  # None=运行时确定, True/False=明确
            "activated": bool(assembly.activated) if assembly else False,
        },
        "source_catalog": {
            "core_sources": sorted(SOAR_CORE_TOOL_SOURCES),
            "deferrable_sources": sorted(SOAR_DEFERRABLE_TOOL_SOURCES),
        },
    }

