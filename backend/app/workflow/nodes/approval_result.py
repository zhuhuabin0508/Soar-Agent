"""审批结果判断节点（路由）：审批回调/超时后恢复执行时评估工单状态。

- approved → 执行封禁节点
- rejected / timeout → 持续监控节点（驳回原因记录；超时默认驳回并已通知运营）
- escalated → 实例终止（escalated，转人工调查）
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import ApprovalTicket, WorkflowInstance
from .base import BaseNode, NodeResult


class ApprovalResultNode(BaseNode):
    key = "approval_result"
    name = "审批结果判断"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        ticket = (
            db.query(ApprovalTicket)
            .filter(ApprovalTicket.workflow_instance_id == instance.id)
            .order_by(ApprovalTicket.id.desc())
            .first()
        )
        if ticket is None:
            return NodeResult(status="fail", action="error", error="审批工单不存在")

        ctx["approval_status"] = ticket.status
        ctx["approval_comment"] = ticket.approval_comment or ""
        output = {
            "ticket_id": ticket.id,
            "ticket_status": ticket.status,
            "approver": ticket.approver or "",
            "comment": ticket.approval_comment or "",
        }
        if ticket.status == "approved":
            return NodeResult(output=output, next_key="execute_ban")
        if ticket.status in ("rejected", "timeout"):
            # 驳回/超时 → 持续监控（超时在定时任务中已按默认驳回处理并通知运营）
            return NodeResult(output=output, next_key="monitor_log")
        if ticket.status == "escalated":
            # 升级转人工调查：实例终止
            ctx["final_result"] = "escalated"
            return NodeResult(output=output, action="abort")
        return NodeResult(status="fail", action="error", error=f"工单状态异常: {ticket.status}")
