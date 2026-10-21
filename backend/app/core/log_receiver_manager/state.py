"""日志采集子系统进程级共享状态。

独立成模块的原因：runtime（状态机/启停）与 adapters（监听实现）需要共享
``_runtimes`` / ``_recent_stats`` 等内存快照；若互相直接 import 会形成循环。
本模块不依赖包内其他模块，任何一方均可安全顶层导入。
"""
import os
import tempfile
import threading
from typing import Any

# ----------------------------------------------------------------------
# 常量（自原 log_receiver_manager.py 平移，语义不变）
# ----------------------------------------------------------------------
# 后台健康检查间隔（秒）
HEALTH_CHECK_INTERVAL = 60
# 断流判定：超过该秒数无新日志触发"断流"告警
NO_DATA_STALE_SECONDS = 600
# 解析失败率阈值（%）
FAIL_RATE_THRESHOLD = 80.0
# kafka 积压阈值（条）
BACKLOG_THRESHOLD = 10000
# kafka 积压采样间隔（秒）
BACKLOG_SAMPLE_INTERVAL = 30
# kafka 积压恢复缓冲（条）：低于 阈值-缓冲 才解除告警，避免抖振
BACKLOG_RECOVER_MARGIN = 1000
# 保存/重启接收渠道时同步等待 bind 结果的超时（秒）
BIND_WAIT_TIMEOUT_S = 3.0
# 保存/重启接收渠道时同步等待 connect 结果的超时（秒）
CONNECT_WAIT_TIMEOUT_S = 8.0
# 监听线程优雅停止等待时间（秒）
STOP_JOIN_TIMEOUT_S = 5.0

# 跨平台文件锁（用于多 worker 部署协调：仅一个 worker 启动监听）
try:  # POSIX（生产容器为 Linux）
    import fcntl as _fcntl
except ImportError:  # Windows 开发环境
    _fcntl = None
try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

# 单 worker 监听锁文件路径（可经环境变量覆盖）
_LISTENER_LOCK_PATH = os.environ.get(
    "LOG_RECEIVER_LOCK_PATH", os.path.join(tempfile.gettempdir(), "soar-log-receiver.lock")
)

_manager_started = False
_manager_lock = threading.Lock()

# 内存中的运行状态快照：receiver_id -> {thread, socket_server, stop_event, ...}
_runtimes: dict[int, dict[str, Any]] = {}

# 每个接收渠道的最近指标（内存，供健康检查）
_recent_stats: dict[int, dict[str, Any]] = {}

# 断流/失败率告警去重状态
_alerted: dict[str, bool] = {}
# 最近一次发送通知的时间（用于按 notify_interval_minutes 间隔重复提醒）
_last_notify_at: dict[str, Any] = {}

# 进程级文件锁句柄（保持打开以持有锁）
_listener_lock_fh = None


def _runtime_receiver(receiver_key) -> dict | None:
    """从内存快照中取接收渠道配置（含 DB 里最新字段）。"""
    if receiver_key is None:
        return None
    rt = _runtimes.get(receiver_key)
    return (rt or {}).get("receiver")


def _runtime_bucket(receiver_id: int) -> dict:
    """取某接收渠道的运行时桶（不存在则初始化，含逐代 stop/ready/failed 事件）。"""
    rt = _runtimes.setdefault(
        receiver_id,
        {
            "stop_event": threading.Event(),
            # 本代启动是否已就绪（成功标 ready，失败标 ready+failed）
            "ready_event": threading.Event(),
            "failed_event": threading.Event(),
            # 代计数：每次重启自增，旧代循环据此识别自己是旧代
            "generation": 0,
        },
    )
    return rt
