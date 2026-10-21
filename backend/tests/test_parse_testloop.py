"""阶段二：解析测试闭环 / 草稿发布版本管理 / 失败样本下钻 单测。

覆盖：
- 草稿机制：PUT 保存草稿（线上不受影响）→ 发布替换线上 + 版本快照 + 审计；
- 版本管理：创建即 v1、版本列表（is_current）、单版本取数、回滚生成新版本；
- 测试解析（test-parse）：多条日志逐条预处理 → 命中规则（逐条件评估详情）→
  提取明细 / 校验结果；未命中展示自动路由回退路径；use_draft 切换草稿/线上；
- 失败样本下钻：模板维度（error_type 四分类 + 按原因筛选）、
  条目维度（DeviceReceiveLog fail/unknown 分类 + 筛选）。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_parse_testloop.py -v
"""
import os
import sys

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.ingest as ingest_mod
from app.database import Base, get_db
from app.dependencies import get_current_user
from app.models.audit_log import AuditLog
from app.models.log_receiver import DeviceReceiveLog, LogReceiver
from app.models.log_source_entry import LogSourceEntry
from app.models.parse_error import ParseErrorQueue
from app.models.parse_strategy import ParseStrategy, ParseStrategyVersion
from app.models.user import User

# ============ 测试基础设施：共享内存 SQLite ============
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

Base.metadata.create_all(_engine, tables=[
    ParseStrategy.__table__,
    ParseStrategyVersion.__table__,
    ParseErrorQueue.__table__,
    LogReceiver.__table__,
    LogSourceEntry.__table__,
    DeviceReceiveLog.__table__,
    User.__table__,
    AuditLog.__table__,
])


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """每用例：ingest 的策略缓存 SessionLocal 指到测试库并重置进程级缓存。"""
    monkeypatch.setattr(ingest_mod, "SessionLocal", _TestSessionLocal)
    ingest_mod._strategy_loader = None
    yield
    ingest_mod._strategy_loader = None
    with _engine.begin() as conn:
        for name in (
            "parse_strategy_versions", "parse_strategies", "parse_error_queue",
            "log_source_entries", "log_receivers", "device_receive_logs",
            "users", "audit_logs",
        ):
            conn.execute(Base.metadata.tables[name].delete())


def _build_client():
    app = FastAPI()
    from app.api.v1.ingest import router as ingest_router
    from app.api.v1.log_receivers import router as lr_router

    app.include_router(ingest_router)
    app.include_router(lr_router)

    def _override_db():
        db = _TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fake_user = User(id=1, username="tester", role="admin", role_id=None)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    return TestClient(app)


# 测试模板：规则匹配 datatype=account_change（青藤预处理器输出的扁平字段）
STRATEGY_CONFIG = {
    "strategy_name": "测试模板",
    "device_type": "test_dev",
    "version": "1.0",
    "status": "enabled",
    "outer_wrapper": {"data_path": "", "header_fields": [], "uuid_source": "uuid"},
    "rules": [
        {
            "rule_id": "acct", "log_type": "账号变更", "enabled": True,
            "match": {"type": "all", "conditions": [
                {"field": "datatype", "op": "eq", "value": "account_change"},
            ]},
            "extract": {"type": "fields", "fields": [
                {"source": "agent_ip", "target": "src_ip", "type": "string"},
                {"source": "host_name", "target": "host_name", "type": "string"},
                {"source": "severity", "target": "risk_level", "type": "int"},
            ]},
            "map": {
                "enum_maps": {}, "defaults": [{"target": "alert_kind", "value": "account"}],
                "field_mappings": [], "validations": [
                    {"field": "src_ip", "rule": "regex", "pattern": r"\d+\.\d+\.\d+\.\d+", "severity": "warning"},
                ],
            },
            "extension_fields": [],
        },
        {
            "rule_id": "never", "log_type": "兜底规则", "enabled": True,
            "match": {"type": "all", "conditions": [
                {"field": "datatype", "op": "eq", "value": "__never_match__"},
            ]},
            "extract": {"type": "fields", "fields": [{"source": "x", "target": "y", "type": "string"}]},
            "map": {"enum_maps": {}, "defaults": [], "field_mappings": [], "validations": []},
            "extension_fields": [],
        },
    ],
}

