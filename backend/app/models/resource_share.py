"""资源共享授权模型：owner 可将资源的编辑权限共享给其他用户。

资源级 owner 权限控制补充：默认仅创建者（owner）与 admin 能编辑/删除资源。
owner 可通过 ``resource_shares`` 表把某资源的编辑权限授权给其他用户，
被授权用户对该资源也拥有编辑权限（不改变 owner 归属）。

``resource_type`` 取值：workflow / agent / tool / skill / knowledge_base。
``resource_id`` 为对应资源表的主键 ID。
"""
from sqlalchemy import Column, DateTime, Integer, String, func

from app.database import Base


class ResourceShare(Base):
    """资源共享授权记录。"""

    __tablename__ = "resource_shares"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 资源类型：workflow / agent / tool / skill / knowledge_base
    resource_type = Column(String(32), nullable=False)
    # 资源ID（对应资源表主键）
    resource_id = Column(Integer, nullable=False)
    # 被授权用户ID
    shared_with = Column(Integer, nullable=False)
    # 授权人（owner）用户ID
    granted_by = Column(Integer, nullable=False)
    # 授权权限级别：view（仅查看）/ edit（编辑）
    # edit 隐含 view；owner 与 admin 始终拥有 edit 权限
    permission = Column(String(16), nullable=False, default="edit", server_default="edit")
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<ResourceShare id={self.id} "
            f"{self.resource_type}:{self.resource_id} -> user:{self.shared_with}>"
        )
