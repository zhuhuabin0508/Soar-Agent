"""中间件系统 —— 借鉴 Hermes ``agent/shell_hooks.py`` + ``agent/verify_hooks.py`` 钩子模式。

提供 4 个钩子点，支撑等保审计日志、参数改写、执行包装、限流等横切关注点：

1. ``before_tool_call``    —— 工具调用前（可改写参数、阻断调用）
2. ``after_tool_call``     —— 工具调用后（可改写结果、记录审计）
3. ``before_llm_call``     —— LLM 调用前（可改写 messages、阻断调用）
4. ``after_llm_call``      —— LLM 调用后（可改写响应、记录审计）

设计原则：

- **不侵入业务代码**：``tool_engine`` / ``executor`` 只在固定点位调用
  ``middleware_registry.invoke_*``，中间件逻辑全在中间件类内。
- **有序执行**：中间件按 priority 升序执行（数字小先执行）。
- **可短路**：``before_*`` 中间件返回 ``ShortCircuitResult`` 可短路，
  跳过后续中间件和实际调用，直接返回合成结果。
- **异常隔离**：单个中间件异常不影响其他中间件和主流程（捕获 + 日志）。
- **per-agent 配置**：中间件列表从 ``Agent.tool_configs.middlewares`` 加载，
  不同 Agent 可启用不同中间件组合。

内置中间件：

- ``AuditMiddleware``     —— 等保审计日志（工具调用 + LLM 调用全记录）
- ``RedactMiddleware``    —— 日志脱敏（调用 ``redact`` 模块）
- ``RateLimitMiddleware`` —— LLM 调用限流（防打爆配额）
- ``TimingMiddleware``    —— 调用耗时统计
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.agent.hermes.redact import redact_sensitive_text, redact_url_credentials, redact_headers

logger = logging.getLogger(__name__)

__all__ = [
    "MiddlewareContext",
    "ToolCallRequest",
    "ToolCallResponse",
    "LLMCallRequest",
    "LLMCallResponse",
    "ShortCircuitResult",
    "BaseMiddleware",
    "AuditMiddleware",
    "RedactMiddleware",
    "RateLimitMiddleware",
    "TimingMiddleware",
    "MiddlewareRegistry",
]


@dataclass
class MiddlewareContext:
    """中间件执行上下文（per-turn，所有钩子共享）。"""

    agent_id: int
    user_id: int
    session_id: str = ""
    # 工具调用历史（供 verification / guardrail 查询）
    tool_history: list[dict] = field(default_factory=list)
    # 已确认的事实（供 verification 查询）
    confirmed_facts: dict[str, Any] = field(default_factory=dict)
    # 中间件可附加的元数据（审计用）
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRequest:
    """工具调用请求（before_tool_call 的输入）。"""

    tool_name: str
    arguments: dict
    tool_call_id: str


@dataclass
class ToolCallResponse:
    """工具调用响应（after_tool_call 的输入/输出）。"""

    tool_name: str
    tool_call_id: str
    result: Any
    is_error: bool = False
    duration_ms: int = 0


@dataclass
class LLMCallRequest:
    """LLM 调用请求（before_llm_call 的输入）。"""

    messages: list[dict]
    tools: list[dict]
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024


@dataclass
class LLMCallResponse:
    """LLM 调用响应（after_llm_call 的输入/输出）。"""

    content: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    model: str = ""
    duration_ms: int = 0


@dataclass
class ShortCircuitResult:
    """短路结果：before_* 中间件返回此对象可跳过实际调用。

    ``result`` 字段类型取决于钩子点：
    - before_tool_call → ToolCallResponse
    - before_llm_call → LLMCallResponse
    """

    result: Any
    reason: str = ""


class BaseMiddleware:
    """中间件基类。子类按需重写钩子方法。"""

    name: str = "base"
    priority: int = 100  # 数字小先执行

    def before_tool_call(
        self, request: ToolCallRequest, ctx: MiddlewareContext
    ) -> Optional[ShortCircuitResult]:
        """工具调用前钩子。返回 ShortCircuitResult 可短路。"""
        return None

    def after_tool_call(
        self, response: ToolCallResponse, ctx: MiddlewareContext
    ) -> ToolCallResponse:
        """工具调用后钩子。可改写 response 并返回。"""
        return response

    def before_llm_call(
        self, request: LLMCallRequest, ctx: MiddlewareContext
    ) -> Optional[ShortCircuitResult]:
        """LLM 调用前钩子。返回 ShortCircuitResult 可短路。"""
        return None

    def after_llm_call(
        self, response: LLMCallResponse, ctx: MiddlewareContext
    ) -> LLMCallResponse:
        """LLM 调用后钩子。可改写 response 并返回。"""
        return response


# ─── 内置中间件 ──────────────────────────────────────────────────


class AuditMiddleware(BaseMiddleware):
    """等保审计中间件：记录所有工具调用和 LLM 调用到日志。

    等保要求：所有安全相关操作必须可审计、可追溯。
    记录字段：时间、用户、Agent、工具/模型、参数（脱敏）、结果摘要、耗时。
    """

    name = "audit"
    priority = 10  # 最先执行，记录原始请求

    def __init__(self, audit_logger: Optional[Callable[[dict], None]] = None):
        """audit_logger: 自定义审计日志处理器。None 用默认 logger.info。"""
        self._audit_logger = audit_logger or self._default_logger

    def _default_logger(self, entry: dict) -> None:
        logger.info("审计日志: %s", entry)

    def before_tool_call(self, request: ToolCallRequest, ctx: MiddlewareContext) -> Optional[ShortCircuitResult]:
        entry = {
            "type": "tool_call",
            "phase": "before",
            "timestamp": _now_iso(),
            "agent_id": ctx.agent_id,
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "tool_name": request.tool_name,
            "tool_call_id": request.tool_call_id,
            "arguments_redacted": redact_sensitive_text(str(request.arguments), force=True),
        }
        try:
            self._audit_logger(entry)
        except Exception as exc:
            logger.warning("审计日志写入失败: %s", exc)
        return None

    def after_tool_call(self, response: ToolCallResponse, ctx: MiddlewareContext) -> ToolCallResponse:
        # tool_history 累积已由 tool_engine._execute_one 统一负责（核心职责，不依赖中间件）
        # 此处只做审计日志记录，避免重复累积
        entry = {
            "type": "tool_call",
            "phase": "after",
            "timestamp": _now_iso(),
            "agent_id": ctx.agent_id,
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "tool_name": response.tool_name,
            "tool_call_id": response.tool_call_id,
            "is_error": response.is_error,
            "duration_ms": response.duration_ms,
            "result_summary": _summarize(response.result),
        }
        try:
            self._audit_logger(entry)
        except Exception as exc:
            logger.warning("审计日志写入失败: %s", exc)
        return response

    def before_llm_call(self, request: LLMCallRequest, ctx: MiddlewareContext) -> Optional[ShortCircuitResult]:
        entry = {
            "type": "llm_call",
            "phase": "before",
            "timestamp": _now_iso(),
            "agent_id": ctx.agent_id,
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "model": request.model,
            "messages_count": len(request.messages),
            "tools_count": len(request.tools),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        try:
            self._audit_logger(entry)
        except Exception as exc:
            logger.warning("审计日志写入失败: %s", exc)
        return None

    def after_llm_call(self, response: LLMCallResponse, ctx: MiddlewareContext) -> LLMCallResponse:
        entry = {
            "type": "llm_call",
            "phase": "after",
            "timestamp": _now_iso(),
            "agent_id": ctx.agent_id,
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "model": response.model,
            "content_length": len(response.content) if response.content else 0,
            "tool_calls_count": len(response.tool_calls),
            "usage": response.usage,
            "duration_ms": response.duration_ms,
        }
        try:
            self._audit_logger(entry)
        except Exception as exc:
            logger.warning("审计日志写入失败: %s", exc)
        return response


class RedactMiddleware(BaseMiddleware):
    """脱敏中间件：确保日志和 LLM 输入中不含凭据。

    - before_llm_call：对 messages 做凭据脱敏（防用户粘贴配置泄露）
    - after_tool_call：对 HTTP 工具的实际请求 URL/headers 做脱敏日志
    """

    name = "redact"
    priority = 20

    def before_llm_call(self, request: LLMCallRequest, ctx: MiddlewareContext) -> Optional[ShortCircuitResult]:
        from app.agent.hermes.message_sanitization import sanitize_messages
        request.messages = sanitize_messages(
            request.messages,
            redact_credentials=True,
            truncate_long=True,
            scan_injection=True,
        )
        return None


class RateLimitMiddleware(BaseMiddleware):
    """LLM 调用限流中间件：防打爆配额。

    简单令牌桶：每分钟最多 N 次调用。超限返回 ShortCircuitResult
    携带限流错误，跳过实际 LLM 调用。
    """

    name = "rate_limit"
    priority = 30

    def __init__(self, max_calls_per_minute: int = 60):
        self._max = max_calls_per_minute
        self._window_start: float = time.time()
        self._count = 0

    def before_llm_call(self, request: LLMCallRequest, ctx: MiddlewareContext) -> Optional[ShortCircuitResult]:
        now = time.time()
        # 重置窗口
        if now - self._window_start >= 60.0:
            self._window_start = now
            self._count = 0
        self._count += 1
        if self._count > self._max:
            logger.warning(
                "LLM 调用限流: count=%d, max=%d/min, agent_id=%s",
                self._count, self._max, ctx.agent_id,
            )
            return ShortCircuitResult(
                result=LLMCallResponse(
                    content="",
                    usage={},
                    model=request.model,
                ),
                reason=f"rate_limited: 超过每分钟 {self._max} 次调用上限",
            )
        return None


class TimingMiddleware(BaseMiddleware):
    """耗时统计中间件：记录工具和 LLM 调用耗时。"""

    name = "timing"
    priority = 40

    def __init__(self):
        self._tool_start: dict[str, float] = {}
        self._llm_start: float = 0.0

    def before_tool_call(self, request: ToolCallRequest, ctx: MiddlewareContext) -> Optional[ShortCircuitResult]:
        self._tool_start[request.tool_call_id] = time.time()
        return None

    def after_tool_call(self, response: ToolCallResponse, ctx: MiddlewareContext) -> ToolCallResponse:
        start = self._tool_start.pop(response.tool_call_id, None)
        if start is not None:
            response.duration_ms = int((time.time() - start) * 1000)
        return response

    def before_llm_call(self, request: LLMCallRequest, ctx: MiddlewareContext) -> Optional[ShortCircuitResult]:
        self._llm_start = time.time()
        return None

    def after_llm_call(self, response: LLMCallResponse, ctx: MiddlewareContext) -> LLMCallResponse:
        if self._llm_start:
            response.duration_ms = int((time.time() - self._llm_start) * 1000)
            self._llm_start = 0.0
        return response


# ─── 中间件注册表 ────────────────────────────────────────────────


class MiddlewareRegistry:
    """中间件注册表：管理有序中间件列表，提供 4 个钩子点的派发。"""

    # 内置中间件名 → 工厂
    BUILTIN_FACTORIES: dict[str, Callable[..., BaseMiddleware]] = {
        "audit": AuditMiddleware,
        "redact": RedactMiddleware,
        "rate_limit": RateLimitMiddleware,
        "timing": TimingMiddleware,
    }

    def __init__(self):
        self._middlewares: list[BaseMiddleware] = []

    def register(self, middleware: BaseMiddleware) -> None:
        """注册中间件（按 priority 升序插入）。"""
        self._middlewares.append(middleware)
        self._middlewares.sort(key=lambda m: m.priority)
        logger.debug("已注册中间件: %s (priority=%d)", middleware.name, middleware.priority)

    def register_builtin(self, name: str, **kwargs) -> None:
        """按名注册内置中间件。"""
        factory = self.BUILTIN_FACTORIES.get(name)
        if factory is None:
            raise ValueError(f"未知内置中间件: {name}，可选: {list(self.BUILTIN_FACTORIES.keys())}")
        mw = factory(**kwargs)
        self.register(mw)

    @classmethod
    def from_agent_config(cls, tool_configs: dict | None) -> "MiddlewareRegistry":
        """从 Agent.tool_configs.middlewares 加载中间件配置。

        配置格式::

            tool_configs = {
                "middlewares": [
                    {"name": "audit", "config": {}},
                    {"name": "redact"},
                    {"name": "rate_limit", "config": {"max_calls_per_minute": 30}},
                ]
            }
        """
        registry = cls()
        if not isinstance(tool_configs, dict):
            return registry
        middlewares_config = tool_configs.get("middlewares", [])
        if not isinstance(middlewares_config, list):
            return registry
        for entry in middlewares_config:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            config = entry.get("config", {}) or {}
            if name and name in cls.BUILTIN_FACTORIES:
                try:
                    registry.register_builtin(name, **config)
                except Exception as exc:
                    logger.warning("中间件 %s 注册失败: %s", name, exc)
        return registry

    def invoke_before_tool_call(
        self, request: ToolCallRequest, ctx: MiddlewareContext
    ) -> Optional[ShortCircuitResult]:
        """派发 before_tool_call 钩子。返回 ShortCircuitResult 表示短路。"""
        for mw in self._middlewares:
            try:
                result = mw.before_tool_call(request, ctx)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning("中间件 %s before_tool_call 异常: %s", mw.name, exc)
        return None

    def invoke_after_tool_call(
        self, response: ToolCallResponse, ctx: MiddlewareContext
    ) -> ToolCallResponse:
        """派发 after_tool_call 钩子。"""
        for mw in self._middlewares:
            try:
                response = mw.after_tool_call(response, ctx)
            except Exception as exc:
                logger.warning("中间件 %s after_tool_call 异常: %s", mw.name, exc)
        return response

    def invoke_before_llm_call(
        self, request: LLMCallRequest, ctx: MiddlewareContext
    ) -> Optional[ShortCircuitResult]:
        """派发 before_llm_call 钩子。返回 ShortCircuitResult 表示短路。"""
        for mw in self._middlewares:
            try:
                result = mw.before_llm_call(request, ctx)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning("中间件 %s before_llm_call 异常: %s", mw.name, exc)
        return None

    def invoke_after_llm_call(
        self, response: LLMCallResponse, ctx: MiddlewareContext
    ) -> LLMCallResponse:
        """派发 after_llm_call 钩子。"""
        for mw in self._middlewares:
            try:
                response = mw.after_llm_call(response, ctx)
            except Exception as exc:
                logger.warning("中间件 %s after_llm_call 异常: %s", mw.name, exc)
        return response


def _now_iso() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat()


def _summarize(result: Any, max_chars: int = 200) -> str:
    """生成结果摘要（用于审计日志，避免日志过大）。"""
    if result is None:
        return "null"
    s = str(result)
    if isinstance(result, dict) and "error" in result:
        s = f"error: {result.get('error')}"
    if len(s) > max_chars:
        s = s[:max_chars] + f"... (+{len(s) - max_chars} chars)"
    return redact_sensitive_text(s, force=True)
