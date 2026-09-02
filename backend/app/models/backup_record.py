"""数据备份记录模型。

记录每次数据库备份的元信息（文件路径、大小、类型、状态、范围、校验值等），
用于备份管理与恢复追溯。

字段说明：
- ``name``：备份名称（用户自定义或自动生成）
- ``note``：备注说明（备份原因）
- ``scope``：备份范围，``full``（全量）或逗号分隔的模块名（``agents,kbs,tools``）
- ``storage_location``：存储位置，``local`` / ``oss`` / ``s3`` / ``nfs``
- ``is_encrypted``：是否加密存储
- ``checksum`` / ``checksum_algo``：完整性校验值（SHA-256）
- ``duration_seconds``：备份耗时（秒）
- ``version``：备份时的系统版本（用于恢复前版本兼容性校验）
- ``expired``：是否已过期（保留策略清理标记）
"""
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, Boolean, func

from app.database import Base


class BackupRecord(Base):
    """备份记录：记录一次 pg_dump 备份的文件信息与执行状态。

    预置 status 取值：
    - ``running``：备份进行中
    - ``completed``：备份完成
    - ``failed``：备份失败（详见 error_message）
    """

    __tablename__ = "backup_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 备份文件绝对路径
    file_path = Column(String(500), nullable=False)
    # 文件大小（MB）
    file_size_mb = Column(Float, nullable=False)
    # 备份类型：manual（手动）/ scheduled（定时）
    backup_type = Column(String(20), nullable=False)
    # 状态：running / completed / failed
    status = Column(String(20), nullable=False, default="completed")
    # 失败时的错误信息
    error_message = Column(Text, nullable=True)
    # 触发者（用户名）
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    # 完成时间（用于计算耗时）
    completed_at = Column(DateTime, nullable=True)
    # 备份名称（用户自定义或自动生成 backup_YYYYMMDD_HHMMSS）
    name = Column(String(200), nullable=True)
    # 备注说明（备份原因）
    note = Column(Text, nullable=True)
    # 备份范围：full 或逗号分隔的模块名（agents,kbs,tools,workflows,assets,system_config,users）
    scope = Column(String(500), nullable=False, default="full")
    # 存储位置：local / oss / s3 / nfs
    storage_location = Column(String(20), nullable=False, default="local")
    # 是否加密存储
    is_encrypted = Column(Boolean, nullable=False, default=False)
    # 完整性校验值（SHA-256）
    checksum = Column(String(128), nullable=True)
    # 校验算法
    checksum_algo = Column(String(20), nullable=True)
    # 备份耗时（秒）
    duration_seconds = Column(Float, nullable=True)
    # 备份时的系统版本（用于恢复前版本兼容性校验）
    version = Column(String(50), nullable=True)
    # 是否已过期（保留策略清理标记）
    expired = Column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<BackupRecord id={self.id} type={self.backup_type!r} status={self.status!r}>"
