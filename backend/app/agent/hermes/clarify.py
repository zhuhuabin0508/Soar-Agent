"""澄清问答工具 —— 移植自 Hermes ``tools/clarify_tool.py``。

允许 Agent 在信息不足时主动向用户提问，而非瞎猜后执行错误动作。

SOAR 场景尤其重要：

- 告警 IP 字段为空或格式异常 → 问用户补充
- 设备操作目标不明确（多台设备匹配）→ 问用户选哪台
- block_ip 的封禁时长未指定 → 问用户封多久
- 告警严重程度与处置策略不匹配 → 问用户确认

两种模式（与 Hermes 一致）：

1. **多选** —— 提供最多 4 个选项，用户选一个或输入"其他"
2. **开放式** —— 不提供选项，用户自由文本回答

关键设计（与 Hermes 一致）：

- 选项只放 ``choices`` 数组，**绝不**写进 ``question`` 文本（UI 会渲染
  choices 为可选项；写进 question 会变成死文本）
- ``callback`` 由平台层注入（CLI/Web），本模块只定义 schema + 校验 + 派发
- 最大 4 选项 + 自动追加"其他"= 5 个 UI 行

调用方式：作为工具注册到 ``tool_engine``，LLM 调用 ``clarify`` 工具时
触发，``callback`` 通过 ``interrupt_event`` 挂起执行等待用户输入。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_CHOICES",
    "clarify_tool",
    "CLARIFY_SCHEMA",
    "get_clarify_tool_schema",
]


# 预定义选项数上限。UI 自动追加第 5 个"其他（输入你的答案）"。
MAX_CHOICES = 4


def _flatten_choice(c: Any) -> str:
    """把单个选项强转为用户可见的显示字符串。

    schema 声明 choices 为裸字符串，但 LLM 有时发 dict 形式
    （``[{"description": "..."}]``）。朴素的 ``str(c)`` 会把整个 dict
    变成 Python repr —— ``{'description': '...'}`` —— 泄露到每个渲染
    选项的表面（CLI 面板、Web 选项、编号列表）并被原样作为用户答案返回。

    dict 解包顺序是规范的 LLM 工具调用用户可见 key：
    ``label`` → ``description`` → ``text`` → ``title``。
    ``name`` 和 ``value`` 故意排除 —— 它们是组件形状字段，可能携带原始
    enum 值或短标识符，非人类可读标签。
    """
    if c is None:
        return ""
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, dict):
        for key in ("label", "description", "text", "title"):
            v = c.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    if isinstance(c, (list, tuple)):
        return " ".join(_flatten_choice(x) for x in c).strip()
    return str(c).strip()


def clarify_tool(
    question: str,
    choices: Optional[List[str]] = None,
    callback: Optional[Callable[[str, Optional[List[str]]], str]] = None,
) -> str:
    """向用户提问，可选带多选选项。

    Args:
        question: 问题文本（只含问题本身，不含选项）
        choices: 最多 4 个预定义答案选项。省略时为开放式提问。
        callback: 平台层注入的回调，签名 ``callback(question, choices) -> str``。
                  None 时返回错误（当前执行上下文不支持交互）。

    Returns:
        JSON 字符串，含用户响应。
    """
    if not question or not question.strip():
        return json.dumps({"error": "问题文本不能为空"}, ensure_ascii=False)

    question = question.strip()

    # 校验和修剪选项
    if choices is not None:
        if not isinstance(choices, list):
            return json.dumps({"error": "choices 必须是字符串列表"}, ensure_ascii=False)
        choices = [s for s in (_flatten_choice(c) for c in choices) if s]
        if len(choices) > MAX_CHOICES:
            choices = choices[:MAX_CHOICES]
        if not choices:
            choices = None  # 空列表 → 开放式

    if callback is None:
        return json.dumps(
            {"error": "当前执行上下文不支持澄清问答（无 callback 注入）"},
            ensure_ascii=False,
        )

    try:
        user_response = callback(question, choices)
    except Exception as exc:
        logger.exception("clarify callback 异常: %s", exc)
        return json.dumps({"error": f"获取用户输入失败: {exc}"}, ensure_ascii=False)

    return json.dumps({
        "question": question,
        "choices_offered": choices,
        "user_response": str(user_response).strip(),
    }, ensure_ascii=False)


# OpenAI Function-Calling Schema
CLARIFY_SCHEMA = {
    "name": "clarify",
    "description": (
        "当你需要澄清、反馈或决策时向用户提问。支持两种模式：\n\n"
        "1. **多选** —— 提供最多 4 个选项，用户选一个或输入'其他'。\n"
        "2. **开放式** —— 不提供选项，用户自由文本回答。\n\n"
        "关键：提供选项时，每个选项只放 ``choices`` 数组，绝不把选项写进 "
        "``question`` 文本。UI 会渲染 choices 为可选项；写进 question 的"
        "选项会变成死文本。\n\n"
        "正确: question='封禁多长时间？', choices=['1小时', '24小时', '永久']\n"
        "错误: question='封禁多长时间？1) 1小时 2) 24小时', choices=[]\n\n"
        "使用场景：\n"
        "- 告警信息不全（IP 为空、设备未指定）\n"
        "- 设备操作目标不明确（多台设备匹配）\n"
        "- 处置策略与告警严重程度不匹配\n"
        "- 决策有重大权衡，需用户参与\n\n"
        "不要用于危险命令的简单 yes/no 确认（写工具的 verification 机制处理）。"
        "低风险决策应自行做合理默认选择。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "问题本身，且只有问题（如 '封禁多长时间？'）。"
                    "不要把答案选项嵌入这里 —— 作为 ``choices`` 数组的独立元素传入。"
                ),
            },
            "choices": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_CHOICES,
                "description": (
                    "提供可选项时必填：每个选项是数组的一个元素（最多 4 个）。"
                    "UI 会渲染为可点选行并自动追加'其他（输入你的答案）'选项。"
                    "仅当 genuinely 开放式自由文本提问时才省略此参数。"
                ),
            },
        },
        "required": ["question"],
    },
}


def get_clarify_tool_schema() -> dict:
    """返回 OpenAI function-calling 兼容的 clarify 工具 schema。"""
    return {"type": "function", "function": CLARIFY_SCHEMA}
