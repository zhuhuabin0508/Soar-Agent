"""执行记录查询路由。

提供执行列表（分页）与执行详情（含节点轨迹）查询，
以及监测统计 API（成功率 / 平均耗时 / 节点瓶颈 / 错误趋势）。
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, extract, case
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Execution, ExecutionLog, ExecutionTrace
from app.schemas.execution import ExecutionOut
from app.schemas.execution_trace import ExecutionTraceOut

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/executions",
    tags=["executions"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[ExecutionOut])
def list_executions(
    limit: int = Query(50, ge=1, le=500, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    workflow_id: Optional[int] = Query(None, description="按工作流 ID 过滤"),
    status: Optional[str] = Query(None, description="按状态过滤(success/failed/running)"),
    db: Session = Depends(get_db),
) -> list[Execution]:
    """查询执行记录列表（分页，支持按工作流/状态过滤）。

    Args:
        limit: 每页数量，默认 50，范围 1-500。
        offset: 偏移量，默认 0。
        workflow_id: 可选，按工作流 ID 过滤。
        status: 可选，按执行状态过滤。
        db: 数据库会话。

    Returns:
        执行记录列表，按创建时间倒序。
    """
    logger.info("查询执行列表: limit=%s, offset=%s, workflow_id=%s, status=%s", limit, offset, workflow_id, status)
    q = db.query(Execution)
    if workflow_id is not None:
        q = q.filter(Execution.workflow_id == workflow_id)
    if status:
        q = q.filter(Execution.status == status)
    executions = (
        q.order_by(Execution.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    logger.info("查询到 %d 条执行记录", len(executions))
    return executions


@router.get("/{execution_id}")
def get_execution(
    execution_id: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """查询单个执行详情，含节点轨迹列表。

    Args:
        execution_id: 执行记录 ID。
        db: 数据库会话。

    Returns:
        ``{"execution": ExecutionOut, "traces": [ExecutionTraceOut, ...]}``。
    """
    logger.info("查询执行详情: id=%s", execution_id)
    execution = (
        db.query(Execution).filter(Execution.id == execution_id).first()
    )
    if execution is None:
        logger.warning("执行记录不存在: id=%s", execution_id)
        raise HTTPException(status_code=404, detail="Execution not found")

    traces = (
        db.query(ExecutionTrace)
        .filter(ExecutionTrace.execution_id == execution_id)
        .order_by(ExecutionTrace.started_at.asc())
        .all()
    )
    logs = (
        db.query(ExecutionLog)
        .filter(ExecutionLog.execution_id == execution_id)
        .order_by(ExecutionLog.timestamp.asc())
        .all()
    )
    logger.info(
        "执行详情: id=%s, traces=%d, logs=%d", execution_id, len(traces), len(logs)
    )

    execution_out = ExecutionOut.model_validate(execution)
    traces_out = [ExecutionTraceOut.model_validate(t) for t in traces]
    logs_out = [
        {
            "node_id": log.node_id,
            "level": log.level,
            "message": log.message,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]
    return {"execution": execution_out, "traces": traces_out, "logs": logs_out}


@router.get("/stats/overview")
def get_stats_overview(
    days: int = Query(7, ge=1, le=90, description="统计最近 N 天的数据"),
    workflow_id: Optional[int] = Query(None, description="按工作流 ID 过滤；不传则统计全部"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """监测统计概览：成功率 / 平均耗时 / 按天趋势 / 触发类型分布 / 节点瓶颈。

    支持按 ``workflow_id`` 过滤（只统计指定工作流的执行），便于在执行监测看板
    上聚焦单个工作流的运行情况。不传 ``workflow_id`` 时统计全部执行（含智能体测试）。

    Args:
        days: 统计最近 N 天的数据，默认 7 天，范围 1-90。
        workflow_id: 可选，按工作流 ID 过滤。
        db: 数据库会话。

    Returns:
        ``{total, success, failed, success_rate, avg_duration_seconds,
           by_day: [{date, total, success, failed}],
           by_trigger: {webhook: N, test_run: M},
           node_bottleneck: [{node_type, avg_duration_seconds, count, failed_count}]}``
    """
    since = datetime.now() - timedelta(days=days)
    logger.info("查询监测统计: days=%s, since=%s, workflow_id=%s", days, since, workflow_id)

    # ---- 总体统计 ----
    base_q = db.query(Execution).filter(Execution.created_at >= since)
    if workflow_id is not None:
        base_q = base_q.filter(Execution.workflow_id == workflow_id)
    total = base_q.count()
    success = base_q.filter(Execution.status == "success").count()
    failed = base_q.filter(Execution.status == "failed").count()
    success_rate = round(success / total, 4) if total > 0 else 0.0

    # 平均耗时（秒）：EXTRACT(EPOCH FROM (finished_at - created_at))
    avg_q = db.query(
        func.avg(
            extract("epoch", Execution.finished_at - Execution.created_at)
        )
    ).filter(
        Execution.created_at >= since,
        Execution.finished_at.isnot(None),
    )
    if workflow_id is not None:
        avg_q = avg_q.filter(Execution.workflow_id == workflow_id)
    avg_duration_row = avg_q.scalar()
    avg_duration_seconds = round(float(avg_duration_row or 0), 2)

    # ---- 按天趋势 ----
    day_q = (
        db.query(
            func.date(Execution.created_at).label("date"),
            func.count(Execution.id).label("total"),
            func.sum(case((Execution.status == "success", 1), else_=0)).label("success"),
            func.sum(case((Execution.status == "failed", 1), else_=0)).label("failed"),
        )
        .filter(Execution.created_at >= since)
    )
    if workflow_id is not None:
        day_q = day_q.filter(Execution.workflow_id == workflow_id)
    day_rows = (
        day_q.group_by(func.date(Execution.created_at))
        .order_by(func.date(Execution.created_at).asc())
        .all()
    )
    by_day = [
        {
            "date": str(r.date),
            "total": int(r.total or 0),
            "success": int(r.success or 0),
            "failed": int(r.failed or 0),
        }
        for r in day_rows
    ]

    # ---- 按触发类型分布 ----
    trigger_q = (
        db.query(
            Execution.trigger_type,
            func.count(Execution.id),
        )
        .filter(Execution.created_at >= since)
    )
    if workflow_id is not None:
        trigger_q = trigger_q.filter(Execution.workflow_id == workflow_id)
    trigger_rows = trigger_q.group_by(Execution.trigger_type).all()
    by_trigger = {row[0] or "unknown": int(row[1]) for row in trigger_rows}

    # ---- 节点瓶颈：按 node_type 统计平均耗时与失败数 ----
    # 关联 Execution 过滤时间范围，再按 ExecutionTrace.node_type 聚合
    bottleneck_q = (
        db.query(
            ExecutionTrace.node_type,
            func.count(ExecutionTrace.id).label("count"),
            func.avg(
                extract("epoch", ExecutionTrace.finished_at - ExecutionTrace.started_at)
            ).label("avg_duration"),
            func.sum(
                case((ExecutionTrace.status == "failed", 1), else_=0)
            ).label("failed_count"),
        )
        .join(Execution, ExecutionTrace.execution_id == Execution.id)
        .filter(
            Execution.created_at >= since,
            ExecutionTrace.finished_at.isnot(None),
        )
    )
    if workflow_id is not None:
        bottleneck_q = bottleneck_q.filter(Execution.workflow_id == workflow_id)
    bottleneck_rows = (
        bottleneck_q.group_by(ExecutionTrace.node_type)
        .order_by(func.avg(extract("epoch", ExecutionTrace.finished_at - ExecutionTrace.started_at)).desc())
        .limit(20)
        .all()
    )
    node_bottleneck = [
        {
            "node_type": r.node_type,
            "count": int(r.count or 0),
            "avg_duration_seconds": round(float(r.avg_duration or 0), 3),
            "failed_count": int(r.failed_count or 0),
        }
        for r in bottleneck_rows
    ]

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "success_rate": success_rate,
        "avg_duration_seconds": avg_duration_seconds,
        "by_day": by_day,
        "by_trigger": by_trigger,
        "node_bottleneck": node_bottleneck,
    }
