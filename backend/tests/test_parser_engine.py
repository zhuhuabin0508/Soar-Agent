"""解析引擎单元测试。

验证：给定策略 JSON 和原始日志 JSON，引擎能独立运行解析并返回结果，不依赖数据库。
运行：docker exec soar-backend-dev python -m pytest /app/tests/test_parser_engine.py -v
（或直接 python tests/test_parser_engine.py）
"""
import json
import sys

sys.path.insert(0, "/app")

from app.engine.parser_engine import ParseEngine
from app.engine.strategy_loader import StrategyLoader

# ------------------------------------------------------------------
# 测试用策略（Sangfor XDR 精简版）
# ------------------------------------------------------------------
STRATEGY = {
    "id": 1,
    "strategy_name": "Sangfor XDR 安全告警 v1.30",
    "device_type": "sangfor_xdr",
    "version": "1.30",
    "status": "enabled",
    "config": {
        "strategy_name": "Sangfor XDR 安全告警 v1.30",
        "device_type": "sangfor_xdr",
        "version": "1.30",
        "route_rules": {"match_type": "exact", "match_field": "type", "match_value": "security_alert"},
        "outer_wrapper": {
            "data_path": "data",
            "header_fields": ["sendTime", "tenant", "type", "version", "alertType"],
            "uuid_source": "data.uuId",
        },
        "field_mappings": [
            {"source": "uuId", "target": "uuid", "type": "string", "required": True},
            {"source": "riskLevel", "target": "risk_level", "type": "enum_int",
             "enum_map": "RISK_LEVEL", "enum_target": "risk_level_name"},
            {"source": "srcIp", "target": "src_ip", "type": "json_array_to_string"},
            {"source": "occurTimestamp", "target": "occur_timestamp", "type": "timestamp_to_datetime",
             "timezone_field": "timeRegion"},
            {"source": "timeRegion", "target": "time_region", "type": "string"},
            {"source": "srcCountry", "target": "src_country", "type": "string"},
            {"source": "attckTechnique", "target": "attck_technique", "type": "json_array_to_string"},
            {"source": "hostIp", "target": "host_ip", "type": "json_array_to_string"},
            {"source": "riskTag", "target": "risk_tag", "type": "comma_split_to_json"},
            {"source": "severity", "target": "severity", "type": "int"},
        ],
        "enum_maps": {
            "RISK_LEVEL": {"0": "严重", "1": "高危", "2": "中危", "3": "低危", "4": "信息", "5": "未知"},
        },
        "validations": [
            {"field": "uuid", "rule": "regex", "pattern": r"^alert-\d{10}-\w{5}$", "severity": "warning"},
            {"field": "src_ip", "rule": "ip_list_valid", "severity": "warning"},
            {"field": "risk_level", "rule": "range", "min": 0, "max": 5, "severity": "warning"},
            {"field": "severity", "rule": "range", "min": 0, "max": 100, "severity": "warning"},
        ],
        "extension_fields": ["analysisInfo", "containerName", "logCount", "responseAction"],
    },
}

# 测试用原始告警
RAW_ALERT = {
    "sendTime": "2026-08-26 10:00:00",
    "tenant": "default",
    "type": "security_alert",
    "version": "1.30",
    "alertType": "host",
    "data": {
        "uuId": "alert-1787700000-abcde",
        "riskLevel": 1,
        "srcIp": ["1.2.3.4", "5.6.7.8"],
        "occurTimestamp": 1787700000,
        "timeRegion": "GMT+08:00",
        "srcCountry": "中国",
        "attckTechnique": ["T1566", "T1566.001"],
        "hostIp": ["192.168.1.100"],
        "riskTag": "恶意IP,暴力破解",
        "severity": 80,
        "analysisInfo": "检测到暴力破解行为",
        "containerName": "",
        "logCount": 12,
        "responseAction": "block",
    },
}


def test_route_match_and_parse():
    """策略路由命中 + 完整解析（success）。"""
    loader = StrategyLoader(strategies=[STRATEGY])
    engine = ParseEngine(loader=loader, sink=None)
    result = engine.parse_one(RAW_ALERT)

    assert result.status == "success", f"期望 success，实际 {result.status}，警告: {result.warnings}"
    assert result.strategy_id == 1
    assert result.uuid == "alert-1787700000-abcde"
    f = result.fields
    # 类型转换
    assert f["src_ip"] == json.dumps(["1.2.3.4", "5.6.7.8"], ensure_ascii=False)
    assert f["risk_tag"] == json.dumps(["恶意IP", "暴力破解"], ensure_ascii=False)
    assert f["severity"] == 80
    # 枚举翻译：1 → 高危
    assert f["risk_level"] == 1
    assert f["risk_level_name"] == "高危"
    # 时间戳转换（北京时间 naive）
    assert f["occur_timestamp"] is not None
    assert f["occur_timestamp"].year == 2026
    # 扩展归档：header + extension_fields
    ext = json.loads(f["extensions"])
    assert ext["tenant"] == "default"
    assert ext["type"] == "security_alert"
    assert ext["analysisInfo"] == "检测到暴力破解行为"
    assert ext["logCount"] == 12
    assert ext["responseAction"] == "block"
    # 系统字段
    assert f["device_type"] == "sangfor_xdr"
    assert json.loads(f["raw_data"])["type"] == "security_alert"
    print("PASS: 路由命中 + 完整解析")


