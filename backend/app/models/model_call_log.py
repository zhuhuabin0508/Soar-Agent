"""模型调用日志模型。

记录每次 LLM 调用的详情（模型配置、状态、耗时、Token 用量等），
供「模型设置」页的监控功能展示调用情况。

扩展字段（v2）：
- ``prompt_summary``：请求 Prompt 摘要（截断前 500 字）
- ``response_summary``：响应摘要（截断前 500 字）
- ``error_stack``：失败时的完整错误堆栈
- ``source_ip``：调用来源 IP
- ``user_id``：调用用户 ID
- ``session_id``：关联的会话 ID（如有）
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.database import Base


class ModelCallLog(Base):
    """模型调用日志。"""

    __tablename__ = "model_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 关联的 LLM 配置 ID（agent 的 model_config_id）
    model_config_id = Column(Integer, nullable=True, index=True)
    # 冗余存储模型名/供应商，便于配置被删除后仍可统计
    model_name = Column(String(128), nullable=False, default="")
    provider = Column(String(64), nullable=False, default="")
    # 调用状态：success / failed
    status = Column(String(32), nullable=False, default="success", index=True)
    # 耗时（毫秒）
    latency_ms = Column(Integer, nullable=True)
    # Token 用量（从响应 usage 提取，可能为空）
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    # 总 Token（input + output，便于排序）
    total_tokens = Column(Integer, nullable=True)
    # 失败时的错误信息（截断）
    error_message = Column(Text, nullable=True)
    # 触发来源：agent_test / workflow / manual_test / api / knowledge_vector 等
    trigger_type = Column(String(64), nullable=True, default="")
    # 关联的智能体 ID（如有）
    agent_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    # ===== v2 扩展字段：明细增强 =====
    # 请求 Prompt 摘要（截断前 500 字，便于排查问题）
    prompt_summary = Column(Text, nullable=True)
    # 响应摘要（截断前 500 字）
    response_summary = Column(Text, nullable=True)
    # 失败时的完整错误堆栈
    error_stack = Column(Text, nullable=True)
    # 调用来源 IP
    source_ip = Column(String(64), nullable=True)
    # 调用用户 ID
    user_id = Column(Integer, nullable=True)
    # 关联的会话 ID（如有）
    session_id = Column(String(64), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ModelCallLog id={self.id} model={self.model_name!r} "
            f"status={self.status!r} latency={self.latency_ms}ms>"
        )
