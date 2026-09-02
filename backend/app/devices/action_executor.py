"""设备动作执行器（可复用工具函数）。

从 devices.test_device_action 与 node_executors.execute_device_action 提取，
供 banned_ips API、设备测试、工作流 device_action 节点统一调用。

核心函数：
- ``execute_device_action``: 实际调用设备 API 执行指定动作，返回结构化结果。
- ``find_device_action_by_type``: 查找指定设备的指定类型动作（启用状态优先）。
"""
import json
import logging
from typing import Any

import httpx

from app.models.device import Device, DeviceAction

logger = logging.getLogger(__name__)


def execute_device_action(
    device: Device,
    action: DeviceAction,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """实际调用设备 API 执行指定动作。

    根据 device.api_url + action.api_path 拼接完整 URL，
    按 action.auth_type 选择认证方式，按 body_template 或 params 构造请求体，
    用 httpx 发起实际 HTTP 请求并返回结果。

    Args:
        device: Device ORM 实例（含 api_url/api_key/username/password）。
        action: DeviceAction ORM 实例（含 http_method/api_path/headers/body_template/auth_type）。
        params: 调用参数键值对，用于替换 body_template 中的 {{param}} 占位符；
            若 action 无 body_template，则 params 整体作为 JSON 请求体。
        timeout: HTTP 超时秒数。

    Returns:
        dict: {
            "success": bool,           # HTTP 状态码 < 400
            "status_code": int | None, # HTTP 状态码（请求异常时为 None）
            "response_body": Any,      # 解析后的 JSON 或原始文本
            "error": str | None,       # 失败原因（成功时为 None）
        }
    """
    params = params or {}

    # 1) 拼接 URL
    base_url = (device.api_url or "").rstrip("/")
    api_path = (action.api_path or "").lstrip("/")
    url = f"{base_url}/{api_path}" if api_path else base_url
    if not url:
        return {"success": False, "status_code": None, "response_body": None,
                "error": "设备未配置 api_url 且动作未配置 api_path"}

    # 2) 构造请求头
    headers = {"Content-Type": "application/json"}
    try:
        extra = json.loads(action.headers or "{}")
        if isinstance(extra, dict):
            headers.update(extra)
    except Exception:  # noqa: BLE001
        logger.warning("解析动作 headers 失败，忽略: action_id=%s", action.id)

    # 3) 认证
    auth_type = action.auth_type or "api_key"
    auth = None
    if auth_type in ("api_key", "bearer"):
        headers["Authorization"] = f"Bearer {device.api_key}"
    elif auth_type == "basic":
        auth = (device.username or "", device.password or "")
    # none: 不添加认证

    # 4) 构造请求体
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
    logger.info("调用设备 API: %s %s, auth=%s, device=%s, action=%s",
                method, url, auth_type, device.id, action.id)

    # 5) 发起 HTTP 请求（verify=False 兼容自签证书）
    try:
        with httpx.Client(timeout=timeout, verify=False) as client:
            r = client.request(
                method=method,
                url=url,
                headers=headers,
                json=req_body if isinstance(req_body, (dict, list)) else None,
                data=req_body if isinstance(req_body, str) else None,
                auth=auth,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("设备 API 请求异常: %s", exc)
        return {"success": False, "status_code": None, "response_body": None,
                "error": f"{type(exc).__name__}: {exc}"}

    try:
        resp_body = r.json()
    except Exception:  # noqa: BLE001
        resp_body = r.text

    success = r.status_code < 400
    logger.info("设备动作执行完成: status=%s, success=%s, device=%s, action=%s",
                r.status_code, success, device.id, action.id)
    return {
        "success": success,
        "status_code": r.status_code,
        "response_body": resp_body,
        "error": None if success else f"HTTP {r.status_code}",
    }


def find_device_action_by_type(
    db, device_id: int, action_type: str
) -> tuple[Device | None, DeviceAction | None, str | None]:
    """查找指定设备的指定类型动作（启用状态优先）。

    Args:
        db: 数据库会话。
        device_id: 设备 ID。
        action_type: 动作类型（如 "block_ip" / "unblock_ip"）。

    Returns:
        (device, action, error) 三元组：
        - device 为 None: 设备不存在。
        - action 为 None: 设备无此类型的启用动作。
        - error 非 None: 描述失败原因（可用于 HTTP 错误信息）。
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        return None, None, f"设备不存在: id={device_id}"
    if not device.enabled:
        return device, None, f"设备已禁用: {device.name}"

    action = (
        db.query(DeviceAction)
        .filter(
            DeviceAction.device_id == device_id,
            DeviceAction.action_type == action_type,
            DeviceAction.enabled.is_(True),
        )
        .order_by(DeviceAction.id.asc())
        .first()
    )
    if action is None:
        return device, None, f"设备「{device.name}」未配置启用的 {action_type} 动作"

    return device, action, None
