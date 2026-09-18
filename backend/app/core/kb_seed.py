"""内置知识库种子：开箱即用的研判参考文档。

幂等：按知识库名称查重，已存在则跳过（不覆盖用户修改）。
分段使用 keyword 模式，无需 embedding 即可检索。
"""
import logging

from app.core.chunker import chunk_text
from app.database import SessionLocal
from app.models.knowledge_base import KnowledgeBase, KnowledgeDocument, KnowledgeSegment

logger = logging.getLogger(__name__)

PRESET_KNOWLEDGE_BASES = [
    {
        "name": "安全响应规范",
        "description": "内置：告警研判与处置的标准流程与分级原则",
        "doc_title": "安全响应规范（内置）",
        "content": """# 安全响应规范

## 告警分级
- 高危：涉及外联 C2、横向移动、权限提升，建议优先封禁并人工复核业务影响。
- 中危：异常登录、扫描行为、可疑外联，先查资产归属与威胁情报再决策。
- 低危：信息类告警，记录观察，必要时通知责任单位。

## 研判顺序
1. 白名单：内网可信网段（10/172.16/192.168）优先排除误报。
2. 资产归属：查询资产清单，确认 IP 是否属于已知主机、网段或出口地址。
3. 威胁情报：对外网 IP 查询恶意标签、置信度与历史活动。
4. 处置：封禁前确认非关键业务出口；临时封禁需记录原因与时长。

## 封禁原则
- 外网恶意 IP：可自动封禁，默认 24 小时，高危可延长。
- 内网 IP：禁止自动封禁，必须人工确认。
- 出口/NAT 地址：封禁前必须确认影响范围，优先通知责任单位。
""",
    },
    {
        "name": "常用研判口径",
        "description": "内置：IP 研判常见问题与口径说明",
        "doc_title": "常用研判口径（内置）",
        "content": """# 常用研判口径

## 资产对比
- 同一 IP 可能同时出现在主机资产、网段信息、出口地址中，需全部检索后综合判断。
- 主机资产关注内网 IP 与 EIP；网段信息关注 CIDR 归属；出口地址关注公网出口。
- 资产未命中不代表无关联，需结合威胁情报与告警上下文。

## 情报解读
- confidence ≥ 0.8 且多个情报源一致：倾向认定为恶意。
- 仅单一低置信标签：建议观察或人工复核，不宜直接永久封禁。
- 内网 IP 在情报库无记录属正常，不应据此判定为恶意。

## 话术模板
- 已确认恶意：「该 IP 经情报与资产核查，判定为恶意，建议封禁并通知责任单位。」
- 归属已知资产：「该 IP 归属【单位/系统】，建议联系责任人确认是否为正常业务行为。」
- 未命中：「资产库未命中，已查威胁情报，建议【封禁/观察/人工复核】。」
""",
    },
]


def _ingest_text_document(db, kb: KnowledgeBase, title: str, content: str) -> int:
    """将纯文本写入知识库并分段（同步，keyword 索引）。"""
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.kb_id == kb.id, KnowledgeDocument.title == title)
        .first()
    )
    if doc is None:
        doc = KnowledgeDocument(
            kb_id=kb.id,
            title=title,
            content=content,
            source_type="text",
            status="available",
            progress=100,
            description="系统内置种子文档",
        )
        db.add(doc)
        db.flush()
    else:
        if (doc.content or "") == content and (doc.segment_count or 0) > 0:
            return doc.segment_count or 0
        doc.content = content
        db.query(KnowledgeSegment).filter(KnowledgeSegment.doc_id == doc.id).delete()

    segments_text = chunk_text(content, kb)
    if not segments_text:
        doc.segment_count = 0
        doc.status = "available"
        doc.progress = 100
        return 0

    for seq, seg_text in enumerate(segments_text):
        db.add(
            KnowledgeSegment(
                kb_id=kb.id,
                doc_id=doc.id,
                seq=seq,
                content=seg_text,
                token_count=len(seg_text),
            )
        )
    doc.segment_count = len(segments_text)
    doc.status = "available"
    doc.progress = 100
    return len(segments_text)


def ensure_preset_knowledge_bases() -> None:
    """幂等种入内置知识库及文档分段。"""
    db = SessionLocal()
    try:
        inserted = 0
        for item in PRESET_KNOWLEDGE_BASES:
            kb = db.query(KnowledgeBase).filter(KnowledgeBase.name == item["name"]).first()
            if kb is None:
                kb = KnowledgeBase(
                    name=item["name"],
                    description=item["description"],
                    chunk_mode="auto",
                    chunk_size=500,
                    chunk_overlap=50,
                    index_mode="keyword",
                )
                db.add(kb)
                db.flush()
                inserted += 1
                logger.info("种入内置知识库: %s", item["name"])
            seg_count = _ingest_text_document(db, kb, item["doc_title"], item["content"])
            logger.info("内置知识库文档就绪: %s, segments=%d", item["name"], seg_count)
        if inserted:
            db.commit()
        else:
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("内置知识库种子失败: %s", exc)
        db.rollback()
    finally:
        db.close()
