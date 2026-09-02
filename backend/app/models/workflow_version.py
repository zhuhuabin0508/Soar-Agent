"""WorkflowVersion 数据模型，用于工作流版本管理与回滚。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database import Base


class WorkflowVersion(Base):
    """工作流版本快照模型，存储某次保存时的完整工作流状态。

    ``snapshot`` 字段保存 ``{name, graph_config, enabled}`` 三项，
    回滚时直接用 snapshot 覆盖当前工作流对应字段。
    """

    __tablename__ = "workflow_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    change_note = Column(String(500), nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    workflow = relationship("Workflow", back_populates="versions")

    def __repr__(self) -> str:
        return (
            f"<WorkflowVersion id={self.id} "
            f"workflow_id={self.workflow_id} "
            f"version_number={self.version_number}>"
        )
