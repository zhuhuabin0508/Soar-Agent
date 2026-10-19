# -*- coding: utf-8 -*-
"""阶段 5：工作流危险推导 + 自门控豁免。"""
from app.agent.workflow_as_tool import workflow_danger, workflow_self_gates


def _graph(*types):
    return {"nodes": [{"id": f"n{i}", "type": t} for i, t in enumerate(types)]}


class TestWorkflowDanger:
    def test_block_node_is_high(self):
        assert workflow_danger(_graph("webhook_trigger", "block_ip")) == "high"

    def test_device_action_node_is_high(self):
        assert workflow_danger(_graph("device_action")) == "high"

    def test_tool_node_is_high(self):
        assert workflow_danger(_graph("tool")) == "high"

    def test_only_safe_nodes_is_low(self):
        assert workflow_danger(_graph("webhook_trigger", "send_notification", "end")) == "low"

    def test_empty_graph_is_low(self):
        assert workflow_danger({}) == "low"
        assert workflow_danger(None) == "low"


class TestWorkflowSelfGates:
    def test_human_review_self_gates(self):
        assert workflow_self_gates(_graph("block_ip", "human_review")) is True

    def test_approval_ticket_self_gates(self):
        assert workflow_self_gates(_graph("approval_ticket")) is True

    def test_without_approval_not_self_gating(self):
        assert workflow_self_gates(_graph("block_ip", "end")) is False


class TestGateExemptionSemantics:
    """闸判定表达式 = requires_confirmation(danger, AGENT) and name not in self_gating。"""

    def _sets(self):
        from types import SimpleNamespace

        from app.core.tools.derive import self_gating_tool_names
        # 两个工作流工具：一个自门控（图内有审批节点），一个不是
        descs = {
            "workflow_1_gated": SimpleNamespace(
                extra={"self_gating": True}, danger_level="high"),
            "workflow_2_bare": SimpleNamespace(
                extra={"self_gating": False}, danger_level="high"),
        }
        return self_gating_tool_names(descs), descs

    def test_self_gating_tool_passes_gate(self):
        from app.core.tools.policy import SCENARIO_AGENT, requires_confirmation

        gating, descs = self._sets()
        name = "workflow_1_gated"
        danger = descs[name].danger_level
        # 高危但在豁免集 → 闸放行（判定表达式为 False）
        assert requires_confirmation(danger, SCENARIO_AGENT) is True   # 前提：确实高危
        assert name in gating                                          # 前提：确实豁免
        assert not (requires_confirmation(danger, SCENARIO_AGENT) and name not in gating)

    def test_non_gating_high_tool_blocked(self):
        from app.core.tools.policy import SCENARIO_AGENT, requires_confirmation

        gating, descs = self._sets()
        name = "workflow_2_bare"
        danger = descs[name].danger_level
        # 高危且不在豁免集 → 闸拦截（表达式为 True）
        assert requires_confirmation(danger, SCENARIO_AGENT) and name not in gating
