"""告警规则引擎单测（XDR 风格重构版）。

覆盖：
- 匹配纯逻辑：all/any、嵌套条件组（两层）、in_cidr 网段、作用域、优先级、空条件
- 统计类规则：滑动窗口计数触发阈值、group_by 分组独立计数、count_distinct 去重、
  窗口滑出剪枝、测试模拟与线上计数隔离、阶段行为（触发告警/未达阈值终态明细）
- 字段配置（XDR 双控件）：static/map/keep 应用、告警名称模板插值、
  旧规则 override 回退兼容、field_mapping 优先
- 阶段行为：命中保留+规则标识、suppress/未命中移除+终态明细、匹配优先于统计、
  抑制拦截统计计数、命中记录行、高危通知节流
- 发布门禁：verify_rule_passes_samples（匹配/统计）
- 告警聚合：聚合键拼接、聚合配置查询
- API 载荷校验：类型/统计配置/字段映射/聚合配置/嵌套深度/重名/作用域/动作/等级映射/标签
- 序列化（新列）与快速开始模板配置
- 测试端点（load_enabled_rules 打桩，只读不落库）：匹配链明细/草稿优先级/
  统计模拟/字段配置预览/样例上限

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_alert_rules.py -v
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.core.log_receiver_manager.events import NormalizedEvent, RawEvent
from app.core.log_receiver_manager.pipeline.alert_rule_stage import (
    AlertRuleStage,
    _notify_high_risk as _real_notify_high_risk,
    apply_rule_action,
    get_alert_aggregation_config,
    match_alert_rules,
    record_stats_event,
    render_name_template,
    reset_stats_windows,
    simulate_stats,
    verify_rule_passes_samples,
)
from app.core.log_receiver_manager.pipeline.base_stage import PipelineData


@pytest.fixture(autouse=True)
def _no_notify(monkeypatch):
    """默认屏蔽高危通知推送（避免单测触碰真实通知；节流测试自行还原真实实现）。"""
    from app.core.log_receiver_manager.pipeline import alert_rule_stage as mod

    monkeypatch.setattr(mod, "_notify_high_risk", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _clean_stats_windows():
    """每个用例前后清空统计滑动窗口（模块级状态，用例间互不污染）。"""
    reset_stats_windows()
    yield
    reset_stats_windows()


class _FakeResult:
    """ParseResult 替身（alert_rule 阶段消费的字段）。"""

    def __init__(self, fields, status="success"):
        self.fields = fields
        self.status = status
        self.strategy_id = 10
        self.strategy_name = "青藤万相"
        self.rule_id = "R001"
        self.log_type = "host_alarm"
        self.parse_ms = 1


def _norm(fields):
    return NormalizedEvent.from_parse_result(_FakeResult(fields))


def _rule(**kw):
    """构造规则 dict（load_enabled_rules 缓存项结构）。"""
    base = {
        "id": kw.pop("id", 1),
        "name": kw.pop("name", "规则"),
        "priority": 100,
        "scope": "global",
        "device_type": "",
        "match": "all",
        "conditions": [],
        "rule_type": "match",
        "action": "alert",
        "override": {},
        "field_mapping": {},
    }
    base.update(kw)
    return base


def _stats_rule(**kw):
    """构造统计类规则（条件为输入筛选 + stats_config；threshold 快捷参数注入配置）。"""
    threshold = kw.pop("threshold", None)
    cfg = {
        "window": {"value": 5, "unit": "minute"},
        "method": "count",
        "distinct_field": None,
        "group_by": ["src_ip"],
        "threshold": 3,
    }
    cfg.update(kw.pop("stats_config", None) or {})
    if threshold is not None:
        cfg["threshold"] = threshold
    kw["stats_config"] = cfg
    kw.setdefault("id", 11)
    kw.setdefault("name", "暴力破解统计")
    kw["rule_type"] = "stats"
    kw["action"] = "alert"
    kw.setdefault("conditions", [{"field": "threat_type", "op": "eq", "value": "暴力破解"}])
    return _rule(**kw)


def _data(norms, results=None):
    event = RawEvent(
        receiver_id=1, device_id=None, source_type="syslog", source_ip=None,
        transport="udp", received_at=datetime.now(), raw="raw-log",
    )
    return PipelineData(
        event=event,
        results=results or [_FakeResult({"uuid": f"u-{i}"}) for i in range(len(norms))],
        normalized=list(norms),
    )


class _FakeSink:
    """ReceiverSink 替身：记录 record_parsed 调用。"""

    def __init__(self):
        self.parsed = []

    def record_parsed(self, raw, status, err="", alert_id=None, **kw):
        self.parsed.append({"raw": raw, "status": status, "err": err, **kw})


# ===== 匹配纯逻辑 =====
class TestMatchAlertRules:
    def test_match_all_conditions(self):
        rules = [_rule(conditions=[{"field": "risk_level", "op": "gte", "value": 2}])]
        norm = _norm({"risk_level": 1, "device_type": "qt"})
        assert match_alert_rules(norm, rules) is None
        norm = _norm({"risk_level": 2, "device_type": "qt"})
        assert match_alert_rules(norm, rules)["id"] == 1

    def test_match_any_aggregation(self):
        rules = [_rule(match="any", conditions=[
            {"field": "risk_level", "op": "eq", "value": 0},
            {"field": "threat_type", "op": "regex", "value": "暴力破解"},
        ])]
        # 任一满足即命中
        assert match_alert_rules(_norm({"threat_type": "暴力破解攻击"}), rules) is not None
        assert match_alert_rules(_norm({"risk_level": 0}), rules) is not None
        assert match_alert_rules(_norm({"risk_level": 3, "threat_type": "扫描"}), rules) is None

    def test_nested_condition_groups(self):
        # 新版嵌套：risk_level≤2 且（内网网段 或 admin 账号）
        rules = [_rule(conditions={"logic": "all", "items": [
            {"field": "risk_level", "op": "lte", "value": 2},
            {"type": "group", "logic": "any", "items": [
                {"field": "src_ip", "op": "in_cidr", "value": ["10.0.0.0/8"]},
                {"field": "account_name", "op": "eq", "value": "admin"},
            ]},
        ]})]
        assert match_alert_rules(_norm({"risk_level": 1, "src_ip": "10.1.1.1", "account_name": "x"}), rules) is not None
        assert match_alert_rules(_norm({"risk_level": 1, "src_ip": "8.8.8.8", "account_name": "admin"}), rules) is not None
        assert match_alert_rules(_norm({"risk_level": 1, "src_ip": "8.8.8.8", "account_name": "guest"}), rules) is None
        assert match_alert_rules(_norm({"risk_level": 3, "src_ip": "10.1.1.1", "account_name": "admin"}), rules) is None

    def test_nested_group_all_logic(self):
        # 组内 all：两个条件都满足才命中
        rules = [_rule(conditions={"logic": "any", "items": [
            {"type": "group", "logic": "all", "items": [
                {"field": "src_ip", "op": "eq", "value": "1.1.1.1"},
                {"field": "dst_port", "op": "eq", "value": 22},
            ]},
        ]})]
        assert match_alert_rules(_norm({"src_ip": "1.1.1.1", "dst_port": 22}), rules) is not None
        assert match_alert_rules(_norm({"src_ip": "1.1.1.1", "dst_port": 80}), rules) is None

    def test_in_cidr_operator(self):
        rules = [_rule(conditions=[{"field": "src_ip", "op": "in_cidr", "value": ["10.0.0.0/8", "192.168.0.0/16"]}])]
        assert match_alert_rules(_norm({"src_ip": "10.20.30.40"}), rules) is not None
        assert match_alert_rules(_norm({"src_ip": "192.168.1.1"}), rules) is not None
        assert match_alert_rules(_norm({"src_ip": "8.8.8.8"}), rules) is None
        assert match_alert_rules(_norm({}), rules) is None  # 缺失字段不满足

    def test_scope_device_type_filter(self):
        rules = [_rule(scope="device_type", device_type="qingteng_wanxiang",
                       conditions=[{"field": "risk_level", "op": "exists"}])]
        assert match_alert_rules(_norm({"device_type": "qingteng_wanxiang", "risk_level": 2}), rules)
        # 设备类型不同：规则不适用（即使条件满足）
        assert match_alert_rules(_norm({"device_type": "sangfor_xdr", "risk_level": 2}), rules) is None

    def test_priority_first_hit_wins(self):
        rules = [
            _rule(id=1, name="高优先级", priority=1, action="suppress",
                  conditions=[{"field": "alert_name", "op": "regex", "value": ".*"}]),
            _rule(id=2, name="低优先级", priority=9, action="alert",
                  conditions=[{"field": "alert_name", "op": "regex", "value": ".*"}]),
        ]
        # 两条都满足条件，但只有优先级高（数值小）的首条生效
        assert match_alert_rules(_norm({"alert_name": "x"}), rules)["id"] == 1

    def test_empty_conditions_never_match(self):
        # 空条件视为不匹配（安全默认，避免空规则放行全部日志）
        rules = [_rule(conditions=[])]
        assert match_alert_rules(_norm({"risk_level": 0}), rules) is None

    def test_missing_field_only_exists_empty(self):
        rules = [_rule(conditions=[{"field": "src_ip", "op": "exists"}])]
        assert match_alert_rules(_norm({"risk_level": 0}), rules) is None
        rules = [_rule(conditions=[{"field": "src_ip", "op": "empty"}])]
        assert match_alert_rules(_norm({"risk_level": 0}), rules) is not None


# ===== 统计类规则（滑动窗口）=====
class TestStatsWindow:
    def test_threshold_trigger_and_group_independence(self):
        rule = _stats_rule(threshold=3)
        same = _norm({"threat_type": "暴力破解", "src_ip": "1.1.1.1"})
        other = _norm({"threat_type": "暴力破解", "src_ip": "2.2.2.2"})
        assert record_stats_event(rule, same)["count"] == 1
        assert record_stats_event(rule, same)["count"] == 2
        assert record_stats_event(rule, other)["count"] == 1  # 不同分组键独立计数
        rec = record_stats_event(rule, same)
        assert rec["count"] == 3 and rec["triggered"] is True  # 达阈值触发
        assert rec["group_key"] == "1.1.1.1"

    def test_window_slide_out(self):
        # 5 分钟窗口：前两条发生在 10 分钟前，应滑出；新事件计数从 1 重新开始
        rule = _stats_rule(threshold=2)
        old = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        recent = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        n1 = _norm({"threat_type": "暴力破解", "src_ip": "1.1.1.1", "occur_timestamp": old})
        n2 = _norm({"threat_type": "暴力破解", "src_ip": "1.1.1.1", "occur_timestamp": old})
        n3 = _norm({"threat_type": "暴力破解", "src_ip": "1.1.1.1", "occur_timestamp": recent})
        assert record_stats_event(rule, n1)["count"] == 1
        assert record_stats_event(rule, n2)["count"] == 2
        # 新事件到来时窗口剪枝：两条旧事件滑出，仅剩当前一条
        rec = record_stats_event(rule, n3)
        assert rec["count"] == 1 and rec["triggered"] is False

    def test_count_distinct(self):
        rule = _stats_rule(threshold=3, stats_config={
            "window": {"value": 1, "unit": "hour"}, "method": "count_distinct",
            "distinct_field": "account_name", "group_by": [], "threshold": 3,
        })
        base = {"threat_type": "暴力破解", "src_ip": "1.1.1.1"}
        assert record_stats_event(rule, _norm({**base, "account_name": "a"}))["count"] == 1
        assert record_stats_event(rule, _norm({**base, "account_name": "a"}))["count"] == 1  # 去重
        assert record_stats_event(rule, _norm({**base, "account_name": "b"}))["count"] == 2
        rec = record_stats_event(rule, _norm({**base, "account_name": "c"}))
        assert rec["count"] == 3 and rec["triggered"] is True

    def test_simulate_stats_isolation(self):
        # 测试模拟不污染线上计数：先模拟 3 条，线上再计一条应从 1 开始
        rule = _stats_rule(threshold=3)
        norms = [_norm({"threat_type": "暴力破解", "src_ip": "1.1.1.1"}) for _ in range(3)]
        sims = simulate_stats(rule, norms)
        assert [s["count"] for s in sims] == [1, 2, 3]
        assert sims[-1]["triggered"] is True
        rec = record_stats_event(rule, norms[0])
        assert rec["count"] == 1  # 线上窗口未被模拟污染

    def test_simulate_stats_input_filter(self):
        # 输入条件不匹配的样例不计入窗口
        rule = _stats_rule()
        sims = simulate_stats(rule, [
            _norm({"threat_type": "扫描", "src_ip": "1.1.1.1"}),   # 不匹配
            _norm({"threat_type": "暴力破解", "src_ip": "1.1.1.1"}),  # 匹配
        ])
        assert sims[0]["matched"] is False and "条件" in sims[0]["reason"]
        assert sims[1]["matched"] is True and sims[1]["count"] == 1

    def test_stage_stats_trigger_alert_and_waiting_note(self, monkeypatch):
        rule = _stats_rule(threshold=3)
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage.load_enabled_rules",
            lambda: [rule],
        )
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage._bump_hit_counts",
            lambda hits: None,
        )
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage._record_hits",
            lambda rows: None,
        )
        stage = AlertRuleStage({})
        mk = lambda i: _norm({"uuid": f"u-{i}", "threat_type": "暴力破解", "src_ip": "1.1.1.1", "risk_level": 2})
        # 前两条：计入窗口未达阈值 → 终态明细不产生告警
        data1 = _data([mk(1)])
        sink1 = _FakeSink()
        stage.process(data1, sink1, None)
        assert data1.results == [] and "未达阈值" in sink1.parsed[0]["err"]
        data2 = _data([mk(2)])
        sink2 = _FakeSink()
        stage.process(data2, sink2, None)
        assert data2.results == [] and "2/3" in sink2.parsed[0]["err"]
        # 第三条：达到阈值 → 产生告警（规则标识写入）
        data3 = _data([mk(3)])
        sink3 = _FakeSink()
        stage.process(data3, sink3, None)
        assert len(data3.results) == 1
        fields = data3.normalized[0].to_alert_fields()
        assert fields["alert_rule_id"] == 11 and fields["alert_rule_name"] == "暴力破解统计"

    def test_match_rule_wins_over_stats_and_suppress_blocks_stats(self, monkeypatch):
        stats_rule = _stats_rule(threshold=2)
        suppress_rule = _rule(id=2, name="抑制暴力破解", priority=1, action="suppress",
                              conditions=[{"field": "threat_type", "op": "eq", "value": "暴力破解"}])
        for patch in (
            "app.core.log_receiver_manager.pipeline.alert_rule_stage._bump_hit_counts",
            "app.core.log_receiver_manager.pipeline.alert_rule_stage._record_hits",
        ):
            monkeypatch.setattr(patch, lambda *a: None)
        stage = AlertRuleStage({})
        mk = _norm({"uuid": "u-1", "threat_type": "暴力破解", "src_ip": "1.1.1.1"})
        # 抑制存在：事件被抑制且不计入统计窗口
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage.load_enabled_rules",
            lambda: [suppress_rule, stats_rule],
        )
        data = _data([mk])
        sink = _FakeSink()
        stage.process(data, sink, None)
        assert data.results == [] and "抑制" in sink.parsed[0]["err"]
        # 移除抑制：统计计数照常累计（第 2 条触发）
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage.load_enabled_rules",
            lambda: [stats_rule],
        )
        stage.process(_data([mk]), _FakeSink(), None)
        data2 = _data([mk])
        stage.process(data2, _FakeSink(), None)
        assert len(data2.results) == 1  # 第 2 条触发统计告警


# ===== 字段配置（XDR 双控件）与动作扩展 =====
class TestFieldMappingAndActions:
    def test_render_name_template_interpolation(self):
        fields = {"threat_type": "暴力破解", "src_ip": "1.2.3.4"}
        assert render_name_template("{threat_type}告警", fields) == "暴力破解告警"
        assert render_name_template("{threat_type}-{src_ip}", fields) == "暴力破解-1.2.3.4"
        # 缺失变量留空、不含 { 的快路径原样返回
        assert render_name_template("{missing}告警", fields) == "告警"
        assert render_name_template("固定名称", fields) == "固定名称"
        assert render_name_template("", fields) == ""

    def test_apply_field_mapping_modes(self):
        rule = _rule(id=7, field_mapping={
            "alert_name": {"mode": "static", "value": "{threat_type} 来自 {src_ip}"},
            "risk_level": {"mode": "static", "value": 1},
            "threat_sub_type": {"mode": "map", "value": "threat_type"},
            "account_name": {"mode": "keep", "value": None},
        })
        norm = _norm({"threat_type": "暴力破解", "src_ip": "1.2.3.4", "risk_level": 3,
                      "threat_sub_type": "原值", "account_name": "root", "alert_name": "原名"})
        fields = apply_rule_action(norm, rule)
        assert fields["alert_name"] == "暴力破解 来自 1.2.3.4"  # 静态值模板插值
        assert fields["risk_level"] == 1 and fields["risk_level_name"] == "高危"  # 静态等级+中文名
        assert fields["threat_sub_type"] == "暴力破解"  # 字段映射
        assert fields["account_name"] == "root"  # 保留解析结果

    def test_field_mapping_overrides_legacy_override(self):
        # field_mapping 配置了 alert_name（keep）时 override.alert_name 不再生效
        rule = _rule(id=8, override={"alert_name": "旧覆盖", "risk_level": 0},
                     field_mapping={"alert_name": {"mode": "keep", "value": None}})
        norm = _norm({"alert_name": "解析名", "risk_level": 3})
        fields = apply_rule_action(norm, rule)
        assert fields["alert_name"] == "解析名"  # keep 保留
        assert fields["risk_level"] == 0  # risk_level 未配置映射 → 回退 override

    def test_legacy_override_still_works_without_mapping(self):
        rule = _rule(id=9, override={"alert_name": "【{threat_type}】", "risk_level": 0, "tags": ["T1"]})
        norm = _norm({"alert_name": "原名", "threat_type": "Webshell", "risk_level": 3})
        fields = apply_rule_action(norm, rule)
        assert fields["alert_name"] == "【Webshell】"
        assert fields["risk_level"] == 0 and fields["risk_level_name"] == "严重"
        assert "T1" in (fields.get("risk_tag") or "")

    def test_merge_tags_json_safe(self):
        import json

        from app.core.log_receiver_manager.pipeline.alert_rule_stage import _merge_tags

        norm = _norm({"risk_tag": json.dumps(["已有标签"], ensure_ascii=False)})
        _merge_tags(norm, ["新标签", "已有标签"])
        assert json.loads(norm.get_field("risk_tag")) == ["已有标签", "新标签"]  # 去重合并
        # 无原标签 / 原值非法 JSON 均安全
        norm2 = _norm({})
        _merge_tags(norm2, ["a"])
        assert json.loads(norm2.get_field("risk_tag")) == ["a"]
        norm3 = _norm({"risk_tag": "not-json"})
        _merge_tags(norm3, ["b"])
        assert json.loads(norm3.get_field("risk_tag")) == ["b"]

    def test_apply_adjust_level(self):
        from app.core.log_receiver_manager.pipeline.alert_rule_stage import _apply_adjust_level

        norm = _norm({"risk_level": 3, "risk_level_name": "低危"})
        _apply_adjust_level(norm, {"3": 1})
        assert norm.get_field("risk_level") == 1
        assert norm.get_field("risk_level_name") == "高危"  # 等级同步中文名
        # 未映射等级保留原值；非法映射不生效
        norm2 = _norm({"risk_level": 2})
        _apply_adjust_level(norm2, {"3": 1})
        assert norm2.get_field("risk_level") == 2
        norm3 = _norm({"risk_level": 2})
        _apply_adjust_level(norm3, None)
        assert norm3.get_field("risk_level") == 2

    def test_contains_operator_match(self):
        rules = [_rule(conditions=[{"field": "threat_type", "op": "contains", "value": "暴力破解"}])]
        assert match_alert_rules(_norm({"threat_type": "SSH暴力破解攻击"}), rules) is not None
        assert match_alert_rules(_norm({"threat_type": "扫描行为"}), rules) is None

    def test_eval_conditions_details_flat_and_nested(self):
        from app.core.log_receiver_manager.pipeline.alert_rule_stage import _eval_conditions, _eval_rule_conditions

        norm = _norm({"risk_level": 0, "threat_type": "扫描", "src_ip": "10.0.0.1"})
        matched, details = _eval_conditions(norm, "all", [
            {"field": "risk_level", "op": "in", "value": [0, 1]},
            {"field": "threat_type", "op": "eq", "value": "暴力破解"},
        ])
        assert matched is False
        assert details[0]["passed"] is True and details[1]["passed"] is False  # 逐条件明细
        # 嵌套结构明细：组节点带 logic/items
        rule = _rule(conditions={"logic": "all", "items": [
            {"field": "risk_level", "op": "eq", "value": 0},
            {"type": "group", "logic": "any", "items": [
                {"field": "src_ip", "op": "in_cidr", "value": ["10.0.0.0/8"]},
                {"field": "threat_type", "op": "eq", "value": "暴力破解"},
            ]},
        ]})
        matched, details = _eval_rule_conditions(norm, rule)
        assert matched is True
        assert details[1]["type"] == "group" and details[1]["logic"] == "any"
        assert details[1]["passed"] is True
        assert details[1]["items"][0]["passed"] is True and details[1]["items"][1]["passed"] is False


# ===== 阶段行为（严格模式）=====
class TestAlertRuleStageProcess:
    def _patch_common(self, monkeypatch, rules):
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage.load_enabled_rules",
            lambda: rules,
        )
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage._bump_hit_counts",
            lambda hits: None,
        )
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage._record_hits",
            lambda rows: None,
        )
        return AlertRuleStage({})

    def test_hit_alert_rule_kept_with_metadata_and_override(self, monkeypatch):
        rules = [_rule(id=7, name="高危告警", action="alert",
                       override={"alert_name": "覆盖名称", "risk_level": 0},
                       conditions=[{"field": "risk_level", "op": "lte", "value": 1}])]
        stage = self._patch_common(monkeypatch, rules)
        norm = _norm({"uuid": "u-1", "risk_level": 1, "alert_name": "原名"})
        data = _data([norm])
        sink = _FakeSink()
        stage.process(data, sink, None)
        assert len(data.results) == 1  # 保留 → 进入 Normalizer 落库
        fields = data.normalized[0].to_alert_fields()
        assert fields["alert_rule_id"] == 7
        assert fields["alert_rule_name"] == "高危告警"
        assert fields["alert_name"] == "覆盖名称"  # 覆盖项生效
        assert fields["risk_level"] == 0
        assert fields["risk_level_name"] == "严重"  # 覆盖等级同步中文名
        assert sink.parsed == []  # 保留条目不在此处记明细（Normalizer 统一记）

    def test_suppress_rule_removed_with_terminal_record(self, monkeypatch):
        rules = [_rule(id=3, name="抑制健康检查", action="suppress",
                       conditions=[{"field": "alert_name", "op": "regex", "value": "健康检查"}])]
        stage = self._patch_common(monkeypatch, rules)
        norm = _norm({"uuid": "u-1", "alert_name": "主机健康检查"})
        data = _data([norm])
        sink = _FakeSink()
        stage.process(data, sink, None)
        assert data.results == [] and data.normalized == []  # 移除，不产生告警
        assert len(sink.parsed) == 1  # 但记终态接收明细（解析本身成功）
        rec = sink.parsed[0]
        assert rec["status"] == "success"
        assert "抑制" in rec["err"] and "抑制健康检查" in rec["err"]
        assert rec["strategy_id"] == 10  # 命中解析模板信息保留（日志预览可查）

    def test_no_rule_hit_strict_mode_removed(self, monkeypatch):
        # 严格模式：无任何启用规则 → 全部不产生告警
        stage = self._patch_common(monkeypatch, [])
        norm = _norm({"uuid": "u-1", "risk_level": 0})
        data = _data([norm])
        sink = _FakeSink()
        stage.process(data, sink, None)
        assert data.results == [] and data.normalized == []
        assert len(sink.parsed) == 1
        assert "严格模式" in sink.parsed[0]["err"]

    def test_mixed_batch(self, monkeypatch):
        rules = [_rule(id=1, name="仅青藤", scope="device_type", device_type="qt",
                       conditions=[{"field": "risk_level", "op": "exists"}])]
        stage = self._patch_common(monkeypatch, rules)
        n1 = _norm({"uuid": "u-1", "device_type": "qt", "risk_level": 1})
        n2 = _norm({"uuid": "u-2", "device_type": "sangfor", "risk_level": 1})
        data = _data([n1, n2])
        sink = _FakeSink()
        stage.process(data, sink, None)
        assert len(data.results) == 1  # 仅命中规则的第一条保留
        assert data.normalized[0].to_alert_fields()["alert_rule_id"] == 1
        assert len(sink.parsed) == 1  # 第二条记未命中明细

    def test_stage_adjust_level_action(self, monkeypatch):
        rules = [_rule(id=5, name="降级映射", action="adjust_level",
                       override={"level_map": {"0": 2}},
                       conditions=[{"field": "risk_level", "op": "eq", "value": 0}])]
        stage = self._patch_common(monkeypatch, rules)
        norm = _norm({"uuid": "u-1", "risk_level": 0, "risk_level_name": "严重"})
        data = _data([norm])
        stage.process(data, _FakeSink(), None)
        assert len(data.results) == 1  # 调整等级同样产生告警（保留）
        fields = data.normalized[0].to_alert_fields()
        assert fields["risk_level"] == 2
        assert fields["risk_level_name"] == "中危"
        assert fields["alert_rule_id"] == 5

    def test_stage_name_template_and_tags_applied(self, monkeypatch):
        rules = [_rule(id=6, name="命名模板", action="alert",
                       override={"alert_name": "【{threat_type}】{src_ip}", "tags": ["tagA"]},
                       conditions=[{"field": "risk_level", "op": "exists"}])]
        stage = self._patch_common(monkeypatch, rules)
        norm = _norm({"uuid": "u-1", "risk_level": 1, "threat_type": "Webshell",
                      "src_ip": "10.0.0.8"})
        data = _data([norm])
        stage.process(data, _FakeSink(), None)
        fields = data.normalized[0].to_alert_fields()
        assert fields["alert_name"] == "【Webshell】10.0.0.8"  # 模板插值
        assert "tagA" in (fields.get("risk_tag") or "")  # 标签追加

    def test_stage_records_hits_rows(self, monkeypatch):
        captured = {}
        rules = [
            _rule(id=1, name="产生", action="alert",
                  conditions=[{"field": "risk_level", "op": "eq", "value": 1}]),
            _rule(id=2, name="抑制", action="suppress",
                  conditions=[{"field": "risk_level", "op": "eq", "value": 0}]),
        ]
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage.load_enabled_rules",
            lambda: rules,
        )
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage._bump_hit_counts",
            lambda hits: captured.update(hits),
        )
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage._record_hits",
            lambda rows: captured.setdefault("rows", []).extend(rows),
        )
        stage = AlertRuleStage({})
        data = _data([
            _norm({"uuid": "u-1", "risk_level": 1}),
            _norm({"uuid": "u-2", "risk_level": 0}),
        ])
        stage.process(data, _FakeSink(), None)
        assert captured == {1: 1, "rows": [
            {"rule_id": 1, "rule_name": "产生", "action": "alert", "uuid": "u-1",
             "source_ip": "", "alert_name": "", "risk_level": 1, "parse_status": "success"},
            {"rule_id": 2, "rule_name": "抑制", "action": "suppress", "uuid": "u-2",
             "source_ip": "", "alert_name": "", "risk_level": 0, "parse_status": "success"},
        ]}  # 告警与抑制均写命中记录（hit_count 仅 alert/adjust/统计触发计入）

    def test_high_risk_notify_throttle(self, monkeypatch):
        from app.core.log_receiver_manager.pipeline import alert_rule_stage as mod

        calls = []
        # 还原真实实现（autouse fixture 默认屏蔽了通知）
        monkeypatch.setattr(mod, "_notify_high_risk", _real_notify_high_risk)
        monkeypatch.setattr(mod, "_notify_last", {})
        monkeypatch.setattr(
            "app.core.notification_dispatch.dispatch_notification",
            lambda db, **kw: calls.append(kw),
        )
        rule = {"id": 9, "name": "高危"}
        fields = {"risk_level": 0, "alert_name": "严重告警", "src_ip": "1.1.1.1"}
        mod._notify_high_risk(rule, None, fields)
        mod._notify_high_risk(rule, None, fields)  # 同规则 5 分钟内节流
        assert len(calls) == 1
        assert calls[0]["event_type"] == "alert_high_risk"
        assert "严重告警" in calls[0]["title"]
        # 低危不推送（换规则 ID 绕过节流，验证等级门槛）
        mod._notify_high_risk({"id": 10, "name": "低危"}, None, {"risk_level": 3, "alert_name": "x"})
        assert len(calls) == 1


# ===== 发布门禁 =====
class TestPublishGate:
    def test_match_rule_pass(self):
        rule = _rule(conditions=[{"field": "risk_level", "op": "lte", "value": 1}])
        ok, _ = verify_rule_passes_samples(rule, [_norm({"risk_level": 0})])
        assert ok is True
        ok, msg = verify_rule_passes_samples(rule, [_norm({"risk_level": 3})])
        assert ok is False and "未命中" in msg

    def test_stats_rule_pass(self):
        rule = _stats_rule(threshold=3)
        norms = [_norm({"threat_type": "暴力破解", "src_ip": "1.1.1.1"}) for _ in range(3)]
        ok, _ = verify_rule_passes_samples(rule, norms)
        assert ok is True
        ok, msg = verify_rule_passes_samples(rule, norms[:2])
        assert ok is False and "阈值" in msg


# ===== 告警聚合 =====
class TestAlertAggregation:
    def test_aggregation_key(self):
        from app.core.log_receiver_manager.pipeline.normalizer_stage import _aggregation_key

        fields = {"src_ip": "1.1.1.1", "threat_type": "暴力破解"}
        assert _aggregation_key(fields, ["src_ip", "threat_type"]) == "1.1.1.1|暴力破解"
        assert _aggregation_key(fields, []) == ""
        assert _aggregation_key(fields, ["account_name"]) == ""  # 缺失留空

    def test_get_alert_aggregation_config(self, monkeypatch):
        rule = _rule(id=5, alert_aggregation={"window": {"value": 30, "unit": "minute"}, "keys": ["src_ip"]})
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage.load_enabled_rules",
            lambda: [rule],
        )
        assert get_alert_aggregation_config(5)["keys"] == ["src_ip"]
        assert get_alert_aggregation_config(None) is None
        assert get_alert_aggregation_config(999) is None  # 未知规则
        # 未配置聚合 → None
        rule2 = _rule(id=6)
        monkeypatch.setattr(
            "app.core.log_receiver_manager.pipeline.alert_rule_stage.load_enabled_rules",
            lambda: [rule2],
        )
        assert get_alert_aggregation_config(6) is None


# ===== 模型回归 =====
class TestModels:
    def test_alert_rule_columns_exist(self):
        from app.models.alert_rule import AlertRule

        row = AlertRule(
            name="统计规则", rule_type="stats", rule_group="暴力破解", draft=1,
            stats_config='{"threshold": 5}', field_mapping='{"src_ip": {"mode": "map", "value": "src_ip"}}',
            alert_aggregation='{"keys": ["src_ip"]}',
        )
        assert row.rule_type == "stats" and row.rule_group == "暴力破解"
        assert row.draft == 1

    def test_alert_event_aggregation_columns(self):
        from app.models.alert_event import AlertEvent

        row = AlertEvent(uuid="u-x", aggregation_count=3, aggregation_key="1.1.1.1|暴力破解")
        assert row.aggregation_count == 3

    def test_alert_rule_group_model(self):
        from app.models.alert_rule_group import AlertRuleGroup

        row = AlertRuleGroup(name="暴力破解", sort_order=10)
        assert row.name == "暴力破解" and row.sort_order == 10

    def test_alert_rule_hit_model(self):
        from app.models.alert_rule_hit import AlertRuleHit

        row = AlertRuleHit(
            rule_id=1, rule_name="高危告警", action="alert", uuid="u-1",
            source_ip="1.2.3.4", alert_name="暴力破解", risk_level=1,
            parse_status="success",
        )
        assert row.rule_id == 1 and row.action == "alert" and row.risk_level == 1


# ===== API 载荷校验 =====
class _FakeQuery:
    def __init__(self, rows=None):
        self._rows = rows or []

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeDB:
    """名称唯一性/分组查询打桩（默认无重名、无既有分组）。"""

    def __init__(self, name_rows=None):
        self._name_rows = name_rows
        self.added = []

    def query(self, *a, **k):
        return _FakeQuery(self._name_rows)

    def add(self, obj):
        self.added.append(obj)


class TestRuleValidation:
    def _payload(self, **kw):
        from app.api.v1.alert_rules import RuleCreate

        base = dict(
            name="规则", enabled=True, priority=100, scope="global", device_type="",
            match="all", conditions=[{"field": "risk_level", "op": "gte", "value": 2}],
            type="match", action="alert", override={},
        )
        base.update(kw)
        return RuleCreate(**base)

    def _stats_payload(self, **kw):
        from app.api.v1.alert_rules import RuleCreate

        base = dict(
            name="统计规则", type="stats", action="alert", scope="global", match="all",
            conditions=[{"field": "threat_type", "op": "eq", "value": "暴力破解"}],
            stats_config={"window": {"value": 5, "unit": "minute"}, "method": "count",
                          "distinct_field": None, "group_by": ["src_ip"], "threshold": 10},
        )
        base.update(kw)
        return RuleCreate(**base)

    def test_valid_payload(self):
        from app.api.v1.alert_rules import _validate

        out = _validate(self._payload(), _FakeDB())
        assert out["rule_type"] == "match" and out["draft"] == 0
        # 条件归一为嵌套结构
        import json as _json
        conds = _json.loads(out["conditions"])
        assert conds["logic"] == "all" and conds["items"][0]["field"] == "risk_level"

    def test_nested_conditions_accepted_and_match_column_synced(self):
        from app.api.v1.alert_rules import _validate

        import json as _json
        payload = self._payload(match="any", conditions={"logic": "any", "items": [
            {"field": "risk_level", "op": "in", "value": [0, 1]},
            {"type": "group", "logic": "all", "items": [
                {"field": "src_ip", "op": "in_cidr", "value": ["10.0.0.0/8"]},
                {"field": "dst_port", "op": "eq", "value": 22},
            ]},
        ]})
        out = _validate(payload, _FakeDB())
        conds = _json.loads(out["conditions"])
        assert conds["logic"] == "any" and conds["items"][1]["type"] == "group"
        assert out["match"] == "any"  # 顶层逻辑冗余存 match 列

    @pytest.mark.parametrize("kw,detail", [
        ({"scope": "device_type", "device_type": ""}, "设备类型"),
        ({"scope": "channel"}, "作用域"),
        ({"match": "xxx"}, "聚合"),
        ({"type": "correlation"}, "规则类型"),
        ({"action": "drop"}, "动作"),
        ({"conditions": []}, "不能为空"),
        ({"conditions": [{"field": "x", "op": "bad", "value": 1}]}, "不支持的操作符"),
        ({"conditions": [{"field": "x", "op": "eq", "value": None}]}, "比较值"),
        # 嵌套组：三个条件组嵌套（G1>G2>G3）过深，最多两层
        ({"conditions": {"logic": "all", "items": [
            {"type": "group", "logic": "any", "items": [
                {"type": "group", "logic": "all", "items": [
                    {"type": "group", "logic": "any", "items": [{"field": "x", "op": "exists"}]},
                ]},
            ]},
        ]}}, "嵌套过深"),
        # adjust_level 动作：必须配置等级映射且键值 0-4
        ({"action": "adjust_level", "override": {}}, "等级映射"),
        ({"action": "adjust_level", "override": {"level_map": {"9": 0}}}, "等级映射"),
        ({"action": "adjust_level", "override": {"level_map": {"2": 7}}}, "等级映射"),
        # alert 动作：标签最多 10 个
        ({"override": {"tags": [f"t{i}" for i in range(11)]}}, "附加标签"),
        # 覆盖等级必须 0-4
        ({"override": {"risk_level": 9}}, "0-4"),
    ])
    def test_invalid_payload_422(self, kw, detail):
        from fastapi import HTTPException

        from app.api.v1.alert_rules import _validate

        with pytest.raises(HTTPException) as ei:
            _validate(self._payload(**kw), _FakeDB())
        assert ei.value.status_code == 422
        assert detail in ei.value.detail

    def test_adjust_level_valid_payload(self):
        from app.api.v1.alert_rules import _validate

        _validate(self._payload(
            action="adjust_level", override={"level_map": {"2": 1, "3": 2}},
        ), _FakeDB())  # 合法等级映射不抛异常

    def test_duplicate_name_422(self):
        from fastapi import HTTPException

        from app.api.v1.alert_rules import _validate

        with pytest.raises(HTTPException) as ei:
            _validate(self._payload(), _FakeDB(name_rows=[(1,)]))
        assert "已存在" in ei.value.detail

    @pytest.mark.parametrize("kw,detail", [
        ({"stats_config": None}, "stats_config"),
        ({"stats_config": {"window": {"value": 5, "unit": "week"}, "method": "count", "group_by": [], "threshold": 5}}, "窗口单位"),
        ({"stats_config": {"window": {"value": 0, "unit": "minute"}, "method": "count", "group_by": [], "threshold": 5}}, "窗口数值"),
        ({"stats_config": {"window": {"value": 5, "unit": "minute"}, "method": "sum", "group_by": [], "threshold": 5}}, "统计方式"),
        ({"stats_config": {"window": {"value": 5, "unit": "minute"}, "method": "count_distinct", "distinct_field": None, "group_by": [], "threshold": 5}}, "去重字段"),
        ({"stats_config": {"window": {"value": 5, "unit": "minute"}, "method": "count_distinct", "distinct_field": "not_a_field", "group_by": [], "threshold": 5}}, "去重字段"),
        ({"stats_config": {"window": {"value": 5, "unit": "minute"}, "method": "count", "group_by": ["not_a_field"], "threshold": 5}}, "分组字段"),
        ({"stats_config": {"window": {"value": 5, "unit": "minute"}, "method": "count", "group_by": [], "threshold": 0}}, "阈值"),
    ])
    def test_stats_config_invalid_422(self, kw, detail):
        from fastapi import HTTPException

        from app.api.v1.alert_rules import _validate

        with pytest.raises(HTTPException) as ei:
            _validate(self._stats_payload(**kw), _FakeDB())
        assert detail in ei.value.detail

    def test_stats_valid_and_action_forced_alert(self):
        from app.api.v1.alert_rules import _validate

        out = _validate(self._stats_payload(), _FakeDB())
        assert out["rule_type"] == "stats" and out["stats_config"]
        # 统计规则动作固定 alert：suppress 拒绝
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as ei:
            _validate(self._stats_payload(action="suppress"), _FakeDB())
        assert "固定" in ei.value.detail

    def test_field_mapping_invalid_422(self):
        from fastapi import HTTPException

        from app.api.v1.alert_rules import _validate

        cases = [
            ({"field_mapping": {"not_a_field": {"mode": "static", "value": "x"}}}, "标准告警模型"),
            ({"field_mapping": {"src_ip": {"mode": "map", "value": "not_a_field"}}}, "标准告警模型"),
            ({"field_mapping": {"src_ip": {"mode": "bad", "value": "x"}}}, "取值方式"),
            ({"field_mapping": {"risk_level": {"mode": "static", "value": "高"}}}, "0-4"),
        ]
        for kw, detail in cases:
            with pytest.raises(HTTPException) as ei:
                _validate(self._payload(**kw), _FakeDB())
            assert detail in ei.value.detail

    def test_field_mapping_valid(self):
        from app.api.v1.alert_rules import _validate

        out = _validate(self._payload(field_mapping={
            "alert_name": {"mode": "static", "value": "{threat_type} 告警"},
            "risk_level": {"mode": "static", "value": 1},
            "src_ip": {"mode": "map", "value": "src_ip"},
            "account_name": {"mode": "keep", "value": None},
        }), _FakeDB())
        assert out["field_mapping"]

    def test_alert_aggregation_invalid_422(self):
        from fastapi import HTTPException

        from app.api.v1.alert_rules import _validate

        cases = [
            ({"alert_aggregation": {"window": {"value": 30, "unit": "minute"}, "keys": []}}, "聚合键"),
            ({"alert_aggregation": {"window": {"value": 30, "unit": "minute"}, "keys": ["not_a_field"]}}, "标准告警模型"),
            ({"alert_aggregation": {"window": {"value": 1, "unit": "week"}, "keys": ["src_ip"]}}, "窗口单位"),
        ]
        for kw, detail in cases:
            with pytest.raises(HTTPException) as ei:
                _validate(self._payload(**kw), _FakeDB())
            assert detail in ei.value.detail

    def test_draft_flag_and_group_autocreate(self):
        from app.api.v1.alert_rules import _validate

        db = _FakeDB()
        out = _validate(self._payload(draft=True, group="自定义分组"), db)
        assert out["draft"] == 1 and out["rule_group"] == "自定义分组"
        assert len(db.added) == 1  # 分组不存在时自动创建


# ===== 序列化 =====
class TestSerialize:
    def test_serialize_new_columns(self):
        import json as _json

        from app.api.v1.alert_rules import _serialize
        from app.models.alert_rule import AlertRule

        rule = AlertRule(
            id=3, name="暴力破解统计", rule_type="stats", rule_group="暴力破解", draft=1,
            match="all",
            conditions=_json.dumps({"logic": "all", "items": [{"field": "x", "op": "exists"}]}),
            stats_config=_json.dumps({"threshold": 5}), field_mapping='{"src_ip": {"mode": "map", "value": "src_ip"}}',
            alert_aggregation='{"window": {"value": 30, "unit": "minute"}, "keys": ["src_ip"]}',
            last_test_passed_at=datetime(2026, 10, 12, 10, 0, 0),
        )
        out = _serialize(rule)
        assert out["type"] == "stats" and out["group"] == "暴力破解"
        assert out["draft"] is True and out["last_test_passed_at"] == "2026-10-12 10:00:00"
        assert out["stats_config"]["threshold"] == 5
        assert out["field_mapping"]["src_ip"]["mode"] == "map"
        assert out["alert_aggregation"]["keys"] == ["src_ip"]
        assert out["conditions"]["logic"] == "all"


# ===== 快速开始模板配置 =====
class TestTemplates:
    def test_templates_config(self):
        from app.api.v1.alert_rules import _TEMPLATES, RuleCreate, _validate

        assert len(_TEMPLATES) == 3
        keys = [t["key"] for t in _TEMPLATES]
        assert keys == ["high_risk", "bruteforce", "all_alerts"]
        rec = [t for t in _TEMPLATES if t["recommended"]]
        assert len(rec) == 1 and rec[0]["key"] == "high_risk"
        # 每个模板载荷可过校验（预填后可直接保存）
        for t in _TEMPLATES:
            _validate(RuleCreate(**t["payload"]), _FakeDB())
        # 宽松兜底走 parse_status 条件（引擎匹配前注入）
        all_t = next(t for t in _TEMPLATES if t["key"] == "all_alerts")
        assert all_t["payload"]["conditions"]["items"][0]["field"] == "parse_status"


# ===== 测试端点（load_enabled_rules 打桩，只读不落库）=====
class TestRulesTestEndpoint:
    @pytest.fixture(autouse=True)
    def _patch_loader(self, monkeypatch, request):
        rules = getattr(request, "param", [])
        monkeypatch.setattr(
            "app.api.v1.alert_rules.load_enabled_rules",
            lambda: list(rules),
        )

    def _body(self, samples, draft=None):
        from app.api.v1.alert_rules import TestBody

        return TestBody(samples=samples, draft_rule=draft)

    @pytest.mark.parametrize("_patch_loader", [[_rule(id=1, name="高危", conditions=[
        {"field": "risk_level", "op": "in", "value": [0, 1]},
    ])]], indirect=True)
    def test_rule_chain_and_final_alert(self, _patch_loader):
        from app.api.v1.alert_rules import TestSample, test_rules

        res = test_rules(self._body([TestSample(fields={"risk_level": 1})]), db=None)
        out = res["results"][0]
        assert out["final"]["outcome"] == "alert" and out["final"]["rule_id"] == 1
        assert out["chain"][0]["matched"] is True
        assert out["fields"]["risk_level"] == 1
        assert "只读" in res["note"]

    @pytest.mark.parametrize("_patch_loader", [[_rule(id=1, conditions=[
        {"field": "risk_level", "op": "in", "value": [0, 1]},
    ])]], indirect=True)
    def test_no_rule_hit_strict_note(self, _patch_loader):
        from app.api.v1.alert_rules import TestSample, test_rules

        res = test_rules(self._body([TestSample(fields={"risk_level": 3})]), db=None)
        out = res["results"][0]
        assert out["final"]["outcome"] == "no_rule"
        assert "严格模式" in out["final"]["note"]
        assert out["chain"][0]["matched"] is False

    @pytest.mark.parametrize("_patch_loader", [[_rule(id=1, name="抑制", action="suppress",
                                                      conditions=[{"field": "risk_level", "op": "exists"}])]],
                             indirect=True)
    def test_suppress_outcome(self, _patch_loader):
        from app.api.v1.alert_rules import TestSample, test_rules

        res = test_rules(self._body([TestSample(fields={"risk_level": 1})]), db=None)
        assert res["results"][0]["final"]["outcome"] == "suppressed"
        assert "抑制" in res["results"][0]["final"]["note"]

    @pytest.mark.parametrize("_patch_loader", [[_rule(id=1, name="兜底抑制", priority=100, action="suppress",
                                                      conditions=[{"field": "risk_level", "op": "exists"}])]],
                             indirect=True)
    def test_draft_rule_participates_by_priority(self, _patch_loader):
        from app.api.v1.alert_rules import RuleCreate, TestSample, test_rules

        # 库里一条 priority=100 的 suppress 规则兜底；草稿 priority=10 应排前并先命中
        draft = RuleCreate(
            name="草稿高危", priority=10, match="any", type="match",
            conditions=[{"field": "risk_level", "op": "eq", "value": 1}],
            action="alert",
        )
        res = test_rules(self._body([TestSample(fields={"risk_level": 1})], draft=draft), db=None)
        out = res["results"][0]
        assert out["final"]["rule_id"] == 0  # 草稿 id=0
        assert out["chain"][0]["rule_id"] == 0  # 草稿按 priority 排在库内规则之前
        assert out["chain"][0]["matched"] is True

    @pytest.mark.parametrize("_patch_loader", [[]], indirect=True)
    def test_field_mapping_preview(self, _patch_loader):
        from app.api.v1.alert_rules import RuleCreate, TestSample, test_rules

        draft = RuleCreate(
            name="命名草稿", match="any", type="match",
            conditions=[{"field": "risk_level", "op": "exists"}],
            action="alert",
            field_mapping={
                "alert_name": {"mode": "static", "value": "【{threat_type}】告警"},
                "risk_level": {"mode": "static", "value": 0},
            },
        )
        res = test_rules(
            self._body([TestSample(fields={"risk_level": 3, "threat_type": "Webshell"})], draft=draft),
            db=None,
        )
        out = res["results"][0]
        assert out["final"]["alert_name"] == "【Webshell】告警"
        assert out["final"]["risk_level"] == 0
        assert out["final"]["risk_level_name"] == "严重"

    @pytest.mark.parametrize("_patch_loader", [[]], indirect=True)
    def test_stats_simulation(self, _patch_loader):
        from app.api.v1.alert_rules import RuleCreate, StatsConfigBody, TestSample, test_rules

        draft = RuleCreate(
            name="统计草稿", type="stats", action="alert", priority=10,
            conditions=[{"field": "threat_type", "op": "eq", "value": "暴力破解"}],
            stats_config=StatsConfigBody(
                window={"value": 5, "unit": "minute"}, method="count",
                group_by=["src_ip"], threshold=3,
            ),
        )
        samples = [TestSample(fields={"threat_type": "暴力破解", "src_ip": "1.1.1.1", "risk_level": 2})
                   for _ in range(3)]
        res = test_rules(self._body(samples, draft=draft), db=None)
        # 前两条：计入窗口未达阈值；第三条：触发产生告警
        assert res["results"][0]["final"]["outcome"] == "stats_waiting"
        assert "1/3" in res["results"][0]["final"]["note"]
        assert res["results"][1]["final"]["outcome"] == "stats_waiting"
        final = res["results"][2]["final"]
        assert final["outcome"] == "alert" and final["action"] == "stats"
        assert final["stats"]["count"] == 3 and final["stats"]["triggered"] is True
        # 逐样例统计明细（分组键 → 计数）
        assert res["results"][0]["stats"][0]["group_key"] == "1.1.1.1"
        assert [s["stats"][0]["count"] for s in res["results"]] == [1, 2, 3]

    @pytest.mark.parametrize("_patch_loader", [[]], indirect=True)
    def test_samples_limit(self, _patch_loader):
        import pydantic

        from app.api.v1.alert_rules import RuleCreate, TestBody, TestSample

        draft = RuleCreate(name="草稿", conditions=[{"field": "x", "op": "exists"}])
        samples = [TestSample(fields={}) for _ in range(11)]
        # 样例上限 10 条由 Pydantic 在解析期拦截（422）
        with pytest.raises(pydantic.ValidationError):
            TestBody(samples=samples, draft_rule=draft)
