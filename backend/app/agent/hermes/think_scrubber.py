"""流式思维块清洗器 —— 移植自 Hermes ``agent/think_scrubber.py``。

为什么需要状态机（而非简单正则）：

LLM（DeepSeek-R1、Qwen3、MiniMax-M2.7 等）流式输出
``<think>...</think>`` 推理块时，逐 delta 到达：

    delta1 = "<think>"
    delta2 = "Let me check their config"
    delta3 = "</think>"

逐 delta 正则清洗会破坏下游消费者依赖的状态：delta1 被整体擦除，
下游状态机看不到开标签，把 delta2 当普通内容，推理就泄露给用户。

SOAR 场景尤其关键：用户需求 #3 要求"输出必须遵循预定义 JSON Schema"，
泄露的 ``<think>`` 标签会破坏 JSON 解析，导致下游 SOAR 平台无法执行。

本模块在上游层集中状态机，每个 ``stream_delta_callback`` 看到的文本
都已移除推理块。delta 边界处的部分标签被暂存，等下个 delta 解析；
流结束时 ``flush()`` 显化任何被暂存的、最终不是真标签的文本。

用法::

    scrubber = StreamingThinkScrubber()
    scrubber.reset()  # 每个 turn 开头
    for delta in stream:
        visible = scrubber.feed(delta)
        if visible:
            emit(visible)
    tail = scrubber.flush()  # 流结束
    if tail:
        emit(tail)

标签变体（大小写不敏感）：
  ``<think>``, ``<thinking>``, ``<reasoning>``, ``<thought>``,
  ``<REASONING_SCRATCHPAD>``。

开标签的块边界规则：仅当开标签出现在流开头、换行后（可选后随空白）、
或当前行只输出了空白时，才视为推理块开标签。这防止正文中*提及*标签名
（如 ``"use <think> tags here"``）被误擦除。闭合对（``<think>X</think>``）
无论位置一律擦除；闭合对是有意的、有界构造。
"""
from __future__ import annotations

from typing import Tuple

__all__ = ["StreamingThinkScrubber", "strip_think_blocks", "extract_think_blocks"]


import re as _re

# 思维块正则：匹配 <think>...</think> 等变体（非贪婪，大小写不敏感）
_THINK_PATTERN = _re.compile(
    r"<(?P<tag>think|thinking|reasoning|thought|REASONING_SCRATCHPAD)>"
    r"(?P<content>.*?)</(?P=tag)>",
    _re.DOTALL | _re.IGNORECASE,
)


def extract_think_blocks(text: str) -> tuple[str, str]:
    """提取思维块内容，返回 (思考内容, 清洗后文本)。

    与 ``strip_think_blocks`` 配合使用：本函数用正则提取 ``<think>...</think>``
    块内的文本（供前端展示思考过程），``strip_think_blocks`` 负责流式状态机
    清洗（处理部分标签/孤儿闭标签等边界情况）。

    Args:
        text: LLM 原始响应文本。

    Returns:
        (thinking_content, clean_text)
        - thinking_content: 所有思维块内容拼接（无块时为空串）
        - clean_text: 移除完整思维块后的文本（再交由 strip_think_blocks 处理边界）
    """
    if not text:
        return "", text
    parts: list[str] = []

    def _collect(m: _re.Match) -> str:
        parts.append(m.group("content"))
        return ""

    clean = _THINK_PATTERN.sub(_collect, text)
    return "\n".join(parts), clean


