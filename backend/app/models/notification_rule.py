"""通知规则模型。

用于配置「哪些事件类型需要通知、通知给谁」的路由规则。
``dispatch_notification`` 在派发通知时会查询匹配的启用规则，
将通知投递给规则中指定的目标用户（按 ID 或按角色匹配）。

关键设计：
- ``event_type`` 对应 Notification.type，如 feedback / model_alert / system_update / announcement / execution_failed
- ``target_user_ids`` / ``target_roles`` 以 JSON 数组存储，支持「指定用户 + 指定角色」混合目标
- ``enabled`` 控制规则启停，停用后不再匹配
- 未匹配任何规则时，``dispatch_notification`` 回退为全员广播，保证不丢通知
"""
import json
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.database import Base


class NotificationRule(Base):
    """通知路由规则：事件类型 → 目标用户/角色。"""

    __tablename__ = "notification_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 规则名称，便于管理员识别，如「反馈提交通知运维组」
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    # 触发事件类型，对应 Notification.type；"*" 表示匹配所有事件
    event_type = Column(String(50), nullable=False, index=True)
    # 目标用户 ID 列表（JSON 数组，如 [1, 3, 5]）
    target_user_ids = Column(Text, nullable=False, default="[]")
    # 目标角色列表（JSON 数组，如 ["admin", "analyst"]）
    target_roles = Column(Text, nullable=False, default="[]")
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def get_target_user_ids(self) -> list[int]:
        """解析目标用户 ID 列表。"""
        try:
            ids = json.loads(self.target_user_ids or "[]")
            return [int(i) for i in ids if i is not None]
        except (ValueError, TypeError):
            return []

    def get_target_roles(self) -> list[str]:
        """解析目标角色列表。"""
        try:
            roles = json.loads(self.target_roles or "[]")
            return [str(r) for r in roles if r]
        except (ValueError, TypeError):
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "event_type": self.event_type,
            "target_user_ids": self.get_target_user_ids(),
            "target_roles": self.get_target_roles(),
            "enabled": self.enabled,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<NotificationRule id={self.id} name={self.name!r} "
            f"event_type={self.event_type!r} enabled={self.enabled}>"
        )
