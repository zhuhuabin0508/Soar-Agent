"""采集子系统流水线单测：NormalizedEvent 往返 / Filter op 矩阵 / Translator 补填。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_collector_pipeline.py -v
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.log_receiver_manager.events import NormalizedEvent, RawEvent
from app.core.log_receiver_manager.pipeline.base_stage import PipelineData
from app.core.log_receiver_manager.pipeline.filter_stage import FilterStage, should_drop
from app.core.log_receiver_manager.pipeline.runner import PipelineRunner, get_default_config
from app.core.log_receiver_manager.pipeline.translator_stage import TranslatorStage


class _FakeResult:
    """ParseResult 替身（仅 fields，测试往返用）。"""

    def __init__(self, fields):
        self.fields = fields


def _norm(fields):
    return NormalizedEvent.from_parse_result(_FakeResult(fields))


def _data_with_norms(*norms):
    """构造含 NormalizedEvent 列表的 PipelineData（Filter/Translator 测试共用）。"""
    event = RawEvent(
        receiver_id=1, device_id=None, source_type="syslog", source_ip=None,
        transport="udp", received_at=datetime.now(), raw="r",
    )
    return PipelineData(event=event, results=[_FakeResult({}) for _ in norms], normalized=list(norms))


class TestNormalizedEventRoundtrip:
    def _fields(self):
        return {
            "uuid": "u-123", "alert_name": "暴力破解", "risk_level": 1,
            "risk_level_name": "高危", "severity": 80, "src_ip": '["1.2.3.4"]',
            "src_port": "8080", "dst_ip": "10.0.0.1", "host_ip": "192.168.1.1",
            "user_name": "root", "occur_timestamp": datetime(2026, 8, 26, 12, 0, 0),
            "strategy_id": 10, "device_type": "qingteng_wanxiang",
            "rule_id": "R001", "log_type": "host_alarm", "parse_status": "success",
            # JSON 字符串与自定义键 → extra_fields 透传
            "extensions": '{"a": 1}', "parse_warnings": "[]",
            "raw_data": '{"k": "v"}', "risk_tag": '["暴力破解"]',
            "some_vendor_field": "custom", "tenant": "default",
        }

    def test_roundtrip_lossless(self):
        fields = self._fields()
        norm = _norm(fields)
        assert norm.to_alert_fields() == fields  # 逐键无损（含值与键集合）

    def test_partial_fields_no_default_injected(self):
        # 仅部分键存在时，往返不得引入缺省键（如 risk_level=-1）
        fields = {"uuid": "u-1", "alert_name": "x"}
        out = _norm(fields).to_alert_fields()
        assert out == fields
        assert "risk_level" not in out
        assert "severity" not in out

    def test_get_set_field(self):
        norm = _norm({"risk_level": 2, "custom_x": "y"})
        assert norm.get_field("risk_level") == 2
        assert norm.get_field("custom_x") == "y"
        assert norm.get_field("missing") is None
        norm.set_field("risk_level", 3)
        norm.set_field("another_custom", "z")
        out = norm.to_alert_fields()
        assert out["risk_level"] == 3
        assert out["another_custom"] == "z"
        assert out["custom_x"] == "y"


class TestAlertEventRuleMetadata:
    """回归：parser_engine 注入 fields 的 rule_id/log_type 必须是 AlertEvent 合法列。

    历史 bug：_ALERT_FIELD_MAP 定义了 rule_id/log_type，parser_engine 命中规则后
    把规则元数据写入输出 fields，但 AlertEvent 模型缺列导致 AlertEvent(**fields)
    入库崩溃（'rule_id' is an invalid keyword argument for AlertEvent）。
    """

    def test_parser_fields_construct_alert_event(self):
        from app.engine.parser_engine import ParseEngine
        from app.models.alert_event import AlertEvent

        config = {
            "device_type": "qingteng_wanxiang",
            "outer_wrapper": {"uuid_source": "id"},
            "rules": [{
                "rule_id": "functional", "log_type": "功能日志",
                "match": {"type": "all", "conditions": [
                    {"field": "datatype", "op": "eq", "value": "account_change"}]},
                "extract": {"mode": "fields", "fields": [{"source": "event", "target": "alert_name"}]},
            }],
        }
        engine = ParseEngine(loader=None, sink=None)  # 指定 strategy 时 loader 不参与
        result = engine.parse_one(
            {"datatype": "account_change", "id": "u-qt-1", "event": "账号密码修改"},
            strategy={"id": 10, "strategy_name": "青藤万相", "config": config},
        )
        assert result.status in ("success", "partial")
        assert result.fields["rule_id"] == "functional"
        assert result.fields["log_type"] == "功能日志"
        alert = AlertEvent(**result.fields)  # 模型缺列时会抛 TypeError
        assert alert.rule_id == "functional"
        assert alert.log_type == "功能日志"

    def test_roundtrip_with_real_parse_engine_output(self):
        # 用真实 ParseEngine（纯计算）输出验证往返
        from app.engine.parser_engine import ParseEngine
        from app.engine.strategy_loader import StrategyLoader

        strategy = {
            "id": 1, "strategy_name": "t", "device_type": "t", "status": "enabled",
            "config": {
                "route_rules": {"match_type": "exact", "match_field": "type", "match_value": "security_alert"},
                "field_mappings": [
                    {"source": "uuId", "target": "uuid", "type": "string", "required": True},
                    {"source": "riskLevel", "target": "risk_level", "type": "enum_int",
                     "enum_map": "RISK_LEVEL", "enum_target": "risk_level_name"},
                ],
                "enum_maps": {"RISK_LEVEL": {"1": "高危"}},
            },
        }
        loader = StrategyLoader(fetch_strategies=lambda: [strategy])
        engine = ParseEngine(loader=loader)
        result = engine.parse_one({"type": "security_alert", "uuId": "u-9", "riskLevel": 1})
        assert result.status in ("success", "partial")
        assert _norm(result.fields).to_alert_fields() == result.fields


class TestFilterStage:
    def test_disabled_by_default_passthrough(self):
        # 默认 enabled=false → 全透传（重构后行为等价的保证）
        stage = FilterStage({"enabled": False, "rules": [{"field": "risk_level", "op": "gte", "value": 0}]})
        data = _data_with_norms(_norm({"risk_level": 1}), _norm({"risk_level": 9}))
        stage.process(data, None, None)
        assert len(data.results) == 2 and data.dropped == 0

    def test_drop_match_all(self):
        stage = FilterStage({
            "enabled": True, "match": "all",
            "rules": [
                {"field": "risk_level", "op": "gte", "value": 3},
                {"field": "alert_name", "op": "regex", "value": "健康检查"},
            ],
        })
        data = _data_with_norms(
            _norm({"risk_level": 4, "alert_name": "每日健康检查"}),
            _norm({"risk_level": 4, "alert_name": "暴力破解"}),
            _norm({"risk_level": 1, "alert_name": "每日健康检查"}),
        )
        stage.process(data, None, None)
        assert data.dropped == 1
        assert [n.get_field("alert_name") for n in data.normalized] == ["暴力破解", "每日健康检查"]

    def test_drop_match_any(self):
        stage = FilterStage({
            "enabled": True, "match": "any",
            "rules": [{"field": "risk_level", "op": "gte", "value": 3}],
        })
        data = _data_with_norms(_norm({"risk_level": 4}), _norm({"risk_level": 1}))
        stage.process(data, None, None)
        assert data.dropped == 1

    def test_op_matrix(self):
        norm = _norm({"risk_level": 2, "alert_name": "x", "src_ip": "", "custom_list": ["a"]})
        assert should_drop(norm, "all", [{"field": "risk_level", "op": "eq", "value": 2}])
        assert should_drop(norm, "all", [{"field": "risk_level", "op": "ne", "value": 3}])
        assert should_drop(norm, "all", [{"field": "alert_name", "op": "in", "value": ["x", "y"]}])
        assert should_drop(norm, "all", [{"field": "alert_name", "op": "not_in", "value": ["z"]}])
        assert should_drop(norm, "all", [{"field": "risk_level", "op": "gte", "value": 2}])
        assert should_drop(norm, "all", [{"field": "risk_level", "op": "lte", "value": 2}])
        assert should_drop(norm, "all", [{"field": "risk_level", "op": "gt", "value": 1}])
        assert should_drop(norm, "all", [{"field": "risk_level", "op": "lt", "value": 3}])
        assert should_drop(norm, "all", [{"field": "alert_name", "op": "regex", "value": "^x$"}])
        assert should_drop(norm, "all", [{"field": "custom_list", "op": "exists"}])
        assert should_drop(norm, "all", [{"field": "src_ip", "op": "empty"}])
        # 缺失字段：exists=False、其余 op 不满足
        assert not should_drop(norm, "all", [{"field": "nope", "op": "exists"}])
        assert not should_drop(norm, "all", [{"field": "nope", "op": "eq", "value": ""}])
        # 不可比较类型不抛异常
        assert not should_drop(norm, "all", [{"field": "alert_name", "op": "gte", "value": 1}])
        # 空 rules 不丢弃
        assert not should_drop(norm, "all", [])


class TestTranslatorStage:
    MAPS = {
        "risk_level_name": {"0": "严重", "1": "高危", "2": "中危", "3": "低危", "4": "信息"},
    }

    def test_fills_empty_only(self):
        stage = TranslatorStage({"maps": self.MAPS})
        n_has = _norm({"risk_level": 1, "risk_level_name": "策略已翻译"})
        n_empty = _norm({"risk_level": 2, "risk_level_name": ""})
        n_absent = _norm({"risk_level": 3})
        data = _data_with_norms(n_has, n_empty, n_absent)
        stage.process(data, None, None)
        assert n_has.get_field("risk_level_name") == "策略已翻译"  # 不覆盖
        assert n_empty.get_field("risk_level_name") == "中危"      # 补空
        assert n_absent.get_field("risk_level_name") == "低危"     # 缺失也补

    def test_empty_maps_noop(self):
        stage = TranslatorStage({"maps": {}})
        norm = _norm({"risk_level": 1})
        stage.process(_data_with_norms(norm), None, None)
        assert norm.get_field("risk_level_name") is None


class TestPipelineConfig:
    def test_default_config_loads(self):
        cfg = get_default_config()
        assert cfg["preprocessors"] == ["json", "qingteng_syslog", "plain_message"]
        assert cfg["filter"]["enabled"] is False     # 默认禁用（等价保证）
        assert cfg["enricher"]["enrichers"] == []    # 默认无富化
        assert cfg["translator"]["maps"] == {}       # 默认无词表

    def test_runner_builds_six_stages(self):
        runner = PipelineRunner(get_default_config())
        names = [type(s).name for s in runner.stages]
        # alert_rule 位于 translator 与 normalizer 之间（告警规则严格匹配）
        assert names == ["parser", "filter", "enricher", "translator", "alert_rule", "normalizer"]

    def test_for_receiver_cache_and_override(self):
        r1 = PipelineRunner.for_receiver({"id": 99})
        r1b = PipelineRunner.for_receiver({"id": 99})
        assert r1 is r1b
        # adapter_config.pipeline 覆盖 filter 后缓存按配置 hash 区分
        r2 = PipelineRunner.for_receiver({"id": 99, "adapter_config": {"pipeline": {"filter": {"enabled": True}}}})
        assert r2 is not r1
        assert r2.stages[1].config["enabled"] is True
        # adapter_config 为 JSON 字符串亦可
        r3 = PipelineRunner.for_receiver({"id": 99, "adapter_config": '{"pipeline": {"filter": {"enabled": true}}}'})
        assert r3.stages[1].config["enabled"] is True
