"""资源共享授权管理路由。

owner 可将资源的编辑权限共享给其他用户（资源级 owner 权限控制的补充）。
被授权用户对该资源也拥有编辑权限，但不改变 owner 归属，也不能再转授或撤销共享。

接口：
- GET    /resource-shares/{resource_type}/{resource_id}            查看共享列表（仅 owner/admin）
- POST   /resource-shares/{resource_type}/{resource_id}            添加共享（body: {user_id}，仅 owner/admin）
- DELETE /resource-shares/{resource_type}/{resource_id}/{user_id}  撤销共享（仅 owner/admin）

``resource_type`` 白名单：workflow / agent / tool / skill / knowledge_base。
共享管理权限：仅 admin 或资源 owner 可操作。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agent import Agent
from app.models.knowledge_base import KnowledgeBase
from app.models.resource_share import ResourceShare
from app.models.skill import Skill
from app.models.tool import Tool
from app.models.user import User
from app.models.workflow import Workflow

logger = logging.getLogger(__name__)

# 资源类型 → ORM 模型 映射（同时作为白名单校验）
_RESOURCE_MODELS = {
    "workflow": Workflow,
    "agent": Agent,
    "tool": Tool,
    "skill": Skill,
    "knowledge_base": KnowledgeBase,
}

# router 级鉴权：所有共享管理接口强制登录
router = APIRouter(
    prefix="/resource-shares",
    tags=["resource-shares"],
    dependencies=[Depends(get_current_user)],
)


class ShareCreateRequest(BaseModel):
    """添加共享请求体。"""

    user_id: int = Field(..., description="被授权用户ID")
    permission: str = Field("edit", description="授权权限级别：view（查看）/ edit（编辑）")


def _get_resource_or_404(db: Session, resource_type: str, resource_id: int):
    """按资源类型与 ID 查询资源对象，类型不在白名单 400，不存在 404。"""
    model = _RESOURCE_MODELS.get(resource_type)
    if model is None:
        raise HTTPException(status_code=400, detail=f"不支持的资源类型: {resource_type}")
    obj = db.query(model).filter(model.id == resource_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return obj


def _check_share_management_permission(user: User, resource_obj) -> None:
    """校验共享管理权限：仅 admin 或资源 owner 可管理共享（被授权用户不可）。"""
    if user.role == "admin":
        return
    if getattr(resource_obj, "created_by", None) == user.id:
        return
    raise HTTPException(status_code=403, detail="无权管理此资源的共享：仅创建者或管理员可操作")


def _share_to_dict(s: ResourceShare) -> dict:
    """序列化共享记录。"""
    return {
        "id": s.id,
        "resource_type": s.resource_type,
        "resource_id": s.resource_id,
        "shared_with": s.shared_with,
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
    """查看资源的共享授权列表（仅 owner/admin）。"""
    resource_obj = _get_resource_or_404(db, resource_type, resource_id)
    _check_share_management_permission(current_user, resource_obj)
    shares = (
        db.query(ResourceShare)
        .filter(
            ResourceShare.resource_type == resource_type,
            ResourceShare.resource_id == resource_id,
        )
        .order_by(ResourceShare.id.asc())
        .all()
    )
    return [_share_to_dict(s) for s in shares]


@router.post("/{resource_type}/{resource_id}", status_code=201)
def add_share(
    resource_type: str,
    resource_id: int,
    body: ShareCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """添加资源共享授权（仅 owner/admin）。

    - 不能给自己共享（owner 已有权限）。
    - 重复共享时更新权限级别（支持 查看 -> 编辑 升级 / 编辑 -> 查看 降级）。
    - 被授权用户必须存在且启用。
    - permission 取值 view（仅查看）/ edit（编辑），其他值 400。
    """
    # 权限级别校验
    if body.permission not in ("view", "edit"):
        raise HTTPException(status_code=400, detail="permission 取值仅支持 view / edit")

    resource_obj = _get_resource_or_404(db, resource_type, resource_id)
    _check_share_management_permission(current_user, resource_obj)

    if body.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能给自己共享：owner 已有编辑权限")

    # 被授权用户必须存在且启用
    target = db.query(User).filter(User.id == body.user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="被授权用户不存在")
    if not target.is_active:
        raise HTTPException(status_code=400, detail="被授权用户已被禁用")

    # 防重复授权
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
        # 已存在授权：更新权限级别（如已授权查看，再次授权编辑时升级权限），不报错
        existing.permission = body.permission
        existing.granted_by = current_user.id
        db.commit()
        db.refresh(existing)
        logger.info(
            "资源共享权限已更新: type=%s, resource_id=%s, shared_with=%s, permission=%s, by=%s",
            resource_type, resource_id, body.user_id, body.permission, current_user.id,
        )
        return _share_to_dict(existing)

    share = ResourceShare(
        resource_type=resource_type,
        resource_id=resource_id,
        shared_with=body.user_id,
        granted_by=current_user.id,
        permission=body.permission,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    logger.info(
        "资源共享已添加: type=%s, resource_id=%s, shared_with=%s, granted_by=%s",
        resource_type, resource_id, body.user_id, current_user.id,
    )
    return _share_to_dict(share)


@router.delete("/{resource_type}/{resource_id}/{user_id}")
def revoke_share(
    resource_type: str,
    resource_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """撤销资源共享授权（仅 owner/admin）。"""
    resource_obj = _get_resource_or_404(db, resource_type, resource_id)
    _check_share_management_permission(current_user, resource_obj)

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
    logger.info(
        "资源共享已撤销: type=%s, resource_id=%s, shared_with=%s, by=%s",
        resource_type, resource_id, user_id, current_user.id,
    )
    return {"ok": True}
