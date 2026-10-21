"""日志来源条目模型。

监听型渠道（syslog / snmp_trap / netflow / pcap）收到某来源 IP 的日志后，
按 (receiver_id, source_ip) 自动生成"来源条目"；管理员可在条目上独立配置
解析策略（strategy_id）与流水线覆盖（entry_config.pipeline），未配置时
回退接收渠道默认（日志零丢失）。
"""
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.database import Base


class LogSourceEntry(Base):
    """来源条目：一个接收渠道下按来源 IP 自动发现的接入实例。"""

    __tablename__ = "log_source_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receiver_id = Column(Integer, nullable=False, index=True, comment="所属接收渠道 ID")
    source_ip = Column(String(64), nullable=False, comment="来源地址（该条目的标识）")
    name = Column(String(128), nullable=False, default="", comment="条目名称，默认取 source_ip")
    # 首见创建时自动按 devices.ip_address 匹配绑定；管理员可改
    device_id = Column(Integer, nullable=True, index=True, comment="关联设备 ID")
    enabled = Column(Integer, nullable=False, default=1, comment="1启用 0停用（停用=丢弃该来源日志）")
    # 条目级手动策略：优先级链最前（条目 → 渠道 → 设备绑定 → 自动匹配）
    strategy_id = Column(Integer, nullable=True, comment="条目级解析策略 ID（NULL/0=回退渠道/自动匹配）")
    # 条目级流水线覆盖 JSON：{"pipeline": {"filter": {...}, "enricher": {...}, "translator": {...}}}
    entry_config = Column(Text, nullable=False, default="{}", comment="条目级流水线覆盖 JSON")
    auto_created = Column(Integer, nullable=False, default=1, comment="1自动发现 0手工创建")

    # 运行统计（entry_registry 内存缓冲节流累加）
    received_count = Column(Integer, nullable=False, default=0, comment="累计接收条数")
    last_received_at = Column(DateTime, nullable=True, comment="最近一次收到日志的时间")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("receiver_id", "source_ip", name="uq_log_source_entry_recv_ip"),
    )

    def __repr__(self):
        return (
            f"<LogSourceEntry id={self.id} receiver={self.receiver_id} "
            f"source_ip={self.source_ip!r} enabled={self.enabled}>"
        )
