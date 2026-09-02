"""运营通知辅助：写站内通知（通知中心可见）。"""
import logging

from sqlalchemy.orm import Session

from app.models.notification import Notification

logger = logging.getLogger(__name__)


def notify_ops(db: Session, title: str, content: str, *, user_id: int = 1, ntype: str = "workflow") -> None:
    """向运营人员（默认 admin）发送站内通知，失败不影响主流程。"""
    try:
        db.add(Notification(
            user_id=user_id,
            type=ntype,
            title=title,
            content=content,
            created_by="system",
        ))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("运营通知写入失败: %s", title)
