"""解析策略模型。

一个策略描述一种设备/数据源的告警日志格式，以 JSON 存储。
新增设备时只需创建新策略，不需要修改引擎代码。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.timezone import beijing_now
from app.database import Base


class ParseStrategy(Base):
    """解析策略配置。"""

    __tablename__ = "parse_strategies"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String(255), nullable=False, comment="策略名称")
    device_type = Column(String(64), default="", index=True, comment="设备类型标识")
    version = Column(String(32), default="1.0", comment="策略版本")
    status = Column(String(16), default="enabled", index=True, comment="enabled/disabled")
    config = Column(Text, nullable=False, comment="策略配置 JSON 全文")
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    def __repr__(self):
        return f"<ParseStrategy id={self.id} name={self.strategy_name!r} v={self.version!r}>"
