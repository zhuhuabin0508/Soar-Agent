"""通知中心模型。

记录推送给用户的通知消息，支持：
- 定向通知（user_id 指向具体用户）
- 全员广播（user_id 为 null）
- 已读状态跟踪与关联资源回溯（related_type / related_id）。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.database import Base


class Notification(Base):
    """通知消息：系统向用户推送的公告 / 告警 / 执行结果等。"""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 目标用户，为 null 表示全员广播
    user_id = Column(Integer, nullable=True, index=True)
    # 通知类型：announcement / system_alert / execution_failed 等
    type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    # 关联资源类型：workflow / execution 等
    related_type = Column(String(50), nullable=True)
    related_id = Column(Integer, nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    def __repr__(self) -> str:
        return f"<Notification id={self.id} type={self.type!r} title={self.title!r}>"
