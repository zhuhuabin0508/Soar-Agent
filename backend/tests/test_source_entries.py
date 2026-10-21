"""来源条目模型单测：自动发现 / 优先级合并 / 统计 flush / runner 缓存共存 / CRUD API。

覆盖阶段 1-4 全部行为：
- EntryRegistry：首见自动建条目 + 设备 IP 绑定、60s TTL 缓存（二次零查库）、
  发现开关关闭回退、条目数上限、并发 pending 去重、统计缓冲 flush（失败回填重试）；
- merge_receiver_entry：条目 strategy_id/device_id 覆盖渠道（0=强制自动，None=跟随）、
  entry_config.pipeline 与渠道 pipeline 深合并（条目覆盖渠道）；
- run_pipeline_for_event：条目停用丢弃、合并结果写回 event.receiver、
  非监听型协议不触发条目发现；
- PipelineRunner 缓存：多条目配置共存（FIFO 容量淘汰，不互挤）；
- 条目 CRUD API：列表搜索分页 / 更新（含缓存 invalidate）/ 删除 / 批量删除。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_source_entries.py -v
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.log_receiver_manager.entry_registry import (
    EntryRegistry,
    LISTEN_PROTOCOLS,
    entry_registry,
    merge_receiver_entry,
)
from app.core.log_receiver_manager.events import RawEvent
from app.core.log_receiver_manager.pipeline.runner import PipelineRunner, run_pipeline_for_event
from app.database import Base, get_db
from app.dependencies import get_current_user
from app.models.device import Device
from app.models.log_receiver import DeviceReceiveLog, DeviceReceiveMetric, LogReceiver
from app.models.log_source_entry import LogSourceEntry
from app.models.parse_strategy import ParseStrategy
from app.models.user import User

# ============ 测试基础设施：共享内存 SQLite（entry_registry 独立会话与 API get_db 同源） ============
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

# 只建本测试涉及的表（避免无关模型的方言兼容问题）
Base.metadata.create_all(_engine, tables=[
    Device.__table__,
    LogReceiver.__table__,
    LogSourceEntry.__table__,
    ParseStrategy.__table__,
    User.__table__,
    DeviceReceiveLog.__table__,
    DeviceReceiveMetric.__table__,
])


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """每用例：把 entry_registry / db_count_entries 的 SessionLocal 指到测试库，并清空进程级缓存。"""
    import app.core.log_receiver_manager.entry_registry as er_mod

    monkeypatch.setattr(er_mod, "SessionLocal", _TestSessionLocal)
    entry_registry._cache.clear()
    entry_registry._pending.clear()
    entry_registry._stats.clear()
    PipelineRunner._cache.clear()
    yield
    # 清库（保留表结构），保证用例间互不污染
    with _engine.begin() as conn:
        for name in (
            "log_source_entries", "log_receivers", "parse_strategies",
            "devices", "users", "device_receive_logs", "device_receive_metrics",
        ):
            conn.execute(Base.metadata.tables[name].delete())


def _receiver(rid=1, protocol="syslog", adapter_config=None, strategy_id=None, device_id=None):
    return {
        "id": rid,
        "protocol": protocol,
        "strategy_id": strategy_id,
        "device_id": device_id,
        "adapter_config": adapter_config if adapter_config is not None else {},
    }


def _seed_device(ip="1.1.1.1", name="青藤主机"):
    db = _TestSessionLocal()
    try:
        d = Device(name=name, type="edr", ip_address=ip)
        db.add(d)
        db.commit()
        return d.id
    finally:
        db.close()


def _seed_entry(rid=1, ip="1.1.1.1", **kw):
    db = _TestSessionLocal()
    try:
        rec = LogSourceEntry(
            receiver_id=rid,
            source_ip=ip,
            name=kw.pop("name", ip),
            device_id=kw.pop("device_id", None),
            enabled=kw.pop("enabled", 1),
            strategy_id=kw.pop("strategy_id", None),
            entry_config=kw.pop("entry_config", "{}"),
            auto_created=kw.pop("auto_created", 0),
        )
        db.add(rec)
        db.commit()
        return rec.id
    finally:
        db.close()


# ============ EntryRegistry：自动发现 / 缓存 / 开关 / 上限 ============
class TestEntryDiscovery:
    def test_first_seen_creates_entry_with_device_binding(self):
        dev_id = _seed_device("1.1.1.1")
        entry = entry_registry.resolve(1, "1.1.1.1", _receiver())
        assert entry is not None
        assert entry["source_ip"] == "1.1.1.1"
        assert entry["device_id"] == dev_id  # 首见按 devices.ip_address 自动绑定
        assert entry["name"] == "1.1.1.1"
        assert entry["enabled"] is True
        # 库中确有一条，且 auto_created=1
        db = _TestSessionLocal()
        try:
            rec = db.query(LogSourceEntry).filter_by(receiver_id=1, source_ip="1.1.1.1").one()
            assert rec.auto_created == 1
        finally:
            db.close()

    def test_second_resolve_hits_cache_zero_db(self, monkeypatch):
        import app.core.log_receiver_manager.entry_registry as er_mod

        first = entry_registry.resolve(1, "1.1.1.1", _receiver())
        assert first is not None

        def _boom():
            raise RuntimeError("不应再查库（应命中缓存）")

        monkeypatch.setattr(er_mod, "SessionLocal", _boom)
        second = entry_registry.resolve(1, "1.1.1.1", _receiver())
        assert second is not None and second["id"] == first["id"]  # 命中缓存，零查库

    def test_discovery_disabled_returns_none(self):
        rv = _receiver(adapter_config={"entry_discovery": False})
        assert entry_registry.resolve(2, "2.2.2.2", rv) is None
        db = _TestSessionLocal()
        try:
            assert db.query(LogSourceEntry).filter_by(receiver_id=2).count() == 0
        finally:
            db.close()

    def test_discovery_default_off_for_pull_protocols(self):
        # 拉取型协议（kafka 等）不在 LISTEN_PROTOCOLS，默认不建条目
        assert "kafka" not in LISTEN_PROTOCOLS
        rv = _receiver(protocol="kafka")
        assert entry_registry.resolve(3, "3.3.3.3", rv) is None
        db = _TestSessionLocal()
        try:
            assert db.query(LogSourceEntry).filter_by(receiver_id=3).count() == 0
        finally:
            db.close()

    def test_max_count_blocks_new_entries(self):
        rv = _receiver(adapter_config={"entry_max_count": 1})
        first = entry_registry.resolve(1, "1.1.1.1", rv)
        assert first is not None
        second = entry_registry.resolve(1, "9.9.9.9", rv)  # 超上限：不建，回退渠道默认
        assert second is None
        db = _TestSessionLocal()
        try:
            assert db.query(LogSourceEntry).filter_by(receiver_id=1).count() == 1
        finally:
            db.close()

    def test_existing_manual_entry_loaded_not_recreated(self):
        eid = _seed_entry(rid=1, ip="1.1.1.1", enabled=0, name="手工条目")
        entry = entry_registry.resolve(1, "1.1.1.1", _receiver())
        assert entry is not None and entry["id"] == eid
        assert entry["enabled"] is False
        assert entry["name"] == "手工条目"
        db = _TestSessionLocal()
        try:
            assert db.query(LogSourceEntry).filter_by(receiver_id=1, source_ip="1.1.1.1").count() == 1
        finally:
            db.close()

    def test_concurrent_pending_falls_back(self):
        entry_registry._pending.add((1, "1.1.1.1"))  # 模拟另一线程正在创建
        assert entry_registry.resolve(1, "1.1.1.1", _receiver()) is None  # 本次回退渠道默认

    def test_invalidate_clears_cache(self):
        entry_registry.resolve(1, "1.1.1.1", _receiver())
        entry_registry.invalidate(1, "1.1.1.1")
        assert (1, "1.1.1.1") not in entry_registry._cache
        # 再 resolve 重新从库加载
        again = entry_registry.resolve(1, "1.1.1.1", _receiver())
        assert again is not None


# ============ merge_receiver_entry：条目 → 渠道优先级链 + pipeline 深合并 ============
class TestMergeReceiverEntry:
    def _entry(self, strategy_id=None, device_id=None, pipeline=None):
        return {
            "id": 10, "source_ip": "1.1.1.1", "name": "e", "enabled": True,
            "strategy_id": strategy_id, "device_id": device_id,
            "entry_config": {"pipeline": pipeline} if pipeline else {},
        }

    def test_entry_strategy_overrides_receiver(self):
        merged = merge_receiver_entry(_receiver(strategy_id=5), self._entry(strategy_id=9))
        assert merged["strategy_id"] == 9

    def test_entry_strategy_zero_forces_auto(self):
        # 条目显式 0 = 强制自动匹配（忽略渠道固定策略）
        merged = merge_receiver_entry(_receiver(strategy_id=5), self._entry(strategy_id=0))
        assert merged["strategy_id"] == 0

    def test_entry_strategy_none_follows_receiver(self):
        merged = merge_receiver_entry(_receiver(strategy_id=5), self._entry(strategy_id=None))
        assert merged["strategy_id"] == 5

    def test_entry_device_overrides_receiver(self):
        merged = merge_receiver_entry(_receiver(device_id=1), self._entry(device_id=7))
        assert merged["device_id"] == 7
        # 条目未绑定设备时不覆盖渠道归属
        merged2 = merge_receiver_entry(_receiver(device_id=1), self._entry(device_id=None))
        assert merged2["device_id"] == 1

    def test_pipeline_deep_merge_entry_overrides_channel(self):
        rv = _receiver(adapter_config={
            "pipeline": {
                "filter": {"enabled": False, "rules": [{"field": "a", "op": "eq", "value": 1}]},
                "enricher": {"enrichers": ["asset"]},
                "translator": {"maps": {"risk_level_name": {"0": "严重"}}},
            }
        })
        entry = self._entry(pipeline={
            "filter": {"enabled": True, "rules": [{"field": "b", "op": "gte", "value": 3}]},
        })
        merged = merge_receiver_entry(rv, entry)
        pipe = merged["adapter_config"]["pipeline"]
        # 条目覆盖渠道：filter 整段被条目覆盖（list 直接替换）
        assert pipe["filter"] == {"enabled": True, "rules": [{"field": "b", "op": "gte", "value": 3}]}
        # 渠道独有段保留（条目未提供 enricher/translator）
        assert pipe["enricher"] == {"enrichers": ["asset"]}
        assert pipe["translator"] == {"maps": {"risk_level_name": {"0": "严重"}}}

    def test_original_receiver_not_mutated(self):
        rv = _receiver(adapter_config={"pipeline": {"filter": {"enabled": False}}})
        snapshot = dict(rv)
        merge_receiver_entry(rv, self._entry(pipeline={"filter": {"enabled": True}}))
        assert rv == snapshot  # 浅拷贝，不改原 dict


# ============ 统计缓冲 flush：累加入库 + 失败回填重试 ============
class TestEntryStatsFlush:
    def test_bump_and_flush_accumulates(self):
        _seed_entry(rid=1, ip="1.1.1.1")
        for _ in range(3):
            entry_registry.bump(1, "1.1.1.1")
        assert entry_registry._stats[(1, "1.1.1.1")][0] == 3
        entry_registry.flush_stats()
        db = _TestSessionLocal()
        try:
            rec = db.query(LogSourceEntry).filter_by(receiver_id=1, source_ip="1.1.1.1").one()
            assert rec.received_count == 3
            assert rec.last_received_at is not None
        finally:
            db.close()
        assert entry_registry._stats == {}  # flush 后缓冲清空

    def test_flush_failure_refills_and_retries(self, monkeypatch):
        import app.core.log_receiver_manager.entry_registry as er_mod

        _seed_entry(rid=1, ip="1.1.1.1")
        entry_registry.bump(1, "1.1.1.1")

        class _BadSession:
            def execute(self, *a, **k):
                raise RuntimeError("db down")

            def commit(self):
                raise RuntimeError("db down")

            def rollback(self):
                pass

            def close(self):
                pass

        monkeypatch.setattr(er_mod, "SessionLocal", _BadSession)
        entry_registry.flush_stats()  # 失败：回填缓冲
        assert entry_registry._stats[(1, "1.1.1.1")][0] == 1

        monkeypatch.setattr(er_mod, "SessionLocal", _TestSessionLocal)
        entry_registry.flush_stats()  # 重试成功
        db = _TestSessionLocal()
        try:
            rec = db.query(LogSourceEntry).filter_by(receiver_id=1, source_ip="1.1.1.1").one()
            assert rec.received_count == 1
        finally:
            db.close()
        assert entry_registry._stats == {}


# ============ run_pipeline_for_event：条目发现注入 / 停用丢弃 / 写回 ============
class TestRunPipelineForEvent:
    def _event(self, receiver, source_ip="1.1.1.1"):
        return RawEvent(
            receiver_id=receiver["id"], device_id=None, source_type=receiver["protocol"],
            source_ip=source_ip, transport="udp", received_at=datetime.now(),
            raw="x", receiver=receiver,
        )

    def _patch_run(self, monkeypatch):
        calls = []

        def _fake_run(self, event):
            calls.append({"config": self.config, "receiver": dict(event.receiver)})

        monkeypatch.setattr(PipelineRunner, "run", _fake_run)
        return calls

    def test_disabled_entry_drops_event(self, monkeypatch):
        calls = self._patch_run(monkeypatch)
        _seed_entry(rid=1, ip="1.1.1.1", enabled=0)
        run_pipeline_for_event(self._event(_receiver()))
        assert calls == []  # 条目停用：丢弃，不进流水线

    def test_entry_config_merged_back_to_event(self, monkeypatch):
        calls = self._patch_run(monkeypatch)
        _seed_entry(rid=1, ip="1.1.1.1", strategy_id=9,
                    entry_config='{"pipeline": {"filter": {"enabled": true}}}')
        ev = self._event(_receiver())
        run_pipeline_for_event(ev)
        assert len(calls) == 1
        # 合并结果写回 event.receiver：策略与 pipeline 均为条目级
        assert ev.receiver["strategy_id"] == 9
        assert calls[0]["receiver"]["strategy_id"] == 9
        assert calls[0]["config"]["filter"]["enabled"] is True
        # 统计已缓冲
        assert entry_registry._stats[(1, "1.1.1.1")][0] == 1

    def test_pull_protocol_skips_entry_discovery(self, monkeypatch):
        calls = self._patch_run(monkeypatch)
        rv = _receiver(protocol="kafka")
        ev = self._event(rv)
        run_pipeline_for_event(ev)
        assert len(calls) == 1  # 直接渠道默认执行
        db = _TestSessionLocal()
        try:
            assert db.query(LogSourceEntry).count() == 0  # 不建条目
        finally:
            db.close()

    def test_no_source_ip_skips_discovery(self, monkeypatch):
        calls = self._patch_run(monkeypatch)
        ev = self._event(_receiver(), source_ip=None)
        run_pipeline_for_event(ev)
        assert len(calls) == 1


# ============ PipelineRunner 缓存：多条目共存（FIFO 容量淘汰） ============
class TestRunnerCacheCoexist:
    def test_multiple_entry_configs_coexist(self):
        rv = _receiver()
        rA = PipelineRunner.for_receiver(
            merge_receiver_entry(rv, {"strategy_id": None, "device_id": None, "enabled": True,
                                     "entry_config": {"pipeline": {"filter": {"enabled": True}}}}),
            source_ip="1.1.1.1",
        )
        rB = PipelineRunner.for_receiver(
            merge_receiver_entry(rv, {"strategy_id": None, "device_id": None, "enabled": True,
                                     "entry_config": {"pipeline": {"filter": {"enabled": False}}}}),
            source_ip="2.2.2.2",
        )
        assert rA is not rB  # 不同来源条目各持一个 runner，不互挤
        assert rA.config["filter"]["enabled"] is True
        assert rB.config["filter"]["enabled"] is False
        # 同键二次取同一实例
        assert PipelineRunner.for_receiver(
            merge_receiver_entry(rv, {"strategy_id": None, "device_id": None, "enabled": True,
                                      "entry_config": {"pipeline": {"filter": {"enabled": True}}}}),
            source_ip="1.1.1.1",
        ) is rA
        assert len([k for k in PipelineRunner._cache if k[0] == 1]) == 2

    def test_same_ip_different_channel_not_shared(self):
        a = PipelineRunner.for_receiver(_receiver(rid=1), source_ip="1.1.1.1")
        b = PipelineRunner.for_receiver(_receiver(rid=2), source_ip="1.1.1.1")
        assert a is not b


# ============ 条目 CRUD API ============
def _build_client():
    app = FastAPI()
    from app.api.v1.log_receivers import router as lr_router

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


def _seed_receiver(rid=1, protocol="syslog"):
    db = _TestSessionLocal()
    try:
        rec = LogReceiver(device_id=1, device_name="d", name=f"r{rid}", protocol=protocol, syslog_port=514)
        db.add(rec)
        db.commit()
        return rec.id
    finally:
        db.close()


class TestEntryAPI:
    def test_list_search_and_pagination(self):
        rid = _seed_receiver()
        for ip in ("1.1.1.1", "1.1.1.2", "2.2.2.2"):
            _seed_entry(rid=rid, ip=ip)
        client = _build_client()
        res = client.get(f"/log-receivers/{rid}/entries")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 3
        res2 = client.get(f"/log-receivers/{rid}/entries?search=1.1.1.&page_size=10")
        assert res2.json()["total"] == 2
        # 404：渠道不存在
        assert client.get("/log-receivers/999/entries").status_code == 404

    def test_update_entry_and_invalidate_cache(self):
        rid = _seed_receiver()
        eid = _seed_entry(rid=rid, ip="1.1.1.1")
        client = _build_client()
        # 先让缓存热起来
        entry_registry.resolve(rid, "1.1.1.1", _receiver(rid))
        assert (rid, "1.1.1.1") in entry_registry._cache

        res = client.put(f"/log-receivers/entries/{eid}", json={
            "name": "核心交换机",
            "enabled": False,
            "strategy_id": 0,
            "device_id": 0,
            "entry_config": {"pipeline": {"filter": {"enabled": True, "rules": []}}},
        })
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "核心交换机"
        assert body["enabled"] is False
        assert body["strategy_id"] is None  # 0 归一化为跟随渠道
        assert body["auto_created"] is False  # 手工配置过即视为已管理
        # 同进程缓存已失效
        assert (rid, "1.1.1.1") not in entry_registry._cache

    def test_update_with_strategy_binding(self):
        rid = _seed_receiver()
        db = _TestSessionLocal()
        try:
            st = ParseStrategy(strategy_name="青藤策略", device_type="qingteng_wanxiang", config="{}")
            db.add(st)
            db.commit()
            sid = st.id
        finally:
            db.close()
        eid = _seed_entry(rid=rid, ip="1.1.1.1")
        client = _build_client()
        res = client.put(f"/log-receivers/entries/{eid}", json={"strategy_id": sid})
        assert res.status_code == 200
        assert res.json()["strategy_id"] == sid
        # 策略不存在 → 404
        res2 = client.put(f"/log-receivers/entries/{eid}", json={"strategy_id": 99999})
        assert res2.status_code == 404

    def test_delete_and_batch_delete(self):
        rid = _seed_receiver()
        e1 = _seed_entry(rid=rid, ip="1.1.1.1")
        e2 = _seed_entry(rid=rid, ip="2.2.2.2")
        e3 = _seed_entry(rid=rid, ip="3.3.3.3")
        client = _build_client()
        assert client.delete(f"/log-receivers/entries/{e1}").status_code == 204
        res = client.post(f"/log-receivers/{rid}/entries/batch-delete", json={"ids": [e2, e3]})
        assert res.status_code == 200
        assert res.json()["deleted"] == 2
        db = _TestSessionLocal()
        try:
            assert db.query(LogSourceEntry).filter_by(receiver_id=rid).count() == 0
        finally:
            db.close()
        # 删除后缓存已失效：再 resolve 按发现开关自动重建（库中重新出现该来源条目）
        got = entry_registry.resolve(rid, "1.1.1.1", _receiver(rid))
        assert got is not None and got["enabled"] is True  # 全新自动条目（enabled 默认开）
        db = _TestSessionLocal()
        try:
            assert db.query(LogSourceEntry).filter_by(receiver_id=rid).count() == 1
        finally:
            db.close()

    def test_receiver_list_contains_entries_count(self):
        rid = _seed_receiver()
        _seed_entry(rid=rid, ip="1.1.1.1")
        _seed_entry(rid=rid, ip="2.2.2.2")
        pull_rid = _seed_receiver(rid=2, protocol="kafka")
        client = _build_client()
        res = client.get("/log-receivers")
        items = {r["id"]: r for r in res.json()}
        assert items[rid]["entries_count"] == 2
        assert items[rid]["entry_discovery"] is True
        assert items[pull_rid]["entries_count"] == 0  # 拉取型恒 0
        assert items[pull_rid]["entry_discovery"] is False


# ============ 全局数据源条目页（跨接收器列表 / 详情 / 三态状态） ============
def _seed_receive_log(rid, ip, status="success", when=None):
    db = _TestSessionLocal()
    try:
        rec = DeviceReceiveLog(
            receiver_id=rid, device_name="d", protocol="syslog",
            raw_data="{}", source_ip=ip, parse_status=status,
            received_at=when or datetime.now(),
        )
        db.add(rec)
        db.commit()
        return rec.id
    finally:
        db.close()


def _seed_strategy(name="青藤模板"):
    db = _TestSessionLocal()
    try:
        st = ParseStrategy(strategy_name=name, device_type="qingteng_wanxiang", config="{}")
        db.add(st)
        db.commit()
        return st.id
    finally:
        db.close()


class TestGlobalEntryPage:
    def test_list_with_receiver_filter_and_search(self):
        r1 = _seed_receiver()
        r2 = _seed_receiver(rid=2)
        _seed_entry(rid=r1, ip="1.1.1.1", name="核心交换机")
        _seed_entry(rid=r1, ip="2.2.2.2")
        _seed_entry(rid=r2, ip="3.3.3.3")
        client = _build_client()
        res = client.get("/log-receivers/entries")
        assert res.status_code == 200
        assert res.json()["total"] == 3
        # 按接收器过滤
        res1 = client.get(f"/log-receivers/entries?receiver_id={r1}")
        assert res1.json()["total"] == 2
        # 搜索（IP / 名称）
        res2 = client.get("/log-receivers/entries?search=核心交换")
        assert res2.json()["total"] == 1
        assert res2.json()["items"][0]["source_ip"] == "1.1.1.1"

    def test_three_state_status_and_today_stats(self):
        rid = _seed_receiver()
        # pending：自动发现、未绑设备/模板
        e_pending = _seed_entry(rid=rid, ip="1.1.1.1", auto_created=1)
        # active：已绑定模板
        sid = _seed_strategy()
        e_active = _seed_entry(rid=rid, ip="2.2.2.2", strategy_id=sid)
        # parse_error：今日有接收但全部失败
        e_error = _seed_entry(rid=rid, ip="3.3.3.3", auto_created=0)
        _seed_receive_log(rid, "3.3.3.3", status="fail")
        _seed_receive_log(rid, "3.3.3.3", status="unknown")
        # disabled：停用
        e_off = _seed_entry(rid=rid, ip="4.4.4.4", enabled=0)
        # active 但今日有成功解析（today_parsed 计 success+partial）
        _seed_receive_log(rid, "2.2.2.2", status="partial")

        client = _build_client()
        res = client.get("/log-receivers/entries?page_size=50")
        rows = {r["id"]: r for r in res.json()["items"]}
        assert rows[e_pending]["status"] == "pending"
        assert rows[e_active]["status"] == "active"
        assert rows[e_error]["status"] == "parse_error"
        assert rows[e_off]["status"] == "disabled"
        # 今日统计：3.3.3.3 收 2 解析成功 0 失败 2；2.2.2.2 收 1 成功 1 失败 0
        assert rows[e_error]["today_received"] == 2
        assert rows[e_error]["today_parsed"] == 0
        assert rows[e_error]["today_failed"] == 2
        assert rows[e_active]["today_parsed"] == 1
        assert rows[e_active]["today_failed"] == 0
        # 状态计数卡片：与状态判定同口径
        assert res.json()["status_counts"] == {
            "pending": 1, "active": 1, "parse_error": 1, "disabled": 1,
        }
        # 状态筛选
        res2 = client.get("/log-receivers/entries?status=parse_error")
        assert res2.json()["total"] == 1
        assert res2.json()["items"][0]["id"] == e_error

    def test_parse_error_with_partial_failures_and_received_excluded(self):
        """今日失败>0 即解析异常（即使另有成功）；received 中间态行不计入今日统计。"""
        rid = _seed_receiver()
        sid = _seed_strategy()
        e = _seed_entry(rid=rid, ip="5.5.5.5", strategy_id=sid, auto_created=0)
        _seed_receive_log(rid, "5.5.5.5", status="success")
        _seed_receive_log(rid, "5.5.5.5", status="fail")
        _seed_receive_log(rid, "5.5.5.5", status="received")  # 中间态行不计

        client = _build_client()
        res = client.get("/log-receivers/entries")
        row = res.json()["items"][0]
        assert row["id"] == e
        # 今日 = 终态行数（success+fail），排除 received：收 2 成功 1 失败 1
        assert row["today_received"] == 2
        assert row["today_parsed"] == 1
        assert row["today_failed"] == 1
        # 部分失败同样计入解析异常
        assert row["status"] == "parse_error"
        assert res.json()["status_counts"]["parse_error"] == 1

    def test_bound_strategy_resolution_chain(self):
        # 条目固定 > 接收器默认 > 自动匹配
        sid_entry = _seed_strategy("条目模板")
        sid_recv = _seed_strategy("接收器模板")
        rid = _seed_receiver()
        db = _TestSessionLocal()
        try:
            db.query(LogReceiver).filter(LogReceiver.id == rid).update({"strategy_id": sid_recv})
            db.commit()
        finally:
            db.close()
        e1 = _seed_entry(rid=rid, ip="1.1.1.1", strategy_id=sid_entry)
        e2 = _seed_entry(rid=rid, ip="2.2.2.2")
        client = _build_client()
        rows = {r["id"]: r for r in client.get("/log-receivers/entries").json()["items"]}
        assert rows[e1]["bound_strategy_source"] == "entry"
        assert rows[e1]["bound_strategy_name"] == "条目模板"
        assert rows[e2]["bound_strategy_source"] == "receiver"
        assert rows[e2]["bound_strategy_name"] == "接收器模板"
        # 接收器也不固定 → 自动匹配
        db = _TestSessionLocal()
        try:
            db.query(LogReceiver).filter(LogReceiver.id == rid).update({"strategy_id": None})
            db.commit()
        finally:
            db.close()
        rows2 = {r["id"]: r for r in client.get("/log-receivers/entries").json()["items"]}
        assert rows2[e2]["bound_strategy_source"] == "auto"
        assert rows2[e2]["bound_strategy_id"] is None

    def test_entry_detail(self):
        rid = _seed_receiver()
        dev_id = _seed_device(ip="9.9.9.9", name="边界防火墙")
        eid = _seed_entry(rid=rid, ip="9.9.9.9", device_id=dev_id, name="边界防火墙")
        client = _build_client()
        res = client.get(f"/log-receivers/entries/{eid}")
        assert res.status_code == 200
        body = res.json()
        assert body["source_ip"] == "9.9.9.9"
        assert body["device_name"] == "边界防火墙"
        assert body["device_type"] == "edr"
        assert body["receiver_name"] == f"r{rid}"
        # 404：条目不存在
        assert client.get("/log-receivers/entries/99999").status_code == 404

    def test_receiver_list_contains_today_stats(self):
        rid = _seed_receiver()
        db = _TestSessionLocal()
        try:
            now_hour = datetime.now().strftime("%Y-%m-%dT%H")
            db.add(DeviceReceiveMetric(
                stat_hour=now_hour, receiver_id=rid, receiver_name=f"r{rid}",
                total_count=10, success_count=7, partial_count=1, fail_count=2,
            ))
            db.commit()
        finally:
            db.close()
        client = _build_client()
        res = client.get("/log-receivers")
        row = next(r for r in res.json() if r["id"] == rid)
        assert row["today_total"] == 10
        assert row["today_fail"] == 2


# ============ 接收器设备归属分层：监听型可空 / 拉取型必填 ============
class TestReceiverDeviceOwnership:
    def test_create_listen_receiver_without_device(self):
        """监听型（syslog）不绑定设备可创建：归属交给来源条目按 IP 自动绑定。"""
        client = _build_client()
        res = client.post("/log-receivers", json={
            "name": "syslog-9514", "protocol": "syslog",
            "device_id": None, "syslog_port": 9514, "enabled": False,
        })
        assert res.status_code == 201
        body = res.json()
        assert body["device_id"] is None
        assert body["device_name"] == ""

    def test_create_pull_receiver_requires_device(self):
        """拉取型（kafka）缺 device_id → 422（无来源 IP 可供条目归属）。"""
        client = _build_client()
        res = client.post("/log-receivers", json={
            "name": "kafka-soc", "protocol": "kafka",
            "kafka_bootstrap": "localhost:9092", "kafka_topic": "alerts",
            "device_id": None, "enabled": False,
        })
        assert res.status_code == 422

    def test_update_listen_receiver_can_clear_device(self):
        """监听型已有归属也可清空（改为按来源条目归属）。"""
        dev_id = _seed_device("9.9.9.9", name="旧设备")
        db = _TestSessionLocal()
        try:
            rec = LogReceiver(device_id=dev_id, device_name="旧设备",
                              name="r1", protocol="syslog", syslog_port=514)
            db.add(rec)
            db.commit()
            rid = rec.id
        finally:
            db.close()
        client = _build_client()
        res = client.put(f"/log-receivers/{rid}", json={
            "name": "r1", "protocol": "syslog", "device_id": None,
            "syslog_port": 514, "enabled": False,
        })
        assert res.status_code == 200
        assert res.json()["device_id"] is None
        assert res.json()["device_name"] == ""
