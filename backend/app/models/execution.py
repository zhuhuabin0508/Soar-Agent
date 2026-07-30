"""Execution 数据模型。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database import Base


class Execution(Base):
    """执行记录模型，记录单次工作流执行的状态与结果。"""

    __tablename__ = "executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"))
    # 智能体测试时关联的 agent_id（工作流执行时为 None）
    agent_id = Column(Integer, nullable=True, index=True)
    status = Column(String(50), default="pending")
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    # 执行完成时间，用于 MTTR（平均响应时间）计算
    finished_at = Column(DateTime, nullable=True)
    # 触发类型：webhook（线上）/ test_run（节点/流程测试）/ manual（手动）/ agent_test（智能体测试）
    trigger_type = Column(String(32), nullable=False, default="webhook")

    workflow = relationship("Workflow", back_populates="executions")
    logs = relationship(
        "ExecutionLog",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="ExecutionLog.timestamp",
    )
    traces = relationship(
        "ExecutionTrace",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="ExecutionTrace.started_at",
    )

    def __repr__(self) -> str:
        return (
            f"<Execution id={self.id} workflow_id={self.workflow_id} "
            f"status={self.status!r}>"
        )
