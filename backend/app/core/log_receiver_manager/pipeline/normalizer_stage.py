"""⑤ Normalizer 阶段：NormalizedEvent → AlertEvent 落库（末端映射）。

- ``to_alert_fields()`` 把 ECS 事件无损映射回 AlertEvent 兼容 dict；
- 复用 SQLAlchemySink.save_alert（uuid 重复 → partial「重复告警，已跳过」，
  成功触发封禁工作流）；
- 告警聚合（XDR 风格）：命中规则的告警若配置了聚合（同键同窗合并），
  先查同规则 + 同聚合键 + 时间窗内的既有告警，命中则聚合计数 +1 并
  更新发生时间，不产生新告警记录；首条告警携带聚合键落库；
- 逐条写接收明细（success/partial/fail）+ 解析量指标；
- 富化结果（norm.enrichments 非空时）并入 extensions["enrichment"] 归档，
  默认无富化则不触碰 extensions（与重构前逐字段一致）。
"""
import json
import logging
from datetime import timedelta

from ..registry import stage_registry
from .base_stage import BaseStage, PipelineData

logger = logging.getLogger(__name__)


def _record(sink, raw, result, status, err=None, alert_id=None) -> None:
    """记录单条解析终态明细（带命中信息：模板/规则 + 解析后字段）。"""
    sink.record_parsed(
        raw, status, err, alert_id,
        strategy_id=result.strategy_id,
        strategy_name=result.strategy_name,
        rule_id=result.rule_id,
        log_type=result.log_type,
        parsed_fields=result.fields or None,
    )


def _aggregation_key(fields: dict, keys: list) -> str:
    """聚合键值串：键字段按序拼接（值转字符串，缺失留空）。"""
    return "|".join(str(fields.get(k) or "") for k in keys)[:255]


def _find_aggregatable(db, AlertEvent, rule_id: int, key: str, window_start) -> object | None:
    """查找可合并的既有告警：同规则 + 同聚合键 + 时间窗内（最新一条）。"""
    return (
        db.query(AlertEvent)
        .filter(
            AlertEvent.alert_rule_id == rule_id,
            AlertEvent.aggregation_key == key,
            AlertEvent.created_at >= window_start,
        )
        .order_by(AlertEvent.id.desc())
        .first()
    )


@stage_registry.register
class NormalizerStage(BaseStage):
    """范式化落库步骤。"""

    name = "normalizer"

    def process(self, data: PipelineData, sink, db) -> None:
        from app.core.timezone import beijing_now
        from app.models.alert_event import AlertEvent
        from app.core.log_receiver_manager.pipeline.alert_rule_stage import (
            _stats_window_seconds,
            get_alert_aggregation_config,
        )

        engine = data.engine
        raw = data.event.raw
        for result, norm in zip(data.results, data.normalized):
            fields = norm.to_alert_fields()
            # 告警名称兜底：模板规则未提取 alert_name 时，用命中规则名（log_type）/
            # 威胁类型（threat_type）填充，避免告警列表出现空名称
            if not fields.get("alert_name"):
                fields["alert_name"] = (
                    norm.get_field("log_type")
                    or norm.get_field("threat_type")
                    or ""
                )
            # 富化结果并入 extensions（仅在有富化时；默认空富化不动 extensions）
            if norm.enrichments:
                try:
                    ext = json.loads(fields.get("extensions") or "{}")
                    if isinstance(ext, dict):
                        ext["enrichment"] = norm.enrichments
                        fields["extensions"] = json.dumps(ext, ensure_ascii=False)
                except (ValueError, TypeError):
                    pass
            try:
                # ===== 告警聚合：同规则 + 同聚合键 + 时间窗内 → 合并计数，不产生新告警 =====
                agg_cfg = get_alert_aggregation_config(fields.get("alert_rule_id"))
                if agg_cfg:
                    key = _aggregation_key(fields, agg_cfg.get("keys") or [])
                    window_start = beijing_now() - timedelta(
                        seconds=_stats_window_seconds(agg_cfg.get("window") or {})
                    )
                    existing = _find_aggregatable(
                        db, AlertEvent, int(fields["alert_rule_id"]), key, window_start
                    )
                    if existing is not None:
                        existing.aggregation_count = (existing.aggregation_count or 1) + 1
                        # 发生时间推进到最新一条（保持窗口语义）
                        if fields.get("occur_timestamp") is not None:
                            existing.occur_timestamp = fields.get("occur_timestamp")
                        if fields.get("last_timestamp") is not None:
                            existing.last_timestamp = fields.get("last_timestamp")
                        db.commit()
                        _record(
                            sink, raw, result, result.status,
                            err=f"同类告警聚合：合并至告警 #{existing.id}（累计 {existing.aggregation_count} 条）",
                            alert_id=existing.id,
                        )
                        engine.sink.record_metrics(
                            data.stat_hour, result.strategy_id, result.strategy_name,
                            result.status, result.parse_ms,
                        )
                        continue
                    # 窗口内首条：携带聚合键落库（后续同键合并依据）
                    fields["aggregation_key"] = key
                outcome = engine.sink.save_alert(fields)
                if outcome == "duplicate":
                    _record(sink, raw, result, "partial", err="重复告警，已跳过")
                    engine.sink.record_metrics(
                        data.stat_hour, result.strategy_id, result.strategy_name,
                        result.status, result.parse_ms,
                    )
                    continue
                alert_row = (
                    db.query(AlertEvent.id)
                    .filter(AlertEvent.uuid == fields.get("uuid"))
                    .first()
                )
                _record(
                    sink, raw, result, result.status,
                    alert_id=alert_row[0] if alert_row else None,
                )
                engine.sink.record_metrics(
                    data.stat_hour, result.strategy_id, result.strategy_name,
                    result.status, result.parse_ms,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("接收日志入库失败: %s", exc)
                _record(sink, raw, result, "fail", err=str(exc))
                engine.sink.record_metrics(
                    data.stat_hour, result.strategy_id, result.strategy_name,
                    "fail", result.parse_ms,
                )
