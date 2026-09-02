"""解析流水线调度。

流程：接收 → 策略路由 → 外层解包 → 字段映射 → 枚举翻译 → 校验 → 扩展归档 → 入库。

引擎通过 ``sink``（持久化后端）依赖注入落库，不直接依赖数据库：
- 生产环境传入 SQLAlchemy 实现（见 ``app.api.v1.ingest``）；
- 测试时 sink 传 None 或内存实现即可独立运行解析并返回结果。
"""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Protocol

from app.engine.enum_translator import translate as enum_translate
from app.engine.field_mapper import apply_mappings
from app.engine.strategy_loader import StrategyLoader, get_path
from app.engine.validator import run_validations
from app.core.timezone import BEIJING_TZ

logger = logging.getLogger(__name__)

# 错误类型常量
ERR_JSON_PARSE = "json_parse_failed"
ERR_NO_STRATEGY = "no_strategy_matched"
ERR_DB_WRITE = "db_write_failed"
ERR_VALIDATION = "field_validation_failed"


class ParseSink(Protocol):
    """持久化后端协议（依赖注入，引擎不依赖具体实现）。"""

    def save_alert(self, fields: dict[str, Any]) -> str:
        """写入标准告警表，返回 ``inserted`` / ``duplicate``（幂等跳过）。"""
        ...

    def save_error(
        self,
        raw_data: str,
        error_type: str,
        error_msg: str,
        uuid: Optional[str] = None,
        strategy_id: Optional[int] = None,
    ) -> None:
        """写入解析错误队列。"""
        ...

    def record_metrics(
        self,
        stat_hour: str,
        strategy_id: Optional[int],
        strategy_name: str,
        status: str,
        parse_ms: int,
    ) -> None:
        """按小时累加指标（status ∈ total 之外的 success/partial/fail，total 由 save 调用决定）。"""
        ...


@dataclass
class ParseResult:
    """单条告警的解析结果。"""

    status: str = "fail"  # success / partial / fail
    fields: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)
    strategy_id: Optional[int] = None
    strategy_name: str = ""
    error_type: str = ""
    error_msg: str = ""
    uuid: str = ""
    parse_ms: int = 0

    def to_dict(self) -> dict:
        """序列化为可 JSON 化的 dict（供 API 响应与测试断言）。"""
        return {
            "status": self.status,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "uuid": self.uuid,
            "warnings": self.warnings,
            "error_type": self.error_type,
            "error_msg": self.error_msg,
            "parse_ms": self.parse_ms,
        }


