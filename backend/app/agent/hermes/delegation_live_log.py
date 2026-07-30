"""子代理委派的实时只追加 transcript —— 移植自 Hermes ``tools/delegation_live_log.py``。

每次 ``delegate_task`` 分发为每个子任务创建一个 append-only、人类可读的日志：

    <cache_root>/delegation/live/<delegation_id>/task-<n>.log

文件在分发时预创建并写入 header（便于 ``tail -f`` 立即附加），随后子代理
每个事件追加一行：assistant 文本、思维、工具调用、工具结果、生命周期标记。
路径从 ``delegate_task`` 返回，父 agent（或用户）可观察子代理工作过程，
而非盲等汇总结果。

设计约束（与 Hermes 一致）：

* **永不抛入 agent 循环**：每次写入都 wrap，首次失败禁用 writer 并降级为
  debug 日志。
* **扛子代理崩溃**：每次写入用 append 模式打开——无长生命周期 handle，
  每个事件写入即 flush。
* **仅旁路**：不触碰消息内容，prompt caching 不受影响。
* **无配置旋钮**：保留期是模块常量（7 天），每次新分发时机会性清理。
* **强制脱敏**：每行写入前经 ``redact_sensitive_text(force=True)`` 脱敏——
  这些日志可能被沙箱读取，工具参数/结果常携带凭据（bearer header、.env dump、
  provider 错误回显 key）。

Soar 适配点：

1. 脱敏用 Soar 的 ``app.agent.hermes.redact.redact_sensitive_text``（已覆盖
   OpenAI/Anthropic/火山/通义/智谱/月之暗面 API Key + Bearer/JWT/连接串/PEM）。
2. transcript 根目录用 ``SOAR_DELEGATION_CACHE_DIR`` 环境变量配置，回退到
   ``/tmp/soar_delegation/live``（容器内可挂载）。
3. 事件类型映射适配 Soar 的 SSE 事件契约（start/token/tool_start/tool_end/done）。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "LIVE_RETENTION_DAYS",
    "LiveTranscriptWriter",
    "live_transcript_root",
    "new_live_delegation_id",
    "create_live_transcripts",
    "update_manifest_statuses",
    "prune_stale_live_dirs",
    "wrap_progress_callback",
]

# Live transcript 目录保留期（天），每次新分发时机会性清理
LIVE_RETENTION_DAYS = 7

# 每行截断预算（字符）。.log 是紧凑运维视图，非全保真记录——
# 子代理的执行记录（Execution）与 summary spill 文件承载完整文本。
_ASSISTANT_MAX = 600
_THINKING_MAX = 300
_ARGS_MAX = 220
_RESULT_MAX = 400
_KICKOFF_MAX = 500

# 流式 delta 缓冲，另一事件类型到达（或完成）时 flush 为一行 assistant 文本。
# 限制缓冲大小，防止巨大流式回复占用内存。
_STREAM_BUFFER_FLUSH_CHARS = 4000


def live_transcript_root() -> Path:
    """transcript 根目录（可配置，回退到 /tmp）。

    优先用 ``SOAR_DELEGATION_CACHE_DIR`` 环境变量；否则回退到系统临时目录。
    """
    cache_dir = os.environ.get("SOAR_DELEGATION_CACHE_DIR", "")
    if cache_dir:
        base = Path(cache_dir)
    else:
        base = Path("/tmp") / "soar_delegation"
    return base / "live"


def new_live_delegation_id() -> str:
    """生成委派 ID（与目录名一致）。"""
    return f"deleg_{uuid.uuid4().hex[:8]}"


def _one_line(text: Any, limit: int) -> str:
    """折叠为单行并截断，附省略字符数。"""
    s = str(text or "")
    s = " ".join(s.split())  # 折叠换行/连续空白
    if len(s) > limit:
        omitted = len(s) - limit
        s = s[:limit] + f" …(+{omitted} chars)"
    return s


def _redact(text: str) -> str:
    """写入 transcript 前强制脱敏凭据。

    这些日志可能被沙箱读取，事件渲染的数据恰是常携带密钥的类型：
    工具参数（curl 的 bearer header）、工具结果（.env dump、provider 错误回显
    key）、流式 assistant 文本。

    ``force=True``：这是安全边界，即使全局脱敏开关关闭也必须脱敏。
    redactor 不可用时扣留该行而非写入原始文本——丢失一行 debug 日志的代价
    远小于把活凭据写入沙箱可读文件。
    """
    if not text:
        return text
    try:
        from app.agent.hermes.redact import redact_sensitive_text

        return redact_sensitive_text(text, force=True) or ""
    except Exception:  # pragma: no cover - 核心模块；失败也不泄露
        return "[line withheld: redaction unavailable]"


class LiveTranscriptWriter:
    """单个子代理任务的 append-only 人类可读事件日志。

    所有方法 best-effort：首次写入失败翻转 ``_ok`` 为 False，后续调用变 no-op
    （debug 日志）。永不抛异常。
    """

    def __init__(
        self,
        delegation_id: str,
        task_index: int,
        goal: str,
        context: Optional[str] = None,
        root: Optional[Path] = None,
    ):
        self.delegation_id = delegation_id
        self.task_index = task_index
        self._ok = True
        self._lock = threading.Lock()
        self._stream_buf: List[str] = []
        self._stream_len = 0
        try:
            base = root if root is not None else live_transcript_root()
            d = base / delegation_id
            d.mkdir(parents=True, exist_ok=True)
            self.path: Optional[Path] = d / f"task-{task_index}.log"
            header = [
                "=== Soar subagent live transcript ===",
                f"delegation: {delegation_id}   task: {task_index}",
                # header 绕过 event()，所以这里也要脱敏——goal 字符串可能携带
                # 调用方粘贴的 key
                f"goal: {_redact(_one_line(goal, _KICKOFF_MAX))}",
                f"started: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                "(append-only; streams while the subagent runs — tail -f me)",
                "=" * 40,
            ]
            self.path.write_text("\n".join(header) + "\n", encoding="utf-8")
            self.event(
                "user",
                "kickoff: " + _one_line(goal, _KICKOFF_MAX)
                + (f" | context: {_one_line(context, _KICKOFF_MAX)}" if context else ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Live transcript init failed (%s task %s): %s",
                         delegation_id, task_index, exc)
            self._ok = False
            self.path = None

    # ── 底层 ────────────────────────────────────────────────────────────
    def event(self, role: str, text: str) -> None:
        """追加一行 ``HH:MM:SS role ⟩ text``。每次写入 flush。"""
        if not self._ok or self.path is None:
            return
        # 单一 choke point：所有 typed helper 都经过这里，脱敏一次覆盖
        # args/result/thinking/streamed text——后续新增 helper 也无法绕过
        line = f"{time.strftime('%H:%M:%S')} {role:<9}| {_redact(text)}\n"
        try:
            with self._lock:
                # 每次写入用 append 模式：无持有 handle，扛子代理崩溃，
                # close() 即 flush
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
        except Exception as exc:  # noqa: BLE001
            self._ok = False
            logger.debug("Live transcript write failed (%s): %s", self.path, exc)

    # ── typed helpers ────────────────────────────────────────────────────
    def assistant_text(self, text: str) -> None:
        t = _one_line(text, _ASSISTANT_MAX)
        if t:
            self.event("assistant", t)

    def thinking(self, text: str) -> None:
        t = _one_line(text, _THINKING_MAX)
        if t:
            self.event("think", t)

    def tool_start(self, name: str, args_preview: Any = None) -> None:
        self.flush_stream()
        args = _one_line(args_preview, _ARGS_MAX)
        self.event("tool", f"-> {name or '?'}({args})")

    def tool_result(
        self,
        name: str,
        result: Any = None,
        duration: Any = None,
        is_error: bool = False,
    ) -> None:
        status = "ERROR" if is_error else "ok"
        dur = ""
        try:
            if duration is not None:
                dur = f" {float(duration):.1f}s"
        except (TypeError, ValueError):
            pass
        self.event("result", f"{name or '?'} {status}{dur}: "
                             f"{_one_line(result, _RESULT_MAX)}")

    def marker(self, text: str) -> None:
        """生命周期标记：start / final / error / interrupt / budget。"""
        self.flush_stream()
        self.event("final", _one_line(text, _ASSISTANT_MAX))

    # ── 流式回复缓冲 ─────────────────────────────────────────────────────
    def add_stream_delta(self, delta: str) -> None:
        """缓冲流式 assistant 回复文本；flush 时合为一行。"""
        if not delta or not self._ok:
            return
        self._stream_buf.append(delta)
        self._stream_len += len(delta)
        if self._stream_len >= _STREAM_BUFFER_FLUSH_CHARS:
            self.flush_stream()

    def flush_stream(self) -> None:
        if not self._stream_buf:
            return
        text = "".join(self._stream_buf)
        self._stream_buf = []
        self._stream_len = 0
        self.assistant_text(text)

    # ── 事件 demux（子代理 SSE 事件 → transcript 行） ────────────────────
    def observe(
        self,
        event_type: Any,
        tool_name: Any = None,
        preview: Any = None,
        args: Any = None,
        **kwargs: Any,
    ) -> None:
        """把子代理事件映射到 transcript 行。

        适配 Soar 的 SSE 事件契约（start/token/tool_start/tool_end/done）。
        未知事件忽略。永不抛异常（event() 吞掉 I/O）。
        """
        et = str(event_type or "")
        if et == "tool_start":
            self.tool_start(str(tool_name or ""), preview if preview else args)
        elif et == "tool_end":
            self.tool_result(
                str(tool_name or ""),
                result=kwargs.get("result", preview),
                duration=kwargs.get("duration"),
                is_error=bool(kwargs.get("is_error")),
            )
        elif et == "token":
            # 流式 token：缓冲为 assistant 文本
            self.add_stream_delta(str(preview or ""))
        elif et == "start":
            self.event("start", _one_line(preview, _KICKOFF_MAX))
        elif et == "done":
            self.flush_stream()
            summary = kwargs.get("message") or preview
            parts = ["complete"]
            if summary:
                parts.append(f"summary: {_one_line(summary, _RESULT_MAX)}")
            self.marker(" ".join(parts))
        elif et == "error":
            self.flush_stream()
            self.event("error", _one_line(preview or kwargs.get("message"), _RESULT_MAX))
        elif et == "status":
            self.event("status", _one_line(preview or kwargs.get("message"), _ARGS_MAX))

    def finalize(self, entry: Dict[str, Any]) -> None:
        """从聚合结果条目写终止标记。

        补充 subagent.complete 事件不携带的退出原因细节
        （budget 耗尽 via exit_reason=max_iterations、错误等）。
        """
        parts = [f"end status={entry.get('status', '?')}"]
        exit_reason = entry.get("exit_reason")
        if exit_reason:
            parts.append(f"exit_reason={exit_reason}")
        if exit_reason == "max_iterations":
            parts.append("(iteration budget exhausted)")
        if entry.get("error"):
            parts.append(f"error: {_one_line(entry['error'], _RESULT_MAX)}")
        self.marker(" ".join(parts))


def wrap_progress_callback(inner_cb, writer: "LiveTranscriptWriter"):
    """包装子代理的进度回调，使事件同时落入日志。

    ``inner_cb`` 可为 None（无父展示）——包装器仍记录。
    Writer 失败永不传播；inner callback 行为不变（其自身异常由调用方按原样处理）。
    """

    def _cb(event_type, tool_name=None, preview=None, args=None, **kwargs):
        try:
            writer.observe(event_type, tool_name, preview, args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — 永不进入 agent 循环
            logger.debug("Live transcript observe failed: %s", exc)
        if inner_cb is not None:
            inner_cb(event_type, tool_name, preview, args, **kwargs)

    def _flush():
        try:
            writer.flush_stream()
        except Exception:  # noqa: BLE001
            pass
        inner_flush = getattr(inner_cb, "_flush", None)
        if callable(inner_flush):
            inner_flush()

    _cb._flush = _flush
    return _cb


# ── 分发时辅助 ────────────────────────────────────────────────────────────


def create_live_transcripts(
    task_list: List[Dict[str, Any]],
    context: Optional[str] = None,
    delegation_id: Optional[str] = None,
) -> "tuple[Optional[str], List[Optional[LiveTranscriptWriter]], List[str]]":
    """为每个任务创建预写 header 的 writer + manifest.json。

    返回 ``(delegation_id, writers, paths)``。顶层失败返回
    ``(None, [None]*n, [])`` 使委派不受影响。
    同时机会性清理过期 live 目录（保留期）。
    """
    n = len(task_list)
    try:
        prune_stale_live_dirs()
    except Exception:  # noqa: BLE001
        pass
    try:
        deleg_id = delegation_id or new_live_delegation_id()
        writers: List[Optional[LiveTranscriptWriter]] = []
        paths: List[str] = []
        for i, t in enumerate(task_list):
            w = LiveTranscriptWriter(
                deleg_id, i, str(t.get("goal", "")),
                context=t.get("context") or context,
            )
            writers.append(w if w.path is not None else None)
            if w.path is not None:
                paths.append(str(w.path))
        if not paths:
            return None, [None] * n, []
        _write_manifest(deleg_id, task_list, paths)
        return deleg_id, writers, paths
    except Exception as exc:  # noqa: BLE001
        logger.debug("Live transcript creation failed: %s", exc)
        return None, [None] * n, []


def _manifest_path(delegation_id: str) -> Path:
    return live_transcript_root() / delegation_id / "manifest.json"


def _write_manifest(
    delegation_id: str,
    task_list: List[Dict[str, Any]],
    paths: List[str],
) -> None:
    try:
        manifest = {
            "delegation_id": delegation_id,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "task_count": len(task_list),
            "tasks": [
                {
                    "index": i,
                    # manifest.json 与 .log 同目录（沙箱可读），同样需脱敏
                    "goal": _redact(str(t.get("goal", ""))[:500]),
                    "log": paths[i] if i < len(paths) else None,
                    "status": "running",
                }
                for i, t in enumerate(task_list)
            ],
        }
        _manifest_path(delegation_id).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Live transcript manifest write failed: %s", exc)


def update_manifest_statuses(
    delegation_id: Optional[str],
    results: List[Dict[str, Any]],
) -> None:
    """批次聚合后 best-effort 更新每任务状态。"""
    if not delegation_id:
        return
    try:
        mp = _manifest_path(delegation_id)
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        by_index = {r.get("task_index"): r for r in results if isinstance(r, dict)}
        for task in manifest.get("tasks", []):
            r = by_index.get(task.get("index"))
            if r is not None:
                task["status"] = r.get("status", task.get("status"))
                if r.get("exit_reason"):
                    task["exit_reason"] = r["exit_reason"]
        manifest["completed"] = time.strftime("%Y-%m-%d %H:%M:%S")
        mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Live transcript manifest update failed: %s", exc)


def prune_stale_live_dirs(max_age_days: int = LIVE_RETENTION_DAYS) -> int:
    """移除超过保留期的 live/<delegation_id> 目录。返回移除数。全 best-effort。"""
    removed = 0
    try:
        root = live_transcript_root()
        if not root.is_dir():
            return 0
        cutoff = time.time() - max_age_days * 86400
        for child in root.iterdir():
            try:
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
    except Exception as exc:  # noqa: BLE001
        logger.debug("Live transcript pruning failed: %s", exc)
    return removed
