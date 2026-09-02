"""Pydantic / FastAPI 请求体校验错误信息中文化。

FastAPI 默认在 422 RequestValidationError 中返回英文消息（如
``body.title: String should have at least 5 characters``）。本模块负责把
``ValidationError`` 的 errors() 列表翻译为用户可读的中文摘要，由
``main.py`` 注册的全局异常处理器统一调用。

翻译策略：
1. 错误类型（``type``）→ 中文模板（带占位符 ``{min}`` / ``{max}`` 等上下文）；
2. 字段路径（``loc``）的最末段 → 友好的中文字段名（仅在反馈等已知模块覆盖）；
3. 字段名未知时退化为英文路径，确保不丢信息。

输出示例：``标题：长度不能少于 5 字；详细描述：长度不能少于 5 字``
"""
from __future__ import annotations

from typing import Any, Iterable

# ============ 字段名中英文映射 ============
# 仅覆盖用户提交场景的高频字段；未覆盖字段保留英文，便于排查
FIELD_LABELS: dict[str, str] = {
    # 反馈
    "title": "标题",
    "description": "详细描述",
    "module": "所属模块",
    "priority": "严重程度",
    "type": "反馈类型",
    "reproduce_steps": "复现步骤",
    "expected_result": "期望结果",
    "actual_result": "实际结果",
    "contact": "联系方式",
    "content": "回复内容",
    "status": "状态",
    "ids": "反馈ID列表",
    "action": "批量动作",
    # 通用
    "username": "用户名",
    "password": "密码",
    "email": "邮箱",
    "phone": "电话",
    "name": "名称",
    "page": "页码",
    "size": "每页条数",
}

# ============ 错误类型中文模板 ============
# key 与 Pydantic v2 的 error['type'] 对应；占位符从 ctx 取
TYPE_TEMPLATES: dict[str, str] = {
    # 缺失
    "missing": "该字段为必填项",
    "missing_for_discriminator": "缺少判别字段",
    # 字符串
    "string_too_short": "长度不能少于 {min} 字",
    "string_too_long": "长度不能超过 {max} 字",
    "string_pattern_mismatch": "格式不符合要求",
    "string_type": "必须是文本",
    "value_error": "取值不合法",
    # 数值
    "int_parsing": "必须是整数",
    "int_parsing_size": "数值过大",
    "int_type": "必须是整数",
    "float_parsing": "必须是数字",
    "float_type": "必须是数字",
    "less_than": "必须小于 {lt}",
    "less_than_equal": "必须小于等于 {le}",
    "greater_than": "必须大于 {gt}",
    "greater_than_equal": "必须大于等于 {ge}",
    "multiple_of": "必须是 {multiple_of} 的倍数",
    # 列表 / 长度
    "too_short": "至少需要 {min_length} 项",
    "too_long": "最多允许 {max_length} 项",
    "list_type": "必须是列表",
    # 布尔 / 枚举
    "bool_parsing": "必须是布尔值",
    "bool_type": "必须是布尔值",
    "literal_error": "取值不在允许范围内",
    "value_error.const": "取值不在允许范围内",
    "enum": "取值不在允许范围内",
    # 日期时间
    "date_parsing": "日期格式不正确",
    "datetime_parsing": "日期时间格式不正确",
    "time_parsing": "时间格式不正确",
    # 通用兜底
    "json_invalid": "JSON 格式不正确",
    "json_type": "必须是 JSON",
    "assertion_error": "校验失败",
    "value_error.missing": "该字段为必填项",
}


def _format_field(loc: list[str]) -> str:
    """从错误 loc（如 ['body', 'title']）取最末段并尝试中文化。

    - 去掉 'body' / 'query' / 'path' 这类参数来源前缀；
    - 末段若在 FIELD_LABELS 则用中文，否则保留英文。
    """
    if not loc:
        return ""
    # 去掉 FastAPI 注入的来源前缀
    cleaned = [p for p in loc if p not in ("body", "query", "path", "header")]
    if not cleaned:
        return loc[-1]
    last = str(cleaned[-1])
    return FIELD_LABELS.get(last, last)


def _format_message(err: dict[str, Any]) -> str:
    """按 type 模板渲染中文消息，带占位符的从 ctx 替换。"""
    etype = str(err.get("type") or "")
    ctx = err.get("ctx") or {}
    # 模板里的 {min}/{max} 等短占位符与 Pydantic v2 的 ctx 键（min_length/max_length）不同，
    # 这里做别名补齐，避免 format() 抛 KeyError 回退成原模板。
    aliases = {"min": "min_length", "max": "max_length"}
    fmt_ctx: dict[str, Any] = {k: v for k, v in ctx.items() if isinstance(v, (int, float, str))}
    for short, long_key in aliases.items():
        if long_key in fmt_ctx and short not in fmt_ctx:
            fmt_ctx[short] = fmt_ctx[long_key]
    template = TYPE_TEMPLATES.get(etype)
    if template:
        try:
            return template.format(**fmt_ctx)
        except (KeyError, IndexError, ValueError):
            return template
    # Pydantic v1 风格兜底：使用原始 msg 但去掉英文标识
    raw = str(err.get("msg") or "")
    if not raw:
        return "取值不合法"
    # 常见英文短语兜底翻译
    fallback_map = {
        "field required": "该字段为必填项",
        "value is not a valid integer": "必须是整数",
        "value is not a valid float": "必须是数字",
        "value is not a valid boolean": "必须是布尔值",
        "value is not a valid list": "必须是列表",
        "value is not a valid datetime": "日期时间格式不正确",
        "value is not a valid date": "日期格式不正确",
        "ensure this value has at least": "长度不足",
        "ensure this value has at most": "长度超出限制",
        "str": "字符串",
    }
    lower = raw.lower()
    for en, zh in fallback_map.items():
        if en in lower:
            return zh
    return raw


def translate_validation_errors(errors: Iterable[dict[str, Any]]) -> str:
    """把 Pydantic errors 列表翻译为以「；」分隔的中文摘要。

    单条：``标题：长度不能少于 5 字``
    多条：``标题：长度不能少于 5 字；详细描述：长度不能少于 5 字``
    """
    parts: list[str] = []
    for err in errors:
        field = _format_field(list(err.get("loc") or []))
        msg = _format_message(err)
        parts.append(f"{field}：{msg}" if field else msg)
    # 去重保留顺序
    seen: set[str] = set()
    unique = [p for p in parts if not (p in seen or seen.add(p))]
    return "；".join(unique) if unique else "请求参数校验失败"
