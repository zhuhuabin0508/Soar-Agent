"""角色模型。

支持可配置权限矩阵，每个角色通过 permissions JSON 存储各模块的权限动作列表。
系统内置角色（admin/analyst/viewer）标记 is_system=True，不可删除。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON

from app.database import Base


class Role(Base):
    """角色模型，用于 RBAC 权限矩阵。

    permissions 结构示例::

        {
            "workflow": ["view", "edit", "delete", "execute"],
            "tool": ["view", "execute"],
            ...
        }
    """

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)
    # 权限矩阵：{模块名: [动作列表]}
    permissions = Column(JSON, nullable=False, default=dict)
    # 系统内置角色不可删除
    is_system = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name!r}>"
