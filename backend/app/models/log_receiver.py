"""设备日志接收（被动接入）模型。

用于让对方设备/上游把日志主动推送到 SOAR，而不是 SOAR 主动去拉取。
支持 syslog（UDP/TCP）、kafka 等接收协议。接收到的原始日志进入
解析入库管道（ParseEngine），并可查看接收情况与异常。
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


class LogReceiver(Base):
    """设备日志接收渠道配置。

    一条属于某设备的日志接入配置，protocol 决定如何监听/消费：
    - syslog：本 SOAR 开启 UDP/TCP 端口监听；
    - kafka ：本 SOAR 作为 consumer 从 topic 拉取。
    """

    __tablename__ = "log_receivers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, nullable=False, index=True, comment="所属设备 ID")
    device_name = Column(String(255), nullable=False, default="", comment="设备名称冗余")
    name = Column(String(128), nullable=False, default="", comment="接收渠道名称，如 syslog-514")
    # 接收协议：syslog / kafka / webhook
    protocol = Column(String(32), nullable=False, default="syslog", comment="接收协议")
    enabled = Column(Integer, nullable=False, default=1, comment="是否启用: 1启用 0停用")

    # syslog 配置
    syslog_port = Column(Integer, nullable=True, comment="syslog 监听端口")
    syslog_proto = Column(String(16), nullable=False, default="udp", comment="syslog 传输: udp/tcp")
    syslog_bind = Column(String(64), nullable=False, default="0.0.0.0", comment="syslog 监听地址")

    # kafka 配置
    kafka_bootstrap = Column(String(512), nullable=False, default="", comment="kafka bootstrap servers（逗号分隔）")
    kafka_topic = Column(String(255), nullable=False, default="", comment="kafka topic（支持多个逗号分隔）")
    kafka_group = Column(String(255), nullable=False, default="soar-ingest", comment="kafka 消费组")
    kafka_security = Column(String(255), nullable=False, default="", comment="kafka 安全协议配置 JSON")

    # 接收内容格式
    format = Column(String(16), nullable=False, default="json", comment="内容格式: json/raw")

    # 异常通知间隔（分钟）：0=异常期间仅首次通知一次，>0=异常持续期间每 N 分钟重复提醒
    notify_interval_minutes = Column(Integer, nullable=False, default=0, comment="异常通知间隔（分钟）")

    description = Column(String(512), nullable=False, default="", comment="描述")

    # 运行状态（由接收管理器维护）
    # syslog: binding/listening/failed/stopped  kafka: connecting/running/failed/stopped
    # 另有 unconfigured / start_failed 表示配置缺失或启动失败
    status = Column(String(32), nullable=False, default="unconfigured", comment="运行状态")
    last_received_at = Column(DateTime, nullable=True, comment="最近一次收到日志的时间")
    last_error = Column(Text, nullable=True, comment="最近一次错误信息")
    received_count = Column(Integer, nullable=False, default=0, comment="累计接收条数")
    error_count = Column(Integer, nullable=False, default=0, comment="累计异常条数")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_log_receiver_device_name"),
    )

    def __repr__(self):
        return (
            f"<LogReceiver id={self.id} device={self.device_id} "
            f"{self.protocol}:{self.syslog_port} status={self.status}>"
        )


class DeviceReceiveLog(Base):
    """设备日志接收明细：记录每次收到的原始日志（含解析结果）。"""

    __tablename__ = "device_receive_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receiver_id = Column(Integer, nullable=True, index=True, comment="接收渠道 ID")
    device_id = Column(Integer, nullable=True, index=True, comment="设备 ID")
    device_name = Column(String(255), nullable=False, default="", comment="设备名称冗余")
    protocol = Column(String(32), nullable=False, default="syslog", comment="接收协议")
    # JSON 原始内容（原样留存）
    raw_data = Column(Text, nullable=True, comment="接收到的原始数据")
    source_ip = Column(String(64), nullable=True, comment="来源地址（syslog）")
    # 处理结果
    parse_status = Column(String(16), nullable=False, default="received", comment="received/success/partial/fail")
    parse_error = Column(Text, nullable=True, comment="解析错误信息")
    alert_id = Column(Integer, nullable=True, comment="解析入库的告警 ID")
    received_at = Column(DateTime, server_default=func.now(), index=True, comment="接收时间")

    def __repr__(self):
        return (
            f"<DeviceReceiveLog id={self.id} device={self.device_name!r} "
            f"protocol={self.protocol} status={self.parse_status}>"
        )


class DeviceReceiveMetric(Base):
    """设备日志接收指标（按小时聚合，按接收渠道维度）。"""

    __tablename__ = "device_receive_metrics"

    id = Column(Integer, primary_key=True, index=True)
    stat_hour = Column(String(16), nullable=False, comment="统计小时 YYYY-MM-DDTHH")
    receiver_id = Column(Integer, nullable=False, comment="接收渠道 ID")
    receiver_name = Column(String(255), default="", comment="接收渠道名称冗余")
    device_id = Column(Integer, nullable=True, comment="设备 ID")
    protocol = Column(String(32), nullable=False, default="syslog", comment="接收协议")
    total_count = Column(Integer, default=0, comment="接收总数")
    success_count = Column(Integer, default=0, comment="解析成功数")
    partial_count = Column(Integer, default=0, comment="部分成功数")
    fail_count = Column(Integer, default=0, comment="失败数")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_hour", "receiver_id", name="uq_device_receive_metric_hour_receiver"),
    )

    def __repr__(self):
        return f"<DeviceReceiveMetric hour={self.stat_hour!r} receiver={self.receiver_id} total={self.total_count}>"
