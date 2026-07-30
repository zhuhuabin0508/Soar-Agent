"""安全设备与设备动作 CRUD 路由。

提供设备管理（防火墙/WAF/IPS/EDR等）与动作配置的 CRUD 接口，
并支持动作连通性测试：实际调用设备 API 返回结果。
"""
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.device import Device, DeviceAction
from app.schemas.common import to_dict, to_dict_list

logger = logging.getLogger(__name__)

# 读操作：仅需登录；写操作：要求 admin 角色
router = APIRouter(
    prefix="/devices",
    tags=["devices"],
)


# ============ Pydantic 请求体 ============

class DeviceBase(BaseModel):
    """设备创建/更新请求体。"""

    name: str = Field(..., description="设备名称")
    type: str = Field("firewall", description="设备类型: firewall/waf/ips/ids/edr/soar/custom")
    vendor: str = Field("", description="厂商")
    api_url: str = Field("", description="设备 API 基地址")
    api_key: str = Field("", description="API Key 或 Token")
    username: str = Field("", description="用户名（Basic Auth 时用）")
    password: str = Field("", description="密码（Basic Auth 时用）")
    enabled: bool = Field(True, description="是否启用")
    description: str = Field("", description="设备描述")


class DeviceActionBase(BaseModel):
    """设备动作创建/更新请求体。"""

    name: str = Field(..., description="动作名称，如 封禁IP")
    action_type: str = Field("custom", description="动作类型: block_ip/unblock_ip/quarantine_host/isolate_endpoint/add_ioc/delete_ioc/custom")
    http_method: str = Field("POST", description="HTTP 方法: GET/POST/PUT/DELETE/PATCH")
    api_path: str = Field("", description="API 路径（拼在 api_url 后）")
    params_schema: str = Field("[]", description="参数定义 JSON 数组")
    headers: str = Field("{}", description="额外请求头 JSON 对象")
    body_template: str = Field("", description="请求体模板（含 {{param}} 占位符）")
    auth_type: str = Field("api_key", description="认证方式: api_key/basic/bearer/none")
    enabled: bool = Field(True, description="是否启用")
    description: str = Field("", description="动作描述")


class ActionTestRequest(BaseModel):
    """动作测试请求体。"""

    params: dict = Field(default_factory=dict, description="测试参数键值对")


# ============ 设备 CRUD ============

@router.get("", dependencies=[Depends(get_current_user)])
def list_devices(db: Session = Depends(get_db)) -> list[dict]:
    """列出所有安全设备。"""
    logger.info("查询设备列表")
    devices = db.query(Device).order_by(Device.created_at.desc()).all()
    return to_dict_list(devices)


