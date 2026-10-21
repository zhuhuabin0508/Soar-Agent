"""工单功能模型。

包含 5 张表：
- ``TicketGroup``：工单处理分组（自定义人员分组，如"监测预警组/研判分析组/应急处置组"）
- ``TicketGroupMember``：分组成员（分组-用户多对多关联）
- ``TicketFlow``：工单流程模板（节点/字段/路由全部内嵌 nodes JSON，支持草稿/发布/版本）
- ``Ticket``：工单实例（发起时对流程模板做快照，进行中工单不受模板修改影响）
- ``TicketNodeRecord``：工单节点处理记录（每个节点的处理人/填写的字段值/流转去向，构成处理时间线）

处理模式：节点到达分组后组内全员可见，任一人提交即代表全组（先到先得）。
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, JSON, func

from app.core.timezone import to_beijing_iso
from app.database import Base


class TicketGroup(Base):
    """工单处理分组：把系统现有人员账号自定义分组。"""

    __tablename__ = "ticket_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self, member_count: int | None = None) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        if member_count is not None:
            result["member_count"] = member_count
        return result

    def __repr__(self) -> str:
        return f"<TicketGroup id={self.id} name={self.name!r}>"


class TicketGroupMember(Base):
    """分组成员：分组与用户的多对多关联。"""

    __tablename__ = "ticket_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_ticket_group_member"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("ticket_groups.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result


class TicketFlow(Base):
    """工单流程模板。

    ``nodes`` JSON 结构::

        {
          "start_groups": [1, 2],          # 可发起工单的分组 ID 列表
          "nodes": [
            {
              "key": "n1",                  # 节点唯一标识（流程内唯一，不可变）
              "name": "研判分析",           # 节点显示名
              "group_id": 3,                # 处理分组（type=end 时可为空）
              "type": "task",               # task=处理节点 / end=结束节点
              "fields": [                   # 该节点需填写的字段
                {"key": "is_false_alarm", "label": "是否误报", "type": "select",
                 "required": true, "options": ["是", "否"],
                 "placeholder": "", "alert_field_mapping": "alert_name",
                 "default": ""}
              ],
              "routes": [                   # 流转路由（按序匹配，可带条件）
                {"to": "n2", "label": "需应急", "when": {"field": "is_need_emergency", "op": "eq", "value": "是"}},
                {"to": "end", "label": "默认", "when": null}
              ]
            }
          ]
        }

    字段类型：text/textarea/number/datetime/select/switch/ip/url/file。
    条件操作符：eq（等于）/ ne（不等于）。
    ``is_draft``：草稿状态不会被发起工单引用；发布时做结构校验。
    ``version``：每次发布自增，仅记录当前发布版本号。
    """

    __tablename__ = "ticket_flows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    is_draft = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=0)
    nodes = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result

    def __repr__(self) -> str:
        return f"<TicketFlow id={self.id} name={self.name!r} draft={self.is_draft}>"


class Ticket(Base):
    """工单实例。

    - ``ticket_no``：工单编号，格式 ``TK-YYYYMMDD-XXXX``（当日自增序号）
    - ``flow_snapshot``：发起时的流程模板完整快照，后续模板修改不影响进行中工单
    - ``status``：processing=进行中 / completed=已完成 / cancelled=已取消
    - ``current_node_key``：当前停留节点（status=processing 时有效）
    - ``current_group_id``：当前处理分组（决定谁可见/可处理）
    - ``priority``：low/medium/high/critical
    - ``related_alert_id`` / ``related_alert_uuid``：关联告警（一键发起时写入）
    - ``arrived_at``：进入当前节点时间（节点停留超时提醒的计时起点，流转时重置）
    - ``first_reminded_at`` / ``last_reminded_at`` / ``remind_count``：超时提醒进度
    - ``archived``：归档标记（软删除，仅完结工单可归档，可取消归档恢复）
    - ``enrichment_data``：发起时对 src_ip / dst_ip 自动研判的结果
      （资产库匹配 + 威胁情报查询，JSON 结构见 app.core.ticket_enrichment），
      随工单全程流转，各节点处理人只读可见
    """

    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_no = Column(String(32), nullable=False, unique=True, index=True)
    title = Column(String(200), nullable=False)
    flow_id = Column(Integer, ForeignKey("ticket_flows.id"), nullable=False, index=True)
    flow_name = Column(String(100), nullable=False, default="")
    flow_snapshot = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="processing", index=True)
    current_node_key = Column(String(64), nullable=True)
    current_node_name = Column(String(100), nullable=True)
    current_group_id = Column(Integer, nullable=True, index=True)
    created_by_id = Column(Integer, nullable=False, index=True)
    created_by_name = Column(String(64), nullable=False, default="")
    priority = Column(String(20), nullable=False, default="medium")
    related_alert_id = Column(Integer, nullable=True, index=True)
    related_alert_uuid = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    closed_at = Column(DateTime, nullable=True)
    # 节点停留超时提醒（阶段2）：由定时扫描任务维护，流转到新节点时重置
    arrived_at = Column(DateTime, nullable=True)
    first_reminded_at = Column(DateTime, nullable=True)
    last_reminded_at = Column(DateTime, nullable=True)
    remind_count = Column(Integer, nullable=False, default=0)
    # 归档标记（阶段2）：软删除，列表默认排除归档工单
    archived = Column(Boolean, nullable=False, default=False)
    # 发起时自动研判结果（资产匹配 + 威胁情报，按 src_ip/dst_ip），随工单流转
    enrichment_data = Column(JSON, nullable=True)

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result

    def __repr__(self) -> str:
        return f"<Ticket id={self.id} no={self.ticket_no!r} status={self.status!r}>"


class TicketNodeRecord(Base):
    """工单节点处理记录：每个节点一条，构成处理时间线。

    - ``node_key`` / ``node_name``：快照中的节点标识与名称（含发起节点 start）
    - ``group_id``：该节点的处理分组（发起节点为发起人所在分组，可为空）
    - ``handler_id`` / ``handler_name``：实际处理人（先到先得：组内任一人提交即代表全组）
    - ``action``：create=发起 / submit=提交流转 / cancel=取消 / end=结束落位
    - ``field_values``：本节点填写的字段值 JSON
    - ``route_to``：流转去向节点 key（结束为 end）
    - ``comment``：处理意见
    - ``attachments``：附件列表 JSON（[{name, url}]，一期预留）
    """

    __tablename__ = "ticket_node_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    node_key = Column(String(64), nullable=False, default="")
    node_name = Column(String(100), nullable=False, default="")
    group_id = Column(Integer, nullable=True)
    handler_id = Column(Integer, nullable=False)
    handler_name = Column(String(64), nullable=False, default="")
    action = Column(String(20), nullable=False, default="submit")
    field_values = Column(JSON, nullable=False, default=dict)
    route_to = Column(String(64), nullable=True)
    comment = Column(Text, nullable=True)
    attachments = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result

    def __repr__(self) -> str:
        return f"<TicketNodeRecord id={self.id} ticket={self.ticket_id} node={self.node_key!r}>"
