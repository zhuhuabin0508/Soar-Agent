"""审批相关 Pydantic Schema。"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class ApprovalItem(BaseModel):
    """待审批执行列表项（工单）。

    字段说明：
    - ``alert_data`` / ``agent_messages`` / ``agent_decision``：兼容旧审批中心，
      仅含告警与 Agent 决策的精简字段。
    - ``context``：完整执行上下文，含 payload 与各节点输入输出，供工作台
      展示所有信息以供工作人员判断。
    - ``review_meta``：触发审批的节点元数据（title/description/instructions）。
    """

    execution_id: int
    workflow_id: int
    workflow_name: str
    status: str
    created_at: Optional[datetime] = None
    alert_data: Optional[dict[str, Any]] = None
    agent_messages: Optional[list[dict[str, Any]]] = None
    agent_decision: Optional[dict[str, Any]] = None
    context: Optional[dict[str, Any]] = None
    review_meta: Optional[dict[str, Any]] = None


class ApprovalActionResponse(BaseModel):
    """审批操作（通过 / 拒绝）响应。"""

    execution_id: int
    status: str
    message: str
