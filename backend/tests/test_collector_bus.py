"""采集子系统总线单测：InProcessBus 满载丢弃 / 阻塞提交 / 窗口聚合（不依赖 DB）。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_collector_bus.py -v
"""
import os
import sys
import threading
import time

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.log_receiver_manager.bus import reset_bus
from app.core.log_receiver_manager.bus.inprocess_bus import InProcessBus
from app.core.log_receiver_manager.events import RawEvent
from datetime import datetime


def _mk_event(i=0, raw="x"):
    return RawEvent(
        receiver_id=1, device_id=None, source_type="syslog", source_ip="1.2.3.4",
        transport="udp", received_at=datetime.now(), raw=raw,
    )


class TestInProcessBus:
    def test_publish_consume_roundtrip(self):
        bus = InProcessBus(maxsize=10)
        ev = _mk_event(raw="hello")
        assert bus.publish(ev) is True
        got = bus.consume()
        assert got is ev
        bus.task_done()

    def test_empty_raw_skipped(self):
        bus = InProcessBus(maxsize=10)
        assert bus.publish(_mk_event(raw="")) is True
        assert bus.stats()["qsize"] == 0

    def test_overflow_drop_counts(self):
        bus = InProcessBus(maxsize=2)
        assert bus.publish(_mk_event(raw="a"))
        assert bus.publish(_mk_event(raw="b"))
        assert bus.publish(_mk_event(raw="c")) is False  # 满载丢弃
        assert bus.publish(_mk_event(raw="d")) is False
        assert bus.stats()["dropped"] == 2
        assert bus.stats()["qsize"] == 2

    def test_blocking_publish_waits_for_space(self):
        bus = InProcessBus(maxsize=1)
        assert bus.publish(_mk_event(raw="a"))
        result = {}

        def _publisher():
            result["ok"] = bus.publish(_mk_event(raw="b"), blocking=True, timeout=5.0)

        t = threading.Thread(target=_publisher)
        t.start()
        time.sleep(0.2)
        assert bus.consume() is not None  # 腾出空间
        bus.task_done()
        t.join(timeout=5)
        assert result.get("ok") is True

    def test_blocking_publish_timeout_drops(self):
        bus = InProcessBus(maxsize=1)
        bus.publish(_mk_event(raw="a"))
        assert bus.publish(_mk_event(raw="b"), blocking=True, timeout=0.2) is False
        assert bus.stats()["dropped"] == 1

    def test_worker_pool_processes_events(self):
        bus = InProcessBus(maxsize=10, workers=2)
        got = []
        done = threading.Event()

        def handler(event):
            got.append(event.raw)
            if len(got) >= 3:
                done.set()

        bus.set_handler(handler)
        bus.start()
        try:
            for i in range(3):
                bus.publish(_mk_event(raw=f"m{i}"))
            assert done.wait(timeout=5)
            assert sorted(got) == ["m0", "m1", "m2"]
        finally:
            bus.stop()

    def test_get_bus_singleton_and_reset(self):
        reset_bus()
        from app.core.log_receiver_manager.bus import get_bus

        b1 = get_bus()
        b2 = get_bus()
        assert b1 is b2
        assert isinstance(b1, InProcessBus)  # 默认后端
        reset_bus()

    def test_raw_event_dict_roundtrip(self):
        ev = _mk_event(raw="payload")
        ev.meta = {"topic": "t1"}
        ev.receiver = {"id": 1, "protocol": "kafka"}
        restored = RawEvent.from_dict(ev.to_dict())
        assert restored.raw == "payload"
        assert restored.meta == {"topic": "t1"}
        assert restored.receiver == {"id": 1, "protocol": "kafka"}
        assert restored.receiver_id == 1
        assert restored.source_ip == "1.2.3.4"