# 青藤 syslog 样例（与接收管道同预处理器：datatype= + datatime= 判定）
QT_LOG = (
    '<182>Oct  8 10:21:07 wangxiang qtAlert[4154710] datatype="account_change" '
    'datatime="1791426061" agent_ip="10.223.132.193" host_name="CNA05" '
    'severity="0" uname="i-00000019"'
)


def _seed_strategy(config=None):
    config = config or STRATEGY_CONFIG
    db = _TestSessionLocal()
    try:
        strat = ParseStrategy(
            strategy_name=config["strategy_name"],
            device_type=config["device_type"],
            version=config.get("version", "1.0"),
            status="enabled",
            config=__import__("json").dumps(config, ensure_ascii=False),
        )
        db.add(strat)
        db.commit()
        return strat.id
    finally:
        db.close()


# ============ 草稿 / 发布 / 版本管理 ============
class TestDraftPublish:
    def test_create_makes_v1_snapshot(self):
        client = _build_client()
        res = client.post("/ingest/strategies", json=STRATEGY_CONFIG)
        assert res.status_code == 201
        sid = res.json()["id"]
        assert res.json()["published_version_no"] == 1
        db = _TestSessionLocal()
        try:
            assert db.query(ParseStrategyVersion).filter_by(strategy_id=sid, version_no=1).count() == 1
        finally:
            db.close()

    def test_put_saves_draft_online_unchanged(self):
        sid = _seed_strategy()
        client = _build_client()
        draft = {**STRATEGY_CONFIG, "strategy_name": "改名草稿"}
        res = client.put(f"/ingest/strategies/{sid}", json=draft)
        assert res.status_code == 200 and res.json()["draft_saved"] is True
        db = _TestSessionLocal()
        try:
            strat = db.query(ParseStrategy).get(sid)
            assert strat.draft_config is not None and "改名草稿" in strat.draft_config
            assert "改名草稿" not in strat.config  # 线上版本不受影响
        finally:
            db.close()

    def test_publish_replaces_config_and_audits(self):
        sid = _seed_strategy()
        client = _build_client()
        client.put(f"/ingest/strategies/{sid}", json={**STRATEGY_CONFIG, "strategy_name": "发布版"})
        res = client.post(f"/ingest/strategies/{sid}/publish", json={"remark": "修复规则"})
        assert res.status_code == 200
        assert res.json()["published_version_no"] == 2
        db = _TestSessionLocal()
        try:
            strat = db.query(ParseStrategy).get(sid)
            assert strat.draft_config is None and "发布版" in strat.config
            assert strat.strategy_name == "发布版"
            assert strat.published_version_no == 2
            assert db.query(ParseStrategyVersion).filter_by(strategy_id=sid).count() == 2
            audit = db.query(AuditLog).filter_by(action="publish", resource_type="strategy").all()
            assert len(audit) == 1 and audit[0].username == "tester"
        finally:
            db.close()

    def test_publish_without_draft_422(self):
        sid = _seed_strategy()
        client = _build_client()
        assert client.post(f"/ingest/strategies/{sid}/publish", json={"remark": ""}).status_code == 422

    def test_discard_draft(self):
        sid = _seed_strategy()
        client = _build_client()
        client.put(f"/ingest/strategies/{sid}", json=STRATEGY_CONFIG)
        assert client.delete(f"/ingest/strategies/{sid}/draft").status_code == 200
        # 无草稿再丢弃 → 422
        assert client.delete(f"/ingest/strategies/{sid}/draft").status_code == 422

    def test_versions_list_detail_and_rollback(self):
        sid = _seed_strategy()
        client = _build_client()
        client.put(f"/ingest/strategies/{sid}", json={**STRATEGY_CONFIG, "strategy_name": "v2版"})
        client.post(f"/ingest/strategies/{sid}/publish", json={"remark": "v2"})
        # 版本列表：v2 is_current
        versions = client.get(f"/ingest/strategies/{sid}/versions").json()
        assert [v["version_no"] for v in versions] == [2, 1]
        assert versions[0]["is_current"] is True and versions[1]["is_current"] is False
        # 单版本取数
        v1 = client.get(f"/ingest/strategies/{sid}/versions/1").json()
        assert v1["config"]["strategy_name"] == "测试模板"
        # 回滚到 v1 → 新版本 v3 且线上恢复
        res = client.post(f"/ingest/strategies/{sid}/rollback", json={"version_no": 1, "remark": ""})
        assert res.status_code == 200 and res.json()["published_version_no"] == 3
        db = _TestSessionLocal()
        try:
            strat = db.query(ParseStrategy).get(sid)
            assert strat.strategy_name == "测试模板"
            audit = db.query(AuditLog).filter_by(action="rollback", resource_type="strategy").count()
            assert audit == 1
        finally:
            db.close()

    def test_detail_returns_draft_and_online(self):
        sid = _seed_strategy()
        client = _build_client()
        client.put(f"/ingest/strategies/{sid}", json={**STRATEGY_CONFIG, "strategy_name": "草稿版"})
        detail = client.get(f"/ingest/strategies/{sid}").json()
        assert detail["has_draft"] is True
        assert detail["draft_config"]["strategy_name"] == "草稿版"
        assert detail["config"]["strategy_name"] == "测试模板"


