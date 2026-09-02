"""WorkflowVersion Pydantic Schema。"""
from typing import Any, Optional

from app.schemas._datetime import BeijingDatetime
from pydantic import BaseModel, Field


class WorkflowVersionOut(BaseModel):
    """WorkflowVersion 输出 Schema。"""

    id: int
    workflow_id: int
    version_number: int
    snapshot: dict[str, Any] = Field(
        ..., description="工作流快照，含 name / graph_config / enabled"
    )
    change_note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[BeijingDatetime] = None

    model_config = {"from_attributes": True}


class WorkflowVersionCreate(BaseModel):
    """创建 WorkflowVersion 的请求体。

    ``snapshot`` 由后端从当前工作流自动读取，前端仅需可选传入变更说明。
    """

    change_note: Optional[str] = Field(
        None, max_length=500, description="变更说明，可选"
    )


class RollbackResponse(BaseModel):
    """回滚响应 Schema。"""

    workflow: dict[str, Any] = Field(
        ..., description="回滚后的工作流当前状态（含 name/graph_config/enabled）"
    )
    version_number: int = Field(
        ..., description="回滚产生的最新版本号"
    )
    message: str = Field(..., description="回滚结果说明")
