"""从 ToolDescriptor 注册表派生治理名单（消除多处硬编码）。"""
from __future__ import annotations

from app.core.tools.descriptor import ToolDescriptor
from app.core.tools.governance_legacy import (
    LEGACY_NEVER_PARALLEL,
    LEGACY_PARALLEL_SAFE,
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
