"""数据备份与恢复 Schema。"""
from typing import Optional

from app.schemas._datetime import BeijingDatetime
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
    created_at: Optional[BeijingDatetime] = None
    completed_at: Optional[BeijingDatetime] = None
    name: Optional[str] = None
    note: Optional[str] = None
    scope: str = "full"
    storage_location: str = "local"
    is_encrypted: bool = False
    checksum: Optional[str] = None
    checksum_algo: Optional[str] = None
    duration_seconds: Optional[float] = None
    version: Optional[str] = None
    expired: bool = False

    model_config = {"from_attributes": True}


class BackupCreateRequest(BaseModel):
    """创建备份请求体。

    支持自定义名称、范围、备注、加密等选项。
    - ``backup_type``：manual / scheduled
    - ``scope``：full（全量）或逗号分隔的模块名（agents,kbs,tools,...）
        注意：当前底层为 pg_dump 全库导出，scope 作为元数据记录，
        部分恢复时可据此选择恢复哪些表的 SQL。
    """

    backup_type: str = Field("manual", description="备份类型：manual / scheduled")
    name: Optional[str] = Field(None, description="备份名称，为空时自动生成")
    note: Optional[str] = Field(None, description="备注说明")
    scope: str = Field("full", description="备份范围：full 或逗号分隔的模块名")
    storage_location: str = Field("local", description="存储位置")
    is_encrypted: bool = Field(False, description="是否加密存储")


class BackupListResponse(BaseModel):
    """备份记录列表响应。"""

    backups: list[BackupRecordOut]
    total: int


class RestoreRequest(BaseModel):
    """恢复请求体。

    恢复操作会覆盖当前数据库，必须显式确认 ``confirm=True`` 才会执行。
    - ``mode``：full（完全恢复，覆盖全部）/ partial（部分恢复，仅恢复指定模块）
    - ``modules``：partial 模式下要恢复的模块列表
    """

    confirm: bool = Field(False, description="必须为 True 才能执行恢复")
    mode: str = Field("full", description="恢复模式：full / partial")
    modules: Optional[list[str]] = Field(None, description="部分恢复时的模块列表")
    password: Optional[str] = Field(None, description="管理员密码（生产环境二次验证）")


class RestoreResponse(BaseModel):
    """恢复响应。"""

    success: bool
    message: str
    backup_id: int


class BackupStrategyRequest(BaseModel):
    """备份策略配置请求体。"""

    enabled: bool = Field(False, description="是否启用自动备份")
    period: str = Field("daily", description="备份周期：daily / weekly / monthly")
    time: str = Field("02:00", description="备份时间（HH:MM）")
    retention_count: int = Field(10, description="保留最近 N 份")
    retention_days: int = Field(30, description="保留 N 天")
    scope: str = Field("full", description="备份范围")
    storage_location: str = Field("local", description="存储位置")
    is_encrypted: bool = Field(False, description="是否加密存储")
