"""系统资源告警调度器。

后台守护线程，每隔 ``CHECK_INTERVAL`` 秒检查 CPU / 内存 / 磁盘 使用率，
超过阈值时通过 ``dispatch_notification(event_type="system_alert")`` 派发告警。

设计要点：
- 仅在状态由「正常」转为「异常」时通知，避免重复告警。
- 每项资源独立跟踪状态（CPU / 内存 / 磁盘），互不影响。
- 所有异常吞掉，调度器本身永不退出。
"""
import logging
import threading
import time as _time
from typing import Optional

from app.core.timezone import beijing_now

logger = logging.getLogger(__name__)

# 检查间隔（秒）
CHECK_INTERVAL = 60
# 告警阈值（百分比）
CPU_THRESHOLD = 90.0
MEMORY_THRESHOLD = 90.0
DISK_THRESHOLD = 90.0

_scheduler_started = False
_scheduler_lock = threading.Lock()

# 记录每项资源是否已告警（避免重复）
_alert_state: dict[str, bool] = {
    "cpu": False,
    "memory": False,
    "disk": False,
}


def _check_and_alert() -> None:
    """检查系统资源，超阈值时派发 system_alert 通知。"""
    import psutil

    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        import shutil
        disk = shutil.disk_usage("/")

        alerts: list[str] = []

        # CPU 检查
        if cpu_percent >= CPU_THRESHOLD and not _alert_state["cpu"]:
            alerts.append(f"CPU 使用率 {cpu_percent:.1f}%（阈值 {CPU_THRESHOLD}%）")
            _alert_state["cpu"] = True
        elif cpu_percent < CPU_THRESHOLD - 5 and _alert_state["cpu"]:
            _alert_state["cpu"] = False  # 恢复

        # 内存检查
        if mem.percent >= MEMORY_THRESHOLD and not _alert_state["memory"]:
            alerts.append(f"内存使用率 {mem.percent:.1f}%（阈值 {MEMORY_THRESHOLD}%）")
            _alert_state["memory"] = True
        elif mem.percent < MEMORY_THRESHOLD - 5 and _alert_state["memory"]:
            _alert_state["memory"] = False  # 恢复

        # 磁盘检查
        disk_percent = round(disk.used / disk.total * 100, 1)
        if disk_percent >= DISK_THRESHOLD and not _alert_state["disk"]:
            alerts.append(f"磁盘使用率 {disk_percent:.1f}%（阈值 {DISK_THRESHOLD}%）")
            _alert_state["disk"] = True
        elif disk_percent < DISK_THRESHOLD - 5 and _alert_state["disk"]:
            _alert_state["disk"] = False  # 恢复

        if not alerts:
            return  # 一切正常，不发通知

        # 有异常，走通知规则路由派发
        from app.database import SessionLocal
        from app.core.notification_dispatch import dispatch_notification

        db = SessionLocal()
        try:
            dispatch_notification(
                db,
                event_type="system_alert",
                title="系统资源告警",
                content=(
                    f"系统资源超过阈值，请及时处理。\n\n"
                    + "\n".join(f"• {a}" for a in alerts)
                    + f"\n\n时间：{beijing_now().strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                related_type="system_monitor",
                related_id=None,
                created_by="system",
            )
            logger.warning("system_alert 通知已派发: %s", ", ".join(alerts))
        finally:
            db.close()

    except Exception as exc:  # noqa: BLE001
        logger.warning("系统资源告警检查失败: %s", exc)


def _run_scheduler() -> None:
    """调度器主循环。"""
    logger.info("系统资源告警调度器已启动，检查间隔 %ds", CHECK_INTERVAL)
    while True:
        try:
            _check_and_alert()
        except Exception as exc:  # noqa: BLE001
            logger.warning("系统资源告警调度器异常: %s", exc)
        _time.sleep(CHECK_INTERVAL)


def start_system_alert_scheduler() -> None:
    """启动系统资源告警调度器（仅启动一次）。"""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
        t = threading.Thread(target=_run_scheduler, daemon=True, name="system-alert-scheduler")
        t.start()
        logger.info("系统资源告警调度器线程已创建")
