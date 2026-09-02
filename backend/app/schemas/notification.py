"""Notification Pydantic Schema。"""
from typing import Optional

from app.schemas._datetime import BeijingDatetime
from pydantic import BaseModel, Field


class NotificationCreate(BaseModel):
    """创建 Notification 的请求体。"""

    type: str = Field(..., description="通知类型：announcement / system_alert / execution_failed 等")
    title: str = Field(..., description="通知标题")
    content: Optional[str] = Field(None, description="通知正文")
    user_id: Optional[int] = Field(None, description="目标用户 ID，为空表示全员广播")
    related_type: Optional[str] = Field(None, description="关联资源类型，如 workflow / execution")
    related_id: Optional[int] = Field(None, description="关联资源 ID")


class NotificationOut(BaseModel):
    """Notification 输出 Schema。"""

    id: int
    user_id: Optional[int] = None
    type: str
    title: str
    content: Optional[str] = None
    is_read: bool = False
    related_type: Optional[str] = None
    related_id: Optional[int] = None
    created_by: Optional[str] = None
    created_at: Optional[BeijingDatetime] = None

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """Notification 列表响应，含未读计数。"""

    notifications: list[NotificationOut]
    total: int
    unread_count: int
