"""system prompt 组装器：技能加载 + 变量替换 + 分段注入。

集中处理 Agent 最终 system prompt 的组装，把"基础提示词 + 启用技能正文"
合并为一段完整的 system prompt，供 ``agents.py`` 的纯对话 / LangGraph
两条路径统一调用。

设计要点：
- ``render_variables`` 补齐 ``models/agent.py`` 注释中承诺但未实现的 ``{{key}}``
  变量替换能力。仅匹配 ``{{word}}``（字母/数字/下划线），避免误伤 JSON / 模板字面量。
- ``assemble_system_prompt`` 加载 ``agent.enabled_skills`` 中 ``enabled=True`` 的技能，
  按 ``priority`` 降序注入。技能被禁用或删除时自然 miss，无需显式清理悬挂引用。
- 技能正文同样做 ``{{key}}`` 替换，缺失变量保留原占位符并 warning（不阻断）。
- 总长度超过阈值时 warning（不阻断），便于发现 prompt 膨胀。
"""
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 仅匹配 {{word}}：字母/数字/下划线，避免误伤 JSON 大括号或 CSS 模板
_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# prompt 长度告警阈值（字符数）。超过则 warning，不阻断。
# 32000 字符约等于 8k~16k tokens（中英文混合），接近多数模型上下文上限的 1/4。
_PROMPT_LENGTH_WARN = 32000

# 默认 fallback prompt：当 agent.system_prompt 为空且无技能时使用
_DEFAULT_FALLBACK = "你是一个智能助手，请根据用户输入给出有帮助的回答。"


def render_variables(text: str | None, variables: dict[str, Any] | None) -> str:
    """把 ``{{key}}`` 替换为 ``variables`` 中的值。

    补齐 ``models/agent.py`` 注释承诺但全后端未实现的变量替换能力。

    Args:
        text: 原始文本，可为 None。
        variables: 变量字典，如 ``{"role": "SOC", "product_name": "SOAR平台"}``。

    Returns:
        替换后的文本。缺失变量保留原 ``{{key}}`` 占位符并 warning（不阻断）。
        text 为 None 时返回空字符串。
    """
    if not text:
        return ""
    if not variables:
        return text

    def _repl(match: re.Match) -> str:
        key = match.group(1)
        if key in variables:
            value = variables[key]
            # None 视为未设置，保留占位符
            if value is None:
                logger.warning("变量 %s 值为 None，保留占位符", key)
                return match.group(0)
            return str(value)
        # 缺失变量：保留原占位符 + warning（不阻断，便于排查）
        logger.warning("变量 %s 未提供，保留占位符 {{%s}}", key, key)
        return match.group(0)

    return _VAR_PATTERN.sub(_repl, text)


