"""工单实例 API。

核心能力：
- 工单发起：校验发起人属于流程的发起分组，字段按首节点定义校验，发起即对流程模板做快照
- 工单列表：待我处理（当前节点分组=我的分组）/ 我发起 / 我处理过 / 全部，多维筛选分页
- 工单详情：完整节点处理时间线（上游节点字段对处理人只读展示）
- 工单流转：当前节点分组内任一成员提交即代表全组（先到先得），字段按当前节点定义校验，
  流向必须在路由白名单内，未显式选择时按条件路由自动建议
- 工单取消：仅发起人或 admin
- 附件：通用上传 + query token 下载（截图等 file 类型字段）

权限：``ticket:view`` 可查看，``ticket:edit`` 可发起/流转，取消=发起人或 admin。
所有动作写审计日志，流转成功后通知下一分组。
"""
import logging
import os
import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.notification_dispatch import dispatch_notification
from app.core.sanitizer import sanitize_text
from app.core.ticket_enrichment import build_ticket_enrichment
from app.core.ticket_sla import evaluate_ticket_sla, get_sla_config
from app.core.ticket_flow import (
    get_node,
    get_start_node,
    is_end_node,
    suggest_route,
    validate_field_values,
)
from datetime import timedelta

from app.core.timezone import beijing_now
from app.database import get_db
from app.dependencies import get_current_user, is_admin, require_permission
from app.models.ticket import Ticket, TicketFlow, TicketGroup, TicketGroupMember, TicketNodeRecord
from app.models.user import User
from app.schemas.ticket import TicketAdvance, TicketCancel, TicketCreate
from app.workflow.audit import write_audit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tickets",
    tags=["tickets"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("ticket", "view")),
    ],
)

# ============ 常量与辅助 ============

# 状态中文
STATUS_LABELS = {"processing": "进行中", "completed": "已完成", "cancelled": "已取消"}
PRIORITY_LABELS = {"low": "低", "medium": "中", "high": "高", "critical": "紧急"}

# 附件：扩展名白名单（与反馈附件一致，拒绝一切可执行文件）；元组保序用于报错提示
ALLOWED_ATTACHMENT_EXTENSIONS = (
    "png", "jpg", "jpeg", "gif", "webp", "bmp",
    "pdf", "txt", "log", "md", "csv", "zip",
)
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "uploads",
    "tickets",
    "pending",
)

# 仅去除控制字符（不做 HTML 转义：React 文本渲染自动转义，URL 字段不能被转义）
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_value(v):
    if isinstance(v, str):
        return _CONTROL_CHARS.sub("", v)
    return v


def _clean_field_values(values: dict) -> dict:
    return {k: _clean_value(v) for k, v in (values or {}).items()}


def _my_group_ids(db: Session, user_id: int) -> list[int]:
    """当前用户所属的工单分组 ID 列表。"""
    return [
        gid for (gid,) in db.query(TicketGroupMember.group_id)
        .filter(TicketGroupMember.user_id == user_id)
        .all()
    ]


def _get_ticket_or_404(db: Session, ticket_id: int) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    return ticket


def _group_name_map(db: Session, group_ids: set[int]) -> dict[int, str]:
    """批量取分组名。"""
    ids = [g for g in group_ids if g]
    if not ids:
        return {}
    rows = db.query(TicketGroup.id, TicketGroup.name).filter(TicketGroup.id.in_(ids)).all()
    return {gid: name for gid, name in rows}


def _gen_ticket_no(db: Session) -> str:
    """生成工单编号：TK-YYYYMMDD-XXXX（当日序号，4 位补零）。"""
    today = beijing_now().strftime("%Y%m%d")
    prefix = f"TK-{today}-"
    count = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.ticket_no.like(prefix + "%"))
        .scalar()
        or 0
    )
    return f"{prefix}{count + 1:04d}"


def _resolve_route(
    routes: list,
    field_values: dict,
    explicit_route: str | None,
    node_label: str,
) -> str:
    """解析流转去向：显式选择 → 校验白名单；未选择 → 条件建议/默认路由。"""
    whitelist = {r.get("to") for r in routes or [] if isinstance(r, dict) and r.get("to")}
    if not whitelist:
        raise HTTPException(status_code=400, detail=f"节点「{node_label}」未配置流转路由")
    if explicit_route:
        if explicit_route not in whitelist:
            raise HTTPException(
                status_code=400,
                detail=f"流转去向 {explicit_route} 不在节点「{node_label}」的路由白名单内",
            )
        return explicit_route
    suggested, default = suggest_route(routes, field_values)
    target = suggested or default
    if not target:
        raise HTTPException(status_code=400, detail=f"节点「{node_label}」无可用流转路由")
    return target


