"""结果同步节点：将最终状态同步到封禁工作台并结束实例。

- 已封禁 → ban_records 已在封禁节点置 active，本节点确认终态 + legacy 表
- 待审批 → ban_records 保持 pending_approval（审批节点已写）
- 持续监控 / 已封禁(重复) / 已取消 → 按 ctx.final_result 落终态
实例置 success，写审计日志。
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import BanRecord, WorkflowInstance
from app.workflow.audit import write_audit
from .base import BaseNode, NodeResult

# final_result → 工作台状态映射（非封禁终态收敛 ban_records）
_FINAL_TO_RECORD_STATUS = {
    "monitoring": "cancelled",       # 持续监控：取消待审批记录
    "already_banned": "cancelled",   # 重复封禁：无新记录
}


class ResultSyncNode(BaseNode):
    key = "result_sync"
    name = "结果同步"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        ip = str(ctx.get("ip") or "")
        final = str(ctx.get("final_result") or "")

        # 同步工作台记录终态（封禁节点已写 active，此处收敛其余分支）
        record_status = _FINAL_TO_RECORD_STATUS.get(final)
        if record_status is not None:
            record = db.query(BanRecord).filter(
                BanRecord.source_instance_id == instance.id, BanRecord.ip == ip,
            ).first()
            if record is not None and record.status == "pending_approval":
                record.status = record_status
                db.commit()

        output = {
            "ip": ip,
            "final_result": final,
            "synced": True,
            "ban_record_id": ctx.get("ban_record_id"),
        }
        write_audit(
            db, action="workflow_node", resource_type="workflow_instance", resource_id=instance.id,
            detail={"node": self.key, "ip": ip, "final_result": final},
        )
        # 实例完成
        from app.core.timezone import beijing_now
        instance.status = "success"
        instance.final_result = final or "monitoring"
        instance.finished_at = beijing_now()
        db.commit()
        return NodeResult(output=output)
