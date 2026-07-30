"""不可信工具结果包装（防 prompt injection）。

移植 Hermes ``tool_dispatch_helpers.py`` 的 ``_maybe_wrap_untrusted`` /
``_neutralize_delimiters`` 逻辑，适配 Soar 工具名。

不可信工具（知识库检索、HTTP 工具、文件查询等）的结果可能包含
外部内容，需包装在 ``<untrusted_tool_result>`` 标签内，并中和嵌入的
分隔符 token，防止恶意内容逃逸包装边界。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 不可信工具名集合（结果可能含外部内容）
_UNTRUSTED_TOOL_NAMES = frozenset({
    "search_knowledge_base",
    "query_kb_file",
    "web_search",
    "web_extract",
    "get_threat_intel",  # 威胁情报 API 返回外部数据
})

# 不可信工具名前缀（HTTP/OpenAPI 工具结果可能含外部内容）
_UNTRUSTED_TOOL_PREFIXES = ("http_", "openapi_")

# 包装标签
_UNTRUSTED_OPEN = "<untrusted_tool_result"
_UNTRUSTED_CLOSE = "</untrusted_tool_result>"

# 最小包装长度（短结果不包装，减少噪音）
_UNTRUSTED_WRAP_MIN_CHARS = 32

# 分隔符 token 中和正则（不区分大小写）
# 把嵌入的 ``untrusted_tool_result`` 文本中和为 ``untrusted-tool-result``（连字符），
# 防止恶意内容伪造包装边界。
_DELIMITER_TOKEN_RE = re.compile(r"untrusted_tool_result", re.IGNORECASE)


def is_untrusted_tool(name: str | None) -> bool:
    """判断工具结果是否需要不可信包装。

    Args:
        name: 工具名

    Returns:
        True 表示结果需包装在 ``<untrusted_tool_result>`` 内
    """
    if not name:
        return False
    if name in _UNTRUSTED_TOOL_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in _UNTRUSTED_TOOL_PREFIXES)


def neutralize_delimiters(content: str) -> str:
    """中和内容中嵌入的分隔符 token。

    把 ``untrusted_tool_result``（下划线）替换为 ``untrusted-tool-result``（连字符），
    防止恶意内容通过伪造 ``</untrusted_tool_result>`` 标签逃逸包装边界。

    Args:
        content: 原始内容

    Returns:
        中和后的内容
    """
    if not content:
        return content
    return _DELIMITER_TOKEN_RE.sub("untrusted-tool-result", content)


def maybe_wrap_untrusted(name: str, content: Any) -> Any:
    """按需包装不可信工具结果。

    与 Hermes 完全一致的逻辑：
    - 非不可信工具 → 原样返回
    - 不可信工具 + 字符串内容 → 包装在 ``<untrusted_tool_result source="...">`` 内
    - 不可信工具 + 多模态列表内容 → 包装每个文本 part

    包装前会先 ``neutralize_delimiters`` 中和嵌入的分隔符。
    短结果（< _UNTRUSTED_WRAP_MIN_CHARS 字符）不包装。

    Args:
        name: 工具名
        content: 工具返回的原始内容

    Returns:
        包装后的内容（字符串或多模态列表）
    """
    if not is_untrusted_tool(name):
        return content

    # 多模态列表（OpenAI content parts 格式）
    if isinstance(content, list):
        wrapped_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if len(text) >= _UNTRUSTED_WRAP_MIN_CHARS:
                    text = _wrap_text(name, text)
                wrapped_parts.append({**part, "text": text})
            else:
                wrapped_parts.append(part)
        return wrapped_parts

    # 字符串内容
    if isinstance(content, str):
        if len(content) < _UNTRUSTED_WRAP_MIN_CHARS:
            return content
        return _wrap_text(name, content)

    # dict / 其他类型 → 序列化为 JSON 字符串后包装
    try:
        text = json.dumps(content, ensure_ascii=False, default=str)
    except Exception:
        text = str(content)
    if len(text) < _UNTRUSTED_WRAP_MIN_CHARS:
        return content
    return _wrap_text(name, text)


def _wrap_text(source: str, text: str) -> str:
    """包装单段文本。"""
    neutralized = neutralize_delimiters(text)
    return f'{_UNTRUSTED_OPEN} source="{source}">\n{neutralized}\n{_UNTRUSTED_CLOSE}'
