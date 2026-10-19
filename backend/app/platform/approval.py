"""Agent 高危工具的人工确认工单（复用 approval_tickets / 审批中心）。

与工作流审批的区别：
- kind="agent_tool"，无工作流实例（workflow_instance_id=0）+ 无 IP（ip=""）；
- 携带工具名 / 参数 / agent / session / 去重键；
- 审批通过后由 6b 的 Celery 任务执行工具（本步只负责建单与去重）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.timezone import beijing_now

DEDUP_WINDOW_MINUTES = 30

KIND_AGENT_TOOL = "agent_tool"


def make_dedup_key(*, tool_name: str, arguments: dict | None,
                   agent_id: Optional[int], session_id: Optional[str]) -> str:
    """去重键 = hash(工具名 + 参数 + agent_id + session_id)。"""
    raw = "|".join([
        tool_name or "",
        json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False),
        str(agent_id or 0),
        session_id or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def create_tool_approval(
    db: Session,
    *,
    tool_name: str,
    arguments: dict | None,
    danger_level: str,
    agent_id: Optional[int] = None,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    window_minutes: int = DEDUP_WINDOW_MINUTES,
):
    """为一次 Agent 高危工具调用创建（或复用）审批工单。返回 ApprovalTicket。"""
    from app.models.workflow_ban import ApprovalTicket

    key = make_dedup_key(tool_name=tool_name, arguments=arguments,
                         agent_id=agent_id, session_id=session_id)

    cutoff = beijing_now() - timedelta(minutes=window_minutes)
    existing = (
        db.query(ApprovalTicket)
        .filter(
            ApprovalTicket.kind == KIND_AGENT_TOOL,
            ApprovalTicket.dedup_key == key,
            ApprovalTicket.status == "pending",
            ApprovalTicket.created_at >= cutoff,
        )
        .order_by(ApprovalTicket.id.desc())
        .first()
    )
    if existing is not None:
        return existing

    ticket = ApprovalTicket(
        kind=KIND_AGENT_TOOL,
        workflow_instance_id=0,      # 哨兵：非工作流工单
        ip="",                       # 哨兵：非按 IP 封禁
        status="pending",
        tool_name=tool_name,
        tool_arguments=json.dumps(arguments or {}, ensure_ascii=False),
        agent_id=agent_id,
        session_id=session_id,
        requested_by=user_id,
        dedup_key=key,
        alert_summary=f"Agent 高危工具确认：{tool_name}（danger={danger_level}）",
        deadline=beijing_now() + timedelta(hours=24),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket
