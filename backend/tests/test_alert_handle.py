"""告警处置闭环单测。

覆盖：
- 状态机合法性：合法流转成功、非法流转 422
- 单条处置：deal_status/assignee_name 更新、AlertHandleLog 写入
- 批量处置：多条成功+部分跳过
- 处置时间线：按时间降序、字段完整

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_alert_handle.py -v
"""
import os
import sys

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.timezone import beijing_now
from app.database import Base
from app.models.alert_event import AlertEvent
from app.models.alert_handle_log import AlertHandleLog
from app.models.user import User
from app.api.v1.alerts import (
    _TRANSITIONS,
    _DEAL_STATUS_NAMES,
    _do_handle,
    HandleBody,
)

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

Base.metadata.create_all(_engine, tables=[
    AlertEvent.__table__,
    AlertHandleLog.__table__,
    User.__table__,
])


@pytest.fixture(autouse=True)
def _clean_db():
    """每个测试前清理所有表数据（共享同一 in-memory engine）。"""
    session = _TestSessionLocal()
    try:
        for tbl in (AlertHandleLog, AlertEvent, User):
            session.query(tbl).delete()
        session.commit()
    finally:
        session.close()
    yield


def _db():
    """创建测试用 session。"""
    return _TestSessionLocal()


def _seed_user(db, name="analyst1", display_name="分析员A"):
    """种子一个测试用户。"""
    u = User(
        username=name,
        password_hash="x",
        display_name=display_name,
        role="analyst",
    )
    db.add(u)
    db.commit()
    return u


def _seed_alert(db, deal_status=0):
    """种子一条测试告警。"""
    a = AlertEvent(
        uuid=f"test-uuid-{db.query(AlertEvent).count() + 1:03d}",
        alert_name="测试告警",
        risk_level=2,
        risk_level_name="中危",
        deal_status=deal_status,
        deal_status_name=_DEAL_STATUS_NAMES.get(deal_status, ""),
    )
    db.add(a)
    db.commit()
    return a


class TestStateMachine:
    """状态机流转规则校验。"""

    def test_transitions_cover_all_statuses(self):
        """所有已定义状态都有流转规则。"""
        for status in _DEAL_STATUS_NAMES:
            assert status in _TRANSITIONS, f"状态 {status} 缺少流转规则"

    def test_pending_can_go_to_processing(self):
        """待确认 → 处置中 合法。"""
        assert 70 in _TRANSITIONS[0]

    def test_processing_can_go_to_closed(self):
        """处置中 → 已关闭 合法。"""
        assert 20 in _TRANSITIONS[70]

    def test_processing_can_rollback(self):
        """处置中 → 待确认（退回）合法。"""
        assert 0 in _TRANSITIONS[70]

    def test_closed_can_reopen(self):
        """已关闭 → 处置中（重新打开）合法。"""
        assert 70 in _TRANSITIONS[20]

    def test_closed_cannot_go_to_pending(self):
        """已关闭 → 待确认 非法（只能重新打开为处置中）。"""
        assert 0 not in _TRANSITIONS[20]


class TestHandleAlert:
    """单条处置端点逻辑。"""

    def test_legal_transition_updates_alert(self):
        """合法流转：告警状态/指派人/handled_at 正确更新。"""
        db = _db()
        user = _seed_user(db)
        alert = _seed_alert(db, deal_status=0)
        body = HandleBody(to_status=70, assignee_id=user.id, comment="开始处置")

        log = _do_handle(db, alert, body, user.id, user.display_name)

        assert alert.deal_status == 70
        assert alert.deal_status_name == "处置中"
        assert alert.assignee_id == user.id
        assert alert.assignee_name == "分析员A"
        assert alert.handled_at is not None
        assert log.action == "status_change"
        assert log.from_status == 0
        assert log.to_status == 70
        assert log.to_assignee == "分析员A"
        db.close()

    def test_illegal_transition_raises(self):
        """非法流转：已关闭 → 已加白 应 422。"""
        db = _db()
        user = _seed_user(db)
        alert = _seed_alert(db, deal_status=20)  # 已关闭
        body = HandleBody(to_status=30, assignee_id=None, comment="尝试加白")

        with pytest.raises(Exception) as exc_info:
            _do_handle(db, alert, body, user.id, user.display_name)
        # HTTPException 的 detail 属性
        detail = getattr(exc_info.value, "detail", str(exc_info.value))
        assert "不允许的状态流转" in str(detail)
        db.close()

    def test_close_action(self):
        """处置中 → 已关闭：action=close。"""
        db = _db()
        user = _seed_user(db)
        alert = _seed_alert(db, deal_status=70)
        body = HandleBody(to_status=20, assignee_id=None, comment="已处置完成")

        log = _do_handle(db, alert, body, user.id, user.display_name)
        assert log.action == "close"
        db.close()

    def test_reopen_action(self):
        """已关闭 → 处置中：action=reopen。"""
        db = _db()
        user = _seed_user(db)
        alert = _seed_alert(db, deal_status=20)
        body = HandleBody(to_status=70, assignee_id=None, comment="重新打开")

        log = _do_handle(db, alert, body, user.id, user.display_name)
        assert log.action == "reopen"
        db.close()

    def test_assign_only_no_status_change(self):
        """仅指派不改状态：action=assign。"""
        db = _db()
        user = _seed_user(db)
        alert = _seed_alert(db, deal_status=70)
        alert.assignee_name = "旧处理人"
        db.commit()
        body = HandleBody(to_status=70, assignee_id=user.id, comment="指派给新人")

        log = _do_handle(db, alert, body, user.id, user.display_name)
        assert log.action == "assign"
        assert log.from_assignee == "旧处理人"
        assert log.to_assignee == "分析员A"
        db.close()

    def test_comment_only(self):
        """仅备注不改状态不改指派：action=comment。"""
        db = _db()
        user = _seed_user(db)
        alert = _seed_alert(db, deal_status=70)
        body = HandleBody(to_status=70, assignee_id=None, comment="补充说明")

        log = _do_handle(db, alert, body, user.id, user.display_name)
        assert log.action == "comment"
        db.close()

    def test_multiple_logs_form_timeline(self):
        """多次处置操作生成多条日志，按时间降序。"""
        db = _db()
        user = _seed_user(db)
        alert = _seed_alert(db, deal_status=0)

        _do_handle(db, alert, HandleBody(to_status=70, comment="开始"), user.id, user.display_name)
        _do_handle(db, alert, HandleBody(to_status=20, comment="完成"), user.id, user.display_name)
        db.commit()

        logs = (
            db.query(AlertHandleLog)
            .filter(AlertHandleLog.alert_id == alert.id)
            .order_by(AlertHandleLog.created_at.desc())
            .all()
        )
        assert len(logs) == 2
        assert logs[0].to_status == 20  # 最新的在前
        assert logs[1].to_status == 70
        db.close()

    def test_assignee_name_fallback_to_username(self):
        """display_name 为空时回退到 username。"""
        db = _db()
        user = User(username="nopname", password_hash="x", display_name=None, role="analyst")
        db.add(user)
        db.commit()
        alert = _seed_alert(db, deal_status=0)
        body = HandleBody(to_status=70, assignee_id=user.id, comment="指派")

        _do_handle(db, alert, body, user.id, "nopname")
        assert alert.assignee_name == "nopname"
        db.close()


class TestBatchHandle:
    """批量处置逻辑。"""

    def test_batch_mixed_success_skip(self):
        """批量中部分合法部分非法：成功+跳过。"""
        db = _db()
        user = _seed_user(db)
        a1 = _seed_alert(db, deal_status=0)   # 0→70 允许
        a2 = _seed_alert(db, deal_status=20)  # 20→30 不允许（已关闭只能→处置中）

        body = HandleBody(to_status=30, assignee_id=None, comment="批量加白")

        results = {"succeeded": [], "skipped": []}
        for alert in [a1, a2]:
            from_status = alert.deal_status if alert.deal_status is not None else 0
            allowed = _TRANSITIONS.get(from_status, set())
            if body.to_status not in allowed:
                results["skipped"].append(alert.id)
                continue
            _do_handle(db, alert, body, user.id, user.display_name)
            results["succeeded"].append(alert.id)
        db.commit()

        assert a1.id in results["succeeded"]
        assert a2.id in results["skipped"]
        assert a1.deal_status == 30
        assert a2.deal_status == 20  # 未变更
        db.close()
