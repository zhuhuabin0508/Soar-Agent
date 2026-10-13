"""修复目录类别 level 失真：让每个目录的 level 恒等于 parent.level + 1。

背景：早期「移动目录」只更新被移动目录自身的 level，其后代 level 未同步修正，
导致深层子目录的 level 偏小（例如实际在第 4 层却记录为第 3 层）。
该问题会影响目录树的层级显示、新建子目录的层级判断，以及移动时的越界校验。

用法（在 backend 目录下，需可连数据库）:
    python -m scripts.fix_category_levels            # 预检 + 修复
    python -m scripts.fix_category_levels --dry-run  # 只报告不写库

幂等：level 已正确的目录不会被改动。
"""
import logging
import sys

from app.database import SessionLocal
from app.models.deliverable import ServiceCategory

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fix_category_levels")


def main(dry_run: bool = False) -> int:
    """按 parent_id 重算全树 level，返回被修正的目录数。"""
    db = SessionLocal()
    try:
        cats = db.query(ServiceCategory).all()
        by_id = {c.id: c for c in cats}
        children_map: dict[int | None, list[ServiceCategory]] = {}
        for c in cats:
            children_map.setdefault(c.parent_id, []).append(c)

        fixed = 0
        orphan = 0

        def walk(node: ServiceCategory, level: int) -> None:
            nonlocal fixed
            if (node.level or 0) != level:
                logger.info(
                    "修正: id=%s name=%s level %s → %s",
                    node.id, node.name, node.level, level,
                )
                if not dry_run:
                    node.level = level
                fixed += 1
            for child in children_map.get(node.id, []):
                walk(child, level + 1)

        # 从根目录（无父级，或父级已不存在）开始逐层下推
        for c in cats:
            if c.parent_id is None or c.parent_id not in by_id:
                if c.parent_id is not None:
                    orphan += 1
                    logger.warning(
                        "父级缺失，按根级处理: id=%s name=%s parent_id=%s",
                        c.id, c.name, c.parent_id,
                    )
                walk(c, 1)

        if not dry_run:
            db.commit()
        logger.info(
            "%s完成：目录总数=%s，修正=%s，父级缺失=%s",
            "预检" if dry_run else "修复",
            len(cats), fixed, orphan,
        )
        return fixed
    finally:
        db.close()


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
