"""资源共享授权管理路由。

owner 可将资源的查看/编辑权限共享给其他用户或角色。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, is_admin
from app.models.agent import Agent
from app.models.knowledge_base import KnowledgeBase
from app.models.resource_share import ResourceShare
from app.models.role import Role
from app.models.skill import Skill
from app.models.tool import Tool
from app.models.user import User
from app.models.workflow import Workflow

logger = logging.getLogger(__name__)

_RESOURCE_MODELS = {
    "workflow": Workflow,
    "agent": Agent,
    "tool": Tool,
    "skill": Skill,
    "knowledge_base": KnowledgeBase,
}

router = APIRouter(
    prefix="/resource-shares",
    tags=["resource-shares"],
    dependencies=[Depends(get_current_user)],
)


class ShareCreateRequest(BaseModel):
    user_id: Optional[int] = Field(None, description="被授权用户ID（与 role_id 二选一）")
    role_id: Optional[int] = Field(None, description="被授权角色ID（与 user_id 二选一）")
    permission: str = Field("edit", description="授权权限级别：view / edit")


def _get_resource_or_404(db: Session, resource_type: str, resource_id: int):
    model = _RESOURCE_MODELS.get(resource_type)
    if model is None:
        raise HTTPException(status_code=400, detail=f"不支持的资源类型: {resource_type}")
    obj = db.query(model).filter(model.id == resource_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return obj


def _check_share_management_permission(user: User, db: Session, resource_obj) -> None:
    if is_admin(user, db):
        return
    if getattr(resource_obj, "created_by", None) == user.id:
        return
    raise HTTPException(status_code=403, detail="无权管理此资源的共享：仅创建者或管理员可操作")


def _share_to_dict(s: ResourceShare, db: Session) -> dict:
    role_name = None
    if s.shared_with_role:
        role = db.query(Role).filter(Role.id == s.shared_with_role).first()
        role_name = role.name if role else None
    return {
        "id": s.id,
        "resource_type": s.resource_type,
        "resource_id": s.resource_id,
        "shared_with": s.shared_with,
        "shared_with_role": s.shared_with_role,
        "role_name": role_name,
        "granted_by": s.granted_by,
        "permission": s.permission or "edit",
        "created_at": s.created_at,
    }


@router.get("/{resource_type}/{resource_id}")
def list_shares(
    resource_type: str,
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    resource_obj = _get_resource_or_404(db, resource_type, resource_id)
    _check_share_management_permission(current_user, db, resource_obj)
    shares = (
        db.query(ResourceShare)
        .filter(
            ResourceShare.resource_type == resource_type,
            ResourceShare.resource_id == resource_id,
        )
        .order_by(ResourceShare.id.asc())
        .all()
    )
    return [_share_to_dict(s, db) for s in shares]


@router.post("/{resource_type}/{resource_id}", status_code=201)
def add_share(
    resource_type: str,
    resource_id: int,
    body: ShareCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if body.permission not in ("view", "edit"):
        raise HTTPException(status_code=400, detail="permission 取值仅支持 view / edit")
    if body.user_id is None and body.role_id is None:
        raise HTTPException(status_code=400, detail="user_id 与 role_id 至少提供一个")
    if body.user_id is not None and body.role_id is not None:
        raise HTTPException(status_code=400, detail="user_id 与 role_id 不能同时提供")

    resource_obj = _get_resource_or_404(db, resource_type, resource_id)
    _check_share_management_permission(current_user, db, resource_obj)

    if body.user_id is not None:
        if body.user_id == current_user.id:
            raise HTTPException(status_code=400, detail="不能给自己共享：owner 已有编辑权限")
        target = db.query(User).filter(User.id == body.user_id).first()
        if target is None:
            raise HTTPException(status_code=404, detail="被授权用户不存在")
        if not target.is_active:
            raise HTTPException(status_code=400, detail="被授权用户已被禁用")
        existing = (
            db.query(ResourceShare)
            .filter(
                ResourceShare.resource_type == resource_type,
                ResourceShare.resource_id == resource_id,
                ResourceShare.shared_with == body.user_id,
            )
            .first()
        )
        if existing is not None:
            existing.permission = body.permission
            existing.granted_by = current_user.id
            db.commit()
            db.refresh(existing)
            return _share_to_dict(existing, db)
        share = ResourceShare(
            resource_type=resource_type,
            resource_id=resource_id,
            shared_with=body.user_id,
            granted_by=current_user.id,
            permission=body.permission,
        )
    else:
        role = db.query(Role).filter(Role.id == body.role_id).first()
        if role is None:
            raise HTTPException(status_code=404, detail="被授权角色不存在")
        existing = (
            db.query(ResourceShare)
            .filter(
                ResourceShare.resource_type == resource_type,
                ResourceShare.resource_id == resource_id,
                ResourceShare.shared_with_role == body.role_id,
            )
            .first()
        )
        if existing is not None:
            existing.permission = body.permission
            existing.granted_by = current_user.id
            db.commit()
            db.refresh(existing)
            return _share_to_dict(existing, db)
        share = ResourceShare(
            resource_type=resource_type,
            resource_id=resource_id,
            shared_with_role=body.role_id,
            granted_by=current_user.id,
            permission=body.permission,
        )

    db.add(share)
    db.commit()
    db.refresh(share)
    return _share_to_dict(share, db)


@router.delete("/{resource_type}/{resource_id}/{user_id}")
def revoke_share(
    resource_type: str,
    resource_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    resource_obj = _get_resource_or_404(db, resource_type, resource_id)
    _check_share_management_permission(current_user, db, resource_obj)
    share = (
        db.query(ResourceShare)
        .filter(
            ResourceShare.resource_type == resource_type,
            ResourceShare.resource_id == resource_id,
            ResourceShare.shared_with == user_id,
        )
        .first()
    )
    if share is None:
        raise HTTPException(status_code=404, detail="共享记录不存在")
    db.delete(share)
    db.commit()
    return {"ok": True}


@router.delete("/{resource_type}/{resource_id}/role/{role_id}")
def revoke_role_share(
    resource_type: str,
    resource_id: int,
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    resource_obj = _get_resource_or_404(db, resource_type, resource_id)
    _check_share_management_permission(current_user, db, resource_obj)
    share = (
        db.query(ResourceShare)
        .filter(
            ResourceShare.resource_type == resource_type,
            ResourceShare.resource_id == resource_id,
            ResourceShare.shared_with_role == role_id,
        )
        .first()
    )
    if share is None:
        raise HTTPException(status_code=404, detail="角色共享记录不存在")
    db.delete(share)
    db.commit()
    return {"ok": True}
