"""数据备份与恢复 Schema。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BackupRecordOut(BaseModel):
    """备份记录输出。"""

    id: int
    file_path: str
    file_size_mb: float
    backup_type: str
    status: str
    error_message: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BackupCreateRequest(BaseModel):
    """创建备份请求体。"""

    backup_type: str = Field("manual", description="备份类型：manual / scheduled")


class BackupListResponse(BaseModel):
    """备份记录列表响应。"""

    backups: list[BackupRecordOut]
    total: int


class RestoreRequest(BaseModel):
    """恢复请求体。

    恢复操作会覆盖当前数据库，必须显式确认 ``confirm=True`` 才会执行。
    """

    confirm: bool = Field(False, description="必须为 True 才能执行恢复")


class RestoreResponse(BaseModel):
    """恢复响应。"""

    success: bool
    message: str
    backup_id: int
