"""日志类型识别与路由（Classifier & Router）单元测试。

覆盖：
- 元数据直路由（source_type/device_vendor 别名命中，大小写不敏感）；
- 特征匹配（特异度降序返回候选列表，exists/not_exists 算子）；
- 候选回退（解析失败/路由级校验器拒绝/策略 severity=error 校验拒绝 → 下一候选）；
- 同设备类型多策略取版本最新；
- 旧版 route_rules 自动匹配兜底（YAML 未登记设备类型不受影响）；
- 全部失败 → unknown 兜底结果（error_type=unknown_log_type，uuid 尽力保留）；
- YAML 特征表：新增设备类型零改码、mtime 热加载、坏文件保留上次可用表、文件缺失空表。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_classifier.py -v
"""
import os
import sys
import tempfile

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.engine.classifier import (
    ERR_UNKNOWN_LOG_TYPE,
    ClassifierRouter,
    FeatureTable,
    LogClassifier,
    load_feature_table,
    reload_feature_table,
)
from app.engine.parser_engine import ParseEngine
from app.engine.strategy_loader import StrategyLoader


# ------------------------------------------------------------------
# 测试用策略构造（旧格式 config：route_rules + field_mappings，恒命中版/条件命中版）
# ------------------------------------------------------------------
def _strategy(sid, device_type, always_hit=True, version="1.0", validations=None):
    name = f"{device_type} 测试策略 v{version}"
    route = (
        {"match_type": "exact", "match_field": "", "match_value": ""}
        if always_hit
        else {"match_type": "exact", "match_field": "type", "match_value": "never_match_value"}
    )
    config = {
        "strategy_name": name,
        "device_type": device_type,
        "version": version,
        "route_rules": route,
        "outer_wrapper": {"data_path": "", "header_fields": [], "uuid_source": "event_uuid"},
        "field_mappings": [
            {"source": "event_name", "target": "alert_name", "type": "string"},
            {"source": "src_ip", "target": "src_ip", "type": "string"},
        ],
        "enum_maps": {},
        "validations": validations or [],
        "extension_fields": [],
    }
    return {
        "id": sid,
        "strategy_name": name,
        "device_type": device_type,
        "version": version,
        "status": "enabled",
        "config": config,
    }


def _table(entries, metadata_fields=None):
    """由 dict 构造特征匹配表（测试注入，不读文件）。"""
    data = {"device_types": entries}
    if metadata_fields:
        data["metadata_fields"] = metadata_fields
    return FeatureTable.from_dict(data)


def _router(strategies, entries, metadata_fields=None):
    loader = StrategyLoader(strategies=strategies)
    classifier = LogClassifier(_table(entries, metadata_fields))
    engine = ParseEngine(loader=loader, sink=None)
    return ClassifierRouter(loader, classifier=classifier), engine


# ============ 1. 元数据直路由 ============
class TestMetadataRoute:
    ENTRIES = [{
        "device_type": "sangfor_xdr",
        "specificity": 90,
        "metadata": {"source_type": ["sangfor", "深信服"], "device_vendor": ["sangfor", "深信服"]},
        "match": {"type": "all", "conditions": [
            {"field": "type", "op": "eq", "value": "security_alert"},
        ]},
    }]

    def test_metadata_direct_route(self):
        """元数据命中 → 直接路由（特征条件不满足也能路由成功）。"""
        router, engine = _router([_strategy(1, "sangfor_xdr")], self.ENTRIES)
        raw = {"device_vendor": "深信服", "type": "other_type", "event_uuid": "u-meta"}
        cls = router.classify(raw)
        assert cls.method == "metadata"
        assert cls.device_type == "sangfor_xdr"
        result = router.parse_one(raw, engine)
        assert result.status in ("success", "partial")
        assert result.strategy_id == 1

    def test_metadata_case_insensitive_and_implicit_name(self):
        """别名大小写不敏感；设备类型名本身是隐式别名。"""
        router, _ = _router([], self.ENTRIES)
        assert router.classify({"source_type": "SANGFOR"}).device_type == "sangfor_xdr"
        assert router.classify({"device_type": "Sangfor_XDR"}).device_type == "sangfor_xdr"

    def test_unknown_metadata_value_falls_to_features(self):
        """元数据存在但不匹配任何已知类型 → 交由特征匹配。"""
        router, _ = _router([], self.ENTRIES)
        raw = {"source_type": "brand_new_lake", "type": "security_alert"}
        cls = router.classify(raw)
        assert cls.method == "features"
        assert cls.candidates == ["sangfor_xdr"]


