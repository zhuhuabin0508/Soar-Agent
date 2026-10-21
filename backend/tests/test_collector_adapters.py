"""新增输入适配器单测（file_tail/rest_api/jdbc/snmp_trap/netflow/pcap，不依赖 DB）。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_collector_adapters.py -v
"""
import json
import os
import struct
import sys
import tempfile
import threading
import time
from datetime import datetime

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.core.log_receiver_manager import adapter_registry
from app.core.log_receiver_manager.adapters.file_tail_adapter import FileTailAdapter
from app.core.log_receiver_manager.adapters.jdbc_adapter import JdbcAdapter, _row_value
from app.core.log_receiver_manager.adapters.netflow_adapter import NetFlowAdapter, _parse_v5
from app.core.log_receiver_manager.adapters.pcap_adapter import PcapAdapter
from app.core.log_receiver_manager.adapters.rest_api_adapter import RestApiAdapter, _dig, _record_to_text
from app.core.log_receiver_manager.adapters.snmp_trap_adapter import SnmpTrapAdapter


class _FakeCtx:
    """轻量适配器测试句柄：publish 只入列表，不触碰总线/DB。"""

    def __init__(self, receiver: dict):
        self.receiver_id = 0
        self.generation = 1
        self.stop_event = threading.Event()
        self.receiver = receiver
        self.runtime_ref = {}
        self.published: list[tuple] = []
        self.statuses: list[tuple] = []

    def signal_ready(self, success, error=""):
        self.ready = (success, error)

    def set_status(self, status, error=None):
        self.statuses.append((status, error))

    def mark_start_failed(self, error):
        self.set_status("start_failed", error)

    def publish(self, raw, source_ip=None, meta=None, blocking=False, timeout=5.0):
        self.published.append((raw, source_ip, meta))
        return True


# ----------------------------------------------------------------------
# 注册表：8 种源类型全量注册 + 必填键元数据
# ----------------------------------------------------------------------
class TestNewAdaptersRegistered:
    def test_all_source_types(self):
        names = set(adapter_registry.names())
        assert names >= {
            "syslog", "kafka", "jdbc", "snmp_trap",
            "netflow", "rest_api", "pcap", "file_tail",
        }

    def test_source_types_metadata_contains_required_keys(self):
        meta = {t["value"]: t for t in adapter_registry.source_types()}
        assert ("url", "数据库连接串（SQLAlchemy URL）") in meta["jdbc"]["required_config_keys"]
        assert ("base_url", "接口基础地址") in meta["rest_api"]["required_config_keys"]
        assert ("path", "文件路径") in meta["file_tail"]["required_config_keys"]

    def test_validate_config_missing_keys_chinese(self):
        errs = adapter_registry.validate_config("jdbc", {})
        assert any("query" in e for e in errs)
        errs = adapter_registry.validate_config("rest_api", {})
        assert any("base_url" in e for e in errs)
        assert adapter_registry.validate_config("file_tail", {"path": "/tmp/x.log"}) == []


