"""安全设备适配层。

聚合各类安全设备（如防火墙）的处置能力，对外提供统一调用入口。
"""
from app.devices.firewall import block_ip_on_firewall, is_ip_blocked
from app.devices.action_executor import execute_device_action, find_device_action_by_type

__all__ = [
    "block_ip_on_firewall", "is_ip_blocked",
    "execute_device_action", "find_device_action_by_type",
]
