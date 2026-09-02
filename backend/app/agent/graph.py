"""LangGraph 状态机构建模块。

定义 Agent 决策状态机：``agent_node`` 调用绑定工具的 LLM，
``tool_executor_node`` 执行工具调用，二者通过条件边循环，
直至 Agent 输出最终结构化 JSON 回答或达到迭代上限。

支持两种构建方式：
- 模块级单例 ``agent_graph``：启动时按环境变量 ``ANTHROPIC_API_KEY`` 构建默认图（向后兼容）。
- ``build_agent_graph(...)``：按 DB 中的 LLMConfig / 启用工具 / 系统提示词动态构建，
  供 ``decision.run_agent_decision`` 在运行时按智能体配置调用。

模型与依赖仅在真正使用图时才被导入，避免在仅有 Mock 降级路径的
开发环境（未安装 langchain-anthropic）中导入失败。
"""
import logging
from typing import Optional

from app.agent.state import AgentState

logger = logging.getLogger(__name__)

# 系统提示词：约束 Agent 的角色、行为与输出格式
SYSTEM_PROMPT: str = (
    "你是 SOC 高级安全专家。接收到告警后，请利用工具查询源 IP 的白名单状态、"
    "资产归属、网段和威胁情报。如果不在白名单且确认为恶意，请根据常规安全标准"
    "提供建议。你的回答必须最终输出为 JSON 格式："
    '{"decision": "block_ip"/"ignore"/"need_human_approval", '
    '"target_ip": "xxx", "reason": "xxxx", "duration": "24h"}'
)

# 最大迭代次数：超过则强制结束，防止死循环
MAX_ITERATIONS: int = 5


