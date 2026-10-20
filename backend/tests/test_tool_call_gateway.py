# -*- coding: utf-8 -*-
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.hermes.tool_engine import HermesToolEngine
from app.agent.hermes.types import ToolCall, ToolEntry
from app.core.timezone import beijing_now
from app.core.tools.call_gateway import authorize_tool_call, tier_of
from app.core.tools.policy import ConfirmationConfig
from app.platform.approval import make_dedup_key


def test_tier_map():
    assert tier_of("low") == "L0"
    assert tier_of("medium") == "L1"
    assert tier_of("high") == "L2"
    assert tier_of("critical") == "L3"
    assert tier_of("") == "L0"


def _db_with_ticket(ticket):
    db = MagicMock()
    q = db.query.return_value
    q.filter.return_value = q
    q.with_for_update.return_value = q
    q.first.return_value = ticket
    q.all.return_value = []
    return db


def _ticket(args, *, user_id=2, status="approved", result='{"status":"executing"}', tool_name="block_ip"):
    return SimpleNamespace(
        id=9,
        kind="agent_tool",
        status=status,
        tool_name=tool_name,
        deadline=beijing_now() + timedelta(minutes=10),
        requested_by=user_id,
        agent_id=1,
        session_id="s",
        dedup_key=make_dedup_key(
            tool_name=tool_name, arguments=args, agent_id=1, session_id="s",
        ),
        tool_arguments=json.dumps(args, ensure_ascii=False),
        result=result,
    )


def _user():
    return SimpleNamespace(id=2, role="analyst", username="analyst")


def test_l2_credential_allows_once():
    args = {"ip": "1.1.1.1"}
    ticket = _ticket(args)
    db = _db_with_ticket(ticket)
    first = authorize_tool_call(
        db, tool_name="block_ip", arguments=args, danger_level="high",
        required_permission=None, user=_user(), approved_ticket_id=9,
    )
    assert first.allow is True
    assert "consumed" in ticket.result
    second = authorize_tool_call(
        db, tool_name="block_ip", arguments=args, danger_level="high",
        required_permission=None, user=_user(), approved_ticket_id=9,
    )
    assert second.allow is False
    assert "已使用" in second.reason


def test_l2_rejects_argument_mismatch():
    ticket = _ticket({"ip": "1.1.1.1"})
    db = _db_with_ticket(ticket)
    decision = authorize_tool_call(
        db, tool_name="block_ip", arguments={"ip": "2.2.2.2"}, danger_level="high",
        required_permission=None, user=_user(), approved_ticket_id=9,
    )
    assert decision.allow is False
    assert "参数" in decision.reason
    assert "executing" in ticket.result


def test_agent_critical_denied_and_workflow_allowed():
    db = MagicMock()
    denied = authorize_tool_call(
        db, tool_name="wipe", arguments={}, danger_level="critical",
        required_permission=None, user=_user(),
    )
    assert denied.allow is False
    allowed = authorize_tool_call(
        db, tool_name="wipe", arguments={}, danger_level="critical",
        required_permission=("device", "edit"), user=None,
    )
    assert allowed.allow is True
    assert allowed.tier == "L3"


def _engine():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    engine = HermesToolEngine(db, None)
    engine._self_gating = frozenset()
    engine._required_permissions = {}
    return engine


def test_engine_l2_without_credential_does_not_run():
    engine = _engine()
    engine.user = _user()
    engine.user_id = 2
    engine.confirmation_config = ConfirmationConfig(enabled=False)
    called = {"n": 0}

    async def coro(**kwargs):
        called["n"] += 1
        return {"ok": True}

    engine._registry["danger_tool"] = ToolEntry(
        name="danger_tool", description="", args_schema=None, coroutine=coro,
    )
    engine._danger_levels["danger_tool"] = "high"
    tc = ToolCall(original_index=0, id="t", name="danger_tool", arguments={})
    result = asyncio.run(engine.execute_tool_calls([tc]))[0]
    assert called["n"] == 0
    assert result.is_error is True
    assert "凭证" in str(result.content)


def test_engine_l3_does_not_run_for_chat_user():
    engine = _engine()
    engine.user = _user()
    engine.confirmation_config = ConfirmationConfig(enabled=True)
    called = {"n": 0}

    async def coro(**kwargs):
        called["n"] += 1
        return {"ok": True}

    engine._registry["wipe"] = ToolEntry(
        name="wipe", description="", args_schema=None, coroutine=coro,
    )
    engine._danger_levels["wipe"] = "critical"
    tc = ToolCall(original_index=0, id="t", name="wipe", arguments={})
    result = asyncio.run(engine.execute_tool_calls([tc]))[0]
    assert called["n"] == 0
    assert result.is_error is True
    assert "最高危" in str(result.content)
    assert "pending_approval" not in str(result.content)
