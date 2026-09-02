"""知识库文档入库服务：分段（chunking）+ 向量生成（embedding）。

文档入库流程：
1. **解析**：``file_parser`` 已把文件解析为纯文本（``doc.content``）。
2. **分段**：按知识库 ``chunk_mode/chunk_size/chunk_overlap/chunk_delimiter``
   调用 ``chunker.chunk_text`` 切分为多个分段。
3. **向量化**：``index_mode`` 为 vector/hybrid 时，批量调用 embedding 接口
   生成各段向量。失败则段向量留空，回退纯关键词检索（保证可用）。
4. **落库**：分段写入 ``knowledge_segments`` 表，更新文档 ``segment_count`` 与状态。

所有步骤均有日志输出，可在后端日志中看到完整的"解析→分段→打分准备"过程。
"""
import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from app.core.chunker import chunk_text
from app.core.file_parser import parse_file_content
from app.models.knowledge_base import KnowledgeBase, KnowledgeDocument, KnowledgeSegment

logger = logging.getLogger(__name__)

# 单批向量生成上限（OpenAI embeddings 接口建议 ≤2048 输入，这里保守取 64）
_EMBED_BATCH_SIZE = 64

# 上传文件保存目录：backend/uploads/
# __file__ = backend/app/core/kb_service.py，上溯 3 级到 backend/
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "uploads",
)


