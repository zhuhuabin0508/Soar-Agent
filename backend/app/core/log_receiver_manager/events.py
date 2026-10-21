"""统一事件模型：RawEvent（适配器输出）+ NormalizedEvent（ECS 风格范式化事件）。

设计要点：
- 所有 7 种输入适配器统一输出 :class:`RawEvent`，进入可插拔总线；
- :class:`NormalizedEvent` 是流水线中间表示（ECS 风格字段命名），末端经
  ``to_alert_fields()`` 无损映射回 AlertEvent 列名 dict 落库——
  ParseEngine 输出的 fields 本就是 AlertEvent 列名 dict，因此
  ``from_parse_result → to_alert_fields`` 可逐键往返（见 _ALERT_FIELD_MAP），
  实现"统一 schema"且下游（告警页/工作流/看板）零改动。
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ----------------------------------------------------------------------
# RawEvent：适配器输出的标准原始事件（所有源类型统一结构）
# ----------------------------------------------------------------------
@dataclass
class RawEvent:
    """标准原始事件。"""

    receiver_id: int
    device_id: Optional[int]
    source_type: str            # = LogReceiver.protocol（syslog/kafka/jdbc/...）
    source_ip: Optional[str]    # syslog 对端 / netflow exporter；拉取类为远端地址
    transport: str              # udp/tcp/kafka/jdbc/rest_api/file/pcap/snmp
    received_at: datetime
    raw: str                    # 原始报文文本
    meta: dict = field(default_factory=dict)       # topic/partition、游标等适配器附加信息
    receiver: dict = field(default_factory=dict)   # 渠道配置快照（扁平 dict，沿用现有结构）

    def to_dict(self) -> dict:
        """序列化为可 JSON 化 dict（跨进程总线如 KafkaBus 使用）。"""
        return {
            "receiver_id": self.receiver_id,
            "device_id": self.device_id,
            "source_type": self.source_type,
            "source_ip": self.source_ip,
            "transport": self.transport,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "raw": self.raw,
            "meta": self.meta,
            "receiver": self.receiver,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RawEvent":
        """从 to_dict 的输出还原（与 to_dict 互逆）。"""
        received_at = d.get("received_at")
        if isinstance(received_at, str):
            received_at = datetime.fromisoformat(received_at)
        return cls(
            receiver_id=d["receiver_id"],
            device_id=d.get("device_id"),
            source_type=d.get("source_type") or "",
            source_ip=d.get("source_ip"),
            transport=d.get("transport") or "",
            received_at=received_at or datetime.now(),
            raw=d.get("raw") or "",
            meta=d.get("meta") or {},
            receiver=d.get("receiver") or {},
        )


# ----------------------------------------------------------------------
# NormalizedEvent：ECS 风格范式化事件（流水线中间表示）
# ----------------------------------------------------------------------
# ECS 属性名 → AlertEvent 列名。命中的键在 from_parse_result 时提为事件属性，
# 其余键（extensions/parse_warnings/risk_tag 等 JSON 字符串与策略自定义键）
# 原样进入 extra_fields 透传，保证往返无损。
_ALERT_FIELD_MAP: dict[str, str] = {
    # 事件内容（ECS event.*）
    "uuid": "uuid",
    "alert_name": "alert_name",
    "description": "description",
    "recommendation": "recommendation",
    "base_content": "base_content",
    "proof_type": "proof_type",
    "proof_description": "proof_description",
    # 等级
    "risk_level": "risk_level",
    "risk_level_name": "risk_level_name",
    "severity": "severity",
    "confidence": "confidence",
    # 威胁分类
    "threat_class": "threat_class",
    "threat_type": "threat_type",
    "threat_sub_type": "threat_sub_type",
    "attack_state": "attack_state",
    "attack_state_name": "attack_state_name",
    "stage": "stage",
    "stage_name": "stage_name",
    "deal_status": "deal_status",
    "deal_status_name": "deal_status_name",
    # 源/目的（ECS source.* / destination.*）
    "src_ip": "src_ip",
    "src_port": "src_port",
    "src_asset_id": "src_asset_id",
    "src_ip_tag": "src_ip_tag",
    "src_ip_tag_name": "src_ip_tag_name",
    "src_region_id": "src_region_id",
    "src_region_name": "src_region_name",
    "src_country": "src_country",
    "src_province": "src_province",
    "src_city": "src_city",
    "dst_ip": "dst_ip",
    "dst_port": "dst_port",
    "dst_asset_id": "dst_asset_id",
    "dst_region_id": "dst_region_id",
    "dst_region_name": "dst_region_name",
    "direction": "direction",
    "direction_name": "direction_name",
    "protocol": "protocol",
    "xff_client_ip": "xff_client_ip",
    # 主体（ECS host.* / user.*）
    "host_ip": "host_ip",
    "asset_id": "asset_id",
    "region_id": "region_id",
    "group_id": "group_id",
    "subject_type": "subject_type",
    "user_name": "user_name",
    "account_id": "account_id",
    "account_name": "account_name",
    "agent_id": "agent_id",
    # 时间
    "occur_timestamp": "occur_timestamp",
    "first_timestamp": "first_timestamp",
    "last_timestamp": "last_timestamp",
    "upload_timestamp": "upload_timestamp",
    "upload_time": "upload_time",
    "upload_time_raw": "upload_time_raw",
    "time_region": "time_region",
    # 规则元数据
    "strategy_id": "strategy_id",
    "device_type": "device_type",
    "rule_id": "rule_id",
    "log_type": "log_type",
    "parse_status": "parse_status",
    # 原文兜底
    "raw_data": "raw_data",
}
# 反向映射（AlertEvent 列名 → ECS 属性名）
_ECS_ATTR_MAP: dict[str, str] = {v: k for k, v in _ALERT_FIELD_MAP.items()}


@dataclass
class NormalizedEvent:
    """ECS 风格范式化事件（流水线 Filter/Enricher/Translator 阶段操作对象）。

    仅当输入 fields 中**实际存在**某键时才设置对应属性并记入 ``_present``；
    ``to_alert_fields()`` 只输出显式设置过的属性 + extra_fields，
    从而保证 ``from_parse_result(result.fields) → to_alert_fields()`` 与原
    fields **逐键等价**（不引入缺省键、不丢键、不改值）。
    """

    # ECS event.*
    uuid: Any = None
    alert_name: Any = None
    description: Any = None
    recommendation: Any = None
    base_content: Any = None
    proof_type: Any = None
    proof_description: Any = None
    risk_level: Any = None
    risk_level_name: Any = None
    severity: Any = None
    confidence: Any = None
    threat_class: Any = None
    threat_type: Any = None
    threat_sub_type: Any = None
    attack_state: Any = None
    attack_state_name: Any = None
    stage: Any = None
    stage_name: Any = None
    deal_status: Any = None
    deal_status_name: Any = None
    # ECS source.* / destination.*
    src_ip: Any = None
    src_port: Any = None
    src_asset_id: Any = None
    src_ip_tag: Any = None
    src_ip_tag_name: Any = None
    src_region_id: Any = None
    src_region_name: Any = None
    src_country: Any = None
    src_province: Any = None
    src_city: Any = None
    dst_ip: Any = None
    dst_port: Any = None
    dst_asset_id: Any = None
    dst_region_id: Any = None
    dst_region_name: Any = None
    direction: Any = None
    direction_name: Any = None
    protocol: Any = None
    xff_client_ip: Any = None
    # ECS host.* / user.*
    host_ip: Any = None
    asset_id: Any = None
    region_id: Any = None
    group_id: Any = None
    subject_type: Any = None
    user_name: Any = None
    account_id: Any = None
    account_name: Any = None
    agent_id: Any = None
    # 时间
    occur_timestamp: Any = None
    first_timestamp: Any = None
    last_timestamp: Any = None
    upload_timestamp: Any = None
    upload_time: Any = None
    upload_time_raw: Any = None
    time_region: Any = None
    # 规则元数据
    strategy_id: Any = None
    device_type: Any = None
    rule_id: Any = None
    log_type: Any = None
    parse_status: Any = None
    raw_data: Any = None

    # 未列入 _ALERT_FIELD_MAP 的键（extensions/parse_warnings/devices/risk_tag/
    # attck_technique/threat_define 及策略自定义键）原样透传
    extra_fields: dict = field(default_factory=dict)
    # 记录哪些 ECS 属性来自输入 fields（其余保持 None 不参与输出）
    _present: set = field(default_factory=set)
    # 流水线附加信息（富化结果等），不影响落库字段
    enrichments: dict = field(default_factory=dict)
    ecs_version: str = "soar-ecs-1.0"

    # ------------------------------------------------------------------
    # ParseResult.fields（AlertEvent 列名 dict）→ NormalizedEvent
    # ------------------------------------------------------------------
    @classmethod
    def from_parse_result(cls, result) -> "NormalizedEvent":
        """ParseEngine 的 ParseResult → ECS 风格事件（无损：键/值原样搬运）。"""
        ev = cls()
        for key, value in (result.fields or {}).items():
            attr = _ECS_ATTR_MAP.get(key)
            if attr is not None:
                setattr(ev, attr, value)
                ev._present.add(attr)
            else:
                ev.extra_fields[key] = value
        return ev

    # ------------------------------------------------------------------
    # NormalizedEvent → AlertEvent 兼容 dict（与 ParseEngine 输出逐键等价）
    # ------------------------------------------------------------------
    def to_alert_fields(self) -> dict:
        """ECS 字段 + extra_fields 合并为 AlertEvent(**fields) 兼容 dict。

        与 ``from_parse_result`` 的输入逐键等价：只输出显式设置过的 ECS
        属性与透传的 extra_fields，不引入缺省键。
        """
        out: dict[str, Any] = dict(self.extra_fields)
        for attr in self._present:
            out[_ALERT_FIELD_MAP[attr]] = getattr(self, attr)
        return out

    def get_field(self, alert_key: str) -> Any:
        """按 AlertEvent 列名读取字段值（Filter/Enricher/Translator 统一取值入口）。"""
        attr = _ECS_ATTR_MAP.get(alert_key)
        if attr is not None and attr in self._present:
            return getattr(self, attr)
        return self.extra_fields.get(alert_key)

    def set_field(self, alert_key: str, value: Any) -> None:
        """按 AlertEvent 列名写入字段值（仅当目标为空时补填请先查 get_field）。"""
        attr = _ECS_ATTR_MAP.get(alert_key)
        if attr is not None:
            setattr(self, attr, value)
            self._present.add(attr)
        else:
            self.extra_fields[alert_key] = value

    def to_ecs_dict(self) -> dict:
        """输出 ECS 视图 dict（展示/调试用；键为 ECS 属性名 + extra）。"""
        out = {attr: getattr(self, attr) for attr in self._present}
        out.update(self.extra_fields)
        out["_ecs_version"] = self.ecs_version
        return out

    def to_json(self) -> str:
        """序列化为 JSON 字符串（datetime 值转 isoformat）。"""
        def _default(o):
            if isinstance(o, datetime):
                return o.isoformat()
            raise TypeError(f"不可序列化: {type(o)!r}")

        return json.dumps(self.to_ecs_dict(), ensure_ascii=False, default=_default)
