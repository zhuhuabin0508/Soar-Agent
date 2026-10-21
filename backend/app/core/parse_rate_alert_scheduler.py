"""解析模板成功率告警调度器。

后台守护线程，每隔 ``CHECK_INTERVAL`` 秒检查各启用解析模板的成功率：
过去 ``WINDOW_HOURS`` 小时内所有有解析量的小时桶成功率均低于阈值
（系统配置 ``parse.success_rate_threshold``，默认 80%），且最早有量桶
不晚于窗口起点（即低成功率已持续满 24 小时）时：

- 写入一条 AlertEvent（``rule_id=parse_rate_low``，可在告警列表按模板筛到）；
- 通过 ``dispatch_notification(event_type="parse_alert")`` 派发通知中心提醒。

去重策略（无状态、重启安全）：同一模板 24 小时内已存在 parse_rate_low
告警则跳过；成功率恢复（出现达标小时桶）后再次跌破将重新计时。

设计要点（与 system_alert_scheduler 一致）：
- 所有异常吞掉，调度器本身永不退出；
- 阈值每次检查时从系统配置读取，修改后下个周期生效。
"""
import logging
import threading
import time as _time
from datetime import timedelta

from app.core.timezone import beijing_now
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# 检查间隔（秒）
CHECK_INTERVAL = 600
# 持续时长窗口（小时）：低成功率持续满该时长才告警
WINDOW_HOURS = 24
# 默认成功率告警阈值（百分比），可由系统配置 parse.success_rate_threshold 覆盖
DEFAULT_THRESHOLD = 80.0
# 生成告警的 rule_id 标识（AlertEvent.rule_id，告警列表按模板筛选可见）
ALERT_RULE_ID = "parse_rate_low"

_scheduler_started = False
_scheduler_lock = threading.Lock()


def _get_threshold(db) -> float:
    """读取系统配置 ``parse.success_rate_threshold``（默认 80，收敛到 1-100）。"""
    from app.models.system_config import SystemConfig

    cfg = (
        db.query(SystemConfig)
        .filter(SystemConfig.key == "parse.success_rate_threshold")
        .first()
    )
    try:
        val = float(cfg.value) if cfg and cfg.value not in (None, "") else DEFAULT_THRESHOLD
    except (ValueError, TypeError):
        val = DEFAULT_THRESHOLD
    return min(max(val, 1.0), 100.0)


def evaluate_low_rate_window(metric_rows, threshold, window_start_hour):
    """判定窗口内小时指标是否构成「持续低成功率」。

    Args:
        metric_rows: [(stat_hour, total, success+partial)]，已限制在窗口内；
            stat_hour 为 ``%Y-%m-%dT%H`` 北京时间字符串（字典序即时间序）。
        threshold: 成功率阈值（百分比）。
        window_start_hour: 窗口起点小时串（``now - WINDOW_HOURS``）。

    Returns:
        满足「所有有量桶成功率 < 阈值 且 最早有量桶不晚于窗口起点（持续满窗口）」
        时返回统计 dict（first_hour/total/ok/fail/rate），否则 None。
        无量桶不计入（模板日志稀疏不打断持续判定）。
    """
    buckets = sorted(
        ((h, int(t or 0), int(ok or 0)) for h, t, ok in metric_rows if int(t or 0) > 0),
        key=lambda x: x[0],
    )
    if not buckets:
        return None
    # 任一有量小时达标 → 不构成持续低成功率
    if any(b[2] * 100.0 / b[1] >= threshold for b in buckets):
        return None
    # 最早有量桶晚于窗口起点 → 低成功率尚未持续满窗口
    if buckets[0][0] > window_start_hour:
        return None
    total = sum(b[1] for b in buckets)
    ok = sum(b[2] for b in buckets)
    return {
        "first_hour": buckets[0][0],
        "total": total,
        "ok": ok,
        "fail": total - ok,
        "rate": ok * 100.0 / total,
    }