def _notify_next_group(db: Session, ticket: Ticket, node_name: str, group_id: int | None) -> None:
    """流转成功后通知下一分组（事件类型 ticket，通知规则未配置时回退广播）。"""
    if not group_id:
        return
    group = db.query(TicketGroup).filter(TicketGroup.id == group_id).first()
    group_label = group.name if group else f"分组{group_id}"
    dispatch_notification(
        db,
        event_type="ticket",
        title=f"工单待处理：{ticket.ticket_no}",
        content=(
            f"工单「{ticket.title}」已流转至节点「{node_name}」，"
            f"请【{group_label}】跟进处理（组内任一成员提交即代表全组）"
        ),
        related_type="ticket",
        related_id=ticket.id,
        created_by="system",
    )


def _ticket_list_item(ticket: Ticket, group_names: dict[int, str]) -> dict:
    data = ticket.to_dict()
    # 列表剔除自动研判大 JSON（详情接口返回，保持列表响应轻量）
    data.pop("enrichment_data", None)
    data["status_label"] = STATUS_LABELS.get(ticket.status, ticket.status)
    data["priority_label"] = PRIORITY_LABELS.get(ticket.priority, ticket.priority)
    data["current_group_name"] = group_names.get(ticket.current_group_id) if ticket.current_group_id else None
    return data


def _ticket_detail(db: Session, ticket: Ticket, current_user: User) -> dict:
    """工单详情：快照 + 节点时间线 + 当前用户操作权限。"""
    snapshot = ticket.flow_snapshot if isinstance(ticket.flow_snapshot, dict) else {}
    records = (
        db.query(TicketNodeRecord)
        .filter(TicketNodeRecord.ticket_id == ticket.id)
        .order_by(TicketNodeRecord.id.asc())
        .all()
    )
    # 分组名映射（快照节点 + 当前节点涉及的分组）
    group_ids: set[int] = set()
    for n in snapshot.get("nodes") or []:
        if isinstance(n, dict) and n.get("group_id"):
            group_ids.add(int(n["group_id"]))
    if ticket.current_group_id:
        group_ids.add(ticket.current_group_id)
    group_names = _group_name_map(db, group_ids)

    current_node = get_node(snapshot, ticket.current_node_key) if ticket.current_node_key else None
    my_groups = set(_my_group_ids(db, current_user.id))
    admin = is_admin(current_user, db)

    data = _ticket_list_item(ticket, group_names)
    data.update({
        "flow_snapshot": snapshot,
        "records": [r.to_dict() for r in records],
        # 自动研判结果随详情返回（列表已剔除）：资产匹配 + 威胁情报
        "enrichment_data": ticket.enrichment_data,
        "group_names": {str(k): v for k, v in group_names.items()},
        "current_node": current_node,
        "can_handle": (
            ticket.status == "processing"
            and bool(current_node)
            and (admin or (current_node.get("group_id") in my_groups))
        ),
        "can_cancel": (
            ticket.status == "processing"
            and (admin or ticket.created_by_id == current_user.id)
        ),
    })
    return data


# ============ 发起可用流程 ============

@router.get("/flows/options")
def flow_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """发起工单可选的流程模板列表（已发布且启用），含首节点表单定义与发起权限标记。"""
    flows = (
        db.query(TicketFlow)
        .filter(TicketFlow.enabled.is_(True), TicketFlow.is_draft.is_(False))
        .order_by(TicketFlow.id.desc())
        .all()
    )
    my_groups = set(_my_group_ids(db, current_user.id))
    admin = is_admin(current_user, db)
    items = []
    for f in flows:
        nodes = f.nodes if isinstance(f.nodes, dict) else {}
        start_groups = set(nodes.get("start_groups") or [])
        start_node = get_start_node(nodes)
        if not start_node:
            continue
        items.append({
            "id": f.id,
            "name": f.name,
            "description": f.description,
            "version": f.version,
            "node_count": len(nodes.get("nodes") or []),
            "start_groups": sorted(start_groups),
            "first_node": {
                "key": start_node.get("key"),
                "name": start_node.get("name"),
                "fields": start_node.get("fields") or [],
                "routes": start_node.get("routes") or [],
            },
            "can_initiate": admin or bool(start_groups & my_groups),
        })
    return {"items": items}