# ============ 测试解析（test-parse） ============
class TestTestParse:
    def test_qingteng_line_hits_rule_with_details(self):
        sid = _seed_strategy()
        client = _build_client()
        res = client.post(f"/ingest/strategies/{sid}/test-parse", json={"logs": [QT_LOG]})
        assert res.status_code == 200
        body = res.json()
        assert body["strategy"]["using"] == "published"
        assert body["summary"] == {"total": 1, "success": 1, "partial": 0, "fail": 0}
        r = body["results"][0]
        assert r["status"] == "success"
        assert r["rule"]["rule_id"] == "acct"
        # 逐条件评估详情：datatype eq account_change 命中
        cond = r["rules_detail"][0]["conditions"][0]
        assert cond["field"] == "datatype" and cond["hit"] is True
        assert cond["actual"] == "account_change"
        # 提取明细：agent_ip → src_ip
        row = next(m for m in r["mappings"] if m["target"] == "src_ip")
        assert row["source"] == "agent_ip" and row["raw_value"] == "10.223.132.193"
        assert row["converted"] == "10.223.132.193"
        # 校验结果：定义 1 条且通过
        assert r["validations"]["defined"] == 1 and r["validations"]["passed"] == 1
        assert r["fields"]["alert_kind"] == "account"
        assert r["fallback_path"] is None

    def test_unmatched_log_shows_fallback_path(self):
        sid = _seed_strategy()
        client = _build_client()
        res = client.post(
            f"/ingest/strategies/{sid}/test-parse",
            json={"logs": ['{"type": "unmatched_kind"}']},
        )
        body = res.json()
        r = body["results"][0]
        assert r["status"] == "fail" and r["rule"] is None
        fb = r["fallback_path"]
        assert fb is not None
        assert "classification" in fb and "metadata_checks" in fb
        assert isinstance(fb["attempts"], list)
        assert fb["legacy_route_rules"] is None  # 无 route_rules 存量策略

    def test_use_draft_switches_config(self):
        sid = _seed_strategy()
        client = _build_client()
        # 草稿：把 agent_ip → src_ip 改为 host_name → src_ip
        draft = __import__("json").loads(__import__("json").dumps(STRATEGY_CONFIG))
        draft["rules"][0]["extract"]["fields"][0] = {"source": "host_name", "target": "src_ip", "type": "string"}
        client.put(f"/ingest/strategies/{sid}", json=draft)
        # 测草稿：src_ip = host_name 值
        res = client.post(f"/ingest/strategies/{sid}/test-parse", json={"logs": [QT_LOG], "use_draft": True})
        assert res.json()["strategy"]["using"] == "draft"
        fields = res.json()["results"][0]["fields"]
        assert fields["src_ip"] == "CNA05"
        # 测线上：src_ip = agent_ip 值
        res2 = client.post(f"/ingest/strategies/{sid}/test-parse", json={"logs": [QT_LOG], "use_draft": False})
        assert res2.json()["strategy"]["using"] == "published"
        assert res2.json()["results"][0]["fields"]["src_ip"] == "10.223.132.193"

    def test_context_shows_binding_chain(self):
        sid = _seed_strategy()
        db = _TestSessionLocal()
        try:
            rv = LogReceiver(device_id=None, device_name="d", name="rx", protocol="syslog", syslog_port=514)
            db.add(rv)
            db.flush()
            entry = LogSourceEntry(receiver_id=rv.id, source_ip="1.2.3.4", strategy_id=sid)
            db.add(entry)
            db.commit()
            entry_id, receiver_id = entry.id, rv.id
        finally:
            db.close()
        client = _build_client()
        res = client.post(
            f"/ingest/strategies/{sid}/test-parse",
            json={"logs": [QT_LOG], "context": {"entry_id": entry_id, "receiver_id": receiver_id}},
        )
        ctx = res.json()["context"]
        assert ctx["bound_strategy_id"] == sid and ctx["bound_strategy_source"] == "entry"
        assert "绑定当前模板" in ctx["note"]


