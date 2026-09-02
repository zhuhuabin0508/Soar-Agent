"""大屏统计路由。

聚合最近 7 天的执行数据，计算 KPI 指标、趋势、告警分类与高危 IP。
所有统计在 Python 侧完成（数据量有限，避免复杂 JSON SQL 查询）。
"""
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models import Agent, ChatMessage, Execution, ExecutionTrace, LLMConfig, ModelCallLog

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_permission("dashboard", "view"))],
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


@router.get("/ai-usage")
def get_ai_usage_stats(
    days: int = 7,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """获取智能体与大模型使用情况统计（默认最近 7 天）。

    统计内容：
    - KPI：智能体调用总数、模型调用总数、总 Token 消耗、模型平均耗时、
      模型成功率、活跃智能体数。
    - agent_usage：按智能体聚合调用次数、执行数、对话消息数、模型调用数、Token、最近活跃时间。
    - model_usage：按模型配置聚合调用次数、成功/失败数、成功率、平均耗时、Token 用量。
    - agent_trend：近 N 天每日智能体调用趋势。
    - model_trend：近 N 天每日模型调用次数与 Token 消耗趋势。
    - provider_distribution：按供应商聚合模型调用次数占比。
    - trigger_distribution：按触发来源（agent_test/workflow/manual_test）聚合模型调用次数。

    Args:
        days: 统计最近 N 天的数据，默认 7，范围 1-90。
        db: 数据库会话。

    Returns:
        AI 使用统计字典。
    """
    days = max(1, min(int(days), 90))
    logger.info("计算 AI 使用统计: days=%s", days)

    today = date.today()
    n_days_ago = today - timedelta(days=days - 1)
    date_list = [(n_days_ago + timedelta(days=i)).isoformat() for i in range(days)]
    date_set = set(date_list)
    since_datetime = datetime.combine(n_days_ago, datetime.min.time())

    # ============ 模型调用统计（ModelCallLog） ============
    model_logs = (
        db.query(ModelCallLog)
        .filter(ModelCallLog.created_at >= since_datetime)
        .all()
    )
    logger.info("最近%d天模型调用日志数: %d", days, len(model_logs))

    # ---- 模型 KPI ----
    total_model_calls = len(model_logs)
    model_success = sum(1 for m in model_logs if m.status == "success")
    model_failed = total_model_calls - model_success
    model_success_rate = round(model_success / total_model_calls, 4) if total_model_calls > 0 else 0.0
    latencies = [m.latency_ms for m in model_logs if m.latency_ms is not None]
    avg_model_latency_ms = round(sum(latencies) / len(latencies)) if latencies else 0
    total_tokens = sum(m.total_tokens or 0 for m in model_logs)
    total_input_tokens = sum(m.input_tokens or 0 for m in model_logs)
    total_output_tokens = sum(m.output_tokens or 0 for m in model_logs)

    # ---- 按模型配置聚合 ----
    # 预加载 LLMConfig 名称映射
    llm_configs = {c.id: c for c in db.query(LLMConfig).all()}
    model_agg: dict[int, dict] = defaultdict(lambda: {
        "call_count": 0, "success_count": 0, "failed_count": 0,
        "latency_sum": 0, "latency_count": 0,
        "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
        "model_name": "", "provider": "",
    })
    for m in model_logs:
        key = m.model_config_id
        agg = model_agg[key]
        agg["call_count"] += 1
        if m.status == "success":
            agg["success_count"] += 1
        else:
            agg["failed_count"] += 1
        if m.latency_ms is not None:
            agg["latency_sum"] += m.latency_ms
            agg["latency_count"] += 1
        agg["input_tokens"] += m.input_tokens or 0
        agg["output_tokens"] += m.output_tokens or 0
        agg["total_tokens"] += m.total_tokens or 0
        # 模型名/供应商优先取日志冗余字段，缺失时取配置
        agg["model_name"] = m.model_name or agg["model_name"]
        agg["provider"] = m.provider or agg["provider"]

    model_usage = []
    for config_id, agg in model_agg.items():
        cfg = llm_configs.get(config_id) if config_id else None
        model_usage.append({
            "model_config_id": config_id,
            "config_name": cfg.name if cfg else "(已删除配置)" if config_id else "(未关联配置)",
            "model_name": agg["model_name"] or (cfg.model_name if cfg else ""),
            "provider": agg["provider"] or (cfg.provider if cfg else ""),
            "call_count": agg["call_count"],
            "success_count": agg["success_count"],
            "failed_count": agg["failed_count"],
            "success_rate": round(agg["success_count"] / agg["call_count"], 4) if agg["call_count"] else 0.0,
            "avg_latency_ms": round(agg["latency_sum"] / agg["latency_count"]) if agg["latency_count"] else 0,
            "input_tokens": agg["input_tokens"],
            "output_tokens": agg["output_tokens"],
            "total_tokens": agg["total_tokens"],
        })
    # 按调用次数倒序
    model_usage.sort(key=lambda x: x["call_count"], reverse=True)

    # ---- 供应商分布 ----
    provider_counter: Counter[str] = Counter()
    for m in model_logs:
        provider = m.provider or "unknown"
        provider_counter[provider] += 1
    provider_distribution = [
        {"name": name, "value": count}
        for name, count in provider_counter.most_common()
    ]

    # ---- 触发来源分布 ----
    trigger_counter: Counter[str] = Counter()
    for m in model_logs:
        trigger_counter[m.trigger_type or "unknown"] += 1
    trigger_distribution = [
        {"name": name, "value": count}
        for name, count in trigger_counter.most_common()
    ]

    # ---- 模型调用趋势（按天） ----
    daily_model_calls: dict[str, int] = {d: 0 for d in date_list}
    daily_model_tokens: dict[str, int] = {d: 0 for d in date_list}
    for m in model_logs:
        if not m.created_at:
            continue
        day_str = m.created_at.date().isoformat()
        if day_str in date_set:
            daily_model_calls[day_str] += 1
            daily_model_tokens[day_str] += m.total_tokens or 0
    model_trend = [
        {"date": d, "count": daily_model_calls[d], "tokens": daily_model_tokens[d]}
        for d in date_list
    ]

    # ============ 智能体统计（Execution + ChatMessage + ModelCallLog） ============
    # 近 N 天执行记录（按 agent_id）
    executions = (
        db.query(Execution)
        .filter(Execution.created_at >= since_datetime)
        .all()
    )
    # 近 N 天对话消息（按 agent_id）
    chat_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.created_at >= since_datetime)
        .all()
    )
    # 智能体 ID 集合（执行 + 对话 + 模型调用中出现）
    agent_ids = set()
    for e in executions:
        if e.agent_id:
            agent_ids.add(e.agent_id)
    for cm in chat_messages:
        agent_ids.add(cm.agent_id)
    for m in model_logs:
        if m.agent_id:
            agent_ids.add(m.agent_id)

    agents_map = {a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()} if agent_ids else {}

    # 按智能体聚合
    exec_by_agent: dict[int, list] = defaultdict(list)
    for e in executions:
        if e.agent_id:
            exec_by_agent[e.agent_id].append(e)
    msg_by_agent: dict[int, list] = defaultdict(list)
    for cm in chat_messages:
        msg_by_agent[cm.agent_id].append(cm)
    model_by_agent: dict[int, list] = defaultdict(list)
    for m in model_logs:
        if m.agent_id:
            model_by_agent[m.agent_id].append(m)

    agent_usage = []
    for aid in agent_ids:
        agent = agents_map.get(aid)
        agent_execs = exec_by_agent.get(aid, [])
        agent_msgs = msg_by_agent.get(aid, [])
        agent_model_logs = model_by_agent.get(aid, [])
        # 最近活跃时间：取执行、消息、模型调用中最新的 created_at
        last_active = None
        candidates = []
        if agent_execs:
            candidates.extend(e.created_at for e in agent_execs if e.created_at)
        if agent_msgs:
            candidates.extend(cm.created_at for cm in agent_msgs if cm.created_at)
        if agent_model_logs:
            candidates.extend(m.created_at for m in agent_model_logs if m.created_at)
        if candidates:
            last_active = max(candidates).isoformat()
        # 对话数：按 session_id 去重
        session_ids = {cm.session_id for cm in agent_msgs}
        agent_usage.append({
            "agent_id": aid,
            "agent_name": agent.name if agent else f"(已删除智能体 #{aid})",
            "engine": agent.engine if agent else "",
            "conversation_count": len(session_ids),
            "message_count": len(agent_msgs),
            "execution_count": len(agent_execs),
            "model_call_count": len(agent_model_logs),
            "total_tokens": sum(m.total_tokens or 0 for m in agent_model_logs),
            "last_active_at": last_active,
        })
    # 按模型调用数倒序，其次按执行数
    agent_usage.sort(key=lambda x: (x["model_call_count"], x["execution_count"]), reverse=True)

    # ---- 智能体 KPI ----
    total_agent_calls = len(executions) + len(chat_messages)
    active_agents = len(agent_ids)

    # ---- 智能体调用趋势（按天，按执行+消息数） ----
    daily_agent_calls: dict[str, int] = {d: 0 for d in date_list}
    for e in executions:
        if e.created_at:
            day_str = e.created_at.date().isoformat()
            if day_str in date_set:
                daily_agent_calls[day_str] += 1
    for cm in chat_messages:
        if cm.created_at:
            day_str = cm.created_at.date().isoformat()
            if day_str in date_set:
                daily_agent_calls[day_str] += 1
    agent_trend = [
        {"date": d, "count": daily_agent_calls[d]}
        for d in date_list
    ]

    stats = {
        "kpi": {
            "total_agent_calls": total_agent_calls,
            "active_agents": active_agents,
            "total_model_calls": total_model_calls,
            "model_success_count": model_success,
            "model_failed_count": model_failed,
            "model_success_rate": model_success_rate,
            "avg_model_latency_ms": avg_model_latency_ms,
            "total_tokens": total_tokens,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
        },
        "agent_usage": agent_usage,
        "model_usage": model_usage,
        "agent_trend": agent_trend,
        "model_trend": model_trend,
        "provider_distribution": provider_distribution,
        "trigger_distribution": trigger_distribution,
    }
    logger.info("AI 使用统计计算完成: agents=%d, models=%d", len(agent_usage), len(model_usage))
    return stats
