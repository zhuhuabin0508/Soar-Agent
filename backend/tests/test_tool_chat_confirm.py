# -*- coding: utf-8 -*-
"""对话内确认/拒绝高危工具。"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.platform.approval import confirm_and_execute_tool, reject_tool_confirmation


def _ticket(**kwargs):
    defaults = dict(
        id=9,
        kind="agent_tool",
        status="pending",
        tool_name="block_ip",
        tool_arguments='{"ip":"1.1.1.1"}',
        agent_id=3,
        result=None,
        result_delivered=False,
        approver=None,
        approval_comment="",
        approved_at=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_reject_tool_records_approver():
    ticket = _ticket()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticket
    user = SimpleNamespace(id=7, username="ops_alice")

    out = reject_tool_confirmation(db, ticket_id=9, agent_id=3, user=user, comment="误报")
    assert out["decision"] == "rejected"
    assert ticket.status == "rejected"
    assert ticket.approver == "ops_alice"
    assert "误报" in ticket.result
    db.commit.assert_called()


def test_confirm_and_execute_claims_then_runs():
    ticket = _ticket()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticket
    user = SimpleNamespace(id=7, username="ops_alice")
    inv = SimpleNamespace(ok=True, error="", content={"status": "success"}, raw_content={"status": "success"})

    with patch(
        "app.platform.tool_runtime.invoke_tool",
        new=AsyncMock(return_value=inv),
    ) as mocked:
        out = asyncio.run(
            confirm_and_execute_tool(db, ticket_id=9, agent_id=3, user=user)
        )

    assert out["decision"] == "approved"
    assert out["ok"] is True
    assert ticket.approver == "ops_alice"
    assert ticket.status == "approved"
    payload = json.loads(ticket.result)
    assert payload["ok"] is True
    mocked.assert_awaited()
    assert mocked.await_args.kwargs.get("approved_ticket_id") == 9
