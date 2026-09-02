"""ExecutionLog 数据模型。

记录工作流执行过程中每个节点的日志输出（info/warning/error），
用于执行详情回放与排查。与 ExecutionTrace（节点级输入输出快照）互补。
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base


class ExecutionLog(Base):
    """执行日志模型，与 Execution 一对多关系。"""

    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=False)
    node_id = Column(String(100), nullable=True)
    level = Column(String(32), nullable=False, default="info")
    message = Column(Text, nullable=False, default="")
    timestamp = Column(DateTime, server_default=func.now())

    execution = relationship("Execution", back_populates="logs")

    def __repr__(self) -> str:
        return (
            f"<ExecutionLog id={self.id} execution_id={self.execution_id} "
            f"node_id={self.node_id!r} level={self.level!r}>"
        )
