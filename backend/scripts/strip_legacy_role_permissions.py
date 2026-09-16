"""一次性迁移脚本：剔除 analyst/viewer 系统角色中的越权模块权限（落盘版）。

背景（渗透测试整改 漏洞4/5）：
- ``GET /ban-workflow/banned-ips``、``GET /api/v1/banned-ips*`` 与
  ``GET /ingest/strategies*`` 已收紧为仅 admin（require_role("admin")）。
- 这两个模块（``ban_workflow``、``strategy``）原先被错误分配给 analyst / viewer，
  属权限分配过宽；``permissions.py`` 的 DEFAULT_ROLES 已同步收紧。
- 但数据库中已存在的 ``is_system`` 角色记录不会因改种子自动更新
  （``_seed_default_roles`` 仅在 roles 表为空时执行；
  ``_sync_role_permission_modules`` 只添加不删除），因此需要本脚本做一次性收敛。

收敛范围（严格遵循决策，防止扩大影响面）：
- 仅处理 is_system=True 的 analyst / viewer 角色；
- 仅剔除 ``ban_workflow``、``strategy`` 两个模块的 permissions JSON 键；
- admin 角色不动；自定义（非 is_system）角色不动（属管理员显式授权）。

幂等：可重复执行；已剔除的角色不产生额外变更，重复执行无副作用。

验收日志：每个受影响角色输出 before/after 的权限键差异。

执行方式（在 backend 目录/容器内）：
    cd backend && python -m scripts.strip_legacy_role_permissions
或容器内：
    docker exec -it soar-backend-dev python -m scripts.strip_legacy_role_permissions

建议纳入部署流程，一次部署执行一次；重复执行无副作用（自愈）。
"""
import logging
import sys
from pathlib import Path

# 允许从 backend 目录或容器工作目录直接以模块方式运行
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal  # noqa: E402
from app.models.role import Role  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("strip_legacy_role_permissions")

# 已收紧为 admin-only、需从 analyst/viewer 剔除的模块
TARGET_MODULES = ("strategy", "ban_workflow")
# 仅处理系统内置非管理员角色
TARGET_ROLE_NAMES = ("analyst", "viewer")


def run() -> int:
    """执行迁移。返回受影响（发生变更）的角色数；幂等，重复执行返回 0。"""
    db = SessionLocal()
    changed = 0
    try:
        roles = (
            db.query(Role)
            .filter(Role.is_system.is_(True), Role.name.in_(TARGET_ROLE_NAMES))
            .all()
        )
        for role in roles:
            perms = role.permissions if isinstance(role.permissions, dict) else {}
            before = set(perms.keys())
            removed = [m for m in TARGET_MODULES if m in before]
            if not removed:
                logger.info(
                    "角色 %s(id=%s)：无 %s 目标权限键，无需变更",
                    role.name, role.id, "/".join(TARGET_MODULES),
                )
                continue
            for m in removed:
                perms.pop(m, None)
            role.permissions = perms
            db.add(role)
            changed += 1
            logger.info(
                "角色 %s(id=%s) 已剔除模块: %s | before: %s | after: %s",
                role.name, role.id, removed, sorted(before), sorted(perms.keys()),
            )
        db.commit()
        if changed:
            logger.info("迁移完成：共更新 %d 个角色", changed)
        else:
            logger.info("无需迁移：所有目标角色已是最新状态")
        return changed
    finally:
        db.close()


if __name__ == "__main__":
    run()
