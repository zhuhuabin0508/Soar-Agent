"""动作分支节点（路由）：按智能体 action + need_confirm 分流。

- action=monitor → 持续监控节点
- action=ban 且 need_confirm=false → 直接封禁节点
- action=ban 且 need_confirm=true → 审批工单节点
- 其余未知动作 → 持续监控（保守处置）
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import WorkflowInstance
from .base import BaseNode, NodeResult


class ActionBranchNode(BaseNode):
    key = "action_branch"
    name = "动作分支"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        decision = ctx.get("agent_decision") or {}
        action = str(decision.get("action") or "").lower()
        need_confirm = bool(decision.get("need_confirm"))

        if action == "ban" and not need_confirm:
            next_key, branch = "direct_ban", "直接封禁"
        elif action == "ban" and need_confirm:
            next_key, branch = "approval_ticket", "人工审批"
        else:
            next_key, branch = "monitor_log", "持续监控"

        ctx["action_branch"] = branch
        return NodeResult(
            output={"action": action, "need_confirm": need_confirm, "branch": branch},
            next_key=next_key,
        )
