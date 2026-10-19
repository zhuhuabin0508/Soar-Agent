# -*- coding: utf-8 -*-
"""阶段 6c：审批结果注入下一轮。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.hermes.executor import HermesAgentExecutor


def _executor(session_rows):
    ex = HermesAgentExecutor.__new__(HermesAgentExecutor)   # 跳过 __init__ 的重依赖
    ex.db = MagicMock()
    ex.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = session_rows
    ex.agent = SimpleNamespace(id=9)
    ex.messages = [{"role": "system", "content": "sys"}]
    ex._log = lambda *a, **k: None
    return ex


def test_inject_marks_delivered_and_appends_system_message():
    t = SimpleNamespace(id=12, tool_name="block_ip", status="approved",
                        result='{"ok": true}', result_delivered=False)
    ex = _executor([t])
    ex._inject_approval_results(session_id="sess-1")

    assert t.result_delivered is True
    assert ex.db.commit.called
    last = ex.messages[-1]
    assert last["role"] == "system" and "人工审批结果" in last["content"]
    assert "#12" in last["content"]


def test_inject_noop_without_session():
    ex = _executor([])
    ex._inject_approval_results(session_id="")
    assert len(ex.messages) == 1        # 只保留原 system
