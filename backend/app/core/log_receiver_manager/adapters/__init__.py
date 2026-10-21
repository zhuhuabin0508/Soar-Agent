"""输入适配器包：import 即触发各适配器自注册（插件发现点）。

新增适配器三步：
1. 新建 ``xxx_adapter.py`` 实现 BaseAdapter 子类并 ``@adapter_registry.register``；
2. 在本文件 import 一次；
3. 运行时按 ``LogReceiver.protocol`` 查注册表启动，无需改引擎代码。
"""
from . import (
    file_tail_adapter,  # noqa: F401
    jdbc_adapter,  # noqa: F401
    kafka_adapter,  # noqa: F401
    netflow_adapter,  # noqa: F401
    pcap_adapter,  # noqa: F401
    rest_api_adapter,  # noqa: F401
    snmp_trap_adapter,  # noqa: F401
    syslog_adapter,  # noqa: F401
)