# ============ 2. 特征匹配（特异度降序候选列表） ============
class TestFeatureMatch:
    ENTRIES = [
        {"device_type": "vendor_a", "specificity": 100,
         "match": {"type": "all", "conditions": [{"field": "vendor_tag", "op": "eq", "value": "acme"}]}},
        {"device_type": "vendor_b", "specificity": 50,
         "match": {"type": "all", "conditions": [{"field": "vendor_tag", "op": "eq", "value": "acme"}]}},
    ]

    def test_candidates_ordered_by_specificity(self):
        """多设备类型同时命中 → 候选按特异度降序。"""
        router, _ = _router([], self.ENTRIES)
        cls = router.classify({"vendor_tag": "acme"})
        assert cls.method == "features"
        assert cls.candidates == ["vendor_a", "vendor_b"]

    def test_specificity_tie_keeps_yaml_order(self):
        """同特异度保持 YAML 定义顺序（排序稳定）。"""
        entries = [
            {"device_type": "first", "specificity": 10, "match": {"type": "all", "conditions": [
                {"field": "x", "op": "eq", "value": 1}]}},
            {"device_type": "second", "specificity": 10, "match": {"type": "all", "conditions": [
                {"field": "x", "op": "eq", "value": 1}]}},
        ]
        router, _ = _router([], entries)
        assert router.classify({"x": 1}).candidates == ["first", "second"]

    def test_exists_and_not_exists_ops(self):
        """exists/not_exists 算子：只看字段是否有值。"""
        entries = [{
            "device_type": "struct_check", "specificity": 10,
            "match": {"type": "all", "conditions": [
                {"field": "datatype", "op": "exists"},
                {"field": "noise", "op": "not_exists"},
            ]},
        }]
        router, _ = _router([], entries)
        assert router.classify({"datatype": "alert"}).candidates == ["struct_check"]
        assert router.classify({"datatype": "alert", "noise": "x"}).candidates == []
        assert router.classify({}).candidates == []


# ============ 3. 候选回退 ============
class TestCandidateFallback:
    ENTRIES = [
        {"device_type": "vendor_a", "specificity": 100,
         "match": {"type": "all", "conditions": [{"field": "vendor_tag", "op": "eq", "value": "acme"}]}},
        {"device_type": "vendor_b", "specificity": 50,
         "match": {"type": "all", "conditions": [{"field": "vendor_tag", "op": "eq", "value": "acme"}]}},
    ]
    RAW = {"vendor_tag": "acme", "event_uuid": "u1", "event_name": "e", "src_ip": "1.2.3.4"}

    def test_fallback_on_parse_fail(self):
        """高特异度候选解析失败（无匹配规则）→ 回退下一候选。"""
        strats = [
            _strategy(1, "vendor_a", always_hit=False),
            _strategy(2, "vendor_b"),
        ]
        router, engine = _router(strats, self.ENTRIES)
        result = router.parse_one(self.RAW, engine)
        assert result.status in ("success", "partial")
        assert result.strategy_id == 2

    def test_fallback_on_route_validator_gate(self):
        """YAML 路由级校验器拒绝（任一失败不论 severity）→ 回退下一候选。"""
        entries = [
            {**self.ENTRIES[0], "validators": [{"field": "src_ip", "rule": "ip_list_valid"}]},
            self.ENTRIES[1],
        ]
        strats = [_strategy(1, "vendor_a"), _strategy(2, "vendor_b")]
        router, engine = _router(strats, entries)
        raw = {**self.RAW, "src_ip": "999.999.999.999"}  # 非法 IP：候选 A 校验不过
        result = router.parse_one(raw, engine)
        assert result.strategy_id == 2
        # 合法 IP：候选 A 直接收录
        router_ok, engine_ok = _router(strats, entries)
        assert router_ok.parse_one(self.RAW, engine_ok).strategy_id == 1

    def test_fallback_on_strategy_error_severity(self):
        """策略内置 severity=error 校验失败 → 候选拒绝；warning 级不阻断。"""
        strats = [
            _strategy(1, "vendor_a", validations=[
                {"field": "src_ip", "rule": "ip_list_valid", "severity": "error"}]),
            _strategy(2, "vendor_b", validations=[
                {"field": "src_ip", "rule": "ip_list_valid", "severity": "warning"}]),
        ]
        router, engine = _router(strats, self.ENTRIES)
        raw = {**self.RAW, "src_ip": "not-an-ip"}
        result = router.parse_one(raw, engine)
        assert result.strategy_id == 2  # 候选 A（error 级）被门控拒绝

    def test_version_desc_within_device_type(self):
        """同设备类型多策略：版本最新的先试。"""
        strats = [
            _strategy(1, "vendor_a", version="1.0"),
            _strategy(2, "vendor_a", version="2.0"),
        ]
        router, engine = _router(strats, self.ENTRIES)
        result = router.parse_one(self.RAW, engine)
        assert result.strategy_id == 2

    def test_parse_exception_falls_back(self):
        """候选解析抛异常（策略配置损坏）→ 视为该候选失败，回退下一候选。"""
        strats = [_strategy(1, "vendor_a"), _strategy(2, "vendor_b")]

        class BoomEngine:
            def __init__(self, real):
                self._real = real
                self._calls = 0

            def parse_one(self, raw, strategy=None):
                self._calls += 1
                if self._calls == 1:
                    raise RuntimeError("损坏的策略配置")
                return self._real.parse_one(raw, strategy=strategy)

        loader = StrategyLoader(strategies=strats)
        classifier = LogClassifier(_table(self.ENTRIES))
        real_engine = ParseEngine(loader=loader, sink=None)
        router = ClassifierRouter(loader, classifier=classifier)
        result = router.parse_one(self.RAW, BoomEngine(real_engine))
        assert result.status in ("success", "partial")
        assert result.strategy_id == 2


