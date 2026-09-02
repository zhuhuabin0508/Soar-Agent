"""工具结果预算与持久化 —— 移植自 Hermes ``tools/budget_config.py`` +
``tools/tool_result_storage.py`` + ``tools/tool_output_limits.py``。

防御上下文窗口溢出的三层防护（与 Hermes 一致）：

1. **per-tool 输出上限**（工具内部）：工具在返回前自行截断。
   ``tool_output_limits`` 提供可配置的 ``max_bytes`` / ``max_lines`` / ``max_line_length``。
2. **per-result 持久化**（``maybe_persist_tool_result``）：工具返回后，
   若输出超过阈值，全量结果持久化到 ``Execution.variables``，上下文只
   保留预览 + 引用。模型可调用 ``query_persisted_result`` 虚拟工具取回。
3. **per-turn 聚合预算**（``enforce_turn_budget``）：收集本 turn 所有工具
   结果后，若总量超预算，把最大的非持久化结果溢出到持久化，直到达标。

SOAR 适配（与 Hermes 的差异）：

- Hermes 持久化到沙箱临时目录（``/tmp/hermes-results/``），模型用
  ``read_file`` 取回。SOAR 持久化到 ``Execution.variables``（数据库 JSON 列），
  模型用 ``query_persisted_result`` 虚拟工具取回。
- SOAR 的 ``Execution.variables`` 是 JSON 字段，单值有大小限制（默认 5MB，
  与知识库文档截断限制一致），超大结果需落盘 + 路径引用。
- 按模型上下文窗口动态缩放预算：小模型（如 65K token）不能套用大模型
  （200K+ token）的固定阈值，否则单条结果就撑爆窗口。

设计原则：

- ``read_file`` / ``query_persisted_result`` 等读取工具阈值设为 ``inf``，
  防止"持久化→读取→再持久化"无限循环。
- 预览在最后一个换行处截断，避免截断到一行中间。
- 持久化失败降级为内联截断（不丢失，但不可取回全量）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─── 默认阈值（与 Hermes 一致）────────────────────────────────────

# 单条工具结果持久化阈值（字符数）。超过则持久化。
DEFAULT_RESULT_SIZE_CHARS: int = 100_000
# 单 turn 所有工具结果聚合预算（字符数）。超过则溢出最大者。
DEFAULT_TURN_BUDGET_CHARS: int = 200_000
# 持久化后上下文保留的预览长度（字符数）。
DEFAULT_PREVIEW_SIZE_CHARS: int = 1_500

# 工具输出截断限制（per-tool 内部截断）
DEFAULT_MAX_BYTES: int = 50_000       # HTTP/命令输出字符上限
DEFAULT_MAX_LINES: int = 2_000        # 文件读取行数上限
DEFAULT_MAX_LINE_LENGTH: int = 2_000  # 单行长度上限

# 阈值不可覆盖的工具（防持久化→读取→持久化循环）
# read_file / query_persisted_result 等读取工具设为 inf
PINNED_THRESHOLDS: Dict[str, float] = {
    "read_file": float("inf"),
    "query_persisted_result": float("inf"),
    "session_search": float("inf"),
    "memory_search": float("inf"),
    "tool_search": float("inf"),
    "tool_describe": float("inf"),
    "list_workflow_skills": float("inf"),
}

# token↔字符转换。保守用 4 字符/token（与 model_metadata.py 估算一致）。
_CHARS_PER_TOKEN: int = 4

# 单条结果占模型窗口的比例上限，以及单 turn 工具输出占窗口的比例上限。
# 工具输出不是窗口里唯一的东西（系统提示、工具 schema、对话历史、模型自身
# 回复都要占位），所以这两个值远低于 1.0。
_PER_RESULT_WINDOW_FRACTION: float = 0.15
_PER_TURN_WINDOW_FRACTION: float = 0.30

# 下限：即使极小模型也保证可用预览
_MIN_RESULT_SIZE_CHARS: int = 8_000
_MIN_TURN_BUDGET_CHARS: int = 16_000


@dataclass(frozen=True)
class BudgetConfig:
    """3 层工具结果持久化的不可变预算常量。

    Layer 2 (per-result): ``resolve_threshold(tool_name)`` → 阈值字符数。
    Layer 3 (per-turn):   ``turn_budget`` → 单 turn 所有工具结果的聚合字符预算。
    Preview:              ``preview_size`` → 持久化后的内联预览大小。
    """

    default_result_size: int = DEFAULT_RESULT_SIZE_CHARS
    turn_budget: int = DEFAULT_TURN_BUDGET_CHARS
    preview_size: int = DEFAULT_PREVIEW_SIZE_CHARS
    tool_overrides: Dict[str, int] = field(default_factory=dict)

    def resolve_threshold(self, tool_name: str) -> int | float:
        """解析工具的持久化阈值。

        优先级：pinned → tool_overrides → default_result_size。
        pinned 工具（读取类）返回 inf，永不持久化。
        """
        if tool_name in PINNED_THRESHOLDS:
            return PINNED_THRESHOLDS[tool_name]
        if tool_name in self.tool_overrides:
            return self.tool_overrides[tool_name]
        return self.default_result_size


# 默认配置 —— 与历史硬编码行为完全一致
DEFAULT_BUDGET = BudgetConfig()


def budget_for_context_window(context_length: int | None) -> BudgetConfig:
    """按活动模型的上下文窗口缩放预算返回 BudgetConfig。

    固定默认值（100K 结果 / 200K turn 字符）对大模型（200K+ token）正确，
    但对小模型盲目：65K token 模型上一条 100K 字符的结果或 200K 字符的
    turn 预算（约 50K token）可能单独就接近或超过整个窗口，迫使超大请求。

    缩放使大模型与今天字节一致（比例值钳制到现有默认作为上限），
    同时按比例缩小小模型的预算，下限保证可用预览总能存活。
    """
    if not context_length or context_length <= 0:
        return DEFAULT_BUDGET

    window_chars = context_length * _CHARS_PER_TOKEN
    per_result = int(window_chars * _PER_RESULT_WINDOW_FRACTION)
    per_turn = int(window_chars * _PER_TURN_WINDOW_FRACTION)

    # 钳制：不超过历史默认（大模型不变），不低于下限（小模型可用）
    per_result = max(_MIN_RESULT_SIZE_CHARS, min(per_result, DEFAULT_RESULT_SIZE_CHARS))
    per_turn = max(_MIN_TURN_BUDGET_CHARS, min(per_turn, DEFAULT_TURN_BUDGET_CHARS))

    return BudgetConfig(
        default_result_size=per_result,
        turn_budget=per_turn,
        preview_size=DEFAULT_PREVIEW_SIZE_CHARS,
    )


# ─── 工具输出截断限制（Layer 1）──────────────────────────────────

@dataclass(frozen=True)
class ToolOutputLimits:
    """可配置的工具输出截断限制。"""

    max_bytes: int = DEFAULT_MAX_BYTES
    max_lines: int = DEFAULT_MAX_LINES
    max_line_length: int = DEFAULT_MAX_LINE_LENGTH

    @classmethod
    def from_mapping(cls, data: Dict[str, Any] | None) -> "ToolOutputLimits":
        if not isinstance(data, dict):
            return cls()
        return cls(
            max_bytes=_coerce_positive_int(data.get("max_bytes"), DEFAULT_MAX_BYTES),
            max_lines=_coerce_positive_int(data.get("max_lines"), DEFAULT_MAX_LINES),
            max_line_length=_coerce_positive_int(data.get("max_line_length"), DEFAULT_MAX_LINE_LENGTH),
        )


def truncate_output(
    content: str,
    limits: ToolOutputLimits,
    *,
    max_bytes: Optional[int] = None,
) -> str:
    """按 max_bytes 截断输出（Layer 1）。

    在最后一个换行处截断，避免截到一行中间。追加截断标记。
    """
    if not content:
        return content
    cap = max_bytes if max_bytes is not None else limits.max_bytes
    if len(content) <= cap:
        return content
    truncated = content[:cap]
    last_nl = truncated.rfind("\n")
    if last_nl > cap // 2:
        truncated = truncated[: last_nl + 1]
    omitted = len(content) - len(truncated)
    return f"{truncated}\n... [截断：省略 {omitted} 字符]"


def truncate_lines(
    content: str,
    limits: ToolOutputLimits,
    *,
    max_lines: Optional[int] = None,
) -> str:
    """按行数截断（Layer 1，文件读取场景）。"""
    if not content:
        return content
    cap = max_lines if max_lines is not None else limits.max_lines
    lines = content.split("\n")
    if len(lines) <= cap:
        # 仍需检查单行长度
        return "\n".join(_truncate_line(line, limits) for line in lines)
    kept = lines[:cap]
    omitted = len(lines) - cap
    return "\n".join(_truncate_line(line, limits) for line in kept) + f"\n... [截断：省略 {omitted} 行]"


def _truncate_line(line: str, limits: ToolOutputLimits) -> str:
    if len(line) <= limits.max_line_length:
        return line
    return line[: limits.max_line_length] + " ... [行截断]"


# ─── 持久化（Layer 2 + Layer 3）──────────────────────────────────

PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"


def generate_preview(content: str, max_chars: int = DEFAULT_PREVIEW_SIZE_CHARS) -> tuple[str, bool]:
    """在 max_chars 内的最后一个换行处截断。返回 (preview, has_more)。"""
    if len(content) <= max_chars:
        return content, False
    truncated = content[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        truncated = truncated[: last_nl + 1]
    return truncated, True


def _build_persisted_message(
    preview: str,
    has_more: bool,
    original_size: int,
    ref_key: str,
    tool_name: str,
) -> str:
    """构造 <persisted-output> 替换块。

    ``ref_key`` 是 Execution.variables 中的 key，模型用
    ``query_persisted_result(ref_key=...)`` 取回全量。
    """
    size_kb = original_size / 1024
    if size_kb >= 1024:
        size_str = f"{size_kb / 1024:.1f} MB"
    else:
        size_str = f"{size_kb:.1f} KB"

    msg = f"{PERSISTED_OUTPUT_TAG}\n"
    msg += f"工具 {tool_name} 的结果过大（{original_size:,} 字符，{size_str}）。\n"
    msg += f"全量结果已持久化到 Execution.variables，引用 key：{ref_key}\n"
    msg += "调用 query_persisted_result 工具（传 ref_key）可取回全量内容。\n\n"
    msg += f"预览（前 {len(preview)} 字符）：\n"
    msg += preview
    if has_more:
        msg += "\n..."
    msg += f"\n{PERSISTED_OUTPUT_CLOSING_TAG}"
    return msg


def _safe_ref_key(tool_use_id: str) -> str:
    """从 tool_use_id 生成安全的持久化 key。"""
    raw = str(tool_use_id or "tool_result")
    # 只保留字母数字/下划线/点/连字符
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    if not safe:
        safe = "tool_result"
    if len(safe) > 120:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        safe = safe[:120].rstrip("._-") + "_" + digest
    return f"persisted_{safe}"


def maybe_persist_tool_result(
    content: str,
    tool_name: str,
    tool_use_id: str,
    *,
    variables: Optional[dict] = None,
    config: BudgetConfig = DEFAULT_BUDGET,
    threshold: int | float | None = None,
) -> tuple[str, Optional[str]]:
    """Layer 2：持久化超大结果，返回 (replacement_content, ref_key)。

    把全量结果写入 ``variables`` 字典（调用方负责持久化到 Execution.variables），
    上下文内容替换为预览 + 引用。``variables`` 为 None 时降级为内联截断。

    Args:
        content: 原始工具结果字符串。
        tool_name: 工具名（用于阈值查找 + 消息展示）。
        tool_use_id: 本次调用的唯一 ID（用作持久化 key）。
        variables: Execution.variables 字典引用；None 则不持久化，降级截断。
        config: BudgetConfig 控制阈值和预览大小。
        threshold: 显式覆盖；优先于 config 解析。

    Returns:
        (replacement_content, ref_key)。ref_key 为 None 表示未持久化
        （结果小或持久化失败）。
    """
    effective_threshold = threshold if threshold is not None else config.resolve_threshold(tool_name)

    if effective_threshold == float("inf"):
        return content, None

    if len(content) <= effective_threshold:
        return content, None

    ref_key = _safe_ref_key(tool_use_id)
    preview, has_more = generate_preview(content, max_chars=config.preview_size)

    if variables is not None:
        try:
            variables[ref_key] = {
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "content": content,
                "size": len(content),
                "created_at": _now_iso(),
            }
            logger.info(
                "已持久化大工具结果: %s (%s, %d 字符 -> variables[%s])",
                tool_name, tool_use_id, len(content), ref_key,
            )
            return _build_persisted_message(preview, has_more, len(content), ref_key, tool_name), ref_key
        except Exception as exc:
            logger.warning("持久化工具结果失败 %s: %s", tool_use_id, exc)

    # 降级：内联截断（不丢失，但不可取回全量）
    logger.info(
        "内联截断大工具结果: %s (%d 字符，无 variables 可持久化)",
        tool_name, len(content),
    )
    return (
        f"{preview}\n\n[截断：工具响应为 {len(content):,} 字符。"
        f"全量结果未能持久化。]",
        None,
    )


def enforce_turn_budget(
    tool_messages: list[dict],
    *,
    variables: Optional[dict] = None,
    config: BudgetConfig = DEFAULT_BUDGET,
) -> list[dict]:
    """Layer 3：对本 turn 所有工具结果执行聚合预算。

    若总字符数超预算，把最大的非持久化结果先持久化（写入 variables），
    直到总量达标。已持久化的结果跳过。

    原地修改列表并返回。
    """
    candidates = []
    total_size = 0
    for i, msg in enumerate(tool_messages):
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        size = len(content)
        total_size += size
        if PERSISTED_OUTPUT_TAG not in content:
            candidates.append((i, size))

    if total_size <= config.turn_budget:
        return tool_messages

    candidates.sort(key=lambda x: x[1], reverse=True)

    for idx, size in candidates:
        if total_size <= config.turn_budget:
            break
        msg = tool_messages[idx]
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        tool_use_id = msg.get("tool_call_id", f"budget_{idx}")
        tool_name = msg.get("name", "__budget_enforcement__")

        replacement, _ref = maybe_persist_tool_result(
            content=content,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            variables=variables,
            config=config,
            threshold=0,  # 强制持久化
        )
        if replacement != content:
            total_size -= size
            total_size += len(replacement)
            tool_messages[idx]["content"] = replacement
            logger.info(
                "预算执行：已持久化工具结果 %s (%d 字符)",
                tool_use_id, size,
            )

    return tool_messages


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return default
    return iv if iv > 0 else default


def _now_iso() -> str:
    from app.core.timezone import beijing_now_iso
    return beijing_now_iso()


__all__ = [
    "DEFAULT_BUDGET",
    "BudgetConfig",
    "ToolOutputLimits",
    "budget_for_context_window",
    "truncate_output",
    "truncate_lines",
    "generate_preview",
    "maybe_persist_tool_result",
    "enforce_turn_budget",
    "PERSISTED_OUTPUT_TAG",
    "PERSISTED_OUTPUT_CLOSING_TAG",
]
