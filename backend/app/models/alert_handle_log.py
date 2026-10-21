"""告警处置日志模型。

记录每次告警状态变更、指派、备注等操作，形成完整处置时间线。
操作记录不可删除（等保审计要求），仅追加。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.core.timezone import beijing_now
from app.database import Base


class AlertHandleLog(Base):
    """告警处置日志：每次操作追加一条记录，构成处置时间线。"""

    __tablename__ = "alert_handle_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, nullable=False, index=True, comment="告警 ID")
    # 操作类型：status_change(状态变更) / assign(指派) / comment(备注) / reopen(重开) / close(关闭)
    action = Column(String(32), nullable=False, default="comment", comment="操作类型")
    # 状态变更前后的值（-1 表示无变更，如纯备注）
    from_status = Column(Integer, nullable=True, comment="变更前处置状态")
    to_status = Column(Integer, nullable=True, comment="变更后处置状态")
    # 指派变更前后
    from_assignee = Column(String(128), nullable=True, default="", comment="变更前处理人")
    to_assignee = Column(String(128), nullable=True, default="", comment="变更后处理人")
    # 操作人
    operator_id = Column(Integer, nullable=True, comment="操作人用户 ID")
    operator_name = Column(String(128), nullable=False, default="", comment="操作人姓名")
    # 处置备注
    comment = Column(Text, default="", comment="处置备注")
    created_at = Column(DateTime, default=beijing_now, index=True, comment="操作时间")

    def __repr__(self):
        return (
            f"<AlertHandleLog id={self.id} alert_id={self.alert_id} "
            f"action={self.action!r} operator={self.operator_name!r}>"
        )
