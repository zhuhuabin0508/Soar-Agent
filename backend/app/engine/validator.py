"""校验规则执行。

校验失败不阻断入库，记入 parse_warnings，parse_status 降为 partial。
支持规则：regex / ip_list_valid / range / positive_int。
"""
import ipaddress
import json
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def _iter_ips(value: Any) -> list[str]:
    """把字段值展开为 IP 字符串列表。

    兼容：JSON 数组字符串（``["1.1.1.1","2.2.2.2"]``）、逗号分隔字符串、单个 IP。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    s = str(value).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (ValueError, TypeError):
            pass
    return [p.strip() for p in s.split(",") if p.strip()]


def run_validations(
    fields: dict[str, Any],
    validations: list[dict],
) -> list[dict]:
    """对解析后的字段执行校验规则。

    Args:
        fields: 解析后的标准模型字段 dict。
        validations: 策略 validations 列表，
            ``[{"field", "rule", "severity", ...}]``。

    Returns:
        校验警告列表 ``[{"field", "rule", "severity", "message"}]``。
    """
    warnings: list[dict] = []

    for rule in validations or []:
        field = rule.get("field") or ""
        rule_type = rule.get("rule") or ""
        severity = rule.get("severity") or "warning"
        if not field or not rule_type:
            continue

        value = fields.get(field)

        ok = True
        message = ""
        if rule_type == "regex":
            pattern = rule.get("pattern") or ""
            try:
                ok = value is not None and re.fullmatch(pattern, str(value)) is not None
                if not ok:
                    message = f"不符合正则 {pattern}: {value!r}"
            except re.error:
                message = f"非法正则 {pattern}"
                ok = False
        elif rule_type == "ip_list_valid":
            ips = _iter_ips(value)
            invalid = []
            for ip in ips:
                try:
                    ipaddress.ip_address(ip)
                except ValueError:
                    invalid.append(ip)
            ok = not invalid
            if not ok:
                message = f"非法 IP: {', '.join(invalid)}"
        elif rule_type == "positive_int":
            # datetime 类型字段：校验其为正数秒级时间戳（转换前）；
            # 转换后已是 datetime，仅校验非空；数字则校验 > 0
            if isinstance(value, datetime):
                ok = value.year > 1970
                if not ok:
                    message = f"时间戳异常: {value!r}"
            else:
                try:
                    num = float(value) if value is not None and value != "" else None
                except (ValueError, TypeError):
                    num = None
                ok = num is not None and num > 0
                if not ok:
                    message = f"非正数时间戳: {value!r}"
        elif rule_type == "range":
            try:
                num = float(value) if value is not None and value != "" else None
            except (ValueError, TypeError):
                num = None
            if num is None:
                ok = False
                message = f"非数值无法校验范围: {value!r}"
            else:
                lo = rule.get("min")
                hi = rule.get("max")
                if lo is not None and num < float(lo) or hi is not None and num > float(hi):
                    ok = False
                    message = f"超出范围 [{lo}, {hi}]: {num}"
        else:
            # 未知规则跳过（不记警告）
            logger.debug("未知校验规则 %r，跳过", rule_type)
            continue

        if not ok:
            warnings.append(
                {"field": field, "rule": rule_type, "severity": severity, "message": message}
            )
            logger.debug("校验警告: field=%s rule=%s %s", field, rule_type, message)

    return warnings
