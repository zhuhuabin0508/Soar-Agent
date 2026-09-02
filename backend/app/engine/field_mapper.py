"""字段映射与类型转换。

按策略 ``field_mappings`` 定义，把源数据字段转换为目标标准模型字段。
支持的 type：
- string / int / float / bool
- json_array_to_string：数组 → JSON 字符串
- json_object_to_string：对象 → JSON 字符串
- timestamp_to_datetime：秒级时间戳 → datetime（时区取 timezone_field 指定字段值）
- comma_split_to_json：逗号分隔字符串 → JSON 数组字符串
- enum_int：int 枚举（翻译由 enum_translator 完成，这里只做 int 转换）
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# 时区字符串 → UTC 偏移小时（常见格式）
_TZ_PATTERN = re.compile(r"(?:GMT|UTC)\s*([+-])(\d{1,2})(?::?(\d{2}))?", re.IGNORECASE)

# 北京时区（与项目约定一致：DB 存北京时间 naive datetime）
BEIJING_TZ = timezone(timedelta(hours=8))


def _parse_tz_offset(tz_str: Any) -> timezone:
    """解析时区字符串为 timezone 对象，无法解析时回退北京时间。

    支持格式：GMT+08:00 / UTC+8 / GMT-05:30 等。
    """
    if tz_str:
        m = _TZ_PATTERN.search(str(tz_str))
        if m:
            sign = 1 if m.group(1) == "+" else -1
            hours = int(m.group(2))
            minutes = int(m.group(3) or 0)
            return timezone(sign * timedelta(hours=hours, minutes=minutes))
    return BEIJING_TZ


def convert_value(value: Any, conv_type: str, tz_value: Any = None) -> Any:
    """按 conv_type 转换单个值。

    Args:
        value: 源字段原始值。
        conv_type: 目标类型（见模块 docstring）。
        tz_value: timezone_field 指定字段的值（仅 timestamp_to_datetime 使用）。

    Returns:
        转换后的值；转换失败时返回 None（由调用方记警告）。

    Raises:
        ValueError: 类型转换无法完成（调用方捕获后记入 parse_warnings）。
    """
    if conv_type == "string":
        return "" if value is None else str(value)

    if conv_type == "int":
        if value is None or value == "":
            return 0
        # 兼容 "3"、"3.0" 等字符串
        return int(float(str(value)))

    if conv_type == "float":
        if value is None or value == "":
            return 0.0
        return float(str(value))

    if conv_type == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return bool(value)

    if conv_type == "json_array_to_string":
        if value is None or value == "":
            return "[]"
        if isinstance(value, (list, tuple)):
            return json.dumps(list(value), ensure_ascii=False)
        # 已是 JSON 数组字符串则原样返回，避免二次包装
        s = str(value).strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return json.dumps(parsed, ensure_ascii=False)
            except (ValueError, TypeError):
                pass
        # 单值也包装为数组
        return json.dumps([value], ensure_ascii=False)

    if conv_type == "json_object_to_string":
        if value is None:
            return "{}"
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        raise ValueError(f"期望 dict，实际 {type(value).__name__}")

    if conv_type == "timestamp_to_datetime":
        if value is None or value == "":
            return None
        ts = float(value)
        tz = _parse_tz_offset(tz_value)
        # 秒级时间戳 → 北京时间 naive datetime（项目统一约定）
        local = datetime.fromtimestamp(ts, tz=tz)
        return local.astimezone(BEIJING_TZ).replace(tzinfo=None)

    if conv_type == "comma_split_to_json":
        if value is None:
            return "[]"
        if isinstance(value, (list, tuple)):
            return json.dumps(list(value), ensure_ascii=False)
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
        return json.dumps(parts, ensure_ascii=False)

    if conv_type == "enum_int":
        if value is None or value == "":
            return -1
        return int(float(str(value)))

    # 未知类型：原样返回
    logger.debug("未知转换类型 %r，原样返回", conv_type)
    return value


def apply_mappings(
    data: dict,
    mappings: list[dict],
    context: dict,
) -> tuple[dict, list[dict], list[dict]]:
    """执行字段映射流水线。

    Args:
        data: 解包后的业务数据（outer_wrapper.data_path 指向的内容）。
        mappings: 策略 field_mappings 列表。
        context: 整条原始数据（用于 timezone_field 等跨层取值）。

    Returns:
        ``(fields, warnings, enum_specs)``：
        - fields：目标字段 → 转换后的值（仅包含映射到的字段）；
        - warnings：``[{"field", "source", "message"}]`` 警告列表；
        - enum_specs：``[{"target", "enum_map", "enum_target"}]`` 需要枚举翻译的字段规格，
          供 enum_translator 结合策略 enum_maps 完成翻译。
    """
    fields: dict[str, Any] = {}
    warnings: list[dict] = []
    enum_specs: list[dict] = []

    for m in mappings or []:
        source = m.get("source") or ""
        target = m.get("target") or ""
        conv_type = m.get("type") or "string"
        required = bool(m.get("required"))
        default = m.get("default")
        enum_map = m.get("enum_map")
        enum_target = m.get("enum_target")
        tz_field = m.get("timezone_field")

        value = data.get(source) if source else None

        # required 字段缺失 → 警告（不阻断）
        if source and source not in data:
            msg = f"源字段缺失: {source}"
            if required:
                warnings.append({"field": target or source, "source": source, "message": msg})
            logger.debug("字段映射: %s 缺失（required=%s）", source, required)

        # 缺失时填默认值
        if value is None:
            if default is not None:
                value = default
            else:
                # 类型默认：string→""、int→0、array→[]、datetime→None
                value = _type_default(conv_type)

        # timezone_field 的值（timestamp_to_datetime 用）
        tz_value = None
        if tz_field:
            tz_value = data.get(tz_field) if tz_field in data else _deep_get(context, tz_field)

        # 类型转换
        try:
            converted = convert_value(value, conv_type, tz_value)
        except (ValueError, TypeError) as exc:
            warnings.append(
                {"field": target, "source": source, "message": f"类型转换失败({conv_type}): {exc}"}
            )
            logger.debug("字段映射转换失败: %s→%s %s(%r): %s", source, target, conv_type, value, exc)
            converted = _type_default(conv_type)

        fields[target] = converted

        # 记录需要枚举翻译的字段规格
        if enum_map and enum_target:
            enum_specs.append(
                {"target": target, "enum_map": enum_map, "enum_target": enum_target}
            )

        logger.debug("字段映射: %s(%r) → %s = %r [%s]", source, value, target, converted, conv_type)

    return fields, warnings, enum_specs


def _type_default(conv_type: str) -> Any:
    """各转换类型的缺省默认值。"""
    if conv_type in ("string",):
        return ""
    if conv_type in ("int", "enum_int"):
        return 0
    if conv_type == "float":
        return 0.0
    if conv_type in ("json_array_to_string", "comma_split_to_json"):
        return "[]"
    if conv_type == "json_object_to_string":
        return "{}"
    if conv_type == "timestamp_to_datetime":
        return None
    return ""


def _deep_get(obj: Any, path: str, default: Any = None) -> Any:
    """按点分路径取值（context 中跨层查找 timezone_field）。"""
    cur = obj
    for key in str(path).split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur
