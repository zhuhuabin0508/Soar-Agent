"""Feedback（系统 BUG 与优化建议）Pydantic Schema。

pydantic v2 风格，请求体校验规则：
- ``type`` 白名单 bug/suggestion/other（type=bug 时复现步骤三项必填的
  业务校验在 API 层完成，缺失时返回 400 而非 422）；
- ``title`` 1-200 字符，``description`` 1-5000 字符；
- ``priority`` 白名单 urgent/high/medium/low，默认 medium；
- ``status`` 白名单 pending/processing/replied/resolved/closed。
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

# 白名单常量
FEEDBACK_TYPES = ("bug", "suggestion", "other")
FEEDBACK_PRIORITIES = ("urgent", "high", "medium", "low")
FEEDBACK_STATUSES = ("pending", "processing", "replied", "resolved", "closed")

# BUG 必填三项的中文名（API 层 400 提示复用）
BUG_REQUIRED_FIELDS = {
    "reproduce_steps": "复现步骤",
    "expected_result": "期望结果",
    "actual_result": "实际结果",
}


class FeedbackCreate(BaseModel):
    """提交反馈请求体。"""

    type: Literal["bug", "suggestion", "other"] = Field(..., description="反馈类型：bug/suggestion/other")
    title: str = Field(..., min_length=1, max_length=200, description="标题（1-200 字符）")
    module: Optional[str] = Field(None, max_length=100, description="所属模块/页面名称")
    priority: Literal["urgent", "high", "medium", "low"] = Field("medium", description="优先级")
    description: str = Field(..., min_length=1, max_length=5000, description="问题描述（1-5000 字符）")
    reproduce_steps: Optional[str] = Field(None, max_length=5000, description="复现步骤（type=bug 必填）")
    expected_result: Optional[str] = Field(None, max_length=5000, description="期望结果（type=bug 必填）")
    actual_result: Optional[str] = Field(None, max_length=5000, description="实际结果（type=bug 必填）")
    contact: Optional[str] = Field(None, max_length=200, description="联系方式")
    allow_visit: bool = Field(True, description="是否允许管理员访问复核")
    page_title: Optional[str] = Field(None, max_length=200, description="提交页面标题（自动记录）")
    page_url: Optional[str] = Field(None, max_length=500, description="提交页面 URL（自动记录）")


class FeedbackUpdate(BaseModel):
    """编辑反馈请求体（仅提交人，未完结状态可编辑）。"""

    type: Optional[Literal["bug", "suggestion", "other"]] = Field(None, description="反馈类型")
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="标题")
    module: Optional[str] = Field(None, max_length=100, description="所属模块/页面名称")
    priority: Optional[Literal["urgent", "high", "medium", "low"]] = Field(None, description="优先级")
    description: Optional[str] = Field(None, min_length=1, max_length=5000, description="问题描述")
    reproduce_steps: Optional[str] = Field(None, max_length=5000, description="复现步骤")
    expected_result: Optional[str] = Field(None, max_length=5000, description="期望结果")
    actual_result: Optional[str] = Field(None, max_length=5000, description="实际结果")
    contact: Optional[str] = Field(None, max_length=200, description="联系方式")
    allow_visit: Optional[bool] = Field(None, description="是否允许管理员访问复核")


class ReplyCreate(BaseModel):
    """管理员回复反馈请求体。"""

    content: str = Field(..., min_length=1, max_length=5000, description="回复内容")
    new_status: Optional[Literal["pending", "processing", "replied", "resolved", "closed"]] = Field(
        None, description="回复时同步更新的状态（可选）"
    )
    assignee_id: Optional[int] = Field(None, description="指派处理人 user_id（可选）")


class StatusUpdate(BaseModel):
    """管理员更新反馈状态请求体。"""

    status: Literal["pending", "processing", "replied", "resolved", "closed"] = Field(..., description="新状态")


class BatchAction(BaseModel):
    """批量操作反馈请求体。"""

    ids: list[int] = Field(..., min_length=1, description="反馈 ID 列表（非空）")
    action: Literal["close", "processed", "delete"] = Field(
        ..., description="批量动作：close=关闭 / processed=标记处理中 / delete=硬删除（级联清理附件/历史/通知）"
    )
