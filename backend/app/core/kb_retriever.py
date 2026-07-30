"""知识库检索器（分段级 + 中文分词 + BM25 + 向量混合）。

检索流程：
1. 取知识库下所有 ``KnowledgeSegment``（分段级，非整篇文档）。
2. **关键词检索（BM25）**：用 jieba 对查询与分段分词，计算 BM25 分数。
   - jieba 未安装时回退到字符 bigram，保证中文检索可用（不再用对中文失效的 split）。
3. **向量检索**：index_mode 为 vector/hybrid 时，对查询生成 embedding，
   与各段 embedding 做余弦相似度。embedding 不可用时回退纯 BM25。
4. **混合融合**：hybrid 模式按知识库配置的向量/关键词权重加权归一化。
5. **Rerank**：rerank_enabled 时做轻量重排（查询词密度 + 标题命中加权）。
6. 按分数阈值过滤，返回 top_k 段，附带文档标题与元信息。

返回元素结构：
``{"segment_id", "doc_id", "title", "content", "score", "bm25_score", "vector_score"}``
"""
import logging
import math
from typing import Any

from app.database import SessionLocal
from app.models.knowledge_base import KnowledgeBase, KnowledgeDocument, KnowledgeSegment

logger = logging.getLogger(__name__)

# ===== 分词 =====
_jieba_available = False
try:
    import jieba  # type: ignore

    _jieba_available = True
except ImportError:  # pragma: no cover
    pass

# BM25 参数
_BM25_K1 = 1.5
_BM25_B = 0.75
# 停用词
_STOPWORDS = {"的", "了", "和", "是", "在", "我", "有", "与", "及", "或", "a", "the", "is", "in", "of", "to", "and"}


def tokenize(text: str) -> list[str]:
    """中文分词：优先 jieba，回退字符 bigram + 英文按空格。"""
    if not text:
        return []
    text = text.lower()
    if _jieba_available:
        tokens = [t.strip() for t in jieba.cut(text) if t.strip()]
    else:
        # 回退：英文按空格/标点切，中文按二字滑窗
        import re

        tokens = []
        for chunk in re.findall(r"[a-z0-9]+|[\u4e00-\u9fa5]+", text):
            if re.match(r"[a-z0-9]", chunk):
                tokens.append(chunk)
            else:
                # 中文字符 bigram
                for i in range(len(chunk) - 1):
                    tokens.append(chunk[i : i + 2])
                if len(chunk) == 1:
                    tokens.append(chunk)
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 0]


# ===== BM25 =====
def _bm25_scores(query_tokens: list[str], segments: list[KnowledgeSegment]) -> dict[int, float]:
    """对所有分段计算 BM25 分数，返回 {segment.id: score}。"""
    if not segments or not query_tokens:
        return {}
    # 预计算每段的 token 列表与长度
    seg_tokens: dict[int, list[str]] = {}
    seg_len: dict[int, int] = {}
    for seg in segments:
        toks = tokenize(seg.content or "")
        seg_tokens[seg.id] = toks
        seg_len[seg.id] = len(toks)
    avgdl = sum(seg_len.values()) / max(1, len(segments))
    # 文档频率
    df: dict[str, int] = {}
    for toks in seg_tokens.values():
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    N = len(segments)
    scores: dict[int, float] = {}
    q_terms = set(query_tokens)
    for seg in segments:
        toks = seg_tokens[seg.id]
        if not toks:
            continue
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        dl = seg_len[seg.id] or 1
        s = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            f = tf[term]
            d = df.get(term, 0)
            idf = math.log((N - d + 0.5) / (d + 0.5) + 1)
            s += idf * (f * (_BM25_K1 + 1)) / (f + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avgdl))
        if s > 0:
            scores[seg.id] = s
    return scores


def _normalize(scores: dict[int, float]) -> dict[int, float]:
    """把分数归一化到 [0, 1]。"""
    if not scores:
        return {}
    mx = max(scores.values())
    if mx <= 0:
        return scores
    return {k: v / mx for k, v in scores.items()}


