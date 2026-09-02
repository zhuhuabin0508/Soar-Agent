"""5 条覆盖不同风险等级、解析状态的测试样例 + 异常场景测试。

样例设计：
1. 样例A：riskLevel=0（严重）完整字段 → success，全枚举翻译，扩展归档完整
2. 样例B：riskLevel=1（高危）部分字段缺失（无 severity/confidence/容器字段）→ success/partial
3. 样例C：riskLevel=2（中危）uuid 非法格式 + srcIp 含非法 IP → partial（校验警告）
4. 样例D：riskLevel=5（未知）severity 超范围 + occurTimestamp 缺失 → partial
5. 样例E：riskLevel=3（低危）required uuid 缺失 → partial（required 警告）

异常场景：
- 无策略匹配 → fail + no_strategy_matched
- data 缺失 → 解包警告，字段全默认值 → partial
- uuid 重复推送 → duplicate 幂等跳过

运行：docker exec soar-backend-dev python /app/tests/test_sangfor_strategy.py
"""
import json
import sys

sys.path.insert(0, "/app")

from app.engine.parser_engine import ParseEngine
from app.engine.strategy_loader import StrategyLoader
from app.engine.strategy_seed import load_builtin_strategy


def build_loader() -> StrategyLoader:
    """用内置 Sangfor XDR 策略文件构造 loader（不依赖数据库）。"""
    config = load_builtin_strategy("sangfor_xdr_v130.json")
    assert config, "内置策略文件读取失败"
    return StrategyLoader(
        strategies=[{"id": 1, "status": "enabled", "version": config["version"], "config": config}]
    )


def base_alert(**overrides) -> dict:
    """构造一条完整的 Sangfor XDR 告警骨架。"""
    data = {
        "uuId": "alert-1787700000-abcde",
        "v": 1,
        "seqId": "SEQ-001",
        "tenant": "default",
        "customer": "客户A",
        "devices": {"devUId": "dev-001", "devUName": "核心交换机"},
        "agentId": "agent-001",
        "hostIp": "192.168.1.100,192.168.1.101",
        "groupId": "g-001",
        "assetId": "asset-001",
        "regionId": "region-001",
        "relateAssetType": 0,
        "subjectType": ["host"],
        "xUserUId": "xu-001",
        "xUserId": "xid-001",
        "xUserName": "张三",
        "xUserGroup": "运维组",
        "xUserGroupId": "xg-001",
        "xUserDomain": "corp.local",
        "accountId": "acc-001",
        "accountName": "zhangsan",
        "containerName": "",
        "clusterName": "",
        "firstTimestamp": 1787699900,
        "lastTimestamp": 1787700000,
        "occurTimestamp": 1787700000,
        "uploadTimestamp": 1787700100,
        "uploadTime": "2026-08-26 10:01:40",
        "timeRegion": "GMT+08:00",
        "attackState": 2,
        "name": "暴力破解告警",
        "description": "检测到 SSH 暴力破解行为",
        "recommendation": "建议立即封禁源 IP",
        "riskTag": ["恶意IP", "暴力破解"],
        "srcIp": ["1.2.3.4"],
        "srcPort": "12345",
        "srcAssetId": "",
        "srcIpTag": 1,
        "srcRegionId": "r-001",
        "srcRegionName": "华东",
        "dstIp": ["192.168.1.100"],
        "dstPort": "22",
        "dstAssetId": "asset-001",
        "dstRegionId": "r-001",
        "dstRegionName": "内网",
        "direction": 2,
        "protocol": "TCP",
        "xffClientIp": ["1.2.3.4"],
        "xffClientIpCountry": "中国",
        "xffClientIpProvince": "浙江",
        "xffClientIpCity": "杭州",
        "srcAssetTag": "DMZ",
        "riskLevel": 0,
        "severity": 90,
        "confidence": 85,
        "threatClass": "暴力破解",
        "threatType": "SSH暴力破解",
        "threatSubType": "密码猜测",
        "threatDefine": [{"tid": "T1110"}],
        "stage": 30,
        "attckTechnique": ["T1110", "T1110.001"],
        "alertRuleId": "rule-001",
        "alertEngine": "引擎A",
        "ruleIds": ["r1", "r2"],
        "dealStatus": 0,
        "responseAction": "block",
        "proofType": ["pcap"],
        "proofDescription": "抓包证据",
        "baseContent": "原始日志内容",
        "threatDetail": "威胁详情",
        "analysisInfo": "分析详情",
        "clusterId": "c-001",
        "combineType": 0,
        "highlight": "高亮",
        "dealMsg": "处置消息",
        "logIds": ["log1", "log2"],
        "logCount": 15,
        "devUId": "dev-001",
        "devUName": "核心交换机",
        "groupMapFlag": 1,
        "groupMapReference": "ref-001",
    }
    data.update(overrides)
    return {
        "sendTime": "2026-08-26 10:00:00",
        "tenant": "default",
        "type": "security_alert",
        "version": "1.30",
        "refreshTime": "2026-08-26 10:00:05",
        "alertType": "host",
        "data": data,
    }


