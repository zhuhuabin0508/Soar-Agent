"""数据备份与恢复 API。

提供：
- 手动触发数据库备份（pg_dump）
- 列出备份记录（分页）
- 下载备份文件
- 从备份恢复数据库（psql）
- 删除备份记录与文件
"""
import logging
import os
import subprocess
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.backup_record import BackupRecord
from app.models.user import User
from app.schemas.backup import (
    BackupCreateRequest,
    BackupListResponse,
    BackupRecordOut,
    RestoreRequest,
    RestoreResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/system/backup",
    tags=["backup"],
    dependencies=[Depends(get_current_user)],
)

# 备份文件存放目录
BACKUP_DIR = "/app/backups"

# 数据库连接参数：优先取 settings 中的拆分字段（若存在），否则从环境变量读取，
# 最后回退到与默认 DATABASE_URL 一致的默认值。
# config.py 当前仅暴露 DATABASE_URL，故此处以环境变量为主。
DB_USER = getattr(settings, "DB_USER", None) or os.environ.get("DB_USER", "postgres")
DB_PASSWORD = getattr(settings, "DB_PASSWORD", None) or os.environ.get("DB_PASSWORD", "postgres")
DB_HOST = getattr(settings, "DB_HOST", None) or os.environ.get("DB_HOST", "localhost")
DB_PORT = getattr(settings, "DB_PORT", None) or os.environ.get("DB_PORT", "5432")
DB_NAME = getattr(settings, "DB_NAME", None) or os.environ.get("DB_NAME", "soar")


@router.post("", response_model=BackupRecordOut)
def create_backup(
    payload: BackupCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system_config", "edit")),
) -> BackupRecordOut:
    """触发手动数据库备份。

    使用 pg_dump 导出全库到 /app/backups/ 目录，文件名格式
    ``backup_YYYYMMDD_HHMMSS.sql``，超时 300 秒。备份结果（含失败信息）
    记入 BackupRecord 表。

    Returns:
        BackupRecordOut: 新建的备份记录。
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    file_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    file_path = os.path.join(BACKUP_DIR, file_name)

    record = BackupRecord(
        file_path=file_path,
        file_size_mb=0.0,
        backup_type=payload.backup_type,
        status="running",
        created_by=current_user.username,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    cmd = [
        "pg_dump",
        "-U", DB_USER,
        "-h", DB_HOST,
        "-p", str(DB_PORT),
        "-d", DB_NAME,
        "-f", file_path,
    ]
    env = {**os.environ, "PGPASSWORD": DB_PASSWORD}

    try:
        subprocess.run(cmd, env=env, timeout=300, check=True, capture_output=True)
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        record.file_size_mb = round(size_mb, 2)
        record.status = "completed"
        record.error_message = None
        db.commit()
        db.refresh(record)
        logger.info(
            "备份完成: id=%s, file=%s, size_mb=%.2f",
            record.id, file_path, record.file_size_mb,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc))
        record.status = "failed"
        record.error_message = err
        db.commit()
        db.refresh(record)
        logger.error("备份失败: id=%s, error=%s", record.id, err)
        raise HTTPException(status_code=500, detail=f"备份失败: {err}")
    except subprocess.TimeoutExpired:
        err = "pg_dump 执行超时（300 秒）"
        record.status = "failed"
        record.error_message = err
        db.commit()
        db.refresh(record)
        logger.error("备份超时: id=%s", record.id)
        raise HTTPException(status_code=504, detail=err)

    return BackupRecordOut.model_validate(record)


@router.get("", response_model=BackupListResponse)
def list_backups(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> BackupListResponse:
    """列出所有备份记录（按 created_at 降序，分页）。

    Returns:
        BackupListResponse: 备份记录列表与总数。
    """
    q = db.query(BackupRecord)
    total = q.count()
    records = (
        q.order_by(BackupRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return BackupListResponse(
        backups=[BackupRecordOut.model_validate(r) for r in records],
        total=total,
    )


@router.get("/{backup_id}/download")
def download_backup(
    backup_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    """下载指定备份文件。

    Raises:
        HTTPException(404): 备份记录或文件不存在。
    """
    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if not os.path.isfile(record.file_path):
        raise HTTPException(status_code=404, detail="备份文件不存在")
    return FileResponse(
        path=record.file_path,
        media_type="application/octet-stream",
        filename=os.path.basename(record.file_path),
    )


@router.post("/{backup_id}/restore", response_model=RestoreResponse)
def restore_backup(
    backup_id: int,
    payload: RestoreRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> RestoreResponse:
    """从备份恢复数据库。

    ⚠️ 恢复操作会覆盖当前数据库，请求体必须 ``confirm=True`` 才会执行。
    使用 psql 执行备份 SQL 恢复，超时 300 秒。

    Returns:
        RestoreResponse: 恢复结果（响应中会提示用户当前数据库已被覆盖）。
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="恢复操作需 confirm=True 才能执行")

    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if not os.path.isfile(record.file_path):
        raise HTTPException(status_code=404, detail="备份文件不存在")

    cmd = [
        "psql",
        "-U", DB_USER,
        "-h", DB_HOST,
        "-p", str(DB_PORT),
        "-d", DB_NAME,
        "-f", record.file_path,
    ]
    env = {**os.environ, "PGPASSWORD": DB_PASSWORD}

    try:
        subprocess.run(cmd, env=env, timeout=300, check=True, capture_output=True)
        logger.info("恢复完成: backup_id=%s", backup_id)
        return RestoreResponse(
            success=True,
            message="恢复成功。警告：当前数据库已被备份内容覆盖，建议刷新连接并核对数据。",
            backup_id=backup_id,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc))
        record.status = "failed"
        record.error_message = f"恢复失败: {err}"
        db.commit()
        logger.error("恢复失败: backup_id=%s, error=%s", backup_id, err)
        return RestoreResponse(
            success=False,
            message=f"恢复失败: {err}",
            backup_id=backup_id,
        )
    except subprocess.TimeoutExpired:
        err = "psql 执行超时（300 秒）"
        record.status = "failed"
        record.error_message = err
        db.commit()
        logger.error("恢复超时: backup_id=%s", backup_id)
        return RestoreResponse(
            success=False,
            message=err,
            backup_id=backup_id,
        )


@router.delete("/{backup_id}", status_code=204)
def delete_backup(
    backup_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> None:
    """删除备份记录及其文件。

    先删除磁盘文件，再删除数据库记录。

    Raises:
        HTTPException(404): 备份记录不存在。
    """
    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")

    if os.path.isfile(record.file_path):
        try:
            os.remove(record.file_path)
        except OSError as exc:
            logger.warning("删除备份文件失败: file=%s, error=%s", record.file_path, exc)

    db.delete(record)
    db.commit()
    logger.info("已删除备份记录: id=%s", backup_id)
    return None
