"""InProcessBus：进程内有界队列总线（默认后端）。

行为等价迁移自原 log_receiver_manager.py 的入站并发与背压设计：
- 有界队列（上限 2000 条）+ 固定 worker 线程池（8 个）；
- 队列满导致的丢包按 1s 时间窗口聚合为一条警告（避免高频突发刷屏），
  结束/健康检查时 flush 补报尾数；
- worker 循环体 = 原 ``_ingest_worker``：取事件 → 流水线回调 → task_done，
  异常全部吞掉记日志，worker 永不退出。
"""
import logging
import queue
import threading
import time as _time
from typing import Callable, Optional

from ..events import RawEvent
from .base import RawEventBus

logger = logging.getLogger(__name__)

# 消费 worker 线程数量
_INGEST_WORKERS = 8
# 有界队列上限（条）。超过则丢弃计为背压丢弃，避免积压耗尽内存/线程
_INGEST_QUEUE_MAX = 2000
# 背压丢弃警告节流窗口（秒）
_DROP_LOG_WINDOW_S = 1.0


class InProcessBus(RawEventBus):
    """进程内总线：queue.Queue + 固定 worker 池（默认后端）。"""

    def __init__(
        self,
        maxsize: int = _INGEST_QUEUE_MAX,
        workers: int = _INGEST_WORKERS,
    ) -> None:
        self._queue: "queue.Queue[RawEvent]" = queue.Queue(maxsize=maxsize)
        self._workers = workers
        self._handler: Optional[Callable[[RawEvent], None]] = None
        self._worker_threads: list[threading.Thread] = []
        self._started = False
        self._start_lock = threading.Lock()
        # 背压丢弃聚合状态（窗口内计数 + 上次告警时间）与累计丢弃数
        self._drop_state: dict = {"count": 0, "last_log": 0.0}
        self._dropped_total = 0

    # ------------------------------------------------------------------
    # 生产端
    # ------------------------------------------------------------------
    def publish(self, event: RawEvent, blocking: bool = False, timeout: float = 5.0) -> bool:
        """投递事件：默认队列满即丢弃（syslog 式）；blocking=True 阻塞等待
        （kafka 式，让上游消费端自然回压）。"""
        if not event or not event.raw:
            return True
        try:
            if blocking:
                self._queue.put(event, timeout=timeout)
                return True
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            self._drop_warning_record()
            return False

    # ------------------------------------------------------------------
    # 消费端（worker 池）
    # ------------------------------------------------------------------
    def consume(self) -> RawEvent:
        return self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def set_handler(self, handler: Callable[[RawEvent], None]) -> None:
        self._handler = handler

    def start(self) -> None:
        """启动消费 worker 线程池（幂等：已启动则跳过）。"""
        with self._start_lock:
            if self._started:
                return
            self._started = True
            for i in range(self._workers):
                wt = threading.Thread(
                    target=self._worker_loop, daemon=True, name=f"log-ingest-{i}"
                )
                wt.start()
                self._worker_threads.append(wt)

    def _worker_loop(self) -> None:
        """消费 worker：从有界队列取事件并送入流水线（异常吞掉，永不退出）。"""
        while True:
            try:
                event = self.consume()
                try:
                    if self._handler is None:
                        logger.error("总线 handler 未注入，事件被丢弃（应先 set_handler 再 start）")
                    else:
                        self._handler(event)
                except Exception:  # noqa: BLE001
                    logger.exception("入站 worker 处理异常（忽略）")
                finally:
                    self.task_done()
            except Exception:  # noqa: BLE001
                logger.exception("入站 worker 取队列异常（忽略）")

    def stop(self, join_timeout: float = 5.0) -> None:  # pragma: no cover
        """停止 worker 池（守护线程，仅用于测试与关停；join 后不再消费）。"""
        with self._start_lock:
            threads = list(self._worker_threads)
            self._worker_threads.clear()
            self._started = False
        for t in threads:
            if t is not threading.current_thread():
                t.join(timeout=join_timeout)
        self.flush_drop_warning(trigger="shutdown")

    # ------------------------------------------------------------------
    # 运行指标与背压告警
    # ------------------------------------------------------------------
    def stats(self) -> dict:
        return {
            "qsize": self._queue.qsize(),
            "maxsize": self._queue.maxsize,
            "dropped": self._dropped_total,
            "workers": len(self._worker_threads),
        }

    def _drop_warning_flush(self, trigger: str = "threshold") -> None:
        """按窗口聚合的输出：累计 count > 0 且窗口已到则打一条警告并清零。"""
        count = self._drop_state.get("count") or 0
        if count <= 0:
            return
        now = _time.monotonic()
        if trigger != "shutdown" and now - (self._drop_state.get("last_log") or 0.0) < _DROP_LOG_WINDOW_S:
            return
        logger.warning(
            "入站队列已满，本窗口丢弃日志 %s 条（队列 %s/%s）",
            count,
            self._queue.qsize(),
            self._queue.maxsize,
        )
        self._drop_state["count"] = 0
        self._drop_state["last_log"] = now

    def _drop_warning_record(self) -> None:
        """记一次背压丢弃；若窗口已到则立即聚合输出一条警告。"""
        self._drop_state["count"] = (self._drop_state.get("count") or 0) + 1
        self._dropped_total += 1
        now = _time.monotonic()
        if now - (self._drop_state.get("last_log") or 0.0) >= _DROP_LOG_WINDOW_S:
            self._drop_warning_flush()

    def flush_drop_warning(self, trigger: str = "threshold") -> None:
        """对外暴露的丢弃警告窗口输出（健康检查周期补报尾数）。"""
        self._drop_warning_flush(trigger)
