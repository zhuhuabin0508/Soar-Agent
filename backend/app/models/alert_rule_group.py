"""告警规则分组模型（alert_rule_groups 表）。

XDR 风格列表页左侧「规则分组」树面板数据源：
- 预置分组（种子数据）：暴力破解、异常登录、Web攻击、恶意软件、
  数据泄露、内部违规、其他；
- 规则通过 rule_group 列存分组名（字符串冗余，分组删除时规则移入
  「其他」），分组计数按 alert_rules.rule_group 聚合；
- 分组重命名时同步更新关联规则的 rule_group。
"""
from sqlalchemy import Column, DateTime, Integer, String

from app.core.timezone import beijing_now
from app.database import Base


class AlertRuleGroup(Base):
    """告警规则分组。"""

    __tablename__ = "alert_rule_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False, unique=True, comment="分组名称（唯一）")
    sort_order = Column(Integer, default=0, comment="排序序号，数值越小越靠前")
    created_at = Column(DateTime, default=beijing_now)

    def __repr__(self):
        return f"<AlertRuleGroup id={self.id} name={self.name!r}>"
