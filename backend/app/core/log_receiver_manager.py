"""设备日志接收管理器（被动接入：对方设备主动推送）。

核心职责：
1. 启动/停止每个启用接收渠道的监听线程（syslog UDP/TCP / kafka consumer）。
2. 收到原始日志后写入 ``device_receive_logs``，并交由 ``ParseEngine`` 解析入库
   （复用告警解析管道 → alert_events → 触发封禁工作流）。
3. 维护接收渠道运行状态（running/start_failed/stopped）、累计接收/异常计数。
4. 通过后台调度检查「断流 / 解析失败率 / kafka 积压」并派发通知。

设计要点：
- syslog 用标准库 ``socketserver``，零额外依赖。
- kafka 优先使用 ``aiokafka``；未安装时渠道标记为 start_failed 并给出明确提示。
- 所有接收线程异常吞掉，管理器主循环永不退出。
"""
import hashlib
import json
import logging
import os
import queue
import re
import socketserver
import tempfile
import threading
import time as _time
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.timezone import BEIJING_TZ, beijing_now
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# 跨平台文件锁（用于多 worker 部署协调：仅一个 worker 启动 syslog/kafka 监听）
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

# ----------------------------------------------------------------------
# 常量
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
# 保存/重启接收渠道时同步等待 bind/connect 结果的超时（秒）
# syslog 绑定端口 / kafka 连接 broker 应在该超时内成功或失败，
# 让 HTTP 保存接口能实时把端口占用/连接失败报给用户，而不是事后才变 failed。
BIND_WAIT_TIMEOUT_S = 3.0
CONNECT_WAIT_TIMEOUT_S = 8.0
# 监听线程优雅停止等待时间（秒）
STOP_JOIN_TIMEOUT_S = 5.0

_manager_started = False
_manager_lock = threading.Lock()

# 内存中的运行状态快照：receiver_id -> {thread, socket_server, stop_event, ...}
_runtimes: dict[int, dict[str, Any]] = {}

# 每个接收渠道的最近指标（内存，供健康检查）
_recent_stats: dict[int, dict[str, Any]] = {}

# 断流/失败率告警去重状态
_alerted: dict[str, bool] = {}
# 最近一次发送通知的时间（用于按 notify_interval_minutes 间隔重复提醒）
_last_notify_at: dict[str, datetime] = {}

# ----------------------------------------------------------------------
# 入站并发与背压：有界队列 + 固定 worker 线程池
# ----------------------------------------------------------------------
# 消费 worker 线程数量
_INGEST_WORKERS = 8
# 有界队列上限（条）。超过则丢弃计为背压丢弃，避免积压耗尽内存/线程
_INGEST_QUEUE_MAX = 2000
# 统一的入站处理队列（syslog 与 kafka 共用一个池子）
_ingest_queue: "queue.Queue" = queue.Queue(maxsize=_INGEST_QUEUE_MAX)

# 背压丢弃警告节流窗口（秒）：队列满导致的丢包按窗口聚合为一条警告，
# 避免高频 syslog 突发时每条丢弃都打日志刷屏；结束时 flush 补报尾数。
_DROP_LOG_WINDOW_S = 1.0
# 背压丢弃聚合状态（内存）
_drop_state: dict[str, Any] = {"count": 0, "last_log": 0.0}


def _drop_warning_flush(trigger: str = "threshold") -> None:
    """按窗口聚合的输出：累计 count > 0 且窗口已到则打一条警告并清零。"""
    count = _drop_state.get("count") or 0
    if count <= 0:
        return
    now = _time.monotonic()
    if trigger != "shutdown" and now - (_drop_state.get("last_log") or 0.0) < _DROP_LOG_WINDOW_S:
        return
    logger.warning(
        "入站队列已满，本窗口丢弃日志 %s 条（队列 %s/%s）",
        count,
        _ingest_queue.qsize(),
        _ingest_queue.maxsize,
    )
    _drop_state["count"] = 0
    _drop_state["last_log"] = now


def _drop_warning_record() -> None:
    """记一次背压丢弃；若窗口已到则立即聚合输出一条警告。"""
    _drop_state["count"] = (_drop_state.get("count") or 0) + 1
    now = _time.monotonic()
    if now - (_drop_state.get("last_log") or 0.0) >= _DROP_LOG_WINDOW_S:
        _drop_warning_flush()


def _ingest_worker() -> None:
    """消费 worker：从有界队列取任务并送入解析管道。"""
    while True:
        try:
            raw, receiver, source_ip = _ingest_queue.get()
            try:
                _ingest_through_pipeline(raw, receiver, source_ip)
            except Exception:  # noqa: BLE001
                logger.exception("入站 worker 处理异常（忽略）")
            finally:
                _ingest_queue.task_done()
        except Exception:  # noqa: BLE001
            logger.exception("入站 worker 取队列异常（忽略）")


def _submit_ingest(raw: str, receiver: dict, source_ip: Optional[str]) -> None:
    """把一条原始日志提交到有界队列；队列已满时丢弃并背压计数。

    相比为每条消息新建线程：固定 worker 数天然限流，队列上限提供背压
    （丢弃策略），避免高频 syslog / kafka 突发打爆进程。丢弃警告按
    时间窗口聚合（_drop_warning_record），避免刷屏。
    """
    if not raw:
        return
    try:
        _ingest_queue.put_nowait((raw, receiver, source_ip))
    except queue.Full:
        _drop_warning_record()


def _submit_ingest_blocking(raw: str, receiver: dict, source_ip: Optional[str], timeout: float = 5.0) -> bool:
    """把一条原始日志阻塞式提交到有界队列（kafka 背压策略）。

    队列满时阻塞等待（上限 timeout 秒）让 worker 腾出空间，而不是丢弃消息；
    超时仍未投入则丢弃并记背压计数。用于 kafka 消费端，避免丢消息。
    """
    if not raw:
        return True
    try:
        _ingest_queue.put((raw, receiver, source_ip), timeout=timeout)
        return True
    except queue.Full:
        _drop_warning_record()
        return False



