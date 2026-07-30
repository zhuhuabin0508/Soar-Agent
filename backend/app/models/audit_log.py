"""操作审计日志模型。

记录用户在平台上的关键操作（登录/CRUD/工作流执行等），
用于等保合规审计与安全事件追溯。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.database import Base


class AuditLog(Base):
    """审计日志：谁在何时从哪个 IP 对什么资源做了什么操作。"""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 操作者信息
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(64), nullable=True)
    # 操作类型：login / logout / create / update / delete / execute / export 等
    action = Column(String(32), nullable=False, index=True)
    # 资源类型：workflow / tool / agent / user / role / system_config 等
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(String(64), nullable=True)
    # 操作详情（JSON 字符串）
    detail = Column(Text, nullable=True)
    # 客户端 IP
    ip_address = Column(String(64), nullable=True)
    # 操作结果：success / failed
    result = Column(String(16), nullable=False, default="success")
    created_at = Column(DateTime, server_default=func.now(), index=True)

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} user={self.username!r} action={self.action!r}>"