# ======================================================================
# 5 条测试样例
# ======================================================================
def test_sample_a_critical_success():
    """样例A：riskLevel=0 严重，全字段 → success。"""
    engine = ParseEngine(loader=build_loader(), sink=None)
    raw = base_alert(riskLevel=0)
    result = engine.parse_one(raw)

    assert result.status == "success", f"警告: {result.warnings}"
    f = result.fields
    # 枚举翻译
    assert f["risk_level"] == 0 and f["risk_level_name"] == "严重"
    assert f["attack_state"] == 2 and f["attack_state_name"] == "成功"
    assert f["src_ip_tag"] == 1 and f["src_ip_tag_name"] == "外网"
    assert f["direction"] == 2 and f["direction_name"] == "外到内"
    assert f["stage"] == 30 and f["stage_name"] == "遭受攻击"
    assert f["deal_status"] == 0 and f["deal_status_name"] == "未处置"
    assert f["relate_asset_type"] == 0 and f["relate_asset_type_name"] == "主机"
    # 类型转换
    assert f["host_ip"] == json.dumps(["192.168.1.100", "192.168.1.101"], ensure_ascii=False)
    assert f["risk_tag"] == json.dumps(["恶意IP", "暴力破解"], ensure_ascii=False)
    assert f["severity"] == 90 and f["confidence"] == 85 and f["data_version"] == 1
    assert f["occur_timestamp"].year == 2026
    # 扩展归档（header + extension_fields）
    ext = json.loads(f["extensions"])
    for key in ["sendTime", "refreshTime", "alertType", "devUId", "devUName",
                "logIds", "logCount", "analysisInfo", "clusterId", "combineType",
                "xUserUId", "xUserGroup", "xUserDomain", "srcAssetTag",
                "alertRuleId", "alertEngine", "ruleIds", "responseAction", "threatDetail"]:
        assert key in ext, f"extensions 缺少 {key}"
    print("PASS: 样例A 严重(riskLevel=0) 完整 success")


def test_sample_b_high_partial_fields():
    """样例B：riskLevel=1 高危，缺失 severity/confidence/容器字段 → success。"""
    engine = ParseEngine(loader=build_loader(), sink=None)
    raw = base_alert(riskLevel=1)
    for key in ["severity", "confidence", "containerName", "clusterName",
                "threatDefine", "attckTechnique", "proofType"]:
        raw["data"].pop(key, None)
    result = engine.parse_one(raw)

    assert result.status == "success", f"警告: {result.warnings}"
    f = result.fields
    assert f["risk_level"] == 1 and f["risk_level_name"] == "高危"
    # 缺失字段填类型默认值
    assert f["severity"] == 0 and f["confidence"] == 0
    assert f["threat_define"] == "[]" and f["attck_technique"] == "[]"
    print("PASS: 样例B 高危(riskLevel=1) 缺失字段默认值填充")


def test_sample_c_medium_validation_warnings():
    """样例C：riskLevel=2 中危，uuid 非法 + srcIp 含非法 IP → partial。"""
    engine = ParseEngine(loader=build_loader(), sink=None)
    raw = base_alert(riskLevel=2, uuId="bad-uuid-format", srcIp=["999.999.1.1", "1.2.3.4"])
    result = engine.parse_one(raw)

    assert result.status == "partial"
    rules = {w["rule"] for w in result.warnings}
    assert "regex" in rules and "ip_list_valid" in rules
    assert result.fields["risk_level"] == 2 and result.fields["risk_level_name"] == "中危"
    # 警告已序列化入库
    assert len(json.loads(result.fields["parse_warnings"])) == len(result.warnings)
    print(f"PASS: 样例C 中危(riskLevel=2) 校验警告降级 partial（{len(result.warnings)} 条）")


