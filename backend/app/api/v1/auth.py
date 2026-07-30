"""认证路由：登录、获取当前用户、修改密码。

提供 JWT 登录入口，前端登录页调用 ``POST /auth/login`` 获取 token，
后续请求在 ``Authorization: Bearer <token>`` 头中携带。
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.user import UpdateProfileRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str = Field(..., description="用户名")
    password: str = Field(..., description="明文密码")


class LoginResponse(BaseModel):
    """登录响应体。"""

    access_token: str = Field(..., description="JWT 访问令牌")
    token_type: str = Field("bearer", description="令牌类型")
    user: "UserInfo" = Field(..., description="用户信息")


class UserInfo(BaseModel):
    """用户信息（脱敏，不含密码）。"""

    id: int
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str
    role_id: Optional[int] = None
    is_active: bool

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    """修改密码请求体。"""

    old_password: str = Field(..., description="原密码")
    new_password: str = Field(..., min_length=6, description="新密码（至少 6 位）")


# 解决前向引用：LoginResponse 引用 UserInfo
LoginResponse.model_rebuild()


def _user_info(user: User) -> UserInfo:
    """构造脱敏用户信息。"""
    return UserInfo(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        role_id=user.role_id,
        is_active=user.is_active,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    """用户名密码登录，返回 JWT。

    等保安全增强：
    - 登录前检查账户锁定状态（连续失败 N 次后锁定 M 分钟）
    - 密码错误时累计失败次数，达到阈值自动锁定
    - 登录成功时重置失败计数

    Args:
        body: 登录请求体（username + password）。
        db: 数据库会话。

    Returns:
        含 ``access_token`` 与用户信息的响应。

    Raises:
        HTTPException(401): 用户名不存在或密码错误。
        HTTPException(403): 账号已禁用或已锁定。
    """
    from app.core.security_policy import (
        get_security_policy,
        is_account_locked,
        record_login_failure,
        record_login_success,
    )

    logger.info("登录请求: username=%s", body.username)
    policy = get_security_policy(db)
    user = db.query(User).filter(User.username == body.username).first()

    if user is None:
        logger.warning("登录失败，用户不存在: %s", body.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        logger.warning("登录失败，账号已禁用: %s", body.username)
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    # 检查账户锁定状态
    locked, remaining = is_account_locked(user, policy)
    if locked:
        mins = remaining // 60
        secs = remaining % 60
        logger.warning("登录失败，账户已锁定: %s, 剩余 %ds", body.username, remaining)
        raise HTTPException(
            status_code=403,
            detail=f"账户已被锁定，请在 {mins} 分 {secs} 秒后重试",
        )

    if not verify_password(body.password, user.password_hash):
        logger.warning("登录失败，密码错误: %s", body.username)
        result = record_login_failure(user, db, policy)
        if result["locked"]:
            raise HTTPException(
                status_code=403,
                detail=f"密码错误次数过多，账户已被锁定 {policy.get('security.lockout_duration_minutes', 15)} 分钟",
            )
        raise HTTPException(
            status_code=401,
            detail=f"用户名或密码错误（剩余尝试次数：{result['remaining_attempts']}）",
        )

    # 登录成功：重置失败计数
    record_login_success(user, db)
    user.last_login_at = datetime.now()
    db.commit()

    # 记录审计日志（含客户端 IP，便于追溯登录来源）
    from app.core.audit import get_client_ip, log_audit
    ip = get_client_ip(request)
    log_audit(db, user_id=user.id, username=user.username, action="login",
              resource_type="auth", ip_address=ip, result="success")

    token = create_access_token(user.id, user.username, user.role)
    logger.info("登录成功: username=%s, role=%s", user.username, user.role)
    return LoginResponse(access_token=token, token_type="bearer", user=_user_info(user))


@router.get("/me", response_model=UserInfo)
def get_me(user: User = Depends(get_current_user)) -> UserInfo:
    """获取当前登录用户信息（用于前端鉴权后回显与角色判断）。"""
    return _user_info(user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """修改当前用户密码（含等保密码复杂度校验）。

    Args:
        body: 含原密码与新密码。
        user: 当前登录用户（依赖注入）。
        db: 数据库会话。

    Returns:
        ``{"ok": True}``。

    Raises:
        HTTPException(400): 原密码错误、新密码与原密码相同、或密码复杂度不满足要求。
    """
    from app.core.security_policy import (
        get_security_policy,
        validate_password_complexity,
    )

    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")

    # 等保密码复杂度校验
    policy = get_security_policy(db)
    errors = validate_password_complexity(body.new_password, policy)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))

    user.password_hash = hash_password(body.new_password)
    db.commit()
    logger.info("用户修改密码成功: username=%s", user.username)
    return {"ok": True}


@router.put("/profile", response_model=UserInfo)
def update_profile(
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserInfo:
    """用户自助修改个人资料（display_name / email）。

    Args:
        body: 含待更新字段（仅 display_name / email，未提供则不动）。
        user: 当前登录用户（依赖注入）。
        db: 数据库会话。

    Returns:
        更新后的脱敏用户信息。
    """
    if body.display_name is not None:
        if len(body.display_name) > 128:
            raise HTTPException(status_code=400, detail="显示名长度不能超过 128 个字符")
        user.display_name = body.display_name.strip() or None
    if body.email is not None:
        email = body.email.strip()
        if email and "@" not in email:
            raise HTTPException(status_code=400, detail="邮箱格式不正确")
        user.email = email or None
    db.commit()
    db.refresh(user)
    logger.info("用户更新个人资料成功: username=%s", user.username)
    return _user_info(user)
