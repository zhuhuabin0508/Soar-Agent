"""知识库文本分段（chunking）模块。

按知识库的 ``chunk_mode`` / ``chunk_size`` / ``chunk_overlap`` / ``chunk_delimiter``
配置把文档纯文本切分为多个分段，供 ``KnowledgeSegment`` 存储与分段级检索使用。

分段模式：
- ``auto``：先按段落（空行）切分，超长段落再按句子/长度二次切分，保留上下文。
  自动检测连续短行（如 IP 列表、日志、表格行），按行切分而非累积，提升结构化数据精准度。
- ``line``：按行分段，每 ``chunk_size`` 行合并为一段（默认每行一段），适合 IP 列表/日志/表格。
- ``fixed_length``：按 ``chunk_size`` 滑窗切分，步长 = ``chunk_size - chunk_overlap``。
- ``delimiter``：按 ``chunk_delimiter`` 切分，超长段再按长度兜底。
- ``qa``：识别 Q&A 对（含问号或"问/答/Q/A"前缀的行），每对一段；无 Q&A 结构时回退 auto。

所有模式都会过滤空段，并对超长段做长度兜底（避免单段过大）。
"""
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 单段最大字符数（硬上限，防止异常超长段）
_MAX_SEGMENT_CHARS = 4000
# 句子切分正则（中英文句号、问号、感叹号、换行）
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?\.])\s+|\n+")
# Q&A 行识别
_QA_PREFIX_RE = re.compile(r"^\s*(问|答|Q|A|题目|答案)[\s:：、\.]*", re.IGNORECASE)
# 连续短行检测：单行字符数阈值（≤此值视为短行）
_SHORT_LINE_THRESHOLD = 120
# 连续短行数量阈值（≥此值触发按行切分）
_SHORT_LINE_COUNT_THRESHOLD = 3


def _split_sentences(text: str) -> list[str]:
    """按中英文标点切分句子。"""
    parts = _SENT_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _sliding_window(text: str, size: int, overlap: int) -> list[str]:
    """按定长滑窗切分，步长 = size - overlap。"""
    if size <= 0:
        size = 500
    step = max(1, size - max(0, overlap))
    chunks = []
    i = 0
    while i < len(text):
        chunk = text[i : i + size]
        if chunk.strip():
            chunks.append(chunk.strip())
        if i + size >= len(text):
            break
        i += step
    return chunks


def _cap_segment(seg: str, size: int, overlap: int) -> list[str]:
    """超长段按滑窗兜底切分。"""
    if len(seg) <= _MAX_SEGMENT_CHARS:
        return [seg]
    return _sliding_window(seg, min(size, _MAX_SEGMENT_CHARS) or 500, overlap)


def chunk_fixed_length(text: str, size: int, overlap: int) -> list[str]:
    """定长滑窗分段。"""
    return _sliding_window(text, size, overlap)


def chunk_delimiter(text: str, delimiter: str, size: int, overlap: int) -> list[str]:
    """按分隔符分段，超长段按长度兜底。"""
    if not delimiter:
        delimiter = "\n\n"
    # 支持转义符 \n \t
    delimiter = delimiter.encode().decode("unicode_escape") if "\\n" in delimiter or "\\t" in delimiter else delimiter
    parts = text.split(delimiter)
    segments: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        segments.extend(_cap_segment(p, size, overlap))
    return segments


def chunk_qa(text: str, size: int, overlap: int) -> list[str]:
    """Q&A 模式：把"问+答"配对为一段。无 Q&A 结构时回退 auto。"""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    # 检测是否含 Q&A 结构
    has_qa = any(_QA_PREFIX_RE.match(ln) or "？" in ln or "?" in ln for ln in lines[:20])
    if not has_qa:
        return chunk_auto(text, size, overlap)
    segments: list[str] = []
    cur: list[str] = []
    for ln in lines:
        is_q = bool(_QA_PREFIX_RE.match(ln)) or (("？" in ln or "?" in ln) and not cur)
        if is_q and cur:
            segments.extend(_cap_segment("\n".join(cur), size, overlap))
            cur = []
        cur.append(ln)
    if cur:
        segments.extend(_cap_segment("\n".join(cur), size, overlap))
    return segments


def _is_short_line_block(lines: list[str]) -> bool:
    """检测行列表是否为"连续短行块"（IP 列表/日志/表格行等结构化数据）。

    判定条件：非空行中，≥ ``_SHORT_LINE_COUNT_THRESHOLD`` 行的长度 ≤ ``_SHORT_LINE_THRESHOLD``，
    且这些短行占比 ≥ 60%。
    """
    if len(lines) < _SHORT_LINE_COUNT_THRESHOLD:
        return False
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) < _SHORT_LINE_COUNT_THRESHOLD:
        return False
    short_count = sum(1 for ln in non_empty if len(ln) <= _SHORT_LINE_THRESHOLD)
    return short_count / len(non_empty) >= 0.6