def build_agent_graph(
    api_key: str,
    base_url: str = "",
    model_name: str = "claude-3-5-sonnet-20241022",
    tools: Optional[list] = None,
    system_prompt: Optional[str] = None,
    max_iterations: Optional[int] = None,
    temperature: float = 0,
    max_tokens: int = 1024,
    provider: str = "anthropic",
    extra_llm_kwargs: Optional[dict] = None,
):
    """按指定配置构建并编译 LangGraph 状态机。

    Args:
        api_key: LLM API Key。
        base_url: 自定义 Base URL（可空，留空走官方端点）。
        model_name: 模型名。
        tools: 绑定到 LLM 的工具列表；为 None 或空时使用默认内置工具。
        system_prompt: 自定义系统提示词；None 使用默认。
        max_iterations: 最大迭代轮数；None 使用默认。
        temperature: 采样温度。
        max_tokens: 最大生成 token 数。
        provider: LLM 提供商（anthropic / openai 等）。
        extra_llm_kwargs: 额外的 LLM 参数（top_p/frequency_penalty/presence_penalty/seed）。
            按 provider 过滤：Anthropic 仅支持 top_p，其余忽略并告警；OpenAI 全支持。
            None 或空字典时不传任何额外参数（按需启用模式）。

    Returns:
        编译后的 ``CompiledStateGraph``，可调用 ``ainvoke`` 异步执行。
    """
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, StateGraph
    from langgraph.prebuilt import ToolNode

    from app.agent.agent_tools import agent_tools as default_tools

    iter_limit = max_iterations if max_iterations is not None else MAX_ITERATIONS
    bound_tools = tools if tools else default_tools
    model = model_name or "claude-3-5-sonnet-20241022"
    prov = (provider or "anthropic").lower()

    logger.info(
        "构建 Agent 图: provider=%s, model=%s, base_url=%s, tools=%d, max_iter=%d",
        prov, model, base_url or "(default)", len(bound_tools), iter_limit,
    )

    # 根据 provider 选择 LLM 类
    # anthropic → ChatAnthropic（原生 API）
    # 其它（openai / 火山引擎 / Deepseek / Moonshot 等）→ ChatOpenAI（OpenAI 兼容接口）
    llm_kwargs: dict = {
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # 应用扩展参数：按 provider 过滤
    # ChatAnthropic 仅支持 top_p；ChatOpenAI 支持 top_p/frequency_penalty/presence_penalty/seed
    if extra_llm_kwargs:
        if prov == "anthropic":
            if "top_p" in extra_llm_kwargs:
                llm_kwargs["top_p"] = extra_llm_kwargs["top_p"]
            for k in ("frequency_penalty", "presence_penalty", "seed"):
                if k in extra_llm_kwargs:
                    logger.warning("Anthropic 不支持 %s，已忽略", k)
        else:
            for k in ("top_p", "frequency_penalty", "presence_penalty", "seed"):
                if k in extra_llm_kwargs:
                    llm_kwargs[k] = extra_llm_kwargs[k]

    if prov == "anthropic":
        from langchain_anthropic import ChatAnthropic
        from app.core.llm_helper import _no_proxy_http_client
        if base_url:
            llm_kwargs["anthropic_api_url"] = base_url
        llm_kwargs["http_client"] = _no_proxy_http_client(base_url)
        llm = ChatAnthropic(**llm_kwargs)
    else:
        from langchain_openai import ChatOpenAI
        from app.core.llm_helper import normalize_openai_base_url, _no_proxy_http_client
        # OpenAI 兼容接口：规范化 base_url（ChatOpenAI 会自动追加 /chat/completions，
        # 此处需确保 base_url 不含该后缀，避免 /chat/completions/chat/completions 重复）
        if base_url:
            llm_kwargs["base_url"] = normalize_openai_base_url(base_url)
        llm_kwargs["http_client"] = _no_proxy_http_client(base_url)
        llm = ChatOpenAI(**llm_kwargs)
    llm_with_tools = llm.bind_tools(bound_tools)

    tool_node = ToolNode(bound_tools)

    async def agent_node(state: AgentState) -> dict:
        """Agent 节点：调用 LLM 生成下一步消息。"""
        messages = state["messages"]
        iteration = state.get("iteration", 0)
        logger.info("[agent_node] 第 %d 轮迭代，当前消息数=%d", iteration + 1, len(messages))

        response = await llm_with_tools.ainvoke(messages)
        logger.info("[agent_node] LLM 返回，tool_calls=%s", _tool_calls(response))

        return {"messages": [response], "iteration": iteration + 1}

    def should_continue(state: AgentState) -> str:
        """条件边：判断是否继续调用工具。"""
        iteration = state.get("iteration", 0)
        if iteration >= iter_limit:
            logger.warning("达到最大迭代次数 %d，强制结束", iter_limit)
            return "end"

        messages = state["messages"]
        last_message = messages[-1]
        if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
            logger.info("[should_continue] 检测到 tool_calls，进入工具执行节点")
            return "continue"
        logger.info("[should_continue] 无 tool_calls，Agent 输出最终回答，结束")
        return "end"

    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("agent_node", agent_node)
    graph_builder.add_node("tool_executor_node", tool_node)
    graph_builder.set_entry_point("agent_node")
    graph_builder.add_conditional_edges(
        "agent_node",
        should_continue,
        {
            "continue": "tool_executor_node",
            "end": END,
        },
    )
    graph_builder.add_edge("tool_executor_node", "agent_node")

    compiled = graph_builder.compile()
    logger.info("Agent LangGraph 状态机构建完成")
    return compiled


def _msg_type(message) -> str:
    """安全获取消息类型名称，用于日志输出。"""
    return type(message).__name__


def _tool_calls(message) -> list:
    """安全提取 AIMessage 中的 tool_calls，用于日志输出。"""
    return [tc.get("name") for tc in (getattr(message, "tool_calls", None) or [])]


# 模块级单例：尝试构建默认图（基于环境变量 ANTHROPIC_API_KEY），失败时置 None。
# decision.py 会优先使用 DB 中的 LLMConfig 动态构建图；此单例仅用于无 DB 配置时的回退。
agent_graph = None
try:
    from app.config import settings as _settings  # noqa: WPS433

    if _settings.ANTHROPIC_API_KEY:
        agent_graph = build_agent_graph(api_key=_settings.ANTHROPIC_API_KEY)
    else:
        logger.info("未配置 ANTHROPIC_API_KEY，跳过默认 Agent 图构建（将使用 Mock 降级）")
except Exception as exc:  # noqa: BLE001
    logger.warning("默认 Agent 图构建失败（将使用 Mock 降级）: %s", exc)
    agent_graph = None
