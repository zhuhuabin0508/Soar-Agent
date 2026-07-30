"""ExecutionTrace Pydantic Schema。"""
from datetime import datetime
from typing import Any, Optional

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
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