# ===== 主检索 =====
async def search_kb(kb_id: int, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """在指定知识库中分段级检索。

    Args:
        kb_id: 知识库 ID。
        query: 查询字符串（中文用 jieba 分词）。
        top_k: 返回的最大分段数。

    Returns:
        命中分段列表，按 score 降序。元素含 ``segment_id/doc_id/title/content/score`` 等。
    """
    logger.info("知识库检索: kb_id=%s, query=%s, top_k=%s", kb_id, query, top_k)
    db = SessionLocal()
    try:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if kb is None:
            return []
        segments = (
            db.query(KnowledgeSegment)
            .filter(KnowledgeSegment.kb_id == kb_id)
            .all()
        )
        logger.debug("知识库 %s 共 %d 个分段", kb_id, len(segments))
        if not segments:
            return []

        index_mode = (kb.index_mode or "keyword").lower()
        query_tokens = tokenize(query or "")

        # 1. BM25 关键词分数
        bm25_raw = _bm25_scores(query_tokens, segments)
        bm25_norm = _normalize(bm25_raw)

        # 2. 向量分数（vector/hybrid 模式）
        vector_norm: dict[int, float] = {}
        if index_mode in ("vector", "hybrid"):
            from app.core.embedding import embed_texts, cosine_similarity

            q_vec = await embed_texts([query], kb.embedding_model, db, embedding_config_id=kb.embedding_config_id)
            if q_vec and q_vec[0]:
                qv = q_vec[0]
                vec_raw: dict[int, float] = {}
                for seg in segments:
                    if seg.embedding:
                        vec_raw[seg.id] = cosine_similarity(qv, seg.embedding)
                vector_norm = _normalize(vec_raw)
                if not vector_norm:
                    logger.info("知识库 %s 无段向量，向量检索回退关键词", kb_id)
            else:
                logger.info("向量生成不可用，回退关键词检索: kb_id=%s", kb_id)

        # 3. 融合
        vw = (kb.hybrid_vector_weight or 70) / 100.0 if index_mode == "hybrid" else 0.0
        kw = (kb.hybrid_keyword_weight or 30) / 100.0 if index_mode == "hybrid" else 0.0
        # vector 模式：纯向量；hybrid：加权；keyword：纯 BM25
        seg_map = {seg.id: seg for seg in segments}
        doc_map: dict[int, KnowledgeDocument] = {}
        combined: dict[int, float] = {}
        for seg in segments:
            b = bm25_norm.get(seg.id, 0.0)
            v = vector_norm.get(seg.id, 0.0)
            if index_mode == "vector":
                score = v
            elif index_mode == "hybrid":
                score = vw * v + kw * b
            else:
                score = b
            if score > 0:
                combined[seg.id] = score
        if not combined:
            return []

        # 4. Rerank（轻量：查询词在标题命中 + 段内密度加权）
        if kb.rerank_enabled:
            doc_ids = {seg.doc_id for seg in segments}
            docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all()
            doc_map = {d.id: d for d in docs}
            q_terms_set = set(query_tokens)
            for sid, sc in combined.items():
                seg = seg_map[sid]
                doc = doc_map.get(seg.doc_id)
                title = (doc.title or "") if doc else ""
                title_hit = 1.0 if any(t in title.lower() for t in q_terms_set) else 0.0
                # 段内查询词密度
                seg_toks = tokenize(seg.content or "")
                density = sum(1 for t in seg_toks if t in q_terms_set) / max(1, len(seg_toks))
                combined[sid] = sc * (1.0 + 0.15 * title_hit + 0.25 * min(density, 1.0))

        # 5. 排序 + top_k
        ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)[: max(top_k, 1)]
        if not doc_map:
            doc_ids = {seg_map[sid].doc_id for sid, _ in ranked}
            docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all()
            doc_map = {d.id: d for d in docs}

        results: list[dict[str, Any]] = []
        for sid, score in ranked:
            seg = seg_map[sid]
            doc = doc_map.get(seg.doc_id)
            results.append({
                "segment_id": seg.id,
                "doc_id": seg.doc_id,
                "title": (doc.title if doc else "") or f"文档 #{seg.doc_id}",
                "content": seg.content,
                "score": round(score, 4),
                "bm25_score": round(bm25_norm.get(sid, 0.0), 4),
                "vector_score": round(vector_norm.get(sid, 0.0), 4),
                "seq": seg.seq,
            })
        logger.info("知识库检索完成: kb_id=%s, 命中=%d", kb_id, len(results))
        return results
    finally:
        db.close()
