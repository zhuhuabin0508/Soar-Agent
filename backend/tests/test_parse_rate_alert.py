"""解析模板成功率告警调度器单测。

覆盖：
- evaluate_low_rate_window 纯函数：空窗口 / 未持续满窗口 / 存在达标小时 /
  全部低成功率且持续满窗口 / 零量桶跳过；
- _check_and_alert 集成：持续 24h 低成功率生成 AlertEvent（rule_id=parse_rate_low）
  + 通知派发调用；24h 内去重；出现达标小时后不再告警；阈值走系统配置。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_parse_rate_alert.py -v
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.parse_rate_alert_scheduler as sched
from app.core.parse_rate_alert_scheduler import (
    ALERT_RULE_ID,
    evaluate_low_rate_window,
)
from app.core.timezone import beijing_now
from app.database import Base
from app.models.alert_event import AlertEvent
from app.models.ingestion_metric import IngestionMetric
from app.models.parse_strategy import ParseStrategy
from app.models.system_config import SystemConfig

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

Base.metadata.create_all(_engine, tables=[
    AlertEvent.__table__,
    IngestionMetric.__table__,
    ParseStrategy.__table__,
    SystemConfig.__table__,
])


def _hour_str(dt):
    return dt.strftime("%Y-%m-%dT%H")


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """SessionLocal 指向测试库；通知派发替换为计数桩。"""
    monkeypatch.setattr(sched, "SessionLocal", _TestSessionLocal)
    dispatched = []
    import app.core.notification_dispatch as nd_mod

    def _fake_dispatch(db, **kwargs):
        dispatched.append(kwargs)
        return []

    monkeypatch.setattr(nd_mod, "dispatch_notification", _fake_dispatch)
    yield {"dispatched": dispatched}
    with _engine.begin() as conn:
        for name in ("alert_events", "ingestion_metrics", "parse_strategies", "system_configs"):
            conn.execute(Base.metadata.tables[name].delete())


def _seed_strategy(name="青藤模板", status="enabled"):
    db = _TestSessionLocal()
    try:
        st = ParseStrategy(strategy_name=name, device_type="qingteng_wanxiang", config="{}", status=status)
        db.add(st)
        db.commit()
        return st.id
    finally:
        db.close()


def _seed_metrics(sid, rows):
    """铺小时指标桶。rows: [(stat_hour, total_count, success_count), ...]。"""
    db = _TestSessionLocal()
    try:
        for h, t, o in rows:
            db.add(IngestionMetric(
                stat_hour=h, strategy_id=sid, strategy_name="青藤模板",
                total_count=t, success_count=o, partial_count=0, fail_count=t - o,
            ))
        db.commit()
    finally:
        db.close()


# ============ evaluate_low_rate_window：纯函数判定 ============
class TestEvaluateLowRateWindow:
    def test_empty_rows_returns_none(self):
        assert evaluate_low_rate_window([], 80, "2026-10-08T10") is None

    def test_all_zero_total_returns_none(self):
        rows = [("2026-10-08T10", 0, 0), ("2026-10-09T10", 0, 0)]
        assert evaluate_low_rate_window(rows, 80, "2026-10-08T10") is None

    def test_not_persisted_full_window_returns_none(self):
        # 全部低成功率但最早有量桶晚于窗口起点（未持续满 24h）
        rows = [("2026-10-09T09", 10, 3), ("2026-10-09T10", 10, 2)]
        assert evaluate_low_rate_window(rows, 80, "2026-10-08T10") is None

    def test_any_good_bucket_returns_none(self):
        # 存在一个达标小时桶 → 不构成持续低成功率
        rows = [
            ("2026-10-08T10", 10, 3),
            ("2026-10-09T02", 10, 9),   # 90% ≥ 80%
            ("2026-10-09T10", 10, 3),
        ]
        assert evaluate_low_rate_window(rows, 80, "2026-10-08T10") is None

    def test_all_low_and_persisted_returns_verdict(self):
        rows = [
            ("2026-10-08T10", 10, 3),
            ("2026-10-09T05", 0, 0),    # 零量桶跳过
            ("2026-10-09T10", 10, 2),
        ]
        v = evaluate_low_rate_window(rows, 80, "2026-10-08T10")
        assert v is not None
        assert v["first_hour"] == "2026-10-08T10"
        assert v["total"] == 20
        assert v["ok"] == 5
        assert v["fail"] == 15
        assert v["rate"] == pytest.approx(25.0)

    def test_exactly_threshold_is_not_low(self):
        # 成功率恰等于阈值 → 不低于阈值，不告警
        rows = [("2026-10-08T10", 10, 8), ("2026-10-09T10", 10, 8)]
        assert evaluate_low_rate_window(rows, 80, "2026-10-08T10") is None


# ============ _check_and_alert：集成（告警生成 / 去重 / 恢复 / 阈值配置） ============
class TestCheckAndAlert:
    def _persist_low_metrics(self, sid, hours=25):
        """从 now-hours 到 now-1h 逐小时铺低成功率桶（每桶 10 条成功 3 条）。"""
        now = beijing_now()
        rows = []
        for i in range(hours, 0, -1):
            rows.append((_hour_str(now - timedelta(hours=i)), 10, 3))
        _seed_metrics(sid, rows)

    def test_persisted_low_rate_creates_alert_and_dispatches(self, _setup_env):
        sid = _seed_strategy()
        self._persist_low_metrics(sid)
        sched._check_and_alert()
        db = _TestSessionLocal()
        try:
            alerts = db.query(AlertEvent).filter(
                AlertEvent.strategy_id == sid, AlertEvent.rule_id == ALERT_RULE_ID,
            ).all()
            assert len(alerts) == 1
            a = alerts[0]
            assert "低于阈值" in a.alert_name
            assert a.risk_level == 2
            assert a.parse_status == "success"
        finally:
            db.close()
        # 通知中心已派发一次
        assert len(_setup_env["dispatched"]) == 1
        assert _setup_env["dispatched"][0]["event_type"] == "parse_alert"
        assert _setup_env["dispatched"][0]["related_id"] == sid

    def test_no_duplicate_within_window(self, _setup_env):
        sid = _seed_strategy()
        self._persist_low_metrics(sid)
        sched._check_and_alert()
        sched._check_and_alert()  # 二次检查：窗口内去重
        db = _TestSessionLocal()
        try:
            assert db.query(AlertEvent).filter(
                AlertEvent.strategy_id == sid, AlertEvent.rule_id == ALERT_RULE_ID,
            ).count() == 1
        finally:
            db.close()
        assert len(_setup_env["dispatched"]) == 1

    def test_recent_failure_only_not_persisted_no_alert(self, _setup_env):
        # 仅最近 1 小时有低成功率（未持续满 24h）→ 不告警
        sid = _seed_strategy()
        now = beijing_now()
        _seed_metrics(sid, [(_hour_str(now), 10, 3)])
        sched._check_and_alert()
        db = _TestSessionLocal()
        try:
            assert db.query(AlertEvent).filter(AlertEvent.strategy_id == sid).count() == 0
        finally:
            db.close()
        assert _setup_env["dispatched"] == []

    def test_good_bucket_blocks_alert(self, _setup_env):
        # 24h 前 + 当前小时均低，但中间有一小时达标 → 不告警
        sid = _seed_strategy()
        now = beijing_now()
        _seed_metrics(sid, [
            (_hour_str(now - timedelta(hours=24)), 10, 3),
            (_hour_str(now - timedelta(hours=12)), 10, 9),  # 90% 达标
            (_hour_str(now), 10, 3),
        ])
        sched._check_and_alert()
        db = _TestSessionLocal()
        try:
            assert db.query(AlertEvent).filter(AlertEvent.strategy_id == sid).count() == 0
        finally:
            db.close()

    def test_threshold_from_system_config(self, _setup_env):
        # 阈值配置为 20%：30% 成功率不再告警
        sid = _seed_strategy()
        db = _TestSessionLocal()
        try:
            db.add(SystemConfig(key="parse.success_rate_threshold", value="20"))
            db.commit()
        finally:
            db.close()
        self._persist_low_metrics(sid)
        sched._check_and_alert()
        db = _TestSessionLocal()
        try:
            assert db.query(AlertEvent).filter(AlertEvent.strategy_id == sid).count() == 0
        finally:
            db.close()

    def test_disabled_strategy_skipped(self, _setup_env):
        sid = _seed_strategy(status="disabled")
        self._persist_low_metrics(sid)
        sched._check_and_alert()
        db = _TestSessionLocal()
        try:
            assert db.query(AlertEvent).filter(AlertEvent.strategy_id == sid).count() == 0
        finally:
            db.close()
