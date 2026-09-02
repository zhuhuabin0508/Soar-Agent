"""Workflow Pydantic Schema。"""
from typing import Any, Optional

from app.schemas._datetime import BeijingDatetime
from pydantic import BaseModel, Field


class WorkflowBase(BaseModel):
    """Workflow 基础字段。"""

    name: str = Field(..., description="工作流名称")
    graph_config: dict[str, Any] = Field(..., description="工作流图配置，含 nodes 与 edges")


class WorkflowCreate(WorkflowBase):
    """创建 Workflow 的请求体。"""

    enabled: bool = Field(True, description="是否启用（禁用后 webhook 触发返回 404）")
    trigger_type: str = Field("webhook", description="触发方式：webhook / schedule / event / manual")
    category: Optional[str] = Field(None, description="业务场景分类")
    tags: Optional[list[str]] = Field(None, description="自定义标签数组")
    favorite: bool = Field(False, description="是否收藏常用工作流")
    status: str = Field("published", description="生命周期状态：draft / published / disabled")
    description: Optional[str] = Field(None, description="工作流描述/说明")


class WorkflowUpdate(BaseModel):
    """更新 Workflow 的请求体，所有字段可选。"""

    name: Optional[str] = None
    graph_config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    trigger_type: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    favorite: Optional[bool] = None
    status: Optional[str] = None
    description: Optional[str] = None


class WorkflowOut(WorkflowBase):
    """Workflow 输出 Schema。

    注意：``webhook_secret`` 仅在详情接口返回（列表接口不返回，避免泄露）。
    """

    id: int
    enabled: bool = True
    webhook_secret: Optional[str] = None
    trigger_type: str = "webhook"
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    favorite: bool = False
    status: str = "published"
    description: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[BeijingDatetime] = None
    updated_at: Optional[BeijingDatetime] = None
    # 资源级 owner 控制：admin/owner/被授权用户可编辑
    can_edit: bool = False

    model_config = {"from_attributes": True}


class WorkflowListItem(BaseModel):
    """Workflow 列表项 Schema（不含 webhook_secret，避免列表泄露）。"""

    id: int
    name: str
    enabled: bool = True
    trigger_type: str = "webhook"
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    favorite: bool = False
    status: str = "published"
    description: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[BeijingDatetime] = None
    updated_at: Optional[BeijingDatetime] = None
    # 资源级 owner 控制：admin/owner/被授权用户可编辑
    can_edit: bool = False
    # 列表项扩展统计字段（由 list_workflows 注入，非 ORM 字段）
    last_run_status: Optional[str] = None
    last_run_at: Optional[BeijingDatetime] = None
    today_count: int = 0
    success_rate_7d: Optional[float] = None
    avg_duration_seconds: Optional[float] = None

    model_config = {"from_attributes": True}
