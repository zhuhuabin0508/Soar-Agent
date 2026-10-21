"""日志类型识别与路由（Classifier & Router）。

数据湖 / 日志审计设备推送「混合日志」时，接收链路在**未手动指定解析策略**的
情况下按本模块自动识别日志的设备类型并路由到对应解析策略。不改变手动指定的
优先级链：条目 strategy_id → 接收器 strategy_id → 设备绑定 parser_strategy_id
→ 本模块自动识别（增强原 route_rules 自动匹配层）。

路由流程（对应 classifier_features.yaml）：
    1. 元数据直路由：日志顶层携带 source_type / device_vendor 等元数据且
       命中某设备类型的别名 → 直接路由到该设备类型；
    2. 特征匹配：无元数据时按特异度（specificity）从高到低评估各设备类型
       的 match 特征条件，全部命中的进入候选列表（保持特异度顺序）；
    3. 候选回退：按候选顺序取该设备类型的启用策略（版本降序）逐个尝试解析，
       每个候选经过「路由级校验器」门控（YAML validators 任一失败、或策略
       内置 severity=error 校验失败 → 拒绝），失败回退下一候选；
       最后回退到旧版 route_rules 自动匹配（YAML 未登记设备类型的存量
       策略不受影响）；
    4. unknown 兜底：全部候选失败 → 返回 error_type=unknown_log_type 的
       失败结果，由调用方写入 unknown 兜底队列（parse_error_queue，
       支持重试与人工处理）。

特征匹配表为 YAML 文件（随包发布，按 mtime+size 热加载），新增设备类型只需
在表中追加条目，无需改代码。引擎侧依赖（ParseEngine/StrategyLoader）均为
依赖注入，本模块可脱离数据库独立测试。
"""
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from app.engine.parser_engine import ParseResult
from app.engine.rule_matcher import _match_rule
from app.engine.strategy_loader import _version_key
from app.engine.validator import run_validations

logger = logging.getLogger(__name__)

# unknown 兜底队列的错误类型（写入 parse_error_queue.error_type）
ERR_UNKNOWN_LOG_TYPE = "unknown_log_type"

# 特征匹配表默认路径（随包发布）
FEATURE_TABLE_PATH = os.path.join(os.path.dirname(__file__), "classifier_features.yaml")

# 元数据直路由检查字段（YAML 未配置时的默认值）
DEFAULT_METADATA_FIELDS = ["source_type", "device_vendor", "device_type", "vendor", "__source"]


# ----------------------------------------------------------------------
# 特征匹配表
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class DeviceTypeEntry:
    """单个设备类型的识别配置（YAML 归一化后）。"""

    device_type: str                    # 设备类型标识（对应策略 device_type）
    specificity: int = 0                # 特异度：越高越优先评估
    metadata: dict[str, list[str]] = field(default_factory=dict)  # 元数据别名（字段 → 小写别名）
    match: dict = field(default_factory=dict)                     # 特征条件（结构同策略规则 match）
    validators: list[dict] = field(default_factory=list)          # 路由级校验器


