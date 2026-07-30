"""系统监控 API。

提供：
- 服务健康检查（数据库 / Redis / 自身）
- 系统性能指标（CPU / 内存 / 磁盘）
- 操作审计日志查询（分页 + 过滤）
"""
import logging
import os
import shutil
from datetime import datetime
from typing import Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.audit_log import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/system-monitor",
    tags=["system-monitor"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/health")
def check_health(db: Session = Depends(get_db)) -> dict:
    """检查各服务健康状态。

    Returns:
        ``{services: [{name, status, latency_ms, detail}], overall: "healthy"/"degraded"} ``
    """
    services = []

    # 1. 数据库健康检查
    try:
        start = datetime.now()
        db.execute(text("SELECT 1"))
        latency = (datetime.now() - start).total_seconds() * 1000
        services.append({
            "name": "PostgreSQL",
            "status": "healthy",
            "latency_ms": round(latency, 2),
            "detail": "连接正常",
        })
    except Exception as exc:  # noqa: BLE001
        services.append({
            "name": "PostgreSQL",
            "status": "unhealthy",
            "latency_ms": 0,
            "detail": str(exc),
        })

    # 2. Redis 健康检查
    try:
        import redis as redis_lib
        from app.config import settings
        start = datetime.now()
        r = redis_lib.from_url(settings.REDIS_URL, socket_timeout=3)
        r.ping()
        latency = (datetime.now() - start).total_seconds() * 1000
        services.append({
            "name": "Redis",
            "status": "healthy",
            "latency_ms": round(latency, 2),
            "detail": "连接正常",
        })
    except Exception as exc:  # noqa: BLE001
        services.append({
            "name": "Redis",
            "status": "unhealthy",
            "latency_ms": 0,
            "detail": str(exc),
        })

    # 3. API 服务自身
    services.append({
        "name": "API Server",
        "status": "healthy",
        "latency_ms": 0,
        "detail": f"PID {os.getpid()}",
    })

    # 4. Celery Worker（通过检查 Redis 队列是否有消费者间接判断）
    try:
        import redis as redis_lib
        from app.config import settings
        r = redis_lib.from_url(settings.REDIS_URL, socket_timeout=3)
        # 检查 celery 队列长度
        queue_len = r.llen("celery")
        services.append({
            "name": "Celery Worker",
            "status": "healthy",
            "latency_ms": 0,
            "detail": f"队列积压: {queue_len} 条",
        })
    except Exception as exc:  # noqa: BLE001
        services.append({
            "name": "Celery Worker",
            "status": "unknown",
            "latency_ms": 0,
            "detail": "无法检测",
        })

    overall = "healthy" if all(s["status"] == "healthy" for s in services) else "degraded"
    return {"services": services, "overall": overall, "checked_at": datetime.now().isoformat()}


@router.get("/performance")
def get_performance() -> dict:
    """获取系统性能指标（CPU / 内存 / 磁盘）。

    Returns:
        ``{cpu_percent, memory: {total, used, percent}, disk: {total, used, percent}, uptime_seconds}``
    """
    # CPU 使用率
    cpu_percent = psutil.cpu_percent(interval=0.5)

    # 内存
    mem = psutil.virtual_memory()

    # 磁盘（当前工作目录所在分区）
    disk = shutil.disk_usage("/")

    # 进程运行时间
    try:
        process = psutil.Process()
        uptime = int(datetime.now().timestamp() - process.create_time())
    except Exception:  # noqa: BLE001
        uptime = 0

    return {
        "cpu_percent": cpu_percent,
        "cpu_count": psutil.cpu_count(),
        "memory": {
            "total_gb": round(mem.total / 1024 ** 3, 2),
            "used_gb": round(mem.used / 1024 ** 3, 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1024 ** 3, 2),
            "used_gb": round(disk.used / 1024 ** 3, 2),
            "percent": round(disk.used / disk.total * 100, 1),
        },
        "uptime_seconds": uptime,
    }


@router.get("/audit-logs")
def list_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None, description="按操作类型过滤"),
    resource_type: Optional[str] = Query(None, description="按资源类型过滤"),
    username: Optional[str] = Query(None, description="按用户名过滤"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("audit_log", "view")),
) -> dict:
    """查询操作审计日志（分页 + 过滤）。

    Returns:
        ``{logs: [...], total: N}``
    """
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    if username:
        q = q.filter(AuditLog.username.ilike(f"%{username}%"))

    total = q.count()
    logs = (
        q.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "logs": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "username": l.username,
                "action": l.action,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "detail": l.detail,
                "ip_address": l.ip_address,
                "result": l.result,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


# ============ 服务日志（通过 Docker SDK 获取容器日志） ============

def _get_docker_client():
    """获取 Docker 客户端（通过挂载的 docker.sock）。

    失败返回 None（调用方处理）。
    """
    try:
        import docker

        return docker.from_env()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Docker 客户端初始化失败: %s", exc)
        return None


# SOAR 平台相关容器名前缀（只列出这些，避免暴露无关容器）
_SOAR_CONTAINER_PREFIX = "soar-"


@router.get("/services")
def list_service_containers() -> dict:
    """列出 SOAR 平台的所有 Docker 容器及状态。

    通过 Docker SDK 获取 ``soar-`` 前缀的容器，返回名称、状态、镜像、运行时长。
    若 docker.sock 未挂载或不可访问，返回 ``{services: [], error: ...}``。
    """
    client = _get_docker_client()
    if client is None:
        return {
            "services": [],
            "error": "无法访问 Docker（docker.sock 未挂载或 Docker SDK 未安装）",
        }
    services = []
    try:
        for c in client.containers.list(all=True):
            if not c.name.startswith(_SOAR_CONTAINER_PREFIX):
                continue
            # 容器状态：created/restarting/running/removing/paused/exited/dead
            status = c.status
            # 镜像信息容错：重建后旧镜像可能已被删除，c.image 访问可能抛 404
            image_tag = ""
            try:
                tags = c.image.tags
                image_tag = tags[0] if tags else (c.image.id[:19] if c.image.id else "")
            except Exception as img_exc:  # noqa: BLE001
                logger.debug("获取容器 %s 镜像信息失败: %s", c.name, img_exc)
                image_tag = "<image-unavailable>"
            services.append({
                "name": c.name,
                "status": status,
                "image": image_tag,
                "short_id": c.short_id,
                "running": status == "running",
            })
        services.sort(key=lambda s: s["name"])
    except Exception as exc:  # noqa: BLE001
        logger.exception("列出容器失败: %s", exc)
        return {"services": [], "error": str(exc)}
    return {"services": services}


@router.get("/services/{container_name}/logs")
def get_service_logs(
    container_name: str,
    tail: int = Query(200, ge=1, le=2000, description="获取最后 N 行日志"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("audit_log", "view")),
) -> dict:
    """获取指定服务容器的最近日志。

    Args:
        container_name: 容器名（如 ``soar-backend`` / ``soar-postgres``）。
        tail: 获取最后 N 行日志（默认 200，上限 2000）。

    Returns:
        ``{container, tail, logs}``，logs 为字符串行列表。
    """
    # 安全：只允许 soar- 前缀的容器，避免任意容器日志泄露
    if not container_name.startswith(_SOAR_CONTAINER_PREFIX):
        raise HTTPException(status_code=400, detail="仅允许查看 SOAR 平台服务日志")

    client = _get_docker_client()
    if client is None:
        raise HTTPException(status_code=503, detail="无法访问 Docker（docker.sock 未挂载）")
    try:
        container = client.containers.get(container_name)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"容器不存在: {container_name}")

    try:
        # timestamps=True 带时间戳；tail=tail 取最后 N 行
        raw = container.logs(tail=tail, timestamps=True)
        # docker logs 返回 bytes，按行解码
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return {
            "container": container_name,
            "status": container.status,
            "tail": tail,
            "logs": lines,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("获取容器日志失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"获取日志失败: {exc}")
