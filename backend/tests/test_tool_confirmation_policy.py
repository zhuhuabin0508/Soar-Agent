# -*- coding: utf-8 -*-
"""阶段 1 单测：危险层级 × 场景 策略 + 契约字段。"""
from app.core.tools.policy import (
    SCENARIO_AGENT, SCENARIO_WORKFLOW, ConfirmationConfig, requires_confirmation,
)


class TestRequiresConfirmation:
    def test_high_requires_confirm_in_agent(self):
        assert requires_confirmation("high", SCENARIO_AGENT) is True

    def test_high_not_required_in_workflow(self):
        assert requires_confirmation("high", SCENARIO_WORKFLOW) is False

    def test_low_never_requires(self):
        assert requires_confirmation("low", SCENARIO_AGENT) is False

    def test_critical_requires_confirm_in_agent(self):
        assert requires_confirmation("critical", SCENARIO_AGENT) is True

    def test_unknown_level_falls_back_to_low(self):
        assert requires_confirmation("", SCENARIO_AGENT) is False


class TestConfirmationConfig:
    def test_default_enabled(self):
        assert ConfirmationConfig().enabled is True

    def test_from_mapping(self):
        assert ConfirmationConfig.from_mapping({"enabled": False}).enabled is False
        assert ConfirmationConfig.from_mapping({}).enabled is True


def test_descriptor_contract_fields():
    from app.core.tools.descriptor import ToolDescriptor
    d = ToolDescriptor(name="x", description="", args_schema=None, coroutine=None)
    assert d.danger_level == "low"
    assert d.required_permission is None
