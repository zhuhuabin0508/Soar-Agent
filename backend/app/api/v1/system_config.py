"""系统配置 API。

键值对存储平台级配置，支持批量读取与更新。
预置配置项：平台名称、Logo、主题色、CORS 白名单、Webhook 限流等。
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.system_config import SystemConfig
from app.models.user import User
from app.schemas.system_config import SystemConfigOut, SystemConfigUpdate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/system-config",
    tags=["system-config"],
    dependencies=[Depends(get_current_user)],
)

# 预置配置项及其默认值与描述（首次访问时自动补齐）
DEFAULT_CONFIGS: dict[str, dict[str, str]] = {
    "platform_name": {"value": "SOAR 平台", "description": "平台显示名称"},
    "logo_url": {"value": "", "description": "Logo 图片 URL"},
    "primary_color": {"value": "#6366f1", "description": "主题色（十六进制色值）"},
    "cors_origins": {
        "value": "http://localhost:8080,http://localhost:5173",
        "description": "CORS 白名单（逗号分隔）",
    },
    "webhook_rate_limit": {"value": "30", "description": "Webhook 限流（次/分钟）"},
}


@router.get("", response_model=list[SystemConfigOut])
def list_configs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "view")),
) -> list[SystemConfig]:
    """列出所有系统配置项（自动补齐缺失的预置项）。"""
    configs = db.query(SystemConfig).order_by(SystemConfig.key).all()
    existing_keys = {c.key for c in configs}

    # 补齐缺失的预置配置项
    for key, meta in DEFAULT_CONFIGS.items():
        if key not in existing_keys:
            cfg = SystemConfig(
                key=key, value=meta["value"], description=meta["description"]
            )
            db.add(cfg)
            configs.append(cfg)

    if len(configs) > len(existing_keys):
        db.commit()

    return configs


@router.put("")
def update_configs(
    body: SystemConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> dict:
    """批量更新系统配置。"""
    for key, value in body.configs.items():
        cfg = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if cfg:
            cfg.value = value
        else:
            desc = DEFAULT_CONFIGS.get(key, {}).get("description", "")
            db.add(SystemConfig(key=key, value=value, description=desc))
    db.commit()
    logger.info("系统配置批量更新: keys=%s", list(body.configs.keys()))
    return {"ok": True}


@router.get("/security")
def get_security_config(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "view")),
) -> dict:
    """获取等保安全策略配置。"""
    from app.core.security_policy import get_security_policy

    policy = get_security_policy(db)
    return {"policy": policy}


@router.put("/security")
def update_security_config(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> dict:
    """更新等保安全策略配置。

    body 为 ``{key: value}`` 字典，仅接受 ``security.*`` 前缀的键。
    """
    from app.core.security_policy import DEFAULT_SECURITY_POLICY

    updated = []
    for key, value in body.items():
        # 仅允许更新已知的安全策略键
        if key not in DEFAULT_SECURITY_POLICY:
            continue
        str_value = str(value) if not isinstance(value, bool) else ("true" if value else "false")
        cfg = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if cfg:
            cfg.value = str_value
        else:
            db.add(SystemConfig(key=key, value=str_value, description="等保安全策略"))
        updated.append(key)
    db.commit()
    logger.info("安全策略更新: keys=%s", updated)
    return {"ok": True, "updated": updated}