# ============ 失败样本下钻（模板维度） ============
class TestStrategyFailureSamples:
    def _seed_errors(self, sid):
        import json as _json
        db = _TestSessionLocal()
        try:
            for et, msg in (
                ("no_strategy_matched", "无匹配策略"),
                ("unknown_log_type", "类型识别与路由失败"),
                ("json_parse_failed", "原始数据不是 JSON 对象"),
                ("field_validation_failed", "字段校验失败"),
                ("db_write_failed", "入库异常"),
            ):
                db.add(ParseErrorQueue(
                    strategy_id=sid, raw_data=_json.dumps({"a": 1}),
                    error_type=et, error_msg=msg,
                ))
            db.commit()
        finally:
            db.close()

    def test_classification_stats_and_filter(self):
        sid = _seed_strategy()
        self._seed_errors(sid)
        client = _build_client()
        body = client.get(f"/ingest/strategies/{sid}/failure-samples").json()
        assert body["total"] == 5
        stats = body["stats"]
        assert stats["no_template"] == 2  # no_strategy_matched + unknown_log_type
        assert stats["format_error"] == 1
        assert stats["validation_failed"] == 1
        assert stats["other"] == 1  # db_write_failed
        # 按原因筛选
        body2 = client.get(f"/ingest/strategies/{sid}/failure-samples?reason=no_template").json()
        assert body2["total"] == 2
        assert all(i["reason_class"] == "no_template" for i in body2["items"])
        # 条目维度标签
        assert body["reason_labels"]["no_template"] == "无匹配模板"

    def test_404_for_missing_strategy(self):
        client = _build_client()
        assert client.get("/ingest/strategies/999/failure-samples").status_code == 404


# ============ 失败样本下钻（条目维度） ============
class TestEntryFailureSamples:
    def _seed(self):
        import json as _json
        db = _TestSessionLocal()
        try:
            rv = LogReceiver(device_id=None, device_name="d", name="rx", protocol="syslog", syslog_port=514)
            db.add(rv)
            db.flush()
            entry = LogSourceEntry(receiver_id=rv.id, source_ip="1.2.3.4")
            db.add(entry)
            db.flush()
            for status, err in (
                ("fail", "无匹配策略：无匹配"),
                ("unknown", "类型识别与路由失败：无元数据且特征条件未命中"),
                ("fail", "字段校验失败：uuid 不符合正则"),
                ("fail", "原始数据不是 JSON 对象"),
                ("fail", "其他奇怪错误"),
            ):
                db.add(DeviceReceiveLog(
                    receiver_id=rv.id, source_ip="1.2.3.4", parse_status=status,
                    parse_error=err, raw_data=_json.dumps({"b": 2}),
                ))
            db.commit()
            return entry.id
        finally:
            db.close()

    def test_entry_failure_classification_and_filter(self):
        entry_id = self._seed()
        client = _build_client()
        body = client.get(f"/log-receivers/entries/{entry_id}/failure-samples").json()
        assert body["total"] == 5
        stats = body["stats"]
        assert stats["no_template"] == 2  # 无匹配 + unknown
        assert stats["validation_failed"] == 1
        assert stats["format_error"] == 1
        assert stats["other"] == 1
        # 按原因筛选
        body2 = client.get(f"/log-receivers/entries/{entry_id}/failure-samples?reason=no_template").json()
        assert body2["total"] == 2
        # 原始日志可查看
        assert body["items"][0]["raw_data"]

    def test_404_for_missing_entry(self):
        client = _build_client()
        assert client.get("/log-receivers/entries/999/failure-samples").status_code == 404