@router.post("", status_code=201, dependencies=[Depends(require_role("admin"))])
def create_device(body: DeviceBase, db: Session = Depends(get_db)) -> dict:
    """创建安全设备。"""
    logger.info("创建设备: name=%s, type=%s", body.name, body.type)
    device = Device(
        name=body.name,
        type=body.type,
        vendor=body.vendor,
        api_url=body.api_url,
        api_key=body.api_key,
        username=body.username,
        password=body.password,
        enabled=body.enabled,
        description=body.description,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    logger.info("设备已创建: id=%s", device.id)
    return to_dict(device)


@router.put("/{device_id}", dependencies=[Depends(require_role("admin"))])
def update_device(device_id: int, body: DeviceBase, db: Session = Depends(get_db)) -> dict:
    """更新安全设备。"""
    logger.info("更新设备: id=%s", device_id)
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    device.name = body.name
    device.type = body.type
    device.vendor = body.vendor
    device.api_url = body.api_url
    device.api_key = body.api_key
    device.username = body.username
    device.password = body.password
    device.enabled = body.enabled
    device.description = body.description
    db.commit()
    db.refresh(device)
    logger.info("设备已更新: id=%s", device.id)
    return to_dict(device)


@router.delete("/{device_id}", dependencies=[Depends(require_role("admin"))])
def delete_device(device_id: int, db: Session = Depends(get_db)) -> dict:
    """删除安全设备（同时级联删除其下所有动作）。"""
    logger.info("删除设备: id=%s", device_id)
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    # 级联删除该设备下所有动作
    db.query(DeviceAction).filter(DeviceAction.device_id == device_id).delete()
    db.delete(device)
    db.commit()
    logger.info("设备已删除: id=%s", device_id)
    return {"ok": True}


# ============ 设备动作 CRUD ============

@router.get("/{device_id}/actions", dependencies=[Depends(get_current_user)])
def list_device_actions(device_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """列出指定设备的所有动作。"""
    logger.info("查询设备动作列表: device_id=%s", device_id)
    if db.query(Device).filter(Device.id == device_id).first() is None:
        raise HTTPException(status_code=404, detail="Device not found")
    actions = (
        db.query(DeviceAction)
        .filter(DeviceAction.device_id == device_id)
        .order_by(DeviceAction.created_at.desc())
        .all()
    )
    return to_dict_list(actions)


@router.post("/{device_id}/actions", status_code=201, dependencies=[Depends(require_role("admin"))])
def create_device_action(
    device_id: int, body: DeviceActionBase, db: Session = Depends(get_db)
) -> dict:
    """为指定设备创建动作。"""
    logger.info("创建设备动作: device_id=%s, name=%s", device_id, body.name)
    if db.query(Device).filter(Device.id == device_id).first() is None:
        raise HTTPException(status_code=404, detail="Device not found")
    action = DeviceAction(
        device_id=device_id,
        name=body.name,
        action_type=body.action_type,
        http_method=body.http_method,
        api_path=body.api_path,
        params_schema=body.params_schema,
        headers=body.headers,
        body_template=body.body_template,
        auth_type=body.auth_type,
        enabled=body.enabled,
        description=body.description,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    logger.info("设备动作已创建: id=%s", action.id)
    return to_dict(action)


@router.put(
    "/{device_id}/actions/{action_id}",
    dependencies=[Depends(require_role("admin"))],
)
def update_device_action(
    device_id: int, action_id: int, body: DeviceActionBase, db: Session = Depends(get_db)
) -> dict:
    """更新设备动作。"""
    logger.info("更新设备动作: device_id=%s, action_id=%s", device_id, action_id)
    action = (
        db.query(DeviceAction)
        .filter(DeviceAction.id == action_id, DeviceAction.device_id == device_id)
        .first()
    )
    if action is None:
        raise HTTPException(status_code=404, detail="DeviceAction not found")
    action.name = body.name
    action.action_type = body.action_type
    action.http_method = body.http_method
    action.api_path = body.api_path
    action.params_schema = body.params_schema
    action.headers = body.headers
    action.body_template = body.body_template
    action.auth_type = body.auth_type
    action.enabled = body.enabled
    action.description = body.description
    db.commit()
    db.refresh(action)
    logger.info("设备动作已更新: id=%s", action.id)
    return to_dict(action)


@router.delete(
    "/{device_id}/actions/{action_id}",
    dependencies=[Depends(require_role("admin"))],
)
def delete_device_action(
    device_id: int, action_id: int, db: Session = Depends(get_db)
) -> dict:
    """删除设备动作。"""
    logger.info("删除设备动作: device_id=%s, action_id=%s", device_id, action_id)
    action = (
        db.query(DeviceAction)
        .filter(DeviceAction.id == action_id, DeviceAction.device_id == device_id)
        .first()
    )
    if action is None:
        raise HTTPException(status_code=404, detail="DeviceAction not found")
    db.delete(action)
    db.commit()
    logger.info("设备动作已删除: id=%s", action_id)
    return {"ok": True}


# ============ 动作测试 ============

@router.post(
    "/{device_id}/actions/{action_id}/test",
    dependencies=[Depends(require_role("admin"))],
    summary="测试设备动作连通性",
)
def test_device_action(
    device_id: int,
    action_id: int,
    body: ActionTestRequest,
    db: Session = Depends(get_db),
) -> dict:
    """实际调用设备 API 测试动作是否可用。

    根据 device.api_url + action.api_path 拼接完整 URL，
    按 action.auth_type 选择认证方式，按 body_template 或 params 构造请求体，
    用 httpx 发起实际 HTTP 请求并返回结果。
    """
    logger.info("测试设备动作: device_id=%s, action_id=%s", device_id, action_id)
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    action = (
        db.query(DeviceAction)
        .filter(DeviceAction.id == action_id, DeviceAction.device_id == device_id)
        .first()
    )
    if action is None:
        raise HTTPException(status_code=404, detail="DeviceAction not found")

    params = body.params or {}

    # 拼接完整 URL
    base_url = (device.api_url or "").rstrip("/")
    api_path = (action.api_path or "").lstrip("/")
    url = f"{base_url}/{api_path}" if api_path else base_url
    if not url:
        return {"success": False, "status_code": None, "response_body": None,
                "error": "设备未配置 api_url 且动作未配置 api_path"}

    # 构造请求头
    headers = {"Content-Type": "application/json"}
    try:
        extra_headers = json.loads(action.headers or "{}")
        if isinstance(extra_headers, dict):
            headers.update(extra_headers)
    except Exception:  # noqa: BLE001
        logger.warning("解析动作 headers 失败，忽略: action_id=%s", action_id)

    # 认证
    auth_type = action.auth_type or "api_key"
    auth = None
    if auth_type == "api_key":
        headers["Authorization"] = f"Bearer {device.api_key}"
    elif auth_type == "bearer":
        headers["Authorization"] = f"Bearer {device.api_key}"
    elif auth_type == "basic":
        auth = (device.username or "", device.password or "")
    # none: 不添加认证

    # 构造请求体
    if action.body_template:
        body_str = action.body_template
        for k, v in params.items():
            body_str = body_str.replace(f"{{{{{k}}}}}", str(v))
        try:
            req_body = json.loads(body_str)
        except Exception:  # noqa: BLE001
            req_body = body_str  # 保持字符串
    else:
        req_body = params

    method = (action.http_method or "POST").upper()
    logger.info("调用设备 API: %s %s, auth=%s", method, url, auth_type)

    try:
        with httpx.Client(timeout=30, verify=False) as client:  # verify=False 兼容自签证书
            r = client.request(
                method=method,
                url=url,
                headers=headers,
                json=req_body if isinstance(req_body, (dict, list)) else None,
                data=req_body if isinstance(req_body, str) else None,
                auth=auth,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("设备动作测试请求异常: %s", exc)
        return {"success": False, "status_code": None, "response_body": None,
                "error": f"{type(exc).__name__}: {exc}"}

    try:
        resp_body = r.json()
    except Exception:  # noqa: BLE001
        resp_body = r.text

    success = r.status_code < 400
    logger.info("设备动作测试完成: status=%s, success=%s", r.status_code, success)
    return {
        "success": success,
        "status_code": r.status_code,
        "response_body": resp_body,
        "error": None if success else f"HTTP {r.status_code}",
    }
