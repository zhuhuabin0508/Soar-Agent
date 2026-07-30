"""数据备份记录模型。

记录每次数据库备份的元信息（文件路径、大小、类型、状态等），
用于备份管理与恢复追溯。
"""
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func

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

    def __repr__(self) -> str:
        return f"<BackupRecord id={self.id} type={self.backup_type!r} status={self.status!r}>"
