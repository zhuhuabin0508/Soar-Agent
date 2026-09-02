"""FastAPI 依赖注入：工具与设备能力注册 + 鉴权依赖。

鉴权依赖（P0-1）：
- ``get_current_user``：从 Authorization: Bearer <JWT> 解析当前登录用户，所有管理 API 使用。
- ``require_role(*roles)``：RBAC 角色校验，返回依赖工厂。
- ``verify_webhook_secret``：校验 webhook 请求的 per-workflow 密钥（header 或 path）。
- ``get_optional_user``：可选鉴权，未登录返回 None（用于健康检查等）。
"""
import functools
import logging
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import DEFAULT_ROLES, has_permission, migrate_permissions
from app.core.security import decode_access_token
from app.database import get_db
from app.devices.firewall import block_ip_on_firewall, is_ip_blocked
from app.models.role import Role
from app.models.user import User
from app.tools.context_tools import (
    check_subnet,
    check_whitelist,
    get_asset_info,
    get_threat_intel,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """安全上下文工具注册表。

    聚合所有查询类工具函数引用，路由层可通过依赖注入获取
    单实例并直接调用对应工具方法。
    """

    def __init__(self) -> None:
        self.check_whitelist = check_whitelist
        self.get_asset_info = get_asset_info
        self.get_threat_intel = get_threat_intel
        self.check_subnet = check_subnet
        logger.debug("ToolRegistry 实例已创建")


class FirewallDevice:
    """防火墙设备能力封装。

    将防火墙封禁与查询能力聚合为设备对象，便于依赖注入。
    """

    def __init__(self) -> None:
        self.block_ip_on_firewall = block_ip_on_firewall
        self.is_ip_blocked = is_ip_blocked
        logger.debug("FirewallDevice 实例已创建")


@functools.lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    """获取 ToolRegistry 单例（依赖注入入口）。"""
    logger.info("构建/复用 ToolRegistry 单例")
    return ToolRegistry()


@functools.lru_cache(maxsize=1)
def get_firewall_device() -> FirewallDevice:
    """获取 FirewallDevice 单例（依赖注入入口）。"""
    logger.info("构建/复用 FirewallDevice 单例")
    return FirewallDevice()


# ============ 鉴权依赖 ============

_CREDENTIAL_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="未认证或认证已过期，请重新登录",
    headers={"WWW-Authenticate": "Bearer"},
)

_FORBIDDEN_EXCEPTION = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="权限不足，无法执行此操作",
)


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """JWT 鉴权依赖：解析 Bearer token 并返回当前用户。

    所有管理类 API（CRUD/审批/工具编辑等）应通过 ``Depends(get_current_user)``
    或 ``Depends(require_role(...))`` 强制登录。

    安全增强：
    - 解码 JWT 后校验 ``jti`` 是否在黑名单中（登出/刷新/强制下线后立即失效）。
    - Redis 不可用时降级放行（保证可用性）。

    Raises:
        HTTPException(401): 未携带 token / token 无效 / 用户不存在 / 用户已禁用 / token 已被吊销。
    """
    if not authorization:
        raise _CREDENTIAL_EXCEPTION
    # 兼容 "Bearer xxx" 与裸 token
    parts = authorization.split(" ", 1)
    token = parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else authorization.strip()
    if not token:
        raise _CREDENTIAL_EXCEPTION

    payload = decode_access_token(token)
    if payload is None:
        raise _CREDENTIAL_EXCEPTION

    # 拒绝 OTP 待验证 token（仅用于两步登录第二步，不能用于 API 鉴权）
    if payload.get("type") == "otp_pending":
        logger.warning("OTP 待验证 token 不可用于 API 鉴权: uid=%s", payload.get("sub"))
        raise _CREDENTIAL_EXCEPTION

    # 校验 token 是否已被吊销（登出/刷新/强制下线）
    jti = payload.get("jti")
    if jti:
        from app.core.session import is_token_blacklisted
        if is_token_blacklisted(jti):
            logger.warning("Token 已被吊销: uid=%s, jti=%s", payload.get("sub"), jti)
            raise _CREDENTIAL_EXCEPTION

    user_id = payload.get("sub")
    if user_id is None:
        raise _CREDENTIAL_EXCEPTION

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        raise _CREDENTIAL_EXCEPTION

    user = db.query(User).filter(User.id == uid).first()
    if user is None:
        logger.warning("JWT 用户不存在: uid=%s", uid)
        raise _CREDENTIAL_EXCEPTION
    if not user.is_active:
        logger.warning("用户已禁用: uid=%s, username=%s", uid, user.username)
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")
    return user


def require_role(*allowed_roles: str) -> Callable:
    """RBAC 角色校验依赖工厂。

    用法：``Depends(require_role("admin", "analyst"))`` 表示仅允许 admin/analyst 访问。

    Args:
        allowed_roles: 允许的角色名集合。

    Returns:
        FastAPI 依赖函数，返回当前用户（已校验角色）。
    """
    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            logger.warning(
                "权限不足: uid=%s, username=%s, role=%s, required=%s",
                user.id, user.username, user.role, allowed_roles,
            )
            raise _FORBIDDEN_EXCEPTION
        return user

    return _checker