# ----------------------------------------------------------------------
# ParseEngine 持久化后端（接收渠道专用的实时 sink）
# ----------------------------------------------------------------------
# 大值摘要阈值（字符）：超过该长度则不再原样入库，改为存储 长度+sha256+前 N 字预览，
# 避免超大 JSON/日志撑爆 device_receive_logs.raw_data（Text 上限）。
_SUMMARIZE_THRESHOLD = 4000
# 大值摘要时保留的预览字符数
_SUMMARIZE_PREVIEW = 512


def _summarize_large_value(raw: str) -> str:
    """超限原始日志转为摘要：长度 + sha256 + 预览，便于定位与校验原文完整性。"""
    import hashlib

    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    return "".join([
        f"[大值摘要] 原始长度={len(raw)} sha256={digest}\n",
        f"--- 前 {_SUMMARIZE_PREVIEW} 字符预览 ---\n",
        raw[:_SUMMARIZE_PREVIEW],
    ])


class ReceiverSink:
    """把接收到的日志写入 device_receive_logs + 记录接收指标。

    实际解析入库复用 ingest.SQLAlchemySink（写入 alert_events 并触发封禁）。
    每个调用传入独立的 db 会话，适合在后台线程中使用。
    """

    def __init__(self, db, receiver: dict, source_ip: Optional[str] = None) -> None:
        self.db = db
        self.receiver_id = receiver.get("id")
        self.device_id = receiver.get("device_id")
        self.device_name = receiver.get("device_name") or ""
        self.protocol = receiver.get("protocol") or "syslog"
        self.receiver_name = receiver.get("name") or ""
        self.source_ip = source_ip

    def _record_receive_log(
        self, raw_data: str, parse_status: str, parse_error: str = "",
        alert_id: Optional[int] = None,
    ) -> None:
        from app.models.log_receiver import DeviceReceiveLog

        rec = DeviceReceiveLog(
            receiver_id=self.receiver_id,
            device_id=self.device_id,
            device_name=self.device_name,
            protocol=self.protocol,
            raw_data=raw_data if len(raw_data) <= _SUMMARIZE_THRESHOLD else _summarize_large_value(raw_data),
            source_ip=self.source_ip,
            parse_status=parse_status,
            parse_error=parse_error[:2000] if parse_error else "",
            alert_id=alert_id,
        )
        self.db.add(rec)

    def _record_receive_metric(self, status: str) -> None:
        """按小时原子累加接收指标（按 receiver_id 维度）。"""
        from sqlalchemy import text as sa_text

        stat_hour = beijing_now().strftime("%Y-%m-%dT%H")
        sql = sa_text(
            """
            UPDATE device_receive_metrics
            SET {status_col} = {status_col} + 1,
                receiver_name = :rname,
                updated_at = :now
            WHERE stat_hour = :hour AND receiver_id = :rid
            """.format(status_col=f"{status}_count")
        )
        result = self.db.execute(
            sql,
            {
                "rname": self.receiver_name,
                "hour": stat_hour,
                "rid": self.receiver_id,
                "now": beijing_now(),
            },
        )
        if result.rowcount == 0:
            from app.models.log_receiver import DeviceReceiveMetric

            self.db.add(
                DeviceReceiveMetric(
                    stat_hour=stat_hour,
                    receiver_id=self.receiver_id,
                    receiver_name=self.receiver_name,
                    device_id=self.device_id,
                    protocol=self.protocol,
                    total_count=1,
                    success_count=1 if status == "success" else 0,
                    partial_count=1 if status == "partial" else 0,
                    fail_count=1 if status == "fail" else 0,
                )
            )

    def record_raw_received(self, raw_data: str) -> None:
        """仅记录接收明细 + 指标（未进入解析）。"""
        from sqlalchemy import text as sa_text

        self._record_receive_log(raw_data, "received")
        # 计入 total 与 log_receivers.received_count
        stat_hour = beijing_now().strftime("%Y-%m-%dT%H")
        sql = sa_text(
            """
            UPDATE device_receive_metrics
            SET total_count = total_count + 1,
                receiver_name = :rname,
                updated_at = :now
            WHERE stat_hour = :hour AND receiver_id = :rid
            """
        )
        result = self.db.execute(
            sql,
            {"rname": self.receiver_name, "hour": stat_hour,
             "rid": self.receiver_id, "now": beijing_now()},
        )
        if result.rowcount == 0:
            from app.models.log_receiver import DeviceReceiveMetric

            self.db.add(
                DeviceReceiveMetric(
                    stat_hour=stat_hour,
                    receiver_id=self.receiver_id,
                    receiver_name=self.receiver_name,
                    device_id=self.device_id,
                    protocol=self.protocol,
                    total_count=1,
                    success_count=0,
                    partial_count=0,
                    fail_count=0,
                )
            )
        db2 = SessionLocal()
        try:
            from sqlalchemy import text as t2

            db2.execute(
                t2(
                    """
                    UPDATE log_receivers
                    SET received_count = received_count + 1, last_received_at = :now
                    WHERE id = :rid
                    """
                ),
                {"rid": self.receiver_id, "now": beijing_now()},
            )
            db2.commit()
        finally:
            db2.close()

    def record_parsed(
        self, raw_data: str, parse_status: str, parse_error: str = "",
        alert_id: Optional[int] = None,
    ) -> None:
        """记录解析结果（success/partial/fail）+ 对应指标。"""
        self._record_receive_log(raw_data, parse_status, parse_error, alert_id)
        self._record_receive_metric(parse_status)
        if parse_status == "fail":
            _bump_counts(self.receiver_id, errors=1)


