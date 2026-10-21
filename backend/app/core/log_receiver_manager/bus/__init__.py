"""总线工厂：按环境变量选择后端，默认进程内有界队列。

环境变量：
- ``LOG_BUS_BACKEND``：``inprocess``（默认）/ ``kafka``
- ``LOG_BUS_KAFKA_BOOTSTRAP`` / ``LOG_BUS_KAFKA_TOPIC``：kafka 后端连接参数
  （阶段8提供 KafkaBus 实现，未就绪/初始化失败时自动回退进程内总线）。
"""
import logging
import os
import threading
from typing import Optional

from .base import RawEventBus

logger = logging.getLogger(__name__)

_bus: Optional[RawEventBus] = None
_bus_lock = threading.Lock()


def get_bus() -> RawEventBus:
    """获取（惰性创建）进程级总线单例。"""
    global _bus
    if _bus is not None:
        return _bus
    with _bus_lock:
        if _bus is None:
            backend = (os.environ.get("LOG_BUS_BACKEND") or "inprocess").strip().lower()
            if backend == "kafka":
                try:
                    from .kafka_bus import KafkaBus

                    _bus = KafkaBus()
                    logger.info("原始事件总线后端: kafka")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("kafka 总线初始化失败，回退进程内总线: %s", exc)
                    _bus = _make_inprocess()
            else:
                _bus = _make_inprocess()
    return _bus


def reset_bus() -> None:
    """重置总线单例（仅测试用）。"""
    global _bus
    with _bus_lock:
        _bus = None


def _make_inprocess() -> RawEventBus:
    from .inprocess_bus import InProcessBus

    return InProcessBus()
