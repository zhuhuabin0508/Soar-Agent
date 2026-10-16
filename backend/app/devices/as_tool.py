"""把 Device / DeviceAction 投影为 Agent 工具（纯构建器，P2-2a）。

本模块只做构建（产出 ToolDescriptor），不接线：
- ToolRegistryBuilder._register_device_tools（enabled_devices）→ P2-3
- verification 的 device 工具分派 → P2-2b
- 语义 block_ip（默认设备解析）→ P2-4

设计要点：
- 写动作判定（架构 §6.4）：risk_level=high_risk 或 category ∈ {block, dispose}；
- 描述符标志（C1-6/C1-7）：写动作 mutating=True + verification="device_action" +
  parallel_safe=False + deferrable=False（核心）；读动作反之（可延迟）；
- coroutine 一律经 DeviceGateway（设备唯一执行缝，P2-1）；
- 只暴露「启用且在线」的设备（C1-12）；
- 描述写明「何时用」（C1-10，降 LLM 选错率）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.tool_builders import _build_args_model
from app.core.tools.descriptor import ToolDescriptor

logger = logging.getLogger(__name__)

# 写动作分类（架构 §6.4）：阻断类 / 处置类
_WRITE_CATEGORIES = frozenset({"block", "dispose"})


def is_write_action(action) -> bool:
    """写动作 = risk_level=high_risk 或 category ∈ {block, dispose}。"""
    return (getattr(action, "risk_level", "") or "").lower() == "high_risk" \
        or (getattr(action, "category", "") or "").lower() in _WRITE_CATEGORIES


def _parse_params_schema(action) -> list[dict]:
    """解析动作的 params_schema（JSON 数组），失败回退 []。"""
    try:
        parsed = json.loads(action.params_schema or "[]")
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def build_device_action_tool(db, device, action) -> ToolDescriptor:
    """投影工具：单个设备动作 → ``device_{device_id}_{action_id}``。

    设备/动作在构建期固化，LLM 只需填动作自身的参数。
    """
    write = is_write_action(action)
    args_schema = _build_args_model(
        f"device_action_{action.id}", _parse_params_schema(action)
    )

    async def _coroutine(**kwargs):
        from app.devices.gateway import DeviceGateway
        return await DeviceGateway.invoke(
            db, device.id, action_id=action.id, params=kwargs, source="agent",
        )

    kind = "写动作（会改变设备状态，需证据验证）" if write else "读动作（只读查询，无副作用）"
    description = (
        f"[设备动作] {device.name} · {action.name}"
        f"（action_type={action.action_type}，risk_level={action.risk_level or 'readonly'}，{kind}）。"
        f"何时用：需要对设备「{device.name}」执行 {action.action_type} 时调用。"
    )
    if action.description:
        description += f" {action.description}"

    return ToolDescriptor(
        name=f"device_{device.id}_{action.id}",
        description=description,
        args_schema=args_schema,
        coroutine=_coroutine,
        source="device",
        tool_source="device",
        tool_type="device",
        category=(action.category or None),
        mutating=write,
        risk_level="high" if write else "low",
        parallel_safe=not write,
        deferrable=not write,
        verification="device_action" if write else None,
    )


def build_list_devices_tool(db) -> ToolDescriptor:
    """枚举工具：``list_devices``，列出启用且在线的设备（C1-12）。"""
    async def _coroutine(**kwargs):
        from app.models.device import Device
        rows = (
            db.query(Device)
            .filter(Device.enabled.is_(True), Device.status == "online")
            .all()
        )
        return [
            {
                "id": d.id,
                "name": d.name,
                "type": d.type,
                "vendor": d.vendor,
                "description": d.description,
            }
            for d in rows
        ]

    return ToolDescriptor(
        name="list_devices",
        description=(
            "列出当前可用的安全设备（仅启用且在线的）。"
            "何时用：需要了解平台接入哪些防火墙/WAF/EDR 等设备、"
            "或需要设备 ID 供设备动作工具调用时使用。"
        ),
        args_schema=None,
        coroutine=_coroutine,
        source="device",
        tool_source="device",
        tool_type="device",
        mutating=False,
        parallel_safe=True,
        deferrable=False,
    )


def build_list_device_actions_tool(db) -> ToolDescriptor:
    """枚举工具：``list_device_actions``，列出启用的设备动作（可选按设备过滤）。"""
    async def _coroutine(**kwargs):
        from app.models.device import DeviceAction
        q = db.query(DeviceAction).filter(DeviceAction.enabled.is_(True))
        device_id = kwargs.get("device_id")
        if device_id:
            try:
                q = q.filter(DeviceAction.device_id == int(device_id))
            except (TypeError, ValueError):
                pass
        rows = q.all()
        return [
            {
                "id": a.id,
                "device_id": a.device_id,
                "name": a.name,
                "action_type": a.action_type,
                "category": a.category,
                "risk_level": a.risk_level,
                "description": a.description,
            }
            for a in rows
        ]

    return ToolDescriptor(
        name="list_device_actions",
        description=(
            "列出安全设备的可用动作（如 block_ip/unblock_ip 等，仅启用的）。"
            "何时用：需要查看某设备支持哪些动作、或需要 action_type 供 device_action "
            "兜底工具调用时使用；传 device_id 只看该设备。"
        ),
        args_schema=None,
        parameters={
            "type": "object",
            "properties": {
                "device_id": {"type": "integer", "description": "可选，只看该设备"},
            },
        },
        coroutine=_coroutine,
        source="device",
        tool_source="device",
        tool_type="device",
        mutating=False,
        parallel_safe=True,
        deferrable=False,
    )


def build_device_action_facade_tool(db) -> ToolDescriptor:
    """门面工具：``device_action``，按 device_id + action_type 兜底调用任意设备动作。"""
    async def _coroutine(**kwargs):
        from app.devices.gateway import DeviceGateway
        device_id = kwargs.pop("device_id", None)
        action_type = kwargs.pop("action_type", None)
        if device_id is None or not action_type:
            return {"error": "缺少必填参数：device_id 与 action_type"}
        try:
            device_id = int(device_id)
        except (TypeError, ValueError):
            return {"error": f"device_id 必须是整数: {device_id!r}"}
        # 入参支持两种风格：params 对象，或直接平铺剩余 kwargs
        params = kwargs.pop("params", None)
        if not isinstance(params, dict):
            params = dict(kwargs)
        elif kwargs:
            params = {**kwargs, **params}
        return await DeviceGateway.invoke(
            db, device_id, action_type=str(action_type), params=params, source="agent",
        )

    return ToolDescriptor(
        name="device_action",
        description=(
            "[设备动作·兜底] 按 device_id + action_type 直接调用任意安全设备动作。"
            "何时用：仅当没有对应的投影工具（device_{设备ID}_{动作ID}）或语义工具"
            "（如 block_ip）可用时才用本工具；优先使用投影/语义工具。"
        ),
        args_schema=None,
        parameters={
            "type": "object",
            "properties": {
                "device_id": {"type": "integer", "description": "目标设备 ID"},
                "action_type": {
                    "type": "string",
                    "description": "动作类型，如 block_ip/unblock_ip/quarantine_host",
                },
                "params": {"type": "object", "description": "动作参数（可选）"},
            },
            "required": ["device_id", "action_type"],
        },
        coroutine=_coroutine,
        source="device",
        tool_source="device",
        tool_type="device",
        mutating=True,
        risk_level="high",
        parallel_safe=False,
        deferrable=False,
        verification="device_action",
    )
