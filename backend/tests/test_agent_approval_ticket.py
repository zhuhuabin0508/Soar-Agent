# -*- coding: utf-8 -*-
"""阶段 6a：Agent 工具审批单创建与去重。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.platform.approval import (
    KIND_AGENT_TOOL, create_tool_approval, make_dedup_key,
)


def _db(existing=None):
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = existing
    return db


def test_dedup_key_stable():
    k1 = make_dedup_key(tool_name="block_ip", arguments={"ip": "1.1.1.1"}, agent_id=1, session_id="s")
    k2 = make_dedup_key(tool_name="block_ip", arguments={"ip": "1.1.1.1"}, agent_id=1, session_id="s")
    k3 = make_dedup_key(tool_name="block_ip", arguments={"ip": "2.2.2.2"}, agent_id=1, session_id="s")
    assert k1 == k2 and k1 != k3


def test_creates_agent_ticket():
    db = _db(existing=None)
    t = create_tool_approval(
        db, tool_name="block_ip", arguments={"ip": "1.1.1.1"},
        danger_level="high", agent_id=1, user_id=2, session_id="s1",
    )
    assert t.kind == KIND_AGENT_TOOL
    assert t.workflow_instance_id == 0 and t.ip == ""
    assert t.status == "pending"
    assert json.loads(t.tool_arguments) == {"ip": "1.1.1.1"}
    assert t.deadline is not None
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_reuses_pending_ticket():
    existing = SimpleNamespace(id=42, status="pending", kind=KIND_AGENT_TOOL)
    db = _db(existing=existing)
    t = create_tool_approval(
        db, tool_name="block_ip", arguments={"ip": "1.1.1.1"},
        danger_level="high", agent_id=1, session_id="s1",
    )
    assert t is existing
    db.add.assert_not_called()
