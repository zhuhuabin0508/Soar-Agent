"""LLMConfig 数据模型。

存储大模型供应商配置（API Key、Base URL、模型名等），
供 Agent 决策与节点执行时动态加载。可标记 ``is_default`` 作为默认模型。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.database import Base


class LLMConfig(Base):
    """LLM 配置模型。"""

    __tablename__ = "llm_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    provider = Column(String(64), nullable=False, default="anthropic")
    api_key = Column(String(512), nullable=False, default="")
    base_url = Column(String(512), nullable=False, default="")
    model_name = Column(String(128), nullable=False, default="")
    # 模型类型：chat（对话）/ embedding（向量化）。知识库配置 embedding 时从此类配置中选取。
    model_type = Column(String(32), nullable=False, default="chat")
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<LLMConfig id={self.id} name={self.name!r} provider={self.provider!r}>"