def _ingest_through_pipeline(raw: str, receiver: dict, source_ip: Optional[str]) -> None:
    """把原始日志（str）送入告警解析管道。

    兼容 JSON 与纯文本：优先按 JSON 解析成 dict 交由 ParseEngine；否则
    尝试按青藤万相 Syslog 文本键值对（``key="value"``）解析成结构化 dict；
    均失败再包装为 ``{"message": raw}`` 交由策略匹配。解析结果同时写入接收明细。
    """
    from app.models.alert_event import AlertEvent

    db = SessionLocal()
    try:
        sink = ReceiverSink(db, receiver, source_ip)
        # 1) 记录接收明细 + total 指标
        sink.record_raw_received(raw)

        # 2) 解析原始数据
        payload = _coerce_payload(raw)

        items = payload if isinstance(payload, list) else [payload]
        if not items:
            return

        # 复用 ingestion 解析：策略路由 → 入库 alert_events → 触发封禁
        from app.api.v1.ingest import SQLAlchemySink, get_strategy_loader
        from app.engine.parser_engine import ParseEngine

        loader = get_strategy_loader()
        if not loader.strategies:
            loader.refresh()
        engine = ParseEngine(loader=loader, sink=SQLAlchemySink(db))

        # 3) 逐条解析（记录到 device_receive_logs + 接收指标）
        for it in items:
            result = engine.parse_one(it) if isinstance(it, dict) else None
            if result is None or result.status == "fail":
                sink.record_parsed(
                    raw,
                    "fail",
                    result.error_msg if result else "数据不是 JSON 对象",
                )
                continue
            try:
                outcome = engine.sink.save_alert(result.fields)
                if outcome == "duplicate":
                    sink.record_parsed(raw, "partial", "重复告警，已跳过", None)
                    continue
                alert_row = (
                    db.query(AlertEvent.id)
                    .filter(AlertEvent.uuid == result.fields.get("uuid"))
                    .first()
                )
                sink.record_parsed(
                    raw, result.status, None,
                    alert_row[0] if alert_row else None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("接收日志入库失败: %s", exc)
                sink.record_parsed(raw, "fail", str(exc))

        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("日志接收解析管道异常: %s", exc)
        db.rollback()
    finally:
        db.close()


# ----------------------------------------------------------------------
# syslog 文本 key="value" → dict 预处理器
# （青藤万相 Syslog 手册报文为「空格分隔的 key="value"」文本，非 JSON）
# ----------------------------------------------------------------------
# 识别青藤 datatype 的正则：青藤所有事件类型的 datatype 命名
_QT_DATATYPE_RE = re.compile(
    r"^(bruteforce_ext|bruteforce_inter|excep_login|bounce_shell|win_bounce_shell|"
    r"privilege_escalation|backdoor_diagnose|backdoor_diagnose_win|webshell|malic_opera|"
    r"honeypot|honey_file|web_command|web_command_win|file_monitor|virus_detect|"
    r"virus_detect_win|mem_backdoor|anti_virus_detect|shell_log|access_log|net_connect|"
    r"proc_create|security_patch|weak_pwd|system_audit|dns_access|account_change|"
    r"agent_offline_check|agent_suspend_check|agent_remove_check)$"
)


def _unescape_qt_value(value: str) -> str:
    """还原 syslog 属性值转义：\\" → "、\\\\ → \\、\\b、\\n、\\t、\\f、\\r。"""
    if "\\" not in value:
        return value
    out = []
    i = 0
    n = len(value)
    while i < n:
        c = value[i]
        if c == "\\" and i + 1 < n:
            nxt = value[i + 1]
            mapping = {
                '"': '"', "\\": "\\", "b": "\b", "n": "\n", "t": "\t", "f": "\f", "r": "\r",
            }
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_qingteng_syslog(text: str) -> Optional[dict]:
    """把青藤万相 syslog 文本（``<HEADER><TAG>key1="v1" key2="v2"...``）解析为 dict。

    仅当内容体含 ``datatype=`` 且值为已知青藤事件类型，且包含 ``datatime=`` 才判定为
    青藤日志并解析（避免误匹配其他厂牌 syslog）。解析结果：
    - 顶层 ``key="value"`` 平坦化为 dict；
    - ``detail.xxx`` 前缀字段平坦化为 ``detail_xxx``（便于策略 field_mappings 直接取用）；
    - 数组值（``x\,y``）还原为 JSON 数组字符串（``["x","y"]``）；
    - 派生 ``event_uuid``（sha256(agent_id|datatype|datatime) 前 40 位）与
      ``__source="qingteng_syslog"``（供策略路由）、``datatime_raw`` 原始时间。

    Args:
        text: 完整 syslog 报文字符串。

    Returns:
        结构化 dict；若不能识别为青藤日志返回 None。
    """
    text = (text or "").strip()
    if not text:
        return None

    # 定位内容体：找到第一个 datatype= 键值对（content 之外的 HEADER/TAG 不含该键）
    marker = "datatype="
    idx = text.find(marker)
    if idx < 0:
        return None
    content = text[idx:]

    # 解析 key="value" 序列（值可能含空格，用引号闭合边界切分）
    pairs = re.findall(r'([A-Za-z0-9_\.\-]+)="((?:[^"\\]|\\.)*)"', content)
    if not pairs:
        return None
    fields: dict[str, Any] = {}
    for key, raw_val in pairs:
        val = _unescape_qt_value(raw_val)
        # 数组值（含 \, 分隔）还原为 JSON 数组字符串
        if "\\," in raw_val:
            items = [x.strip() for x in _unescape_qt_value(raw_val).split(",") if x.strip()]
            fields[key] = json.dumps(items, ensure_ascii=False)
        else:
            fields[key] = val

    datatype = fields.get("datatype", "")
    if not _QT_DATATYPE_RE.match(datatype.strip()):
        return None
    # 事件类型等字段为空时跳过（无有效数据）
    if not fields.get("datatime"):
        return None

    # detail.* → detail_xxx（平坦化，便于策略字段映射）
    detail: dict[str, Any] = fields.pop("detail", None) if isinstance(fields.get("detail"), dict) else {}
    flat: dict[str, Any] = {}
    for k, v in fields.items():
        if k.startswith("detail."):
            flat["detail_" + k[len("detail."):]] = v
        else:
            flat[k] = v
    flat.update(detail)

    # 派生去重 uuid 与来源标记
    uid = hashlib.sha256(
        f"{flat.get('agent_id', '')}|{flat.get('datatype', '')}|{flat.get('datatime', '')}"
        .encode("utf-8", errors="replace")
    ).hexdigest()[:40]
    flat["event_uuid"] = uid
    flat["datatime_raw"] = flat.get("datatime", "")
    flat["__source"] = "qingteng_syslog"
    flat["__qt_recv_at"] = beijing_now().strftime("%Y-%m-%d %H:%M:%S")
    return flat


def _coerce_payload(raw: str):
    """把原始报文规整为解析管道可消费的 payload（list 或 dict）。

    优先级：JSON（list/dict）→ 青藤 syslog 文本 → 纯文本兜底包装。
    """
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, (list, dict)):
            return parsed
    except (ValueError, TypeError):
        pass
    qt = parse_qingteng_syslog(raw)
    if qt:
        return qt
    return {"message": raw, "raw": raw}