def _create_alert(db, strategy, threshold: float, verdict: dict, now) -> None:
    """写一条成功率告警 + 派发通知中心提醒（同事务，由调用方 commit）。"""
    from app.core.notification_dispatch import dispatch_notification

    desc = (
        f"解析模板「{strategy.strategy_name}」过去 {WINDOW_HOURS} 小时解析成功率 "
        f"{verdict['rate']:.1f}%，低于阈值 {threshold:g}%。"
        f"窗口内共解析 {verdict['total']} 条：成功 {verdict['ok']} 条、失败 {verdict['fail']} 条。"
        "请检查失败样本与模板校验规则。"
    )
    alert_fields = dict(
        uuid=f"parse-rate-low-{strategy.id}-{now.strftime('%Y%m%d%H%M%S')}",
        strategy_id=strategy.id,
        rule_id=ALERT_RULE_ID,
        log_type="系统告警",
        device_type="system",
        alert_name=f"解析模板成功率低于阈值：{strategy.strategy_name}",
        description=desc,
        recommendation=(
            "在「解析模板」页查看失败样本，核对校验规则（正则/必填字段）是否误伤合法日志；"
            "修复后重放失败样本验证。"
        ),
        risk_level=2,
        risk_level_name="中危",
        threat_type="解析成功率异常",
        occur_timestamp=now,
        upload_timestamp=now,
        parse_status="success",
    )
    from app.models.alert_event import AlertEvent

    db.add(AlertEvent(**alert_fields))
    dispatch_notification(
        db,
        event_type="parse_alert",
        title="解析模板成功率异常",
        content=desc + f"\n\n时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
        related_type="parse_template",
        related_id=strategy.id,
        created_by="system",
    )


def _check_and_alert() -> None:
    """检查全部启用模板的成功率，满足条件时生成告警并通知。"""
    from app.models.alert_event import AlertEvent
    from app.models.ingestion_metric import IngestionMetric
    from app.models.parse_strategy import ParseStrategy

    db = SessionLocal()
    try:
        threshold = _get_threshold(db)
        now = beijing_now()
        window_start_hour = (now - timedelta(hours=WINDOW_HOURS)).strftime("%Y-%m-%dT%H")
        strategies = db.query(ParseStrategy).filter(ParseStrategy.status == "enabled").all()
        for st in strategies:
            try:
                rows = (
                    db.query(
                        IngestionMetric.stat_hour,
                        IngestionMetric.total_count,
                        IngestionMetric.success_count,
                        IngestionMetric.partial_count,
                    )
                    .filter(
                        IngestionMetric.strategy_id == st.id,
                        IngestionMetric.stat_hour >= window_start_hour,
                    )
                    .all()
                )
                metric_rows = [(h, t, (s or 0) + (p or 0)) for h, t, s, p in rows]
                verdict = evaluate_low_rate_window(metric_rows, threshold, window_start_hour)
                if verdict is None:
                    continue
                # 去重：窗口时长内已告警过则跳过（恢复后再跌破重新计时）
                since = now - timedelta(hours=WINDOW_HOURS)
                exists = (
                    db.query(AlertEvent.id)
                    .filter(
                        AlertEvent.strategy_id == st.id,
                        AlertEvent.rule_id == ALERT_RULE_ID,
                        AlertEvent.occur_timestamp >= since,
                    )
                    .first()
                )
                if exists:
                    continue
                _create_alert(db, st, threshold, verdict, now)
                logger.warning(
                    "解析模板成功率告警: strategy=%s rate=%.1f%% threshold=%g%%",
                    st.strategy_name, verdict["rate"], threshold,
                )
            except Exception:  # noqa: BLE001
                logger.exception("解析模板成功率检查失败: id=%s", st.id)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("解析模板成功率告警检查失败: %s", exc)
    finally:
        db.close()


def _run_scheduler() -> None:
    """调度器主循环。"""
    logger.info("解析模板成功率告警调度器已启动，检查间隔 %ds", CHECK_INTERVAL)
    while True:
        try:
            _check_and_alert()
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析模板成功率告警调度器异常: %s", exc)
        _time.sleep(CHECK_INTERVAL)


def start_parse_rate_alert_scheduler() -> None:
    """启动解析模板成功率告警调度器（仅启动一次）。"""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
        t = threading.Thread(
            target=_run_scheduler, daemon=True, name="parse-rate-alert-scheduler"
        )
        t.start()
        logger.info("解析模板成功率告警调度器线程已创建")
