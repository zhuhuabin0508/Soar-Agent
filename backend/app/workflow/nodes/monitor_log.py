"""持续监控记录节点：写入监控日志表，可选通知安全运营人员。"""
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import MonitorLog, WorkflowInstance
from app.workflow.notify import notify_ops
from .base import BaseNode, NodeResult


class MonitorLogNode(BaseNode):
    key = "monitor_log"
    name = "持续监控记录"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        ip = str(ctx.get("ip") or "")
        decision = ctx.get("agent_decision") or {}
        log = MonitorLog(
            ip=ip,
            risk_level=str(decision.get("risk_level") or ""),
            advice=str(decision.get("monitoring_advice") or ""),
            reasons=json.dumps(decision.get("reasons") or [], ensure_ascii=False),
            instance_id=instance.id,
        )
        db.add(log)
        db.commit()

        # 中高危监控通知运营（低危静默）
        if str(decision.get("risk_level") or "") in ("严重", "高危", "中危"):
            notify_ops(
                db, f"IP {ip} 已加入持续监控",
                f"告警「{ctx.get('alert_name') or ''}」研判建议持续监控：{decision.get('monitoring_advice') or ''}",
            )

        ctx["final_result"] = "monitoring"
        ctx["monitor_log_id"] = log.id
        return NodeResult(output={"ip": ip, "monitor_log_id": log.id, "advice": decision.get("monitoring_advice")})
