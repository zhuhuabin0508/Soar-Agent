"""已封禁处理节点：记录 already_banned 状态并写审计日志，进结果同步。"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import WorkflowInstance
from app.workflow.audit import write_audit
from .base import BaseNode, NodeResult


class AlreadyBannedNode(BaseNode):
    key = "already_banned"
    name = "已封禁处理"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        ip = str(ctx.get("ip") or "")
        ctx["final_result"] = "already_banned"
        write_audit(
            db, action="workflow_node", resource_type="workflow_instance", resource_id=instance.id,
            detail={"node": self.key, "ip": ip, "result": "already_banned"},
        )
        return NodeResult(output={"ip": ip, "result": "already_banned"})