async def ingest_document(db: Session, doc: KnowledgeDocument, kb: KnowledgeBase) -> int:
    """对文档执行分段 + 向量化，写入 ``knowledge_segments`` 表。

    若文档已有分段（重复入库），先删除旧分段再重新生成。

    Args:
        db: 数据库会话。
        doc: 知识文档（需已填充 ``content``）。
        kb: 所属知识库（提供分段/索引配置）。

    Returns:
        生成的分段数量。
    """
    if doc is None or kb is None:
        logger.warning("入库跳过: doc 或 kb 为空")
        return 0

    content = doc.content or ""
    doc_id = doc.id
    kb_id = kb.id
    logger.info("===== 文档入库开始: doc_id=%s, kb_id=%s, content_len=%s =====", doc_id, kb_id, len(content))

    # 1. 状态标记为"解析中"
    doc.status = "parsing"
    doc.progress = 10
    db.commit()

    # 2. 删除旧分段（重新入库场景）
    old_count = db.query(KnowledgeSegment).filter(KnowledgeSegment.doc_id == doc_id).count()
    if old_count > 0:
        logger.info("删除旧分段: doc_id=%s, 旧段数=%d", doc_id, old_count)
        db.query(KnowledgeSegment).filter(KnowledgeSegment.doc_id == doc_id).delete()
        db.commit()

    # 3. 分段
    try:
        segments_text = chunk_text(content, kb)
    except Exception as exc:  # noqa: BLE001
        logger.exception("分段失败: doc_id=%s, err=%s", doc_id, exc)
        doc.status = "failed"
        doc.progress = 0
        db.commit()
        return 0

    if not segments_text:
        logger.warning("分段结果为空: doc_id=%s（content 可能为空）", doc_id)
        doc.segment_count = 0
        doc.status = "available"
        doc.progress = 100
        db.commit()
        return 0

    logger.info(
        "分段完成: doc_id=%s, mode=%s, size=%s, overlap=%s, 段数=%d",
        doc_id, kb.chunk_mode, kb.chunk_size, kb.chunk_overlap, len(segments_text),
    )

    # 4. 状态标记为"索引中"
    doc.status = "indexing"
    doc.progress = 30
    db.commit()

    # 5. 向量化（vector/hybrid 模式）
    index_mode = (kb.index_mode or "keyword").lower()
    need_embedding = index_mode in ("vector", "hybrid")
    embeddings: list[list[float] | None] = [None] * len(segments_text)

    if need_embedding:
        logger.info("开始向量化: doc_id=%s, model=%s, 段数=%d", doc_id, kb.embedding_model, len(segments_text))
        try:
            from app.core.embedding import embed_texts

            # 分批生成，避免单次请求过大
            for start in range(0, len(segments_text), _EMBED_BATCH_SIZE):
                batch = segments_text[start : start + _EMBED_BATCH_SIZE]
                vectors = await embed_texts(batch, kb.embedding_model, db, embedding_config_id=kb.embedding_config_id)
                if vectors and len(vectors) == len(batch):
                    for j, vec in enumerate(vectors):
                        embeddings[start + j] = vec
                else:
                    logger.warning(
                        "向量批次生成失败或数量不匹配: doc_id=%s, start=%s, 批大小=%d",
                        doc_id, start, len(batch),
                    )
                # 更新向量化进度：30% ~ 100% 区间
                done = start + len(batch)
                doc.progress = min(99, 30 + int(70 * done / len(segments_text)))
                db.commit()
            emb_ok = sum(1 for e in embeddings if e is not None)
            logger.info("向量化完成: doc_id=%s, 成功=%d/%d", doc_id, emb_ok, len(segments_text))
            if emb_ok == 0:
                logger.warning("向量全部生成失败，段向量留空，将回退关键词检索: doc_id=%s", doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("向量化异常（段向量留空）: doc_id=%s, err=%s", doc_id, exc)

    # 6. 落库分段
    from app.core.kb_retriever import tokenize

    for seq, seg_text in enumerate(segments_text):
        seg = KnowledgeSegment(
            kb_id=kb_id,
            doc_id=doc_id,
            seq=seq,
            content=seg_text,
            token_count=len(tokenize(seg_text)),
            embedding=embeddings[seq] if embeddings[seq] else None,
        )
        db.add(seg)
    doc.segment_count = len(segments_text)
    doc.status = "available"
    doc.progress = 100
    db.commit()
    logger.info(
        "===== 文档入库完成: doc_id=%s, 段数=%d, 向量=%s, 状态=available =====",
        doc_id, len(segments_text), "已生成" if any(e for e in embeddings) else "无（关键词模式）",
    )
    return len(segments_text)


async def reingest_document(db: Session, doc_id: int, kb_id: int) -> dict[str, Any]:
    """重新解析并分段指定文档（知识库配置变更后用）。

    若文档有存储的文件路径（``file_path``），会**从磁盘重新解析文件内容**，
    而非复用之前存储的 ``content``。这解决了首次上传时解析失败（如缺少
    xlrd 导致 ``.xls`` 文件 ``content`` 为空）后，即便补装依赖、重写解析器，
    重新解析仍得到空内容的问题——因为旧逻辑直接拿 DB 里的空 ``content`` 去分段。

    重新解析流程：
    1. 取出文档记录与所属知识库。
    2. 若 ``file_path`` 存在且文件仍在磁盘上，调用 ``parse_file_content``
       重新解析，覆盖 ``doc.content``（解析失败则沿用旧 content 并告警）。
    3. 调用 ``ingest_document`` 执行分段 + 向量化。

    Returns:
        ``{"doc_id", "segment_count", "status"}``。
    """
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == doc_id, KnowledgeDocument.kb_id == kb_id)
        .first()
    )
    if doc is None:
        return {"doc_id": doc_id, "segment_count": 0, "status": "not_found"}
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if kb is None:
        return {"doc_id": doc_id, "segment_count": 0, "status": "kb_not_found"}

    # 若有文件路径，从磁盘重新解析（覆盖可能为空的旧 content）
    # 典型场景：首次上传 .xls 时未装 xlrd → content 为空 → 段数为 0；
    #         补装 xlrd 后重新解析，必须重读文件才能拿到真实内容。
    if doc.file_path:
        full_path = os.path.join(UPLOAD_DIR, doc.file_path)
        if os.path.isfile(full_path):
            try:
                new_content = await parse_file_content(full_path, doc.file_type or "")
                if new_content and new_content.strip():
                    old_len = len(doc.content or "")
                    logger.info(
                        "重新解析文件成功: doc_id=%s, file=%s, type=%s, old_len=%d, new_len=%d",
                        doc_id, doc.file_path, doc.file_type, old_len, len(new_content),
                    )
                    doc.content = new_content
                    db.commit()
                    db.refresh(doc)
                else:
                    logger.warning(
                        "重新解析结果为空: doc_id=%s, file=%s, type=%s（检查文件是否损坏或解析依赖是否安装）",
                        doc_id, doc.file_path, doc.file_type,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception("重新解析文件失败，沿用旧 content: doc_id=%s, err=%s", doc_id, exc)
        else:
            logger.warning(
                "文件不存在于磁盘，沿用旧 content: doc_id=%s, path=%s",
                doc_id, full_path,
            )
    else:
        logger.info("文档无文件路径，沿用存储 content 重新分段: doc_id=%s", doc_id)

    count = await ingest_document(db, doc, kb)
    return {"doc_id": doc_id, "segment_count": count, "status": doc.status}


def list_segments(db: Session, doc_id: int) -> list[dict[str, Any]]:
    """列出文档的分段（按 seq 升序），供前端展示解析/分段结果。"""
    segs = (
        db.query(KnowledgeSegment)
        .filter(KnowledgeSegment.doc_id == doc_id)
        .order_by(KnowledgeSegment.seq.asc())
        .all()
    )
    return [
        {
            "id": s.id,
            "seq": s.seq,
            "content": s.content,
            "token_count": s.token_count,
            "has_embedding": bool(s.embedding),
            "char_count": len(s.content or ""),
            "preview": (s.content or "")[:200],
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in segs
    ]


async def ingest_document_bg(doc_id: int, kb_id: int) -> None:
    """后台文档入库任务（独立 DB 会话，不阻塞 API 响应）。

    由 ``upload_document`` / ``create_document`` 通过 ``asyncio.create_task`` 启动，
    在请求返回后继续执行分段 + 向量化，通过更新 ``doc.progress`` 让前端轮询可见进度。

    失败时设置 ``doc.status = "failed"``，不会抛出异常到事件循环。
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if doc is None or kb is None:
            logger.error("后台入库失败: doc 或 kb 不存在, doc_id=%s, kb_id=%s", doc_id, kb_id)
            return
        await ingest_document(db, doc, kb)
        logger.info("后台入库完成: doc_id=%s, status=%s, progress=%s", doc_id, doc.status, doc.progress)
    except Exception as exc:  # noqa: BLE001
        logger.exception("后台入库异常: doc_id=%s, err=%s", doc_id, exc)
        try:
            doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
            if doc:
                doc.status = "failed"
                doc.progress = 0
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


async def reingest_document_bg(doc_id: int, kb_id: int) -> None:
    """后台重新入库任务（独立 DB 会话，不阻塞 API 响应）。"""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await reingest_document(db, doc_id, kb_id)
        logger.info("后台重新入库完成: doc_id=%s", doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("后台重新入库异常: doc_id=%s, err=%s", doc_id, exc)
        try:
            doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
            if doc:
                doc.status = "failed"
                doc.progress = 0
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()
