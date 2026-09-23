"""Agent 运行时统一入口（invoke_agent / invoke_agent_sse）。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, AsyncIterator, Optional

from sqlalchemy.orm import Session

from app.agent.prompt_assembler import assemble_system_prompt
from app.models.agent import Agent
from app.workflow.agent_client import REQUIRED_FIELDS as BAN_RISK_REQUIRED_FIELDS

logger = logging.getLogger(__name__)

OUTPUT_MODE_CHAT = "chat"
OUTPUT_MODE_SOC_DECISION = "soc_decision"
OUTPUT_MODE_BAN_RISK_ANALYZE = "ban_risk_analyze"


@dataclass
class RunContext:
    agent_id: int
    engine: str
    channel: str
    output_mode: str
    user_id: Optional[int] = None
    stream: bool = False


@dataclass
class AgentInvokeResult:
    response: str = ""
    messages: list = field(default_factory=list)
    logs: list = field(default_factory=list)
    decision: Optional[dict] = None
    raw: Optional[dict] = None


def resolve_runtime_user(db: Session):
    from app.models.user import User

    try:
        user = db.query(User).first()
        if user is not None:
            return user
    except Exception:  # noqa: BLE001
        pass
    return SimpleNamespace(id=0, username="runtime-system")


def resolve_engine(agent: Agent) -> str:
    raw = (getattr(agent, "engine", None) or "hermes").lower()
    if raw in ("langgraph", "legacy"):
        logger.warning(
            "agent_id=%s engine=%s deprecated, routing to hermes",
            agent.id,
            raw,
        )
        return "hermes"
    return "hermes"


def adapt_soc_decision(content: str, src_ip: str = "unknown") -> dict:
    from app.agent.decision import _parse_action_decision_from_content

    return _parse_action_decision_from_content(content, src_ip)


def adapt_ban_risk_analyze(content: str) -> dict:
    from app.agent.decision import _extract_json_object
    from app.workflow.agent_client import AgentCallError

    candidate = _extract_json_object(content)
    if candidate is None:
        candidate = (content or "").strip()
    if not candidate:
        raise AgentCallError("响应为空，无法解析 ban_risk_analyze JSON")
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AgentCallError(f"响应 JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentCallError("响应不是 JSON 对象")
    missing = [f for f in BAN_RISK_REQUIRED_FIELDS if f not in data]
    if missing:
        raise AgentCallError(f"响应缺少必填字段: {', '.join(missing)}")
    return data


def _log_invoke(ctx: RunContext) -> None:
    logger.info(
        "invoke_agent agent_id=%s engine=%s channel=%s output_mode=%s stream=%s user_id=%s",
        ctx.agent_id,
        ctx.engine,
        ctx.channel,
        ctx.output_mode,
        ctx.stream,
        ctx.user_id,
    )


def _load_agent(db: Session, agent_id: int | None, agent: Agent | None) -> Agent:
    if agent is not None:
        return agent
    if agent_id is None:
        raise ValueError("agent_id or agent is required")
    row = db.query(Agent).filter(Agent.id == agent_id).first()
    if row is None:
        raise ValueError(f"Agent not found: {agent_id}")
    return row


def _normalize_user(user):
    if user is not None:
        return user
    return SimpleNamespace(id=0, username="runtime-system")


def _parse_input(input_data: str | dict) -> tuple[str, dict]:
    if isinstance(input_data, dict):
        return json.dumps(input_data, ensure_ascii=False), input_data
    text = input_data or ""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return text, parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return text, {"input": text}


def _resolve_system_prompt(
    db: Session,
    agent: Agent,
    override,
    *,
    for_decision: bool = False,
) -> str | None:
    if override is not None and getattr(override, "system_prompt", None) is not None:
        return override.system_prompt
    if for_decision:
        return assemble_system_prompt(db, agent, allow_none=True)
    return assemble_system_prompt(
        db,
        agent,
        fallback_prompt="你是一个智能助手，请根据用户输入给出有帮助的回答。",
    )


def build_hermes_executor(
    db: Session,
    agent: Agent,
    user,
    *,
    override=None,
    system_prompt: str | None = None,
):
    from app.agent.hermes import HermesAgentExecutor

    if system_prompt is None:
        system_prompt = _resolve_system_prompt(db, agent, override)
    return HermesAgentExecutor(
        db=db,
        agent=agent,
        user=_normalize_user(user),
        override=override,
        system_prompt=system_prompt,
    )


async def _collect_hermes_text(executor, user_message: str, session_id: str) -> str:
    final_text = ""
    async for event in executor.run(user_message, session_id=session_id):
        etype = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
        if etype == "done":
            final_text = (
                event.get("content", "")
                if isinstance(event, dict)
                else getattr(event, "content", "")
            ) or final_text
        elif etype == "error":
            msg = (
                event.get("message", "hermes error")
                if isinstance(event, dict)
                else getattr(event, "message", "hermes error")
            )
            raise RuntimeError(msg)
    return final_text


async def invoke_agent(
    *,
    db: Session,
    agent_id: int | None = None,
    agent: Agent | None = None,
    input: str | dict,
    user,
    channel: str = "api",
    stream: bool = False,
    output_mode: str = OUTPUT_MODE_CHAT,
    inline_config: dict | None = None,
    override=None,
    session_id: str = "default",
    history: list[dict] | None = None,
) -> AgentInvokeResult:
    if stream:
        raise ValueError("stream=True 请使用 invoke_agent_sse()")
    if inline_config is not None:
        logger.warning("invoke_agent inline_config 过渡路径尚未实现，忽略 inline_config")

    agent = _load_agent(db, agent_id, agent)
    engine = resolve_engine(agent)
    user = _normalize_user(user)
    user_id = getattr(user, "id", None)

    ctx = RunContext(
        agent_id=agent.id,
        engine=engine,
        channel=channel,
        output_mode=output_mode,
        user_id=user_id,
        stream=False,
    )
    _log_invoke(ctx)

    user_message, payload = _parse_input(input)
    for_decision = output_mode in (OUTPUT_MODE_SOC_DECISION, OUTPUT_MODE_BAN_RISK_ANALYZE)
    system_prompt = _resolve_system_prompt(db, agent, override, for_decision=for_decision)
    executor = build_hermes_executor(
        db, agent, user, override=override, system_prompt=system_prompt
    )
    if history:
        executor.load_history(history)

    final_text = await _collect_hermes_text(executor, user_message, session_id)
    new_messages = executor.get_new_messages()

    if output_mode == OUTPUT_MODE_SOC_DECISION:
        src_ip = (
            payload.get("src_ip")
            or payload.get("ip")
            or payload.get("target_ip")
            or "unknown"
        )
        decision = adapt_soc_decision(final_text, str(src_ip))
        return AgentInvokeResult(
            response=final_text,
            messages=new_messages,
            decision=decision,
            raw={**decision, "messages": new_messages, "logs": []},
        )

    if output_mode == OUTPUT_MODE_BAN_RISK_ANALYZE:
        decision = adapt_ban_risk_analyze(final_text)
        return AgentInvokeResult(
            response=final_text,
            messages=new_messages,
            decision=decision,
            raw=decision,
        )

    return AgentInvokeResult(
        response=final_text,
        messages=new_messages,
        raw={"response": final_text, "messages": new_messages},
    )


async def invoke_agent_sse(
    *,
    db: Session,
    agent_id: int | None = None,
    agent: Agent | None = None,
    input: str | dict,
    user,
    channel: str = "api",
    override=None,
    session_id: str = "default",
    history: list[dict] | None = None,
    executor_holder: list | None = None,
) -> AsyncIterator[str]:
    agent = _load_agent(db, agent_id, agent)
    engine = resolve_engine(agent)
    user = _normalize_user(user)
    user_id = getattr(user, "id", None)

    ctx = RunContext(
        agent_id=agent.id,
        engine=engine,
        channel=channel,
        output_mode=OUTPUT_MODE_CHAT,
        user_id=user_id,
        stream=True,
    )
    _log_invoke(ctx)

    user_message, _payload = _parse_input(input)
    system_prompt = _resolve_system_prompt(db, agent, override)
    executor = build_hermes_executor(
        db, agent, user, override=override, system_prompt=system_prompt
    )
    if history:
        executor.load_history(history)
    if executor_holder is not None:
        executor_holder.append(executor)

    from app.agent.hermes.sse import sse_stream

    async for chunk in sse_stream(executor, user_message, session_id=session_id):
        yield chunk