# ============ 4. legacy route_rules 兜底 + unknown 兜底队列 ============
class TestLegacyAndUnknown:
    def test_legacy_route_rules_fallback(self):
        """YAML 未登记设备类型的存量策略：仍按 route_rules 自动匹配。"""
        legacy = {
            "id": 7, "strategy_name": "存量策略", "device_type": "legacy_dev",
            "version": "1.0", "status": "enabled",
            "config": {
                "strategy_name": "存量策略", "device_type": "legacy_dev", "version": "1.0",
                "route_rules": {"match_type": "exact", "match_field": "type", "match_value": "legacy_event"},
                "outer_wrapper": {"data_path": "", "header_fields": [], "uuid_source": "event_uuid"},
                "field_mappings": [{"source": "event_name", "target": "alert_name", "type": "string"}],
                "enum_maps": {}, "validations": [], "extension_fields": [],
            },
        }
        entries = [{"device_type": "vendor_a", "specificity": 100,
                   "match": {"type": "all", "conditions": [
                       {"field": "vendor_tag", "op": "eq", "value": "acme"}]}}]
        router, engine = _router([legacy], entries)
        result = router.parse_one({"type": "legacy_event", "event_uuid": "u-leg"}, engine)
        assert result.status in ("success", "partial")
        assert result.strategy_id == 7

    def test_all_fail_goes_unknown(self):
        """候选存在但全部失败 → unknown 结果，error_msg 含尝试轨迹与 uuid。"""
        strats = [_strategy(1, "vendor_a", always_hit=False)]
        entries = [{"device_type": "vendor_a", "specificity": 100,
                    "match": {"type": "all", "conditions": [
                        {"field": "vendor_tag", "op": "eq", "value": "acme"}]}}]
        router, engine = _router(strats, entries)
        raw = {"vendor_tag": "acme", "event_uuid": "u-unk"}
        result = router.parse_one(raw, engine)
        assert result.status == "fail"
        assert result.error_type == ERR_UNKNOWN_LOG_TYPE
        assert "vendor_a#策略1" in result.error_msg
        assert result.uuid == "u-unk"  # 候选解析中提取的 uuid 尽力保留

    def test_no_match_no_strategy_unknown(self):
        """无元数据、特征未命中、route_rules 未命中 → unknown（uuid 从 raw 顶层兜底提取）。"""
        router, engine = _router([_strategy(1, "vendor_a")], [])
        result = router.parse_one({"foo": "bar", "event_uuid": "u-raw"}, engine)
        assert result.status == "fail"
        assert result.error_type == ERR_UNKNOWN_LOG_TYPE
        assert result.uuid == "u-raw"
        assert "无候选策略" in result.error_msg


# ============ 5. YAML 特征表：加载 / 热更新 / 容错 / 零改码扩展 ============
ACME_YAML = """
metadata_fields: [source_type, device_vendor]
device_types:
  - device_type: acme_fw
    specificity: 80
    metadata:
      device_vendor: [acme]
    match:
      type: all
      conditions:
        - { field: vendor_tag, op: eq, value: acme }
    validators: []
"""

