"""PipelineRunner：按配置组装六步流水线并执行（_ingest_through_pipeline 迁入）。

配置三层合并：
1. 全局默认 ``pipeline_default.json``；
2. 渠道 ``adapter_config.pipeline`` 深覆盖（阶段2起生效）；
3. Runner 实例按 ``(receiver_id, config_hash)`` 缓存，渠道配置刷新时自然失效。

执行流程（与原 _ingest_through_pipeline 逐行为等价）：
    独立 db 会话 → ReceiverSink.record_raw_received → 预处理器链 → 五步
    → db.commit；异常 rollback + 日志（不向 worker 抛出）。
"""
import copy
import hashlib
import json
import logging
import os
import threading
from typing import Optional

from app.database import SessionLocal

from .alert_rule_stage import AlertRuleStage
from .base_stage import PipelineData
from .enricher_stage import EnricherStage
from .filter_stage import FilterStage
from .normalizer_stage import NormalizerStage
from .parser_stage import ParserStage
from .preprocessors import run_preprocessor_chain
from .sink import ReceiverSink
from .translator_stage import TranslatorStage

logger = logging.getLogger(__name__)

# 默认流水线配置（包内 JSON，随代码发布）
_DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "pipeline_default.json")

# 六步链构造顺序（预处理插件链在 runner 层执行，不作为 Stage）
# alert_rule 位于 translator 与 normalizer 之间：解析成功的日志经告警规则
# 判定（严格模式）后才进入落库步骤
_STAGE_ORDER: list = [
    ("parser", ParserStage),
    ("filter", FilterStage),
    ("enricher", EnricherStage),
    ("translator", TranslatorStage),
    ("alert_rule", AlertRuleStage),
    ("normalizer", NormalizerStage),
]

_default_config_cache: Optional[dict] = None
_default_config_lock = threading.Lock()


