"""资产记录模型。

存储从知识库梳理或对话录入的资产信息，按 (agent_id, identifier) 去重。
供资产管理智能体的 discover_new_kbs / query_asset / add_asset / update_asset /
list_assets 工具使用，以及前端「资产管理」页面展示。

设计要点：
- ``agent_id`` 作用域：每个资产智能体独立维护各自资产表，互不污染。
- ``identifier`` + ``identifier_type``：由智能体灵活判断的唯一标识（IP/主机名/工号等）。
- ``extra_fields`` (JSON)：不同知识库字段不同时，非常规字段统一存这里。
- ``source``：kb_ingest（KB 梳理）/ manual（前端手动）/ agent_add（对话录入）。
"""
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON

from app.database import Base


def _beijing_now():
    """北京时间（UTC+8），供 created_at/updated_at 默认值使用。

    Docker 容器默认 UTC 时区，统一存北京时间保证前端显示正确。
    """
    return datetime.utcnow() + timedelta(hours=8)


class Asset(Base):
    """资产记录。"""

    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    # 作用域：资产归属于哪个智能体梳理
    agent_id = Column(Integer, index=True, nullable=False)
    # 来源知识库（0 表示对话录入，无 KB 来源）
    kb_id = Column(Integer, index=True, nullable=False, default=0)
    # 冗余存储 KB 名称（KB 删除后仍可展示来源）
    kb_name = Column(String(255), default="")
    # 去重主标识：IP/资产名/主机名/工号等，由智能体灵活判定填入
    identifier = Column(String(255), index=True, nullable=False)
    # 标识类型：ip/hostname/asset_name/employee_id/mac/custom
    identifier_type = Column(String(32), default="custom")
    # 资产名称（展示用）
    name = Column(String(255), default="")
    # 资产类型：服务器/工作站/网络设备/应用/账号等
    asset_type = Column(String(64), default="")
    department = Column(String(128), default="")
    owner = Column(String(128), default="")
    location = Column(String(128), default="")
    ip = Column(String(128), default="")
    # 重要性：low/medium/high/critical
    criticality = Column(String(16), default="medium")
    # 灵活字段：每个 KB 字段不同时，非常规字段塞这里
    extra_fields = Column(JSON, nullable=True, default=dict)
    # 来源：kb_ingest（KB 梳理）/ manual（前端手动）/ agent_add（对话录入）
    source = Column(String(20), default="agent_add")
    # LLM 提取时的原始 KB 片段（便于溯源审计）
    raw_content = Column(Text, default="")
    created_at = Column(DateTime, default=_beijing_now)
    updated_at = Column(DateTime, default=_beijing_now, onupdate=_beijing_now)

    __table_args__ = (
        # 按 (agent_id, identifier) 唯一去重：同一智能体下相同 identifier 视为同一资产
        Index("idx_assets_agent_identifier", "agent_id", "identifier", unique=True),
    )

    def __repr__(self):
        return f"<Asset id={self.id} agent_id={self.agent_id} identifier={self.identifier!r}>"
