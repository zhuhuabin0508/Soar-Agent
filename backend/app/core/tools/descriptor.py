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

    parameters: Optional[dict] = None
    extra: dict = field(default_factory=dict)
