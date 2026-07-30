"""ExecutionTrace 数据模型。

记录工作流执行过程中每个节点的运行轨迹（输入 / 输出 / 状态 / 时间戳），
用于执行详情回放与大屏 MTTR 统计。
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database import Base


class ExecutionTrace(Base):
    """节点执行轨迹模型，与 Execution 一对多关系。"""

    __tablename__ = "execution_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=False)
    node_id = Column(String(100), nullable=False)
    node_type = Column(String(100), nullable=False)
    node_label = Column(String(255), nullable=True)
    input = Column(JSON, nullable=True)
    output = Column(JSON, nullable=True)
    # success / failed / skipped / waiting
    status = Column(String(50), default="running")
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)

    execution = relationship("Execution", back_populates="traces")

    def __repr__(self) -> str:
        return (
            f"<ExecutionTrace id={self.id} execution_id={self.execution_id} "
            f"node_id={self.node_id!r} status={self.status!r}>"
        )
