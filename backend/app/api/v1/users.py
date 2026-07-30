"""用户管理 API。

仅授权用户可查看用户列表，编辑/删除需更高权限。
不可删除/禁用当前登录账号，系统至少保留一个管理员。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.role import Role
from app.models.user import User
from app.schemas.user import (
    ResetPasswordRequest,
    UserCreate,
    UserOut,
    UserUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user", "view")),
) -> list[User]:
    """列出所有用户。"""
    logger.info("列出所有用户")
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user", "edit")),
) -> User:
    """创建用户。"""
    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"用户名 '{body.username}' 已存在")

    # 根据 role 名称解析 role_id
    role_id = body.role_id
    if not role_id and body.role:
        role = db.query(Role).filter(Role.name == body.role).first()
        if role:
            role_id = role.id

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        email=body.email,
        role=body.role,
        role_id=role_id,
        is_active=body.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("用户创建: id=%s, username=%s", user.id, user.username)
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user", "edit")),
) -> User:
    """更新用户信息（不含密码）。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    logger.info("用户更新: id=%s", user_id)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("user", "delete")),
) -> None:
    """删除用户（不可删除自己，系统至少保留一个管理员）。"""
    if current.id == user_id:
        raise HTTPException(status_code=400, detail="不可删除当前登录账号")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 保护最后一个管理员
    if user.role == "admin":
        admin_count = db.query(User).filter(User.role == "admin").count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="系统至少保留一个管理员账号")

    db.delete(user)
    db.commit()
    logger.info("用户删除: id=%s", user_id)
    return None


@router.post("/{user_id}/reset-password", response_model=UserOut)
def reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user", "edit")),
) -> User:
    """管理员重置用户密码。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    db.refresh(user)
    logger.info("密码重置: user_id=%s", user_id)
    return user


@router.post("/{user_id}/toggle-active", response_model=UserOut)
def toggle_active(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("user", "edit")),
) -> User:
    """启用/禁用用户（不可禁用自己）。"""
    if current.id == user_id:
        raise HTTPException(status_code=400, detail="不可禁用当前登录账号")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    logger.info("用户启停: user_id=%s, active=%s", user_id, user.is_active)
    return user