# ----------------------------------------------------------------------
# syslog 监听（socketserver + 线程）
# ----------------------------------------------------------------------
class _SyslogUDPHandler(socketserver.BaseRequestHandler):
    """UDP syslog 处理器：报文为 (data, socket)。"""

    def handle(self) -> None:
        try:
            raw_data = self.request[0].strip().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return
        client_ip = self.client_address[0] if self.client_address else None
        _dispatch_received(raw_data, self.server, client_ip)


class _SyslogTCPHandler(socketserver.StreamRequestHandler):
    """TCP syslog 处理器：按行读取（换行分隔的简单 syslog 格式）。"""

    def handle(self) -> None:
        try:
            for line in self.rfile:
                raw_data = line.decode("utf-8", errors="replace").strip()
                if not raw_data:
                    continue
                client_ip = self.client_address[0] if self.client_address else None
                _dispatch_received(raw_data, self.server, client_ip)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception:  # noqa: BLE001
            logger.exception("TCP syslog 处理异常（忽略）")


def _dispatch_received(raw_data: str, server: Any, client_ip: Optional[str]) -> None:
    """把收到的 syslog 报文异步投递给解析管道。"""
    receiver_key = getattr(server, "receiver_key", None)
    receiver = _runtime_receiver(receiver_key)
    if receiver and raw_data:
        # 入站统一走有界队列 + 固定 worker（背压限流）
        _submit_ingest(raw_data, receiver, client_ip)


class _SyslogUDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True


class _SyslogTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def _runtime_receiver(receiver_key: Optional[int]) -> Optional[dict]:
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


def _signal_generation_started(receiver_id: int, success: bool, error: str = "") -> None:
    """本代启动完成：置位 ready_event（成功），失败时另置位 failed_event。

    保存接口通过等待 ready_event（配合超时）即可同步获知 bind/connect 结果。
    """
    rt = _runtimes.get(receiver_id)
    if not rt:
        return
    if success:
        rt["last_error"] = None
    else:
        rt["last_error"] = error
    rt["ready_event"].set()
    if not success:
        rt["failed_event"].set()


def _safe_close_server(server: Any) -> None:
    """安全关闭 socketserver（不抛异常）。"""
    if server is None:
        return
    try:
        server.server_close()
    except Exception:  # noqa: BLE001
        logger.exception("关闭 socketserver 异常（忽略）")


def _refresh_runtime_receiver(receiver_id: int) -> None:
    """从 DB 刷新接收渠道配置到内存快照。"""
    db = SessionLocal()
    try:
        from app.models.log_receiver import LogReceiver

        rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
        if rec:
            rt = _runtime_bucket(receiver_id)
            rt["receiver"] = {
                "id": rec.id,
                "device_id": rec.device_id,
                "device_name": rec.device_name,
                "name": rec.name,
                "protocol": rec.protocol,
                "syslog_port": rec.syslog_port,
                "syslog_proto": rec.syslog_proto,
                "syslog_bind": rec.syslog_bind,
                "kafka_bootstrap": rec.kafka_bootstrap,
                "kafka_topic": rec.kafka_topic,
                "kafka_group": rec.kafka_group,
                "kafka_security": rec.kafka_security,
                "format": rec.format,
            }
    finally:
        db.close()


