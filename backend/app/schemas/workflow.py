"""Workflow Pydantic Schema。"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class WorkflowBase(BaseModel):
    """Workflow 基础字段。"""

    name: str = Field(..., description="工作流名称")
    graph_config: dict[str, Any] = Field(..., description="工作流图配置，含 nodes 与 edges")


class WorkflowCreate(WorkflowBase):
    """创建 Workflow 的请求体。"""

    enabled: bool = Field(True, description="是否启用（禁用后 webhook 触发返回 404）")


class WorkflowUpdate(BaseModel):
    """更新 Workflow 的请求体，所有字段可选。"""

    name: Optional[str] = None
    graph_config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None


class WorkflowOut(WorkflowBase):
    """Workflow 输出 Schema。

    注意：``webhook_secret`` 仅在详情接口返回（列表接口不返回，避免泄露）。
    """

    id: int
    enabled: bool = True
    webhook_secret: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WorkflowListItem(BaseModel):
    """Workflow 列表项 Schema（不含 webhook_secret，避免列表泄露）。"""

    id: int
    name: str
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
