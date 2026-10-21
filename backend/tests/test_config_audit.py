"""配置变更审计日志测试（阶段四③）+ 模板导入导出测试（阶段四②）。

覆盖设备对接域四类对象的增删改审计留痕：
- 接收器：创建 / 更新（字段级 diff）/ 删除 → audit_logs（resource_type=log_receiver）
- 数据源条目：更新（字段级 diff）/ 删除 / 批量删除 → audit_logs（resource_type=log_source_entry）
- 解析模板：创建 / 草稿保存 / 启停 / 删除 → audit_logs（resource_type=strategy）
- detail 含对象名称与变更内容，ip_address 记录来源 IP

模板导入导出：
- 导出返回策略 config 全文（JSON 附件）
- 导入校验结构，名称冲突自动重命名（追加 (导入N) 后缀），非法结构整批拒绝
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.v1.ingest as ingest_mod
import app.api.v1.log_receivers as receivers_mod
from app.database import Base, get_db
from app.dependencies import get_current_user
from app.models.alert_event import AlertEvent
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.ingestion_metric import IngestionMetric
from app.models.log_receiver import DeviceReceiveLog, DeviceReceiveMetric, LogReceiver
from app.models.log_source_entry import LogSourceEntry
from app.models.parse_error import ParseErrorQueue
from app.models.parse_strategy import ParseStrategy, ParseStrategyVersion
from app.models.user import User
from app.models.workflow_ban import WorkflowInstance

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
    DeviceReceiveMetric.__table__,
    User.__table__,
    AuditLog.__table__,
    AlertEvent.__table__,
    Device.__table__,
    IngestionMetric.__table__,
    WorkflowInstance.__table__,
])

_TABLES = (
    "parse_strategy_versions", "parse_strategies", "parse_error_queue",
    "log_source_entries", "log_receivers", "device_receive_logs",
    "device_receive_metrics", "users", "audit_logs",
    "alert_events", "devices", "ingestion_metrics", "workflow_instances",
)


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """每用例：ingest 策略缓存 SessionLocal 指到测试库并重置进程级缓存。"""
    monkeypatch.setattr(ingest_mod, "SessionLocal", _TestSessionLocal)
    ingest_mod._strategy_loader = None
    yield
    ingest_mod._strategy_loader = None
    with _engine.begin() as conn:
        for name in _TABLES:
            conn.execute(Base.metadata.tables[name].delete())


def _build_client():
    app = FastAPI()
    from app.api.v1.ingest import router as ingest_router
    from app.api.v1.log_receivers import router as receivers_router

    app.include_router(ingest_router)
    app.include_router(receivers_router)

    def _override_db():
        db = _TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fake_user = User(id=1, username="auditor", role="admin", role_id=None)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    return TestClient(app)


def _audit_rows(db, resource_type=None, action=None):
    q = db.query(AuditLog)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    if action:
        q = q.filter(AuditLog.action == action)
    return q.order_by(AuditLog.id.desc()).all()


def _detail_dict(log):
    return json.loads(log.detail) if log.detail else {}


# ============ 接收器审计 ============
class TestReceiverAudit:
    def test_create_receiver_audited(self):
        """创建接收器 → audit_logs 记 create + 对象名称 + 协议。"""
        client = _build_client()
        resp = client.post("/log-receivers", json={
            "name": "syslog-test", "protocol": "syslog",
            "syslog_port": 15141, "syslog_proto": "udp", "enabled": False,
        })
        assert resp.status_code == 201, resp.text
        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="log_receiver", action="create")
            assert len(rows) == 1
            d = _detail_dict(rows[0])
            assert d["name"] == "syslog-test"
            assert d["protocol"] == "syslog"
            assert rows[0].username == "auditor"
            assert rows[0].ip_address  # 来源 IP 已记录
        finally:
            db.close()

    def test_update_receiver_field_diff_audited(self):
        """更新接收器 → audit_logs 记 update，detail 含字段级 old/new diff。"""
        db = _TestSessionLocal()
        rec = LogReceiver(
            name="syslog-old", protocol="syslog", enabled=0,
            syslog_port=15142, syslog_proto="udp", syslog_bind="0.0.0.0",
            adapter_config="{}", kafka_security="{}", format="json", description="旧描述",
        )
        db.add(rec)
        db.commit()
        rid = rec.id
        db.close()

        client = _build_client()
        resp = client.put(f"/log-receivers/{rid}", json={
            "name": "syslog-new", "protocol": "syslog", "enabled": False,
            "syslog_port": 15142, "syslog_proto": "udp", "syslog_bind": "0.0.0.0",
            "format": "json", "description": "新描述",
        })
        assert resp.status_code == 200, resp.text

        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="log_receiver", action="update")
            assert len(rows) == 1
            d = _detail_dict(rows[0])
            assert d["name"] == "syslog-new"
            assert d["changes"]["name"] == {"old": "syslog-old", "new": "syslog-new"}
            assert d["changes"]["description"] == {"old": "旧描述", "new": "新描述"}
        finally:
            db.close()

    def test_delete_receiver_audited(self):
        """删除接收器 → audit_logs 记 delete + 对象名称。"""
        db = _TestSessionLocal()
        rec = LogReceiver(name="to-delete", protocol="syslog", enabled=0, syslog_port=15143, adapter_config="{}", kafka_security="{}")
        db.add(rec)
        db.commit()
        rid = rec.id
        db.close()

        client = _build_client()
        resp = client.delete(f"/log-receivers/{rid}")
        assert resp.status_code == 204

        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="log_receiver", action="delete")
            assert len(rows) == 1
            assert _detail_dict(rows[0])["name"] == "to-delete"
        finally:
            db.close()


# ============ 数据源条目审计 ============
class TestSourceEntryAudit:
    def _insert_entry(self):
        db = _TestSessionLocal()
        rec = LogReceiver(name="r-entry", protocol="syslog", enabled=0, syslog_port=15144, adapter_config="{}", kafka_security="{}")
        db.add(rec)
        db.flush()
        entry = LogSourceEntry(receiver_id=rec.id, source_ip="10.0.0.1", name="10.0.0.1", enabled=1)
        db.add(entry)
        db.commit()
        eid, rid = entry.id, rec.id
        db.close()
        return eid, rid

    def test_update_entry_field_diff_audited(self):
        """更新条目（停用）→ audit_logs 记 update + enabled diff + 来源 IP。"""
        eid, _ = self._insert_entry()
        client = _build_client()
        resp = client.put(f"/log-receivers/entries/{eid}", json={"enabled": False, "name": "入口A"})
        assert resp.status_code == 200, resp.text

        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="log_source_entry", action="update")
            assert len(rows) == 1
            d = _detail_dict(rows[0])
            assert d["name"] == "入口A"
            assert d["source_ip"] == "10.0.0.1"
            assert d["changes"]["enabled"] == {"old": True, "new": False}
            assert d["changes"]["name"] == {"old": "10.0.0.1", "new": "入口A"}
        finally:
            db.close()

    def test_delete_entry_audited(self):
        """删除条目 → audit_logs 记 delete + 对象名称与来源 IP 字段。"""
        eid, _ = self._insert_entry()
        client = _build_client()
        resp = client.delete(f"/log-receivers/entries/{eid}")
        assert resp.status_code == 204

        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="log_source_entry", action="delete")
            assert len(rows) == 1
            d = _detail_dict(rows[0])
            assert d["source_ip"] == "10.0.0.1"
            assert d["receiver_id"]
        finally:
            db.close()

    def test_batch_delete_entries_audited(self):
        """批量删除条目 → audit_logs 记 delete，detail 含 count 与 source_ips。"""
        _, rid = self._insert_entry()
        db = _TestSessionLocal()
        db.add(LogSourceEntry(receiver_id=rid, source_ip="10.0.0.2", name="10.0.0.2", enabled=1))
        db.commit()
        ids = [e.id for e in db.query(LogSourceEntry.id).filter(LogSourceEntry.receiver_id == rid).all()]
        db.close()

        client = _build_client()
        resp = client.post(f"/log-receivers/{rid}/entries/batch-delete", json={"ids": ids})
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] == 2

        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="log_source_entry", action="delete")
            assert len(rows) == 1
            d = _detail_dict(rows[0])
            assert d["operation"] == "batch_delete"
            assert d["count"] == 2
            assert set(d["source_ips"]) == {"10.0.0.1", "10.0.0.2"}
        finally:
            db.close()


# ============ 解析模板审计 ============
def _minimal_strategy_config(name="审计模板"):
    return {
        "strategy_name": name,
        "device_type": "audit_dev",
        "version": "1.0",
        "status": "enabled",
        "route_rules": {"match_type": "exact", "match_field": "type", "match_value": "x"},
        "field_mappings": [{"source": "a", "target": "b"}],
    }


class TestStrategyAudit:
    def test_create_strategy_audited(self):
        """创建模板 → audit_logs 记 create + 模板名 + 设备类型。"""
        client = _build_client()
        resp = client.post("/ingest/strategies", json=_minimal_strategy_config())
        assert resp.status_code == 201, resp.text

        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="strategy", action="create")
            assert len(rows) == 1
            d = _detail_dict(rows[0])
            assert d["strategy_name"] == "审计模板"
            assert d["device_type"] == "audit_dev"
        finally:
            db.close()

    def test_save_draft_and_toggle_status_audited(self):
        """草稿保存与启停 → audit_logs 各记 update，detail 含操作与状态 diff。"""
        client = _build_client()
        sid = client.post("/ingest/strategies", json=_minimal_strategy_config()).json()["id"]

        resp = client.put(f"/ingest/strategies/{sid}", json=_minimal_strategy_config("审计模板-改"))
        assert resp.status_code == 200, resp.text
        resp = client.patch(f"/ingest/strategies/{sid}/status", json={"status": "disabled"})
        assert resp.status_code == 200, resp.text

        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="strategy", action="update")
            assert len(rows) == 2
            ops = {_detail_dict(r).get("operation") for r in rows}
            assert ops == {"save_draft", "toggle_status"}
            toggle = next(r for r in rows if _detail_dict(r).get("operation") == "toggle_status")
            assert _detail_dict(toggle)["changes"]["status"] == {"old": "enabled", "new": "disabled"}
        finally:
            db.close()

    def test_delete_strategy_audited(self):
        """删除模板 → audit_logs 记 delete + 模板名。"""
        client = _build_client()
        sid = client.post("/ingest/strategies", json=_minimal_strategy_config("待删模板")).json()["id"]

        resp = client.delete(f"/ingest/strategies/{sid}")
        assert resp.status_code == 204

        db = _TestSessionLocal()
        try:
            rows = _audit_rows(db, resource_type="strategy", action="delete")
            assert len(rows) == 1
            assert _detail_dict(rows[0])["strategy_name"] == "待删模板"
        finally:
            db.close()


# ============ 模板导入导出 ============
class TestStrategyImportExport:
    def test_export_returns_config_json(self):
        """导出模板 → JSON 附件，内容即策略 config 全文。"""
        client = _build_client()
        sid = client.post("/ingest/strategies", json=_minimal_strategy_config("导出模板")).json()["id"]

        resp = client.get(f"/ingest/strategies/{sid}/export")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
        cfg = resp.json()
        assert cfg["strategy_name"] == "导出模板"
        assert cfg["route_rules"]["match_value"] == "x"

    def test_export_404_for_missing(self):
        """导出不存在的模板 → 404。"""
        client = _build_client()
        assert client.get("/ingest/strategies/999/export").status_code == 404

    def test_import_renames_conflict(self):
        """导入与存量同名模板 → 自动重命名 (导入2)，原名保留在 renamed_from。"""
        client = _build_client()
        client.post("/ingest/strategies", json=_minimal_strategy_config("冲突模板"))

        resp = client.post("/ingest/strategies/import", json={"config": _minimal_strategy_config("冲突模板")})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["imported"] == 1
        assert data["items"][0]["renamed_from"] == "冲突模板"
        assert data["items"][0]["strategy_name"] == "冲突模板(导入2)"

        db = _TestSessionLocal()
        try:
            names = {r.strategy_name for r in db.query(ParseStrategy).all()}
            assert names == {"冲突模板", "冲突模板(导入2)"}
            # 导入动作写审计（action=upload）
            rows = _audit_rows(db, resource_type="strategy", action="upload")
            assert len(rows) == 1
            assert _detail_dict(rows[0])["operation"] == "import"
        finally:
            db.close()

    def test_import_batch_and_same_batch_conflict(self):
        """批量导入：数组内两个同名模板 → 第二个自动重命名。"""
        client = _build_client()
        configs = [_minimal_strategy_config("批量A"), _minimal_strategy_config("批量A")]
        resp = client.post("/ingest/strategies/import", json={"configs": configs})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["imported"] == 2
        assert data["items"][0]["renamed_from"] is None
        assert data["items"][1]["strategy_name"] == "批量A(导入2)"

    def test_import_invalid_config_rejected_wholesale(self):
        """批量中任一结构非法 → 整批拒绝（422），不产生部分导入。"""
        client = _build_client()
        bad = {"strategy_name": "", "device_type": "x"}  # 缺 strategy_name / route_rules
        resp = client.post("/ingest/strategies/import", json={"configs": [_minimal_strategy_config("合法模板"), bad]})
        assert resp.status_code == 422

        db = _TestSessionLocal()
        try:
            assert db.query(ParseStrategy).count() == 0
        finally:
            db.close()

    def test_import_empty_body_rejected(self):
        """空导入内容 → 422。"""
        client = _build_client()
        resp = client.post("/ingest/strategies/import", json={})
        assert resp.status_code == 422
