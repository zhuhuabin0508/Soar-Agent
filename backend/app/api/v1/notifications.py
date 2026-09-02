"""通知中心 API。

提供：
- 当前用户通知列表查询（含广播，分页 + 未读计数）
- 未读通知计数
- 单条 / 全部标记已读
- 单条通知删除
- 管理员发布公告（创建通知）
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import (
    NotificationCreate,
    NotificationListResponse,
    NotificationOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_permission("notification", "view"))],
)


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationListResponse:
    """获取当前用户的通知列表（含全员广播）。"""
    visibility = (Notification.user_id == current_user.id) | (Notification.user_id.is_(None))

    q = db.query(Notification).filter(visibility)
    total = q.count()

    unread_count = (
        db.query(Notification)
        .filter(visibility, Notification.is_read.is_(False))
        .count()
    )

    notifications = (
        q.order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return NotificationListResponse(
        notifications=[NotificationOut.model_validate(n) for n in notifications],
        total=total,
        unread_count=unread_count,
    )


@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """获取当前用户未读通知数量（含全员广播）。"""
    visibility = (Notification.user_id == current_user.id) | (Notification.user_id.is_(None))
    unread_count = (
        db.query(Notification)
        .filter(visibility, Notification.is_read.is_(False))
        .count()
    )
    return {"unread_count": unread_count}


@router.put("/read-all")
def mark_all_as_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """标记当前用户所有通知（含广播）为已读。"""
    visibility = (Notification.user_id == current_user.id) | (Notification.user_id.is_(None))
    updated = (
        db.query(Notification)
        .filter(visibility, Notification.is_read.is_(False))
        .update({Notification.is_read: True}, synchronize_session=False)
    )
    db.commit()
    return {"success": True, "updated_count": updated}


@router.put("/{notification_id}/read")
def mark_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """标记单条通知为已读（需验证归属当前用户或为广播）。"""
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if n is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    if not ((n.user_id == current_user.id) or (n.user_id is None)):
        raise HTTPException(status_code=404, detail="通知不存在")

    if not n.is_read:
        n.is_read = True
        db.commit()
    return {"success": True}


@router.delete("/{notification_id}", status_code=204)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """删除单条通知（需验证归属当前用户或为广播）。"""
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if n is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    if not ((n.user_id == current_user.id) or (n.user_id is None)):
        raise HTTPException(status_code=404, detail="通知不存在")

    db.delete(n)
    db.commit()


@router.post("", response_model=NotificationOut, status_code=201)
def create_notification(
    payload: NotificationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system_config", "edit")),
) -> Notification:
    """创建通知 / 发布公告（仅管理员可用）。

    - 指定 user_id：直接创建给该用户
    - user_id 为 None（公告）：走 dispatch_notification 规则路由（event_type=announcement）
    """
    # 公告类型（user_id 为空）走规则路由，按通知规则分发给目标用户/角色
    if payload.user_id is None:
        from app.core.notification_dispatch import dispatch_notification

        created = dispatch_notification(
            db,
            event_type="announcement",
            title=payload.title,
            content=payload.content,
            related_type=payload.related_type,
            related_id=payload.related_id,
            created_by=current_user.username,
        )
        if not created:
            # 极端情况：规则路由未产出通知（不应发生），回退广播
            n = Notification(
                user_id=None,
                type=payload.type,
                title=payload.title,
                content=payload.content,
                related_type=payload.related_type,
                related_id=payload.related_id,
                created_by=current_user.username,
            )
            db.add(n)
            db.commit()
            db.refresh(n)
            return n
        logger.info(
            "公告已通过规则路由派发: event_type=announcement, created_by=%s, 派发 %d 条",
            current_user.username, len(created),
        )
        return created[0]

    # 指定用户：直接创建
    n = Notification(
        user_id=payload.user_id,
        type=payload.type,
        title=payload.title,
        content=payload.content,
        related_type=payload.related_type,
        related_id=payload.related_id,
        created_by=current_user.username,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    logger.info(
        "通知已创建: id=%s, type=%s, user_id=%s, created_by=%s",
        n.id, n.type, n.user_id, n.created_by,
    )
    return n
