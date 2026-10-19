"""工具调用策略：危险层级 × 使用场景 → 是否需要人工确认。

场景（只有两个「会调工具」的入口）：
- agent    ：invoke_agent → Hermes → tool_engine（LLM 自主决策）
- workflow ：工作流节点 / invoke_tool（SOP 保证，直接执行）

注意：权限不在本模块校验（契约里 required_permission 仅埋点）。
"""
from __future__ import annotations

from dataclasses import dataclass

SCENARIO_AGENT = "agent"
SCENARIO_WORKFLOW = "workflow"

DANGER_LEVELS = ("low", "medium", "high", "critical")

# 危险层级 → 需要人工确认的场景集合
_CONFIRM_REQUIRED: dict[str, frozenset[str]] = {
    "critical": frozenset({SCENARIO_AGENT}),
    "high": frozenset({SCENARIO_AGENT}),
    "medium": frozenset(),
    "low": frozenset(),
}


def requires_confirmation(danger_level: str, scenario: str) -> bool:
    """该危险层级的工具在该场景下是否需要人工确认。"""
    return scenario in _CONFIRM_REQUIRED.get((danger_level or "low").lower(), frozenset())


@dataclass
class ConfirmationConfig:
    """确认闸开关（读 Agent.tool_configs["confirmation"]）。

    **默认开启**：高危工具在 Agent 对话中弹出确认框，由当前登录用户确认/拒绝。
    单个 Agent 可在 ``tool_configs["confirmation"]["enabled"] = False`` 关闭。
    """
    enabled: bool = True

    @classmethod
    def from_mapping(cls, data: dict | None) -> "ConfirmationConfig":
        data = data or {}
        return cls(enabled=bool(data.get("enabled", True)))