# ----------------------------------------------------------------------
# FileTail：增量跟踪 / from_beginning / 轮转重读 / 背压不丢行
# ----------------------------------------------------------------------
class TestFileTailAdapter:
    def _run_until(self, ctx, fn, timeout=5.0):
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        deadline = time.time() + timeout
        while time.time() < deadline and not ctx.stop_event.is_set():
            time.sleep(0.05)
        ctx.stop_event.set()
        t.join(timeout=3)

    def test_tail_incremental(self, monkeypatch):
        from app.core.log_receiver_manager.adapters._polling import CursorStore
        monkeypatch.setattr(CursorStore, "_flush_to_db", lambda self, value: None)
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8") as f:
            fpath = f.name
            f.write("line1\nline2\n")
        try:
            ctx = _FakeCtx({
                "protocol": "file_tail",
                "adapter_config": {"path": fpath, "from_beginning": True, "poll_interval_seconds": 0.2},
            })
            self._run_until(ctx, lambda: FileTailAdapter(ctx).run())
            lines = [raw for raw, _, _ in ctx.published]
            assert lines == ["line1", "line2"]
        finally:
            os.unlink(fpath)

    def test_tail_appends_and_rotation(self, monkeypatch):
        from app.core.log_receiver_manager.adapters._polling import CursorStore
        monkeypatch.setattr(CursorStore, "_flush_to_db", lambda self, value: None)
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8") as f:
            fpath = f.name
            f.write("a\n")
        try:
            ctx = _FakeCtx({
                "protocol": "file_tail",
                "adapter_config": {"path": fpath, "from_beginning": True, "poll_interval_seconds": 0.2},
            })
            adapter = FileTailAdapter(ctx)
            t = threading.Thread(target=adapter.run, daemon=True)
            t.start()
            time.sleep(0.6)  # 读到 a
            with open(fpath, "a", encoding="utf-8") as f:
                f.write("b\n")
            time.sleep(0.6)  # 增量读到 b
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("c\n")  # truncate：offset > size → 从头重读
            time.sleep(0.8)
            ctx.stop_event.set()
            t.join(timeout=3)
            lines = [raw for raw, _, _ in ctx.published]
            assert lines == ["a", "b", "c"]
        finally:
            os.unlink(fpath)

    def test_publish_failure_keeps_offset(self, monkeypatch):
        """总线满（publish=False）不推进 offset，恢复后下轮重读该行（不丢数据）。"""
        from app.core.log_receiver_manager.adapters._polling import CursorStore
        monkeypatch.setattr(CursorStore, "_flush_to_db", lambda self, value: None)
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8") as f:
            fpath = f.name
            f.write("x1\n")
        try:
            ctx = _FakeCtx({
                "protocol": "file_tail",
                "adapter_config": {"path": fpath, "from_beginning": True, "poll_interval_seconds": 0.2},
            })
            fail = {"flag": False}
            orig_publish = ctx.publish

            def flaky_publish(raw, **kw):
                if fail["flag"]:
                    return False  # 模拟队列满
                return orig_publish(raw, **kw)

            ctx.publish = flaky_publish
            adapter = FileTailAdapter(ctx)
            t = threading.Thread(target=adapter.run, daemon=True)
            t.start()
            time.sleep(0.5)              # 读到 x1
            fail["flag"] = True
            with open(fpath, "a", encoding="utf-8") as f:
                f.write("x2\n")          # 投递失败的行
            time.sleep(0.6)              # 若轮：publish=False → offset 不推进
            fail["flag"] = False
            time.sleep(0.8)              # 恢复：从保留的 offset 重读 x2 → 成功
            ctx.stop_event.set()
            t.join(timeout=3)
            lines = [raw for raw, _, _ in ctx.published]
            assert lines == ["x1", "x2"]
        finally:
            os.unlink(fpath)


