"""智能体研判节点：调用 IP 风险研判智能体，解析并校验结构化响应。

调用失败（网络/超时/结构缺失）转异常处理节点，并计入熔断统计。
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import WorkflowInstance
from app.workflow import agent_client
from app.workflow.trigger import record_agent_outcome
from .base import BaseNode, NodeResult


class AgentAnalyzeNode(BaseNode):
    key = "agent_analyze"
    name = "智能体研判"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        ip = str(ctx.get("ip") or "")
        alert_context = {
            "alert_name": ctx.get("alert_name") or "",
            "risk_level": ctx.get("risk_level") or "",
            "threat_class": ctx.get("alert_type") or "",
            "occur_timestamp": ctx.get("occur_timestamp") or "",
            "src_country": ctx.get("src_country") or "",
        }
        try:
            decision = agent_client.analyze_ip_risk(
                db, ip, alert_context, instance_id=instance.id, node_key=self.key,
            )
        except agent_client.AgentCallError as exc:
            # 熔断统计：连续失败计数 +1（成功在下方清零）
            record_agent_outcome(ok=False)
            return NodeResult(
                status="fail", action="error",
                output={"ip": ip, "request_context": alert_context},
                error=str(exc),
            )

        # 研判成功：清零连续失败计数 + 完整落库供审计复盘
        record_agent_outcome(ok=True)
        ctx["agent_decision"] = decision
        return NodeResult(output={
            "ip": ip,
            "request_context": alert_context,
            "decision": decision,
        })
