"""从 ToolDescriptor 注册表派生治理名单（消除多处硬编码）。"""
from __future__ import annotations

from app.core.tools.descriptor import ToolDescriptor
from app.core.tools.governance_legacy import (
    LEGACY_FILE_MUTATING,
    LEGACY_NEVER_PARALLEL,
    LEGACY_NO_EFFECT,
    LEGACY_PARALLEL_SAFE,
    LEGACY_SOAR_WRITE,
)

Registry = dict[str, ToolDescriptor]


def write_tools_requiring_verification(r: Registry) -> frozenset[str]:
    return frozenset(n for n, d in r.items() if d.verification)


def never_parallel_names(r: Registry) -> frozenset[str]:
    derived = frozenset(n for n, d in r.items() if d.mutating or not d.parallel_safe)
    return derived | LEGACY_NEVER_PARALLEL


def parallel_safe_names(r: Registry) -> frozenset[str]:
    derived = frozenset(n for n, d in r.items() if d.parallel_safe and not d.mutating)
    return derived | LEGACY_PARALLEL_SAFE


def deferrable_names(r: Registry) -> frozenset[str]:
    return frozenset(n for n, d in r.items() if d.deferrable)


def no_effect_names(r: Registry) -> frozenset[str]:
    derived = frozenset(
        n for n, d in r.items() if not d.mutating and d.parallel_safe
    )
    return derived | LEGACY_NO_EFFECT


def mutating_tool_names(r: Registry) -> frozenset[str]:
    derived = frozenset(n for n, d in r.items() if d.mutating)
    return derived | LEGACY_SOAR_WRITE


def file_mutating_tool_names(r: Registry) -> frozenset[str]:
    derived = frozenset(
        n for n, d in r.items()
        if d.mutating and (d.verification or d.name in ("record_ban", "save_memory"))
    )
    return derived | LEGACY_FILE_MUTATING


def danger_levels(r: Registry) -> dict[str, str]:
    """工具名 → danger_level（来自描述符声明，缺省 low）。"""
    return {n: (getattr(d, "danger_level", None) or "low") for n, d in r.items()}
