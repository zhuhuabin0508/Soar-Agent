"""Device 安全设备模型。

存储安全设备（防火墙/WAF/IPS/EDR等）的连接信息，
每个设备可配置多个动作（DeviceAction），供工作流中的设备动作节点调用。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from app.database import Base


class Device(Base):
    """安全设备模型。"""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="设备名称")
    type = Column(String(64), nullable=False, default="firewall", comment="设备类型: firewall/waf/ips/ids/edr/soar/custom")
    vendor = Column(String(128), nullable=False, default="", comment="厂商: 如 深信服/绿盟/天融信/paloalto/fortinet")
    api_url = Column(String(512), nullable=False, default="", comment="设备 API 基地址，如 https://10.0.0.1:8443/api")
    api_key = Column(String(512), nullable=False, default="", comment="API Key 或 Token")
    username = Column(String(128), nullable=False, default="", comment="用户名（Basic Auth 时用）")
    password = Column(String(256), nullable=False, default="", comment="密码（Basic Auth 时用）")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")
    description = Column(String(512), nullable=False, default="", comment="设备描述")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Device id={self.id} name={self.name!r} type={self.type!r}>"


class DeviceAction(Base):
    """设备动作模型。每个动作对应一个 API 调用。"""
    __tablename__ = "device_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, nullable=False, index=True, comment="所属设备 ID")
    name = Column(String(128), nullable=False, comment="动作名称，如 封禁IP")
    action_type = Column(String(64), nullable=False, default="custom", comment="动作类型: block_ip/unblock_ip/quarantine_host/isolate_endpoint/add_ioc/delete_ioc/custom")
    http_method = Column(String(16), nullable=False, default="POST", comment="HTTP 方法: GET/POST/PUT/DELETE/PATCH")
    api_path = Column(String(512), nullable=False, default="", comment="API 路径（拼在 api_url 后），如 /block/ip")
    # 参数 schema: JSON 数组 [{name, type, required, default, description, placeholder}]
    params_schema = Column(String(4096), nullable=False, default="[]", comment="参数定义 JSON")
    # 额外请求头: JSON 对象 {"X-Custom-Header": "value"}
    headers = Column(String(2048), nullable=False, default="{}", comment="额外请求头 JSON")
    # 请求体模板（含变量占位符 {{param_name}}），留空则用 params 自动构造 JSON
    body_template = Column(String(4096), nullable=False, default="", comment="请求体模板")
    auth_type = Column(String(32), nullable=False, default="api_key", comment="认证方式: api_key/basic/bearer/none")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")
    description = Column(String(512), nullable=False, default="", comment="动作描述")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<DeviceAction id={self.id} device_id={self.device_id} name={self.name!r}>"
