"""来源条目注册中心：监听型渠道按来源 IP 自动发现条目 + 条目级配置合并。

设计约束（与接收管理器背压/游标机制解耦）：
- 高频事件路径**零查库**：条目配置快照走进程内缓存（60s TTL，跨 worker 最终一致）；
- 首见来源走一次独立短会话 INSERT（模仿 sink._bump_counts 模式，不占事件主会话）；
- 创建失败仅记日志并返回 None，事件回退渠道默认配置继续处理（**日志零丢失**）；
- 接收统计内存缓冲，由健康检查循环（60s）批量刷库，不新增线程。
"""
import json
import logging
import threading
import time
from typing import Optional

from sqlalchemy import text as sa_text

from app.core.timezone import beijing_now
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# 启用条目模型的监听型协议（拉取型渠道保持渠道级策略）
LISTEN_PROTOCOLS = {"syslog", "snmp_trap", "netflow", "pcap"}

# 条目配置缓存 TTL（秒）：API 更新条目后同进程 invalidate 立即生效，跨 worker 靠 TTL
_ENTRY_CACHE_TTL_S = 60.0

# 单渠道条目数默认上限（adapter_config.entry_max_count 可覆盖；防 pcap 等场景爆炸）
DEFAULT_ENTRY_MAX_COUNT = 1000


def _entry_snapshot(rec) -> dict:
    """ORM 行 → 事件路径可用的条目配置快照 dict。"""
    cfg = rec.entry_config
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg or "{}")
        except (ValueError, TypeError):
            cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "id": rec.id,
        "source_ip": rec.source_ip,
        "name": rec.name,
        "device_id": rec.device_id,
        "enabled": bool(rec.enabled),
        "strategy_id": rec.strategy_id,
        "entry_config": cfg,
    }


def _receiver_adapter_cfg(receiver: dict) -> dict:
    """防御性解析 receiver dict 的 adapter_config（runtime 已解析 dict，双保险）。"""
    cfg = (receiver or {}).get("adapter_config")
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg or "{}")
        except (ValueError, TypeError):
            cfg = {}
    return cfg if isinstance(cfg, dict) else {}


def _discovery_flags(receiver: dict) -> tuple:
    """渠道的条目发现开关与上限（adapter_config 约定键，默认按协议类型）。"""
    cfg = _receiver_adapter_cfg(receiver)
    discovery = cfg.get("entry_discovery")
    if discovery is None:
        discovery = (receiver or {}).get("protocol") in LISTEN_PROTOCOLS
    raw_max = cfg.get("entry_max_count")
    try:
        max_count = int(raw_max) if raw_max not in (None, "") else DEFAULT_ENTRY_MAX_COUNT
    except (ValueError, TypeError):
        max_count = DEFAULT_ENTRY_MAX_COUNT
    return bool(discovery), max_count


