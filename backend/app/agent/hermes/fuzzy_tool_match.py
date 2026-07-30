"""工具名模糊匹配 —— 简化自 Hermes ``tools/fuzzy_match.py`` 的多策略思路。

LLM 经常拼错工具名（``get_threat_intel`` → ``get_threatintel`` /
``threat_intel`` / ``get_threat_intel_info``）。直接返回 "Unknown tool"
会让 LLM 反复试探，浪费迭代预算。

本模块用多策略链找到最接近的已注册工具名，返回匹配结果 + did-you-mean 提示。
``tool_engine._execute_one`` 在工具名未命中注册表时调用。

策略链（从精确到模糊，命中即停）：

1. **exact** —— 精确匹配（大小写敏感）
2. **case_insensitive** —— 大小写不敏感
3. **underscore_hyphen** —— 下划线/连字符互换（``get-info`` → ``get_info``）
4. **normalize_separators** —— 去除所有分隔符（``getthreatintel`` → ``get_threat_intel``）
5. **levenshtein** —— 编辑距离 ≤ 2（处理拼写错误）
6. **token_subset** —— 工具名 token 是查询的子集（``threat_intel`` → ``get_threat_intel``）
7. **prefix_match** —— 前缀匹配（``get_threat`` → ``get_threat_intel``，唯一前缀时）

did-you-mean 提示：无精确匹配时，返回 top-3 候选 + 相似度分数，供
synthetic 工具结果回写给 LLM，引导其下次用正确名字。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

__all__ = [
    "FuzzyMatchResult",
    "fuzzy_match_tool_name",
    "did_you_mean_hint",
    "FUZZY_MATCH_THRESHOLD",
]


# 模糊匹配的最低相似度阈值（低于此值不视为匹配）
FUZZY_MATCH_THRESHOLD = 0.6


class FuzzyMatchResult:
    """工具名模糊匹配结果。"""

    def __init__(
        self,
        matched_name: Optional[str],
        strategy: str,
        confidence: float,
        candidates: list[tuple[str, float]],
    ):
        self.matched_name = matched_name  # 匹配到的工具名，None 表示未匹配
        self.strategy = strategy  # 命中的策略名
        self.confidence = confidence  # 置信度 0..1
        self.candidates = candidates  # top-N 候选 [(name, score)]

    @property
    def is_match(self) -> bool:
        return self.matched_name is not None

    def to_hint(self) -> str:
        """生成 did-you-mean 提示文本。"""
        if self.is_match:
            return (
                f"工具名 '{self.matched_name}' 已自动匹配（策略={self.strategy}, "
                f"置信度={self.confidence:.2f}）。下次请直接使用此名字。"
            )
        if not self.candidates:
            return "未找到匹配工具，请检查工具名或调用 tool_search 查询可用工具。"
        top = self.candidates[:3]
        names = ", ".join(f"'{n}' ({s:.2f})" for n, s in top)
        return f"工具名未精确匹配。你可能想要: {names}。请用正确名字重试。"


def fuzzy_match_tool_name(
    query: str,
    registered_names: list[str],
    *,
    threshold: float = FUZZY_MATCH_THRESHOLD,
) -> FuzzyMatchResult:
    """在已注册工具名中模糊匹配 ``query``。

    Args:
        query: LLM 请求的工具名（可能拼错）
        registered_names: 已注册的工具名列表
        threshold: 最低相似度阈值

    Returns:
        FuzzyMatchResult
    """
    if not query or not registered_names:
        return FuzzyMatchResult(None, "none", 0.0, [])

    # 1. 精确匹配
    for name in registered_names:
        if name == query:
            return FuzzyMatchResult(name, "exact", 1.0, [(name, 1.0)])

    # 2. 大小写不敏感
    query_lower = query.lower()
    for name in registered_names:
        if name.lower() == query_lower:
            return FuzzyMatchResult(name, "case_insensitive", 0.95, [(name, 0.95)])

    # 3. 下划线/连字符互换
    query_normalized_sep = re.sub(r'[-]', '_', query_lower)
    for name in registered_names:
        name_normalized_sep = re.sub(r'[-]', '_', name.lower())
        if name_normalized_sep == query_normalized_sep:
            return FuzzyMatchResult(name, "underscore_hyphen", 0.9, [(name, 0.9)])

    # 4. 去除所有分隔符
    query_no_sep = re.sub(r'[_\-.]', '', query_lower)
    candidates_no_sep = []
    for name in registered_names:
        name_no_sep = re.sub(r'[_\-.]', '', name.lower())
        if name_no_sep == query_no_sep:
            candidates_no_sep.append((name, 0.85))
    if candidates_no_sep:
        best = max(candidates_no_sep, key=lambda x: x[1])
        return FuzzyMatchResult(best[0], "normalize_separators", best[1], candidates_no_sep)

    # 5. Levenshtein 距离（编辑距离）
    levenshtein_candidates = []
    for name in registered_names:
        ratio = SequenceMatcher(None, query_lower, name.lower()).ratio()
        if ratio >= threshold:
            levenshtein_candidates.append((name, ratio))
    if levenshtein_candidates:
        levenshtein_candidates.sort(key=lambda x: -x[1])
        best = levenshtein_candidates[0]
        return FuzzyMatchResult(best[0], "levenshtein", best[1], levenshtein_candidates)

    # 6. token 子集匹配
    query_tokens = set(_tokenize(query_lower))
    if query_tokens:
        token_candidates = []
        for name in registered_names:
            name_tokens = set(_tokenize(name.lower()))
            if query_tokens.issubset(name_tokens) or name_tokens.issubset(query_tokens):
                ratio = len(query_tokens & name_tokens) / len(query_tokens | name_tokens)
                if ratio >= threshold:
                    token_candidates.append((name, ratio))
        if token_candidates:
            token_candidates.sort(key=lambda x: -x[1])
            best = token_candidates[0]
            return FuzzyMatchResult(best[0], "token_subset", best[1], token_candidates)

    # 7. 前缀匹配（唯一前缀时）
    prefix_candidates = [n for n in registered_names if n.lower().startswith(query_lower)]
    if len(prefix_candidates) == 1:
        return FuzzyMatchResult(prefix_candidates[0], "prefix_unique", 0.8, [(prefix_candidates[0], 0.8)])
    if len(prefix_candidates) > 1:
        # 多个前缀匹配，不自动选（歧义），但作为候选返回
        pass

    # 兜底：返回 top-3 候选供 did-you-mean
    all_candidates = []
    for name in registered_names:
        ratio = SequenceMatcher(None, query_lower, name.lower()).ratio()
        if ratio >= 0.3:  # 最低门槛，避免完全无关
            all_candidates.append((name, ratio))
    all_candidates.sort(key=lambda x: -x[1])
    return FuzzyMatchResult(None, "none", 0.0, all_candidates[:3])


def did_you_mean_hint(query: str, registered_names: list[str]) -> str:
    """快捷生成 did-you-mean 提示文本。"""
    result = fuzzy_match_tool_name(query, registered_names)
    return result.to_hint()


def _tokenize(name: str) -> list[str]:
    """把工具名拆分为 token（按下划线/连字符/点）。"""
    return [t for t in re.split(r'[_\-.]', name) if t]
