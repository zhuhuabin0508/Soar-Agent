"""角色管理 API。

支持自定义角色的增删改查与权限矩阵配置。
系统内置角色（admin/analyst/viewer）不可删除。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.permissions import ACTION_LABELS, MODULE_LABELS, PERMISSION_MODULES
from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.role import Role
from app.models.user import User
from app.schemas.role import RoleCreate, RoleOut, RoleUpdate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/roles",
    tags=["roles"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role", "view")),
) -> list[Role]:
    """列出所有角色。"""
    logger.info("列出所有角色")
    return db.query(Role).order_by(Role.id).all()


@router.get("/modules")
def get_permission_modules() -> dict:
    """获取权限模块定义（供前端渲染权限矩阵表格）。

    返回：
        - ``modules``：``{模块名: [动作列表]}``
        - ``module_labels``：模块中文标签
        - ``action_labels``：动作中文标签
    """
    return {
        "modules": PERMISSION_MODULES,
        "module_labels": MODULE_LABELS,
        "action_labels": ACTION_LABELS,
    }


@router.post("", response_model=RoleOut, status_code=201)
def create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role", "edit")),
) -> Role:
    """创建自定义角色。"""
    existing = db.query(Role).filter(Role.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"角色名 '{body.name}' 已存在")

    role = Role(
        name=body.name,
        description=body.description,
        permissions=body.permissions,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    logger.info("角色创建: id=%s, name=%s", role.id, role.name)
    return role


@router.put("/{role_id}", response_model=RoleOut)
def update_role(
    role_id: int,
    body: RoleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role", "edit")),
) -> Role:
    """更新角色（名称/描述/权限矩阵）。"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(role, key, value)
    db.commit()
    db.refresh(role)
    logger.info("角色更新: id=%s", role_id)
    return role


@router.delete("/{role_id}", status_code=204)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role", "delete")),
) -> None:
    """删除角色（系统内置角色不可删除，有关联用户时不可删除）。"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_system:
        raise HTTPException(status_code=400, detail="系统内置角色不可删除")

    # 检查是否有用户关联此角色
    user_count = db.query(User).filter(User.role_id == role_id).count()
    if user_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该角色下仍有 {user_count} 个用户，请先转移用户后再删除",
        )

    db.delete(role)
    db.commit()
    logger.info("角色删除: id=%s", role_id)
    return None
