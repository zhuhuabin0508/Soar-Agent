"""RawEventBus：原始事件总线抽象接口。

默认实现为进程内有界队列（InProcessBus，含背压丢弃与固定 worker 池）；
可通过环境变量 ``LOG_BUS_BACKEND=kafka`` 切换为 Kafka 分布式总线
（见 bus/kafka_bus.py，阶段8提供）。
"""
from abc import ABC, abstractmethod
from typing import Callable, Optional

from ..events import RawEvent


class RawEventBus(ABC):
    """原始事件总线（生产者=各适配器，消费者=流水线 worker 池）。"""

    @abstractmethod
    def publish(self, event: RawEvent, blocking: bool = False, timeout: float = 5.0) -> bool:
        """投递一条原始事件。

        - ``blocking=False``：队列满即丢弃并背压计数，返回 False；
        - ``blocking=True``：队列满阻塞等待（上限 timeout 秒），超时丢弃返回 False。
        """

    @abstractmethod
    def consume(self) -> RawEvent:
        """（worker 内部）阻塞取出一条事件。"""

    @abstractmethod
    def task_done(self) -> None:
        """（worker 内部）标记一条事件处理完成。"""

    @abstractmethod
    def start(self) -> None:
        """启动消费 worker 池（幂等）。"""

    @abstractmethod
    def set_handler(self, handler: Callable[[RawEvent], None]) -> None:
        """注入消费回调（worker 每条事件调用一次；必须在 start 前注入）。"""

    @abstractmethod
    def stats(self) -> dict:
        """返回 {"qsize", "maxsize", "dropped", "workers"} 运行指标。"""

    @abstractmethod
    def flush_drop_warning(self, trigger: str = "threshold") -> None:
        """背压丢弃警告窗口聚合输出（trigger ∈ threshold/health/shutdown）。"""

    def stop(self, join_timeout: float = 5.0) -> None:  # pragma: no cover
        """停止总线（默认无操作；有后台线程的实现覆写）。"""
