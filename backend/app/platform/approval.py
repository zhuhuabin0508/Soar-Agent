"""Agent 高危工具的对话内确认。

对话弹出确认 → 当前用户确认/拒绝 → 当场执行或取消。
ApprovalTicket(kind=agent_tool) 仅作审计与防重放，不进入工作台审批中心。
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.timezone import beijing_now

logger = logging.getLogger(__name__)

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


def _load_agent_tool_ticket(db: Session, ticket_id: int, *, agent_id: int):
    from app.models.workflow_ban import ApprovalTicket

    ticket = db.query(ApprovalTicket).filter(ApprovalTicket.id == ticket_id).first()
    if ticket is None:
        raise ValueError("确认工单不存在")
    if (ticket.kind or "") != KIND_AGENT_TOOL:
        raise ValueError("非 Agent 工具确认工单")
    if ticket.agent_id is not None and int(ticket.agent_id) != int(agent_id):
        raise ValueError("工单与当前智能体不匹配")
    return ticket


async def confirm_and_execute_tool(
    db: Session,
    *,
    ticket_id: int,
    agent_id: int,
    user,
) -> dict[str, Any]:
    """对话内确认：当前用户批准后当场执行工具（一次性凭据）。"""
    from app.workflow.audit import write_audit
    from app.platform.tool_runtime import invoke_tool

    ticket = _load_agent_tool_ticket(db, ticket_id, agent_id=agent_id)
    if ticket.status != "pending":
        raise ValueError(f"工单已处理（{ticket.status}），不可重复确认")
    if ticket.result is not None:
        raise ValueError("工单已执行过，不可重复确认")

    ticket.status = "approved"
    ticket.approver = getattr(user, "username", None) or str(getattr(user, "id", ""))
    ticket.approval_comment = "对话内确认"
    ticket.approved_at = beijing_now()
    ticket.result = json.dumps({"status": "executing"}, ensure_ascii=False)
    db.commit()

    try:
        args = json.loads(ticket.tool_arguments or "{}")
    except Exception:  # noqa: BLE001
        args = {}

    inv = await invoke_tool(
        ticket.tool_name,
        args,
        db=db,
        agent_id=ticket.agent_id or agent_id,
        user=user,
        verify=False,
        approved_ticket_id=ticket.id,
    )
    payload = {
        "ok": inv.ok,
        "error": inv.error,
        "content": inv.content,
        "raw_content": inv.raw_content,
    }
    try:
        ticket.result = json.dumps(payload, ensure_ascii=False, default=str)[:8000]
    except Exception:  # noqa: BLE001
        ticket.result = json.dumps({"ok": inv.ok, "error": inv.error})[:8000]
    ticket.result_delivered = False
    db.commit()

    try:
        write_audit(
            db,
            action="tool_confirm",
            resource_type="approval_ticket",
            resource_id=ticket.id,
            detail={
                "result": "approved",
                "tool_name": ticket.tool_name,
                "agent_id": agent_id,
                "ok": inv.ok,
            },
            operator=ticket.approver,
            user_id=getattr(user, "id", None),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("写工具确认审计失败: %s", exc)

    return {
        "ok": inv.ok,
        "ticket_id": ticket.id,
        "tool_name": ticket.tool_name,
        "approver": ticket.approver,
        "decision": "approved",
        "result": payload,
    }


def reject_tool_confirmation(
    db: Session,
    *,
    ticket_id: int,
    agent_id: int,
    user,
    comment: str = "",
) -> dict[str, Any]:
    """对话内拒绝：记录当前用户，不执行工具。"""
    from app.workflow.audit import write_audit

    ticket = _load_agent_tool_ticket(db, ticket_id, agent_id=agent_id)
    if ticket.status != "pending":
        raise ValueError(f"工单已处理（{ticket.status}），不可重复操作")

    ticket.status = "rejected"
    ticket.approver = getattr(user, "username", None) or str(getattr(user, "id", ""))
    ticket.approval_comment = comment or "对话内拒绝"
    ticket.approved_at = beijing_now()
    payload = {
        "ok": False,
        "status": "rejected",
        "comment": ticket.approval_comment,
        "approver": ticket.approver,
    }
    ticket.result = json.dumps(payload, ensure_ascii=False)
    ticket.result_delivered = False
    db.commit()

    try:
        write_audit(
            db,
            action="tool_reject",
            resource_type="approval_ticket",
            resource_id=ticket.id,
            detail={
                "result": "rejected",
                "tool_name": ticket.tool_name,
                "agent_id": agent_id,
                "comment": ticket.approval_comment,
            },
            operator=ticket.approver,
            user_id=getattr(user, "id", None),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("写工具拒绝审计失败: %s", exc)

    return {
        "ok": True,
        "ticket_id": ticket.id,
        "tool_name": ticket.tool_name,
        "approver": ticket.approver,
        "decision": "rejected",
        "result": payload,
    }
