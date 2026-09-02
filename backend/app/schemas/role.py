"""角色管理 Schema。"""
from typing import Any, Optional

from app.schemas._datetime import BeijingDatetime
from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    """创建角色请求体。"""

    name: str = Field(..., min_length=2, max_length=64, description="角色名称")
    description: Optional[str] = Field(None, max_length=255)
    permissions: dict[str, list[str]] = Field(
        default_factory=dict,
        description="权限矩阵 {模块: [动作列表]}",
    )


class RoleUpdate(BaseModel):
    """更新角色请求体。"""

    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[dict[str, list[str]]] = None


class RoleOut(BaseModel):
    """角色输出 Schema。"""

    id: int
    name: str
    description: Optional[str] = None
    permissions: dict[str, Any] = Field(default_factory=dict)
    is_system: bool = False
    created_at: Optional[BeijingDatetime] = None
    user_count: int = 0

    model_config = {"from_attributes": True}