def require_permission(module: str, action: str) -> Callable:
    """权限矩阵校验依赖工厂（基于 Role.permissions）。

    用法：``Depends(require_permission("user", "edit"))``

    校验逻辑：
    1. admin 角色自动通过（拥有所有权限）。
    2. 优先查 ``user.role_id`` 关联的 Role.permissions 矩阵。
    3. 若无 role_id，fallback 到 ``DEFAULT_ROLES`` 中 ``user.role`` 对应的权限。

    Args:
        module: 权限模块名（如 ``"user"`` / ``"workflow"``）。
        action: 动作名（如 ``"view"`` / ``"edit"`` / ``"delete"``）。

    Returns:
        FastAPI 依赖函数，返回当前用户（已校验权限）。
    """

    def _checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        # admin 角色自动拥有所有权限
        if user.role == "admin":
            return user
        # 优先查 role_id 关联的角色权限矩阵
        if user.role_id:
            role = db.query(Role).filter(Role.id == user.role_id).first()
            if role and role.name == "admin":
                return user
            if role and has_permission(migrate_permissions(role.permissions), module, action):
                return user
        # fallback：查 DEFAULT_ROLES 中 user.role 对应的权限
        for default_role in DEFAULT_ROLES:
            if default_role["name"] == user.role:
                if has_permission(default_role["permissions"], module, action):
                    return user
                break
        logger.warning(
            "权限不足: uid=%s, username=%s, module=%s, action=%s",
            user.id, user.username, module, action,
        )
        raise _FORBIDDEN_EXCEPTION

    return _checker


def check_resource_ownership(
    user: User,
    db: Session,
    resource_type: str,
    resource_id: int,
    resource_obj,
) -> None:
    """校验用户对资源的编辑权限（资源级 owner 控制）。

    通过条件（满足任一即放行）：
    1. ``admin`` 角色；
    2. 当前用户是资源创建者（``resource_obj.created_by == user.id``）；
    3. 当前用户被 owner 显式共享授权（``resource_shares`` 表有记录）。

    否则抛 403。供各资源 update/delete 接口在查出资源对象后调用，
    作为模块级权限校验之后的第二道防线。

    Args:
        user: 当前登录用户。
        db: 数据库会话。
        resource_type: 资源类型 workflow/agent/tool/skill/knowledge_base。
        resource_id: 资源ID。
        resource_obj: 资源 ORM 实例（需有 ``created_by`` 属性）。
    """
    from app.models.resource_share import ResourceShare

    # admin 自动通过
    if user.role == "admin":
        return
    # owner
    if getattr(resource_obj, "created_by", None) == user.id:
        return
    # 被授权用户
    share = db.query(ResourceShare).filter(
        ResourceShare.resource_type == resource_type,
        ResourceShare.resource_id == resource_id,
        ResourceShare.shared_with == user.id,
    ).first()
    if share:
        return
    logger.warning(
        "资源编辑权限不足: uid=%s, username=%s, type=%s, resource_id=%s, owner=%s",
        user.id, user.username, resource_type, resource_id,
        getattr(resource_obj, "created_by", None),
    )
    raise HTTPException(status_code=403, detail="无权编辑此资源：仅创建者或被授权用户可编辑")


def compute_can_edit_ids(
    db: Session,
    user: User,
    resource_type: str,
    resource_ids: list[int],
) -> set[int]:
    """批量计算用户被共享授权可编辑的资源 ID 集合（资源级 owner 控制）。

    仅返回通过 ``resource_shares`` 表被授权的资源 ID；admin 与 owner 的判断
    在调用处做（admin 全部可编辑、owner 自己创建的可编辑）。

    Args:
        db: 数据库会话。
        user: 当前登录用户。
        resource_type: 资源类型 workflow/agent/tool/skill/knowledge_base。
        resource_ids: 资源 ID 列表。

    Returns:
        用户被共享授权的资源 ID 集合（admin 返回空集，因调用处会直接判 True）。
    """
    from app.models.resource_share import ResourceShare

    # admin 无需查共享表（调用处直接判 True）
    if user.role == "admin":
        return set()
    if not resource_ids:
        return set()

    rows = (
        db.query(ResourceShare.resource_id)
        .filter(
            ResourceShare.resource_type == resource_type,
            ResourceShare.resource_id.in_(resource_ids),
            ResourceShare.shared_with == user.id,
            ResourceShare.permission == "edit",
        )
        .all()
    )
    return {r[0] for r in rows}


def get_optional_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """可选鉴权：未登录返回 None，登录则返回用户（用于公开但可识别身份的端点）。"""
    if not authorization:
        return None
    try:
        return get_current_user(authorization=authorization, db=db)
    except HTTPException:
        return None


def verify_webhook_secret(workflow, x_webhook_secret: Optional[str]) -> None:
    """校验 webhook 请求携带的 per-workflow 密钥。

    作为辅助函数在 webhook 路由内调用（需先查出 workflow 对象，并从请求头取出密钥传入）。

    Args:
        workflow: Workflow ORM 实例。
        x_webhook_secret: 请求头 ``X-Webhook-Secret`` 的值（可为 None）。

    Raises:
        HTTPException(403): 工作流未配置密钥。
        HTTPException(401): 密钥不匹配。
    """
    expected = workflow.webhook_secret
    if not expected:
        # 工作流未配置密钥，拒绝触发（强制要求配置）
        logger.warning("工作流未配置 webhook 密钥: id=%s", workflow.id)
        raise HTTPException(
            status_code=403,
            detail="该工作流未配置 Webhook 密钥，请先在工作流编辑页生成并配置密钥",
        )
    if not x_webhook_secret or x_webhook_secret != expected:
        logger.warning("Webhook 密钥校验失败: workflow_id=%s", workflow.id)
        raise _CREDENTIAL_EXCEPTION
