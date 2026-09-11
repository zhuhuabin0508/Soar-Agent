"""用户管理 API。

仅授权用户可查看用户列表，编辑/删除需更高权限。
不可删除/禁用当前登录账号，系统至少保留一个管理员。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
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
) -> list[UserOut]:
    """列出所有用户（含角色显示名）。"""
    logger.info("列出所有用户")
    users = db.query(User).order_by(User.id).all()
    # 批量查询角色名，避免 N+1
    role_ids = {u.role_id for u in users if u.role_id}
    roles_map: dict[int, str] = {}
    if role_ids:
        roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
        roles_map = {r.id: r.name for r in roles}
    result = []
    for u in users:
        data = UserOut.model_validate(u)
        data.role_name = roles_map.get(u.role_id) if u.role_id else None
        result.append(data)
    return result


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("user", "edit")),
) -> User:
    """创建用户。

    安全防护（防特权提升）：指定角色（``role``/``role_id``）或启用状态
    （``is_active``）为高敏感操作，仅限 admin 执行；非 admin 用户仅能以
    默认 ``analyst`` 角色创建普通用户，不能创建管理员账号。
    """
    # 角色/启用状态为敏感字段：仅 admin 可指定（防特权升级 / Mass Assignment）
    if current.role != "admin":
        if body.role not in ("analyst", None) or body.role_id is not None or body.is_active is not True:
            raise HTTPException(status_code=403, detail="仅管理员可创建管理员或指定角色/启用状态")

    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"用户名 '{body.username}' 已存在")

    # 等保密码复杂度校验（与系统设置中的密码策略一致）
    from app.core.security_policy import get_security_policy, validate_password_complexity
    policy = get_security_policy(db)
    errors = validate_password_complexity(body.password, policy)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))

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
        allowed_login_methods=body.allowed_login_methods,
        # 新建用户首次登录需改密
        must_change_password=True,
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
    current: User = Depends(require_permission("user", "edit")),
) -> User:
    """更新用户信息（不含密码）。

    安全防护（防特权提升）：修改角色字段（``role``/``role_id``）与启用状态
    （``is_active``）为高敏感操作，仅限 admin 执行。仅拥有 ``user:edit``
    权限的非 admin 用户只能更新 ``display_name``/``email``/``allowed_login_methods``
    等非敏感资料字段，杜绝通过批量更新把普通账号提升为管理员。
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 角色/启用状态为敏感字段：仅 admin 可修改（防特权升级 / Mass Assignment）
    sensitive_fields = ("role", "role_id", "is_active")
    if any(getattr(body, f, None) is not None for f in sensitive_fields) and current.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改用户角色或启用状态")

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

    # 等保密码复杂度校验（与系统设置中的密码策略一致）
    from app.core.security_policy import get_security_policy, validate_password_complexity
    policy = get_security_policy(db)
    errors = validate_password_complexity(body.new_password, policy)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))

    user.password_hash = hash_password(body.new_password)
    # 管理员重置后强制用户下次登录改密
    user.must_change_password = True
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


@router.post("/{user_id}/force-logout")
def force_logout(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("user", "edit")),
    authorization: Optional[str] = Header(None),
) -> dict:
    """强制下线指定用户的所有会话（管理员操作）。

    将该用户当前所有活跃会话的 token 拉黑并删除会话记录，
    受影响的设备在下一次请求时将收到 401 未认证错误。

    安全策略：
    - 不可强制下线自己（避免误操作，请使用「退出登录」）
    - 记录审计日志（含操作者 IP）
    - 默认下线该用户全部会话；如需保留当前管理员会话，
      ``except_sid`` 可由调用方扩展（当前不传，下线目标用户的全部）

    Args:
        user_id: 目标用户 ID。
        request: HTTP 请求（用于获取客户端 IP）。
        db: 数据库会话。
        current: 当前登录用户（鉴权）。
        authorization: Authorization 头（保留以与 auth 模块一致，本接口不使用）。

    Returns:
        ``{"ok": True, "revoked": <被下线的会话数>}``。
    """
    from app.core.session import revoke_all_sessions
    from app.core.audit import get_client_ip, log_audit

    if current.id == user_id:
        raise HTTPException(status_code=400, detail="不可强制下线当前登录账号，请使用「退出登录」")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    revoked = revoke_all_sessions(user_id)
    ip = get_client_ip(request)
    log_audit(
        db,
        user_id=current.id,
        username=current.username,
        action="force_logout",
        resource_type="user",
        resource_id=str(user_id),
        ip_address=ip,
        result="success",
        detail={"target_user": user.username, "revoked_sessions": revoked},
    )
    logger.info(
        "强制下线: operator=%s, target_user_id=%s, target_username=%s, revoked=%d",
        current.username, user_id, user.username, revoked,
    )
    return {"ok": True, "revoked": revoked}
