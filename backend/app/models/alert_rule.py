"""告警规则模型（alert_rules 表）。

流水线 alert_rule 阶段消费：解析成功的日志按优先级匹配启用中的规则，
- 匹配类（rule_type=match）：命中即按动作处理——alert 产生告警 /
  suppress 抑制 / adjust_level 调整等级（严格模式：未命中不产生告警）；
- 统计类（rule_type=stats）：条件为输入筛选，滑动窗口内（基于
  occur_timestamp）按分组键计数，达到阈值时对触发的当前事件产生告警；
- 关联类（rule_type=correlation）：P2 预留，暂不支持。

XDR 风格扩展列：rule_group（分组树）/ stats_config（统计配置 JSON）/
field_mapping（字段配置：静态值 / 字段映射 / 保留）/ alert_aggregation
（告警侧聚合配置 JSON，null 不启用）/ draft（草稿，草稿不参与线上匹配）/
last_test_passed_at（最近一次发布测试通过时间，发布门禁依据）。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.timezone import beijing_now
from app.database import Base


class AlertRule(Base):
    """告警规则（匹配 / 统计）。"""

    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, comment="规则名称（全局唯一）")
    description = Column(String(512), default="", comment="规则说明")
    enabled = Column(Integer, default=1, index=True, comment="1 启用 / 0 停用")
    priority = Column(Integer, default=100, comment="匹配优先级，数值越小越先匹配")
    # 作用域：global 全局 / device_type 按设备类型（需填 device_type）
    scope = Column(String(16), default="global", comment="作用域：global / device_type")
    device_type = Column(String(64), default="", comment="scope=device_type 时生效的设备类型")
    # 条件聚合：all 全部满足 / any 任一满足（旧版扁平条件结构使用；
    # 新版嵌套结构 {logic, items} 的顶层逻辑存于 conditions JSON 内）
    match = Column(String(8), default="all", comment="条件聚合：all / any")
    # 条件 JSON。两种结构：
    #   旧版扁平：[{"field": "risk_level", "op": "in", "value": [0, 1]}, ...]（顶层逻辑取 match 列）
    #   新版嵌套：{"logic": "all", "items": [叶条件 | {"type": "group", "logic": "any", "items": [...]}]}
    # 组最多两层嵌套；op 语义与流水线 Filter 阶段一致
    conditions = Column(Text, default="[]", comment="匹配条件 JSON（扁平或嵌套结构）")
    rule_type = Column(String(16), default="match", comment="规则类型：match 匹配 / stats 统计（correlation 预留）")
    action = Column(String(16), default="alert", comment="命中动作：alert 产生告警 / suppress 抑制 / adjust_level 调整等级")
    # 覆盖项 JSON（按动作取用）：
    #   alert        → {"tags": ["重点关注"]}（名称/等级改用 field_mapping）
    #   suppress     → {"reason": "健康检查噪音"}
    #   adjust_level → {"level_map": {"0": 0, "1": 0, "2": 1, "3": 2, "4": 3}}
    override = Column(Text, default="{}", comment="动作参数 JSON")
    # 统计配置 JSON（仅 rule_type=stats）：
    #   {"window": {"value": 5, "unit": "minute"}, "method": "count|count_distinct",
    #    "distinct_field": "src_ip", "group_by": ["src_ip"], "threshold": 10}
    stats_config = Column(Text, default="", comment="统计配置 JSON（空串=非统计规则）")
    # 字段配置 JSON（XDR 双控件）：{字段名: {"mode": "static|map|keep", "value": ...}}
    #   static=静态值（告警名称支持 {field} 变量插值）/ map=字段映射（值为解析字段名）/ keep=保留解析结果
    field_mapping = Column(Text, default="{}", comment="输出字段配置 JSON")
    # 告警聚合配置 JSON（告警生成侧同键同窗合并；空串=不启用）：
    #   {"window": {"value": 30, "unit": "minute"}, "keys": ["src_ip", "threat_type"]}
    alert_aggregation = Column(Text, default="", comment="告警聚合配置 JSON")
    rule_group = Column(String(64), default="其他", comment="规则分组名（分组树管理，删除分组时移入「其他」）")
    draft = Column(Integer, default=0, index=True, comment="1 草稿（不参与线上匹配）/ 0 已发布")
    last_test_passed_at = Column(DateTime, nullable=True, comment="最近一次发布测试通过时间")
    hit_count = Column(Integer, default=0, comment="累计命中次数")
    created_by = Column(String(128), default="", comment="创建人用户名")
    updated_by = Column(String(128), default="", comment="最近更新人用户名")
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    def __repr__(self):
        return f"<AlertRule id={self.id} name={self.name!r} type={self.rule_type!r} action={self.action!r} enabled={self.enabled}>"
