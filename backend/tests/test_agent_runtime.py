"""Agent 运行时适配器与引擎路由单测。"""
import json

import pytest

from app.platform.agent_runtime import (
    adapt_ban_risk_analyze,
    adapt_soc_decision,
    resolve_engine,
)
from app.workflow.agent_client import AgentCallError


class _FakeAgent:
    def __init__(self, agent_id: int, engine: str):
        self.id = agent_id
        self.engine = engine


class TestResolveEngine:
    def test_hermes_unchanged(self):
        assert resolve_engine(_FakeAgent(1, "hermes")) == "hermes"

    def test_langgraph_maps_to_hermes(self):
        assert resolve_engine(_FakeAgent(2, "langgraph")) == "hermes"

    def test_legacy_maps_to_hermes(self):
        assert resolve_engine(_FakeAgent(3, "legacy")) == "hermes"


class TestAdaptSocDecision:
    def test_valid_json(self):
        content = json.dumps(
            {
                "decision": "block_ip",
                "target_ip": "1.2.3.4",
                "reason": "恶意",
                "duration": "24h",
            },
            ensure_ascii=False,
        )
        out = adapt_soc_decision(content, "1.2.3.4")
        assert out["decision"] == "block_ip"
        assert out["target_ip"] == "1.2.3.4"

    def test_invalid_decision_fallback(self):
        content = json.dumps({"decision": "maybe_block", "target_ip": "1.2.3.4"})
        out = adapt_soc_decision(content, "1.2.3.4")
        assert out["decision"] == "need_human_approval"

    def test_free_text_fallback(self):
        out = adapt_soc_decision("这不是 JSON", "9.9.9.9")
        assert out["decision"] == "need_human_approval"
        assert out["target_ip"] == "9.9.9.9"


class TestAdaptBanRiskAnalyze:
    def _valid_body(self):
        return {
            "is_banned": False,
            "risk_level": "高危",
            "action": "ban",
            "need_confirm": True,
            "ban_plan": {"ban_level": "high", "ban_duration": 7200, "reason": "test"},
            "monitoring_advice": "观察",
            "reasons": ["境外 IP"],
        }

    def test_valid_json(self):
        content = json.dumps(self._valid_body(), ensure_ascii=False)
        out = adapt_ban_risk_analyze(content)
        assert out["action"] == "ban"
        assert out["need_confirm"] is True

    def test_missing_field_raises(self):
        body = self._valid_body()
        del body["ban_plan"]
        with pytest.raises(AgentCallError, match="ban_plan"):
            adapt_ban_risk_analyze(json.dumps(body))

    def test_invalid_json_raises(self):
        with pytest.raises(AgentCallError, match="解析失败"):
            adapt_ban_risk_analyze("not-json{")

    def test_embedded_json_object(self):
        content = "分析如下： " + json.dumps(self._valid_body(), ensure_ascii=False)
        out = adapt_ban_risk_analyze(content)
        assert out["risk_level"] == "高危"
