"""对话工具是否允许当前用户调用。无用户视为系统主体，不按角色裁剪。"""
from __future__ import annotations

from app.core.permissions import has_permission, resolve_user_permissions


def user_may_call(user, db, required: tuple[str, str] | None) -> bool:
    if user is None or required is None:
        return True
    from app.dependencies import is_admin

    if is_admin(user, db):
        return True
    module, action = required
    permissions = resolve_user_permissions(user, db)
    return has_permission(permissions, module, action)
