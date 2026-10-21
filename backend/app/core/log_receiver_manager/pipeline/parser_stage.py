"""① Parser 阶段：复用 ParseEngine（策略 JSON 驱动），不重写解析。

策略优先级与原 _ingest_through_pipeline 完全一致：
    receiver.strategy_id（条目/渠道固定）→ Device.parser_strategy_id（设备绑定）
    → ClassifierRouter 自动路由（均未指定时：元数据直路由 → 特征匹配候选
    回退 → route_rules 兜底 → unknown 兜底队列）。

成功/部分成功的结果同时构建 NormalizedEvent（一一对应挂到 data.normalized），
供 Filter/Enricher/Translator/Normalizer 后续步骤操作；fail 的条目在此处
直接记接收明细+解析指标并丢弃（与原逻辑一致）；类型识别失败的条目额外
写入 unknown 兜底队列（parse_error_queue，error_type=unknown_log_type，
支持重试与人工处理）。
"""
import json
import logging
from datetime import datetime
from typing import Optional

from app.core.timezone import BEIJING_TZ
from app.engine.classifier import ERR_UNKNOWN_LOG_TYPE, ClassifierRouter

from ..events import NormalizedEvent
from ..registry import stage_registry
from .base_stage import BaseStage, PipelineData

logger = logging.getLogger(__name__)


@stage_registry.register
class ParserStage(BaseStage):
    """策略解析步骤（config 暂无参数，纯复用引擎）。"""

    name = "parser"

    def process(self, data: PipelineData, sink, db) -> None:
        from app.api.v1.ingest import SQLAlchemySink, get_strategy_loader
        from app.engine.parser_engine import ParseEngine

        loader = get_strategy_loader()
        if not loader.strategies:
            loader.refresh()
        engine = ParseEngine(loader=loader, sink=SQLAlchemySink(db))
        data.engine = engine
        data.stat_hour = datetime.now(BEIJING_TZ).strftime("%Y-%m-%dT%H")

        # 渠道手动固定解析策略：>0 时严格用该策略解析（失败即解析失败，不自动换）
        # 渠道未指定时，回退到设备级绑定（Device.parser_strategy_id）
        receiver = data.event.receiver or {}
        pinned_id = receiver.get("strategy_id")
        if not pinned_id:
            dev_id = receiver.get("device_id")
            if dev_id:
                from sqlalchemy import text as sa_text

                pinned_id = db.execute(
                    sa_text("SELECT parser_strategy_id FROM devices WHERE id = :id"),
                    {"id": dev_id},
                ).scalar()
        pinned_strategy: Optional[dict] = None
        if pinned_id:
            pinned_strategy = loader.get_by_id(int(pinned_id))
        data.pinned_strategy = pinned_strategy

        raw = data.event.raw
        router = ClassifierRouter(loader)
        for it in data.items:
            if isinstance(it, dict):
                if pinned_id:
                    result = engine.parse_one(it, strategy=pinned_strategy)
                else:
                    # 类型识别与路由：元数据直路由 → 特征匹配候选回退 →
                    # route_rules 兜底 → unknown 兜底队列
                    result = router.parse_one(it, engine)
            else:
                result = None
            if result is None or result.status == "fail":
                unknown = (
                    result is not None and result.error_type == ERR_UNKNOWN_LOG_TYPE
                )
                sink.record_parsed(
                    raw,
                    "unknown" if unknown else "fail",
                    result.error_msg if result else "数据不是 JSON 对象",
                    strategy_id=result.strategy_id if result else None,
                    strategy_name=result.strategy_name if result else "",
                    rule_id=result.rule_id if result else "",
                    log_type=result.log_type if result else "",
                )
                if unknown and engine.sink is not None:
                    # unknown 兜底队列：原始报文写 parse_error_queue（可重试/人工处理）
                    try:
                        engine.sink.save_error(
                            raw,
                            ERR_UNKNOWN_LOG_TYPE,
                            result.error_msg,
                            uuid=result.uuid or None,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("unknown 兜底队列写入失败")
                engine.sink.record_metrics(
                    data.stat_hour,
                    result.strategy_id if result else None,
                    result.strategy_name if result else "",
                    "fail",
                    result.parse_ms if result else 0,
                )
                continue
            data.results.append(result)
            data.normalized.append(NormalizedEvent.from_parse_result(result))