def chunk_line(text: str, size: int, overlap: int) -> list[str]:
    """按行分段：每 ``size`` 行合并为一段。

    适合 IP 列表、日志、CSV/表格行等结构化数据，确保每行（或少量行）独立成段，
    BM25 检索能精准命中单行数据。

    Args:
        text: 文档纯文本。
        size: 每段包含的行数（≤1 时每行一段）。
        overlap: 段间重叠行数。
    """
    lines = [ln.rstrip() for ln in text.split("\n")]
    # 过滤纯空行但保留行结构（连续空行压缩为单个空行）
    cleaned: list[str] = []
    prev_empty = False
    for ln in lines:
        if not ln.strip():
            if not prev_empty:
                cleaned.append("")
            prev_empty = True
        else:
            cleaned.append(ln)
            prev_empty = False
    # 去除尾部空行
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    if not cleaned:
        return []

    lines_per_seg = max(1, size)
    overlap_lines = max(0, overlap)
    step = max(1, lines_per_seg - overlap_lines)

    segments: list[str] = []
    i = 0
    while i < len(cleaned):
        batch = cleaned[i : i + lines_per_seg]
        seg_text = "\n".join(batch).strip()
        if seg_text:
            segments.extend(_cap_segment(seg_text, _MAX_SEGMENT_CHARS, 0))
        if i + lines_per_seg >= len(cleaned):
            break
        i += step
    return [s for s in segments if s]


def chunk_auto(text: str, size: int, overlap: int) -> list[str]:
    """自动分段：先按段落，超长段按句子聚合到 size 上下。

    增强逻辑：检测段落内是否为"连续短行块"（IP 列表/日志/表格行），
    若是则按行切分（每行或少量行一段），避免多行结构化数据被合并。
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    segments: list[str] = []
    buf = ""
    for para in paragraphs:
        # 检测段落是否为连续短行块（结构化数据）
        para_lines = para.split("\n")
        if len(para_lines) >= _SHORT_LINE_COUNT_THRESHOLD and _is_short_line_block(para_lines):
            # 先把缓冲区落盘
            if buf:
                segments.extend(_cap_segment(buf, size, overlap))
                buf = ""
            # 按行切分（每行一段，超长行按长度兜底）
            for ln in para_lines:
                ln = ln.strip()
                if ln:
                    segments.extend(_cap_segment(ln, size, overlap))
            continue

        if len(para) > size:
            # 先把缓冲区落盘
            if buf:
                segments.extend(_cap_segment(buf, size, overlap))
                buf = ""
            # 超长段落按句子聚合
            sentences = _split_sentences(para)
            cur = ""
            for sent in sentences:
                if len(cur) + len(sent) + 1 <= size:
                    cur = (cur + " " + sent) if cur else sent
                else:
                    if cur:
                        segments.extend(_cap_segment(cur, size, overlap))
                    cur = sent
            if cur:
                buf = cur
        else:
            # 短段落累积到 size
            if len(buf) + len(para) + 2 <= size:
                buf = (buf + "\n\n" + para) if buf else para
            else:
                if buf:
                    segments.extend(_cap_segment(buf, size, overlap))
                buf = para
    if buf:
        segments.extend(_cap_segment(buf, size, overlap))
    return [s for s in segments if s]


def chunk_text(text: str, kb_config: Any) -> list[str]:
    """按知识库配置切分文本为分段列表。

    Args:
        text: 文档纯文本。
        kb_config: 知识库对象或字典，需含 chunk_mode/chunk_size/chunk_overlap/chunk_delimiter。

    Returns:
        分段文本列表（已过滤空段，单段不超过 _MAX_SEGMENT_CHARS）。
    """
    if not text or not text.strip():
        return []
    cfg = kb_config or {}
    # 兼容 KnowledgeBase 对象与 dict 两种配置形式
    if isinstance(cfg, dict):
        mode = cfg.get("chunk_mode") or "auto"
        size = int(cfg.get("chunk_size") or 500)
        overlap = int(cfg.get("chunk_overlap") or 50)
        delimiter = cfg.get("chunk_delimiter") or "\n\n"
    else:
        mode = getattr(cfg, "chunk_mode", None) or "auto"
        size = int(getattr(cfg, "chunk_size", None) or 500)
        overlap = int(getattr(cfg, "chunk_overlap", None) or 50)
        delimiter = getattr(cfg, "chunk_delimiter", None) or "\n\n"

    if size <= 0:
        size = 500
    if overlap < 0:
        overlap = 0

    mode = (mode or "auto").lower()
    if mode == "fixed_length":
        segments = chunk_fixed_length(text, size, overlap)
    elif mode == "delimiter":
        segments = chunk_delimiter(text, delimiter, size, overlap)
    elif mode == "qa":
        segments = chunk_qa(text, size, overlap)
    elif mode == "line":
        segments = chunk_line(text, size, overlap)
    else:
        segments = chunk_auto(text, size, overlap)

    logger.info("分段完成: mode=%s, size=%s, overlap=%s, 段数=%d", mode, size, overlap, len(segments))
    return segments