def _deep_merge(base: dict, override: dict) -> dict:
    """深合并：override 的同名键覆盖 base，dict 递归合并。"""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override) if override is not None else copy.deepcopy(base)
    out = copy.deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def get_default_config() -> dict:
    """加载（并缓存）全局默认流水线配置。"""
    global _default_config_cache
    with _default_config_lock:
        if _default_config_cache is None:
            try:
                with open(_DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                    _default_config_cache = json.load(f)
            except Exception:  # noqa: BLE001
                logger.exception("读取 pipeline_default.json 失败，使用内置默认")
                _default_config_cache = {}
        return copy.deepcopy(_default_config_cache)


class PipelineRunner:
    """单渠道流水线执行器（按渠道配置构造，实例可复用）。"""

    # (receiver_id, source_ip, config_hash) → PipelineRunner 实例缓存
    # source_ip 维度支持"来源条目"级配置：同渠道不同来源各有独立 runner
    _cache: dict = {}
    _cache_lock = threading.Lock()
    # 缓存容量上限（FIFO 淘汰，dict 保序）：单渠道最多 32 个条目配置、全局 512
    _MAX_PER_RECEIVER = 32
    _MAX_GLOBAL = 512

    def __init__(self, config: dict) -> None:
        self.config = config or {}
        self.preprocessor_chain = list(self.config.get("preprocessors") or [])
        self.stages = [
            stage_cls(self.config.get(key) or {})
            for key, stage_cls in _STAGE_ORDER
            if self.config.get(key) is not False  # config 中置 false 可整步禁用
        ]

    # ------------------------------------------------------------------
    # 实例缓存
    # ------------------------------------------------------------------
    @classmethod
    def _evict_locked(cls) -> None:
        """容量上限淘汰（须持锁调用）：per-channel / 全局 FIFO 淘汰最旧。"""
        if len(cls._cache) <= cls._MAX_GLOBAL:
            return
        # 单渠道超限：淘汰该渠道最旧的条目配置
        per_recv: dict = {}
        for k in list(cls._cache.keys()):
            per_recv.setdefault(k[0], []).append(k)
        for rid, ks in per_recv.items():
            for old in ks[: max(0, len(ks) - cls._MAX_PER_RECEIVER)]:
                cls._cache.pop(old, None)
        # 全局超限：按插入序淘汰最旧
        overflow = len(cls._cache) - cls._MAX_GLOBAL
        if overflow > 0:
            for old in list(cls._cache.keys())[:overflow]:
                cls._cache.pop(old, None)

    @classmethod
    def for_receiver(cls, receiver: dict, source_ip: str = "") -> "PipelineRunner":
        """取（或构造）某渠道（可含来源条目维度）的流水线执行器（按配置 hash 缓存）。"""
        receiver = receiver or {}
        rid = receiver.get("id") or 0
        override = {}
        adapter_cfg = receiver.get("adapter_config")
        if isinstance(adapter_cfg, str):
            try:
                adapter_cfg = json.loads(adapter_cfg or "{}")
            except (ValueError, TypeError):
                adapter_cfg = {}
        if isinstance(adapter_cfg, dict):
            override = adapter_cfg.get("pipeline") or {}
        config = _deep_merge(get_default_config(), override)
        config_hash = hashlib.md5(
            json.dumps(config, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        key = (rid, source_ip or "", config_hash)
        with cls._cache_lock:
            runner = cls._cache.get(key)
            if runner is None:
                runner = cls(config)
                cls._cache[key] = runner
                cls._evict_locked()
            return runner

    # ------------------------------------------------------------------
    # 执行（原 _ingest_through_pipeline 迁入）
    # ------------------------------------------------------------------
    def run(self, event) -> None:
        """把一条 RawEvent 送入五步流水线（异常吞掉，不影响 worker）。"""
        db = SessionLocal()
        try:
            sink = ReceiverSink(db, event.receiver, event.source_ip)
            # 1) 记录接收明细 + total 指标
            sink.record_raw_received(event.raw)

            # 2) 预处理器链：原始报文 → 可消费 payload
            payload = run_preprocessor_chain(self.preprocessor_chain, event.raw)
            items = payload if isinstance(payload, list) else [payload]
            if not items:
                # 未产出可解析条目：仍提交接收明细与指标
                # （此前直接 return 未 commit，received 行被回滚丢失，
                # 导致渠道/条目累计计数与明细统计脱节）
                db.commit()
                return

            # 3) 五步流水线
            data = PipelineData(event=event, payload=payload, items=items)
            for stage in self.stages:
                stage.process(data, sink, db)

            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("日志接收解析管道异常: %s", exc)
            db.rollback()
        finally:
            db.close()


def run_pipeline_for_event(event) -> None:
    """总线 worker 回调入口：监听型渠道先做来源条目发现/配置合并，再执行流水线。

    - 条目自动发现（首见建库，失败回退渠道默认，日志零丢失）；
    - 条目停用（enabled=0）= 丢弃该来源日志；
    - 条目级 strategy_id / pipeline 覆盖合并进 receiver dict，
      形成 条目 → 渠道 → 设备绑定 → 自动匹配 的策略优先级链。
    """
    from ..entry_registry import LISTEN_PROTOCOLS, entry_registry, merge_receiver_entry

    receiver = event.receiver or {}
    source_ip = getattr(event, "source_ip", None)
    if source_ip and receiver.get("protocol") in LISTEN_PROTOCOLS:
        entry = entry_registry.resolve(receiver.get("id"), source_ip, receiver)
        if entry is not None:
            entry_registry.bump(receiver.get("id"), source_ip)
            if not entry.get("enabled"):
                return  # 条目已停用：丢弃该来源日志
            receiver = merge_receiver_entry(receiver, entry)
            # 写回事件：ParserStage（策略优先级链）与 ReceiverSink（明细归属）
            # 均从 event.receiver 读取条目级配置
            event.receiver = receiver
    PipelineRunner.for_receiver(receiver, source_ip=source_ip or "").run(event)
