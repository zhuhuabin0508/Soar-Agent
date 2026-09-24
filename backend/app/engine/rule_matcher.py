"""解析规则匹配：判断一条原始日志命中策略内哪条规则。

策略配置升级后，一个策略（设备级解析配置）的 ``rules[]`` 内包含多条规则，
每条规则负责一种日志类型。本模块负责评估规则的 ``match.conditions``，
返回命中的规则 dict（序列化后调用，不依赖数据库）。
"""
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def resolve_rule(raw: dict, config: dict) -> Optional[dict]:
    """从策略 config 的 rules[] 中选出一条命中的规则。

    兼容旧结构：若 config 无 ``rules`` 键，视为单规则策略，返回规整好的
    默认规则（由旧 route_rules / field_mappings 归一化而来），永远命中。

    多规则时按定义顺序逐条评估，取第一个命中（保证确定性）。未命中返回 None。

    Args:
        raw: 原始告警 dict（可能已预处理）。
        config: 策略 config dict。

    Returns:
        命中的规则 dict（含 rule_id/log_type/extract/map 等）；旧结构返回归一化默认规则。
    """
    rules = normalize_rules(config)
    for rule in rules:
        if rule.get("enabled") is False:
            continue
        if _match_rule(raw, rule.get("match") or {}):
            logger.debug("规则命中: rule_id=%s log_type=%s", rule.get("rule_id"), rule.get("log_type"))
            return rule
    logger.debug("未命中任何规则")
    return None


def normalize_rules(config: dict) -> list[dict]:
    """把 config 归一化为规则列表。

    - 新结构：直接返回 config["rules"]；
    - 旧结构（无 rules）：由 route_rules + field_mappings + enum_maps + validations
      + extension_fields 组装成一条默认规则，保证存量策略零改动可用。
    """
    rules = config.get("rules")
    if isinstance(rules, list) and rules:
        return rules
    return [_build_default_rule(config)]


def _build_default_rule(config: dict) -> dict:
    """旧结构 → 单条默认规则。"""
    route = config.get("route_rules") or {}
    return {
        "rule_id": "default",
        "log_type": "默认",
        "enabled": True,
        # 旧的 route_rules 单对象转成 match.conditions
        "match": _route_to_match(route),
        "extract": {"type": "fields", "fields": config.get("field_mappings") or []},
        "map": {
            "field_mappings": config.get("field_mappings") or [],
            "enum_maps": config.get("enum_maps") or {},
            "defaults": [],
            "validations": config.get("validations") or [],
        },
        "extension_fields": config.get("extension_fields") or [],
    }


def _route_to_match(route: dict) -> dict:
    """旧 route_rules（单对象）→ match 结构。

    保留 route_rules 语义，同时兼容归一化后的 match（若已存在则直接使用）。
    """
    if route.get("conditions"):
        return route
    match_type = str(route.get("match_type") or "exact").lower()
    match_field = route.get("match_field") or ""
    match_value = route.get("match_value")
    if not match_field:
        # 无匹配字段 → 无条件，恒命中（单规则策略）
        return {"type": "all", "conditions": []}
    op = "regex" if match_type == "regex" else "eq"
    return {
        "type": "all",
        "conditions": [
            {"field": match_field, "op": op, "value": match_value}
        ],
    }


def _match_rule(raw: dict, match: dict) -> bool:
    """评估规则的 match 条件。

    match = {"type": "all"|"any", "conditions": [...]}
    每条 condition = {"field", "op", "value"}，op ∈ eq/not_eq/in/not_in/regex/contains/gte/lte/gt/lt。
    """
    conditions = match.get("conditions") or []
    if not conditions:
        return True
    combine = str(match.get("type") or "all").lower()
    results = [_match_condition(raw, c) for c in conditions]
    if combine == "any":
        return any(results)
    return all(results)


def _get_path(obj: Any, path: str, default: Any = None) -> Any:
    """按点分路径从嵌套 dict 中取值（module 级复用，避免循环依赖）。"""
    if not path:
        return obj
    cur = obj
    for key in str(path).split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _match_condition(raw: dict, cond: dict) -> bool:
    """评估单条条件。"""
    field = cond.get("field") or ""
    op = str(cond.get("op") or "eq").lower()
    expected = cond.get("value")
    actual = _get_path(raw, field) if field else None

    try:
        if op == "eq":
            return actual == expected
        if op == "not_eq":
            return actual != expected
        if op == "in":
            return actual in (expected or [])
        if op == "not_in":
            return actual not in (expected or [])
        if op == "contains":
            return str(expected) in str(actual)
        if op == "regex":
            return re.fullmatch(str(expected), str(actual)) is not None
        if op in ("gte", "gt", "lte", "lt"):
            return _compare(actual, expected, op)
    except (TypeError, ValueError, re.error) as exc:
        logger.debug("条件评估异常 field=%s op=%s: %s", field, op, exc)
        return False
    return False


def _compare(actual: Any, expected: Any, op: str) -> bool:
    """数值比较。"""
    try:
        a, b = float(actual), float(expected)
    except (TypeError, ValueError):
        return False
    return {
        "gte": a >= b,
        "gt": a > b,
        "lte": a <= b,
        "lt": a < b,
    }[op]
