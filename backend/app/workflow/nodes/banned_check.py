"""已封禁判断节点（路由）：is_banned=true → 已封禁处理，否则 → 动作分支。"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import WorkflowInstance
from .base import BaseNode, NodeResult


class BannedCheckNode(BaseNode):
    key = "banned_check"
    name = "已封禁判断"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        decision = ctx.get("agent_decision") or {}
        is_banned = bool(decision.get("is_banned"))
        ctx["is_banned"] = is_banned
        return NodeResult(
            output={"is_banned": is_banned},
            next_key="already_banned" if is_banned else "action_branch",
        )
