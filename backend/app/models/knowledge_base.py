"""知识库与知识文档数据模型。

KnowledgeBase 为知识库容器，KnowledgeDocument 为其下文档条目。
支持 Dify 风格的分段模式、索引模式、Embedding 模型与检索设置配置。
当前检索使用 PostgreSQL ILIKE 关键词匹配（见 ``app/core/kb_retriever.py``），
索引模式设为 vector/hybrid 时预留向量检索扩展（pgvector + 嵌入模型）。
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database import Base


class KnowledgeBase(Base):
    """知识库模型（对标 Dify 知识库配置）。"""

    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # ===== 分段设置（对标 Dify） =====
    # 分段模式：auto / fixed_length / delimiter / qa
    chunk_mode = Column(String(32), nullable=False, default="auto")
    # 分段长度（字符数）
    chunk_size = Column(Integer, nullable=False, default=500)
    # 分段重叠（字符数）
    chunk_overlap = Column(Integer, nullable=False, default=50)
    # 自定义分隔符（chunk_mode=delimiter 时使用）
    chunk_delimiter = Column(String(256), nullable=True, default="\n\n")
    # OCR 识别开关（针对 PDF / 图片）
    ocr_enabled = Column(Boolean, nullable=False, default=False)

    # ===== 索引设置（对标 Dify） =====
    # 索引模式：keyword（关键词）/ vector（向量）/ hybrid（混合）
    index_mode = Column(String(32), nullable=False, default="keyword")
    # Embedding 模型名称（index_mode 含 vector/hybrid 时使用）
    embedding_model = Column(String(128), nullable=False, default="text-embedding-ada-002")
    # 关联的 LLMConfig.id（model_type=embedding）：优先用此配置的 base_url/api_key/model_name
    # 做向量化。为空时回退到 embedding_model 名称 + 默认 LLMConfig 凭证。
    embedding_config_id = Column(Integer, nullable=True)
    # Embedding 维度（预留，部分模型需指定）
    embedding_dimension = Column(Integer, nullable=False, default=1536)

    # ===== 检索设置（对标 Dify） =====
    # 检索返回数量 top_k
    retrieval_top_k = Column(Integer, nullable=False, default=5)
    # 分数阈值（0~1，低于此分数的结果被过滤）
    score_threshold = Column(Integer, nullable=False, default=0)
    # 是否启用重排序
    rerank_enabled = Column(Integer, nullable=False, default=0)
    # 重排序模型名称（rerank_enabled=True 时使用）
    rerank_model = Column(String(128), nullable=True, default="")
    # 混合检索权重（index_mode=hybrid 时使用，两者之和应为 100）
    hybrid_vector_weight = Column(Integer, nullable=False, default=70)
    hybrid_keyword_weight = Column(Integer, nullable=False, default=30)

    documents = relationship(
        "KnowledgeDocument",
        back_populates="kb",
        cascade="all, delete-orphan",
        order_by="KnowledgeDocument.created_at",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase id={self.id} name={self.name!r}>"


class KnowledgeDocument(Base):
    """知识文档模型。"""

    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    source_type = Column(String(32), nullable=False, default="text")
    file_name = Column(String(512), nullable=True)
    file_type = Column(String(32), nullable=True)
    file_size = Column(Integer, nullable=True)
    # 上传文件在服务器上的保存路径（相对于 uploads 目录），供文件查询工具读取原始文件
    file_path = Column(String(512), nullable=True)
    # 分段数（解析后自动统计）
    segment_count = Column(Integer, nullable=False, default=1)

    # ===== 元数据与分类标签 =====
    # 文档描述/简介（有助于语义检索）
    description = Column(Text, nullable=True)
    # 所属分类/目录
    category = Column(String(255), nullable=True)
    # 自定义标签（JSON 键值对，如 {"版本": "v2.0", "作者": "张三"}）
    tags = Column(JSON, nullable=True, default=dict)
    # 生效时间（到期后自动停止检索）
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)

    # ===== 状态与权限 =====
    # 处理状态：uploading / parsing / indexing / available / failed
    status = Column(String(32), nullable=False, default="available")
    # 处理进度 0-100：0=刚创建，10=解析中，30=分段完成，30-100=向量化中，100=完成
    progress = Column(Integer, nullable=False, default=0)
    # 检索权重（1-10，数值越高优先级越高）
    retrieval_weight = Column(Integer, nullable=False, default=1)

    kb = relationship("KnowledgeBase", back_populates="documents")
    # 文档下的分段（chunking 产物），级联删除
    segments = relationship(
        "KnowledgeSegment",
        back_populates="doc",
        cascade="all, delete-orphan",
        order_by="KnowledgeSegment.seq",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} kb_id={self.kb_id} title={self.title!r}>"


class KnowledgeSegment(Base):
    """知识文档的分段（chunk）。

    文档入库时按知识库的 chunk_mode/chunk_size/chunk_overlap 配置切分为多个分段，
    检索在分段级别进行（而非整篇文档），命中只返回相关段，提升精准度并减少噪声。

    ``embedding`` 存储该段的向量（JSON 浮点数组）。当前未启用 pgvector，
    余弦相似度在 Python 侧用 numpy 计算（适合中小规模知识库）。
    """

    __tablename__ = "knowledge_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    doc_id = Column(Integer, ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    # 段序号（同一文档内从 0 递增）
    seq = Column(Integer, nullable=False, default=0)
    # 段文本
    content = Column(Text, nullable=False)
    # token/字符数（用于 BM25 的 |d| 归一化）
    token_count = Column(Integer, nullable=False, default=0)
    # 向量（JSON 浮点数组，index_mode 含 vector/hybrid 时填充）
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    doc = relationship("KnowledgeDocument", back_populates="segments")

    def __repr__(self) -> str:
        return f"<KnowledgeSegment id={self.id} doc_id={self.doc_id} seq={self.seq}>"