# ----------------------------------------------------------------------
# RestApi：records_path 点路径提取 / 游标推进
# ----------------------------------------------------------------------
class TestRestApiAdapter:
    def test_dig_nested_path(self):
        data = {"data": {"list": [{"id": 1}]}, "meta": {"next_cursor": "abc"}}
        assert _dig(data, "data.list") == [{"id": 1}]
        assert _dig(data, "meta.next_cursor") == "abc"
        assert _dig(data, "nope.nope") is None
        assert _dig(data, "") == data

    def test_record_to_text(self):
        assert _record_to_text({"a": 1}) == '{"a": 1}'
        assert _record_to_text("plain") == "plain"
        assert _record_to_text(None) is None

    def test_cursor_advance_semantics(self, monkeypatch):
        """cursor 分页：游标推进持久化，无更多数据时停止。"""
        responses = [
            {"data": {"items": [{"id": 1}]}, "meta": {"next_cursor": "c2"}},
            {"data": {"items": [{"id": 2}]}, "meta": {"next_cursor": "c3"}},
            {"data": {"items": []}, "meta": {"next_cursor": None}},
        ]
        calls = {"n": 0}
        saved_cursors = []

        class _Resp:
            def __init__(self, payload):
                self.payload = payload
                self.status_code = 200

            def json(self):
                return self.payload

        class _FakeHttpx:
            class Client:
                def __init__(self, **kw):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def request(self, method, url, **kw):
                    idx = min(calls["n"], len(responses) - 1)
                    calls["n"] += 1
                    return _Resp(responses[idx])

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "httpx":
                return _FakeHttpx
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        ctx = _FakeCtx({
            "protocol": "rest_api",
            "adapter_config": {
                "base_url": "http://x", "records_path": "data.items",
                "pagination": "cursor", "cursor_path": "meta.next_cursor",
                "poll_interval_seconds": 30,
            },
        })
        adapter = RestApiAdapter(ctx)
        adapter._cursor = type("_C", (), {
            "load": lambda s: None,
            "save": lambda s, v, force=False: saved_cursors.append(v),
        })()
        adapter._poll_once(ctx.receiver["adapter_config"])
        assert [raw for raw, _, _ in ctx.published] == ['{"id": 1}', '{"id": 2}']
        assert saved_cursors[-1] == "c3"


# ----------------------------------------------------------------------
# Jdbc：行值序列化
# ----------------------------------------------------------------------
class TestJdbcAdapter:
    def test_row_value_types(self):
        assert _row_value(datetime(2026, 10, 8, 12, 0, 0)) == "2026-10-08T12:00:00"
        assert _row_value(b"hello") == "hello"
        assert _row_value(None) is None
        assert _row_value(3.14) == 3.14
        assert _row_value(object())  # 兜底 str()

    def test_registered_and_required(self):
        assert adapter_registry.get("jdbc") is JdbcAdapter


# ----------------------------------------------------------------------
# NetFlow：v5 手解 + v9 模板/数据解析
# ----------------------------------------------------------------------
def _build_v5_packet(src="10.0.0.1", dst="10.0.0.2", sport=1234, dport=80):
    import socket as _s

    header = struct.pack(
        "!HHIIIIBBH", 5, 1, 1000, 1760000000, 0, 42, 0, 0, 0,
    )

    def _u32(ip: str) -> int:
        return struct.unpack("!I", _s.inet_aton(ip))[0]

    record = struct.pack(
        "!IIIHHIIIIHHBBBBHHBBH",
        _u32(src), _u32(dst), _u32("0.0.0.0"),
        1, 2, 10, 512, 100, 200, sport, dport, 0, 0x12, 6, 0, 100, 200, 24, 24, 0,
    )
    return header + record


class TestNetFlowV5:
    def test_parse_v5_fields(self):
        flows = _parse_v5(_build_v5_packet())
        assert len(flows) == 1
        f = flows[0]
        assert f["src_ip"] == "10.0.0.1" and f["dst_ip"] == "10.0.0.2"
        assert f["src_port"] == 1234 and f["dst_port"] == 80
        assert f["protocol"] == 6 and f["packets"] == 10 and f["octets"] == 512
        assert f["tcp_flags"] == 0x12

    def test_parse_v5_short_packet_raises(self):
        with pytest.raises(ValueError):
            _parse_v5(b"\x00\x05\x00\x01")


def _build_v9_template_packet(template_id=1000):
    # 头 20B：version=9, count=1, sysuptime, unix_secs, seq, source_id
    head = struct.pack("!HHIIII", 9, 1, 0, 1760000000, 0, 1)
    # 模板集合：id=0；模板：template_id, 4 字段 (src_ip 8/4)(dst_ip 12/4)(sport 7/2)(dport 11/2)
    body = struct.pack("!HH", template_id, 4) + struct.pack("!HH", 8, 4) + \
        struct.pack("!HH", 12, 4) + struct.pack("!HH", 7, 2) + struct.pack("!HH", 11, 2)
    flowset = struct.pack("!HH", 0, 4 + len(body)) + body
    return head + flowset


