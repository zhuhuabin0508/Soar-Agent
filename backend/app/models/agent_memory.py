"""Agent 记忆数据模型（多用户隔离）。

按 (user_id, agent_id) 分区存储长期记忆。
PostgreSQL to_tsvector 中文全文检索（GIN 索引通过原生 SQL 迁移创建）。
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func, Index
from sqlalchemy.dialects.postgresql import JSON

from app.database import Base


class AgentMemory(Base):
    """Agent 记忆条目（按 user_id + agent_id 分区）。

    存储用户与 Agent 对话过程中提取的长期记忆（事实/偏好/决策）。
    多用户隔离：所有查询必须带 WHERE user_id=:uid AND agent_id=:aid。
    """

    __tablename__ = "agent_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    content = Column(Text, nullable=False)
    summary = Column(String(512), nullable=True)  # LLM 生成的摘要
    category = Column(String(64), default="general")  # fact / preference / decision / ...
    hit_count = Column(Integer, default=0)  # 被检索命中次数
    # 威胁扫描状态（TIER 1 功能 2）：clean / blocked / pending
    threat_scan_status = Column(String(16), default="clean")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_agent_memories_user_agent", "user_id", "agent_id"),
        # 全文索引通过迁移 SQL 创建（GIN + to_tsvector('chinese', content)）
        # 见 app/core/security.py:run_lightweight_migrations
    )

    def __repr__(self) -> str:
        return (
            f"<AgentMemory id={self.id} user_id={self.user_id} "
            f"agent_id={self.agent_id} category={self.category!r}>"
        )
