"""{{node_id.output.field}} 变量抽取与替换。

用于工作流技能（SkillEngine）中节点间上下文传递。
与 ``prompt_assembler`` 的 ``{{word}}`` 变量不冲突：本模块要求 ``.output.`` 中缀。
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# {{node_id.output.field.subfield}} — 必须含 .output. 中缀
# node_id 允许字母/数字/下划线/连字符；field_path 允许字母/数字/下划线/点
_NODE_VAR_PATTERN = re.compile(r"\{\{\s*([\w-]+)\.output\.([\w.]+)\s*\}\}")


def extract_node_refs(text: str) -> list[tuple[str, str]]:
    """抽取文本中所有 (node_id, field_path) 引用。

    Args:
        text: 可能含 {{node_id.output.field}} 占位符的文本

    Returns:
        [(node_id, field_path), ...] 列表，保留出现顺序
    """
    if not text:
        return []
    refs: list[tuple[str, str]] = []
    for match in _NODE_VAR_PATTERN.finditer(text):
        node_id = match.group(1)
        field_path = match.group(2)
        refs.append((node_id, field_path))
    return refs


def render_node_vars(text: str, node_outputs: dict[str, dict]) -> str:
    """把 {{node_id.output.field}} 替换为 node_outputs[node_id][field]。

    缺失时保留原占位符并 warning（便于调试）。
    field_path 支持点分嵌套：{{n1.output.data.ip}} → node_outputs["n1"]["data"]["ip"]。

    Args:
        text: 含占位符的文本
        node_outputs: {node_id: output_dict} 节点输出映射

    Returns:
        替换后的文本
    """
    if not text or not node_outputs:
        return text

    def _replace(match: re.Match) -> str:
        node_id = match.group(1)
        field_path = match.group(2)
        if node_id not in node_outputs:
            logger.warning("变量引用节点不存在: node_id=%s, field=%s", node_id, field_path)
            return match.group(0)  # 保留原占位符
        value = _get_nested(node_outputs[node_id], field_path)
        if value is None:
            logger.warning("变量引用字段不存在: node_id=%s, field=%s", node_id, field_path)
            return match.group(0)
        if isinstance(value, str):
            return value
        import json

        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    return _NODE_VAR_PATTERN.sub(_replace, text)


def _get_nested(data: dict, path: str) -> Any:
    """按点分路径取嵌套值。

    Args:
        data: 字典
        path: 点分路径，如 "data.ip.address"

    Returns:
        值；路径不存在返回 None
    """
    if not isinstance(data, dict) or not path:
        return None
    current: Any = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current
