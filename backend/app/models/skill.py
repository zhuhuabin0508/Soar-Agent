"""Skill 数据模型。

技能是一段**纯文本指令**（处置流程/角色设定/领域规则/SOP），启用后由
``app/agent/prompt_assembler.py`` 注入到 Agent 的 system prompt 中，
持续塑造 AI 行为（类似 Claude Skill）。技能不是可调用函数，与
``Tool``（code/http 可执行工具）是两类不同实体。

``content`` 支持 ``{{key}}`` 变量占位符，运行时用 ``Agent.variables`` 替换。
``priority`` 决定多技能时的注入顺序（越大越靠前）。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON

from app.database import Base


class Skill(Base):
    """可编辑技能模型（纯文本，注入 system prompt）。"""

    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)  # 简短摘要（列表展示用）
    # 注入到 system prompt 的正文，支持 {{key}} 引用 Agent.variables
    content = Column(Text, nullable=False)
    # 分类：处置流程 / 角色设定 / 领域规则 / SOP / 其他
    category = Column(String(64), nullable=True)
    tags = Column(JSON, nullable=True, default=list)  # 自由标签数组
    enabled = Column(Boolean, nullable=False, default=True)
    # 注入顺序，越大越靠前（同优先级按 id 升序）
    priority = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Skill id={self.id} name={self.name!r} enabled={self.enabled}>"
