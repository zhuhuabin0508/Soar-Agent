"""异常处理节点：记录错误详情，通知运营人员，实例置 error。"""
from typing import Any

from sqlalchemy.orm import Session

from app.core.timezone import beijing_now
from app.models.workflow_ban import WorkflowInstance
from app.workflow.audit import write_audit
from app.workflow.notify import notify_ops
from .base import BaseNode, NodeResult


class ErrorHandlerNode(BaseNode):
    key = "error_handler"
    name = "异常处理"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        error = str(ctx.get("last_error") or "未知错误")
        ip = str(ctx.get("ip") or "")
        instance.status = "error"
        instance.final_result = "error"
        instance.error_msg = error[:2000]
        instance.finished_at = beijing_now()
        db.commit()

        write_audit(
            db, action="workflow_node", resource_type="workflow_instance", resource_id=instance.id,
            detail={"node": self.key, "ip": ip, "error": error}, result="failed",
        )
        notify_ops(
            db, f"封禁工作流实例 #{instance.id} 异常",
            f"IP {ip} 的工作流执行失败：{error[:300]}",
        )
        return NodeResult(status="fail", output={"ip": ip, "error": error}, error=error)
