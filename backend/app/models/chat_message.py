"""对话消息持久化模型。

Hermes 引擎的每次 /agents/:id/chat 请求是无状态的，但多轮对话（如"封禁确认"
流程）需要跨请求保留上下文。本表持久化每个会话（agent_id + session_id）的
OpenAI 格式消息（user / assistant / tool），下次请求时按 context_turns 加载
最近 N 轮注入到 executor.messages，使 LLM 能看到历史对话与工具结果。

字段说明：
- role: user / assistant / tool（与 OpenAI 消息格式一致）
- content: 消息文本内容
- tool_calls: assistant 消息携带的工具调用（OpenAI tool_calls 格式，JSON）
- tool_call_id / name: tool 消息关联的工具调用 ID 与工具名
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON

from app.core.timezone import beijing_now
from app.database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user / assistant / tool
    content = Column(Text, default="")
    # assistant 消息的工具调用（OpenAI 格式：[{"id","type":"function","function":{"name","arguments"}}]）
    tool_calls = Column(JSON, nullable=True)
    # tool 消息关联的工具调用 ID + 工具名
    tool_call_id = Column(String(128), default="")
    name = Column(String(100), default="")
    created_at = Column(DateTime, default=beijing_now, index=True)
