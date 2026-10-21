"""Kafka 输入适配器（aiokafka 消费循环，自原 _run_kafka_consumer 等价迁移）。

连接状态机：connecting → running（成功）/ failed（异常）。
- 背压策略：队列满时阻塞式提交（上限 5s），让 consumer 自然回压暂停拉取；
- 后台任务周期采样 consumer lag 写入内存快照，供健康检查做积压判定。
"""
import asyncio
import logging

from ..base_adapter import BaseAdapter
from ..registry import adapter_registry
from ..state import BACKLOG_SAMPLE_INTERVAL, _recent_stats
from app.core.timezone import beijing_now

logger = logging.getLogger(__name__)


@adapter_registry.register
class KafkaAdapter(BaseAdapter):
    """Kafka topic 消费适配器。"""

    source_type = "kafka"
    display_name = "Kafka 消费"
    default_ready_timeout_s = 8.0  # = CONNECT_WAIT_TIMEOUT_S

    def run(self) -> None:
        receiver = self.ctx.receiver or {}
        bootstrap = receiver.get("kafka_bootstrap") or ""
        topic = (receiver.get("kafka_topic") or "").strip().rstrip(",")
        group = receiver.get("kafka_group") or "soar-ingest"
        if not bootstrap or not topic:
            self.ctx.mark_start_failed("未配置 kafka bootstrap servers / topic")
            self.ctx.signal_ready(False, "未配置 kafka bootstrap servers / topic")
            return

        # 运行时检测 aiokafka；未安装则标记失败
        try:
            from aiokafka import AIOKafkaConsumer  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            msg = f"未安装 aiokafka 依赖，无法消费 kafka: {exc}. 请 pip install aiokafka"
            self.ctx.mark_start_failed(msg)
            self.ctx.signal_ready(False, f"未安装 aiokafka: {exc}")
            return

        topics = [t.strip() for t in topic.split(",") if t.strip()]
        self.ctx.set_status("connecting", None)
        logger.info(
            "kafka 消费者已启动: %s topic=%s group=%s (receiver=%s gen=%s)",
            bootstrap, topic, group, self.ctx.receiver_id, self.ctx.generation,
        )
        asyncio.run(self._kafka_loop(bootstrap, topics, group))

    async def _kafka_loop(self, bootstrap: str, topics: list, group: str) -> None:
        from aiokafka import AIOKafkaConsumer

        receiver_id = self.ctx.receiver_id
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap,
            group_id=group,
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )
        try:
            await consumer.start()
            self.ctx.signal_ready(True)
            # 重置积压统计，避免上次会话的旧值残留
            stat0 = _recent_stats.setdefault(receiver_id, {})
            stat0["kafka_partitions"] = set()
            stat0["backlog"] = 0
            stat0.pop("backlog_error", None)
            stat0["backlog_sampled_at"] = None
            self.ctx.set_status("running", None)

            # 后台积压采样任务：定期计算 consumer lag
            sampling_task = asyncio.create_task(
                self._kafka_backlog_sampler(consumer)
            )

            try:
                async for msg in consumer:
                    if self.ctx.stop_event.is_set():
                        break
                    try:
                        raw = msg.value.decode("utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        raw = repr(msg.value)
                    # kafka 背压策略：队列满时阻塞等待（上限超时）而不是丢弃消息，
                    # 阻塞让 consumer 自然回压暂停拉取，避免丢包。
                    self.ctx.publish(
                        raw, source_ip=None, blocking=True, timeout=5.0,
                        meta={"topic": msg.topic, "partition": msg.partition, "offset": msg.offset},
                    )
            finally:
                sampling_task.cancel()
                try:
                    await sampling_task
                except asyncio.CancelledError:
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.exception("kafka 消费异常: %s", exc)
            if not self.ctx.stop_event.is_set():
                self.ctx.set_status("failed", f"{type(exc).__name__}: {exc}")
                self.ctx.signal_ready(False, f"{type(exc).__name__}: {exc}")
        finally:
            await consumer.stop()

    async def _kafka_backlog_sampler(self, consumer) -> None:
        """周期性采样 kafka consumer lag 并写入内存，供健康检查做积压判定。"""
        try:
            while not self.ctx.stop_event.is_set():
                await self._sample_kafka_lag(consumer)
                await asyncio.sleep(BACKLOG_SAMPLE_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("kafka 积压采样异常（忽略）: %s", exc)
            stat = _recent_stats.setdefault(self.ctx.receiver_id, {})
            stat["backlog"] = 0
            stat["backlog_error"] = str(exc)

    async def _sample_kafka_lag(self, consumer) -> None:
        """计算并存储所有已分配 partition 的 consumer lag 总和。"""
        try:
            partitions = consumer.assignment()
            if not partitions:
                return
            total_lag = 0
            for tp in partitions:
                try:
                    high = await consumer.highwater(tp)
                    pos = await consumer.position(tp)
                    if high is None or pos is None:
                        continue
                    total_lag += max(0, high - pos)
                except Exception:  # noqa: BLE001
                    continue
            stat = _recent_stats.setdefault(self.ctx.receiver_id, {})
            stat["backlog"] = total_lag
            stat["backlog_sampled_at"] = beijing_now()
            stat.pop("backlog_error", None)
        except Exception as exc:  # noqa: BLE001
            stat = _recent_stats.setdefault(self.ctx.receiver_id, {})
            stat["backlog"] = 0
            stat["backlog_error"] = str(exc)
