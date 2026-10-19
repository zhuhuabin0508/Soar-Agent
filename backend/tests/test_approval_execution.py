# -*- coding: utf-8 -*-
"""阶段 6b：审批凭据校验 + 闸放行。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.hermes.tool_engine import HermesToolEngine
from app.agent.hermes.types import ToolCall, ToolEntry
from app.core.tools.policy import ConfirmationConfig
from app.platform.tool_runtime import invoke_tool


def _db_with_ticket(ticket):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticket
    db.query.return_value.filter.return_value.all.return_value = []
    return db


def test_invoke_tool_rejects_invalid_ticket():
    db = _db_with_ticket(SimpleNamespace(id=1, status="pending", tool_name="block_ip"))
    r = asyncio.run(invoke_tool("block_ip", {}, db=db, approved_ticket_id=1))
    assert r.ok is False
    assert "审批凭据无效" in r.error


def test_engine_gate_skipped_when_approved():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    engine = HermesToolEngine(db, None, approved_ticket_id=42)
    engine.confirmation_config = ConfirmationConfig(enabled=True)

    async def coro(**kw):
        return {"ok": True}

    engine._registry["danger_tool"] = ToolEntry(
        name="danger_tool", description="", args_schema=None, coroutine=coro)
    engine._danger_levels["danger_tool"] = "high"
    engine._self_gating = frozenset()

    tc = ToolCall(original_index=0, id="t", name="danger_tool", arguments={})
    r = asyncio.run(engine.execute_tool_calls([tc]))[0]
    assert "pending_approval" not in str(r.content)
    assert "needs_confirmation" not in str(r.content)