def _run_syslog_listener(receiver_id: int) -> None:
    """启动 syslog UDP/TCP 监听（阻塞运行，异常时更新状态）。

    绑定状态机：binding → listening（成功）/ failed（异常）。
    启动成功/失败通过 ready_event / failed_event 置位，供保存接口同步核实。
    """
    receiver = _runtime_receiver(receiver_id)
    if not receiver:
        return
    port = receiver.get("syslog_port")
    proto = (receiver.get("syslog_proto") or "udp").lower()
    bind = receiver.get("syslog_bind") or "0.0.0.0"
    if not port:
        _mark_start_failed(receiver_id, "未配置 syslog 监听端口")
        _signal_generation_started(receiver_id, success=False, error="未配置 syslog 监听端口")
        return

    rt = _runtime_bucket(receiver_id)
    generation = rt.get("generation", 0)
    stop_event = rt.get("stop_event")
    _set_status(receiver_id, "binding", None)
    server = None
    try:
        if proto == "tcp":
            server = _SyslogTCPServer((bind, port), _SyslogTCPHandler)
        else:
            server = _SyslogUDPServer((bind, port), _SyslogUDPHandler)
        server.receiver_key = receiver_id
        rt["server"] = server
        _signal_generation_started(receiver_id, success=True)
        _set_status(receiver_id, "listening", None)
        logger.info("syslog %s 监听已启动: %s:%s (receiver=%s gen=%s)", proto, bind, port, receiver_id, generation)
        # serve_forever 阻塞直至 server.shutdown()（由 stop_receiver_thread 调用）；
        # 停止/重启时旧代经 join 排空后自然结束。
        server.serve_forever()
    except Exception as exc:  # noqa: BLE001
        logger.exception("syslog 监听启动失败: %s", exc)
        if not (stop_event and stop_event.is_set()):
            _set_status(receiver_id, "failed", f"{type(exc).__name__}: {exc}")
            _signal_generation_started(receiver_id, success=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        _safe_close_server(server)
        # 仅在本代仍占用 server 槽位时才清空，避免误删新一代的 server
        if rt.get("server") is server:
            rt.pop("server", None)


def _run_kafka_consumer(receiver_id: int) -> None:
    """启动 kafka 消费者（阻塞运行，异常时更新状态）。

    连接状态机：connecting → running（成功）/ failed（异常）。
    断开/超时会触发重连（代内自循环）。
    """
    receiver = _runtime_receiver(receiver_id)
    if not receiver:
        return
    bootstrap = receiver.get("kafka_bootstrap") or ""
    topic = (receiver.get("kafka_topic") or "").strip().rstrip(",")
    group = receiver.get("kafka_group") or "soar-ingest"
    if not bootstrap or not topic:
        _mark_start_failed(receiver_id, "未配置 kafka bootstrap servers / topic")
        _signal_generation_started(receiver_id, success=False, error="未配置 kafka bootstrap servers / topic")
        return

    # 运行时检测 aiokafka；未安装则标记失败
    try:
        import asyncio

        from aiokafka import AIOKafkaConsumer
    except Exception as exc:  # noqa: BLE001
        _mark_start_failed(
            receiver_id,
            f"未安装 aiokafka 依赖，无法消费 kafka: {exc}. 请 pip install aiokafka",
        )
        _signal_generation_started(receiver_id, success=False, error=f"未安装 aiokafka: {exc}")
        return

    rt = _runtime_bucket(receiver_id)
    generation = rt.get("generation", 0)
    stop_event = rt.get("stop_event")
    topics = [t.strip() for t in topic.split(",") if t.strip()]

    def _consume() -> None:
        asyncio.run(_kafka_loop(receiver, bootstrap, topics, group, stop_event))

    _set_status(receiver_id, "connecting", None)
    logger.info("kafka 消费者已启动: %s topic=%s group=%s (receiver=%s gen=%s)",
                bootstrap, topic, group, receiver_id, generation)
    _consume()


async def _kafka_loop(receiver: dict, bootstrap: str, topics: list[str], group: str, stop_event) -> None:
    import asyncio

    from aiokafka import AIOKafkaConsumer

    receiver_id = receiver.get("id")
    rt = _runtimes.get(receiver_id, {})
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap,
        group_id=group,
        enable_auto_commit=True,
        auto_offset_reset="latest",
    )
    try:
        await consumer.start()
        rt["ready_event"].set()  # 连接成功，通知同步核实已就绪
        # 重置积压统计，避免上次会话的旧值残留
        stat0 = _recent_stats.setdefault(receiver_id, {})
        stat0["kafka_partitions"] = set()
        stat0["backlog"] = 0
        stat0.pop("backlog_error", None)
        stat0["backlog_sampled_at"] = None
        _set_status(receiver_id, "running", None)

        # 后台积压采样任务：定期计算 consumer lag
        sampling_task = asyncio.create_task(_kafka_backlog_sampler(consumer, receiver_id, stop_event))

        try:
            async for msg in consumer:
                if stop_event and stop_event.is_set():
                    break
                try:
                    raw = msg.value.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    raw = repr(msg.value)
                # kafka 背压策略：队列满时阻塞等待（上限超时）而不是丢弃消息，
                # 阻塞让 consumer 自然回压暂停拉取，避免丢包。
                _submit_ingest_blocking(raw, receiver, None, timeout=5.0)
        finally:
            sampling_task.cancel()
            try:
                await sampling_task
            except asyncio.CancelledError:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("kafka 消费异常: %s", exc)
        if not (stop_event and stop_event.is_set()):
            _set_status(receiver_id, "failed", f"{type(exc).__name__}: {exc}")
            rt["ready_event"].set()
            rt["failed_event"].set()
    finally:
        await consumer.stop()


async def _kafka_backlog_sampler(consumer, receiver_id: int, stop_event) -> None:
    """周期性采样 kafka consumer lag 并写入内存，供健康检查做积压判定。"""
    import asyncio

    try:
        while not (stop_event and stop_event.is_set()):
            await _sample_kafka_lag(consumer, receiver_id)
            await asyncio.sleep(BACKLOG_SAMPLE_INTERVAL)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("kafka 积压采样异常（忽略）: %s", exc)
        _recent_stats.setdefault(receiver_id, {})["backlog"] = 0
        _recent_stats.setdefault(receiver_id, {})["backlog_error"] = str(exc)


async def _sample_kafka_lag(consumer, receiver_id: int) -> None:
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
        stat = _recent_stats.setdefault(receiver_id, {})
        stat["backlog"] = total_lag
        stat["backlog_sampled_at"] = beijing_now()
        stat.pop("backlog_error", None)
    except Exception as exc:  # noqa: BLE001
        stat = _recent_stats.setdefault(receiver_id, {})
        stat["backlog"] = 0
        stat["backlog_error"] = str(exc)


# ----------------------------------------------------------------------
# 接收渠道启停管理
# ----------------------------------------------------------------------
def _set_status(receiver_id: int, status: str, error: Optional[str]) -> None:
    db = SessionLocal()
    try:
        from app.models.log_receiver import LogReceiver

        rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
        if rec:
            rec.status = status
            rec.last_error = error
            if status == "running" and error is None:
                rec.last_error = None
            db.commit()
    finally:
        db.close()


def _mark_start_failed(receiver_id: int, error: str) -> None:
    _set_status(receiver_id, "start_failed", error)
    logger.error("接收渠道 %s 启动失败: %s", receiver_id, error)


