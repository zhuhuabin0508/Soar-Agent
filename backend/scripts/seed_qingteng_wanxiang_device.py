"""青藤万相设备播种脚本：幂等创建"青藤万相"设备并同步全部查询类动作。

用法（在 backend 目录下，需已安装 backend 依赖 + 可连数据库）:
    python -m scripts.seed_qingteng_wanxiang_device

逻辑:
  1. 创建/更新 Device(name=青藤万相, auth_type=qingteng)：设备 api_url/账号密码
     留空待用户在设备管理页配置（青藤认证只需 username/password，见
     app/devices/action_executor.py 的 _qingteng_login）。
  2. 以 device_id + action_type 为幂等键，同步
     app/core/qingteng_wanxiang_actions.QINGTENG_WANXIANG_ACTIONS 中全部
     查询类动作（144 个）到 DeviceAction 表：
     - params_schema: 参数定义 JSON 数组
     - example_response: 返回结果字段说明 JSON 数组
  3. 重复执行安全：已有动作按 action_type 更新字段，不会重复创建；
     数据模块中已删除的动作不自动清除（避免误删用户手动添加的同前缀动作）。
"""
import json
import logging

from sqlalchemy.orm import Session

from app.core.qingteng_wanxiang_actions import QINGTENG_WANXIANG_ACTIONS
from app.database import SessionLocal
from app.models.device import Device, DeviceAction

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_qingteng_wanxiang")

# 设备唯一标识：按名称幂等（与 seed_qingteng_agent 风格一致）
_DEVICE_NAME = "青藤万相"

# 设备基础信息（凭据不在此配置，由用户在设备管理页填写后加密存储）
_DEVICE_FIELDS = dict(
    type="edr",
    vendor="青藤",
    version="v3.4.1.66",
    description="青藤万相主机自适应保护平台（外部 API 手册 v3.4.1.66）："
    "资产清点、风险发现、入侵检测、合规基线、系统审计、快速任务、主机发现、"
    "微隔离的只读查询动作集合。认证方式为青藤动态签名（登录换取 comId/jwt/signKey），"
    "由 action_executor 自动处理；设备需配置 api_url/username/password。",
    auth_type="qingteng",
    enabled=True,
    timeout=30,
    max_retries=0,
    verify_tls=False,
    tags='["青藤", "qingteng", "主机安全"]',
)


def _upsert_device(db: Session) -> Device:
    """幂等创建/更新青藤万相设备（不动用户已配置的连接凭据）。"""
    device = db.query(Device).filter(Device.name == _DEVICE_NAME).first()
    if device is None:
        device = Device(name=_DEVICE_NAME, **_DEVICE_FIELDS)
        device.status = "unconfigured"
        db.add(device)
        db.flush()
        logger.info("设备已创建: id=%s name=%s", device.id, device.name)
        return device
    for k, v in _DEVICE_FIELDS.items():
        setattr(device, k, v)
    logger.info("设备已存在，基础字段已更新: id=%s name=%s", device.id, device.name)
    return device


def _sync_actions(db: Session, device: Device) -> tuple[int, int]:
    """按 device_id + action_type 幂等同步全部查询类动作。

    Returns:
        (created, updated) 新建/更新的动作数量。
    """
    existing = {
        a.action_type: a
        for a in db.query(DeviceAction).filter(DeviceAction.device_id == device.id).all()
    }
    created = updated = 0
    for spec in QINGTENG_WANXIANG_ACTIONS:
        action = existing.get(spec["action_type"])
        if action is None:
            action = DeviceAction(device_id=device.id, action_type=spec["action_type"])
            db.add(action)
            created += 1
        else:
            updated += 1
        # 动作字段与数据模块定义保持一致（params_schema 为 JSON 数组串，
        # response_fields 说明写入 example_response 供前端/工具展示）
        action.name = spec["name"]
        action.http_method = spec["http_method"]
        action.api_path = spec["api_path"]
        action.params_schema = json.dumps(spec["params_schema"], ensure_ascii=False)
        action.headers = "{}"
        action.body_template = ""
        action.auth_type = spec["auth_type"]
        action.enabled = True
        action.description = spec["description"]
        action.category = spec["category"]
        action.risk_level = spec["risk_level"]
        action.example_response = json.dumps(
            {"fields": spec["response_fields"]}, ensure_ascii=False
        )
    return created, updated


def main() -> None:
    db: Session = SessionLocal()
    try:
        device = _upsert_device(db)
        created, updated = _sync_actions(db, device)
        db.commit()
        logger.info(
            "播种完成: device_id=%s, 动作新增 %d 个 / 更新 %d 个（共 %d 个查询类动作）",
            device.id, created, updated, len(QINGTENG_WANXIANG_ACTIONS),
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("播种失败: %s", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
