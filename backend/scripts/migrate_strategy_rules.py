"""存量解析策略迁移脚本：把旧结构（route_rules + field_mappings ...）转为新 rules[] 结构。

策略配置升级后采用"一个策略多条规则(rules[])"结构。旧结构策略由引擎自动归一化单条默认规则，
本脚本把存量策略（内置 JSON 文件 + DB parse_strategies 表）显式落成 rules[] 结构，
便于在编辑页看到并编辑真实规则。

用法（在 backend 目录下，需可连数据库）:
    python -m scripts.migrate_strategy_rules

只迁移旧结构（无 rules 键）的策略；已是新结构的跳过（幂等）。
"""
import json
import logging
from pathlib import Path

from app.engine.rule_matcher import _build_default_rule

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_strategy_rules")

_STRATEGY_DIR = Path(__file__).resolve().parent.parent / "app" / "engine" / "strategies"


def migrate_config(config: dict) -> dict:
    """把单个策略 config 转成 rules[] 结构（已含 rules 则原样返回）。"""
    if isinstance(config.get("rules"), list) and config["rules"]:
        return config
    new = dict(config)
    new["rules"] = [_build_default_rule(config)]
    logger.info("构造默认规则: rule_id=%s log_type=%s", "default", "默认")
    return new


def is_old(config: dict) -> bool:
    """是否为旧结构（缺 rules 键）。"""
    return not (isinstance(config.get("rules"), list) and config["rules"])


def migrate_builtin_files() -> int:
    """迁移 strategies 目录下的内置 JSON 文件，返回改写数量。"""
    updated = 0
    for path in _STRATEGY_DIR.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, ValueError) as exc:
            logger.warning("读取内置文件失败 %s: %s", path.name, exc)
            continue
        if not is_old(config):
            logger.info("内置文件已是新结构，跳过: %s", path.name)
            continue
        new_config = migrate_config(config)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_config, f, ensure_ascii=False, indent=2)
        logger.info("已改写内置文件: %s", path.name)
        updated += 1
    return updated


def migrate_db() -> int:
    """迁移 DB parse_strategies 表中旧结构记录，返回更新数量。"""
    from app.database import SessionLocal
    from app.models.parse_strategy import ParseStrategy

    updated = 0
    db = SessionLocal()
    try:
        rows = db.query(ParseStrategy).all()
        for row in rows:
            try:
                config = json.loads(row.config or "{}")
            except ValueError:
                logger.warning("策略 %s(%d) config 非 JSON，跳过", row.strategy_name, row.id)
                continue
            if not is_old(config):
                continue
            new_config = migrate_config(config)
            row.config = json.dumps(new_config, ensure_ascii=False)
            db.add(row)
            logger.info("已迁移 DB 策略: id=%d name=%s", row.id, row.strategy_name)
            updated += 1
        db.commit()
    finally:
        db.close()
    return updated


def main() -> None:
    file_updated = migrate_builtin_files()
    db_updated = migrate_db()
    logger.info("迁移完成：内置文件 %d 个，DB 策略 %d 条", file_updated, db_updated)


if __name__ == "__main__":
    main()
