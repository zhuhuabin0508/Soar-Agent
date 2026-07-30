"""SQLAlchemy 数据库引擎、会话工厂与声明式基类。"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

logger.info("Initializing database engine: %s", settings.DATABASE_URL)

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 所有 ORM 模型的共同基类
Base = declarative_base()


def get_db():
    """FastAPI 依赖：提供数据库会话，并在请求结束后自动关闭。"""
    db = SessionLocal()
    try:
        logger.debug("Opening DB session")
        yield db
    finally:
        logger.debug("Closing DB session")
        db.close()
