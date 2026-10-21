"""AdapterContext：runtime 注入给适配器的运行时句柄。

适配器不直接触碰 runtime 全局状态（_runtimes/DB 状态机），统一经 ctx：
- ``signal_ready`` / ``set_status`` / ``mark_start_failed``：状态机回调
  （由 runtime 构造 ctx 时注入，避免 adapters → runtime 循环导入，测试可注入桩）；
- ``publish``：把原始报文包装为 :class:`RawEvent` 投递到可插拔总线。
"""
import logging
from typing import Any, Callable, Optional

from app.core.timezone import beijing_now

from .bus import get_bus
from .events import RawEvent
from .state import _runtime_receiver

logger = logging.getLogger(__name__)


class AdapterContext:
    """适配器运行时句柄（每代监听线程一份）。"""

    def __init__(
        self,
        receiver_id: int,
        generation: int,
        stop_event,
        receiver: dict,
        runtime_ref: Optional[dict] = None,
        on_ready: Optional[Callable[[int, bool, str], None]] = None,
        on_status: Optional[Callable[[int, str, Optional[str]], None]] = None,
    ) -> None:
        self.receiver_id = receiver_id
        self.generation = generation
        self.stop_event = stop_event
        self.receiver = receiver                    # 启动时的渠道配置快照
        self.runtime_ref: dict = runtime_ref if runtime_ref is not None else {}
        # runtime 注入的状态机回调（signal_ready / set_status）
        self._on_ready = on_ready
        self._on_status = on_status

    # ------------------------------------------------------------------
    # 状态机（迁移自 _signal_generation_started / _set_status / _mark_start_failed）
    # ------------------------------------------------------------------
    def signal_ready(self, success: bool, error: str = "") -> None:
        """本代启动完成：置位 ready_event（成功），失败时另置位 failed_event。"""
        if self._on_ready is not None:
            self._on_ready(self.receiver_id, success, error)

    def set_status(self, status: str, error: Optional[str] = None) -> None:
        """更新渠道运行状态到 DB（binding/listening/running/failed/...）。"""
        if self._on_status is not None:
            self._on_status(self.receiver_id, status, error)

    def mark_start_failed(self, error: str) -> None:
        """标记启动失败（start_failed）并记日志。"""
        self.set_status("start_failed", error)
        logger.error("接收渠道 %s 启动失败: %s", self.receiver_id, error)

    # ------------------------------------------------------------------
    # 事件投递（统一 RawEvent → 可插拔总线）
    # ------------------------------------------------------------------
    def publish(
        self,
        raw: str,
        source_ip: Optional[str] = None,
        meta: Optional[dict] = None,
        transport: Optional[str] = None,
        blocking: bool = False,
        timeout: float = 5.0,
    ) -> bool:
        """把一条原始日志包装为 RawEvent 投递到总线。

        - 渠道配置优先取内存快照最新值（运行中被 refresh 后立即生效），
          取不到时退回启动快照；
        - ``blocking=False``（syslog 类）：队列满即丢弃并背压计数；
        - ``blocking=True``（kafka 类）：队列满阻塞等待（上限 timeout），
          让消费端自然回压，避免丢消息。
        """
        if not raw:
            return True
        receiver = _runtime_receiver(self.receiver_id) or self.receiver
        source_type = receiver.get("protocol") or self.receiver.get("protocol") or ""
        event = RawEvent(
            receiver_id=self.receiver_id,
            device_id=receiver.get("device_id"),
            source_type=source_type,
            source_ip=source_ip,
            transport=transport or source_type,
            received_at=beijing_now(),
            raw=raw,
            meta=meta or {},
            receiver=receiver,
        )
        return get_bus().publish(event, blocking=blocking, timeout=timeout)