def _bump_counts(receiver_id: int, received: int = 0, errors: int = 0) -> None:
    db = SessionLocal()
    try:
        from sqlalchemy import text as sa_text

        sql = sa_text(
            """
            UPDATE log_receivers
            SET received_count = received_count + :rc,
                error_count = error_count + :ec,
                last_received_at = :now
            WHERE id = :rid
            """
        )
        db.execute(sql, {"rc": received, "ec": errors, "rid": receiver_id, "now": beijing_now()})
        db.commit()
    finally:
        db.close()


def ensure_receiver_thread(receiver_id: int) -> None:
    """确保某接收渠道的监听线程运行中（是否启动以 DB 的 enabled 为准）。"""
    db = SessionLocal()
    try:
        from app.models.log_receiver import LogReceiver

        rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
    finally:
        db.close()
    if not rec:
        return

    # 更新内存快照
    _refresh_runtime_receiver(receiver_id)
    rt = _runtime_bucket(receiver_id)

    if not rec.enabled:
        # DB 停用 → 停掉线程
        rt["enabled"] = False
        stop_receiver_thread(receiver_id)
        return

    thread = rt.get("thread")
    if thread and thread.is_alive():
        return  # 已在运行

    # 创建并启动监听线程；每次启动新开一代（新 stop_event），
    # 旧代循环识别自己的 stop_event 未置位也会自然退出（逐代取消）。
    rt["enabled"] = True
    start_receiver_sync(receiver_id)
    return


def start_receiver_sync(receiver_id: int, timeout: Optional[float] = None) -> Optional[str]:
    """（重新）启动某接收渠道监听线程并同步核实 bind/connect 结果。

    返回 None=未到超时已知成功；返回 "start_failed"/"failed"=启动失败；返回
    "timeout"=超时未确定。供创建/更新/重载接口在保存流程内实时向用户反馈
    端口占用 / 连接失败，而不是事后异步才变 failed。

    每调用一次即开启新一代：旧代 stop_event 不被重置，若旧代仍在运行会
    自然退出（避免重启竞态与孤儿线程）。
    """
    rt = _runtime_bucket(receiver_id)
    # 每次启动前先从 DB 刷新该渠道配置到内存缓存，否则新建/未刷新过的渠道
    # 会读到空的 protocol，误判为“不支持的接收协议”并进入 unconfigured。
    _refresh_runtime_receiver(receiver_id)
    protocol = (rt.get("receiver") or {}).get("protocol") or ""

    # 上一代线程若还在跑，先停掉（逐代取消）
    old_thread = rt.get("thread")
    if old_thread and old_thread.is_alive():
        old_stop = rt.get("stop_event")
        if old_stop:
            old_stop.set()
        old_server = rt.get("server")
        if old_server:
            try:
                old_server.shutdown()
            except Exception:  # noqa: BLE001
                pass
            _safe_close_server(old_server)
        t_join = rt.get("thread")
        if t_join and t_join is not threading.current_thread():
            t_join.join(timeout=STOP_JOIN_TIMEOUT_S)

    # 开启新一代
    rt["generation"] = (rt.get("generation") or 0) + 1
    new_stop = threading.Event()
    new_ready = threading.Event()
    new_failed = threading.Event()
    rt["stop_event"] = new_stop
    rt["ready_event"] = new_ready
    rt["failed_event"] = new_failed

    if protocol == "syslog":
        target = _run_syslog_listener
    elif protocol == "kafka":
        target = _run_kafka_consumer
    else:
        _set_status(receiver_id, "unconfigured", f"不支持的接收协议: {protocol}")
        return "unconfigured"

    t = threading.Thread(
        target=target, args=(receiver_id,), daemon=True,
        name=f"log-receiver-{receiver_id}-{protocol}",
    )
    rt["thread"] = t
    rt["enabled"] = True
    t.start()

    # 同步等待本代启动结果（bind/connect）
    wait = timeout if timeout is not None else (
        BIND_WAIT_TIMEOUT_S if protocol == "syslog" else CONNECT_WAIT_TIMEOUT_S
    )
    if new_ready.wait(timeout=wait):
        return None if not new_failed.is_set() else "failed"
    return "timeout"


def stop_receiver_thread(receiver_id: int) -> None:
    """停止某接收渠道的监听线程，并排空该代已投递的入站任务。"""
    rt = _runtimes.get(receiver_id)
    if not rt:
        return
    stop_event = rt.get("stop_event")
    if stop_event:
        stop_event.set()
    server = rt.get("server")
    if server:
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        _safe_close_server(server)
    thread = rt.get("thread")
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=STOP_JOIN_TIMEOUT_S)  # 优雅停止等待（draining）
    _set_status(receiver_id, "stopped", None)
    rt["enabled"] = False
    logger.info("接收渠道线程已停止: receiver=%s", receiver_id)


def reload_all_receivers() -> None:
    """根据 DB 当前配置同步所有接收渠道线程（启动/停止/重启）。"""
    db = SessionLocal()
    try:
        from app.models.log_receiver import LogReceiver

        receivers = db.query(LogReceiver).filter(LogReceiver.enabled == 1).all()
    finally:
        db.close()

    active_ids = set()
    for rec in receivers:
        active_ids.add(rec.id)
        _refresh_runtime_receiver(rec.id)
        ensure_receiver_thread(rec.id)

    # 停掉不在启用列表中的线程
    for rid in list(_runtimes.keys()):
        if rid not in active_ids and _runtimes.get(rid, {}).get("enabled"):
            stop_receiver_thread(rid)