class EntryRegistry:
    """条目缓存 / 首见建库 / 统计缓冲（进程级单例，仅事件 worker 线程使用）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (receiver_id, source_ip) → {"ts": monotonic, "entry": 快照}
        self._cache: dict = {}
        # 首见查询去重：避免并发事件重复建条目
        self._pending: set = set()
        # (receiver_id, source_ip) → [count, last_received_at]
        self._stats: dict = {}

    # ------------------------------------------------------------------
    # 条目解析（事件路径，必须快）
    # ------------------------------------------------------------------
    def resolve(self, receiver_id, source_ip, receiver: Optional[dict] = None) -> Optional[dict]:
        """取某渠道下来源 IP 的条目配置快照；无条目时按发现开关自动创建。

        Returns:
            条目快照 dict；条目不存在且不自动创建（或创建失败）时返回 None，
            调用方回退渠道默认配置继续处理。
        """
        key = (receiver_id, source_ip)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit["ts"] <= _ENTRY_CACHE_TTL_S:
                return hit["entry"]

        entry = self._load_or_create(receiver_id, source_ip, receiver)
        if entry is not None:
            with self._lock:
                self._cache[key] = {"ts": time.monotonic(), "entry": entry}
        return entry

    def _load_or_create(self, receiver_id, source_ip, receiver) -> Optional[dict]:
        key = (receiver_id, source_ip)
        with self._lock:
            if key in self._pending:
                return None  # 并发首见：另一线程正在创建，本次走渠道默认
            self._pending.add(key)
        try:
            db = SessionLocal()
            try:
                from app.models.log_source_entry import LogSourceEntry

                rec = (
                    db.query(LogSourceEntry)
                    .filter(LogSourceEntry.receiver_id == receiver_id,
                            LogSourceEntry.source_ip == source_ip)
                    .first()
                )
                if rec is not None:
                    return _entry_snapshot(rec)

                discovery, max_count = _discovery_flags(receiver)
                if not discovery:
                    return None
                if max_count > 0:
                    current = db.query(LogSourceEntry).filter(
                        LogSourceEntry.receiver_id == receiver_id
                    ).count()
                    if current >= max_count:
                        logger.warning(
                            "渠道 %s 条目数已达上限 %s，来源 %s 不再自动创建（可调大 entry_max_count）",
                            receiver_id, max_count, source_ip,
                        )
                        return None

                rec = LogSourceEntry(
                    receiver_id=receiver_id,
                    source_ip=source_ip,
                    name=source_ip,
                    device_id=self._match_device(db, source_ip),
                )
                db.add(rec)
                db.commit()
                logger.info("自动发现来源条目：渠道 %s 来源 %s → 条目 %s", receiver_id, source_ip, rec.id)
                return _entry_snapshot(rec)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("来源条目加载失败（事件回退渠道默认）: %s", exc)
            return None
        finally:
            with self._lock:
                self._pending.discard(key)

    @staticmethod
    def _match_device(db, source_ip) -> Optional[int]:
        """首见时按 devices.ip_address 自动绑定设备（查不到则纯 IP 条目）。"""
        try:
            row = db.execute(
                sa_text("SELECT id FROM devices WHERE ip_address = :ip LIMIT 1"),
                {"ip": source_ip},
            ).first()
            return row[0] if row else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("来源条目匹配设备失败（忽略）: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 统计缓冲（事件路径内存计数，健康检查循环批量刷库）
    # ------------------------------------------------------------------
    def bump(self, receiver_id, source_ip) -> None:
        """内存累加接收计数（无 IO）。"""
        with self._lock:
            st = self._stats.get((receiver_id, source_ip))
            if st is None:
                st = [0, None]
                self._stats[(receiver_id, source_ip)] = st
            st[0] += 1
            st[1] = beijing_now()

    def flush_stats(self) -> None:
        """把内存统计批量刷入 log_source_entries（失败回填下轮重试）。"""
        with self._lock:
            pending, self._stats = self._stats, {}
        if not pending:
            return
        db = SessionLocal()
        try:
            for (rid, ip), (count, last_at) in pending.items():
                db.execute(
                    sa_text(
                        """
                        UPDATE log_source_entries
                        SET received_count = received_count + :n,
                            last_received_at = :t
                        WHERE receiver_id = :rid AND source_ip = :ip
                        """
                    ),
                    {"n": count, "t": last_at, "rid": rid, "ip": ip},
                )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("来源条目统计 flush 失败（回填下轮重试）: %s", exc)
            with self._lock:
                for k, (count, last_at) in pending.items():
                    st = self._stats.get(k)
                    if st is None:
                        self._stats[k] = [count, last_at]
                    else:
                        st[0] += count
                        if last_at:
                            st[1] = last_at
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 缓存失效（API 更新/删除条目后调用）
    # ------------------------------------------------------------------
    def invalidate(self, receiver_id=None, source_ip=None) -> None:
        with self._lock:
            if receiver_id is None:
                self._cache.clear()
                return
            if source_ip is None:
                for k in [k for k in self._cache if k[0] == receiver_id]:
                    self._cache.pop(k, None)
            else:
                self._cache.pop((receiver_id, source_ip), None)


# 进程级单例
entry_registry = EntryRegistry()


# ----------------------------------------------------------------------
# 条目级配置合并（runner 注入点使用）
# ----------------------------------------------------------------------
def merge_receiver_entry(receiver: dict, entry: dict) -> dict:
    """把条目配置合并进 receiver dict（浅拷贝，不修改原 dict）。

    优先级链：条目 strategy_id/device_id → 渠道 → 设备绑定 → 自动匹配。
    条目 entry_config.pipeline 与渠道 adapter_config.pipeline 深合并
    （条目覆盖渠道，渠道覆盖默认），与 runner.for_receiver 的合并语义一致。
    """
    merged = dict(receiver or {})
    strategy_id = entry.get("strategy_id")
    if strategy_id is not None:
        # 显式 0 = 条目强制自动匹配（忽略渠道固定策略）
        merged["strategy_id"] = strategy_id
    if entry.get("device_id"):
        merged["device_id"] = entry["device_id"]

    entry_cfg = entry.get("entry_config")
    entry_pipeline = entry_cfg.get("pipeline") if isinstance(entry_cfg, dict) else None
    if entry_pipeline:
        from .pipeline.runner import _deep_merge  # 局部导入避免循环

        adapter_cfg = _receiver_adapter_cfg(merged)
        channel_pipeline = adapter_cfg.get("pipeline") or {}
        merged["adapter_config"] = {
            **adapter_cfg,
            "pipeline": _deep_merge(channel_pipeline, entry_pipeline),
        }
    return merged
