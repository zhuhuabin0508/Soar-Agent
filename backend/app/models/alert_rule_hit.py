"""告警规则命中记录模型（alert_rule_hits 表）。

alert_rule 阶段每次规则命中（含抑制/调整等级）写入一行，用于：
- 规则列表「今日命中 / 累计命中 / 最近触发」统计；
- 命中日志抽屉（时间、来源 IP、告警名称、风险等级、解析状态）；
- 「24h 无命中」疑似失效检测。

保留策略：仅保留最近 7 天（引擎写入时按小时级节流清理）。
alert/suppress/adjust_level 三类动作均记录；rule_name 冗余存储，
规则删除后历史命中仍可读。uuid 为该条日志关联的告警 UUID
（suppress 命中时日志仍带 uuid，便于追溯）。
"""
from sqlalchemy import Column, DateTime, Index, Integer, String

from app.core.timezone import beijing_now
from app.database import Base


class AlertRuleHit(Base):
    """告警规则命中记录。"""

    __tablename__ = "alert_rule_hits"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, nullable=False, index=True, comment="命中的告警规则 ID")
    rule_name = Column(String(255), default="", comment="规则名称（冗余，规则删除后仍可读）")
    action = Column(String(16), default="alert", comment="命中动作：alert / suppress / adjust_level")
    uuid = Column(String(128), default="", index=True, comment="该条日志的告警 UUID")
    source_ip = Column(String(255), default="", comment="来源 IP")
    alert_name = Column(String(512), default="", comment="告警名称（命中时刻）")
    risk_level = Column(Integer, default=-1, comment="风险等级（应用覆盖/映射后）")
    parse_status = Column(String(16), default="", comment="解析状态")
    matched_at = Column(DateTime, default=beijing_now, index=True, comment="命中时间")

    __table_args__ = (
        Index("ix_alert_rule_hits_rule_time", "rule_id", "matched_at"),
    )

    def __repr__(self):
        return f"<AlertRuleHit rule={self.rule_id} action={self.action!r} at={self.matched_at}>"
