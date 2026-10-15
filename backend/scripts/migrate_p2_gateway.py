"""P2-1 迁移脚本：给 device_call_logs 加幂等键/关联键列（幂等，可重复执行）。

无 Alembic，create_all 不会给已存在表加列，故一次性 ALTER TABLE 补列 + 索引。

用法（在 backend 目录下，需可连数据库）:
    python -m scripts.migrate_p2_gateway
"""
import logging

from sqlalchemy import inspect, text

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_p2_gateway")

_NEW_COLUMNS = {
    "idempotency_key": "VARCHAR(128)",
    "correlation_id": "VARCHAR(128)",
}
_NEW_INDEXES = {
    "ix_device_call_logs_idempotency_key": "idempotency_key",
    "ix_device_call_logs_correlation_id": "correlation_id",
}


def migrate() -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        inspector = inspect(db.bind)
        existing_cols = {c["name"] for c in inspector.get_columns("device_call_logs")}

        for col, col_def in _NEW_COLUMNS.items():
            if col in existing_cols:
                logger.info("列已存在，跳过: %s", col)
                continue
            db.execute(text(f"ALTER TABLE device_call_logs ADD COLUMN {col} {col_def}"))
            logger.info("已加列: %s %s", col, col_def)

        for idx, col in _NEW_INDEXES.items():
            db.execute(text(f"CREATE INDEX IF NOT EXISTS {idx} ON device_call_logs ({col})"))
            logger.info("已建索引: %s", idx)

        db.commit()
        logger.info("device_call_logs 迁移完成")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
