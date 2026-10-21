"""BaseAdapter：输入适配器抽象基类。

每种输入源（syslog/kafka/jdbc/snmp_trap/netflow/rest_api/pcap/file_tail）
实现一个子类，经 ``@adapter_registry.register`` 注册后由 runtime 统一启停：

线程模型（与重构前一致）：每接收渠道一条监听线程；generation/stop_event/
ready_event 逐代取消机制由 runtime 维护，适配器只关心 ``run/stop``。

生命周期契约：
1. ``run()`` 阻塞运行至 stop；启动成功/失败必须调用 ``ctx.signal_ready``，
   供保存接口同步核实 bind/connect 结果；
2. ``run()`` 内部异常自行捕获并 ``ctx.set_status("failed", ...)`` 后返回，
   runtime 仅兜底未捕获异常；
3. 持有 socket/sniffer 等资源的适配器覆写 ``stop()`` 主动释放。
"""
import logging
import threading
from abc import ABC, abstractmethod
from typing import ClassVar

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """输入适配器基类。"""

    # 源类型标识（= LogReceiver.protocol，注册表键）
    source_type: ClassVar[str] = ""
    # 展示名（前端下拉/API 元数据）
    display_name: ClassVar[str] = ""
    # start_receiver_sync 同步等待启动结果的超时（秒）
    default_ready_timeout_s: ClassVar[float] = 8.0
    # 必填配置键声明（[(键, 中文说明), ...]，供 API 校验与前端提示）
    required_config_keys: ClassVar[list] = []

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @abstractmethod
    def run(self) -> None:
        """阻塞运行至 stop；先 signal_ready(成功/失败) 再进入主循环。"""

    def stop(self) -> None:
        """默认实现：仅置位 stop_event；持有资源的适配器覆写主动 shutdown。"""
        self.ctx.stop_event.set()

    # ------------------------------------------------------------------
    # 便捷属性
    # ------------------------------------------------------------------
    @property
    def stop_event(self) -> threading.Event:
        return self.ctx.stop_event

    @property
    def receiver(self) -> dict:
        return self.ctx.receiver

    @property
    def runtime_ref(self) -> dict:
        return self.ctx.runtime_ref
