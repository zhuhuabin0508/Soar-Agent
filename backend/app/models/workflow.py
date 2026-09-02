"""Workflow 数据模型。"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database import Base


class Workflow(Base):
    """工作流模型，存储 DAG 图配置（nodes / edges）。

    新增字段（P0-2 webhook 防护）：
    - ``webhook_secret``：per-workflow 的 webhook 触发密钥，调用 webhook 时需携带。
    - ``enabled``：工作流启用开关，禁用后 webhook 触发返回 404。

    新增字段（工作流管理增强）：
    - ``trigger_type``：触发方式标识（webhook / schedule / event / manual）。
    - ``category``：业务场景分类（事件响应 / 告警处置 / 资产发现 / 通知推送 等）。
    - ``tags``：自定义标签数组（JSON），便于多维度筛选。
    - ``favorite``：是否收藏常用工作流。
    - ``status``：生命周期状态（draft / published / disabled）。
    - ``description``：工作流描述/说明。
    """

    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    graph_config = Column(JSON, nullable=False)
    # Webhook 触发密钥（32 位 hex），创建工作流时自动生成，可重置
    webhook_secret = Column(String(64), nullable=True)
    # 工作流启用开关；禁用后 webhook 触发将返回 404
    enabled = Column(Boolean, nullable=False, default=True)
    # 创建者用户ID（资源级 owner 权限控制），null 表示历史数据/系统创建
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 触发方式标识：webhook / schedule / event / manual
    trigger_type = Column(String(32), nullable=False, default="webhook")
    # 业务场景分类：事件响应 / 告警处置 / 资产发现 / 通知推送 / 其他
    category = Column(String(64), nullable=True)
    # 自定义标签 JSON 数组（如 ["重保", "巡检"]）
    tags = Column(JSON, nullable=True)
    # 是否收藏（常用工作流置顶）
    favorite = Column(Boolean, nullable=False, default=False)
    # 生命周期状态：draft / published / disabled
    status = Column(String(32), nullable=False, default="published")
    # 工作流描述/说明
    description = Column(Text, nullable=True)
    # 环境变量（JSON 数组，每项 {name, description, value}；value 加密存储）
    # 节点参数中用 ${env.名称} 引用，运行时解密注入到 ctx.env
    env_vars = Column(JSON, nullable=True)

    executions = relationship("Execution", back_populates="workflow")
    # 工作流版本历史随工作流一并删除（否则 ORM 会试图把 workflow_versions.workflow_id 置空，
    # 但该列为 NOT NULL，导致删除工作流报 500 NotNullViolation）
    versions = relationship("WorkflowVersion", back_populates="workflow", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Workflow id={self.id} name={self.name!r}>"
