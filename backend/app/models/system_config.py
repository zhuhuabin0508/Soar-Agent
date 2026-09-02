"""系统配置模型。

键值对存储平台级配置（平台名称、Logo、主题色、CORS 白名单等）。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.database import Base


class SystemConfig(Base):
    """系统配置键值对。

    预置 key：
    - ``platform_name``：平台显示名称
    - ``logo_url``：Logo 图片 URL
    - ``primary_color``：主题色（十六进制）
    - ``cors_origins``：CORS 白名单（逗号分隔）
    - ``webhook_rate_limit``：Webhook 限流（次/分钟）
    """

    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<SystemConfig key={self.key!r}>"
