"""工作流审计辅助：节点执行/智能体调用/审批/封解封操作统一写审计日志。"""
import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def write_audit(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: Any,
    detail: Optional[dict] = None,
    *,
    operator: str = "system",
    ip_address: str = "",
    result: str = "success",
    user_id: Optional[int] = None,
    commit: bool = True,
) -> None:
    """写一条审计日志（失败仅记录，不影响主流程）。

    Args:
        action: 操作类型，如 workflow_node / workflow_trigger / approval / ban / unban。
        resource_type: 资源类型（workflow_instance / approval_ticket / ban_record 等）。
        resource_id: 资源 ID。
        detail: 操作详情 JSON。
        operator: 操作人（系统节点为 "system"，人工操作为账号名）。
        ip_address: 来源 IP（人工操作记录；系统操作为空）。
    """
    try:
        db.add(AuditLog(
            user_id=user_id,
            username=operator,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            detail=json.dumps(detail or {}, ensure_ascii=False, default=str),
            ip_address=ip_address or "",
            result=result,
        ))
        if commit:
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("审计日志写入失败: action=%s resource=%s", action, resource_id)
