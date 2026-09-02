"""消息消毒 —— 移植自 Hermes ``agent/message_sanitization.py`` 的核心思路。

送入 LLM 前对消息列表做最后消毒：

1. **剥离注入残留**：上游 ``untrusted.maybe_wrap_untrusted`` 已包装不可信内容，
   但若包装被破坏（LLM 误解析、转义错误），这里做兜底扫描。
2. **不可信标记检查**：确认所有 ``<untrusted_tool_result>`` 块成对闭合，
   未闭合的块会被中和（转义为纯文本）。
3. **凭据扫描**：消息中若意外含 API Key（如用户粘贴了配置），送 LLM 前脱敏。
4. **超长消息截断**：单条消息超过阈值时截断（防单条消息撑爆窗口）。

与 ``threat_scanner`` 的分工：

- ``threat_scanner`` 检测并记录威胁，不修改内容（包装由 ``untrusted`` 做）
- ``message_sanitization`` 是最后一道防线：扫描已组装的消息列表，
  兜底处理未包装的注入 + 凭据脱敏 + 超长截断

调用时机：``executor._call_llm`` 前，``context_compressor.maybe_compress`` 之后。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.agent.hermes.redact import redact_sensitive_text
from app.agent.hermes.threat_scanner import scan_for_threats

logger = logging.getLogger(__name__)

__all__ = [
    "sanitize_messages",
    "sanitize_text",
    "check_untrusted_blocks",
    "MAX_MESSAGE_CHARS",
]


# 单条消息内容字符上限（超过则截断，防单条撑爆窗口）
MAX_MESSAGE_CHARS = 100_000


# 不可信包装标签
_UNTRUSTED_OPEN = re.compile(r'<untrusted_tool_result\s+source="[^"]*"\s*>', re.IGNORECASE)
_UNTRUSTED_CLOSE = re.compile(r'</untrusted_tool_result>', re.IGNORECASE)
# 中和后的 token（与 untrusted.neutralize_delimiters 一致）
_NEUTRALIZED_TOKEN = "untrusted-tool-result"


def sanitize_messages(
    messages: list[dict],
    *,
    redact_credentials: bool = True,
    truncate_long: bool = True,
    scan_injection: bool = True,
) -> list[dict]:
    """消毒消息列表（返回新列表，不修改原列表）。

    Args:
        messages: OpenAI 格式消息列表
        redact_credentials: 是否扫描并脱敏凭据（默认 True）
        truncate_long: 是否截断超长消息（默认 True）
        scan_injection: 是否扫描注入威胁（默认 True，仅记录不阻断）

    Returns:
        消毒后的消息列表
    """
    if not messages:
        return messages

    sanitized: list[dict] = []
    for msg in messages:
        new_msg = dict(msg)
        role = new_msg.get("role", "")
        content = new_msg.get("content")

        if content is None:
            sanitized.append(new_msg)
            continue

        # 字符串内容
        if isinstance(content, str):
            content = sanitize_text(
                content,
                redact_credentials=redact_credentials,
                truncate_long=truncate_long,
                scan_injection=scan_injection,
            )
            new_msg["content"] = content
        # 多模态列表内容（OpenAI content parts）
        elif isinstance(content, list):
            new_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    text = sanitize_text(
                        text,
                        redact_credentials=redact_credentials,
                        truncate_long=truncate_long,
                        scan_injection=scan_injection,
                    )
                    new_parts.append({**part, "text": text})
                else:
                    new_parts.append(part)
            new_msg["content"] = new_parts

        sanitized.append(new_msg)

    # 全局检查：不可信块是否成对闭合
    if scan_injection:
        check_untrusted_blocks(sanitized)

    return sanitized


def sanitize_text(
    text: str,
    *,
    redact_credentials: bool = True,
    truncate_long: bool = True,
    scan_injection: bool = True,
) -> str:
    """消毒单段文本。"""
    if not text:
        return text

    result = text

    # 1. 凭据脱敏
    if redact_credentials:
        result = redact_sensitive_text(result, force=True)

    # 2. 超长截断
    if truncate_long and len(result) > MAX_MESSAGE_CHARS:
        result = result[:MAX_MESSAGE_CHARS] + "\n... [消息过长，已截断]"
        logger.warning("消息过长已截断: %d -> %d 字符", len(text), MAX_MESSAGE_CHARS)

    # 3. 注入扫描（仅记录，不阻断 —— 包装由 untrusted 模块负责）
    if scan_injection:
        findings = scan_for_threats(result, scope="context")
        if findings:
            logger.warning(
                "消息中发现威胁模式（已记录，未阻断）: %s。"
                "若来自不可信工具结果，应已被 <untrusted_tool_result> 包装。",
                findings,
            )

    return result


def check_untrusted_blocks(messages: list[dict]) -> bool:
    """检查消息列表中所有 ``<untrusted_tool_result>`` 块是否成对闭合。

    未闭合的块会被中和：开标签转义为纯文本，防 LLM 误认为指令。

    Returns:
        True 表示所有块成对闭合；False 表示有未闭合块被中和。
    """
    all_balanced = True
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            new_content, balanced = _balance_untrusted_in_text(content)
            if not balanced:
                all_balanced = False
                msg["content"] = new_content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    new_text, balanced = _balance_untrusted_in_text(text)
                    if not balanced:
                        all_balanced = False
                        part["text"] = new_text
    return all_balanced


def _balance_untrusted_in_text(text: str) -> tuple[str, bool]:
    """中和文本中未闭合的 ``<untrusted_tool_result>`` 块。

    策略：统计开/闭标签数。若不平衡，把所有未配对的开标签转义为
    ``&lt;untrusted_tool_result&gt;``（HTML 转义），使其不被 LLM 解析为指令。

    Returns:
        (处理后的文本, 是否原本就平衡)
    """
    opens = _UNTRUSTED_OPEN.findall(text)
    closes = _UNTRUSTED_CLOSE.findall(text)

    if len(opens) == len(closes):
        return text, True

    # 不平衡：中和所有开标签（保守策略，防 LLM 误解析）
    # 闭标签若多余也中和
    def _escape_open(m: re.Match) -> str:
        return f"&lt;{_NEUTRALIZED_TOKEN} source=&quot;{m.group(0)}&quot;&gt;"

    def _escape_close(m: re.Match) -> str:
        return f"&lt;/{_NEUTRALIZED_TOKEN}&gt;"

    # 简化：不平衡时整体转义所有标签
    new_text = _UNTRUSTED_OPEN.sub(_escape_open, text)
    new_text = _UNTRUSTED_CLOSE.sub(_escape_close, new_text)
    logger.warning(
        "检测到未闭合的 untrusted_tool_result 块（开=%d 闭=%d），已中和转义",
        len(opens), len(closes),
    )
    return new_text, False