def test_no_strategy_matched():
    """无匹配策略 → fail + no_strategy_matched。"""
    loader = StrategyLoader(strategies=[STRATEGY])
    engine = ParseEngine(loader=loader, sink=None)
    result = engine.parse_one({"type": "unknown_event", "data": {}})
    assert result.status == "fail"
    assert result.error_type == "no_strategy_matched"
    print("PASS: 无匹配策略")


def test_validation_warnings_partial():
    """校验失败不阻断 → partial + parse_warnings。"""
    raw = json.loads(json.dumps(RAW_ALERT))
    raw["data"]["uuId"] = "bad-uuid"           # regex 不过
    raw["data"]["srcIp"] = ["not-an-ip"]       # ip_list_valid 不过
    raw["data"]["severity"] = 999              # range 不过

    loader = StrategyLoader(strategies=[STRATEGY])
    engine = ParseEngine(loader=loader, sink=None)
    result = engine.parse_one(raw)

    assert result.status == "partial"
    rules = {w["rule"] for w in result.warnings}
    assert "regex" in rules
    assert "ip_list_valid" in rules
    assert "range" in rules
    # 字段仍解析入库
    assert result.fields["severity"] == 999
    assert json.loads(result.fields["parse_warnings"]) == result.warnings
    print(f"PASS: 校验警告降级 partial（{len(result.warnings)} 条警告）")


def test_required_missing_warning():
    """required 源字段缺失 → 警告。"""
    raw = json.loads(json.dumps(RAW_ALERT))
    del raw["data"]["uuId"]

    loader = StrategyLoader(strategies=[STRATEGY])
    engine = ParseEngine(loader=loader, sink=None)
    result = engine.parse_one(raw)

    assert result.status == "partial"
    assert any("uuId" in w.get("source", "") for w in result.warnings)
    print("PASS: required 缺失警告")


def test_timestamp_timezone():
    """timestamp_to_datetime 按 timezone_field 换算（GMT+00:00 → 北京时间 +8h）。"""
    raw = json.loads(json.dumps(RAW_ALERT))
    raw["data"]["timeRegion"] = "GMT+00:00"
    raw["data"]["occurTimestamp"] = 0  # UTC 1970-01-01 00:00 → 北京 08:00

    loader = StrategyLoader(strategies=[STRATEGY])
    engine = ParseEngine(loader=loader, sink=None)
    result = engine.parse_one(raw)

    ts = result.fields["occur_timestamp"]
    assert ts.hour == 8, f"期望北京 08:00，实际 {ts}"
    print("PASS: 时区换算（UTC → 北京 +8h）")


def test_version_priority():
    """多策略命中时取 version 最新。"""
    older = json.loads(json.dumps(STRATEGY))
    older["id"] = 2
    older["version"] = "1.10"
    older["config"]["version"] = "1.10"

    loader = StrategyLoader(strategies=[older, STRATEGY])
    matched = loader.match(RAW_ALERT)
    assert matched["id"] == STRATEGY["id"], "应取 version 1.30 的策略"
    print("PASS: 多命中取最新版本")


def test_batch_process_with_memory_sink():
    """批量处理 + 内存 sink（验证依赖注入可脱离数据库运行）。"""
    class MemorySink:
        def __init__(self):
            self.alerts = []
            self.errors = []
            self.metrics = []

        def save_alert(self, fields):
            if any(a["uuid"] == fields["uuid"] for a in self.alerts):
                return "duplicate"
            self.alerts.append(fields)
            return "inserted"

        def save_error(self, raw_data, error_type, error_msg, uuid=None, strategy_id=None):
            self.errors.append({"error_type": error_type, "uuid": uuid})

        def record_metrics(self, stat_hour, strategy_id, strategy_name, status, parse_ms):
            self.metrics.append({"hour": stat_hour, "status": status})

    sink = MemorySink()
    loader = StrategyLoader(strategies=[STRATEGY])
    engine = ParseEngine(loader=loader, sink=sink)

    batch = [
        RAW_ALERT,                                            # success
        {"type": "unknown_event"},                            # no_strategy_matched
        "not-a-dict",                                         # json_parse_failed
    ]
    stats = engine.process(batch)

    assert stats["total"] == 3
    assert stats["success"] == 1
    assert stats["fail"] == 2
    assert len(sink.alerts) == 1
    assert {e["error_type"] for e in sink.errors} == {"no_strategy_matched", "json_parse_failed"}
    assert any(m["status"] == "success" for m in sink.metrics)

    # 幂等：重复 uuid 再推一次 → duplicate
    stats2 = engine.process([RAW_ALERT])
    assert stats2["duplicates"] == 1
    print("PASS: 批量处理 + 内存 sink + 幂等去重")


def test_regex_route_match():
    """regex 路由匹配。"""
    strategy = json.loads(json.dumps(STRATEGY))
    strategy["config"]["route_rules"] = {
        "match_type": "regex", "match_field": "type", "match_value": "security_.*",
    }
    loader = StrategyLoader(strategies=[strategy])
    engine = ParseEngine(loader=loader, sink=None)
    result = engine.parse_one(RAW_ALERT)
    assert result.status in ("success", "partial")
    print("PASS: regex 路由匹配")


if __name__ == "__main__":
    test_route_match_and_parse()
    test_no_strategy_matched()
    test_validation_warnings_partial()
    test_required_missing_warning()
    test_timestamp_timezone()
    test_version_priority()
    test_batch_process_with_memory_sink()
    test_regex_route_match()
    print("\n全部测试通过 ✓")
