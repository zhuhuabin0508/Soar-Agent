"""审批通过后的 Agent 高危工具执行任务（阶段 6b）。"""
from __future__ import annotations

import asyncio
import json

from app.core.celery_app import celery_app
from app.database import SessionLocal


@celery_app.task(
    name="execute_approved_tool",
    soft_time_limit=120,
    time_limit=180,
)
def execute_approved_tool(ticket_id: int) -> dict:
    """执行一张已批准的 agent_tool 工单对应的高危工具调用。"""
    from app.models.workflow_ban import ApprovalTicket
    from app.platform.tool_runtime import invoke_tool

    db = SessionLocal()
    try:
        ticket = db.query(ApprovalTicket).filter(ApprovalTicket.id == ticket_id).first()
        if ticket is None or (ticket.kind or "") != "agent_tool":
            return {"ok": False, "error": "工单不存在或非 agent_tool"}
        if ticket.status != "approved":
            return {"ok": False, "error": f"工单状态非 approved: {ticket.status}"}

        try:
            args = json.loads(ticket.tool_arguments or "{}")
        except Exception:  # noqa: BLE001
            args = {}

        inv = asyncio.run(invoke_tool(
            ticket.tool_name, args, db=db,
            agent_id=ticket.agent_id,
            verify=False,                     # 人工已确认
            approved_ticket_id=ticket.id,
        ))

        payload = {"ok": inv.ok, "error": inv.error, "content": inv.content}
        try:
            ticket.result = json.dumps(payload, ensure_ascii=False)[:8000]
        except Exception:  # noqa: BLE001
            ticket.result = json.dumps({"ok": inv.ok, "error": inv.error})[:8000]
        db.commit()
        return {"ok": inv.ok, "ticket_id": ticket.id}
    finally:
        db.close()
