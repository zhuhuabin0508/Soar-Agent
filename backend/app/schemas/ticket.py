"""工单 Pydantic 请求模型。

覆盖三类对象：
- 分组管理：创建/更新/成员全量设置
- 流程模板：创建/更新（发布走专用 POST /{id}/publish）
- 工单实例：发起/流转/取消
"""
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============ 分组 ============

class GroupCreate(BaseModel):
    """创建分组：名称/描述/启停/初始成员。"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    enabled: bool = True
    member_ids: list[int] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    """更新分组基础信息。"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    enabled: Optional[bool] = None


class GroupMembersUpdate(BaseModel):
    """全量设置分组成员（前端勾选提交，做差集增删）。"""
    user_ids: list[int] = Field(default_factory=list)


# ============ 流程模板 ============

class FlowCreate(BaseModel):
    """创建流程模板：nodes 为完整流程结构 JSON（含 start_groups + nodes）。"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    nodes: dict[str, Any] = Field(default_factory=dict)


class FlowUpdate(BaseModel):
    """更新流程模板：内容变更后自动回到草稿态，需重新发布。"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    enabled: Optional[bool] = None
    nodes: Optional[dict[str, Any]] = None


# ============ 工单实例 ============

class CcTarget(BaseModel):
    """抄送对象：人员或工单分组。"""
    type: str = Field(..., pattern="^(user|group)$")
    id: int
    name: str = Field("", max_length=100)


class TicketCreate(BaseModel):
    """发起工单：field_values 按首节点字段定义校验。

    ``cc_targets``：发起时手动追加的抄送对象（模板固定抄送自动生效，此处无需重复）。
    """
    flow_id: int
    title: str = Field(..., min_length=1, max_length=200)
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    field_values: dict[str, Any] = Field(default_factory=dict)
    route_to: Optional[str] = None
    comment: Optional[str] = None
    related_alert_id: Optional[int] = None
    related_alert_uuid: Optional[str] = Field(None, max_length=64)
    cc_targets: list[CcTarget] = Field(default_factory=list)


class TicketCcAdd(BaseModel):
    """追加抄送对象（发起人/当前处理人/admin，进行中工单）。"""
    targets: list[CcTarget] = Field(default_factory=list)


class TicketAdvance(BaseModel):
    """流转工单：当前节点处理人提交字段值并选择去向。"""
    field_values: dict[str, Any] = Field(default_factory=dict)
    route_to: Optional[str] = None
    comment: Optional[str] = None


class TicketCancel(BaseModel):
    """取消工单：仅发起人或 admin。"""
    comment: Optional[str] = None


class TicketRollback(BaseModel):
    """回退工单：当前节点处理人退回上一节点，必须填写回退原因。"""
    comment: str = Field(..., min_length=1, max_length=1000, description="回退原因（必填）")
