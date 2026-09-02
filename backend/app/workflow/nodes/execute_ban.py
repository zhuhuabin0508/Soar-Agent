"""执行封禁节点：审批确认后执行封禁（复用 ban_executor 公共逻辑）。"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import WorkflowInstance
from .ban_executor import execute_ban
from .base import BaseNode, NodeResult


class ExecuteBanNode(BaseNode):
    key = "execute_ban"
    name = "执行封禁"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        ctx["final_result"] = "banned"
        return execute_ban(db, instance, ctx, self.key)
