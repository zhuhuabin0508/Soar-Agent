"""Workflow 数据模型。"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database import Base


class Workflow(Base):
    """工作流模型，存储 DAG 图配置（nodes / edges）。

    新增字段（P0-2 webhook 防护）：
    - ``webhook_secret``：per-workflow 的 webhook 触发密钥，调用 webhook 时需携带。
    - ``enabled``：工作流启用开关，禁用后 webhook 触发返回 404。
    """

    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    graph_config = Column(JSON, nullable=False)
    # Webhook 触发密钥（32 位 hex），创建工作流时自动生成，可重置
    webhook_secret = Column(String(64), nullable=True)
    # 工作流启用开关；禁用后 webhook 触发将返回 404
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    executions = relationship("Execution", back_populates="workflow")
    versions = relationship("WorkflowVersion", back_populates="workflow")

    def __repr__(self) -> str:
        return f"<Workflow id={self.id} name={self.name!r}>"