# ----------------------------------------------------------------------
# 接收健康检查与异常通知
# ----------------------------------------------------------------------
def _build_recent_stats() -> dict[int, dict[str, Any]]:
    """按接收渠道聚合最近 1 小时接收/解析指标（用于失败率判定）。"""
    db = SessionLocal()
    out: dict[int, dict[str, Any]] = {}
    try:
        from app.models.log_receiver import (
            DeviceReceiveLog,
            DeviceReceiveMetric,
            LogReceiver,
        )
        from sqlalchemy import func

        receivers = db.query(LogReceiver).filter(LogReceiver.enabled == 1).all()
        for rec in receivers:
            base = {
                "id": rec.id,
                "name": rec.name,
                "protocol": rec.protocol,
                "status": rec.status,
                "last_received_at": rec.last_received_at,
                "last_error": rec.last_error,
                "notify_interval_minutes": rec.notify_interval_minutes or 0,
                "total": 0,
                "fail": 0,
                "backlog": 0,
                "backlog_error": None,
                "backlog_sampled_at": None,
            }
            # 从内存中读取后台采样到的 kafka 积压（consumer lag）
            mem = _recent_stats.get(rec.id, {})
            base["backlog"] = mem.get("backlog", 0)
            base["backlog_error"] = mem.get("backlog_error")
            base["backlog_sampled_at"] = mem.get("backlog_sampled_at")
            out[rec.id] = base

        cutoff = (datetime.now(BEIJING_TZ) - timedelta(hours=1)).strftime("%Y-%m-%dT%H")
        rows = (
            db.query(DeviceReceiveMetric)
            .filter(DeviceReceiveMetric.stat_hour >= cutoff)
            .all()
        )
        for m in rows:
            base = out.setdefault(
                m.receiver_id,
                {"id": m.receiver_id, "name": m.receiver_name, "protocol": m.protocol,
                 "status": "unknown", "last_received_at": None, "last_error": None,
                 "total": 0, "fail": 0,
                 "backlog": 0, "backlog_error": None, "backlog_sampled_at": None},
            )
            mem = _recent_stats.get(m.receiver_id, {})
            base["backlog"] = mem.get("backlog", 0)
            base["backlog_error"] = mem.get("backlog_error")
            base["backlog_sampled_at"] = mem.get("backlog_sampled_at")
            base["total"] += m.total_count or 0
            base["fail"] += m.fail_count or 0

        return out
    finally:
        db.close()


def _dispatch_alert(kind: str, title: str, content: str, receiver_id: Optional[int] = None) -> None:
    """派发接收异常通知。"""
    try:
        from app.core.notification_dispatch import dispatch_notification

        db = SessionLocal()
        try:
            dispatch_notification(
                db,
                event_type="receiver_alert",
                title=title,
                content=content,
                related_type="log_receiver",
                related_id=receiver_id,
                created_by="system",
            )
            db.commit()
        finally:
            db.close()
        logger.warning("接收异常通知已派发: %s", title)
    except Exception as exc:  # noqa: BLE001
        logger.exception("接收异常通知派发失败: %s", exc)


def _should_notify(key: str, now: datetime, interval_min: int) -> bool:
    """判断当前告警 key 是否应当发送通知。

    间隔语义：
    - interval_min <= 0：仅在"当前未处于已提醒状态"时提醒（即每段异常首次，
      恢复后重新进入异常再提醒一次），异常持续期间不重复。
    - interval_min > 0：按"距上次通知时间"节流，异常持续期间每 N 分钟重复；
      即使异常短暂恢复后再次触发，只要距上次通知不足 N 分钟也不再提醒，
      从而保证任意异常在 N 分钟内最多提醒一次。
    """
    if interval_min <= 0:
        return not _alerted.get(key)
    last = _last_notify_at.get(key)
    if last is None:
        return not _alerted.get(key)  # 从未通知过 → 真正首次，允许提醒
    return (now - last).total_seconds() >= interval_min * 60


def _mark_notified(key: str, now: datetime) -> None:
    """记录某告警 key 已通知（置位去重标志并记录通知时间）。"""
    _alerted[key] = True
    _last_notify_at[key] = now


def _alert_ok(key: str) -> None:
    """告警恢复：清除去重标志，但保留上次通知时间。

    保留 _last_notify_at 是关键：对于配置了重复间隔（interval_min > 0）的渠道，
    即使异常短暂恢复后再次触发，也仍按上次通知时间节流，避免因状态抖动
    绕过间隔而频繁提醒。interval_min <= 0 时 _should_notify 只看 _alerted 标志，
    不受此时间影响，恢复后仍会重新提醒一次。
    """
    _alerted[key] = False


