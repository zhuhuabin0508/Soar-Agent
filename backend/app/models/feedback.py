"""系统 BUG 与优化建议反馈模型。

用户在前端提交 BUG / 优化建议 / 其他反馈，管理员可在
反馈中心回复、改状态、指派处理人与批量处理。

- ``Feedback``：反馈主表（含复现步骤、期望/实际结果、附件清单等）。
- ``FeedbackHistory``：操作历史（创建/回复/状态流转/重新打开/指派/批量），
  便于审计与前端时间线展示。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.core.timezone import to_beijing_iso
from app.database import Base


class Feedback(Base):
    """系统 BUG 与优化建议反馈。

    字段说明：
    - ``type``：反馈类型 bug（系统 BUG）/ suggestion（优化建议）/ other（其他）。
    - ``priority``：优先级 urgent/high/medium/low。
    - ``status``：处理状态 pending（待处理）/ processing（处理中）/ replied（已回复）
      / resolved（已解决）/ closed（已关闭）。
    - ``reproduce_steps`` / ``expected_result`` / ``actual_result``：type=bug 时必填。
    - ``allow_visit``：是否允许管理员上门/远程访问复核（用户授权标记）。
    - ``page_title`` / ``page_url``：自动记录提交页面来源，便于定位问题。
    - ``attachments``：附件清单，JSON 数组字符串 ``[{"name","path","size"}]``。
    """

    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 提交人 user_id
    user_id = Column(Integer, nullable=False, index=True)
    # 反馈类型：bug / suggestion / other
    type = Column(String(20), nullable=False)
    title = Column(String(200), nullable=False)
    # 所属模块/页面名称
    module = Column(String(100), nullable=True)
    # 优先级：urgent/high/medium/low
    priority = Column(String(20), nullable=False, default="medium")
    description = Column(Text, nullable=False)
    # BUG 必填：复现步骤 / 期望结果 / 实际结果
    reproduce_steps = Column(Text, nullable=True)
    expected_result = Column(Text, nullable=True)
    actual_result = Column(Text, nullable=True)
    # 联系方式（手机/邮箱/IM 等）
    contact = Column(String(200), nullable=True)
    # 是否允许管理员访问复核
    allow_visit = Column(Boolean, nullable=False, default=True)
    # 自动记录提交页面来源
    page_title = Column(String(200), nullable=True)
    page_url = Column(String(500), nullable=True)
    # 处理状态：pending/processing/replied/resolved/closed
    status = Column(String(20), nullable=False, default="pending", index=True)
    # 处理人 user_id
    assignee_id = Column(Integer, nullable=True)
    # 附件清单：JSON 数组字符串 [{"name","path","size"}]
    attachments = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        """序列化为可直接 JSON 返回的字典（datetime 转 +08:00 ISO 字符串）。"""
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result

    def __repr__(self) -> str:
        return f"<Feedback id={self.id} type={self.type!r} title={self.title!r} status={self.status!r}>"


class FeedbackHistory(Base):
    """反馈操作历史：创建 / 回复 / 状态流转 / 重新打开 / 指派 / 批量操作。"""

    __tablename__ = "feedback_histories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feedback_id = Column(Integer, nullable=False, index=True)
    # 操作类型：created/reply/status_change/reopen/assign/edit/batch
    action = Column(String(30), nullable=False)
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=True)
    # 回复内容或操作说明
    content = Column(Text, nullable=True)
    operator_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self) -> dict:
        """序列化为可直接 JSON 返回的字典（datetime 转 +08:00 ISO 字符串）。"""
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result

    def __repr__(self) -> str:
        return (
            f"<FeedbackHistory id={self.id} feedback_id={self.feedback_id} "
            f"action={self.action!r} operator_id={self.operator_id}>"
        )
