"""工单 SLA 目标配置与时效评估。

配置存储：SystemConfig 键 ``ticket.sla_config``，值为 JSON 字符串::

    {"critical": {"response": 30, "resolve": 240}, "high": {...}, ...}

- key 为优先级（critical/high/medium/low），response/resolve 为目标分钟数（正整数）
- 值为 null 表示该优先级对应维度不设目标（该维度不参与统计）

时效口径：
- 响应时长 = 发起（首条 create 记录时间）→ 首次节点提交（首条 submit 记录）
- 解决时长 = 工单创建 → 完成关闭（仅 completed）
- 响应超时：已响应 → 实际响应 > 目标；未响应 →（now 或取消时间 − 发起时间）> 目标
- 解决超时：completed → 实际解决 > 目标；processing →（now − 创建时间）> 目标
- cancelled 仅判响应超时（取消不计解决），completed/cancelled 不做实时超时判断
"""
import json
import logging

from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

SLA_CONFIG_KEY = "ticket.sla_config"

PRIORITIES = ("critical", "high", "medium", "low")

# 默认 SLA 目标（分钟）：响应 = 发起→首次提交；解决 = 创建→关闭
DEFAULT_SLA_CONFIG: dict[str, dict] = {
    "critical": {"response": 30, "resolve": 240},
    "high": {"response": 60, "resolve": 480},
    "medium": {"response": 240, "resolve": 1440},
    "low": {"response": 480, "resolve": 2880},
}


def normalize_sla_config(raw: dict | None) -> tuple[dict, list[str]]:
    """校验并规范化 SLA 配置。

    返回 (规范化配置, 错误列表)。规范化结果固定包含 4 个优先级，
    每个维度为正整数或 None（不限）。未知优先级忽略。
    """
    errors: list[str] = []
    result: dict[str, dict] = {}
    raw = raw or {}
    for p in PRIORITIES:
        item = raw.get(p)
        row: dict = {"response": None, "resolve": None}
        if item is not None:
            if not isinstance(item, dict):
                errors.append(f"{p} 配置格式错误（需为对象）")
                item = {}
            for dim in ("response", "resolve"):
                v = item.get(dim)
                if v in (None, ""):
                    continue
                if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                    errors.append(f"{p} 的{'响应' if dim == 'response' else '解决'}时限需为正整数或留空")
                    continue
                row[dim] = v
        result[p] = row
    return result, errors


def get_sla_config(db: Session) -> dict:
    """读取 SLA 配置（键不存在或解析失败时回退默认值）。"""
    cfg = db.query(SystemConfig).filter(SystemConfig.key == SLA_CONFIG_KEY).first()
    if not cfg or not cfg.value:
        return {p: dict(v) for p, v in DEFAULT_SLA_CONFIG.items()}
    try:
        parsed, errors = normalize_sla_config(json.loads(cfg.value))
        if errors:
            raise ValueError(errors)
        return parsed
    except (ValueError, TypeError) as e:
        logger.warning("SLA 配置解析失败，使用默认值: %s", e)
        return {p: dict(v) for p, v in DEFAULT_SLA_CONFIG.items()}


def save_sla_config(db: Session, config: dict) -> dict:
    """保存 SLA 配置（config 须已通过 normalize_sla_config 校验）。"""
    normalized, _ = normalize_sla_config(config)
    payload = json.dumps(normalized, ensure_ascii=False)
    cfg = db.query(SystemConfig).filter(SystemConfig.key == SLA_CONFIG_KEY).first()
    if cfg:
        cfg.value = payload
    else:
        db.add(SystemConfig(
            key=SLA_CONFIG_KEY, value=payload,
            description="工单 SLA 目标（按优先级：响应/解决时限分钟数，null=不限）",
        ))
    db.commit()
    return normalized


def evaluate_ticket_sla(ticket, records, now, config: dict) -> dict:
    """评估单个工单的 SLA 时效。

    :param ticket: Ticket 工单
    :param records: 该工单的节点记录（按时间升序）
    :param now: 当前时间（datetime）
    :param config: get_sla_config 产出的配置
    :return: {response_minutes, resolve_minutes, response_breach, resolve_breach,
             timeout, has_target}
    """
    creates = [r for r in records if r.action == "create"]
    submits = [r for r in records if r.action == "submit"]

    response_minutes = None
    if creates and submits and creates[0].created_at and submits[0].created_at:
        response_minutes = (submits[0].created_at - creates[0].created_at).total_seconds() / 60

    resolve_minutes = None
    if ticket.status == "completed" and ticket.created_at and ticket.closed_at:
        resolve_minutes = (ticket.closed_at - ticket.created_at).total_seconds() / 60

    target = config.get(ticket.priority) or {}
    resp_target = target.get("response")
    res_target = target.get("resolve")

    # 发起时间基准：优先 create 记录时间，回退工单创建时间
    started_at = (creates[0].created_at if creates and creates[0].created_at else None) or ticket.created_at

    # —— 响应超时 ——
    response_breach = False
    if resp_target and started_at:
        if response_minutes is not None:
            response_breach = response_minutes > resp_target
        elif ticket.status == "processing":
            response_breach = (now - started_at).total_seconds() / 60 > resp_target
        elif ticket.status == "cancelled":
            # 从未提交即取消：取消时点距发起超过目标即响应超时
            end = ticket.closed_at or now
            response_breach = (end - started_at).total_seconds() / 60 > resp_target

    # —— 解决超时 ——
    resolve_breach = False
    if res_target and ticket.created_at:
        if ticket.status == "completed":
            resolve_breach = resolve_minutes is not None and resolve_minutes > res_target
        elif ticket.status == "processing":
            resolve_breach = (now - ticket.created_at).total_seconds() / 60 > res_target

    return {
        "response_minutes": response_minutes,
        "resolve_minutes": resolve_minutes,
        "response_breach": response_breach,
        "resolve_breach": resolve_breach,
        "timeout": bool(response_breach or resolve_breach),
        "has_target": bool(resp_target or res_target),
    }
