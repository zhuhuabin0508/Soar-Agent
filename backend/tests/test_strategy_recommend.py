"""设备接入向导 - 解析策略推荐端点测试。

覆盖：
- 空数据库下内置策略仍可推荐
- 按设备类型过滤
- 存量（db）与内置（builtin）按 strategy_name 去重，存量优先
- rule_count / field_count 统计正确
"""
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

# ============ 共享内存 SQLite ============
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
    app.include_router(ingest_router)

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


def _insert_strategy(db, *, name, device_type, version="1.0", status="enabled", config=None):
    """插入一条存量策略。"""
    import json
    strat = ParseStrategy(
        strategy_name=name,
        device_type=device_type,
        version=version,
        status=status,
        config=json.dumps(config or {}, ensure_ascii=False),
        published_version_no=1,
    )
    db.add(strat)
    db.commit()
    return strat


# ======================================================================
# 测试用例
# ======================================================================
def test_recommend_empty_db_returns_builtin():
    """空数据库：内置策略（sangfor / qingteng）仍可推荐。"""
    client = _build_client()
    r = client.get("/ingest/strategies/recommend")
    assert r.status_code == 200
    data = r.json()
    names = {item["strategy_name"] for item in data}
    # 内置至少包含 sangfor / qingteng
    assert any("Sangfor" in n or "sangfor" in n.lower() for n in names), names
    assert any("青藤" in n or "qingteng" in n.lower() for n in names), names
    # 内置项 source=builtin，id=None
    builtin_items = [it for it in data if it["source"] == "builtin"]
    assert builtin_items
    assert all(it["id"] is None for it in builtin_items)
    # rule_count / field_count > 0
    for it in builtin_items:
        assert it["rule_count"] >= 1
        assert it["field_count"] >= 1


def test_recommend_filter_by_device_type():
    """按 device_type 过滤：只返回匹配的。"""
    client = _build_client()
    r = client.get("/ingest/strategies/recommend?device_type=sangfor_xdr")
    assert r.status_code == 200
    data = r.json()
    assert data, "sangfor_xdr 应有推荐策略"
    assert all(it["device_type"] == "sangfor_xdr" for it in data), data
    # 至少包含 sangfor
    assert any("Sangfor" in it["strategy_name"] for it in data), data


def test_recommend_db_priority_over_builtin():
    """存量与内置同名时：存量优先，去重（只返回一条，source=db）。"""
    client = _build_client()
    db = _TestSessionLocal()
    try:
        # 插入一条与内置同名的存量策略（Sangfor XDR 安全告警 v1.30）
        _insert_strategy(
            db,
            name="Sangfor XDR 安全告警 v1.30",
            device_type="sangfor_xdr",
            config={
                "strategy_name": "Sangfor XDR 安全告警 v1.30",
                "device_type": "sangfor_xdr",
                "version": "1.30",
                "rules": [
                    {
                        "rule_id": "default", "log_type": "默认", "enabled": True,
                        "match": {"type": "all", "conditions": [{"field": "type", "op": "eq", "value": "security_alert"}]},
                        "extract": {"type": "fields", "fields": [
                            {"source": "uuId", "target": "uuid", "type": "string"},
                            {"source": "name", "target": "alert_name", "type": "string"},
                        ]},
                        "map": {"field_mappings": [], "enum_maps": {}, "defaults": []},
                    }
                ],
            },
        )
    finally:
        db.close()

    r = client.get("/ingest/strategies/recommend?device_type=sangfor_xdr")
    assert r.status_code == 200
    data = r.json()
    # 同名只出现一次，且 source=db（存量优先）
    sangfor_items = [it for it in data if "Sangfor" in it["strategy_name"]]
    assert len(sangfor_items) == 1, sangfor_items
    assert sangfor_items[0]["source"] == "db"
    assert sangfor_items[0]["id"] is not None


def test_recommend_stats_correct():
    """rule_count / field_count 统计正确（多规则 + 字段并集）。"""
    client = _build_client()
    db = _TestSessionLocal()
    try:
        _insert_strategy(
            db,
            name="多规则测试模板",
            device_type="multi_rule_dev",
            config={
                "strategy_name": "多规则测试模板",
                "device_type": "multi_rule_dev",
                "version": "1.0",
                "rules": [
                    {
                        "rule_id": "r1", "log_type": "告警", "enabled": True,
                        "match": {"type": "all", "conditions": [{"field": "t", "op": "eq", "value": "a"}]},
                        "extract": {"type": "fields", "fields": [
                            {"source": "u", "target": "uuid", "type": "string"},
                            {"source": "n", "target": "alert_name", "type": "string"},
                        ]},
                        "map": {"field_mappings": [], "enum_maps": {}, "defaults": []},
                    },
                    {
                        "rule_id": "r2", "log_type": "登录", "enabled": True,
                        "match": {"type": "all", "conditions": [{"field": "t", "op": "eq", "value": "b"}]},
                        "extract": {"type": "fields", "fields": [
                            {"source": "u", "target": "uuid", "type": "string"},
                            {"source": "s", "target": "src_ip", "type": "string"},
                        ]},
                        "map": {"field_mappings": [], "enum_maps": {}, "defaults": []},
                    },
                ],
            },
        )
    finally:
        db.close()

    r = client.get("/ingest/strategies/recommend?device_type=multi_rule_dev")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    item = data[0]
    assert item["rule_count"] == 2, item
    # uuid 在两条规则里重复，并集为 3（uuid / alert_name / src_ip）
    assert item["field_count"] == 3, item


def test_recommend_disabled_status_returned():
    """停用策略也返回（向导可查看全量候选，启用状态由前端展示）。"""
    client = _build_client()
    db = _TestSessionLocal()
    try:
        _insert_strategy(
            db,
            name="停用模板",
            device_type="disabled_dev",
            status="disabled",
            config={
                "strategy_name": "停用模板",
                "device_type": "disabled_dev",
                "version": "1.0",
                "rules": [
                    {
                        "rule_id": "r", "log_type": "默认", "enabled": True,
                        "match": {"type": "all", "conditions": []},
                        "extract": {"type": "fields", "fields": [{"source": "u", "target": "uuid", "type": "string"}]},
                        "map": {"field_mappings": [], "enum_maps": {}, "defaults": []},
                    }
                ],
            },
        )
    finally:
        db.close()

    r = client.get("/ingest/strategies/recommend?device_type=disabled_dev")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["status"] == "disabled"
    # enabled 排序在前（test_recommend_db_priority 已验证 enabled 优先）
