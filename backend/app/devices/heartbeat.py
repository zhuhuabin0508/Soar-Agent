"""设备后台健康检查心跳。

在后台周期探测所有启用设备（主动方式为 GET api_url 健康端点），
自动更新 status / last_heartbeat / last_test_error / last_test_latency_ms，
避免设备状态只在用户手动触发 ``POST /devices/health-check`` 时才刷新。

探测逻辑复用 ``app.api.v1.devices._test_device_connection``（不重复实现），
运行时惰性导入以避免模块循环依赖。

核心入口：
- ``start_device_heartbeat``: 启动后台心跳线程（幂等，由 main lifespan 调用）。
"""
import logging
import os
import threading
import time as _time

logger = logging.getLogger(__name__)

# 心跳间隔（秒），可通过环境变量 DEVICE_HEARTBEAT_INTERVAL 覆盖
DEVICE_HEARTBEAT_INTERVAL = int(os.environ.get("DEVICE_HEARTBEAT_INTERVAL", "60"))

_started = False
_lock = threading.Lock()


def _heartbeat_loop() -> None:
    """心跳主循环（阻塞）：周期探测全部启用设备并更新连接状态。"""
    from app.database import SessionLocal
    from app.models.device import Device
    from app.core.timezone import beijing_now

    logger.info("设备健康检查心跳线程已启动，间隔 %ds", DEVICE_HEARTBEAT_INTERVAL)
    while True:
        try:
            db = SessionLocal()
            try:
                from app.api.v1.devices import _test_device_connection

                devices = db.query(Device).filter(Device.enabled.is_(True)).all()
                now = beijing_now()
                online = 0
                for device in devices:
                    # 未配置 api_url 的设备不做主动探测，保持 unconfigured
                    if not (device.api_url or "").strip():
                        continue
                    try:
                        success, _status_code, latency, error, new_status = (
                            _test_device_connection(device)
                        )
                        device.status = new_status
                        device.last_heartbeat = now
                        device.last_test_error = None if success else error
                        device.last_test_latency_ms = latency
                        if new_status == "online":
                            online += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("设备心跳探测异常 device=%s: %s", device.id, exc)
                db.commit()
                if devices:
                    logger.info("设备心跳完成: total=%s, online=%s",
                                len(devices), online)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("设备心跳健康检查异常（忽略）: %s", exc)
        _time.sleep(DEVICE_HEARTBEAT_INTERVAL)


def start_device_heartbeat() -> None:
    """启动设备后台心跳线程（幂等）。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_heartbeat_loop, daemon=True, name="device-heartbeat")
    t.start()
