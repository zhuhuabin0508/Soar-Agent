"""Agent 状态定义模块。

使用 ``TypedDict`` 描述 LangGraph 在各节点间流转的共享状态结构，
确保节点函数对状态的读写具有明确的字段约束。
"""
from typing import TypedDict


class AgentState(TypedDict):
    """LangGraph 状态机的共享状态。

    Attributes:
        alert_data: 原始告警数据，包含 src_ip、dest_ip、alert_type 等字段。
        messages: 对话历史，元素为 LangChain 消息对象或字典。
        action_decision: 最终结构化输出，
            形如 ``{"decision", "target_ip", "reason", "duration"}``。
        iteration: 当前迭代次数，用于限制最大轮询深度，防止死循环。
    """

    alert_data: dict
    messages: list
    action_decision: dict
    iteration: int
