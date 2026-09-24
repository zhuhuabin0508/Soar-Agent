"""按规则 extract 定义提取并映射字段。

现有 field_mapper.apply_mappings 只支持"字段路径取数 + 类型转换"。
本模块把 apply_mappings 封装为规则级提取器，并新增 regex / template 两种
提取模式（处理非结构化/半结构化正文），复用 field_mapper.convert_value
做类型转换，保持与旧逻辑一致的转换语义。

extract 结构：
    { "type": "fields" | "regex" | "template", ... }

返回:
    (fields, warnings, enum_specs) 与 apply_mappings 一致，供引擎消费。
"""
import json
import logging
import re
from typing import Any, Optional

from app.engine.field_mapper import apply_mappings, convert_value, _deep_get

logger = logging.getLogger(__name__)


def extract_fields(data: dict, extract: dict, context: dict) -> tuple[dict, list[dict], list[dict]]:
    """按 extract 定义提取字段并映射。

    Args:
        data: 解包后的业务数据（外层 data_path 指向内容，若规则 extract 指定了
            独立 source，则本函数会先从 context 取出该子对象）。
        extract: 规则 extract 定义。
        context: 整条原始数据（用于跨层取值 / regex 的文本源）。

    Returns:
        ``(fields, warnings, enum_specs)``，语义与 apply_mappings 一致。
    """
    etype = (extract or {}).get("type") or "fields"

    if etype == "regex":
        return _extract_regex(data, extract, context)
    if etype == "template":
        return _extract_template(data, extract, context)
    # 默认 fields：直接复用现有 apply_mappings
    mappings = (extract or {}).get("fields")
    if mappings is None:
        mappings = (extract or {}).get("field_mappings") or []
    return apply_mappings(data, mappings, context)


def _resolve_source_data(data: dict, extract: dict, context: dict) -> tuple[Any, str]:
    """确定提取的文本/数据源。

    优先级：extract.source（点分路径，从 context 取）> data（外层解包结果）。
    """
    src_path = (extract or {}).get("source") or ""
    if src_path:
        return _deep_get(context, src_path), src_path
    return data, ""


def _extract_regex(data: dict, extract: dict, context: dict) -> tuple[dict, list[dict], list[dict]]:
    """正则命名组提取：把文本按正则匹配，捕获组 → 目标字段。"""
    fields: dict[str, Any] = {}
    warnings: list[dict] = []
    enum_specs: list[dict] = []

    pattern = (extract or {}).get("regex") or ""
    src, src_path = _resolve_source_data(data, extract, context)
    text = str(src) if src is not None else ""
    mappings = (extract or {}).get("mappings") or []

    if not pattern:
        warnings.append({"field": "", "source": src_path, "message": "regex 提取缺少 regex 表达式"})
        return fields, warnings, enum_specs

    try:
        m = re.search(pattern, text)
    except re.error as exc:
        warnings.append({"field": "", "source": src_path, "message": f"regex 表达式非法: {exc}"})
        return fields, warnings, enum_specs

    for mp in mappings:
        target = mp.get("target") or ""
        conv_type = mp.get("type") or "string"
        enum_map = mp.get("enum_map")
        enum_target = mp.get("enum_target")
        value = None
        if m:
            group = mp.get("group")
            if group is not None:
                value = m.group(str(group)) if str(group).isdigit() else m.groupdict().get(str(group))
        # 转换
        try:
            converted = convert_value(value, conv_type)
        except (ValueError, TypeError) as exc:
            warnings.append({"field": target, "source": src_path, "message": f"类型转换失败({conv_type}): {exc}"})
            converted = _type_default(conv_type)
        if converted is None:
            converted = mp.get("default")
        fields[target] = converted
        if enum_map and enum_target:
            enum_specs.append({"target": target, "enum_map": enum_map, "enum_target": enum_target})

    return fields, warnings, enum_specs


def _extract_template(data: dict, extract: dict, context: dict) -> tuple[dict, list[dict], list[dict]]:
    """模板/分隔提取：把文本按 sep 切分，按列序映射到目标字段。"""
    fields: dict[str, Any] = {}
    warnings: list[dict] = []
    enum_specs: list[dict] = []

    src, src_path = _resolve_source_data(data, extract, context)
    text = str(src) if src is not None else ""
    sep = (extract or {}).get("sep") or r"\s+"
    columns = (extract or {}).get("columns") or []
    mappings = (extract or {}).get("mappings") or []

    try:
        parts = re.split(sep, text.strip())
    except re.error as exc:
        warnings.append({"field": "", "source": src_path, "message": f"template 分隔符非法: {exc}"})
        return fields, warnings, enum_specs

    # 列位置 → 目标映射
    idx_map: dict[int, dict] = {}
    for mp in mappings:
        idx = mp.get("index")
        if isinstance(idx, int):
            idx_map[idx] = mp
    for i, col in enumerate(columns):
        if i >= len(columns):
            break
        # 支持 columns 列名直接映射 target
        mp = {k: v for k, v in idx_map.get(i, {}).items()}
        target = mp.get("target") or col
        if not target:
            continue
        conv_type = mp.get("type") or "string"
        enum_map = mp.get("enum_map")
        enum_target = mp.get("enum_target")
        raw_value = parts[i] if i < len(parts) else None
        try:
            converted = convert_value(raw_value, conv_type)
        except (ValueError, TypeError) as exc:
            warnings.append({"field": target, "source": src_path, "message": f"类型转换失败({conv_type}): {exc}"})
            converted = _type_default(conv_type)
        if converted is None:
            converted = mp.get("default")
        fields[target] = converted
        if enum_map and enum_target:
            enum_specs.append({"target": target, "enum_map": enum_map, "enum_target": enum_target})

    return fields, warnings, enum_specs


def apply_rule_map(fields: dict, rule_map: dict, context: dict, warnings: list[dict]) -> dict:
    """应用规则 map 阶段：额外的字段映射 + 默认值补充。

    枚举翻译已由引擎统一调用 enum_translator，此处不重复。
    规则 map 通常不含额外映射（提取阶段已处理），保留兼容以支持 rule 级再映射。
    """
    extra_mappings = (rule_map or {}).get("field_mappings") or []
    if extra_mappings:
        mapped, warns, _ = apply_mappings(context, extra_mappings, context)
        for k, v in mapped.items():
            if v is not None:
                fields[k] = v
        warnings.extend(warns)

    # 默认值补充（仅当目标尚未赋值）
    for d in (rule_map or {}).get("defaults") or []:
        target = d.get("target")
        if target and not fields.get(target):
            fields[target] = d.get("value")
    return fields


def _type_default(conv_type: str) -> Any:
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
    return ""
