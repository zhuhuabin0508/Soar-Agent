"""数据模型汇总导出。

注册所有 ORM 模型，确保 ``Base.metadata.create_all`` 能发现全部表。
新增模型在此 import 即可完成注册。
"""
from app.models.agent import Agent
from app.models.agent_file import AgentFile
from app.models.audit_log import AuditLog
from app.models.backup_record import BackupRecord
from app.models.banned_ip import BannedIP
from app.models.chat_message import ChatMessage
from app.models.device import Device, DeviceAction
from app.models.execution import Execution
from app.models.execution_log import ExecutionLog
from app.models.execution_trace import ExecutionTrace
from app.models.knowledge_base import KnowledgeBase, KnowledgeDocument, KnowledgeSegment
from app.models.llm_config import LLMConfig
from app.models.model_call_log import ModelCallLog
from app.models.notification import Notification
from app.models.role import Role
from app.models.skill import Skill
from app.models.system_config import SystemConfig
from app.models.tool import Tool
from app.models.user import User
from app.models.workflow import Workflow
from app.models.workflow_version import WorkflowVersion

__all__ = [
    "Workflow",
    "WorkflowVersion",
    "Execution",
    "ExecutionTrace",
    "ExecutionLog",
    "LLMConfig",
    "ModelCallLog",
    "Tool",
    "Agent",
    "AgentFile",
    "AgentMemory",
    "KnowledgeBase",
    "KnowledgeDocument",
    "KnowledgeSegment",
    "User",
    "Role",
    "Skill",
    "SystemConfig",
    "AuditLog",
    "BannedIP",
    "ChatMessage",
    "Notification",
    "BackupRecord",
    "Device",
    "DeviceAction",
]