ACME_YAML_V2 = ACME_YAML + """
  - device_type: beta_fw
    specificity: 60
    match:
      type: all
      conditions:
        - { field: vendor_tag, op: eq, value: beta }
"""


@pytest.fixture
def yaml_file(tmp_path):
    """临时特征表文件（每用例独立路径，避免共享缓存干扰）。"""
    path = tmp_path / "features.yaml"
    path.write_text(ACME_YAML, encoding="utf-8")
    return str(path)


class TestYamlTable:
    def test_yaml_load_and_route(self, yaml_file):
        """YAML 加载：新增设备类型零改码路由（表 + 策略即可）。"""
        table = load_feature_table(yaml_file)
        assert table.has("acme_fw")
        strats = [_strategy(11, "acme_fw")]
        loader = StrategyLoader(strategies=strats)
        router = ClassifierRouter(
            loader, classifier=LogClassifier(load_feature_table(yaml_file))
        )
        engine = ParseEngine(loader=loader, sink=None)
        # 元数据直路由
        r1 = router.parse_one({"device_vendor": "ACME", "event_uuid": "u1"}, engine)
        assert r1.strategy_id == 11
        # 特征匹配
        r2 = router.parse_one({"vendor_tag": "acme", "event_uuid": "u2"}, engine)
        assert r2.strategy_id == 11

    def test_yaml_hot_reload(self, yaml_file):
        """文件更新（mtime/size 变化）→ 自动热加载。"""
        t1 = load_feature_table(yaml_file)
        assert not t1.has("beta_fw")
        with open(yaml_file, "a", encoding="utf-8") as f:
            f.write("""
  - device_type: beta_fw
    specificity: 60
    match:
      type: all
      conditions:
        - { field: vendor_tag, op: eq, value: beta }
""")
        st = os.stat(yaml_file)
        os.utime(yaml_file, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))
        t2 = load_feature_table(yaml_file)
        assert t2.has("beta_fw"), "文件追加设备类型后应热加载可见"

    def test_broken_yaml_keeps_last_good(self, yaml_file):
        """语法损坏 → 保留上次可用表（不抛异常、不丢配置）。"""
        good = load_feature_table(yaml_file)
        with open(yaml_file, "w", encoding="utf-8") as f:
            f.write("device_types: [Broken {{{{")
        st = os.stat(yaml_file)
        os.utime(yaml_file, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))
        again = load_feature_table(yaml_file)
        assert again.has("acme_fw"), "坏文件应保留上次可用表"

    def test_missing_file_empty_table(self, tmp_path):
        """文件缺失 → 空表降级（仅剩 route_rules 自动匹配，不影响运行）。"""
        table = load_feature_table(str(tmp_path / "not_exist.yaml"))
        assert table.device_types == []
        cls = LogClassifier(table).classify({"source_type": "sangfor"})
        assert cls.method == "" and cls.candidates == []

    def test_reload_forces_cache_drop(self, yaml_file):
        """reload_feature_table：清缓存强制重载。"""
        load_feature_table(yaml_file)
        with open(yaml_file, "w", encoding="utf-8") as f:
            f.write(ACME_YAML_V2)
        table = reload_feature_table(yaml_file)
        assert table.has("beta_fw")


# ============ 6. 随包特征表（生产配置冒烟） ============
class TestPackagedTable:
    def test_packaged_table_loads(self):
        """随包 classifier_features.yaml 可加载且含内置设备类型。"""
        from app.engine.classifier import FEATURE_TABLE_PATH
        table = load_feature_table(FEATURE_TABLE_PATH)
        assert table.has("qingteng_wanxiang")
        assert table.has("sangfor_xdr")
        # 青藤：元数据直路由（__source 来自 syslog 预处理器）
        cls = LogClassifier(table).classify({"__source": "qingteng_syslog"})
        assert cls.method == "metadata"
        assert cls.device_type == "qingteng_wanxiang"
        # 深信服：特征匹配（type=security_alert 且 data 存在）
        cls2 = LogClassifier(table).classify({"type": "security_alert", "data": {"uuId": "x"}})
        assert cls2.method == "features"
        assert cls2.candidates == ["sangfor_xdr"]

    def test_packaged_table_specificity_order(self):
        from app.engine.classifier import FEATURE_TABLE_PATH
        table = load_feature_table(FEATURE_TABLE_PATH)
        assert table.device_types[0].device_type == "qingteng_wanxiang"  # 特异度 100 > 90


if __name__ == "__main__":
    pytest.main([os.path.abspath(__file__), "-v"])
