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


def _db_with_ticket(ticket):
    db = MagicMock()
    q = db.query.return_value
    q.filter.return_value = q
    q.with_for_update.return_value = q
    q.first.return_value = ticket
    return db


def test_reject_tool_records_approver():
    ticket = _ticket()
    db = _db_with_ticket(ticket)
    user = SimpleNamespace(id=7, username="ops_alice")

    out = reject_tool_confirmation(db, ticket_id=9, agent_id=3, user=user, comment="误报")
    assert out["decision"] == "rejected"
    assert ticket.status == "rejected"
    assert ticket.approver == "ops_alice"
    assert "误报" in ticket.result
    db.commit.assert_called()


def test_confirm_and_execute_claims_then_runs():
    ticket = _ticket()
    db = _db_with_ticket(ticket)
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


def test_confirm_rejects_non_pending():
    ticket = _ticket(status="approved", result='{"status":"executing"}')
    db = _db_with_ticket(ticket)
    user = SimpleNamespace(id=7, username="ops_alice")
    try:
        asyncio.run(confirm_and_execute_tool(db, ticket_id=9, agent_id=3, user=user))
        assert False, "should raise"
    except ValueError as exc:
        assert "不可重复" in str(exc) or "已处理" in str(exc)


def test_confirm_trigger_workflow_skill_uses_bridge():
    from datetime import timedelta

    from app.core.timezone import beijing_now
    from app.platform.approval import make_dedup_key

    args = {"workflow_id": 12, "input": {"ip": "1.2.3.4"}}
    ticket = _ticket(
        tool_name="trigger_workflow_skill",
        tool_arguments=json.dumps(args, ensure_ascii=False),
        requested_by=7,
        session_id="",
        deadline=beijing_now() + timedelta(minutes=10),
        dedup_key=make_dedup_key(
            tool_name="trigger_workflow_skill", arguments=args, agent_id=3, session_id="",
        ),
    )
    agent = SimpleNamespace(id=3, enabled_workflows=None)
    ticket_q = MagicMock()
    ticket_q.filter.return_value = ticket_q
    ticket_q.with_for_update.return_value = ticket_q
    ticket_q.first.return_value = ticket
    agent_q = MagicMock()
    agent_q.filter.return_value = agent_q
    agent_q.first.return_value = agent
    db = MagicMock()

    def _query(model):
        mod = getattr(model, "__name__", "")
        if mod == "ApprovalTicket":
            return ticket_q
        return agent_q

    db.query.side_effect = _query
    user = SimpleNamespace(id=7, username="ops_alice", role="analyst", role_id=None)
    ctx = SimpleNamespace(
        status="completed",
        skill_run_id="abc",
        execution_id=99,
        node_outputs={"a": 1},
        pending_approval=None,
    )
    bridge = MagicMock()
    bridge.trigger_skill = AsyncMock(return_value=ctx)

    with patch(
        "app.agent.hermes.skill_engine.WorkflowSkillBridge",
        return_value=bridge,
    ):
        out = asyncio.run(
            confirm_and_execute_tool(db, ticket_id=9, agent_id=3, user=user)
        )

    assert out["ok"] is True
    assert out["result"]["content"]["status"] == "completed"
    bridge.trigger_skill.assert_awaited()