# ============ 发起 ============

@router.post("", status_code=201)
def create_ticket(
    body: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ticket", "edit")),
) -> dict:
    """发起工单。

    - 仅流程模板「可发起分组」成员（或 admin）可发起
    - field_values 按首节点字段定义校验（必填/类型/枚举，拒绝未定义字段）
    - 发起时对流程模板做快照，后续模板修改不影响本工单
    - 关联告警（一键发起）写入 related_alert_id / related_alert_uuid
    """
    flow = db.query(TicketFlow).filter(TicketFlow.id == body.flow_id).first()
    if flow is None:
        raise HTTPException(status_code=404, detail="流程模板不存在")
    if not flow.enabled or flow.is_draft:
        raise HTTPException(status_code=400, detail="流程模板未发布或已停用，不能发起工单")

    nodes_json = flow.nodes if isinstance(flow.nodes, dict) else {}
    start_node = get_start_node(nodes_json)
    if not start_node:
        raise HTTPException(status_code=400, detail="流程模板缺少处理节点")

    # 发起权限：admin 或属于发起分组
    admin = is_admin(current_user, db)
    my_groups = set(_my_group_ids(db, current_user.id))
    start_groups = set(nodes_json.get("start_groups") or [])
    if not admin and not (start_groups & my_groups):
        raise HTTPException(status_code=403, detail="您不属于该流程的可发起分组")

    # 字段校验
    values = _clean_field_values(body.field_values)
    errors = validate_field_values(start_node.get("fields") or [], values)
    if errors:
        raise HTTPException(status_code=422, detail="；".join(errors))

    # 路由解析
    start_label = start_node.get("name") or start_node.get("key")
    route_to = _resolve_route(start_node.get("routes") or [], values, body.route_to, start_label)
    target = get_node(nodes_json, route_to)
    if target is None:
        raise HTTPException(status_code=400, detail=f"流转目标节点 {route_to} 不存在")

    # 快照
    snapshot = {
        "flow_id": flow.id,
        "flow_name": flow.name,
        "version": flow.version,
        "start_groups": list(start_groups),
        "nodes": nodes_json.get("nodes") or [],
    }

    end = is_end_node(target)
    # 自动研判：对 src_ip/dst_ip 做资产匹配 + 威胁情报查询（失败不阻塞发起）
    try:
        enrichment = build_ticket_enrichment(
            db, start_node.get("fields") or [], values
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("工单自动研判失败（忽略，不阻塞发起）: %s", exc)
        enrichment = None
    ticket = Ticket(
        ticket_no=_gen_ticket_no(db),
        title=sanitize_text(body.title).strip(),
        flow_id=flow.id,
        flow_name=flow.name,
        flow_snapshot=snapshot,
        status="completed" if end else "processing",
        current_node_key=route_to,
        current_node_name=target.get("name") or route_to,
        current_group_id=None if end else target.get("group_id"),
        created_by_id=current_user.id,
        created_by_name=current_user.display_name or current_user.username,
        priority=body.priority,
        related_alert_id=body.related_alert_id,
        related_alert_uuid=body.related_alert_uuid,
        closed_at=beijing_now() if end else None,
        # 节点停留计时起点（超时提醒按 arrived_at 计算停留时长）
        arrived_at=None if end else beijing_now(),
        # 发起时自动研判结果（资产匹配 + 威胁情报），随工单流转只读展示
        enrichment_data=enrichment,
    )
    db.add(ticket)
    db.flush()
    db.add(TicketNodeRecord(
        ticket_id=ticket.id,
        node_key=start_node.get("key") or "",
        node_name=start_node.get("name") or "",
        group_id=start_node.get("group_id"),
        handler_id=current_user.id,
        handler_name=current_user.display_name or current_user.username,
        action="create",
        field_values=values,
        route_to=route_to,
        comment=sanitize_text(body.comment) if body.comment else None,
    ))
    if not end:
        _notify_next_group(db, ticket, target.get("name") or route_to, target.get("group_id"))
    db.commit()
    db.refresh(ticket)
    write_audit(
        db, action="ticket_create", resource_type="ticket", resource_id=ticket.id,
        detail={
            "ticket_no": ticket.ticket_no, "flow": flow.name,
            "route_to": route_to, "related_alert_id": body.related_alert_id,
        },
        operator=current_user.username, user_id=current_user.id,
    )
    logger.info("发起工单: id=%s no=%s flow=%s, operator=%s",
                ticket.id, ticket.ticket_no, flow.name, current_user.username)
    return _ticket_detail(db, ticket, current_user)


# ============ 列表 ============

@router.get("")
def list_tickets(
    view: str = Query(default="my_pending", pattern="^(my_pending|created|handled|all)$"),
    status: str | None = Query(default=None, pattern="^(processing|completed|cancelled)$"),
    flow_id: int | None = Query(default=None),
    priority: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
    archived: str = Query(default="exclude", pattern="^(exclude|only|include)$"),
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """工单列表：待我处理 / 我发起 / 我处理过 / 全部 + 状态/流程/优先级/关键词筛选。

    ``archived``：exclude=不含归档（默认）/ only=仅归档 / include=全部。
    """
    query = db.query(Ticket)

    if view == "my_pending":
        my_groups = _my_group_ids(db, current_user.id)
        if not my_groups:
            return {"items": [], "total": 0, "page": page, "size": size, "pages": 0}
        query = query.filter(
            Ticket.status == "processing",
            Ticket.current_group_id.in_(my_groups),
        )
    elif view == "created":
        query = query.filter(Ticket.created_by_id == current_user.id)
    elif view == "handled":
        handled_ids = (
            db.query(TicketNodeRecord.ticket_id)
            .filter(TicketNodeRecord.handler_id == current_user.id)
            .distinct()
            .subquery()
        )
        query = query.filter(Ticket.id.in_(handled_ids))

    # 归档过滤（应用于所有视图）
    if archived == "only":
        query = query.filter(Ticket.archived.is_(True))
    elif archived != "include":
        query = query.filter(Ticket.archived.is_(False))

    if status:
        query = query.filter(Ticket.status == status)
    if flow_id:
        query = query.filter(Ticket.flow_id == flow_id)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if q:
        kw = f"%{q.strip()}%"
        query = query.filter(or_(Ticket.ticket_no.like(kw), Ticket.title.like(kw)))

    query = query.order_by(Ticket.id.desc())
    total = query.count()
    tickets = query.offset((page - 1) * size).limit(size).all()
    group_names = _group_name_map(db, {t.current_group_id for t in tickets if t.current_group_id})
    return {
        "items": [_ticket_list_item(t, group_names) for t in tickets],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size if total > 0 else 0,
    }


# ============ 监控大屏聚合 ============

@router.get("/monitor")
def ticket_monitor_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ticket_monitor", "view")),
):
    """工单监控大屏聚合数据（KPI / 趋势 / 分布 / SLA / 分组效能 / 流转节点 / 最新工单）。

    数据均来自真实工单（排除归档），按大屏七个分区一次返回，前端 60s 轮询。
    需要独立权限 ticket_monitor:view（叠加 router 级 ticket:view）。
    注意：本路由必须注册在 ``GET /{ticket_id}`` 之前，避免 "monitor" 被路径参数吞掉。
    """
    now = beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    tickets = [t for t in db.query(Ticket).all() if not t.archived]
    records = (
        db.query(TicketNodeRecord)
        .order_by(TicketNodeRecord.ticket_id, TicketNodeRecord.created_at)
        .all()
    )
    by_ticket: dict[int, list] = {}
    first_record: dict[int, TicketNodeRecord] = {}
    for r in records:
        by_ticket.setdefault(r.ticket_id, []).append(r)
        if r.action == "create" and r.ticket_id not in first_record:
            first_record[r.ticket_id] = r

    processing = [t for t in tickets if t.status == "processing"]
    completed = [t for t in tickets if t.status == "completed"]
    cancelled = [t for t in tickets if t.status == "cancelled"]
    finished = [t for t in tickets if t.closed_at is not None]

    # —— SLA 目标口径评估（按优先级目标：响应=发起→首次提交，解决=创建→关闭）——
    sla_config = get_sla_config(db)
    sla_eval: dict[int, dict] = {
        t.id: evaluate_ticket_sla(t, by_ticket.get(t.id, []), now, sla_config)
        for t in tickets
    }

    # —— KPI：今日活跃（处理中）= 今日有提交流转且仍在进行中 ——
    today_submit_ids = {
        r.ticket_id
        for r in records
        if r.action == "submit" and r.created_at and r.created_at >= today_start
    }
    active_now = [t for t in processing if t.id in today_submit_ids]
    timeout_warn = [t for t in processing if sla_eval[t.id]["timeout"]]
    kpi = {
        "total": len(tickets),
        "today_new": sum(1 for t in tickets if t.created_at and t.created_at >= today_start),
        "today_closed": sum(1 for t in finished if t.closed_at >= today_start),
        "pending": len(processing),
        "processing_active": len(active_now),
        "completed": len(completed),
        "cancelled": len(cancelled),
        "timeout_warning": len(timeout_warn),
    }

    # —— 趋势：24h 按小时 / 7 天、30 天按天（新增 vs 关闭）——
    def _trend_by_hour(n_hours: int) -> list[dict]:
        cur = now.replace(minute=0, second=0, microsecond=0)
        starts = [cur - timedelta(hours=i) for i in range(n_hours - 1, -1, -1)]
        return [
            {
                "label": s.strftime("%H:%M"),
                "new": sum(1 for t in tickets if t.created_at and s <= t.created_at < s + timedelta(hours=1)),
                "closed": sum(1 for t in finished if s <= t.closed_at < s + timedelta(hours=1)),
            }
            for s in starts
        ]

    def _trend_by_day(n_days: int) -> list[dict]:
        starts = [today_start - timedelta(days=i) for i in range(n_days - 1, -1, -1)]
        return [
            {
                "label": s.strftime("%m-%d"),
                "new": sum(1 for t in tickets if t.created_at and s <= t.created_at < s + timedelta(days=1)),
                "closed": sum(1 for t in finished if s <= t.closed_at < s + timedelta(days=1)),
            }
            for s in starts
        ]

    trend = {"hours24": _trend_by_hour(24), "days7": _trend_by_day(7), "days30": _trend_by_day(30)}

    # —— 分布：优先级 / 来源平台 / 事件类型 + 严重度×状态堆叠 ——
    def _count_by(items, key_fn):
        m: dict = {}
        for it in items:
            k = key_fn(it)
            if k:
                m[k] = m.get(k, 0) + 1
        return [{"name": k, "value": v} for k, v in sorted(m.items(), key=lambda x: -x[1])]

    priority_dist = _count_by(tickets, lambda t: t.priority)
    platform_dist = _count_by(
        tickets,
        lambda t: (first_record.get(t.id).field_values or {}).get("alert_platform")
        if first_record.get(t.id)
        else None,
    )
    type_dist = _count_by(
        tickets,
        lambda t: (first_record.get(t.id).field_values or {}).get("alert_type")
        if first_record.get(t.id)
        else None,
    )
    severity_status = []
    for p in ("critical", "high", "medium", "low"):
        row = {"name": PRIORITY_LABELS.get(p, p), "processing": 0, "completed": 0, "cancelled": 0}
        for t in tickets:
            if t.priority == p:
                row[t.status] = row.get(t.status, 0) + 1
        severity_status.append(row)

    # —— SLA：按优先级目标统计（平均响应/解决 + 达标率/超时率 + 细分计数 + 目标值） ——
    in_scope = [t for t in tickets if sla_eval[t.id]["has_target"]]
    resp_minutes = [sla_eval[t.id]["response_minutes"] for t in in_scope if sla_eval[t.id]["response_minutes"] is not None]
    resolve_minutes = [sla_eval[t.id]["resolve_minutes"] for t in in_scope if sla_eval[t.id]["resolve_minutes"] is not None]
    sla_timeout = [t for t in in_scope if sla_eval[t.id]["timeout"]]

    def _avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    completed_in_scope = [t for t in in_scope if t.status == "completed"]
    on_time = [t for t in completed_in_scope if not sla_eval[t.id]["timeout"]]
    sla = {
        "avg_response_minutes": _avg(resp_minutes),
        "avg_resolve_minutes": _avg(resolve_minutes),
        # 超时率 = SLA 超时工单 / 纳入目标统计的工单
        "timeout_rate": round(len(sla_timeout) / len(in_scope) * 100, 1) if in_scope else 0,
        # 达标率 = 已完结工单中未超目标的占比
        "on_time_rate": round(len(on_time) / len(completed_in_scope) * 100, 1) if completed_in_scope else None,
        "responded_count": len(resp_minutes),
        "resolved_count": len(resolve_minutes),
        "timeout_count": len(sla_timeout),
        "response_overdue_count": sum(1 for t in in_scope if sla_eval[t.id]["response_breach"]),
        "resolve_overdue_count": sum(1 for t in in_scope if sla_eval[t.id]["resolve_breach"]),
        "in_scope_count": len(in_scope),
        "targets": sla_config,
    }

    # —— 分组效能：处理量（提交流转）与当前待办 ——
    group_map = {g.id: g.name for g in db.query(TicketGroup).all()}
    handled_count: dict[int, int] = {}
    for r in records:
        if r.action == "submit" and r.group_id:
            handled_count[r.group_id] = handled_count.get(r.group_id, 0) + 1
    pending_count: dict[int, int] = {}
    for t in processing:
        if t.current_group_id:
            pending_count[t.current_group_id] = pending_count.get(t.current_group_id, 0) + 1
    groups_stats = [
        {
            "name": group_map.get(gid, f"分组{gid}"),
            "handled": handled_count.get(gid, 0),
            "pending": pending_count.get(gid, 0),
        }
        for gid in sorted(set(handled_count) | set(pending_count))
    ]

    # —— 处置状态流转：进行中工单最多的流程节点序列 + 各节点当前数量 ——
    flow_count: dict[int, int] = {}
    for t in processing:
        flow_count[t.flow_id] = flow_count.get(t.flow_id, 0) + 1
    flow_nodes: list[dict] = []
    if flow_count:
        main_flow_id = max(flow_count, key=flow_count.get)
        snap = next(
            (t.flow_snapshot for t in processing if t.flow_id == main_flow_id), {}
        ) or {}
    else:
        latest_flow = db.query(TicketFlow).order_by(TicketFlow.id.desc()).first()
        snap = (latest_flow.nodes if latest_flow else None) or {}
        main_flow_id = latest_flow.id if latest_flow else None
    node_counts: dict[str, int] = {}
    for t in processing:
        if t.flow_id == main_flow_id and t.current_node_key:
            node_counts[t.current_node_key] = node_counts.get(t.current_node_key, 0) + 1
    if snap:
        for n in snap.get("nodes", []):
            if n.get("type") == "end":
                continue
            flow_nodes.append({
                "key": n.get("key"),
                "name": n.get("name"),
                "group": group_map.get(n.get("group_id"), ""),
                "current": node_counts.get(n.get("key"), 0),
            })
    flow_nodes.append({
        "key": "_finished",
        "name": "已完结",
        "group": "",
        "current": len(completed) + len(cancelled),
    })

    # —— 最新工单（中央实时列表 + 底部跑马灯）——
    latest = []
    for t in sorted(tickets, key=lambda x: x.created_at or now, reverse=True)[:20]:
        latest.append({
            "id": t.id,
            "ticket_no": t.ticket_no,
            "title": t.title,
            "priority": t.priority,
            "priority_label": PRIORITY_LABELS.get(t.priority, t.priority),
            "status": t.status,
            "status_label": STATUS_LABELS.get(t.status, t.status),
            "current_node_name": t.current_node_name or t.current_node_key,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "timeout": sla_eval[t.id]["timeout"],
            "remind_count": t.remind_count or 0,
        })

    return {
        "kpi": kpi,
        "trend": trend,
        "dist": {"priority": priority_dist, "platform": platform_dist, "type": type_dist},
        "severity_status": severity_status,
        "sla": sla,
        "groups": groups_stats,
        "flow_nodes": flow_nodes,
        "latest": latest,
        "generated_at": now.isoformat(),
    }


# ============ 详情 ============

@router.get("/{ticket_id}")
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """工单详情：处理时间线 + 当前节点操作表单 + 权限上下文。"""
    ticket = _get_ticket_or_404(db, ticket_id)
    return _ticket_detail(db, ticket, current_user)


# ============ 流转 ============

@router.post("/{ticket_id}/advance")
def advance_ticket(
    ticket_id: int,
    body: TicketAdvance,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ticket", "edit")),
) -> dict:
    """流转工单：当前节点分组内任一成员提交即代表全组（先到先得）。

    - field_values 按当前节点字段定义校验
    - route_to 必须在当前节点路由白名单内；未提供时按条件路由自动建议
    - 流向结束节点时工单完成
    """
    ticket = _get_ticket_or_404(db, ticket_id)
    if ticket.status != "processing":
        raise HTTPException(status_code=400, detail="工单已完结，不能再流转")

    snapshot = ticket.flow_snapshot if isinstance(ticket.flow_snapshot, dict) else {}
    current_node = get_node(snapshot, ticket.current_node_key) if ticket.current_node_key else None
    if not current_node:
        raise HTTPException(status_code=400, detail="当前节点定义缺失（快照损坏）")

    # 处理权限：admin 或属于当前节点分组
    admin = is_admin(current_user, db)
    my_groups = set(_my_group_ids(db, current_user.id))
    if not admin and current_node.get("group_id") not in my_groups:
        raise HTTPException(status_code=403, detail="您不属于当前节点的处理分组")

    # 字段校验
    values = _clean_field_values(body.field_values)
    errors = validate_field_values(current_node.get("fields") or [], values)
    if errors:
        raise HTTPException(status_code=422, detail="；".join(errors))

    # 路由解析
    node_label = current_node.get("name") or current_node.get("key")
    route_to = _resolve_route(current_node.get("routes") or [], values, body.route_to, node_label)
    target = get_node(snapshot, route_to)
    if target is None:
        raise HTTPException(status_code=400, detail=f"流转目标节点 {route_to} 不存在")

    db.add(TicketNodeRecord(
        ticket_id=ticket.id,
        node_key=current_node.get("key") or "",
        node_name=current_node.get("name") or "",
        group_id=current_node.get("group_id"),
        handler_id=current_user.id,
        handler_name=current_user.display_name or current_user.username,
        action="submit",
        field_values=values,
        route_to=route_to,
        comment=sanitize_text(body.comment) if body.comment else None,
    ))

    end = is_end_node(target)
    ticket.current_node_key = route_to
    ticket.current_node_name = target.get("name") or route_to
    ticket.current_group_id = None if end else target.get("group_id")
    # 节点停留计时重置：进入新节点重新计时，超时提醒进度清零
    ticket.arrived_at = None if end else beijing_now()
    ticket.first_reminded_at = None
    ticket.last_reminded_at = None
    ticket.remind_count = 0
    if end:
        ticket.status = "completed"
        ticket.closed_at = beijing_now()
    else:
        _notify_next_group(db, ticket, target.get("name") or route_to, target.get("group_id"))
    db.commit()
    db.refresh(ticket)
    write_audit(
        db, action="ticket_advance", resource_type="ticket", resource_id=ticket.id,
        detail={"ticket_no": ticket.ticket_no, "from": current_node.get("key"), "to": route_to,
                "status": ticket.status},
        operator=current_user.username, user_id=current_user.id,
    )
    logger.info("工单流转: id=%s no=%s %s → %s, operator=%s",
                ticket.id, ticket.ticket_no, current_node.get("key"), route_to, current_user.username)
    return _ticket_detail(db, ticket, current_user)


# ============ 取消 ============

@router.post("/{ticket_id}/cancel")
def cancel_ticket(
    ticket_id: int,
    body: TicketCancel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """取消工单：仅发起人或 admin，需填写取消原因。"""
    ticket = _get_ticket_or_404(db, ticket_id)
    admin = is_admin(current_user, db)
    if not admin and ticket.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅发起人或管理员可取消工单")
    if ticket.status != "processing":
        raise HTTPException(status_code=400, detail="工单已完结，不能取消")

    db.add(TicketNodeRecord(
        ticket_id=ticket.id,
        node_key=ticket.current_node_key or "",
        node_name=ticket.current_node_name or "",
        group_id=ticket.current_group_id,
        handler_id=current_user.id,
        handler_name=current_user.display_name or current_user.username,
        action="cancel",
        field_values={},
        comment=sanitize_text(body.comment) if body.comment else None,
    ))
    ticket.status = "cancelled"
    ticket.closed_at = beijing_now()
    db.commit()
    db.refresh(ticket)
    write_audit(
        db, action="ticket_cancel", resource_type="ticket", resource_id=ticket.id,
        detail={"ticket_no": ticket.ticket_no, "reason": body.comment},
        operator=current_user.username, user_id=current_user.id,
    )
    logger.info("取消工单: id=%s no=%s, operator=%s", ticket.id, ticket.ticket_no, current_user.username)
    return _ticket_detail(db, ticket, current_user)


# ============ 归档（软删除，仅完结工单） ============

@router.post("/{ticket_id}/archive")
def archive_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ticket", "delete")),
) -> dict:
    """归档工单（软删除）：仅已完成/已取消的工单可归档，归档后从默认列表隐藏。"""
    ticket = _get_ticket_or_404(db, ticket_id)
    if ticket.status not in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail="仅已完结（已完成/已取消）的工单可归档")
    if ticket.archived:
        raise HTTPException(status_code=400, detail="工单已处于归档状态")
    ticket.archived = True
    db.commit()
    db.refresh(ticket)
    write_audit(
        db, action="ticket_archive", resource_type="ticket", resource_id=ticket.id,
        detail={"ticket_no": ticket.ticket_no, "status": ticket.status},
        operator=current_user.username, user_id=current_user.id,
    )
    logger.info("归档工单: id=%s no=%s, operator=%s", ticket.id, ticket.ticket_no, current_user.username)
    return _ticket_detail(db, ticket, current_user)


