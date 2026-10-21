"""工单节点停留超时扫描任务（阶段2）。

由 Celery beat 每 5 分钟触发一次（见 celery_app.py 的 beat_schedule）：
- 遍历所有进行中工单，按快照中当前节点的 ``timeout_minutes`` 配置判断是否停留超时
- 超时 → 通过通知中心提醒当前处理分组（event_type=ticket，未配置规则时回退广播）
- 重复提醒：节点 ``remind_interval_minutes`` > 0 时，超时期间每 N 分钟重复提醒；
  未配置或 0 则仅首次提醒
- 幂等与重置：first/last_reminded_at 与 remind_count 记录提醒进度；
  发起/流转时由 tickets.py 重置 arrived_at 与提醒进度

每个工单独立提交，单个工单提醒失败不影响其余扫描。
"""
import logging
from typing import Optional

from app.core.celery_app import celery_app
from app.core.timezone import beijing_now
from app.database import SessionLocal

logger = logging.getLogger(__name__)


def _node_timeout_config(snapshot, node_key: Optional[str]) -> tuple[Optional[int], int]:
    """从流程快照取当前节点的超时配置。

    Returns:
        (timeout_minutes, remind_interval_minutes)；节点未配置或值非法时返回 (None, 0)。
    """
    if not node_key or not isinstance(snapshot, dict):
        return None, 0
    for n in snapshot.get("nodes") or []:
        if not isinstance(n, dict) or n.get("key") != node_key or n.get("type") == "end":
            continue
        tm = n.get("timeout_minutes")
        if isinstance(tm, bool) or not isinstance(tm, (int, float)) or tm <= 0:
            return None, 0
        rim = n.get("remind_interval_minutes")
        if isinstance(rim, bool) or not isinstance(rim, (int, float)) or rim < 0:
            rim = 0
        return int(tm), int(rim)
    return None, 0


@celery_app.task(name="scan_ticket_timeouts")
def scan_ticket_timeouts() -> dict:
    """扫描进行中工单的节点停留超时并推送提醒。"""
    from app.core.notification_dispatch import dispatch_notification
    from app.models.ticket import Ticket, TicketGroup

    db = SessionLocal()
    try:
        now = beijing_now()
        tickets = (
            db.query(Ticket)
            .filter(Ticket.status == "processing")
            .order_by(Ticket.id.asc())
            .all()
        )
        scanned = reminded = 0
        for ticket in tickets:
            scanned += 1
            try:
                timeout_min, interval_min = _node_timeout_config(
                    ticket.flow_snapshot, ticket.current_node_key
                )
                if not timeout_min or not ticket.arrived_at:
                    continue
                stay_minutes = (now - ticket.arrived_at).total_seconds() / 60
                if stay_minutes < timeout_min:
                    continue

                # 是否到达提醒时机：首次超时必提醒；此后按重复间隔（0 = 仅首次）
                if ticket.last_reminded_at is None:
                    due = True
                elif interval_min > 0:
                    due = (now - ticket.last_reminded_at).total_seconds() / 60 >= interval_min
                else:
                    due = False
                if not due:
                    continue

                group_label = f"分组{ticket.current_group_id}"
                if ticket.current_group_id:
                    group = (
                        db.query(TicketGroup)
                        .filter(TicketGroup.id == ticket.current_group_id)
                        .first()
                    )
                    if group:
                        group_label = group.name
                dispatch_notification(
                    db,
                    event_type="ticket",
                    title=f"工单超时提醒：{ticket.ticket_no}",
                    content=(
                        f"工单「{ticket.title}」在节点「{ticket.current_node_name}」"
                        f"已停留 {int(stay_minutes)} 分钟，超过 {timeout_min} 分钟阈值，"
                        f"请【{group_label}】尽快跟进处理"
                    ),
                    related_type="ticket",
                    related_id=ticket.id,
                    created_by="system",
                )
                ticket.first_reminded_at = ticket.first_reminded_at or now
                ticket.last_reminded_at = now
                ticket.remind_count = (ticket.remind_count or 0) + 1
                db.commit()
                reminded += 1
                logger.info(
                    "工单超时提醒: id=%s no=%s node=%s stay=%.0fmin remind_count=%s",
                    ticket.id, ticket.ticket_no, ticket.current_node_key,
                    stay_minutes, ticket.remind_count,
                )
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception("工单超时提醒失败: id=%s", ticket.id)
        if scanned:
            logger.info("工单超时扫描完成: scanned=%d reminded=%d", scanned, reminded)
        return {"scanned": scanned, "reminded": reminded}
    finally:
        db.close()
