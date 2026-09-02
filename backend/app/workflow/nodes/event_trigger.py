"""事件触发节点：从告警记录提取工作流输入变量。"""
import ipaddress
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.alert_event import AlertEvent
from app.models.workflow_ban import WorkflowInstance
from .base import BaseNode, NodeResult


def _parse_ip_list(raw: Any) -> list[str]:
    """src_ip 字段（JSON 数组字符串或单值）→ IP 列表。"""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    s = str(raw)
    if s.startswith("["):
        try:
            return [str(x) for x in json.loads(s)]
        except (ValueError, TypeError):
            pass
    return [s]


def _is_public_ip(ip: str) -> bool:
    """是否公网 IP（非私网/回环/链路本地/保留地址）。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast)


class EventTriggerNode(BaseNode):
    key = "event_trigger"
    name = "事件触发"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        alert = db.query(AlertEvent).filter(AlertEvent.id == instance.alert_id).first()
        if alert is None:
            return NodeResult(status="fail", action="abort", error=f"告警记录不存在: {instance.alert_id}")

        src_ips = _parse_ip_list(alert.src_ip)
        # ip 取 src_ip 第一个外网 IP，若无外网 IP 则取第一个
        public_ips = [ip for ip in src_ips if _is_public_ip(ip)]
        ip = (public_ips or src_ips or [""])[0]

        variables = {
            "ip": ip,
            "alert_id": alert.id,
            "alert_uuid": alert.uuid,
            "alert_name": alert.alert_name or "",
            "risk_level": alert.risk_level_name or "",
            "occur_timestamp": str(alert.occur_timestamp or ""),
            "alert_type": alert.threat_class or "",
            "src_country": alert.src_country or "",
        }
        ctx.update(variables)
        return NodeResult(output={"variables": variables, "src_ip_list": src_ips, "is_public": bool(public_ips)})
