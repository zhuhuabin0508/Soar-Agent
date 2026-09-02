"""入库指标模型（按小时聚合）。

原子累加当小时的 total/success/partial/fail 计数与解析耗时。
"""
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from app.core.timezone import beijing_now
from app.database import Base


class IngestionMetric(Base):
    """按小时聚合的解析入库指标。"""

    __tablename__ = "ingestion_metrics"

    id = Column(Integer, primary_key=True, index=True)
    stat_hour = Column(String(16), nullable=False, comment="统计小时，格式 YYYY-MM-DDTHH")
    strategy_id = Column(Integer, nullable=True, comment="策略 ID，NULL 表示全局")
    strategy_name = Column(String(255), default="", comment="策略名称冗余（展示用）")
    total_count = Column(Integer, default=0, comment="总处理数")
    success_count = Column(Integer, default=0, comment="完全成功数")
    partial_count = Column(Integer, default=0, comment="部分成功数（有警告）")
    fail_count = Column(Integer, default=0, comment="失败数")
    total_parse_ms = Column(Integer, default=0, comment="解析耗时累计（毫秒），avg = total_parse_ms / total")
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    __table_args__ = (
        UniqueConstraint("stat_hour", "strategy_id", name="uq_ingestion_metrics_hour_strategy"),
    )

    def __repr__(self):
        return f"<IngestionMetric hour={self.stat_hour!r} strategy={self.strategy_id} total={self.total_count}>"