class FeatureTable:
    """特征匹配表（YAML 驱动；设备类型按特异度降序）。

    表结构（见 classifier_features.yaml）::

        metadata_fields: [source_type, device_vendor, ...]
        device_types:
          - device_type: xxx / specificity: N / metadata: {...} / match: {...} / validators: [...]
    """

    def __init__(
        self,
        metadata_fields: Optional[list[str]] = None,
        device_types: Optional[list[DeviceTypeEntry]] = None,
    ) -> None:
        self.metadata_fields = list(metadata_fields or DEFAULT_METADATA_FIELDS)
        # 特异性降序（排序稳定：同特异度保持 YAML 定义顺序）
        self.device_types: list[DeviceTypeEntry] = sorted(
            device_types or [], key=lambda e: -e.specificity
        )
        # (元数据字段, 小写别名) → 设备类型
        self._metadata_index: dict[tuple[str, str], str] = {}
        for entry in self.device_types:
            # 设备类型名本身是所有元数据字段的隐式别名
            for mf in self.metadata_fields:
                self._metadata_index[(mf, entry.device_type.lower())] = entry.device_type
            for mf, aliases in (entry.metadata or {}).items():
                for alias in aliases:
                    self._metadata_index[(mf, str(alias).lower())] = entry.device_type

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------
    @classmethod
    def empty(cls) -> "FeatureTable":
        """空表（文件缺失/解析失败时兜底：仅剩 route_rules 自动匹配）。"""
        return cls(metadata_fields=list(DEFAULT_METADATA_FIELDS), device_types=[])

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureTable":
        """从 YAML 解析结果归一化（结构非法时抛 ValueError，由加载层兜底）。"""
        data = data or {}
        raw_fields = data.get("metadata_fields")
        metadata_fields = (
            [str(f).strip() for f in raw_fields if str(f).strip()]
            if isinstance(raw_fields, list) else list(DEFAULT_METADATA_FIELDS)
        )
        entries: list[DeviceTypeEntry] = []
        seen: set[str] = set()
        for item in data.get("device_types") or []:
            if not isinstance(item, dict):
                logger.warning("特征匹配表条目不是对象，跳过: %r", item)
                continue
            device_type = str(item.get("device_type") or "").strip()
            if not device_type:
                logger.warning("特征匹配表条目缺少 device_type，跳过: %r", item)
                continue
            if device_type in seen:
                logger.warning("特征匹配表设备类型重复，后者忽略: %s", device_type)
                continue
            seen.add(device_type)
            try:
                specificity = int(item.get("specificity") or 0)
            except (TypeError, ValueError):
                specificity = 0
            metadata = {
                str(k).strip(): [str(v).strip() for v in (vs or []) if str(v).strip()]
                for k, vs in (item.get("metadata") or {}).items()
                if str(k).strip()
            }
            match = item.get("match") or {}
            if not isinstance(match, dict):
                logger.warning("设备类型 %s 的 match 不是对象，忽略特征条件", device_type)
                match = {}
            validators = item.get("validators") or []
            if not isinstance(validators, list):
                logger.warning("设备类型 %s 的 validators 不是列表，忽略", device_type)
                validators = []
            if not metadata and not (match.get("conditions") or []):
                logger.warning(
                    "设备类型 %s 无元数据别名且无特征条件，永远无法命中", device_type
                )
            entries.append(
                DeviceTypeEntry(
                    device_type=device_type,
                    specificity=specificity,
                    metadata=metadata,
                    match=match,
                    validators=list(validators),
                )
            )
        return cls(metadata_fields=metadata_fields, device_types=entries)

    @classmethod
    def from_yaml(cls, path: str = FEATURE_TABLE_PATH) -> "FeatureTable":
        """读取 YAML 文件并归一化（文件/语法错误抛异常）。"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    # ------------------------------------------------------------------
    # 匹配
    # ------------------------------------------------------------------
    def match_metadata(self, raw: dict) -> Optional[str]:
        """元数据直路由：按字段顺序检查日志顶层元数据，命中别名返回设备类型。

        元数据存在但不匹配任何已知设备类型时返回 None（交由特征匹配兜底）。
        """
        if not isinstance(raw, dict):
            return None
        for mf in self.metadata_fields:
            value = raw.get(mf)
            if value is None or str(value).strip() == "":
                continue
            hit = self._metadata_index.get((mf, str(value).strip().lower()))
            if hit:
                return hit
        return None

    def match_features(self, raw: dict) -> list[str]:
        """特征匹配：按特异度降序评估各设备类型的特征条件，返回全部命中（有序候选列表）。"""
        if not isinstance(raw, dict):
            return []
        hits: list[str] = []
        for entry in self.device_types:
            conditions = (entry.match or {}).get("conditions") or []
            if not conditions:
                continue
            try:
                if _match_rule(raw, entry.match):
                    hits.append(entry.device_type)
            except Exception:  # noqa: BLE001
                logger.exception("特征条件评估异常: device_type=%s", entry.device_type)
        return hits

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def validators(self, device_type: str) -> list[dict]:
        """设备类型的路由级校验器（未登记返回空）。"""
        for entry in self.device_types:
            if entry.device_type == device_type:
                return entry.validators
        return []

    def has(self, device_type: str) -> bool:
        """设备类型是否在表中登记。"""
        return any(entry.device_type == device_type for entry in self.device_types)


# ----------------------------------------------------------------------
# 特征表加载（mtime+size 缓存，热更新；解析失败保留上次可用表）
# ----------------------------------------------------------------------
_table_cache: dict[str, tuple[tuple[float, int], FeatureTable]] = {}
_table_lock = threading.Lock()


def load_feature_table(path: str = FEATURE_TABLE_PATH) -> FeatureTable:
    """加载（并按 mtime+size 缓存）特征匹配表；文件更新自动热加载。

    - 文件缺失 → 空表（系统降级为仅 route_rules 自动匹配，不影响运行）；
    - 语法/结构错误 → 保留上次可用表（首次失败则空表），记日志。
    """
    path = os.path.abspath(path or FEATURE_TABLE_PATH)
    try:
        st = os.stat(path)
        fingerprint = (st.st_mtime, st.st_size)
    except OSError:
        with _table_lock:
            cached = _table_cache.get(path)
        if cached:
            return cached[1]
        return FeatureTable.empty()

    with _table_lock:
        cached = _table_cache.get(path)
        if cached and cached[0] == fingerprint:
            return cached[1]

    # 锁外解析（YAML 解析可能较慢，避免长时间持锁；并发加载幂等）
    try:
        table = FeatureTable.from_yaml(path)
    except Exception:  # noqa: BLE001
        logger.exception("特征匹配表加载失败，保留旧表: %s", path)
        if cached:
            return cached[1]
        return FeatureTable.empty()

    with _table_lock:
        _table_cache[path] = (fingerprint, table)
        if not cached:
            logger.info(
                "特征匹配表已加载: %s（%d 个设备类型）", path, len(table.device_types)
            )
        else:
            logger.info("特征匹配表已热更新: %s（%d 个设备类型）", path, len(table.device_types))
    return table


def reload_feature_table(path: str = FEATURE_TABLE_PATH) -> FeatureTable:
    """清缓存强制重载（测试与管理端点用）。"""
    with _table_lock:
        _table_cache.pop(os.path.abspath(path or FEATURE_TABLE_PATH), None)
    return load_feature_table(path)


# ----------------------------------------------------------------------
# 类型识别（Classifier）
# ----------------------------------------------------------------------
@dataclass
class ClassifyResult:
    """类型识别结果。"""

    method: str = ""                     # metadata（元数据直路由）/ features（特征匹配）/ ""（未识别）
    candidates: list[str] = field(default_factory=list)  # 候选设备类型（特异度降序）
    device_type: Optional[str] = None    # method=metadata 时的直接命中
    reason: str = ""                     # 判定说明（日志/排障用）


class LogClassifier:
    """日志类型识别器：元数据直路由 → 特征匹配。"""

    def __init__(self, table: FeatureTable) -> None:
        self.table = table

    def classify(self, raw: dict) -> ClassifyResult:
        """识别日志的设备类型，返回候选列表（不保证候选有可用策略）。"""
        # 1. 元数据直路由
        hit = self.table.match_metadata(raw)
        if hit:
            return ClassifyResult(
                method="metadata",
                device_type=hit,
                candidates=[hit],
                reason=f"元数据直路由命中 {hit}",
            )
        # 2. 特征匹配（特异度降序，全部命中进入候选）
        hits = self.table.match_features(raw)
        if hits:
            return ClassifyResult(
                method="features",
                candidates=hits,
                reason="特征匹配命中 " + "、".join(hits),
            )
        return ClassifyResult(reason="无元数据且特征条件未命中")


# ----------------------------------------------------------------------
# 路由器（Router）：候选解析器依次尝试 + 校验门控 + unknown 兜底
# ----------------------------------------------------------------------
class ClassifierRouter:
    """按候选顺序尝试解析策略，校验不过回退下一候选，全部失败进 unknown。

    仅在未手动指定策略时被 ParserStage 调用（手动指定的策略仍严格生效，
    失败不自动换）。依赖注入 loader / engine，可脱离数据库独立测试。
    """

    def __init__(self, loader, classifier: Optional[LogClassifier] = None) -> None:
        self.loader = loader
        self._classifier = classifier

    def _current_classifier(self) -> LogClassifier:
        """分类器：测试注入优先；默认每次取热加载的特征表（YAML 更新即生效）。"""
        if self._classifier is not None:
            return self._classifier
        return LogClassifier(load_feature_table())

    def classify(self, raw: dict) -> ClassifyResult:
        """仅类型识别（供调试/测试观察路由决策）。"""
        return self._current_classifier().classify(raw)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def parse_one(self, raw: dict, engine) -> ParseResult:
        """类型识别 → 候选依次尝试 → 全部失败返回 unknown 结果。

        Args:
            raw: 单条原始日志 dict（预处理后）。
            engine: ParseEngine（解析 + 内置校验）。

        Returns:
            ParseResult：候选通过时为该候选的解析结果；全部失败时
            status=fail 且 error_type=unknown_log_type（调用方写兜底队列）。
        """
        classification = self._current_classifier().classify(raw)
        last: Optional[ParseResult] = None
        tried: list[str] = []

        # 3. 候选解析器依次尝试（候选设备类型 → 其启用策略，版本降序）
        for device_type in classification.candidates:
            for strategy in self._strategies_for(device_type):
                tried.append(f"{device_type}#策略{strategy.get('id')}")
                result, accepted = self._try(raw, engine, strategy, device_type)
                if result is not None:
                    last = result
                if accepted:
                    logger.info(
                        "类型路由成功: %s 候选=%s 策略=%s(%s)",
                        classification.method, device_type,
                        strategy.get("id"), strategy.get("strategy_name"),
                    )
                    return result

        # 旧版 route_rules 自动匹配兜底（YAML 未登记设备类型的存量策略不受影响）
        legacy = self.loader.match(raw)
        if legacy is not None:
            tried.append(f"route_rules#策略{legacy.get('id')}")
            result, accepted = self._try(
                raw, engine, legacy, str(legacy.get("device_type") or "")
            )
            if result is not None:
                last = result
            if accepted:
                return result

        # 4. unknown 兜底
        return self._unknown_result(raw, classification, tried, last)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _strategies_for(self, device_type: str) -> list[dict]:
        """候选设备类型的启用策略（缓存内已过滤 enabled），版本降序。"""
        strategies = [
            s for s in (self.loader.strategies or [])
            if str(s.get("device_type") or "") == device_type
        ]
        strategies.sort(key=lambda s: _version_key(s.get("version") or "0"), reverse=True)
        return strategies

    def _try(self, raw: dict, engine, strategy: dict, device_type: str):
        """尝试单候选：解析 + 路由级校验门控。

        Returns:
            (解析结果或 None, 是否接受)。解析异常返回 (None, False)。
        """
        try:
            result = engine.parse_one(raw, strategy=strategy)
        except Exception:  # noqa: BLE001
            logger.exception("候选策略解析异常，回退: 策略=%s", strategy.get("id"))
            return None, False
        if result.status == "fail":
            logger.debug(
                "候选解析失败，回退: 策略=%s %s", strategy.get("id"), result.error_msg
            )
            return result, False
        if not self._gate(device_type, result):
            logger.debug("候选校验不过，回退: 策略=%s device_type=%s",
                         strategy.get("id"), device_type)
            return result, False
        return result, True

    def _gate(self, device_type: str, result: ParseResult) -> bool:
        """路由级校验门控（拒绝即回退下一候选）：

        1. YAML 设备类型的 ``validators``：任一失败即拒绝（不论 severity，
           路由级校验器就是用来做候选门控的）；
        2. 策略内置 severity=error 的校验失败：拒绝（warning 级维持引擎
           既有语义：记警告降 partial，不阻断）。
        """
        validators = self._current_classifier().table.validators(device_type)
        if validators:
            failures = run_validations(result.fields or {}, validators)
            if failures:
                logger.debug("路由校验器拒绝 %s: %s", device_type, failures)
                return False
        if any((w or {}).get("severity") == "error" for w in result.warnings):
            return False
        return True

    def _unknown_result(
        self,
        raw: dict,
        classification: ClassifyResult,
        tried: list[str],
        last: Optional[ParseResult],
    ) -> ParseResult:
        """构造 unknown 兜底结果（error_type=unknown_log_type）。"""
        uuid_val = ""
        if last is not None and getattr(last, "uuid", ""):
            uuid_val = last.uuid
        else:
            best = raw.get("event_uuid") or raw.get("uuid") or ""
            uuid_val = str(best) if best else ""
        reason = classification.reason or "无元数据且特征条件未命中"
        msg = (
            f"类型识别与路由失败：{reason}；"
            f"已尝试 [{('、'.join(tried)) if tried else '无候选策略'}]"
        )
        if last is not None and last.error_msg:
            msg += f"；最后错误：{last.error_msg}"
        return ParseResult(
            status="fail",
            error_type=ERR_UNKNOWN_LOG_TYPE,
            error_msg=msg[:2000],
            uuid=uuid_val,
        )
