"""LLM 错误分类器 —— 移植自 Hermes ``agent/error_classifier.py`` 的核心思路。

LLM 调用失败的原因多样，不同原因需要不同处理：

- ``rate_limit``      → 指数退避重试（429 / RateLimitError）
- ``overloaded``      → 服务端过载，退避重试（529 / OverloadedError）
- ``network``         → 网络瞬断，立即重试（ConnectionError / Timeout）
- ``auth``            → 凭据问题，不重试，提示用户检查配置（401 / 403）
- ``content_filter``  → 内容被过滤，不重试，提示用户改输入（400 content_policy）
- ``context_length``  → 上下文超长，不重试，触发压缩（400 context_length_exceeded）
- ``invalid_request`` → 请求格式错误，不重试（400 其他）
- ``server_error``    → 5xx，退避重试（500 / 502 / 503）
- ``unknown``         → 未知，保守不重试

返回 ``ErrorClassification``，调用方（``executor._call_llm``）根据
``should_retry`` + ``retry_after_s`` 决定是否重试及退避时长。

SOAR 适配：

- 覆盖 LangChain 的异常类型（``RateLimitError`` / ``AuthenticationError`` 等）
- 覆盖 OpenAI / Anthropic / 火山引擎 / 通义 的错误响应格式
- 错误信息送回 LLM 前必须经 ``redact.redact_sensitive_text``（防错误回显 API Key）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = [
    "ErrorClassification",
    "ErrorKind",
    "classify_llm_error",
    "should_retry_error",
    "extract_retry_after",
]


@dataclass(frozen=True)
class ErrorClassification:
    """LLM 错误的分类结果。"""

    kind: str  # ErrorKind 之一
    should_retry: bool
    retry_after_s: float = 0.0  # 建议退避秒数；0 表示立即
    message: str = ""  # 人类可读的错误描述（已脱敏）
    status_code: Optional[int] = None
    needs_context_compression: bool = False  # context_length 错误时为 True


class ErrorKind:
    """错误类型枚举（字符串常量，避免 enum 开销）。"""

    RATE_LIMIT = "rate_limit"
    OVERLOADED = "overloaded"
    NETWORK = "network"
    AUTH = "auth"
    CONTENT_FILTER = "content_filter"
    CONTEXT_LENGTH = "context_length"
    INVALID_REQUEST = "invalid_request"
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"


# 退避策略（秒）
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0
_NETWORK_RETRY_AFTER = 2.0
_SERVER_ERROR_RETRY_AFTER = 5.0


# ─── HTTP 状态码 → 错误类型 ──────────────────────────────────────

_STATUS_CODE_MAP: dict[int, tuple[str, bool, float]] = {
    400: (ErrorKind.INVALID_REQUEST, False, 0.0),
    401: (ErrorKind.AUTH, False, 0.0),
    403: (ErrorKind.AUTH, False, 0.0),
    404: (ErrorKind.INVALID_REQUEST, False, 0.0),
    408: (ErrorKind.NETWORK, True, _NETWORK_RETRY_AFTER),
    413: (ErrorKind.CONTEXT_LENGTH, False, 0.0),
    429: (ErrorKind.RATE_LIMIT, True, 0.0),  # retry-after 从响应头/体提取
    500: (ErrorKind.SERVER_ERROR, True, _SERVER_ERROR_RETRY_AFTER),
    502: (ErrorKind.SERVER_ERROR, True, _SERVER_ERROR_RETRY_AFTER),
    503: (ErrorKind.SERVER_ERROR, True, _SERVER_ERROR_RETRY_AFTER),
    504: (ErrorKind.NETWORK, True, _NETWORK_RETRY_AFTER),
    529: (ErrorKind.OVERLOADED, True, _SERVER_ERROR_RETRY_AFTER),
}


# ─── 错误消息关键词模式 ──────────────────────────────────────────

_RATE_LIMIT_PATTERNS = [
    re.compile(r'(?i)rate\s*limit'),
    re.compile(r'(?i)too\s*many\s*requests'),
    re.compile(r'(?i)请求过于频繁'),
    re.compile(r'(?i)qps\s*limit'),
    re.compile(r'(?i)throttl'),
]

_OVERLOADED_PATTERNS = [
    re.compile(r'(?i)overloaded'),
    re.compile(r'(?i)service\s*unavailable'),
    re.compile(r'(?i)服务暂时不可用'),
]

_NETWORK_PATTERNS = [
    re.compile(r'(?i)connection\s*(?:error|reset|refused|aborted|closed)'),
    re.compile(r'(?i)timeout|timed?\s*out'),
    re.compile(r'(?i)read\s*timeout'),
    re.compile(r'(?i)connect\s*timeout'),
    re.compile(r'(?i)network\s*(?:error|unreachable)'),
    re.compile(r'(?i)sslv3\s*alert|ssl\s*error|certificate\s*verify'),
    re.compile(r'(?i)remote\s*end\s*closed|peer\s*closed'),
    re.compile(r'(?i)连接.*(?:失败|超时|断开)'),
]

_AUTH_PATTERNS = [
    re.compile(r'(?i)invalid\s*api\s*key'),
    re.compile(r'(?i)incorrect\s*api\s*key'),
    re.compile(r'(?i)authentication\s*(?:error|failed)'),
    re.compile(r'(?i)unauthor'),
    re.compile(r'(?i)forbidden'),
    re.compile(r'(?i)permission\s*denied'),
    re.compile(r'(?i)(?:api[_-]?key|token).*(?:invalid|expired|missing)'),
    re.compile(r'(?i)认证失败|无权限|密钥.*无效'),
]

_CONTENT_FILTER_PATTERNS = [
    re.compile(r'(?i)content\s*(?:policy|filter|violation)'),
    re.compile(r'(?i)safety'),
    re.compile(r'(?i)moderation'),
    re.compile(r'(?i)内容.*(?:违规|过滤|审核)'),
]

_CONTEXT_LENGTH_PATTERNS = [
    re.compile(r'(?i)context\s*(?:length|window)'),
    re.compile(r'(?i)maximum\s*context'),
    re.compile(r'(?i)token\s*limit'),
    re.compile(r'(?i)too\s*many\s*tokens'),
    re.compile(r'(?i)context_length_exceeded'),
    re.compile(r'(?i)上下文.*超长|token.*超'),
]


def classify_llm_error(
    exc: BaseException,
    *,
    status_code: Optional[int] = None,
    response_body: Optional[str] = None,
) -> ErrorClassification:
    """分类 LLM 调用异常。

    Args:
        exc: 捕获的异常对象
        status_code: HTTP 状态码（若可从异常提取）
        response_body: 错误响应体（若可获取）

    Returns:
        ErrorClassification，含错误类型 + 重试策略 + 脱敏后的错误描述
    """
    # 1. 优先按状态码分类
    if status_code is not None and status_code in _STATUS_CODE_MAP:
        kind, should_retry, retry_after = _STATUS_CODE_MAP[status_code]
        msg = _extract_message(exc, response_body)
        needs_compress = kind == ErrorKind.CONTEXT_LENGTH
        # rate_limit 尝试从响应体提取 retry-after
        if kind == ErrorKind.RATE_LIMIT:
            retry_after = extract_retry_after(response_body) or retry_after or _BACKOFF_BASE
        return ErrorClassification(
            kind=kind,
            should_retry=should_retry,
            retry_after_s=retry_after,
            message=msg,
            status_code=status_code,
            needs_context_compression=needs_compress,
        )

    # 2. 按异常类型分类（LangChain / httpx / OpenAI SDK）
    exc_name = type(exc).__name__
    exc_module = type(exc).__module__

    if 'RateLimitError' in exc_name or 'RateLimit' in exc_name:
        return ErrorClassification(
            kind=ErrorKind.RATE_LIMIT,
            should_retry=True,
            retry_after_s=extract_retry_after(response_body) or _BACKOFF_BASE,
            message=_extract_message(exc, response_body),
        )
    if 'AuthenticationError' in exc_name or 'AuthError' in exc_name:
        return ErrorClassification(
            kind=ErrorKind.AUTH,
            should_retry=False,
            message=_extract_message(exc, response_body),
        )
    if 'Overloaded' in exc_name or 'OverloadedError' in exc_name:
        return ErrorClassification(
            kind=ErrorKind.OVERLOADED,
            should_retry=True,
            retry_after_s=_SERVER_ERROR_RETRY_AFTER,
            message=_extract_message(exc, response_body),
        )
    if any(net in exc_name for net in ('TimeoutError', 'TimeoutException', 'ConnectError', 'ConnectionError', 'ReadError')):
        return ErrorClassification(
            kind=ErrorKind.NETWORK,
            should_retry=True,
            retry_after_s=_NETWORK_RETRY_AFTER,
            message=_extract_message(exc, response_body),
        )

    # 3. 按错误消息关键词分类
    msg = _extract_message(exc, response_body)
    if msg:
        for pattern in _RATE_LIMIT_PATTERNS:
            if pattern.search(msg):
                return ErrorClassification(
                    kind=ErrorKind.RATE_LIMIT,
                    should_retry=True,
                    retry_after_s=extract_retry_after(response_body) or _BACKOFF_BASE,
                    message=msg,
                )
        for pattern in _CONTEXT_LENGTH_PATTERNS:
            if pattern.search(msg):
                return ErrorClassification(
                    kind=ErrorKind.CONTEXT_LENGTH,
                    should_retry=False,
                    message=msg,
                    needs_context_compression=True,
                )
        for pattern in _AUTH_PATTERNS:
            if pattern.search(msg):
                return ErrorClassification(
                    kind=ErrorKind.AUTH,
                    should_retry=False,
                    message=msg,
                )
        for pattern in _CONTENT_FILTER_PATTERNS:
            if pattern.search(msg):
                return ErrorClassification(
                    kind=ErrorKind.CONTENT_FILTER,
                    should_retry=False,
                    message=msg,
                )
        for pattern in _OVERLOADED_PATTERNS:
            if pattern.search(msg):
                return ErrorClassification(
                    kind=ErrorKind.OVERLOADED,
                    should_retry=True,
                    retry_after_s=_SERVER_ERROR_RETRY_AFTER,
                    message=msg,
                )
        for pattern in _NETWORK_PATTERNS:
            if pattern.search(msg):
                return ErrorClassification(
                    kind=ErrorKind.NETWORK,
                    should_retry=True,
                    retry_after_s=_NETWORK_RETRY_AFTER,
                    message=msg,
                )

    # 4. 兜底：未知错误，保守不重试
    return ErrorClassification(
        kind=ErrorKind.UNKNOWN,
        should_retry=False,
        message=msg or str(exc),
    )


def should_retry_error(classification: ErrorClassification, attempt: int) -> bool:
    """根据分类和当前重试次数决定是否重试。

    Args:
        classification: 错误分类
        attempt: 当前是第几次重试（从 1 开始）

    Returns:
        True 表示应重试
    """
    if not classification.should_retry:
        return False
    # 最多重试 3 次
    if attempt > 3:
        return False
    return True


def extract_retry_after(response_body: Optional[str]) -> Optional[float]:
    """从错误响应中提取 retry-after 秒数。

    支持：
    - HTTP ``Retry-After`` 头值（数字秒）
    - JSON 响应中的 ``retry_after`` / ``retry-after`` 字段
    - 错误消息中的 "try again in X seconds" 模式
    """
    if not response_body:
        return None
    try:
        # JSON 响应
        import json
        data = json.loads(response_body)
        if isinstance(data, dict):
            for key in ('retry_after', 'retry-after', 'retryAfter', 'wait_seconds'):
                v = data.get(key)
                if v is not None:
                    return float(v)
            error = data.get('error')
            if isinstance(error, dict):
                for key in ('retry_after', 'retry-after', 'retryAfter'):
                    v = error.get(key)
                    if v is not None:
                        return float(v)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # 文本模式
    m = re.search(r'(?i)try\s*again\s*in\s*(\d+(?:\.\d+)?)\s*(?:s|sec|second)', response_body)
    if m:
        return float(m.group(1))
    m = re.search(r'(?i)retry[- ]after[:\s]+(\d+(?:\.\d+)?)', response_body)
    if m:
        return float(m.group(1))
    return None


def _extract_message(exc: BaseException, response_body: Optional[str]) -> str:
    """从异常或响应体提取错误消息，并脱敏。"""
    from app.agent.hermes.redact import redact_sensitive_text

    raw = ""
    if response_body:
        raw = str(response_body)[:500]
    if not raw:
        raw = str(exc.args[0] if exc.args else exc)[:500]
    return redact_sensitive_text(raw, force=True)
