"""阶段 C-11 验证测试：delegation_live_log.py + delegator.py

测试覆盖：
1. LiveTranscriptWriter 创建、append-only 写入、流式缓冲、强制脱敏
2. create_live_transcripts 多任务 + manifest.json
3. update_manifest_statuses 完成后状态更新
4. prune_stale_live_dirs 过期清理
5. 委派深度 ContextVar 跟踪
6. ChildAgentConfig 包装 + blocked tools 剥离
7. build_child_system_prompt 聚焦提示词
8. wrap_progress_callback 事件转发
9. Delegator 参数校验与深度超限拒绝
10. DELEGATE_TASK_SCHEMA 结构正确性

运行：
    docker exec soar-backend python -m pytest tests/test_delegation_c11.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ============================================================================
# 1. LiveTranscriptWriter
# ============================================================================


def test_live_writer_creates_file_with_header(tmp_path, monkeypatch):
    """writer 在分发时预创建日志文件并写 header。"""
    from app.agent.hermes.delegation_live_log import LiveTranscriptWriter

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    writer = LiveTranscriptWriter("deleg_test1", 0, "测试目标")

    assert writer.path is not None
    assert writer.path.exists()
    content = writer.path.read_text(encoding="utf-8")
    assert "Soar subagent live transcript" in content
    assert "deleg_test1" in content
    assert "goal: 测试目标" in content
    assert "kickoff: 测试目标" in content


def test_live_writer_append_only(tmp_path, monkeypatch):
    """多次 event 调用追加到同一文件，不覆盖。"""
    from app.agent.hermes.delegation_live_log import LiveTranscriptWriter

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    writer = LiveTranscriptWriter("deleg_test2", 1, "append 测试")

    writer.event("assistant", "第一行")
    writer.event("assistant", "第二行")
    writer.event("tool", "-> search(query)")

    content = writer.path.read_text(encoding="utf-8")
    assert "第一行" in content
    assert "第二行" in content
    assert "-> search" in content


def test_live_writer_redacts_credentials(tmp_path, monkeypatch):
    """写入前强制脱敏 API key / Bearer token。"""
    from app.agent.hermes.delegation_live_log import LiveTranscriptWriter

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    writer = LiveTranscriptWriter("deleg_test3", 0, "脱敏测试")

    # 注入多种凭据，必须脱敏
    writer.tool_result(
        "http_get",
        result='headers={"Authorization": "Bearer sk-abcdef1234567890abcdef1234567890"}',
    )
    writer.event("assistant", "API key is sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxx")

    content = writer.path.read_text(encoding="utf-8")
    # 原始凭据不应出现
    assert "sk-abcdef1234567890abcdef1234567890" not in content
    assert "sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxx" not in content
    # 应该被替换为脱敏标记
    assert "Bearer ***" in content or "[REDACTED" in content or "***" in content


def test_live_writer_stream_buffering(tmp_path, monkeypatch):
    """流式 token 缓冲，直到下一事件 flush。"""
    from app.agent.hermes.delegation_live_log import LiveTranscriptWriter

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    writer = LiveTranscriptWriter("deleg_test4", 0, "流式测试")

    writer.add_stream_delta("Hello")
    writer.add_stream_delta(", ")
    writer.add_stream_delta("World!")
    # 此时 buffer 应有内容，但未 flush
    content_before = writer.path.read_text(encoding="utf-8")
    assert "Hello, World!" not in content_before

    # 触发 flush
    writer.flush_stream()
    content_after = writer.path.read_text(encoding="utf-8")
    assert "Hello, World!" in content_after


def test_live_writer_observe_sse_events(tmp_path, monkeypatch):
    """observe() 把 Soar SSE 事件映射到 transcript 行。"""
    from app.agent.hermes.delegation_live_log import LiveTranscriptWriter

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    writer = LiveTranscriptWriter("deleg_test5", 0, "observe 测试")

    writer.observe("start", preview="子代理启动")
    writer.observe("token", preview="流式")
    writer.observe("token", preview="文本")
    writer.observe("tool_start", tool_name="search_kb", preview="query=告警")
    writer.observe(
        "tool_end", tool_name="search_kb",
        result="找到 3 条记录", duration=1.5, is_error=False,
    )
    writer.observe("done", message="完成")

    content = writer.path.read_text(encoding="utf-8")
    assert "子代理启动" in content
    assert "流式文本" in content  # 两个 token 合并
    assert "search_kb" in content
    assert "找到 3 条记录" in content
    assert "complete" in content


def test_live_writer_failure_degrades_gracefully(tmp_path, monkeypatch):
    """写入失败时翻转 _ok，后续调用变 no-op，不抛异常。"""
    from app.agent.hermes.delegation_live_log import LiveTranscriptWriter

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path / "nonexistent" / "subdir"))
    # 父目录不存在 + mkdir 失败场景：构造时若失败 _ok=False
    # 但 mkdir(parents=True) 会创建，所以构造会成功；改用 path 不可写模拟
    writer = LiveTranscriptWriter("deleg_test6", 0, "失败测试")
    # 模拟写入失败：把 path 改成无效路径
    writer.path = Path("/nonexistent_root_xyz/path/to/log.log")

    # 不应抛异常
    writer.event("assistant", "不应写入")
    assert writer._ok is False  # 失败后 _ok 翻转
    # 后续调用也是 no-op
    writer.event("assistant", "再次调用")
    writer.tool_start("test")


# ============================================================================
# 2. create_live_transcripts + manifest
# ============================================================================


def test_create_live_transcripts_multi_task(tmp_path, monkeypatch):
    """为多个任务创建独立 writer + manifest.json。"""
    from app.agent.hermes.delegation_live_log import (
        create_live_transcripts,
        _manifest_path,
    )

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    tasks = [
        {"goal": "任务 A", "context": "背景 A"},
        {"goal": "任务 B", "context": "背景 B"},
        {"goal": "任务 C", "context": ""},
    ]

    delegation_id, writers, paths = create_live_transcripts(tasks)

    assert delegation_id is not None
    assert delegation_id.startswith("deleg_")
    assert len(writers) == 3
    assert len(paths) == 3
    for w in writers:
        assert w is not None
        assert w.path is not None
        assert w.path.exists()

    # manifest.json 存在且结构正确
    manifest_file = _manifest_path(delegation_id)
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["delegation_id"] == delegation_id
    assert manifest["task_count"] == 3
    assert len(manifest["tasks"]) == 3
    for i, t in enumerate(manifest["tasks"]):
        assert t["index"] == i
        assert t["status"] == "running"
        assert t["log"] == paths[i]


def test_create_live_transcripts_redacts_manifest_goals(tmp_path, monkeypatch):
    """manifest.json 中的 goal 字段必须脱敏。"""
    from app.agent.hermes.delegation_live_log import (
        create_live_transcripts,
        _manifest_path,
    )

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    secret = "sk-ant-api03-secretkey1234567890abcdef"
    tasks = [{"goal": f"分析 {secret} 是否泄露"}]

    delegation_id, _, _ = create_live_transcripts(tasks)
    manifest = json.loads(_manifest_path(delegation_id).read_text(encoding="utf-8"))

    assert secret not in manifest["tasks"][0]["goal"]


def test_update_manifest_statuses(tmp_path, monkeypatch):
    """完成后 best-effort 更新每任务状态。"""
    from app.agent.hermes.delegation_live_log import (
        create_live_transcripts,
        update_manifest_statuses,
        _manifest_path,
    )

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    tasks = [{"goal": "任务 A"}, {"goal": "任务 B"}]
    delegation_id, _, _ = create_live_transcripts(tasks)

    results = [
        {"task_index": 0, "status": "completed", "exit_reason": None, "result": "ok"},
        {"task_index": 1, "status": "failed", "exit_reason": "error", "result": "boom"},
    ]
    update_manifest_statuses(delegation_id, results)

    manifest = json.loads(_manifest_path(delegation_id).read_text(encoding="utf-8"))
    assert manifest["tasks"][0]["status"] == "completed"
    assert manifest["tasks"][1]["status"] == "failed"
    assert manifest["tasks"][1]["exit_reason"] == "error"
    assert "completed" in manifest  # 完成时间戳


# ============================================================================
# 3. prune_stale_live_dirs
# ============================================================================


def test_prune_stale_dirs(tmp_path, monkeypatch):
    """超过保留期的目录被清理，新目录保留。"""
    from app.agent.hermes.delegation_live_log import (
        create_live_transcripts,
        prune_stale_live_dirs,
        live_transcript_root,
    )

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))

    # 先创建一个新目录（会触发内部 prune，但此时还没有老目录）
    create_live_transcripts([{"goal": "新任务"}])

    # 在 live 根下手动塞一个"老"目录（绕过 create_live_transcripts 的内部 prune）
    root = live_transcript_root()
    old_root = root / "deleg_old_manual"
    old_root.mkdir(parents=True, exist_ok=True)
    (old_root / "task-0.log").write_text("old", encoding="utf-8")
    # 修改 mtime 为 10 天前
    old_time = time.time() - 10 * 86400
    os.utime(old_root, (old_time, old_time))

    # 调用 prune，应清理老目录
    removed = prune_stale_live_dirs(max_age_days=7)
    assert removed >= 1
    assert not old_root.exists()  # 老目录已清理
    # 新目录应保留
    remaining = [p.name for p in root.iterdir() if p.is_dir()]
    assert "deleg_old_manual" not in remaining
    assert len(remaining) >= 1  # 至少保留 create_live_transcripts 创建的新目录


# ============================================================================
# 4. 委派深度跟踪
# ============================================================================


def test_delegation_depth_default():
    """默认深度 = 0（顶层 agent）。"""
    from app.agent.hermes.delegator import get_delegation_depth

    assert get_delegation_depth() == 0


def test_delegation_depth_context():
    """delegation_depth_context 设置深度，退出后恢复。"""
    from app.agent.hermes.delegator import (
        get_delegation_depth,
        delegation_depth_context,
    )

    assert get_delegation_depth() == 0
    with delegation_depth_context(1):
        assert get_delegation_depth() == 1
        with delegation_depth_context(2):
            assert get_delegation_depth() == 2
        assert get_delegation_depth() == 1
    assert get_delegation_depth() == 0


# ============================================================================
# 5. ChildAgentConfig + blocked tools
# ============================================================================


def test_strip_blocked_tools():
    """剥离子代理禁止使用的工具。"""
    from app.agent.hermes.delegator import _strip_blocked_tools, DELEGATE_BLOCKED_TOOLS

    parent_tools = [
        "search_knowledge_base", "delegate_task", "clarify",
        "memory_write", "block_ip", "trigger_workflow_skill",
        "send_notification", "get_threat_intel",
    ]
    child_tools = _strip_blocked_tools(parent_tools)

    # 子代理保留了普通工具
    assert "search_knowledge_base" in child_tools
    assert "block_ip" in child_tools
    assert "get_threat_intel" in child_tools
    # 子代理剥离了 blocked tools
    for blocked in DELEGATE_BLOCKED_TOOLS:
        assert blocked not in child_tools


def test_child_agent_config_delegates_to_parent():
    """ChildAgentConfig 未显式设置的属性委托给父 agent。"""
    from app.agent.hermes.delegator import ChildAgentConfig

    parent = MagicMock()
    parent.name = "父代理"
    parent.model_config_id = 42
    parent.temperature = 0.7
    parent.tool_configs = {"guardrails": {}}
    parent.tone_style = "专业"

    child = ChildAgentConfig(
        parent,
        enabled_tools=["search_knowledge_base", "block_ip"],
        name="子代理 A",
    )

    # 显式覆盖
    assert child.enabled_tools == ["search_knowledge_base", "block_ip"]
    assert child.enabled_skills == []  # 子代理不注入技能
    assert child.name == "子代理 A"
    # 委托给父
    assert child.model_config_id == 42
    assert child.temperature == 0.7
    assert child.tool_configs == {"guardrails": {}}
    assert child.tone_style == "专业"


# ============================================================================
# 6. build_child_system_prompt
# ============================================================================


def test_build_child_system_prompt_contains_goal_and_context():
    """子代理 prompt 包含 goal、context 与约束。"""
    from app.agent.hermes.delegator import build_child_system_prompt

    parent = MagicMock()
    parent.tone_style = "专业严谨"

    prompt = build_child_system_prompt(
        goal="调研 SQL 注入防护方案",
        context="项目栈：Python + FastAPI + PostgreSQL",
        parent_agent=parent,
    )

    assert "调研 SQL 注入防护方案" in prompt
    assert "Python + FastAPI + PostgreSQL" in prompt
    assert "delegate_task" in prompt  # 提示子代理该工具不可用
    assert "clarify" in prompt
    assert "memory_write" in prompt
    assert "专业严谨" in prompt


def test_build_child_system_prompt_without_context():
    """无 context 时也能正常生成。"""
    from app.agent.hermes.delegator import build_child_system_prompt

    parent = MagicMock()
    parent.tone_style = ""

    prompt = build_child_system_prompt(
        goal="分析日志", context=None, parent_agent=parent,
    )
    assert "分析日志" in prompt


# ============================================================================
# 7. wrap_progress_callback
# ============================================================================


def test_wrap_progress_callback_forwards_to_writer_and_inner(tmp_path, monkeypatch):
    """包装器把事件同时写入 transcript 和转发到 inner cb。"""
    from app.agent.hermes.delegation_live_log import (
        LiveTranscriptWriter,
        wrap_progress_callback,
    )

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    writer = LiveTranscriptWriter("deleg_wrap", 0, "wrap 测试")

    inner_calls = []

    def inner_cb(event_type, tool_name=None, preview=None, args=None, **kwargs):
        inner_calls.append((event_type, tool_name, preview))

    wrapped = wrap_progress_callback(inner_cb, writer)

    wrapped("tool_start", tool_name="search", preview="q=告警")
    wrapped("token", preview="delta")
    wrapped("done", message="完成")

    # inner cb 被调用 3 次
    assert len(inner_calls) == 3
    # writer 也收到了事件
    content = writer.path.read_text(encoding="utf-8")
    assert "search" in content
    assert "delta" in content
    assert "complete" in content


def test_wrap_progress_callback_inner_none(tmp_path, monkeypatch):
    """inner_cb=None 时包装器仍记录事件。"""
    from app.agent.hermes.delegation_live_log import (
        LiveTranscriptWriter,
        wrap_progress_callback,
    )

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    writer = LiveTranscriptWriter("deleg_wrap2", 0, "wrap 测试 2")

    wrapped = wrap_progress_callback(None, writer)
    # 不应抛异常
    wrapped("tool_start", tool_name="t", preview="args")
    wrapped._flush()

    content = writer.path.read_text(encoding="utf-8")
    assert "-> t" in content


# ============================================================================
# 8. DELEGATE_TASK_SCHEMA
# ============================================================================


def test_delegate_task_schema_structure():
    """delegate_task schema 结构正确。"""
    from app.agent.hermes.delegator import (
        DELEGATE_TASK_SCHEMA,
        get_delegate_tool_schema,
    )

    schema = get_delegate_tool_schema()
    assert schema == DELEGATE_TASK_SCHEMA
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "delegate_task"
    props = fn["parameters"]["properties"]
    assert "goal" in props
    assert "context" in props
    assert "tasks" in props
    # tasks 数组结构
    tasks_items = props["tasks"]["items"]
    assert "goal" in tasks_items["properties"]
    assert "context" in tasks_items["properties"]
    assert tasks_items["required"] == ["goal"]


# ============================================================================
# 9. Delegator 参数校验与深度超限
# ============================================================================


def test_delegator_rejects_missing_args(tmp_path, monkeypatch):
    """无 goal / tasks 参数时返回错误。"""
    from app.agent.hermes.delegator import Delegator

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    delegator = Delegator(db=None, user=MagicMock())

    async def _run():
        events = []
        async for ev in delegator.delegate({}, parent_executor=MagicMock()):
            events.append(ev)
        return events

    events = asyncio.run(_run())

    # 应该 yield 一个 _result 事件，包含错误信息
    assert len(events) == 1
    assert events[0]["type"] == "_result"
    payload = json.loads(events[0]["content"])
    assert "error" in payload
    assert "goal" in payload["error"] or "tasks" in payload["error"]


def test_delegator_rejects_depth_exceeded(tmp_path, monkeypatch):
    """委派深度超限时拒绝执行。"""
    from app.agent.hermes.delegator import (
        Delegator,
        delegation_depth_context,
        MAX_DELEGATION_DEPTH,
    )

    monkeypatch.setenv("SOAR_DELEGATION_CACHE_DIR", str(tmp_path))
    delegator = Delegator(db=None, user=MagicMock(), max_depth=MAX_DELEGATION_DEPTH)

    async def _run():
        # 模拟子代理上下文（depth=1），尝试再次委派
        with delegation_depth_context(MAX_DELEGATION_DEPTH):
            events = []
            async for ev in delegator.delegate(
                {"goal": "测试深度超限"}, parent_executor=MagicMock(),
            ):
                events.append(ev)
        return events

    events = asyncio.run(_run())

    assert len(events) == 1
    assert events[0]["type"] == "_result"
    payload = json.loads(events[0]["content"])
    assert "error" in payload
    assert "深度超限" in payload["error"]
    assert payload["depth"] == MAX_DELEGATION_DEPTH


# ============================================================================
# 10. executor 集成：delegate_task 装配
# ============================================================================


def test_executor_assembles_delegate_tool_schema():
    """executor 的 extra_tool_defs 中包含 delegate_task schema。"""
    # 通过源码检查（避免完整初始化 HermesAgentExecutor，需要 db/agent/user）
    import inspect
    from app.agent.hermes import executor as executor_mod

    src = inspect.getsource(executor_mod)
    assert "get_delegate_tool_schema" in src
    assert "delegate_task" in src
    assert '"delegate": "delegate"' in src or "'delegate': 'delegate'" in src or '"delegate"' in src


def test_executor_has_handle_delegate_call():
    """executor 有 _handle_delegate_call 方法。"""
    from app.agent.hermes.executor import HermesAgentExecutor

    assert hasattr(HermesAgentExecutor, "_handle_delegate_call")
    assert callable(getattr(HermesAgentExecutor, "_handle_delegate_call"))


# ============================================================================
# 11. SSE delegate 事件支持
# ============================================================================


def test_sse_event_dict_supports_delegate_type():
    """SSEEventDict 支持 delegate 类型和 result 字段嵌套。"""
    from app.agent.hermes.sse import make_event, SSEEventDict

    # 构造 delegate 事件，result 字段嵌套子事件 dict
    ev = make_event(
        "delegate",
        result={
            "subagent_id": "sa-0-abc",
            "task_index": 0,
            "event": {"type": "token", "content": "hello"},
        },
    )
    assert ev.type == "delegate"
    assert ev.result["subagent_id"] == "sa-0-abc"
    assert ev.result["event"]["type"] == "token"

    # 序列化
    sse_str = ev.to_sse()
    assert "delegate" in sse_str
    assert "sa-0-abc" in sse_str
    assert "hello" in sse_str