class StreamingThinkScrubber:
    """流式推理/思维块的有状态清洗器。

    状态机：
      - ``_in_block``：进入已开块后为 True，等待闭标签。块内文本全丢弃。
      - ``_buf``：暂存的部分标签尾。下个 ``feed()`` 或 ``flush()`` 显化/丢弃。
      - ``_last_emitted_ended_newline``：最近一次发射是否以 ``\\n`` 结尾，
        或还没发射任何内容（流开头算边界）。用于判断位置 0 的开标签是否在块边界。
    """

    _OPEN_TAG_NAMES: Tuple[str, ...] = (
        "think",
        "thinking",
        "reasoning",
        "thought",
        "REASONING_SCRATCHPAD",
    )

    # 物化字面标签串，热路径用字符串操作而非每次 feed 编译正则。
    _OPEN_TAGS: Tuple[str, ...] = tuple(f"<{name}>" for name in _OPEN_TAG_NAMES)
    _CLOSE_TAGS: Tuple[str, ...] = tuple(f"</{name}>" for name in _OPEN_TAG_NAMES)

    # 预计算最长标签（部分标签暂存上限）。
    _MAX_TAG_LEN: int = max(len(tag) for tag in _OPEN_TAGS + _CLOSE_TAGS)

    def __init__(self) -> None:
        self._in_block: bool = False
        self._buf: str = ""
        self._last_emitted_ended_newline: bool = True

    def reset(self) -> None:
        """重置所有状态。每个新 turn 开头调用。"""
        self._in_block = False
        self._buf = ""
        self._last_emitted_ended_newline = True

    def feed(self, text: str) -> str:
        """喂入一个 delta；返回清洗后的可见部分。

        整个 delta 是推理内容或正在暂存待解析的部分标签时，可能返回空串。
        """
        if not text:
            return ""
        buf = self._buf + text
        self._buf = ""
        out: list[str] = []

        while buf:
            if self._in_block:
                # 寻找最早的闭标签。
                close_idx, close_len = self._find_first_tag(buf, self._CLOSE_TAGS)
                if close_idx == -1:
                    # 还没闭标签 —— 暂存可能的闭标签前缀；其余丢弃。
                    held = self._max_partial_suffix(buf, self._CLOSE_TAGS)
                    self._buf = buf[-held:] if held else ""
                    return "".join(out)
                # 找到闭标签：丢弃块内容 + 标签，继续。
                buf = buf[close_idx + close_len:]
                self._in_block = False
            else:
                # 优先级 1 —— buf 中任意位置的闭合 <tag>X</tag> 对。
                # 闭合对总是有意的、有界构造（即便行中正文含开/闭对也几乎肯定是
                # 模型内联泄露推理），不做边界门控。
                pair = self._find_earliest_closed_pair(buf)
                # 优先级 2 —— 块边界处的未闭合开标签。边界门控防正文提及被误擦。
                open_idx, open_len = self._find_open_at_boundary(buf, out)

                # 选 buf 中最早出现的匹配。
                if pair is not None and (open_idx == -1 or pair[0] <= open_idx):
                    start_idx, end_idx = pair
                    preceding = buf[:start_idx]
                    if preceding:
                        preceding = self._strip_orphan_close_tags(preceding)
                        if preceding:
                            out.append(preceding)
                            self._last_emitted_ended_newline = preceding.endswith("\n")
                    buf = buf[end_idx:]
                    continue

                if open_idx != -1:
                    # 边界处未闭合开标签 —— 发射前置内容，进入块，用剩余继续循环。
                    preceding = buf[:open_idx]
                    if preceding:
                        preceding = self._strip_orphan_close_tags(preceding)
                        if preceding:
                            out.append(preceding)
                            self._last_emitted_ended_newline = preceding.endswith("\n")
                    self._in_block = True
                    buf = buf[open_idx + open_len:]
                    continue

                # buf 中无可解析标签结构。暂存尾部可能的部分标签前缀，其余发射。
                held = self._max_partial_suffix(buf, self._OPEN_TAGS)
                held_close = self._max_partial_suffix(buf, self._CLOSE_TAGS)
                held = max(held, held_close)
                if held:
                    emit_text = buf[:-held]
                    self._buf = buf[-held:]
                else:
                    emit_text = buf
                    self._buf = ""
                if emit_text:
                    emit_text = self._strip_orphan_close_tags(emit_text)
                    if emit_text:
                        out.append(emit_text)
                        self._last_emitted_ended_newline = emit_text.endswith("\n")
                return "".join(out)

        return "".join(out)

    def flush(self) -> str:
        """流结束时的 flush。

        若仍在未闭合块内，暂存内容被丢弃 —— 泄露部分推理比截断回答更糟。
        否则暂存的部分标签尾原样发射（它最终不是真标签前缀）。

        总是把下一个 ``feed()`` 视为新鲜流边界。turn 内重试
        （仅思维预填充、空响应重试）会 flush 后再流式，不调 ``reset()``；
        留 ``_last_emitted_ended_newline`` 为 False 会使新流开头的
        ``<think>`` 看起来在行中并泄露到可见回复。
        """
        if self._in_block:
            self._buf = ""
            self._in_block = False
            # 下个 feed() 是新流 —— 流开头是边界。
            self._last_emitted_ended_newline = True
            return ""
        tail = self._buf
        self._buf = ""
        # 非块路径同理：不从 flushed tail 推导边界标志（如暂存的 '<'）。
        # 流结束意味着下个 feed() 开始新模型响应。
        self._last_emitted_ended_newline = True
        if not tail:
            return ""
        return self._strip_orphan_close_tags(tail)

    # ── 内部辅助 ───────────────────────────────────────────────

    @staticmethod
    def _find_first_tag(buf: str, tags: Tuple[str, ...]) -> Tuple[int, int]:
        """返回 *tags* 中最早出现的 (index, tag_length)，或 (-1, 0)。大小写不敏感。"""
        buf_lower = buf.lower()
        best_idx = -1
        best_len = 0
        for tag in tags:
            idx = buf_lower.find(tag.lower())
            if idx != -1 and (best_idx == -1 or idx < best_idx):
                best_idx = idx
                best_len = len(tag)
        return best_idx, best_len

    def _find_earliest_closed_pair(self, buf: str):
        """返回最早闭合对的 (start_idx, end_idx)，否则 None。

        闭合对是任意变体的 ``<tag>...</tag>``。匹配大小写不敏感且非贪婪
        （开标签后最近的闭标签胜），匹配正则 ``<tag>.*?</tag>`` 语义。
        两种标签变体都能匹配时，开标签更早者胜。
        """
        buf_lower = buf.lower()
        best: "tuple[int, int] | None" = None
        for open_tag, close_tag in zip(self._OPEN_TAGS, self._CLOSE_TAGS):
            open_lower = open_tag.lower()
            close_lower = close_tag.lower()
            open_idx = buf_lower.find(open_lower)
            if open_idx == -1:
                continue
            close_idx = buf_lower.find(close_lower, open_idx + len(open_lower))
            if close_idx == -1:
                continue
            end_idx = close_idx + len(close_lower)
            if best is None or open_idx < best[0]:
                best = (open_idx, end_idx)
        return best

    def _find_open_at_boundary(
        self, buf: str, already_emitted: list[str],
    ) -> Tuple[int, int]:
        """返回最早的块边界开标签 (idx, len)。无合法开标签返回 (-1, 0)。"""
        buf_lower = buf.lower()
        best_idx = -1
        best_len = 0
        for tag in self._OPEN_TAGS:
            tag_lower = tag.lower()
            search_start = 0
            while True:
                idx = buf_lower.find(tag_lower, search_start)
                if idx == -1:
                    break
                if self._is_block_boundary(buf, idx, already_emitted):
                    if best_idx == -1 or idx < best_idx:
                        best_idx = idx
                        best_len = len(tag)
                    break  # 此标签的首个边界命中足够
                search_start = idx + 1
        return best_idx, best_len

    def _is_block_boundary(
        self, buf: str, idx: int, already_emitted: list[str],
    ) -> bool:
        """True 当 *idx* 位置在 buf 中是块边界。

        块边界是：
          - buf 位置 0 且最近发射以换行结尾（或还没发射）
          - 当前行（buf 中最后一个换行后）前置文本全是空白，
            且若无换行则最近先前发射以换行结尾
        """
        if idx == 0:
            # 检查本次 feed() 调用中最近发射的块是否以换行结尾
            if already_emitted:
                return already_emitted[-1].endswith("\n")
            return self._last_emitted_ended_newline
        preceding = buf[:idx]
        last_nl = preceding.rfind("\n")
        if last_nl == -1:
            # buf 中标签前无换行 —— 仅当先前发射以换行结尾且之后全是空白才边界
            if already_emitted:
                prior_newline = already_emitted[-1].endswith("\n")
            else:
                prior_newline = self._last_emitted_ended_newline
            return prior_newline and preceding.strip() == ""
        # 有换行 —— 换行与标签间的文本必须全空白
        return preceding[last_nl + 1:].strip() == ""

    @classmethod
    def _max_partial_suffix(cls, buf: str, tags: Tuple[str, ...]) -> int:
        """返回 buf 的最长后缀，该后缀是某标签的前缀。

        只计严格短于标签本身的前缀（全长后缀是标签本身，作为匹配处理，
        非暂存部分）。大小写不敏感。
        """
        if not buf:
            return 0
        buf_lower = buf.lower()
        max_check = min(len(buf_lower), cls._MAX_TAG_LEN - 1)
        for i in range(max_check, 0, -1):
            suffix = buf_lower[-i:]
            for tag in tags:
                tag_lower = tag.lower()
                if len(tag_lower) > i and tag_lower.startswith(suffix):
                    return i
        return 0

    @classmethod
    def _strip_orphan_close_tags(cls, text: str) -> str:
        """移除 *text* 中的任意闭标签（孤儿闭标签处理）。

        孤儿闭标签在当前清洗器状态中无匹配开标签；它总是噪声，
        连同尾部空白一起剥除，使周围正文自然衔接。
        """
        if "</" not in text:
            return text
        text_lower = text.lower()
        out: list[str] = []
        i = 0
        while i < len(text):
            matched = False
            if text_lower[i:i + 2] == "</":
                for tag in cls._CLOSE_TAGS:
                    tag_lower = tag.lower()
                    tag_len = len(tag_lower)
                    if text_lower[i:i + tag_len] == tag_lower:
                        # 跳过标签及尾部空白
                        j = i + tag_len
                        while j < len(text) and text[j] in " \t\n\r":
                            j += 1
                        i = j
                        matched = True
                        break
            if not matched:
                out.append(text[i])
                i += 1
        return "".join(out)


def strip_think_blocks(text: str) -> str:
    """一次性清洗完整字符串中的所有思维块（非流式场景）。

    用于非流式响应（如 grace call 结果）的后处理。
    流式场景应用 ``StreamingThinkScrubber``。
    """
    if not text:
        return text
    scrubber = StreamingThinkScrubber()
    visible = scrubber.feed(text)
    tail = scrubber.flush()
    return visible + tail
