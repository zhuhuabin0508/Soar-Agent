"""NotificationRule Pydantic Schema。"""
import json
from typing import Optional

from app.schemas._datetime import BeijingDatetime
from pydantic import BaseModel, Field, field_validator


class NotificationRuleCreate(BaseModel):
    """创建通知规则的请求体。"""

    name: str = Field(..., min_length=1, max_length=100, description="规则名称")
    description: Optional[str] = Field(None, description="规则说明")
    event_type: str = Field(..., max_length=50, description="触发事件类型，如 feedback / model_alert / * ")
    target_user_ids: list[int] = Field(default_factory=list, description="目标用户 ID 列表")
    target_roles: list[str] = Field(default_factory=list, description="目标角色列表，如 ['admin']")
    enabled: bool = Field(True, description="是否启用")


class NotificationRuleUpdate(BaseModel):
    """更新通知规则的请求体（所有字段可选）。"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    event_type: Optional[str] = Field(None, max_length=50)
    target_user_ids: Optional[list[int]] = None
    target_roles: Optional[list[str]] = None
    enabled: Optional[bool] = None


class NotificationRuleOut(BaseModel):
    """通知规则输出 Schema。

    ORM 中 ``target_user_ids`` / ``target_roles`` 以 JSON 字符串存储，
    此处通过 validator 解析为 list，避免前端拿到字符串。
    """

    id: int
    name: str
    description: Optional[str] = None
    event_type: str
    target_user_ids: list[int] = []
    target_roles: list[str] = []
    enabled: bool = True
    created_by: Optional[str] = None
    created_at: Optional[BeijingDatetime] = None
    updated_at: Optional[BeijingDatetime] = None

    model_config = {"from_attributes": True}

    @field_validator("target_user_ids", mode="before")
    @classmethod
    def _parse_user_ids(cls, v):
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return [int(i) for i in parsed if i is not None]
            except (ValueError, TypeError):
                return []
        return v or []

    @field_validator("target_roles", mode="before")
    @classmethod
    def _parse_roles(cls, v):
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return [str(r) for r in parsed if r]
            except (ValueError, TypeError):
                return []
        return v or []
