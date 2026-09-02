"""Execution Pydantic Schema。"""
from typing import Any, Optional

from app.schemas._datetime import BeijingDatetime
from pydantic import BaseModel


class ExecutionOut(BaseModel):
    """Execution 输出 Schema。

    注意：``workflow_id`` 可为空（智能体测试执行的 trigger_type=agent_test 时，
    执行不关联工作流，workflow_id 为 None）。若声明为 ``int`` 会导致响应序列化
    校验失败（500 Internal Server Error），故必须用 ``Optional[int]``。
    """

    id: int
    workflow_id: Optional[int] = None
    agent_id: Optional[int] = None
    status: str
    result: Optional[dict[str, Any]] = None
    # 触发类型：webhook（线上）/ test_run（节点/流程测试）/ manual（手动）/ agent_test（智能体测试）
    trigger_type: Optional[str] = None
    created_at: Optional[BeijingDatetime] = None
    finished_at: Optional[BeijingDatetime] = None

    model_config = {"from_attributes": True}
