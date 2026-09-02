"""解析错误队列模型。

JSON 解析失败或无匹配策略的原始数据进入错误队列，支持重试与人工处理。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.timezone import beijing_now
from app.database import Base


class ParseErrorQueue(Base):
    """解析错误队列。"""

    __tablename__ = "parse_error_queue"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(128), nullable=True, comment="告警唯一ID（可空）")
    strategy_id = Column(Integer, nullable=True, comment="命中/尝试的策略 ID（可空）")
    raw_data = Column(Text, nullable=False, comment="原始数据全文")
    error_type = Column(
        String(64),
        default="",
        index=True,
        comment="json_parse_failed/no_strategy_matched/db_write_failed/field_validation_failed",
    )
    error_msg = Column(Text, default="", comment="错误详情")
    retry_count = Column(Integer, default=0, comment="重试次数")
    status = Column(
        String(16),
        default="pending",
        index=True,
        comment="pending/reprocessing/manual/resolved",
    )
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    def __repr__(self):
        return f"<ParseErrorQueue id={self.id} type={self.error_type!r} status={self.status!r}>"