def _load_enabled_skills(db, skill_ids: list[int]) -> list:
    """加载启用中的技能列表。

    查询条件：
    - ``id IN skill_ids``：仅取 Agent 引用的技能
    - ``enabled = True``：禁用的技能立即从 prompt 移除（即时生效）
    - 按 ``priority`` 降序、``id`` 升序排序：priority 越大越靠前，同优先级按创建顺序

    Args:
        db: SQLAlchemy Session。
        skill_ids: Agent.enabled_skills 中的技能 id 列表。

    Returns:
        Skill 对象列表（已排序）。空列表或全部禁用/删除时返回 []。
    """
    if not skill_ids:
        return []
    from app.models.skill import Skill

    try:
        return (
            db.query(Skill)
            .filter(Skill.id.in_(skill_ids), Skill.enabled.is_(True))
            .order_by(Skill.priority.desc(), Skill.id.asc())
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        # 表未建 / 查询异常不应阻断 Agent 对话，降级为无技能
        logger.warning("加载技能失败（降级为无技能注入）: %s", exc)
        return []


def assemble_system_prompt(
    db,
    agent,
    fallback_prompt: str | None = None,
    allow_none: bool = False,
) -> str | None:
    """组装最终 system prompt：基础提示词 + 启用技能正文。

    组装规则：
    1. ``base`` = ``agent.system_prompt``
    2. 对 ``base`` 做 ``{{key}}`` 替换（用 ``agent.variables``）
    3. 加载 ``agent.enabled_skills`` 中 ``enabled=True`` 的技能，按 ``priority`` 降序
    4. 每个技能 ``content`` 做 ``{{key}}`` 替换，空内容跳过
    5. 分段标记包裹技能正文：
       ``=== 启用技能 ===`` / ``--- 技能: {name} ---`` / content /
       ``--- 技能: {name} 结束 ---`` / ``=== 启用技能结束 ===``
    6. ``base`` 为空但有技能：以技能段作为完整 prompt
    7. ``base`` 为空且无技能：
       - ``allow_none=True`` 时返回 ``None``（供 LangGraph 路径透传给 ``run_agent_decision``，
         由 ``decision.py`` 走默认安全专家提示词 + 决策 JSON 解析）
       - ``allow_none=False`` 时返回 ``fallback_prompt``（默认兜底文案），保证纯对话路径
         永远拿到非 None 的 system prompt
    8. 总长度 > 阈值时 ``logger.warning``（不阻断）

    Args:
        db: SQLAlchemy Session，用于加载技能。
        agent: Agent 模型实例。
        fallback_prompt: ``agent.system_prompt`` 为空且无技能且 ``allow_none=False`` 时的兜底提示词。
            为 None 时使用默认兜底文案。
        allow_none: 是否允许在「无 base 且无技能」时返回 None。
            纯对话路径应传 False（默认），LangGraph 决策路径应传 True。

    Returns:
        组装后的 system prompt 字符串；``allow_none=True`` 且无内容时可能返回 None。
    """
    # 1. 取 base prompt
    base = agent.system_prompt or ""

    # 2. 加载启用的技能
    skill_ids = list(agent.enabled_skills or [])
    skills = _load_enabled_skills(db, skill_ids)

    # 3. 处理 base 为空的情况
    if not base.strip():
        if skills:
            # 有技能但无 base：技能段作为完整 prompt（不拼 fallback）
            base = ""
        elif allow_none:
            # 无技能且无 base：LangGraph 路径透传 None，由 decision.py 走默认流程
            logger.info(
                "组装 system prompt: agent_id=%s, 无 base 且无技能，allow_none=True → 返回 None",
                getattr(agent, "id", None),
            )
            return None
        else:
            # 无技能且无 base：纯对话路径用 fallback
            base = fallback_prompt or _DEFAULT_FALLBACK
            # fallback 不做变量替换（它不含 {{key}}），直接返回
            return base

    # 4. 对 base 做变量替换
    variables = agent.variables or {}
    base = render_variables(base, variables)

    # 5. 无技能：返回替换后的 base
    if not skills:
        return base

    # 6. 组装技能段
    skill_blocks: list[str] = []
    for skill in skills:
        content = skill.content or ""
        if not content.strip():
            # 空内容跳过，避免注入空段
            logger.info("技能 %s 内容为空，跳过注入", skill.name)
            continue
        # 技能正文做变量替换
        rendered = render_variables(content, variables)
        block = f"--- 技能: {skill.name} ---\n{rendered}\n--- 技能: {skill.name} 结束 ---"
        skill_blocks.append(block)

    if not skill_blocks:
        # 所有技能内容都为空，退化为仅 base
        return base

    skill_section = "=== 启用技能 ===\n" + "\n\n".join(skill_blocks) + "\n=== 启用技能结束 ==="

    # 7. 拼接 base + 技能段
    if base.strip():
        final_prompt = f"{base}\n\n{skill_section}"
    else:
        # base 为空但有技能：技能段作为完整 prompt
        final_prompt = skill_section

    # 8. 长度告警（不阻断）
    length = len(final_prompt)
    if length > _PROMPT_LENGTH_WARN:
        logger.warning(
            "组装后的 system prompt 较长（%d 字符，阈值 %d），可能占用较多上下文；"
            "agent_id=%s, 技能数=%d",
            length,
            _PROMPT_LENGTH_WARN,
            getattr(agent, "id", None),
            len(skill_blocks),
        )

    logger.info(
        "组装 system prompt: agent_id=%s, base_len=%d, 技能数=%d, 总长度=%d",
        getattr(agent, "id", None),
        len(base),
        len(skill_blocks),
        length,
    )
    return final_prompt