def _build_v9_data_packet(template_id=1000, src="10.1.1.1", dst="10.1.1.2", sport=5555, dport=443):
    import socket as _s

    head = struct.pack("!HHIIII", 9, 1, 0, 1760000001, 1, 1)
    rec = _s.inet_aton(src) + _s.inet_aton(dst) + struct.pack("!HH", sport, dport)
    flowset = struct.pack("!HH", template_id, 4 + len(rec)) + rec
    return head + flowset


class TestNetFlowV9:
    def test_template_then_data(self):
        adapter = NetFlowAdapter(_FakeCtx({"protocol": "netflow", "adapter_config": {}}))
        # 先模板包（建立缓存），再数据包
        assert adapter._parse_packet(_build_v9_template_packet(), {"5", "9", "ipfix"}, "1.2.3.4") == []
        flows = adapter._parse_packet(_build_v9_data_packet(), {"5", "9", "ipfix"}, "1.2.3.4")
        assert len(flows) == 1
        assert flows[0]["src_ip"] == "10.1.1.1"
        assert flows[0]["dst_ip"] == "10.1.1.2"
        assert flows[0]["src_port"] == 5555 and flows[0]["dst_port"] == 443

    def test_data_without_template_dropped(self):
        adapter = NetFlowAdapter(_FakeCtx({"protocol": "netflow", "adapter_config": {}}))
        assert adapter._parse_packet(_build_v9_data_packet(), {"9"}, "9.9.9.9") == []

    def test_version_not_enabled(self):
        adapter = NetFlowAdapter(_FakeCtx({"protocol": "netflow", "adapter_config": {}}))
        assert adapter._parse_packet(_build_v5_packet(), {"9"}, "1.1.1.1") == []

    def test_ipfix_data_with_template(self):
        adapter = NetFlowAdapter(_FakeCtx({"protocol": "netflow", "adapter_config": {}}))
        # IPFIX 复用 v9 集合结构：version=10，头部 offset2-4 为整包长度
        tpl = bytearray(_build_v9_template_packet())
        struct.pack_into("!H", tpl, 0, 10)   # version=10
        struct.pack_into("!H", tpl, 2, len(tpl))
        assert adapter._parse_packet(bytes(tpl), {"5", "9", "ipfix"}, "1.2.3.4") == []
        data = bytearray(_build_v9_data_packet())
        struct.pack_into("!H", data, 0, 10)
        struct.pack_into("!H", data, 2, len(data))
        flows = adapter._parse_packet(bytes(data), {"5", "9", "ipfix"}, "1.2.3.4")
        assert len(flows) == 1 and flows[0]["src_ip"] == "10.1.1.1"


# ----------------------------------------------------------------------
# Pcap / SnmpTrap：依赖可选，未安装跳过
# ----------------------------------------------------------------------
class TestPcapAdapter:
    def test_registered(self):
        assert adapter_registry.get("pcap") is PcapAdapter

    def test_summarize(self):
        pytest.importorskip("scapy")
        from scapy.layers.inet import IP, TCP

        pkt = IP(src="1.1.1.1", dst="2.2.2.2") / TCP(sport=1111, dport=22, flags="S")
        rec = PcapAdapter._summarize(pkt, include_payload=True)
        assert rec["src_ip"] == "1.1.1.1" and rec["dst_ip"] == "2.2.2.2"
        assert rec["src_port"] == 1111 and rec["dst_port"] == 22
        assert rec["tcp_flags"] == "S"


class TestSnmpTrapAdapter:
    def test_registered(self):
        assert adapter_registry.get("snmp_trap") is SnmpTrapAdapter
