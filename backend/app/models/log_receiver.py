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
    """日志接收器配置。

    一条日志接入配置，protocol 决定如何监听/消费：
    - syslog：本 SOAR 开启 UDP/TCP 端口监听；
    - kafka ：本 SOAR 作为 consumer 从 topic 拉取。

    设备归属（device_id）分层：
    - 监听型（syslog/snmp_trap/netflow/pcap）：可空，日志到达后按来源 IP
      自动生成条目，由条目按 devices.ip_address 归属设备；
    - 拉取型（kafka/jdbc/rest_api/file_tail）：必填（无来源 IP 可供条目归属）。
    """

    __tablename__ = "log_receivers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, nullable=True, index=True, comment="默认归属设备 ID（监听型可空，走来源条目归属）")
    device_name = Column(String(255), nullable=False, default="", comment="设备名称冗余")
    name = Column(String(128), nullable=False, default="", comment="接收器名称，如 syslog-514")
    # 源类型（= 接收协议）：syslog / kafka / jdbc / snmp_trap / netflow / rest_api / pcap / file_tail
    protocol = Column(String(32), nullable=False, default="syslog", comment="源类型(接收协议)")
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

    # 适配器实例配置 JSON：新源类型（jdbc/snmp_trap/netflow/rest_api/pcap/file_tail）
    # 的全部参数 + 可选 pipeline 覆盖段 + 轮询水位（拉取类适配器节流回写）。
    # syslog/kafka 兼容走上方类型化列，本列留空即可。
    adapter_config = Column(Text, nullable=False, default="{}", comment="适配器配置 JSON（含流水线覆盖、轮询水位）")

    # 接收内容格式
    format = Column(String(16), nullable=False, default="json", comment="内容格式: json/raw")

    # 手动指定解析策略：NULL/0=自动匹配；>0 固定用该策略解析（失败即解析失败，不自动换）
    strategy_id = Column(Integer, nullable=True, comment="手动绑定的解析策略 ID（NULL/0=自动匹配）")

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
    # 解析命中信息（供数据源条目详情「解析结果」面板展示命中的模板/规则与解析后内容）
    strategy_id = Column(Integer, nullable=True, comment="命中的解析策略 ID")
    strategy_name = Column(String(255), nullable=False, default="", comment="命中的解析策略名称冗余")
    rule_id = Column(String(128), nullable=False, default="", comment="命中的规则标识")
    log_type = Column(String(128), nullable=False, default="", comment="命中的日志类型")
    parsed_fields = Column(Text, nullable=True, comment="解析后的标准模型字段（JSON 序列化）")
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
