"""系统配置 Schema。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SystemConfigOut(BaseModel):
    """系统配置项输出。"""

    key: str
    value: Optional[str] = None
    description: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SystemConfigUpdate(BaseModel):
    """批量更新系统配置请求体。"""

    configs: dict[str, str] = Field(
        ...,
        description="键值对批量更新 {key: value}",
    )