def _check_and_alert_receivers() -> None:
    """检查所有启用接收渠道：断流 / 解析失败率 / 服务停止 / kafka 积压。

    支持按渠道的 notify_interval_minutes 配置重复通知间隔：0=异常期间仅首次
    通知一次（默认）；>0=异常持续期间每 N 分钟重复提醒一次，恢复后重置。
    """
    stats = _build_recent_stats()
    now = datetime.now(BEIJING_TZ)

    for rid, st in stats.items():
        key_prefix = f"receiver:{rid}"
        interval_min = int(st.get("notify_interval_minutes") or 0)

        # 1) 服务状态：健康状态之外（监听线程未真正就绪/停止/失败）按间隔重复通知
        #    健康 = syslog 已 listening / kafka 已 running；
        #    binding/connecting 为过渡态，不告警（还在尝试绑定/连接）。
        healthy = st.get("status") in ("listening", "running")
        if not healthy:
            key = f"{key_prefix}:status"
            if _should_notify(key, now, interval_min):
                _mark_notified(key, now)
                _dispatch_alert(
                    "receiver_down",
                    "日志接收渠道异常",
                    f"接收渠道「{st.get('name')}」状态异常：{st.get('status')}"
                    f"（错误：{st.get('last_error') or '无'}）\n"
                    f"时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
                    rid,
                )
            continue

        # 2) 断流/无数据：超过阈值无新日志
        last_at = st.get("last_received_at")
        stale = False
        if last_at is None:
            stale = True
        else:
            try:
                if isinstance(last_at, datetime):
                    delta = (now - last_at).total_seconds()
                else:
                    delta = (now - datetime.fromisoformat(str(last_at))).total_seconds()
                stale = delta > NO_DATA_STALE_SECONDS
            except Exception:  # noqa: BLE001
                delta = 0
        key = f"{key_prefix}:nodata"
        if stale:
            if _should_notify(key, now, interval_min):
                _mark_notified(key, now)
                _dispatch_alert(
                    "no_data",
                    "日志接收断流提醒",
                    f"接收渠道「{st.get('name')}」已超过 {NO_DATA_STALE_SECONDS // 60} 分钟未收到日志，"
                    f"请检查上游设备是否正常推送。\n时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
                    rid,
                )
        elif _alerted.get(key):
            _alert_ok(key)  # 恢复

        # 3) 解析失败率升高
        total = st.get("total") or 0
        fail = st.get("fail") or 0
        if total > 0:
            rate = fail * 100.0 / total
            key = f"{key_prefix}:failrate"
            if rate >= FAIL_RATE_THRESHOLD:
                if _should_notify(key, now, interval_min):
                    _mark_notified(key, now)
                    _dispatch_alert(
                        "fail_rate",
                        "日志解析失败率过高",
                        f"接收渠道「{st.get('name')}」近 1 小时解析失败率 {rate:.1f}%"
                        f"（失败 {fail}/{total} 条），阈值 {FAIL_RATE_THRESHOLD}%。\n"
                        f"时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
                        rid,
                    )
            elif rate < FAIL_RATE_THRESHOLD - 10 and _alerted.get(key):
                _alert_ok(key)  # 恢复

        # 4) kafka 处理积压（consumer lag）过高
        #    仅对 kafka 渠道且成功采样到 lag 时判定，其他协议不参与；
        #    采样失败视为数据不足，不告警也不视为恢复。
        if st.get("protocol") == "kafka":
            backlog = st.get("backlog") or 0
            sample_err = st.get("backlog_error")
            key = f"{key_prefix}:backlog"
            if backlog >= BACKLOG_THRESHOLD and not sample_err:
                if _should_notify(key, now, interval_min):
                    _mark_notified(key, now)
                    _dispatch_alert(
                        "backlog",
                        "日志处理积压过高",
                        f"接收渠道「{st.get('name')}」kafka 消费积压（consumer lag）"
                        f"达 {backlog} 条，阈值 {BACKLOG_THRESHOLD} 条。\n"
                        f"请检查下游处理能力或调整消费并发。\n"
                        f"时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
                        rid,
                    )
            elif (not sample_err and backlog < BACKLOG_THRESHOLD - BACKLOG_RECOVER_MARGIN
                  and _alerted.get(key)):
                _alert_ok(key)  # 积压回落，恢复


def _run_health_check() -> None:
    """健康检查主循环（阻塞）。"""
    logger.info("日志接收健康检查线程已启动，间隔 %ds", HEALTH_CHECK_INTERVAL)
    while True:
        try:
            _check_and_alert_receivers()
            # 周期补报上一窗口的背压丢弃尾数（若未及阈值 flush）
            _drop_warning_flush(trigger="health")
        except Exception as exc:  # noqa: BLE001
            logger.warning("日志接收健康检查异常: %s", exc)
        _time.sleep(HEALTH_CHECK_INTERVAL)


# ----------------------------------------------------------------------
# 启动入口
# ----------------------------------------------------------------------
# 进程级文件锁句柄（保持打开以持有锁）
_listener_lock_fh = None


def _try_acquire_listener_lock() -> bool:
    """尝试获取"单 worker 日志监听"文件锁。

    多 worker 部署（uvicorn --workers N > 1）时，若每个 worker 都启动 syslog/kafka
    监听会把同一端口绑定冲突。通过跨平台独占文件锁协调：只有第一个成功持锁的
    worker 会启动监听线程，其余 worker 跳过。锁文件句柄保持打开常驻进程。
    """
    global _listener_lock_fh
    if _listener_lock_fh is not None:
        return True  # 本进程已持锁
    fh = None
    try:
        fh = open(_LISTENER_LOCK_PATH, "a+")
        if _fcntl is not None:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        elif _msvcrt is not None:
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write("\0")
                fh.flush()
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_NBLCK, 1)
        # 无锁原语可用：当作已持锁（单 worker 场景）
        _listener_lock_fh = fh
        return True
    except (OSError, IOError):
        if fh is not None:
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass
        return False


def start_log_receiver_manager() -> None:
    """启动日志接收管理器：加载启用渠道 + 启动健康检查线程。

    多 worker 部署下仅启动唯一实例（持有文件锁的 worker 负责监听与健康检查），
    避免 syslog/kafka 端口在多 worker 间冲突。
    """
    global _manager_started
    with _manager_lock:
        if _manager_started:
            return
        _manager_started = True

        # 多 worker 协调：仅第一个成功持锁的 worker 启动监听
        if not _try_acquire_listener_lock():
            logger.info("其他 worker 已持有日志接收监听锁，本 worker 跳过日志监听")
            return

        # 同步所有启用渠道
        try:
            reload_all_receivers()
        except Exception as exc:  # noqa: BLE001
            logger.warning("接收渠道加载失败（忽略）: %s", exc)

        # 启动入站消费 worker 线程池（有界队列背压）
        for i in range(_INGEST_WORKERS):
            wt = threading.Thread(target=_ingest_worker, daemon=True, name=f"log-ingest-{i}")
            wt.start()

        t = threading.Thread(target=_run_health_check, daemon=True, name="log-receiver-health")
        t.start()
        logger.info("日志接收管理器已启动")


def get_receiver_runtime_status(receiver_id: int) -> dict:
    """返回某接收渠道的运行时状态（供 API 查询）。"""
    rt = _runtimes.get(receiver_id, {})
    thread = rt.get("thread")
    return {
        "id": receiver_id,
        "alive": thread is not None and thread.is_alive(),
    }
