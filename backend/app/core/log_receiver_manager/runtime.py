"""运行时管理：状态机 / 启停 / reload / 健康检查 / 文件锁 / 启动入口。

自原 log_receiver_manager.py 平移，行为等价；差异点仅一处：
适配器线程 target 由 if/elif 硬编码改为 ``adapter_registry`` 注册表查找
（新增源类型零代码改动）。
"""
import json
import logging
import threading
import time as _time
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.timezone import BEIJING_TZ, beijing_now
from app.database import SessionLocal

from . import adapters  # noqa: F401  # import 触发各适配器自注册
from .adapter_context import AdapterContext
from .adapters.syslog_adapter import _safe_close_server
from .bus import get_bus
from .entry_registry import entry_registry
from .pipeline.runner import run_pipeline_for_event
from .registry import adapter_registry
from .state import (
    BACKLOG_RECOVER_MARGIN,
    BACKLOG_THRESHOLD,
    CONNECT_WAIT_TIMEOUT_S,
    FAIL_RATE_THRESHOLD,
    HEALTH_CHECK_INTERVAL,
    NO_DATA_STALE_SECONDS,
    STOP_JOIN_TIMEOUT_S,
    _alerted,
    _last_notify_at,
    _listener_lock_fh,
    _manager_lock,
    _manager_started,
    _msvcrt,
    _fcntl,
    _LISTENER_LOCK_PATH,
    _recent_stats,
    _runtimes,
    _runtime_bucket,
    _runtime_receiver,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# 接收渠道状态（DB）
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


# ----------------------------------------------------------------------
# 内存快照刷新（含 adapter_config 防御性解析）
# ----------------------------------------------------------------------
def _refresh_runtime_receiver(receiver_id: int) -> None:
    """从 DB 刷新接收渠道配置到内存快照。"""
    db = SessionLocal()
    try:
        from app.models.log_receiver import LogReceiver

        rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
        if rec:
            rt = _runtime_bucket(receiver_id)
            # adapter_config 列阶段2迁移；列未创建时 getattr 返回 None → 空 dict
            adapter_cfg_raw = getattr(rec, "adapter_config", None)
            try:
                adapter_cfg = json.loads(adapter_cfg_raw) if adapter_cfg_raw else {}
            except (ValueError, TypeError):
                adapter_cfg = {}
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
                "strategy_id": rec.strategy_id,
                "adapter_config": adapter_cfg if isinstance(adapter_cfg, dict) else {},
            }
    finally:
        db.close()


# ----------------------------------------------------------------------
# 适配器线程入口（注册表驱动，替代原 if/elif target 选择）
# ----------------------------------------------------------------------
def _run_adapter_thread(receiver_id: int) -> None:
    """适配器线程入口：构造 ctx → 注册表查找 → 实例化运行。

    线程模型与原 syslog/kafka 监听线程一致（每 receiver 一条线程，
    generation/stop_event 逐代取消）。
    """
    rt = _runtimes.get(receiver_id) or {}
    receiver = rt.get("receiver")
    if not receiver:
        return
    protocol = receiver.get("protocol") or ""
    adapter_cls = adapter_registry.get(protocol)
    ctx = AdapterContext(
        receiver_id=receiver_id,
        generation=rt.get("generation", 0),
        stop_event=rt.get("stop_event"),
        receiver=receiver,
        runtime_ref=rt,
        on_ready=_signal_generation_started,
        on_status=_set_status,
    )
    if adapter_cls is None:
        # 理论不可达（start_receiver_sync 已前置校验），双保险
        ctx.mark_start_failed(f"不支持的接收协议: {protocol}")
        ctx.signal_ready(False, f"不支持的接收协议: {protocol}")
        return
    adapter = adapter_cls(ctx)
    rt["adapter"] = adapter
    try:
        adapter.run()
    except Exception as exc:  # noqa: BLE001
        logger.exception("适配器运行异常: %s", exc)
        if not ctx.stop_event.is_set():
            ctx.set_status("failed", f"{type(exc).__name__}: {exc}")
            ctx.signal_ready(False, f"{type(exc).__name__}: {exc}")
    finally:
        if rt.get("adapter") is adapter:
            rt.pop("adapter", None)


# ----------------------------------------------------------------------
# 接收渠道启停管理
# ----------------------------------------------------------------------
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

    # 注册表查找适配器（替代原 if/elif 协议分支）
    adapter_cls = adapter_registry.get(protocol)
    if adapter_cls is None:
        _set_status(receiver_id, "unconfigured", f"不支持的接收协议: {protocol}")
        return "unconfigured"

    # 上一代线程若还在跑，先停掉（逐代取消）
    old_thread = rt.get("thread")
    if old_thread and old_thread.is_alive():
        old_stop = rt.get("stop_event")
        if old_stop:
            old_stop.set()
        old_adapter = rt.get("adapter")
        if old_adapter is not None:
            try:
                old_adapter.stop()
            except Exception:  # noqa: BLE001
                pass
        else:
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

    t = threading.Thread(
        target=_run_adapter_thread, args=(receiver_id,), daemon=True,
        name=f"log-receiver-{receiver_id}-{protocol}",
    )
    rt["thread"] = t
    rt["enabled"] = True
    t.start()

    # 同步等待本代启动结果（bind/connect）；超时取适配器声明值
    # （syslog 绑定 3s / kafka 等 connect 8s，语义与原常量一致）
    wait = timeout if timeout is not None else adapter_cls.default_ready_timeout_s
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
    adapter = rt.get("adapter")
    if adapter is not None:
        try:
            adapter.stop()
        except Exception:  # noqa: BLE001
            pass
    else:
        # 兼容：适配器未挂载时按旧约定处理 server 槽位
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
            get_bus().flush_drop_warning(trigger="health")
            # 来源条目接收统计批量刷库（内存缓冲，60s 一轮）
            entry_registry.flush_stats()
        except Exception as exc:  # noqa: BLE001
            logger.warning("日志接收健康检查异常: %s", exc)
        _time.sleep(HEALTH_CHECK_INTERVAL)


# ----------------------------------------------------------------------
# 启动入口
# ----------------------------------------------------------------------
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
            import os as _os

            fh.seek(0, _os.SEEK_END)
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
    """启动日志接收管理器：加载启用渠道 + 启动总线 worker 与健康检查线程。

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

        # 启动总线消费 worker 线程池（有界队列背压；等价原 8 入站 worker）
        bus = get_bus()
        bus.set_handler(run_pipeline_for_event)
        bus.start()

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