class ParseEngine:
    """策略驱动的告警解析引擎。

    Args:
        loader: 策略加载器（含路由匹配）。
        sink: 持久化后端；None 时只解析不落库（纯计算模式）。
    """

    def __init__(self, loader: StrategyLoader, sink: Optional[ParseSink] = None) -> None:
        self.loader = loader
        self.sink = sink

    # ------------------------------------------------------------------
    # 单条解析（纯计算，不落库）
    # ------------------------------------------------------------------
    def parse_one(self, raw: dict) -> ParseResult:
        """解析单条原始告警，返回解析结果（不落库，可独立测试）。

        Args:
            raw: 原始告警 JSON（dict）。

        Returns:
            :class:`ParseResult`，status 为 success / partial / fail。
        """
        started = time.perf_counter()
        result = ParseResult()

        # 1. 策略路由
        strategy = self.loader.match(raw)
        if strategy is None:
            result.status = "fail"
            result.error_type = ERR_NO_STRATEGY
            result.error_msg = "无匹配策略"
            result.parse_ms = int((time.perf_counter() - started) * 1000)
            return result
        config = strategy.get("config") or {}
        result.strategy_id = strategy.get("id")
        result.strategy_name = strategy.get("strategy_name") or config.get("strategy_name", "")
        logger.debug(
            "策略命中: id=%s name=%s device=%s",
            result.strategy_id, result.strategy_name, config.get("device_type"),
        )

        # 2. 外层解包
        wrapper = config.get("outer_wrapper") or {}
        data_path = wrapper.get("data_path") or ""
        data = get_path(raw, data_path, default={})
        if not isinstance(data, dict):
            data = {}
            result.warnings.append(
                {"field": "", "source": data_path, "message": f"外层解包失败: {data_path} 不是对象"}
            )
        header_fields = wrapper.get("header_fields") or []
        headers = {k: raw.get(k) for k in header_fields if k in raw}

        # uuid 提前提取（错误队列与结果都用）
        uuid_source = wrapper.get("uuid_source") or ""
        uuid_val = get_path(raw, uuid_source)
        result.uuid = str(uuid_val) if uuid_val is not None else ""

        # 3. 字段映射
        fields, mapping_warnings, enum_specs = apply_mappings(
            data, config.get("field_mappings") or [], raw,
        )
        result.warnings.extend(mapping_warnings)

        # 4. 枚举翻译
        enum_translate(fields, enum_specs, config.get("enum_maps") or {})

        # 5. 校验（失败不阻断，记入 warnings，状态降为 partial）
        validation_warnings = run_validations(fields, config.get("validations") or [])
        result.warnings.extend(validation_warnings)

        # 6. 扩展归档：extension_fields + header_fields → extensions
        extensions: dict[str, Any] = dict(headers)
        for src in config.get("extension_fields") or []:
            if src in data:
                extensions[src] = data[src]
        fields["extensions"] = json.dumps(extensions, ensure_ascii=False)
        fields["strategy_id"] = result.strategy_id
        fields["device_type"] = config.get("device_type") or fields.get("device_type", "")
        if result.uuid:
            fields["uuid"] = result.uuid
        fields["raw_data"] = json.dumps(raw, ensure_ascii=False)
        fields["parse_warnings"] = json.dumps(result.warnings, ensure_ascii=False)

        result.fields = fields
        result.status = "partial" if result.warnings else "success"
        fields["parse_status"] = result.status
        result.parse_ms = int((time.perf_counter() - started) * 1000)
        logger.debug(
            "解析完成: uuid=%s status=%s warnings=%d 用时=%dms",
            result.uuid, result.status, len(result.warnings), result.parse_ms,
        )
        return result

    # ------------------------------------------------------------------
    # 批量处理（含落库）
    # ------------------------------------------------------------------
    def process(self, raw_items: list[Any]) -> dict[str, Any]:
        """处理一批原始数据：逐条解析并落库（若注入了 sink）。

        Args:
            raw_items: 原始数据列表；元素非 dict（JSON 解析失败）时记错误队列。

        Returns:
            汇总统计：
            ``{"total", "success", "partial", "fail", "duplicates", "results": [...]}``。
        """
        stats = {"total": 0, "success": 0, "partial": 0, "fail": 0, "duplicates": 0, "results": []}
        stat_hour = datetime.now(BEIJING_TZ).strftime("%Y-%m-%dT%H")

        for raw in raw_items:
            stats["total"] += 1

            # JSON 解析失败（非 dict 元素）
            if not isinstance(raw, dict):
                self._on_error(
                    raw_data=repr(raw), error_type=ERR_JSON_PARSE,
                    error_msg=f"原始数据不是 JSON 对象: {type(raw).__name__}",
                    stat_hour=stat_hour,
                )
                stats["fail"] += 1
                stats["results"].append(
                    {"status": "fail", "error_type": ERR_JSON_PARSE, "error_msg": "原始数据不是 JSON 对象"}
                )
                continue

            result = self.parse_one(raw)

            # 无匹配策略
            if result.status == "fail":
                self._on_error(
                    raw_data=json.dumps(raw, ensure_ascii=False),
                    error_type=result.error_type,
                    error_msg=result.error_msg,
                    uuid=result.uuid,
                    stat_hour=stat_hour,
                )
                stats["fail"] += 1
                stats["results"].append(result.to_dict())
                continue

            # 落库（sink 为 None 时跳过，纯计算模式）
            if self.sink is not None:
                try:
                    outcome = self.sink.save_alert(result.fields)
                    if outcome == "duplicate":
                        stats["duplicates"] += 1
                        logger.debug("重复 uuid 跳过: %s", result.uuid)
                except Exception as exc:
                    # 入库失败 → 错误队列 + 指标 fail
                    logger.exception("告警入库失败: uuid=%s", result.uuid)
                    self._on_error(
                        raw_data=json.dumps(raw, ensure_ascii=False),
                        error_type=ERR_DB_WRITE,
                        error_msg=str(exc),
                        uuid=result.uuid,
                        strategy_id=result.strategy_id,
                        stat_hour=stat_hour,
                    )
                    stats["fail"] += 1
                    stats["results"].append(
                        {**result.to_dict(), "status": "fail", "error_type": ERR_DB_WRITE}
                    )
                    continue
                try:
                    self.sink.record_metrics(
                        stat_hour, result.strategy_id, result.strategy_name,
                        result.status, result.parse_ms,
                    )
                except Exception:
                    logger.exception("指标埋点失败（不影响入库）")

            stats[result.status] += 1
            stats["results"].append(result.to_dict())

        logger.info(
            "批量解析完成: total=%d success=%d partial=%d fail=%d duplicates=%d",
            stats["total"], stats["success"], stats["partial"], stats["fail"], stats["duplicates"],
        )
        return stats

    def _on_error(
        self,
        raw_data: str,
        error_type: str,
        error_msg: str,
        uuid: Optional[str] = None,
        strategy_id: Optional[int] = None,
        stat_hour: str = "",
    ) -> None:
        """写错误队列 + fail 指标（sink 存在时）。"""
        if self.sink is None:
            return
        try:
            self.sink.save_error(raw_data, error_type, error_msg, uuid=uuid, strategy_id=strategy_id)
            if stat_hour:
                self.sink.record_metrics(stat_hour, strategy_id, "", "fail", 0)
        except Exception:
            logger.exception("错误队列写入失败: type=%s", error_type)
