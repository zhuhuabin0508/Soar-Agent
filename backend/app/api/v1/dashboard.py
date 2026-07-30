"""大屏统计路由。

聚合最近 7 天的执行数据，计算 KPI 指标、趋势、告警分类与高危 IP。
所有统计在 Python 侧完成（数据量有限，避免复杂 JSON SQL 查询）。
"""
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Execution, ExecutionTrace

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    """获取大屏统计数据（最近 7 天）。

    统计内容：
    - KPI：今日告警数、自动封禁成功率、MTTR、待审批数。
    - trend_7d：每日自动处置数 vs 人工审批数。
    - alert_categories：按 alert_type 分组计数。
    - top_malicious_ips：被封禁 IP Top 10 及威胁标签。

    Args:
        db: 数据库会话。

    Returns:
        DashboardStats 结构的字典。
    """
    logger.info("计算大屏统计")

    today = date.today()
    seven_days_ago = today - timedelta(days=6)
    # 7 天日期列表（含今日），格式 YYYY-MM-DD
    date_list = [
        (seven_days_ago + timedelta(days=i)).isoformat() for i in range(7)
    ]
    date_set = set(date_list)

    # 拉取最近 7 天的执行记录（含全部状态）
    since_datetime = datetime.combine(seven_days_ago, datetime.min.time())
    executions = (
        db.query(Execution)
        .filter(Execution.created_at >= since_datetime)
        .all()
    )
    logger.info("最近7天执行记录数: %d", len(executions))

    # 拉取这些执行关联的 block_ip 轨迹，用于成功率与 MTTR 判断
    exec_ids = [e.id for e in executions]
    block_traces: list[ExecutionTrace] = []
    if exec_ids:
        block_traces = (
            db.query(ExecutionTrace)
            .filter(
                ExecutionTrace.execution_id.in_(exec_ids),
                ExecutionTrace.node_type == "block_ip",
            )
            .all()
        )
    # execution_id -> 是否有成功 block_ip 轨迹
    block_success_exec_ids: set[int] = {
        t.execution_id for t in block_traces if t.status == "success"
    }
    block_attempt_exec_ids: set[int] = {t.execution_id for t in block_traces}

    # ---- KPI ----
    today_alerts = sum(
        1 for e in executions if e.created_at and e.created_at.date() == today
    )

    # 自动封禁成功率：有成功 block_ip 轨迹的 execution / 有 block_ip 轨迹的 execution
    if block_attempt_exec_ids:
        auto_block_success_rate = round(
            len(block_success_exec_ids) / len(block_attempt_exec_ids), 4
        )
    else:
        auto_block_success_rate = 0.0

    # MTTR：有成功 block_ip 的 execution 的平均 (finished_at - created_at) 秒数
    mttr_seconds: float = 0.0
    mttr_samples: list[float] = []
    for e in executions:
        if e.id in block_success_exec_ids and e.finished_at and e.created_at:
            delta = (e.finished_at - e.created_at).total_seconds()
            if delta >= 0:
                mttr_samples.append(delta)
    if mttr_samples:
        mttr_seconds = round(sum(mttr_samples) / len(mttr_samples), 2)

    pending_approvals = (
        db.query(Execution)
        .filter(Execution.status == "waiting_for_approval")
        .count()
    )

    # ---- trend_7d ----
    # 每日 auto_count（有成功 block_ip）/ manual_count（decision=need_human_approval 或 status waiting）
    trend: list[dict[str, Any]] = []
    daily_auto: dict[str, int] = {d: 0 for d in date_list}
    daily_manual: dict[str, int] = {d: 0 for d in date_list}

    for e in executions:
        if not e.created_at:
            continue
        day_str = e.created_at.date().isoformat()
        if day_str not in date_set:
            continue
        info = _extract_exec_info(e)
        decision = info.get("decision")
        if e.id in block_success_exec_ids:
            daily_auto[day_str] += 1
        if decision == "need_human_approval" or e.status == "waiting_for_approval":
            daily_manual[day_str] += 1

    for d in date_list:
        trend.append(
            {"date": d, "auto_count": daily_auto[d], "manual_count": daily_manual[d]}
        )

    # ---- alert_categories ----
    category_counter: Counter[str] = Counter()
    for e in executions:
        info = _extract_exec_info(e)
        alert_type = info.get("alert_type")
        if alert_type:
            category_counter[alert_type] += 1
    alert_categories = [
        {"name": name, "value": count}
        for name, count in category_counter.most_common()
    ]

    # ---- top_malicious_ips ----
    ip_counter: Counter[str] = Counter()
    ip_tags: dict[str, list[str]] = {}
    for e in executions:
        info = _extract_exec_info(e)
        blocked_ip = info.get("blocked_ip")
        if blocked_ip:
            ip_counter[blocked_ip] += 1
            tags = info.get("tags") or []
            if tags:
                # 合并标签
                existing = set(ip_tags.get(blocked_ip, []))
                existing.update(tags)
                ip_tags[blocked_ip] = list(existing)
    top_malicious_ips = [
        {"ip": ip, "count": count, "tags": ip_tags.get(ip, [])}
        for ip, count in ip_counter.most_common(10)
    ]

    stats = {
        "kpi": {
            "today_alerts": today_alerts,
            "auto_block_success_rate": auto_block_success_rate,
            "mttr_seconds": mttr_seconds,
            "pending_approvals": pending_approvals,
        },
        "trend_7d": trend,
        "alert_categories": alert_categories,
        "top_malicious_ips": top_malicious_ips,
    }
    logger.info("大屏统计计算完成: %s", stats)
    return stats


def _extract_exec_info(execution: Execution) -> dict[str, Any]:
    """从 Execution.result 中提取决策、告警类型、封禁 IP、威胁标签等信息。

    result 结构因执行阶段而异：
    - waiting_for_approval: ``{"alert_data":..., "agent_decision":...}``
    - success: ``{"context": {"agent_decision":..., "block_result":..., "payload":...}}``
    - failed: ``{"error":..., "context":...}``

    Args:
        execution: 执行记录 ORM 对象。

    Returns:
        含 decision / alert_type / src_ip / blocked_ip / tags 的字典。
    """
    result = execution.result or {}
    info: dict[str, Any] = {}

    # agent_decision 可能位于 result 顶层或 result.context 内
    agent_decision = result.get("agent_decision")
    context = result.get("context") or {}
    if agent_decision is None:
        agent_decision = context.get("agent_decision") or {}
    info["decision"] = agent_decision.get("decision")

    # alert_data 可能位于 result 顶层或 context.payload
    alert_data = result.get("alert_data")
    if alert_data is None:
        alert_data = context.get("payload") or {}
    info["alert_type"] = alert_data.get("alert_type")
    info["src_ip"] = alert_data.get("src_ip")

    # 封禁 IP：优先 block_result.ip，其次 agent_decision.target_ip
    block_result = context.get("block_result") or {}
    info["blocked_ip"] = block_result.get("ip") or agent_decision.get("target_ip")

    # 威胁标签：尝试从 agent_decision / context 中提取
    tags = agent_decision.get("tags") or context.get("tags") or []
    if isinstance(tags, list):
        info["tags"] = tags
    else:
        info["tags"] = []

    return info
