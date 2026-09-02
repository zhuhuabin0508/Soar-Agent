"""节点基类与执行结果契约。"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.workflow_ban import WorkflowInstance

logger = logging.getLogger(__name__)


@dataclass
class NodeResult:
    """节点执行结果。

    Attributes:
        status: success / fail / skipped。
        action: continue / pause / abort / error。
        next_key: 路由节点指定的下一节点 key（None 走默认图）。
        output: 节点输出（写入 workflow_node_logs.output）。
        error: 失败原因。
    """

    status: str = "success"
    action: str = "continue"
    next_key: Optional[str] = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class BaseNode:
    """节点基类：无状态执行单元，ctx 为实例级共享上下文。"""

    key = "base"
    name = "基础节点"

    def execute(self, db: Session, instance: WorkflowInstance, ctx: dict[str, Any]) -> NodeResult:
        """执行节点逻辑，子类必须实现。"""
        raise NotImplementedError

    # ------ 共享辅助 ------
    @staticmethod
    def jdump(obj: Any) -> str:
        """JSON 序列化（供日志输出）。"""
        try:
            return json.dumps(obj, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return str(obj)
