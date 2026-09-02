"""内置解析策略注册。

启动时若 parse_strategies 表中无对应内置策略则自动插入。
内置策略 JSON 存放于 ``app/engine/strategies/`` 目录。

新增内置策略：把 JSON 放入 strategies 目录并在 ``BUILTIN_STRATEGIES`` 中登记文件名。
"""
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 内置策略文件清单（strategies 目录下的文件名）
BUILTIN_STRATEGIES = [
    "sangfor_xdr_v130.json",
]

_STRATEGY_DIR = Path(__file__).parent / "strategies"


def load_builtin_strategy(filename: str) -> dict[str, Any] | None:
    """读取内置策略 JSON 文件，返回策略配置 dict；读取失败返回 None。"""
    path = _STRATEGY_DIR / filename
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        logger.exception("内置策略文件读取失败: %s", path)
        return None


def seed_builtin_strategies(db: Session) -> None:
    """把内置策略注册到 parse_strategies 表（按 strategy_name 幂等）。"""
    from app.models.parse_strategy import ParseStrategy

    for filename in BUILTIN_STRATEGIES:
        config = load_builtin_strategy(filename)
        if not config:
            continue
        name = config.get("strategy_name") or ""
        if not name:
            logger.warning("内置策略 %s 缺少 strategy_name，跳过", filename)
            continue
        exists = db.query(ParseStrategy).filter(ParseStrategy.strategy_name == name).first()
        if exists:
            # 已存在：仅当表内 config 与内置文件不一致时更新（保证内置策略可随版本升级）
            if (exists.config or "") != json.dumps(config, ensure_ascii=False):
                exists.config = json.dumps(config, ensure_ascii=False)
                exists.version = config.get("version", exists.version)
                exists.device_type = config.get("device_type", exists.device_type)
                db.add(exists)
                logger.info("内置策略已更新: %s", name)
            continue
        strat = ParseStrategy(
            strategy_name=name,
            device_type=config.get("device_type", ""),
            version=str(config.get("version", "1.0")),
            status=config.get("status", "enabled"),
            config=json.dumps(config, ensure_ascii=False),
        )
        db.add(strat)
        logger.info("内置策略已注册: %s", name)
    db.commit()
