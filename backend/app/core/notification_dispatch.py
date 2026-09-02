"""通知派发服务：根据通知规则将通知投递给目标用户。

核心函数 ``dispatch_notification``：
1. 查询所有启用的、event_type 匹配（含通配 "*"）的规则
2. 汇总目标用户（按 ID 指定 + 按角色匹配，去重）
3. 若无匹配规则 → 回退为全员广播（user_id=None），保证不丢通知
4. 为每个目标用户创建一条 Notification（同事务，调用方负责 commit）

使用示例：
    from app.core.notification_dispatch import dispatch_notification
    dispatch_notification(
        db, event_type="feedback", title="新反馈", content="...",
        related_type="feedback", related_id=42, created_by="system",
    )
    db.commit()
"""
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.notification_rule import NotificationRule
from app.models.user import User

logger = logging.getLogger(__name__)


def _resolve_target_users(db: Session, rules: list[NotificationRule]) -> list[int]:
    """根据规则列表解析目标用户 ID（按 ID + 按角色匹配，去重）。"""
    user_ids: set[int] = set()
    for rule in rules:
        # 1) 直接指定的用户 ID
        for uid in rule.get_target_user_ids():
            user_ids.add(uid)
        # 2) 按角色匹配
        roles = rule.get_target_roles()
        if roles:
            role_users = (
                db.query(User.id)
                .filter(User.role.in_(roles), User.is_active.is_(True))
                .all()
            )
            for (uid,) in role_users:
                user_ids.add(uid)
    # 过滤掉不存在的用户（轻量校验）
    if not user_ids:
        return []
    existing = {
        uid for (uid,) in db.query(User.id).filter(User.id.in_(user_ids)).all()
    }
    return sorted(existing)


def dispatch_notification(
    db: Session,
    *,
    event_type: str,
    title: str,
    content: Optional[str] = None,
    related_type: Optional[str] = None,
    related_id: Optional[int] = None,
    created_by: Optional[str] = "system",
) -> list[Notification]:
    """根据通知规则派发通知给目标用户。

    - 查询启用的、event_type 匹配（含 "*" 通配）的规则
    - 无匹配规则时回退为全员广播（user_id=None，一条通知）
    - 有匹配规则时为每个目标用户创建一条定向通知
    - 事务由调用方管理（本函数不 commit）

    Returns:
        创建的 Notification 列表
    """
    # 查询匹配的启用规则：event_type 精确匹配 + "*" 通配
    rules = (
        db.query(NotificationRule)
        .filter(
            NotificationRule.enabled.is_(True),
            NotificationRule.event_type.in_([event_type, "*"]),
        )
        .all()
    )

    if not rules:
        # 无匹配规则 → 回退为全员广播
        n = Notification(
            user_id=None,
            type=event_type,
            title=title,
            content=content,
            related_type=related_type,
            related_id=related_id,
            created_by=created_by,
        )
        db.add(n)
        db.flush()
        logger.info(
            "通知派发(广播回退): type=%s, title=%s, created_by=%s",
            event_type, title, created_by,
        )
        return [n]

    # 解析目标用户
    target_user_ids = _resolve_target_users(db, rules)
    if not target_user_ids:
        # 规则匹配但目标用户均不存在 → 回退广播
        n = Notification(
            user_id=None,
            type=event_type,
            title=title,
            content=content,
            related_type=related_type,
            related_id=related_id,
            created_by=created_by,
        )
        db.add(n)
        db.flush()
        logger.warning(
            "通知派发(目标为空回退广播): type=%s, rules=%d, created_by=%s",
            event_type, len(rules), created_by,
        )
        return [n]

    created: list[Notification] = []
    for uid in target_user_ids:
        n = Notification(
            user_id=uid,
            type=event_type,
            title=title,
            content=content,
            related_type=related_type,
            related_id=related_id,
            created_by=created_by,
        )
        db.add(n)
        created.append(n)
    db.flush()
    logger.info(
        "通知派发(规则路由): type=%s, rules=%d, targets=%d, created_by=%s",
        event_type, len(rules), len(created), created_by,
    )
    return created
