"""参数校验节点：校验 IP 为有效 IPv4/IPv6；空/非法时实例直接 skipped。"""
import ipaddress
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow_ban import WorkflowInstance
from .base import BaseNode, NodeResult


class ParamValidateNode(BaseNode):
    key = "param_validate"
    name = "参数校验"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        ip = str(ctx.get("ip") or "").strip()
        if not ip:
            return NodeResult(
                status="skipped", action="abort",
                output={"ip": "", "valid": False},
                error="IP 为空：源数据未提取到有效源 IP，实例跳过",
            )
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return NodeResult(
                status="skipped", action="abort",
                output={"ip": ip, "valid": False},
                error=f"IP 非法: {ip} 不是有效的 IPv4/IPv6 地址，实例跳过",
            )
        ctx["ip_version"] = 4 if addr.version == 4 else 6
        return NodeResult(output={"ip": ip, "valid": True, "version": ctx["ip_version"]})
