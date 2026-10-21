"""设备日志接收管理器（被动接入 + 主动拉取，NGSOC 式多源采集架构）。

原单文件模块（log_receiver_manager.py）原地重构为同名包，对外接口经本门面
re-export，6 处既有 import（main.py / devices.py / log_receivers.py）路径零改动。

架构总览（详见 .trae/documents/日志采集NGSOC架构重构方案.md）：

1. 多源输入层（adapters/）：7 种输入适配器（syslog/kafka/jdbc/snmp_trap/
   netflow/rest_api/pcap/file_tail），插件注册、独立线程、统一输出 RawEvent；
2. 可插拔总线（bus/）：默认进程内有界队列（2000 条 + 8 worker + 丢包窗口
   聚合），可环境变量切换 Kafka；
3. 范式化流水线（pipeline/）：预处理插件链 → 解析→过滤→富化→内容转译→
   范式化 五步可插拔组件，输出 ECS 风格 NormalizedEvent，末端无损映射回
   AlertEvent 落库（下游告警页/工作流/看板零改动）；
4. 运行时（runtime.py + state.py）：generation/stop_event 逐代取消状态机、
   健康检查（断流/失败率/积压）、多 worker 文件锁，均自原实现平移。
"""
from . import adapters  # noqa: F401  # 触发适配器自注册
from .adapter_context import AdapterContext
from .base_adapter import BaseAdapter
from .events import NormalizedEvent, RawEvent
from .registry import (
    adapter_registry,
    preprocessor_registry,
    stage_registry,
)
from .runtime import (
    _alert_ok,
    _build_recent_stats,
    _check_and_alert_receivers,
    _dispatch_alert,
    _mark_notified,
    _mark_start_failed,
    _refresh_runtime_receiver,
    _run_health_check,
    _safe_close_server,
    _set_status,
    _should_notify,
    _signal_generation_started,
    _try_acquire_listener_lock,
    ensure_receiver_thread,
    get_receiver_runtime_status,
    reload_all_receivers,
    start_log_receiver_manager,
    start_receiver_sync,
    stop_receiver_thread,
)
from .state import (
    BACKLOG_RECOVER_MARGIN,
    BACKLOG_SAMPLE_INTERVAL,
    BACKLOG_THRESHOLD,
    BIND_WAIT_TIMEOUT_S,
    CONNECT_WAIT_TIMEOUT_S,
    FAIL_RATE_THRESHOLD,
    HEALTH_CHECK_INTERVAL,
    NO_DATA_STALE_SECONDS,
    STOP_JOIN_TIMEOUT_S,
    _alerted,
    _last_notify_at,
    _recent_stats,
    _runtimes,
    _runtime_bucket,
    _runtime_receiver,
)
from .pipeline.preprocessors import (
    _coerce_payload,
    _unescape_qt_value,
    parse_qingteng_syslog,
)
from .pipeline.sink import (
    ReceiverSink,
    _bump_counts,
    _summarize_large_value,
)

__all__ = [
    # 启停与运行时（既有 API/main 引用）
    "start_log_receiver_manager",
    "ensure_receiver_thread",
    "start_receiver_sync",
    "stop_receiver_thread",
    "reload_all_receivers",
    "get_receiver_runtime_status",
    # 事件模型
    "RawEvent",
    "NormalizedEvent",
    # 插件体系
    "BaseAdapter",
    "AdapterContext",
    "adapter_registry",
    "stage_registry",
    "preprocessor_registry",
    # 持久化 sink 与预处理器（防测试脚本/外部引用）
    "ReceiverSink",
    "parse_qingteng_syslog",
    "_coerce_payload",
    "_unescape_qt_value",
    "_bump_counts",
    "_summarize_large_value",
    # 状态机与快照（内部符号，平移自原模块）
    "_set_status",
    "_mark_start_failed",
    "_signal_generation_started",
    "_refresh_runtime_receiver",
    "_runtime_bucket",
    "_runtime_receiver",
    "_safe_close_server",
    "_runtimes",
    "_recent_stats",
    "_alerted",
    "_last_notify_at",
    "_alert_ok",
    "_mark_notified",
    "_should_notify",
    "_dispatch_alert",
    "_build_recent_stats",
    "_check_and_alert_receivers",
    "_run_health_check",
    "_try_acquire_listener_lock",
    # 常量（平移自原模块）
    "HEALTH_CHECK_INTERVAL",
    "NO_DATA_STALE_SECONDS",
    "FAIL_RATE_THRESHOLD",
    "BACKLOG_THRESHOLD",
    "BACKLOG_SAMPLE_INTERVAL",
    "BACKLOG_RECOVER_MARGIN",
    "BIND_WAIT_TIMEOUT_S",
    "CONNECT_WAIT_TIMEOUT_S",
    "STOP_JOIN_TIMEOUT_S",
]
