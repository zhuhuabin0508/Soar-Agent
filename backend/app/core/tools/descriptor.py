"""统一工具描述符：模块对外暴露的唯一工具契约。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolDescriptor:
    name: str
    description: str
    args_schema: Any
    coroutine: Callable

    source: str = "builtin"
    tool_source: str = "builtin"
    tool_type: str = "code"
    category: Optional[str] = None

    mutating: bool = False
    risk_level: str = "low"
    parallel_safe: bool = False
    deferrable: bool = False
    untrusted: bool = False
    verification: Optional[str] = None

    # 【新增】危险层级：low | medium | high | critical
    # 决定「是否需要人工确认」；见 core/tools/policy.py
    danger_level: str = "low"
    # 【新增·埋点】调用该工具所需权限 (module, action)。
    # 本轮只填值、**不校验**（权限闸后续再做）
    required_permission: tuple[str, str] | None = None

    parameters: Optional[dict] = None
    extra: dict = field(default_factory=dict)
