"""采集子系统预处理器单测：青藤样例 / JSON / 纯文本（与重构前行为逐字段对齐）。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_collector_preprocessors.py -v
"""
import json
import os
import sys

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.log_receiver_manager import _coerce_payload, parse_qingteng_syslog
from app.core.log_receiver_manager.pipeline.preprocessors import (
    DEFAULT_PREPROCESSOR_CHAIN,
    run_preprocessor_chain,
)

# 青藤万相 Syslog 真实样例（account_change 功能日志；datatype/datatime 等键值均为带引号格式）
QT_SAMPLE = (
    '<134>Aug 26 12:00:00 node01 qingteng_probe: datatype="account_change" '
    'datatime="2026-08-26 12:00:00" agent_id="agent-001" severity="4" '
    'detail.node_name="web01" detail.operator="admin" detail.result="success"'
)

# 告警类样例（含数组值与转义）
QT_ALERT_SAMPLE = (
    '<134>Aug 26 12:01:00 node01 qingteng_probe: datatype="host_alarm" '
    'datatime="2026-08-26 12:01:00" agent_id="agent-002" severity="0" '
    'src_ip="10.0.0.1\\,10.0.0.2" dst_ip="192.168.1.1" event_name="test alarm"'
)


class TestQingtengPreprocessor:
    def test_recognizes_and_flattens(self):
        d = parse_qingteng_syslog(QT_SAMPLE)
        assert d is not None
        assert d["datatype"] == "account_change"
        assert d["datatime"] == "2026-08-26 12:00:00"
        assert d["agent_id"] == "agent-001"
        # detail.* 平坦化为 detail_xxx
        assert d["detail_node_name"] == "web01"
        assert d["detail_operator"] == "admin"
        # 派生字段
        assert d["__source"] == "qingteng_syslog"
        assert len(d["event_uuid"]) == 40
        assert d["datatime_raw"] == "2026-08-26 12:00:00"

    def test_severity_translated_to_system_risk_level(self):
        # 青藤 4=危急 → 系统 risk_level 0；0=信息 → 4
        d = parse_qingteng_syslog(QT_SAMPLE)
        assert d["severity"] == 0
        d2 = parse_qingteng_syslog(QT_ALERT_SAMPLE)
        assert d2["severity"] == 4

    def test_array_value_restored_as_json(self):
        d = parse_qingteng_syslog(QT_ALERT_SAMPLE)
        assert d["src_ip"] == json.dumps(["10.0.0.1", "10.0.0.2"], ensure_ascii=False)

    def test_rejects_non_qingteng(self):
        # 无 datatype= 的普通 syslog 不识别
        assert parse_qingteng_syslog("<134>Aug 26 12:00:00 fw1 attack detected") is None
        # 有 datatype 但无 datatime（结构判定不满足）不识别
        assert parse_qingteng_syslog('datatype=x foo="1"') is None
        # 空串
        assert parse_qingteng_syslog("") is None


class TestCoercePayloadChain:
    def test_json_priority(self):
        assert _coerce_payload('{"a": 1}') == {"a": 1}
        assert _coerce_payload('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]

    def test_qingteng_second(self):
        p = _coerce_payload(QT_SAMPLE)
        assert isinstance(p, dict) and p.get("__source") == "qingteng_syslog"

    def test_plain_fallback(self):
        p = _coerce_payload("just some text")
        assert p == {"message": "just some text", "raw": "just some text"}

    def test_default_chain_equivalent_to_coerce_payload(self):
        # 默认链 json → qingteng_syslog → plain_message 与 _coerce_payload 逐行为等价
        for raw in (QT_SAMPLE, QT_ALERT_SAMPLE, '{"k": [1,2]}', "plain text", "", "<134>fw1 x"):
            assert run_preprocessor_chain(DEFAULT_PREPROCESSOR_CHAIN, raw) == _coerce_payload(raw)

    def test_unknown_preprocessor_skipped(self):
        # 未注册的预处理器跳过且不影响链
        out = run_preprocessor_chain(["nope", "json"], '{"a":1}')
        assert out == {"a": 1}