@router.post("/{ticket_id}/unarchive")
def unarchive_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ticket", "delete")),
) -> dict:
    """取消归档：恢复工单在默认列表中的展示。"""
    ticket = _get_ticket_or_404(db, ticket_id)
    if not ticket.archived:
        raise HTTPException(status_code=400, detail="工单未处于归档状态")
    ticket.archived = False
    db.commit()
    db.refresh(ticket)
    write_audit(
        db, action="ticket_unarchive", resource_type="ticket", resource_id=ticket.id,
        detail={"ticket_no": ticket.ticket_no, "status": ticket.status},
        operator=current_user.username, user_id=current_user.id,
    )
    logger.info("取消归档工单: id=%s no=%s, operator=%s", ticket.id, ticket.ticket_no, current_user.username)
    return _ticket_detail(db, ticket, current_user)


# ============ 附件（上传走主 router，下载走 query token router） ============

@router.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ticket", "edit")),
) -> dict:
    """上传工单附件（file 类型字段引用其 URL；发起/流转前上传，暂存 pending 目录）。

    - 扩展名白名单：png/jpg/jpeg/gif/webp/bmp/pdf/txt/log/md/csv/zip
    - 单文件不超过 10MB
    """
    original_name = file.filename or "untitled"
    ext = os.path.splitext(original_name)[1].lower().lstrip(".")
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件类型，仅支持：" + "、".join(ALLOWED_ATTACHMENT_EXTENSIONS))
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(file_bytes) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制（最大 10MB）")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved_filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    with open(os.path.join(UPLOAD_DIR, saved_filename), "wb") as f:
        f.write(file_bytes)
    write_audit(
        db, action="ticket_attachment_upload", resource_type="ticket_attachment",
        resource_id=saved_filename, detail={"name": original_name, "size": len(file_bytes)},
        operator=current_user.username, user_id=current_user.id,
    )
    logger.info("工单附件上传: file=%s size=%d, operator=%s",
                saved_filename, len(file_bytes), current_user.username)
    return {
        "name": sanitize_text(original_name),
        "size": len(file_bytes),
        "url": f"/api/v1/tickets/attachments/{saved_filename}",
    }


def _query_token_auth(request: Request, db: Session = Depends(get_db)) -> User:
    """附件访问专用鉴权：优先 query token，其次标准 Authorization 头。"""
    token = request.query_params.get("token")
    if token:
        return get_current_user(authorization=f"Bearer {token}", db=db)
    return get_current_user(authorization=request.headers.get("authorization"), db=db)


download_router = APIRouter(prefix="/tickets", tags=["tickets"])


@download_router.get("/attachments/{filename}")
def download_attachment(
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(_query_token_auth),
) -> FileResponse:
    """下载/预览工单附件（图片内联显示，做路径穿越校验）。

    支持 ``?token=<jwt>`` 认证，供前端 <img> 直接加载。
    """
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法的文件名")
    file_path = os.path.abspath(os.path.join(UPLOAD_DIR, filename))
    if not file_path.startswith(os.path.abspath(UPLOAD_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="非法的文件名")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="附件不存在")

    ext = os.path.splitext(filename)[1].lower()
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    if ext in image_exts:
        return FileResponse(file_path, filename=filename, content_disposition_type="inline")
    return FileResponse(file_path, filename=filename)
