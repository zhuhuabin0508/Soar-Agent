"""② Filter 阶段：config 驱动的可配置丢弃规则（默认禁用，全透传）。

config 结构::

    {
      "enabled": false,
      "match": "all",            # all=全部条件满足才丢弃 / any=任一满足即丢弃
      "rules": [
        {"field": "risk_level", "op": "gte", "value": 0},
        {"field": "alert_name", "op": "regex", "value": ".*健康检查.*"},
        {"field": "src_ip", "op": "empty"}
      ]
    }

op 支持：eq / ne / in / not_in / gte / lte / gt / lt / regex / contains /
exists / empty / in_cidr（IP 属于网段，value 为 CIDR 列表或单个 CIDR）。
field 取值为空（字段缺失）时仅 exists/empty 可判定，其余 op 视为不满足。
"""
import ipaddress
import logging
import re
from typing import Any

from ..registry import stage_registry
from .base_stage import BaseStage, PipelineData

logger = logging.getLogger(__name__)


def _ip_in_cidrs(actual: Any, expected: Any) -> bool:
    """IP 是否属于任一 CIDR 网段（value：CIDR 列表 / 单个 CIDR / 逗号分隔字符串）。"""
    if isinstance(expected, str):
        raw_nets = [p.strip() for p in expected.split(",") if p.strip()]
    elif isinstance(expected, list):
        raw_nets = expected
    else:
        raw_nets = [expected]
    nets = []
    for item in raw_nets:
        try:
            nets.append(ipaddress.ip_network(str(item), strict=False))
        except ValueError:
            continue
    if not nets:
        return False
    try:
        addr = ipaddress.ip_network(str(actual), strict=False)
    except ValueError:
        return False
    for net in nets:
        try:
            if addr.subnet_of(net):
                return True
        except TypeError:  # IPv4/IPv6 版本不匹配
            continue
    return False


def _match_op(actual: Any, op: str, expected: Any) -> bool:
    """单条规则判定（actual 为字段实际值，可能为 None=缺失）。"""
    if op == "exists":
        return actual is not None
    if op == "empty":
        return actual is None or actual == "" or actual == []
    if actual is None:
        return False  # 其余 op 对缺失字段一律不满足
    try:
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "in":
            return actual in (expected or [])
        if op == "not_in":
            return actual not in (expected or [])
        if op == "regex":
            return re.search(str(expected), str(actual)) is not None
        if op == "contains":
            return str(expected) in str(actual)
        if op == "in_cidr":
            return _ip_in_cidrs(actual, expected)
        if op in ("gte", "lte", "gt", "lt"):
            a, b = float(actual), float(expected)
            return {"gte": a >= b, "lte": a <= b, "gt": a > b, "lt": a < b}[op]
    except (TypeError, ValueError):
        return False
    return False


def should_drop(norm, match: str, rules: list[dict]) -> bool:
    """按 match（all/any）聚合规则判定是否丢弃。"""
    results = []
    for rule in rules or []:
        field = rule.get("field") or ""
        op = (rule.get("op") or "eq").lower()
        expected = rule.get("value")
        results.append(_match_op(norm.get_field(field), op, expected))
    if not results:
        return False
    return all(results) if (match or "all").lower() != "any" else any(results)


@stage_registry.register
class FilterStage(BaseStage):
    """可配置丢弃步骤（默认 enabled=false，保证重构后行为等价全透传）。"""

    name = "filter"

    def process(self, data: PipelineData, sink, db) -> None:
        if not self.config.get("enabled"):
            return
        rules = self.config.get("rules") or []
        if not rules:
            return
        match = self.config.get("match") or "all"
        kept_results, kept_normalized = [], []
        for result, norm in zip(data.results, data.normalized):
            if should_drop(norm, match, rules):
                data.dropped += 1
                continue
            kept_results.append(result)
            kept_normalized.append(norm)
        data.results = kept_results
        data.normalized = kept_normalized
        if data.dropped:
            logger.info(
                "Filter 丢弃 %s 条事件（receiver=%s rules=%s）",
                data.dropped, data.event.receiver_id, len(rules),
            )