def test_sample_d_unknown_out_of_range():
    """样例D：riskLevel=5 未知，severity 超范围 + occurTimestamp 缺失 → partial。"""
    engine = ParseEngine(loader=build_loader(), sink=None)
    raw = base_alert(riskLevel=5, severity=150)
    raw["data"].pop("occurTimestamp", None)
    result = engine.parse_one(raw)

    assert result.status == "partial"
    rules = {w["rule"] for w in result.warnings}
    assert "range" in rules, f"期望 range 警告，实际 {rules}"
    assert result.fields["risk_level"] == 5 and result.fields["risk_level_name"] == "未知"
    assert result.fields["severity"] == 150
    assert result.fields["occur_timestamp"] is None
    print("PASS: 样例D 未知(riskLevel=5) severity 超范围 partial")


def test_sample_e_low_required_uuid_missing():
    """样例E：riskLevel=3 低危，required uuid 缺失 → partial（required 警告）。"""
    engine = ParseEngine(loader=build_loader(), sink=None)
    raw = base_alert(riskLevel=3)
    raw["data"].pop("uuId", None)
    result = engine.parse_one(raw)

    assert result.status == "partial"
    assert any(w.get("source") == "uuId" or w.get("field") == "uuid" for w in result.warnings)
    assert result.fields["risk_level"] == 3 and result.fields["risk_level_name"] == "低危"
    print("PASS: 样例E 低危(riskLevel=3) required uuid 缺失 partial")


# ======================================================================
# 异常场景
# ======================================================================
def test_no_strategy_matched():
    """异常1：无策略匹配 → fail + no_strategy_matched + 错误队列。"""
    class MemorySink:
        def __init__(self):
            self.errors = []

        def save_alert(self, fields):
            return "inserted"

        def save_error(self, raw_data, error_type, error_msg, uuid=None, strategy_id=None):
            self.errors.append(error_type)

        def record_metrics(self, *args, **kwargs):
            pass

    sink = MemorySink()
    engine = ParseEngine(loader=build_loader(), sink=sink)
    stats = engine.process([{"type": "firewall_syslog", "data": {"msg": "x"}}])

    assert stats["fail"] == 1 and stats["success"] == 0
    assert sink.errors == ["no_strategy_matched"]
    print("PASS: 异常1 无策略匹配 → 错误队列")


def test_data_missing():
    """异常2：data 缺失 → 解包警告，字段全默认 → partial。"""
    engine = ParseEngine(loader=build_loader(), sink=None)
    raw = {"sendTime": "2026-08-26 10:00:00", "type": "security_alert", "version": "1.30"}
    result = engine.parse_one(raw)

    # data 缺失 → 所有映射字段取默认值，uuid 也为空
    assert result.status == "partial"
    assert any("解包" in w.get("message", "") or w.get("source") == "uuId" for w in result.warnings)
    f = result.fields
    assert f.get("alert_name", "") == ""
    assert f.get("severity", -1) == 0
    print("PASS: 异常2 data 缺失 → 默认值 + partial")


def test_uuid_duplicate_idempotent():
    """异常3：uuid 重复推送 → duplicate 幂等跳过（不入库第二条）。"""
    class MemorySink:
        def __init__(self):
            self.alerts = []

        def save_alert(self, fields):
            if any(a["uuid"] == fields["uuid"] for a in self.alerts):
                return "duplicate"
            self.alerts.append(fields)
            return "inserted"

        def save_error(self, *args, **kwargs):
            pass

        def record_metrics(self, *args, **kwargs):
            pass

    sink = MemorySink()
    engine = ParseEngine(loader=build_loader(), sink=sink)
    raw = base_alert(riskLevel=1)

    stats1 = engine.process([raw])
    stats2 = engine.process([raw])  # 同 uuid 再推

    assert stats1["success"] == 1 and stats1["duplicates"] == 0
    assert stats2["duplicates"] == 1
    assert len(sink.alerts) == 1, "重复 uuid 不应入库第二条"
    print("PASS: 异常3 uuid 重复幂等跳过")


if __name__ == "__main__":
    test_sample_a_critical_success()
    test_sample_b_high_partial_fields()
    test_sample_c_medium_validation_warnings()
    test_sample_d_unknown_out_of_range()
    test_sample_e_low_required_uuid_missing()
    test_no_strategy_matched()
    test_data_missing()
    test_uuid_duplicate_idempotent()
    print("\n全部测试通过 ✓")
