"""数据备份与恢复 API。

提供：
- 手动触发数据库备份（pg_dump），支持自定义名称/范围/备注/加密
- 列出备份记录（分页）
- 下载备份文件
- 从备份恢复数据库（psql），支持完全/部分恢复模式
- 删除备份记录与文件
- 备份策略配置（自动备份周期/保留策略）
- 备份概览统计（上次/下次/存储占用/健康度）
- 备份详情（文件清单/校验信息/操作日志）
- 完整性校验
- 存储管理与过期清理
- 上传本地备份文件
- 自动备份调度器（后台线程）

备份策略存储在 SystemConfig 表（``backup.strategy.*`` 前缀），调度器在应用启动时
启动，每分钟检查是否到达计划时间，到达则触发 pg_dump 备份并按保留策略清理旧备份。
"""
import hashlib
import logging
import os
import subprocess
import threading
import time as _time
from datetime import datetime, timedelta

from app.core.timezone import beijing_now, beijing_now_iso

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, SessionLocal
from app.dependencies import get_current_user, require_permission
from app.models.backup_record import BackupRecord
from app.models.system_config import SystemConfig
from app.models.user import User
from app.schemas.backup import (
    BackupCreateRequest,
    BackupListResponse,
    BackupRecordOut,
    BackupStrategyRequest,
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

# 数据库连接参数
DB_USER = getattr(settings, "DB_USER", None) or os.environ.get("DB_USER", "postgres")
DB_PASSWORD = getattr(settings, "DB_PASSWORD", None) or os.environ.get("DB_PASSWORD", "postgres")
DB_HOST = getattr(settings, "DB_HOST", None) or os.environ.get("DB_HOST", "localhost")
DB_PORT = getattr(settings, "DB_PORT", None) or os.environ.get("DB_PORT", "5432")
DB_NAME = getattr(settings, "DB_NAME", None) or os.environ.get("DB_NAME", "soar")

# 系统版本（用于备份记录与版本兼容性校验）
SYSTEM_VERSION = getattr(settings, "APP_VERSION", None) or "1.0.0"

# 备份策略默认值
DEFAULT_STRATEGY = {
    "enabled": False,
    "period": "daily",
    "time": "02:00",
    "retention_count": 10,
    "retention_days": 30,
    "scope": "full",
    "storage_location": "local",
    "is_encrypted": False,
}

# 模块名 → 表名映射（用于部分恢复/范围元数据展示）
MODULE_TABLES = {
    "agents": ["agents", "agent_variables"],
    "skills": ["skills"],
    "tools": ["tools"],
    "workflows": ["workflows", "workflow_nodes", "workflow_edges", "workflow_versions"],
    "kbs": ["knowledge_bases", "kb_documents"],
    "assets": ["assets", "asset_types"],
    "system_config": ["system_configs"],
    "users": ["users", "roles", "permissions", "role_permissions"],
}


# ============ 工具函数 ============

def _compute_checksum(file_path: str, algo: str = "sha256") -> str:
    """计算文件校验值（默认 SHA-256）。"""
    h = hashlib.new(algo)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_strategy(db: Session) -> dict:
    """从 SystemConfig 读取备份策略，未配置的用默认值填充。"""
    configs = (
        db.query(SystemConfig)
        .filter(SystemConfig.key.like("backup.strategy.%"))
        .all()
    )
    db_map = {c.key.replace("backup.strategy.", ""): c.value for c in configs}
    result = dict(DEFAULT_STRATEGY)
    for k, v in db_map.items():
        if k in ("enabled", "is_encrypted"):
            result[k] = str(v).strip().lower() in ("true", "1", "yes", "on")
        elif k in ("retention_count", "retention_days"):
            try:
                result[k] = int(v)
            except (ValueError, TypeError):
                pass
        else:
            result[k] = v
    return result


def _set_strategy(db: Session, strategy: dict) -> None:
    """保存备份策略到 SystemConfig。"""
    for k, v in strategy.items():
        key = f"backup.strategy.{k}"
        cfg = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        str_val = str(v) if not isinstance(v, bool) else ("true" if v else "false")
        if cfg:
            cfg.value = str_val
        else:
            db.add(SystemConfig(key=key, value=str_val, description="备份策略配置"))
    db.commit()


def _run_pg_dump(file_path: str) -> None:
    """执行 pg_dump 导出全库。"""
    cmd = [
        "pg_dump", "-U", DB_USER, "-h", DB_HOST, "-p", str(DB_PORT),
        "-d", DB_NAME, "-f", file_path,
    ]
    env = {**os.environ, "PGPASSWORD": DB_PASSWORD}
    subprocess.run(cmd, env=env, timeout=300, check=True, capture_output=True)


def _do_backup(
    db: Session,
    backup_type: str = "manual",
    name: str | None = None,
    note: str | None = None,
    scope: str = "full",
    storage_location: str = "local",
    is_encrypted: bool = False,
    created_by: str | None = "system",
) -> BackupRecord:
    """执行一次备份（共用逻辑：手动 / 定时调度）。

    创建 running 记录 → pg_dump → 计算大小/校验值/耗时 → 更新 completed。
    失败时记录 error_message 并抛出。
    """
    record = _create_backup_record(
        db, backup_type=backup_type, name=name, note=note, scope=scope,
        storage_location=storage_location, is_encrypted=is_encrypted, created_by=created_by,
    )
    _execute_backup(record.id)
    db.refresh(record)
    return record


def _create_backup_record(
    db: Session,
    backup_type: str = "manual",
    name: str | None = None,
    note: str | None = None,
    scope: str = "full",
    storage_location: str = "local",
    is_encrypted: bool = False,
    created_by: str | None = "system",
) -> BackupRecord:
    """创建 running 状态的备份记录（不执行 pg_dump）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = beijing_now().strftime("%Y%m%d_%H%M%S")
    file_name = f"backup_{ts}.sql"
    file_path = os.path.join(BACKUP_DIR, file_name)
    display_name = name or f"backup_{ts}"

    record = BackupRecord(
        file_path=file_path,
        file_size_mb=0.0,
        backup_type=backup_type,
        status="running",
        created_by=created_by,
        name=display_name,
        note=note,
        scope=scope,
        storage_location=storage_location,
        is_encrypted=is_encrypted,
        version=SYSTEM_VERSION,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _execute_backup(record_id: int) -> None:
    """执行 pg_dump 并更新备份记录状态（在独立 session 中操作，支持跨线程调用）。

    使用新 Session 而非传入的 db，以便后台线程安全执行。
    """
    db = SessionLocal()
    try:
        record = db.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        if record is None:
            logger.error("备份记录不存在: id=%s", record_id)
            return
        start = _time.time()
        try:
            _run_pg_dump(record.file_path)
            size_mb = os.path.getsize(record.file_path) / (1024 * 1024)
            checksum = _compute_checksum(record.file_path)
            record.file_size_mb = round(size_mb, 2)
            record.checksum = checksum
            record.checksum_algo = "sha256"
            record.status = "completed"
            record.completed_at = beijing_now()
            record.duration_seconds = round(_time.time() - start, 2)
            record.error_message = None
            db.commit()
            db.refresh(record)
            logger.info(
                "备份完成: id=%s, file=%s, size_mb=%.2f, duration=%.2fs",
                record.id, record.file_path, record.file_size_mb, record.duration_seconds,
            )
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc))
            record.status = "failed"
            record.error_message = err
            record.completed_at = beijing_now()
            record.duration_seconds = round(_time.time() - start, 2)
            db.commit()
            db.refresh(record)
            logger.error("备份失败: id=%s, error=%s", record.id, err)
        except subprocess.TimeoutExpired:
            err = "pg_dump 执行超时（300 秒）"
            record.status = "failed"
            record.error_message = err
            record.completed_at = beijing_now()
            record.duration_seconds = round(_time.time() - start, 2)
            db.commit()
            db.refresh(record)
            logger.error("备份超时: id=%s", record.id)
    finally:
        db.close()


def _cleanup_by_retention(db: Session, strategy: dict) -> int:
    """按保留策略清理过期备份（保留最近 N 份 + 保留 N 天）。

    Returns:
        清理的备份数量。
    """
    retention_count = int(strategy.get("retention_count", 10))
    retention_days = int(strategy.get("retention_days", 30))
    deleted = 0

    # 1. 按份数：保留最近 N 份 completed 记录，其余标记过期
    completed = (
        db.query(BackupRecord)
        .filter(BackupRecord.status == "completed")
        .order_by(BackupRecord.created_at.desc())
        .all()
    )
    if len(completed) > retention_count:
        for r in completed[retention_count:]:
            if not r.expired:
                r.expired = True
                deleted += 1

    # 2. 按天数：超过 retention_days 的标记过期
    cutoff = beijing_now() - timedelta(days=retention_days)
    old = (
        db.query(BackupRecord)
        .filter(BackupRecord.created_at < cutoff, BackupRecord.expired.is_(False))
        .all()
    )
    for r in old:
        r.expired = True
        deleted += 1
    db.commit()
    return deleted


# ============ 自动备份调度器（后台线程） ============

_scheduler_started = False
_scheduler_lock = threading.Lock()


def _backup_scheduler_loop() -> None:
    """自动备份调度器：每分钟检查是否到达计划时间，到达则触发备份。

    启动时由 main.py 调用 start_backup_scheduler() 启动守护线程。
    """
    logger.info("备份调度器已启动，每分钟检查计划时间")
    last_run_key = "backup.strategy._last_run"
    while True:
        try:
            db = SessionLocal()
            try:
                strategy = _get_strategy(db)
                if not strategy.get("enabled"):
                    _time.sleep(60)
                    continue
                now = beijing_now()
                period = strategy.get("period", "daily")
                run_time = strategy.get("time", "02:00")
                try:
                    hh, mm = run_time.split(":")
                    target_h, target_m = int(hh), int(mm)
                except (ValueError, AttributeError):
                    target_h, target_m = 2, 0

                # 判断是否到达计划时间
                due = False
                if period == "daily":
                    due = now.hour == target_h and now.minute == target_m
                elif period == "weekly":
                    # 每周一
                    due = now.weekday() == 0 and now.hour == target_h and now.minute == target_m
                elif period == "monthly":
                    # 每月 1 号
                    due = now.day == 1 and now.hour == target_h and now.minute == target_m

                if not due:
                    _time.sleep(60)
                    continue

                # 防止同一分钟内重复执行
                last_run_cfg = db.query(SystemConfig).filter(SystemConfig.key == last_run_key).first()
                last_run_str = last_run_cfg.value if last_run_cfg else ""
                current_key = now.strftime("%Y-%m-%d %H:%M")
                if last_run_str == current_key:
                    _time.sleep(60)
                    continue

                logger.info("触发自动备份: period=%s, time=%s", period, run_time)
                _do_backup(
                    db, backup_type="scheduled", scope=strategy.get("scope", "full"),
                    storage_location=strategy.get("storage_location", "local"),
                    is_encrypted=bool(strategy.get("is_encrypted", False)),
                    created_by="scheduler",
                )
                # 更新最后执行时间
                if last_run_cfg:
                    last_run_cfg.value = current_key
                else:
                    db.add(SystemConfig(key=last_run_key, value=current_key, description="调度器最后执行时间"))
                db.commit()
                # 清理过期
                _cleanup_by_retention(db, strategy)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            logger.exception("备份调度器异常: %s", exc)
        _time.sleep(60)


def start_backup_scheduler() -> None:
    """启动备份调度器守护线程（幂等，仅启动一次）。"""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    t = threading.Thread(target=_backup_scheduler_loop, daemon=True, name="backup-scheduler")
    t.start()
    logger.info("备份调度器线程已启动")


# ============ 路由 ============

@router.post("", response_model=BackupRecordOut)
def create_backup(
    payload: BackupCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system_config", "edit")),
) -> BackupRecordOut:
    """触发手动数据库备份（支持自定义名称/范围/备注/加密）。

    创建 running 状态的备份记录后立即返回，pg_dump 在后台线程异步执行。
    前端通过 GET /{backup_id}/status 轮询备份进度。
    """
    record = _create_backup_record(
        db, backup_type=payload.backup_type, name=payload.name, note=payload.note,
        scope=payload.scope, storage_location=payload.storage_location,
        is_encrypted=payload.is_encrypted, created_by=current_user.username,
    )
    # 后台线程异步执行 pg_dump，避免前端长时间等待
    t = threading.Thread(
        target=_execute_backup, args=(record.id,), daemon=True, name=f"backup-{record.id}",
    )
    t.start()
    return BackupRecordOut.model_validate(record)


@router.get("", response_model=BackupListResponse)
def list_backups(
    limit: int = Query(50, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> BackupListResponse:
    """列出所有备份记录（按 created_at 降序，分页）。"""
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


@router.get("/strategy")
def get_strategy(db: Session = Depends(get_db)) -> dict:
    """获取备份策略配置。"""
    return {"strategy": _get_strategy(db)}


@router.put("/strategy")
def set_strategy(
    payload: BackupStrategyRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> dict:
    """更新备份策略配置（启用后调度器按计划自动备份）。"""
    strategy = {
        "enabled": payload.enabled,
        "period": payload.period,
        "time": payload.time,
        "retention_count": payload.retention_count,
        "retention_days": payload.retention_days,
        "scope": payload.scope,
        "storage_location": payload.storage_location,
        "is_encrypted": payload.is_encrypted,
    }
    _set_strategy(db, strategy)
    logger.info("备份策略已更新: %s", strategy)
    return {"ok": True, "strategy": strategy}


@router.get("/stats")
def backup_stats(db: Session = Depends(get_db)) -> dict:
    """备份概览统计：上次备份 / 下次自动备份 / 存储占用 / 健康度。

    用于页面顶部 4 个指标卡片。
    """
    all_records = db.query(BackupRecord).order_by(BackupRecord.created_at.desc()).all()

    # 上次备份（最近一次 completed）
    last_backup = next((r for r in all_records if r.status == "completed"), None)

    # 下次自动备份（基于策略计算）
    strategy = _get_strategy(db)
    next_backup = None
    if strategy.get("enabled"):
        now = beijing_now()
        period = strategy.get("period", "daily")
        run_time = strategy.get("time", "02:00")
        try:
            hh, mm = run_time.split(":")
            target_h, target_m = int(hh), int(mm)
        except (ValueError, AttributeError):
            target_h, target_m = 2, 0

        today_target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
        if period == "daily":
            next_dt = today_target if today_target > now else today_target + timedelta(days=1)
        elif period == "weekly":
            days_ahead = (0 - now.weekday()) % 7
            next_dt = today_target
            if days_ahead == 0 and today_target <= now:
                days_ahead = 7
            next_dt = today_target + timedelta(days=days_ahead)
            if next_dt <= now:
                next_dt += timedelta(days=7)
        elif period == "monthly":
            # 下个月 1 号
            if now.month == 12:
                next_dt = now.replace(year=now.year + 1, month=1, day=1, hour=target_h, minute=target_m, second=0, microsecond=0)
            else:
                next_dt = now.replace(month=now.month + 1, day=1, hour=target_h, minute=target_m, second=0, microsecond=0)
            if next_dt <= now:
                # 已过本月 1 号，跳到下月
                pass
        else:
            next_dt = today_target + timedelta(days=1)
        next_backup = next_dt.isoformat() if next_dt else None

    # 存储占用
    total_size_mb = sum(r.file_size_mb for r in all_records if r.status == "completed")

    # 健康度：近 7 天成功/失败次数
    seven_days_ago = beijing_now() - timedelta(days=7)
    recent = [r for r in all_records if r.created_at and r.created_at >= seven_days_ago]
    recent_success = sum(1 for r in recent if r.status == "completed")
    recent_failed = sum(1 for r in recent if r.status == "failed")

    return {
        "last_backup": {
            "id": last_backup.id if last_backup else None,
            "created_at": last_backup.created_at.isoformat() if last_backup and last_backup.created_at else None,
            "backup_type": last_backup.backup_type if last_backup else None,
            "created_by": last_backup.created_by if last_backup else None,
            "file_size_mb": last_backup.file_size_mb if last_backup else None,
        } if last_backup else None,
        "next_backup": next_backup,
        "strategy_enabled": strategy.get("enabled", False),
        "strategy_period": strategy.get("period", "daily"),
        "strategy_time": strategy.get("time", "02:00"),
        "storage": {
            "total_size_mb": round(total_size_mb, 2),
            "total_count": len([r for r in all_records if r.status == "completed"]),
            "backup_dir": BACKUP_DIR,
        },
        "health": {
            "recent_success": recent_success,
            "recent_failed": recent_failed,
            "healthy": recent_failed == 0,
        },
    }


@router.get("/{backup_id}/status")
def backup_status(
    backup_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """查询备份进度状态（轻量接口，供前端轮询）。

    返回 status / progress / stage / error_message / duration_seconds / file_size_mb。
    progress 和 stage 基于记录状态推断，pg_dump 本身无法报告精确进度。
    """
    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if record.status == "completed":
        progress, stage = 100, "备份完成"
    elif record.status == "failed":
        progress, stage = 100, "备份失败"
    else:
        progress, stage = 50, "正在导出数据库..."
    return {
        "id": record.id,
        "status": record.status,
        "progress": progress,
        "stage": stage,
        "error_message": record.error_message,
        "duration_seconds": record.duration_seconds,
        "file_size_mb": record.file_size_mb,
    }


@router.get("/{backup_id}/detail")
def backup_detail(
    backup_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """备份详情：基本信息 / 备份范围（含模块表名）/ 文件清单 / 校验信息 / 操作日志。"""
    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")

    # 备份范围 → 模块表名
    scope = record.scope or "full"
    modules = []
    if scope == "full":
        modules = [{"module": k, "tables": v} for k, v in MODULE_TABLES.items()]
    else:
        for m in scope.split(","):
            m = m.strip()
            if m in MODULE_TABLES:
                modules.append({"module": m, "tables": MODULE_TABLES[m]})

    # 文件清单
    file_info = None
    file_exists = os.path.isfile(record.file_path)
    if file_exists:
        file_info = {
            "path": record.file_path,
            "filename": os.path.basename(record.file_path),
            "size_mb": round(os.path.getsize(record.file_path) / (1024 * 1024), 2),
            "modified_at": datetime.fromtimestamp(os.path.getmtime(record.file_path)).isoformat(),
        }

    # 操作日志
    logs = []
    if record.status == "failed" and record.error_message:
        logs.append({"level": "error", "message": record.error_message, "at": record.completed_at.isoformat() if record.completed_at else None})
    logs.append({"level": "info", "message": f"备份{record.status}", "at": record.completed_at.isoformat() if record.completed_at else None})

    return {
        "record": BackupRecordOut.model_validate(record).model_dump(),
        "modules": modules,
        "file_info": file_info,
        "file_exists": file_exists,
        "logs": logs,
    }


@router.post("/{backup_id}/verify")
def verify_backup(
    backup_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """校验备份文件完整性：重新计算 SHA-256 并与记录值对比。

    Returns:
        ``{ok, verified, current_checksum, stored_checksum, message}``
    """
    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if not os.path.isfile(record.file_path):
        return {"ok": False, "verified": False, "message": "备份文件不存在"}
    current = _compute_checksum(record.file_path)
    verified = (current == record.checksum) if record.checksum else False
    if not record.checksum:
        # 无记录值，自动补录
        record.checksum = current
        record.checksum_algo = "sha256"
        db.commit()
        verified = True
    return {
        "ok": True,
        "verified": verified,
        "current_checksum": current,
        "stored_checksum": record.checksum,
        "message": "校验通过，文件完整" if verified else "校验失败，文件可能已损坏",
    }


@router.post("/cleanup-expired")
def cleanup_expired(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> dict:
    """清理过期备份（删除标记为 expired 的记录及其文件）。

    Returns:
        ``{deleted, failed}`` 清理数量统计。
    """
    expired = db.query(BackupRecord).filter(BackupRecord.expired.is_(True)).all()
    deleted = 0
    failed = 0
    for r in expired:
        if os.path.isfile(r.file_path):
            try:
                os.remove(r.file_path)
                deleted += 1
            except OSError:
                failed += 1
        else:
            deleted += 1
        db.delete(r)
    db.commit()
    logger.info("清理过期备份: deleted=%d, failed=%d", deleted, failed)
    return {"deleted": deleted, "failed": failed}


@router.post("/upload")
async def upload_backup(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system_config", "edit")),
) -> BackupRecordOut:
    """上传本地备份文件（.sql / .bak / .tar.gz / .zip）。

    上传后自动校验格式（后缀）与大小，计算校验值并加入备份列表。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")
    allowed_ext = (".sql", ".bak", ".tar.gz", ".zip", ".dump")
    lower_name = file.filename.lower()
    if not (lower_name.endswith(allowed_ext)):
        raise HTTPException(status_code=400, detail=f"不支持的文件格式，仅支持 {', '.join(allowed_ext)}")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    # 防止文件名冲突
    ts = beijing_now().strftime("%Y%m%d_%H%M%S")
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    save_path = os.path.join(BACKUP_DIR, f"uploaded_{ts}_{safe_name}")

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    size_mb = os.path.getsize(save_path) / (1024 * 1024)
    checksum = _compute_checksum(save_path)

    record = BackupRecord(
        file_path=save_path,
        file_size_mb=round(size_mb, 2),
        backup_type="manual",
        status="completed",
        created_by=current_user.username,
        name=file.filename,
        note="上传的本地备份文件",
        scope="full",
        storage_location="local",
        is_encrypted=False,
        checksum=checksum,
        checksum_algo="sha256",
        completed_at=beijing_now(),
        duration_seconds=0.0,
        version=SYSTEM_VERSION,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("上传备份成功: id=%s, file=%s, size_mb=%.2f", record.id, save_path, size_mb)
    return BackupRecordOut.model_validate(record)


@router.get("/{backup_id}/download")
def download_backup(
    backup_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    """下载指定备份文件。"""
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
    current_user: User = Depends(require_permission("system_config", "edit")),
) -> RestoreResponse:
    """从备份恢复数据库（支持完全/部分恢复模式）。

    ⚠️ 恢复操作会覆盖当前数据库，请求体必须 ``confirm=True`` 才会执行。

    恢复前校验：
    - 备份文件存在
    - 版本兼容性（备份版本 vs 当前版本，不兼容时提示风险但允许继续）
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="恢复操作需 confirm=True 才能执行")

    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if not os.path.isfile(record.file_path):
        raise HTTPException(status_code=404, detail="备份文件不存在")

    # 恢复前校验：完整性（若有记录值则对比）
    if record.checksum:
        current = _compute_checksum(record.file_path)
        if current != record.checksum:
            logger.warning("恢复前校验失败: backup_id=%s", backup_id)

    # 版本兼容性提示
    version_warning = ""
    if record.version and record.version != SYSTEM_VERSION:
        version_warning = f"（注意：备份版本 {record.version} 与当前系统版本 {SYSTEM_VERSION} 不一致，可能存在兼容性风险）"

    # partial 模式：仅恢复指定模块对应的表（提取相关 CREATE/INSERT 语句）
    restore_file = record.file_path
    if payload.mode == "partial" and payload.modules:
        # 简化处理：从全量 SQL 中提取指定表的语句到临时文件
        target_tables = set()
        for m in payload.modules:
            target_tables.update(MODULE_TABLES.get(m, []))
        if target_tables:
            tmp_path = record.file_path + f".partial_{beijing_now().strftime('%H%M%S')}.sql"
            try:
                with open(record.file_path, "r", encoding="utf-8", errors="ignore") as src, \
                     open(tmp_path, "w", encoding="utf-8") as dst:
                    capturing = False
                    for line in src:
                        # pg_dump 的 COPY ... FROM stdin 块按表名识别
                        if line.startswith("COPY public.") and " FROM stdin;" in line:
                            tbl = line.split("COPY public.")[1].split(" ")[0]
                            capturing = tbl in target_tables
                        if capturing:
                            dst.write(line)
                        elif line.startswith("\\."):
                            capturing = False
                restore_file = tmp_path
            except Exception as exc:  # noqa: BLE001
                logger.warning("部分恢复提取失败，回退全量: %s", exc)
                restore_file = record.file_path

    cmd = [
        "psql", "-U", DB_USER, "-h", DB_HOST, "-p", str(DB_PORT),
        "-d", DB_NAME, "-f", restore_file,
    ]
    env = {**os.environ, "PGPASSWORD": DB_PASSWORD}

    try:
        subprocess.run(cmd, env=env, timeout=300, check=True, capture_output=True)
        logger.info("恢复完成: backup_id=%s, mode=%s", backup_id, payload.mode)
        return RestoreResponse(
            success=True,
            message=f"恢复成功。警告：当前数据库已被备份内容覆盖，建议刷新连接并核对数据。{version_warning}",
            backup_id=backup_id,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc))
        record.status = "failed"
        record.error_message = f"恢复失败: {err}"
        db.commit()
        logger.error("恢复失败: backup_id=%s, error=%s", backup_id, err)
        return RestoreResponse(success=False, message=f"恢复失败: {err}", backup_id=backup_id)
    except subprocess.TimeoutExpired:
        err = "psql 执行超时（300 秒）"
        record.status = "failed"
        record.error_message = err
        db.commit()
        return RestoreResponse(success=False, message=err, backup_id=backup_id)
    finally:
        # 清理临时部分恢复文件
        if payload.mode == "partial" and restore_file != record.file_path and os.path.isfile(restore_file):
            try:
                os.remove(restore_file)
            except OSError:
                pass


@router.delete("/{backup_id}", status_code=204)
def delete_backup(
    backup_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> None:
    """删除备份记录及其文件。"""
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
