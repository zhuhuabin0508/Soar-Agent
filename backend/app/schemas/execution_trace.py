"""ExecutionTrace Pydantic Schema。"""
from typing import Any, Optional

from app.schemas._datetime import BeijingDatetime
from pydantic import BaseModel


class ExecutionTraceOut(BaseModel):
    """节点执行轨迹输出 Schema。"""

    id: int
    execution_id: int
    node_id: str
    node_type: str
    node_label: Optional[str] = None
    input: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    status: str
    started_at: Optional[BeijingDatetime] = None
    finished_at: Optional[BeijingDatetime] = None

    model_config = {"from_attributes": True}
