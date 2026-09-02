"""工作流节点包：13 个执行节点，每个节点独立文件。

节点通过 ``NodeResult`` 与引擎通信：
- ``status``：success / fail / skipped
- ``action``：continue（继续下一节点）/ pause（暂停等待审批）/ abort（终止实例）/ error（转异常处理）
- ``next_key``：路由节点指定的下一节点 key（None 走默认图）
- ``output``：节点输出（JSON 序列化写入 workflow_node_logs）
"""
from .base import BaseNode, NodeResult
from .event_trigger import EventTriggerNode
from .param_validate import ParamValidateNode
from .agent_analyze import AgentAnalyzeNode
from .banned_check import BannedCheckNode
from .already_banned import AlreadyBannedNode
from .action_branch import ActionBranchNode
from .direct_ban import DirectBanNode
from .approval_ticket import ApprovalTicketNode
from .approval_result import ApprovalResultNode
from .execute_ban import ExecuteBanNode
from .monitor_log import MonitorLogNode
from .result_sync import ResultSyncNode
from .error_handler import ErrorHandlerNode

# 节点注册表：key → 节点实例（全部无状态，可安全复用）
NODE_REGISTRY = {
    "event_trigger": EventTriggerNode(),
    "param_validate": ParamValidateNode(),
    "agent_analyze": AgentAnalyzeNode(),
    "banned_check": BannedCheckNode(),
    "already_banned": AlreadyBannedNode(),
    "action_branch": ActionBranchNode(),
    "direct_ban": DirectBanNode(),
    "approval_ticket": ApprovalTicketNode(),
    "approval_result": ApprovalResultNode(),
    "execute_ban": ExecuteBanNode(),
    "monitor_log": MonitorLogNode(),
    "result_sync": ResultSyncNode(),
    "error_handler": ErrorHandlerNode(),
}

# 节点中文名（前端时间线展示）
NODE_LABELS = {
    "event_trigger": "事件触发",
    "param_validate": "参数校验",
    "agent_analyze": "智能体研判",
    "banned_check": "已封禁判断",
    "already_banned": "已封禁处理",
    "action_branch": "动作分支",
    "direct_ban": "直接封禁",
    "approval_ticket": "审批工单",
    "approval_result": "审批结果判断",
    "execute_ban": "执行封禁",
    "monitor_log": "持续监控记录",
    "result_sync": "结果同步",
    "error_handler": "异常处理",
}

__all__ = [
    "BaseNode", "NodeResult", "NODE_REGISTRY", "NODE_LABELS",
    "EventTriggerNode", "ParamValidateNode", "AgentAnalyzeNode", "BannedCheckNode",
    "AlreadyBannedNode", "ActionBranchNode", "DirectBanNode", "ApprovalTicketNode",
    "ApprovalResultNode", "ExecuteBanNode", "MonitorLogNode", "ResultSyncNode",
    "ErrorHandlerNode",
]
