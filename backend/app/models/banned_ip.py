"""已封禁 IP 记录模型。

存储被封禁的 IP 信息，包括封禁等级、时长、过期时间、地区、违规次数等。
供 IP 风险研判智能体的 query_banned_ip / record_ban 工具使用，
以及前端「已封禁 IP」页面展示。
"""
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


def _beijing_now():
    """北京时间（UTC+8），供 created_at/updated_at 默认值使用。

    Docker 容器默认 UTC 时区，datetime.utcnow() 返回 UTC 时间，
    前端 new Date() 将无时区 ISO 字符串视为本地时间，导致显示差 8 小时。
    统一存北京时间可保证前端直接显示正确。
    """
    return datetime.utcnow() + timedelta(hours=8)


class BannedIP(Base):
    """已封禁 IP 记录。"""

    __tablename__ = "banned_ips"

    id = Column(Integer, primary_key=True, index=True)
    ip = Column(String(45), unique=True, index=True, nullable=False)
    ban_level = Column(String(20), nullable=False, default="medium")
    ban_duration = Column(Integer, nullable=False, default=3600)
    expired_at = Column(DateTime, nullable=False)
    region = Column(String(50), default="")
    violation_count = Column(Integer, default=0)
    reason = Column(Text, default="")
    status = Column(String(20), default="active")
    # 来源标识：manual=手动添加，agent=智能体添加
    source = Column(String(20), default="agent")
    created_at = Column(DateTime, default=_beijing_now)
    updated_at = Column(DateTime, default=_beijing_now, onupdate=_beijing_now)

    def __repr__(self):
        return f"<BannedIP ip={self.ip!r} level={self.ban_level!r} status={self.status!r}>"
