"""标准告警模型（normalized model）。

所有解析策略产出的统一落库结构，供告警列表、监控和下游自动封禁工作流消费。
字段分组见模块 docstring；extensions 存放策略特有的、标准模型未覆盖的所有字段。
"""
from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.core.timezone import beijing_now
from app.database import Base


class AlertEvent(Base):
    """标准告警事件。"""

    __tablename__ = "alert_events"

    # ===== 标识与租户 =====
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(128), unique=True, index=True, nullable=False, comment="告警唯一ID")
    seq_id = Column(String(128), default="", comment="序列号")
    tenant = Column(String(128), default="", index=True, comment="租户")
    customer = Column(String(128), default="", comment="客户")
    data_version = Column(String(32), default="", comment="数据版本")

    # ===== 来源设备 =====
    strategy_id = Column(Integer, nullable=True, index=True, comment="使用的解析策略 ID")
    device_type = Column(String(64), default="", comment="设备类型，如 sangfor_xdr")
    devices = Column(Text, default="[]", comment="设备详情数组 JSON")
    agent_id = Column(String(128), default="", comment="Agent ID")

    # ===== 资产与主体 =====
    host_ip = Column(String(255), default="", comment="主机 IP（可能是数组 JSON 字符串）")
    asset_id = Column(String(128), default="", comment="资产 ID")
    region_id = Column(String(128), default="", comment="区域 ID")
    relate_asset_type = Column(Integer, default=0, comment="0 主机 / 1 容器")
    relate_asset_type_name = Column(String(16), default="", comment="资产类型中文：主机/容器")
    group_id = Column(String(128), default="", comment="分组 ID")
    subject_type = Column(String(64), default="", comment="主体类型")
    user_name = Column(String(255), default="", comment="用户名")
    account_id = Column(String(128), default="", comment="账号 ID")
    account_name = Column(String(255), default="", comment="账号名")

    # ===== 时间（统一北京时间 naive datetime）=====
    first_timestamp = Column(DateTime, nullable=True, comment="首次发生时间")
    last_timestamp = Column(DateTime, nullable=True, comment="最近发生时间")
    occur_timestamp = Column(DateTime, nullable=True, comment="告警发生时间")
    upload_timestamp = Column(DateTime, nullable=True, comment="上报时间戳（转换后）")
    upload_time = Column(DateTime, nullable=True, comment="上报时间")
    upload_time_raw = Column(String(64), default="", comment="上报时间原始字符串")
    time_region = Column(String(32), default="", comment="时区，如 GMT+08:00")

    # ===== 告警内容 =====
    attack_state = Column(Integer, default=-1, comment="攻击状态 int")
    attack_state_name = Column(String(32), default="", comment="攻击状态中文")
    alert_name = Column(String(512), default="", comment="告警名称")
    description = Column(Text, default="", comment="告警描述")
    recommendation = Column(Text, default="", comment="处置建议")
    risk_tag = Column(Text, default="[]", comment="风险标签 JSON 数组")

    # ===== 源目的 =====
    src_ip = Column(Text, default="", comment="源 IP（可能是数组 JSON 字符串）")
    src_port = Column(String(64), default="", comment="源端口")
    src_asset_id = Column(String(128), default="", comment="源资产 ID")
    src_ip_tag = Column(String(255), default="", comment="源 IP 标签")
    src_ip_tag_name = Column(String(16), default="", comment="源 IP 标签中文：内网/外网")
    src_region_id = Column(String(128), default="", comment="源区域 ID")
    src_region_name = Column(String(255), default="", comment="源区域名")
    dst_ip = Column(Text, default="", comment="目的 IP（可能是数组 JSON 字符串）")
    dst_port = Column(String(64), default="", comment="目的端口")
    dst_asset_id = Column(String(128), default="", comment="目的资产 ID")
    dst_region_id = Column(String(128), default="", comment="目的区域 ID")
    dst_region_name = Column(String(255), default="", comment="目的区域名")
    direction = Column(String(32), default="", comment="方向")
    direction_name = Column(String(16), default="", comment="方向中文：内到外/外到内等")
    protocol = Column(String(32), default="", comment="协议")
    xff_client_ip = Column(String(255), default="", comment="XFF 客户端 IP")
    src_country = Column(String(128), default="", comment="源国家")
    src_province = Column(String(128), default="", comment="源省份")
    src_city = Column(String(128), default="", comment="源城市")

    # ===== 等级 =====
    risk_level = Column(Integer, default=-1, comment="风险等级 int")
    risk_level_name = Column(String(32), default="", comment="风险等级中文")
    severity = Column(Integer, default=-1, comment="严重度 0-100")
    confidence = Column(Integer, default=-1, comment="置信度 0-100")

    # ===== 分类 =====
    threat_class = Column(String(128), default="", comment="威胁大类")
    threat_type = Column(String(128), default="", comment="威胁类型")
    threat_sub_type = Column(String(128), default="", comment="威胁子类型")
    threat_define = Column(Text, default="{}", comment="威胁定义 JSON")
    attck_technique = Column(Text, default="[]", comment="ATT&CK 技术 JSON")
    stage = Column(Integer, default=-1, comment="攻击阶段 int")
    stage_name = Column(String(64), default="", comment="攻击阶段中文")

    # ===== 处置 =====
    deal_status = Column(Integer, default=-1, comment="处置状态 int")
    deal_status_name = Column(String(64), default="", comment="处置状态中文")

    # ===== 举证与扩展 =====
    proof_type = Column(String(64), default="", comment="举证类型")
    proof_description = Column(Text, default="", comment="举证描述")
    base_content = Column(Text, default="", comment="基础内容")
    extensions = Column(Text, default="{}", comment="策略特有扩展字段 JSON")

    # ===== 系统字段 =====
    raw_data = Column(Text, default="", comment="原始 JSON 全文")
    parse_status = Column(String(16), default="success", index=True, comment="success/partial/fail")
    parse_warnings = Column(Text, default="[]", comment="校验警告 JSON 列表")
    created_at = Column(DateTime, default=beijing_now)

    # 组合索引：告警列表常用过滤（发生时间 + 等级 + 处置状态）
    __table_args__ = (
        Index("ix_alert_events_occur_risk_deal", "occur_timestamp", "risk_level", "deal_status"),
    )

    def __repr__(self):
        return f"<AlertEvent uuid={self.uuid!r} status={self.parse_status!r}>"
