"""对话文本上的研判与 JSON 抽取。"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_DEFAULT_BLOCK_DURATION = "24h"
_VALID_DECISIONS = {"block_ip", "ignore", "need_human_approval"}

def _parse_action_decision_from_content(content: str, src_ip: str) -> dict:
    """从 LLM 文本回复中解析结构化决策 JSON。

    Args:
        content: LLM 输出的文本，预期包含 JSON。
        src_ip: 默认 target_ip（解析失败时使用）。

    Returns:
        结构化决策字典；解析失败时返回 ``need_human_approval`` 降级决策。
    """
    fallback = {
        "decision": "need_human_approval",
        "target_ip": src_ip,
        "reason": "Agent 输出无法解析为结构化决策，需人工确认",
        "duration": _DEFAULT_BLOCK_DURATION,
    }
    if not content:
        logger.warning("[Parse] LLM 输出为空，使用降级决策")
        return fallback

    candidate = _extract_json_object(content)
    if candidate is None:
        candidate = content.strip()

    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("[Parse] JSON 解析失败: %s, 原文=%s", exc, content)
        return fallback

    decision = data.get("decision")
    if decision not in _VALID_DECISIONS:
        logger.warning("[Parse] 决策值非法: %s，使用降级决策", decision)
        return fallback

    parsed = {
        "decision": decision,
        "target_ip": data.get("target_ip", src_ip),
        "reason": data.get("reason", ""),
        "duration": data.get("duration", _DEFAULT_BLOCK_DURATION),
    }
    logger.info("[Parse] 决策解析成功: %s", parsed)
    return parsed


def _extract_json_object(text: str) -> str | None:
    """从文本中抽取首个完整的 JSON 对象字符串。"""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
    return None
