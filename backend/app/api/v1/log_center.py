"""日志中心 API。

统一查询系统所有日志：操作审计日志、执行记录、执行日志、模型调用日志。
并提供日志保留策略配置（保留天数 + 最大存储量）与手动清理。

路由前缀：/logs
- GET  /logs/audit          操作审计日志（AuditLog）
- GET  /logs/executions     执行记录（Execution）
- GET  /logs/execution-logs 执行日志（ExecutionLog，节点级）
- GET  /logs/model-calls    模型调用日志（ModelCallLog）
- GET  /logs/stats          日志统计（各类型条数 + 趋势 + 错误聚合 + 成功率）
- GET  /logs/retention      获取保留策略配置
- PUT  /logs/retention      设置保留策略配置
- POST /logs/cleanup        手动清理过期日志

权限：查看日志需要 audit_log.view 或对应模块 view；修改保留策略需 system_config.edit。
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text, case
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.audit_log import AuditLog
from app.models.execution import Execution
from app.models.execution_log import ExecutionLog
from app.models.model_call_log import ModelCallLog
from app.models.system_config import SystemConfig
from app.models.user import User
from app.core.timezone import beijing_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logs", tags=["log-center"])

# 错误分类规则：将原始 error_message 归类为语义化错误类型
_ERROR_PATTERNS = [
    ("dns_resolve", ["name resolution", "temporary failure", "getaddrinfo"]),
    ("timeout", ["timeout", "timed out", "read timeout", "connect timeout"]),
    ("quota_exceeded", ["quota", "rate limit", "429", "too many requests"]),
    ("auth_failed", ["401", "403", "unauthorized", "forbidden", "api key", "authentication"]),
    ("model_unavailable", ["404", "not found", "model not found", "does not exist"]),
    ("server_error", ["500", "502", "503", "504", "internal server error", "bad gateway", "service unavailable"]),
    ("network_error", ["connection", "refused", "reset", "broken pipe", "network"]),
]


def _classify_error(msg: str) -> str:
    """将原始错误信息归类为语义化错误类型。"""
    if not msg:
        return "unknown"
    low = str(msg).lower()
    for category, keywords in _ERROR_PATTERNS:
        if any(kw in low for kw in keywords):
            return category
    return "other"


def _get_config(db: Session, key: str, default: str) -> str:
    cfg = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    return cfg.value if cfg and cfg.value else default


# 操作审计日志
@router.get("/audit")
def list_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None, description="按操作类型过滤"),
    resource_type: Optional[str] = Query(None, description="按资源类型过滤"),
    username: Optional[str] = Query(None, description="按用户名模糊过滤"),
    result: Optional[str] = Query(None, description="按结果过滤 success/failed"),
    start_time: Optional[str] = Query(None, description="起始时间 ISO"),
    end_time: Optional[str] = Query(None, description="结束时间 ISO"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("audit_log", "view")),
) -> dict:
    """查询操作审计日志（分页 + 多维过滤）。"""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    if username:
        q = q.filter(AuditLog.username.ilike(f"%{username}%"))
    if result:
        q = q.filter(AuditLog.result == result)
    if start_time:
        try:
            q = q.filter(AuditLog.created_at >= datetime.fromisoformat(start_time))
        except ValueError:
            pass
    if end_time:
        try:
            q = q.filter(AuditLog.created_at <= datetime.fromisoformat(end_time))
        except ValueError:
            pass
    total = q.count()
    logs = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
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


# 执行记录
@router.get("/executions")
def list_execution_records(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    workflow_id: Optional[int] = Query(None, description="按工作流过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    trigger_type: Optional[str] = Query(None, description="按触发类型过滤"),
    start_time: Optional[str] = Query(None, description="起始时间 ISO"),
    end_time: Optional[str] = Query(None, description="结束时间 ISO"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("execution", "view")),
) -> dict:
    """查询执行记录（分页 + 多维过滤）。"""
    q = db.query(Execution)
    if workflow_id is not None:
        q = q.filter(Execution.workflow_id == workflow_id)
    if status:
        q = q.filter(Execution.status == status)
    if trigger_type:
        q = q.filter(Execution.trigger_type == trigger_type)
    if start_time:
        try:
            q = q.filter(Execution.created_at >= datetime.fromisoformat(start_time))
        except ValueError:
            pass
    if end_time:
        try:
            q = q.filter(Execution.created_at <= datetime.fromisoformat(end_time))
        except ValueError:
            pass
    total = q.count()
    rows = q.order_by(Execution.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "workflow_id": r.workflow_id,
                "trigger_type": r.trigger_type,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ],
    }


# 执行日志（节点级）
@router.get("/execution-logs")
def list_execution_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    execution_id: Optional[int] = Query(None, description="按执行 ID 过滤"),
    node_id: Optional[str] = Query(None, description="按节点 ID 模糊过滤"),
    level: Optional[str] = Query(None, description="按级别过滤 info/warning/error"),
    keyword: Optional[str] = Query(None, description="按消息关键字模糊过滤"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("execution", "view")),
) -> dict:
    """查询执行日志（节点级，ExecutionLog）。"""
    q = db.query(ExecutionLog)
    if execution_id is not None:
        q = q.filter(ExecutionLog.execution_id == execution_id)
    if node_id:
        q = q.filter(ExecutionLog.node_id.ilike(f"%{node_id}%"))
    if level:
        q = q.filter(ExecutionLog.level == level)
    if keyword:
        q = q.filter(ExecutionLog.message.ilike(f"%{keyword}%"))
    total = q.count()
    logs = q.order_by(ExecutionLog.timestamp.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": l.id,
                "execution_id": l.execution_id,
                "node_id": l.node_id,
                "level": l.level,
                "message": l.message,
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            }
            for l in logs
        ],
    }


# 模型调用日志
@router.get("/model-calls")
def list_model_call_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="按状态过滤 success/failed"),
    model_name: Optional[str] = Query(None, description="按模型名模糊过滤"),
    provider: Optional[str] = Query(None, description="按供应商过滤"),
    trigger_type: Optional[str] = Query(None, description="按触发来源过滤"),
    agent_id: Optional[int] = Query(None, description="按智能体 ID 过滤"),
    start_time: Optional[str] = Query(None, description="起始时间 ISO"),
    end_time: Optional[str] = Query(None, description="结束时间 ISO"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("llm_config", "view")),
) -> dict:
    """查询模型调用日志（ModelCallLog）。"""
    q = db.query(ModelCallLog)
    if status:
        q = q.filter(ModelCallLog.status == status)
    if model_name:
        q = q.filter(ModelCallLog.model_name.ilike(f"%{model_name}%"))
    if provider:
        q = q.filter(ModelCallLog.provider == provider)
    if trigger_type:
        q = q.filter(ModelCallLog.trigger_type == trigger_type)
    if agent_id is not None:
        q = q.filter(ModelCallLog.agent_id == agent_id)
    if start_time:
        try:
            q = q.filter(ModelCallLog.created_at >= datetime.fromisoformat(start_time))
        except ValueError:
            pass
    if end_time:
        try:
            q = q.filter(ModelCallLog.created_at <= datetime.fromisoformat(end_time))
        except ValueError:
            pass
    total = q.count()
    logs = q.order_by(ModelCallLog.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": l.id,
                "model_config_id": l.model_config_id,
                "model_name": l.model_name,
                "provider": l.provider,
                "status": l.status,
                "latency_ms": l.latency_ms,
                "input_tokens": l.input_tokens,
                "output_tokens": l.output_tokens,
                "total_tokens": l.total_tokens,
                "error_message": l.error_message,
                "error_category": _classify_error(l.error_message) if l.status == "failed" else None,
                "prompt_summary": getattr(l, "prompt_summary", None),
                "response_summary": getattr(l, "response_summary", None),
                "error_stack": getattr(l, "error_stack", None),
                "trigger_type": l.trigger_type,
                "agent_id": l.agent_id,
                "user_id": l.user_id,
                "source_ip": l.source_ip,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


# 模型调用详情（单条完整信息）
@router.get("/model-calls/{log_id}")
def get_model_call_detail(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("llm_config", "view")),
) -> dict:
    """获取单条模型调用日志的完整详情（含 prompt/response 摘要、错误堆栈）。"""
    l = db.query(ModelCallLog).filter(ModelCallLog.id == log_id).first()
    if not l:
        return {"error": "not_found"}
    return {
        "id": l.id,
        "model_config_id": l.model_config_id,
        "model_name": l.model_name,
        "provider": l.provider,
        "status": l.status,
        "latency_ms": l.latency_ms,
        "input_tokens": l.input_tokens,
        "output_tokens": l.output_tokens,
        "total_tokens": l.total_tokens,
        "error_message": l.error_message,
        "error_category": _classify_error(l.error_message) if l.status == "failed" else None,
        "error_stack": getattr(l, "error_stack", None),
        "prompt_summary": getattr(l, "prompt_summary", None),
        "response_summary": getattr(l, "response_summary", None),
        "trigger_type": l.trigger_type,
        "agent_id": l.agent_id,
        "user_id": l.user_id,
        "source_ip": l.source_ip,
        "session_id": getattr(l, "session_id", None),
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }


# 日志统计：各类型条数 + 趋势 + 错误聚合 + 成功率 + 存储大小
@router.get("/stats")
def get_log_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """日志统计：各类型条数 + 7天趋势 + 错误聚合 + 模型调用成功率 + 存储大小。"""
    audit_count = db.query(AuditLog).count()
    exec_count = db.query(Execution).count()
    exec_log_count = db.query(ExecutionLog).count()
    model_call_count = db.query(ModelCallLog).count()

    # 估算存储大小：用 PostgreSQL pg_total_relation_size 查询表大小
    table_sizes = {}
    try:
        for label, tbl in [
            ("audit_logs", "audit_logs"),
            ("executions", "executions"),
            ("execution_logs", "execution_logs"),
            ("model_call_logs", "model_call_logs"),
        ]:
            row = db.execute(
                text("SELECT pg_total_relation_size(:tbl)"),
                {"tbl": tbl},
            ).scalar()
            table_sizes[label] = round(int(row or 0) / 1024 / 1024, 2)  # MB
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询表大小失败: %s", exc)

    total_mb = round(sum(table_sizes.values()), 2)

    # ===== 7天趋势：每天的日志数量（按类型） =====
    by_day = []
    try:
        today = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(6, -1, -1):
            day_start = today - timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            d_str = day_start.strftime("%Y-%m-%d")
            by_day.append({
                "date": d_str,
                "audit": db.query(AuditLog).filter(AuditLog.created_at >= day_start, AuditLog.created_at < day_end).count(),
                "executions": db.query(Execution).filter(Execution.created_at >= day_start, Execution.created_at < day_end).count(),
                "execution_logs": db.query(ExecutionLog).filter(ExecutionLog.timestamp >= day_start, ExecutionLog.timestamp < day_end).count(),
                "model_calls": db.query(ModelCallLog).filter(ModelCallLog.created_at >= day_start, ModelCallLog.created_at < day_end).count(),
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询7天趋势失败: %s", exc)

    # ===== 模型调用成功率与平均耗时 =====
    model_stats = {"total": 0, "success": 0, "failed": 0, "success_rate": 0, "avg_latency_ms": 0}
    try:
        mc_success = db.query(ModelCallLog).filter(ModelCallLog.status == "success").count()
        mc_failed = db.query(ModelCallLog).filter(ModelCallLog.status == "failed").count()
        mc_avg = db.query(func.avg(ModelCallLog.latency_ms)).filter(ModelCallLog.status == "success").scalar()
        model_stats = {
            "total": model_call_count,
            "success": mc_success,
            "failed": mc_failed,
            "success_rate": round(mc_success / model_call_count * 100, 1) if model_call_count > 0 else 0,
            "avg_latency_ms": int(mc_avg) if mc_avg else 0,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询模型调用统计失败: %s", exc)

    # ===== 错误类型 TOP5（模型调用失败日志按 error_category 聚合） =====
    top_errors = []
    try:
        failed_logs = db.query(ModelCallLog.error_message).filter(
            ModelCallLog.status == "failed",
            ModelCallLog.error_message.isnot(None),
        ).limit(2000).all()
        error_cats: dict[str, int] = {}
        for (msg,) in failed_logs:
            cat = _classify_error(msg)
            error_cats[cat] = error_cats.get(cat, 0) + 1
        # 排序取 TOP5
        sorted_cats = sorted(error_cats.items(), key=lambda x: x[1], reverse=True)[:5]
        cat_labels = {
            "dns_resolve": "DNS解析失败",
            "timeout": "请求超时",
            "quota_exceeded": "配额/限流",
            "auth_failed": "鉴权失败",
            "model_unavailable": "模型不可用",
            "server_error": "服务端错误",
            "network_error": "网络异常",
            "other": "其他错误",
            "unknown": "未知错误",
        }
        top_errors = [
            {"category": cat, "label": cat_labels.get(cat, cat), "count": cnt}
            for cat, cnt in sorted_cats
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询错误聚合失败: %s", exc)

    # ===== 按供应商分组：调用次数与失败率 =====
    by_provider = []
    try:
        provider_stats = db.query(
            ModelCallLog.provider,
            func.count(ModelCallLog.id),
            func.sum(case([(ModelCallLog.status == "failed", 1)], else_=0)),
        ).group_by(ModelCallLog.provider).all()
        for prov, total_p, failed_p in provider_stats:
            if not prov:
                continue
            by_provider.append({
                "provider": prov,
                "total": int(total_p or 0),
                "failed": int(failed_p or 0),
                "success_rate": round((1 - (failed_p or 0) / total_p) * 100, 1) if total_p > 0 else 100,
            })
        by_provider.sort(key=lambda x: x["total"], reverse=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询供应商统计失败: %s", exc)

    # ===== 耗时分布 =====
    latency_dist = {"fast": 0, "normal": 0, "slow": 0}
    try:
        latency_dist["fast"] = db.query(ModelCallLog).filter(
            ModelCallLog.status == "success", ModelCallLog.latency_ms < 500,
        ).count()
        latency_dist["normal"] = db.query(ModelCallLog).filter(
            ModelCallLog.status == "success",
            ModelCallLog.latency_ms >= 500, ModelCallLog.latency_ms < 2000,
        ).count()
        latency_dist["slow"] = db.query(ModelCallLog).filter(
            ModelCallLog.status == "success", ModelCallLog.latency_ms >= 2000,
        ).count()
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询耗时分布失败: %s", exc)

    # ===== 分类保留策略 =====
    retention_config = {
        "retention_days": int(_get_config(db, "log.retention_days", "30")),
        "max_storage_mb": int(_get_config(db, "log.max_storage_mb", "500")),
        "audit_retention_days": int(_get_config(db, "log.audit_retention_days", "90")),
        "executions_retention_days": int(_get_config(db, "log.executions_retention_days", "30")),
        "execution_logs_retention_days": int(_get_config(db, "log.execution_logs_retention_days", "30")),
        "model_calls_retention_days": int(_get_config(db, "log.model_calls_retention_days", "7")),
    }

    return {
        "counts": {
            "audit": audit_count,
            "executions": exec_count,
            "execution_logs": exec_log_count,
            "model_calls": model_call_count,
            "total": audit_count + exec_count + exec_log_count + model_call_count,
        },
        "storage_mb": table_sizes,
        "total_storage_mb": total_mb,
        "by_day": by_day,
        "model_call_stats": model_stats,
        "top_errors": top_errors,
        "by_provider": by_provider,
        "latency_dist": latency_dist,
        "retention": retention_config,
    }


# 获取保留策略配置
@router.get("/retention")
def get_retention_config(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """获取日志保留策略配置（全局 + 分类）。"""
    return {
        "retention_days": int(_get_config(db, "log.retention_days", "30")),
        "max_storage_mb": int(_get_config(db, "log.max_storage_mb", "500")),
        "audit_retention_days": int(_get_config(db, "log.audit_retention_days", "90")),
        "executions_retention_days": int(_get_config(db, "log.executions_retention_days", "30")),
        "execution_logs_retention_days": int(_get_config(db, "log.execution_logs_retention_days", "30")),
        "model_calls_retention_days": int(_get_config(db, "log.model_calls_retention_days", "7")),
    }


# 设置保留策略配置（支持分类保留）
@router.put("/retention")
def update_retention_config(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> dict:
    """设置日志保留策略配置。

    请求体示例：
    {
      "retention_days": 30,
      "max_storage_mb": 500,
      "audit_retention_days": 90,
      "executions_retention_days": 30,
      "execution_logs_retention_days": 30,
      "model_calls_retention_days": 7
    }
    所有字段可选，仅更新传入的字段。
    """
    # 字段映射：请求字段 → 配置 key + 范围校验
    field_map = {
        "retention_days": ("log.retention_days", 7, 365),
        "max_storage_mb": ("log.max_storage_mb", 50, 10240),
        "audit_retention_days": ("log.audit_retention_days", 7, 365),
        "executions_retention_days": ("log.executions_retention_days", 7, 365),
        "execution_logs_retention_days": ("log.execution_logs_retention_days", 7, 365),
        "model_calls_retention_days": ("log.model_calls_retention_days", 7, 365),
    }
    updated = {}
    for field, (key, mn, mx) in field_map.items():
        if field not in body:
            continue
        val = body[field]
        try:
            val = int(val)
        except (ValueError, TypeError):
            continue
        if val < mn or val > mx:
            continue
        cfg = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if cfg:
            cfg.value = str(val)
        else:
            db.add(SystemConfig(key=key, value=str(val)))
        updated[field] = val
    db.commit()
    logger.info("日志保留策略已更新: %s", updated)
    # 返回最新完整配置
    return get_retention_config(db=db, _=_)


# 手动清理过期日志（支持分类保留天数）
@router.post("/cleanup")
def cleanup_expired_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system_config", "edit")),
) -> dict:
    """手动清理过期日志。

    按各类型独立的保留天数清理：
    - 操作审计日志：audit_retention_days
    - 执行记录：executions_retention_days
    - 执行日志：execution_logs_retention_days
    - 模型调用日志：model_calls_retention_days
    返回各表删除条数。
    """
    now = beijing_now()
    deleted = {}

    # 操作审计日志
    audit_days = int(_get_config(db, "log.audit_retention_days", "90"))
    audit_cutoff = now - timedelta(days=audit_days)
    n = db.query(AuditLog).filter(AuditLog.created_at < audit_cutoff).delete(synchronize_session=False)
    deleted["audit"] = n

    # 执行记录
    exec_days = int(_get_config(db, "log.executions_retention_days", "30"))
    exec_cutoff = now - timedelta(days=exec_days)
    n = db.query(Execution).filter(Execution.created_at < exec_cutoff).delete(synchronize_session=False)
    deleted["executions"] = n

    # 执行日志（节点级）
    el_days = int(_get_config(db, "log.execution_logs_retention_days", "30"))
    el_cutoff = now - timedelta(days=el_days)
    n = db.query(ExecutionLog).filter(ExecutionLog.timestamp < el_cutoff).delete(synchronize_session=False)
    deleted["execution_logs"] = n

    # 模型调用日志
    mc_days = int(_get_config(db, "log.model_calls_retention_days", "7"))
    mc_cutoff = now - timedelta(days=mc_days)
    n = db.query(ModelCallLog).filter(ModelCallLog.created_at < mc_cutoff).delete(synchronize_session=False)
    deleted["model_calls"] = n

    db.commit()
    total = sum(deleted.values())
    logger.info(
        "日志清理完成: audit(%dd)=%d, executions(%dd)=%d, execution_logs(%dd)=%d, model_calls(%dd)=%d, total=%d",
        audit_days, deleted["audit"], exec_days, deleted["executions"],
        el_days, deleted["execution_logs"], mc_days, deleted["model_calls"], total,
    )
    return {
        "deleted": deleted,
        "total": total,
        "retention": {
            "audit_retention_days": audit_days,
            "executions_retention_days": exec_days,
            "execution_logs_retention_days": el_days,
            "model_calls_retention_days": mc_days,
        },
    }
