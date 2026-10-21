"""工单 SLA 目标配置 API。

- GET /ticket-config/sla：读取当前配置（含默认值供参照）
- PUT /ticket-config/sla：保存配置（每优先级响应/解决时限，正整数或留空=不限）

权限：``ticket_config:view`` 可查看，``ticket_config:edit`` 可修改，写审计日志。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.ticket_sla import (
    DEFAULT_SLA_CONFIG,
    PRIORITIES,
    get_sla_config,
    normalize_sla_config,
    save_sla_config,
)
from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.user import User
from app.workflow.audit import write_audit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ticket-config/sla",
    tags=["ticket-config"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("ticket_config", "view")),
    ],
)

PRIORITY_LABELS = {"critical": "紧急", "high": "高危", "medium": "中危", "low": "低危"}


class SlaConfigUpdate(BaseModel):
    config: dict


@router.get("")
def get_sla(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ticket_config", "view")),
) -> dict:
    """读取 SLA 目标配置。"""
    return {
        "config": get_sla_config(db),
        "defaults": {p: dict(v) for p, v in DEFAULT_SLA_CONFIG.items()},
        "priority_labels": PRIORITY_LABELS,
    }


@router.put("")
def update_sla(
    body: SlaConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ticket_config", "edit")),
) -> dict:
    """保存 SLA 目标配置（正整数或留空=不限）。"""
    _, errors = normalize_sla_config(body.config)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))
    unknown = [k for k in (body.config or {}) if k not in PRIORITIES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知优先级: {', '.join(map(str, unknown))}")

    saved = save_sla_config(db, body.config)
    write_audit(
        db, action="ticket_sla_update", resource_type="ticket_config", resource_id=None,
        detail={"config": saved},
        operator=current_user.username, user_id=current_user.id,
    )
    logger.info("SLA 配置更新: %s, operator=%s", saved, current_user.username)
    return {"ok": True, "config": saved}
