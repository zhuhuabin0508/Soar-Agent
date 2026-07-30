"""安全模块：密码哈希、JWT 签发/校验、API Key 生成、轻量数据库迁移。

设计要点：
- 密码使用 passlib + bcrypt 哈希，永不存明文。
- JWT 使用 PyJWT（HS256），承载 user_id / username / role。
- Webhook secret 使用 secrets.token_hex 生成 32 字节十六进制串。
- 轻量迁移：由于未引入 Alembic（P1-5 待办），此处提供 ``ensure_columns``
  在启动时检查并 ALTER ADD 缺失列，保证新增字段在老库上可用。
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext
from sqlalchemy import inspect, text

from app.config import settings

logger = logging.getLogger(__name__)

# passlib 上下文：bcrypt 哈希（自动处理 salt 与版本）
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============ 密码哈希 ============

def hash_password(plain: str) -> str:
    """对明文密码做 bcrypt 哈希。"""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("密码校验异常: %s", exc)
        return False


# ============ JWT ============

def create_access_token(user_id: int, username: str, role: str) -> str:
    """签发 JWT 访问令牌。

    payload 包含 ``sub``（user_id）、``username``、``role``、``exp``、``iat``。
    有效期由 ``settings.JWT_EXPIRE_MINUTES`` 控制。
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    logger.info("签发 JWT: user_id=%s, username=%s, role=%s", user_id, username, role)
    return token


def decode_access_token(token: str) -> Optional[dict]:
    """解码并校验 JWT，返回 payload；失败返回 None。"""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT 已过期")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT 无效: %s", exc)
        return None


# ============ API Key / Webhook Secret ============

def generate_webhook_secret() -> str:
    """生成 32 字节十六进制 webhook 密钥（64 字符）。"""
    return secrets.token_hex(32)


def generate_api_key() -> str:
    """生成带前缀的 API Key（用于未来 per-user API Key 场景）。"""
    return f"soar_{secrets.token_urlsafe(32)}"


# ============ 轻量数据库迁移 ============

def ensure_columns(engine, table_name: str, columns: dict[str, str]) -> None:
    """检查并补齐缺失列（轻量迁移，避免引入 Alembic）。

    Args:
        engine: SQLAlchemy 引擎。
        table_name: 表名。
        columns: ``{列名: "SQL 类型定义"}``，如 ``{"enabled": "BOOLEAN NOT NULL DEFAULT TRUE"}``。
            仅当列不存在时执行 ``ALTER TABLE ... ADD COLUMN ...``。
    """
    insp = inspect(engine)
    if not insp.has_table(table_name):
        # 表不存在（create_all 会创建），跳过
        return
    existing = {col["name"] for col in insp.get_columns(table_name)}
    with engine.begin() as conn:
        for col_name, col_def in columns.items():
            if col_name in existing:
                continue
            stmt = f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" {col_def}'
            logger.info("轻量迁移: %s", stmt)
            conn.execute(text(stmt))
    logger.info("轻量迁移完成: table=%s, checked=%d", table_name, len(columns))


def run_lightweight_migrations(engine) -> None:
    """运行所有轻量迁移（启动时调用）。

    当前覆盖：
    - workflows 表新增 webhook_secret / enabled 列。
    - users 表新增 role_id / failed_login_count / locked_until 列。
    - executions 表新增 agent_id 列（智能体执行记录关联）。
    - knowledge_bases 表新增 Dify 风格配置列（分段/索引/检索）。
    - knowledge_documents 表新增 updated_at / segment_count 列。
    - agents 表新增 enabled_skills 列（启用的技能 id 列表，注入 system prompt）。
    - tools 表新增 tool_type / http_config / category 列。

    线程安全：使用 PostgreSQL advisory lock 防止多实例并发执行 DDL。
    锁 ID 77001 为本项目专用，避免与其他应用冲突。
    """
    # advisory lock：使用独立 raw connection 防止多实例并发 DDL
    # pg_try_advisory_lock 是 session 级锁，必须用同一连接解锁，所以不能用连接池
    lock_conn = engine.raw_connection()
    locked = False
    try:
        cursor = lock_conn.cursor()
        cursor.execute("SELECT pg_try_advisory_lock(77001)")
        locked = cursor.fetchone()[0]
        cursor.close()
        if not locked:
            logger.info("轻量迁移：另一实例正在执行，跳过")
            return
        ensure_columns(
            engine,
            "workflows",
            {
                "webhook_secret": "VARCHAR(64)",
                "enabled": "BOOLEAN NOT NULL DEFAULT TRUE",
            },
        )
        # users 表新增 role_id 列（关联 roles 表）
        ensure_columns(
            engine,
            "users",
            {"role_id": "INTEGER"},
        )
        # users 表新增等保安全字段：登录失败计数与锁定截止时间
        ensure_columns(
            engine,
            "users",
            {
                "failed_login_count": "INTEGER NOT NULL DEFAULT 0",
                "locked_until": "TIMESTAMP WITHOUT TIME ZONE",
            },
        )
        # executions 表新增 agent_id 列（智能体测试执行记录关联）
        ensure_columns(
            engine,
            "executions",
            {"agent_id": "INTEGER"},
        )
        # knowledge_bases 表新增 Dify 风格配置列
        ensure_columns(
            engine,
            "knowledge_bases",
            {
                "chunk_mode": "VARCHAR(32) NOT NULL DEFAULT 'auto'",
                "chunk_size": "INTEGER NOT NULL DEFAULT 500",
                "chunk_overlap": "INTEGER NOT NULL DEFAULT 50",
                "chunk_delimiter": "VARCHAR(256)",
                "ocr_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
                "index_mode": "VARCHAR(32) NOT NULL DEFAULT 'keyword'",
                "embedding_model": "VARCHAR(128) NOT NULL DEFAULT 'text-embedding-ada-002'",
                "embedding_dimension": "INTEGER NOT NULL DEFAULT 1536",
                "retrieval_top_k": "INTEGER NOT NULL DEFAULT 5",
                "score_threshold": "INTEGER NOT NULL DEFAULT 0",
                "rerank_enabled": "INTEGER NOT NULL DEFAULT 0",
                "rerank_model": "VARCHAR(128)",
                "hybrid_vector_weight": "INTEGER NOT NULL DEFAULT 70",
                "hybrid_keyword_weight": "INTEGER NOT NULL DEFAULT 30",
            },
        )
        # knowledge_documents 表新增 updated_at / segment_count 列 + 元数据/状态/权重
        ensure_columns(
            engine,
            "knowledge_documents",
            {
                "updated_at": "TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()",
                "segment_count": "INTEGER NOT NULL DEFAULT 1",
                "description": "TEXT",
                "category": "VARCHAR(255)",
                "tags": "JSON",
                "effective_from": "TIMESTAMP WITHOUT TIME ZONE",
                "effective_to": "TIMESTAMP WITHOUT TIME ZONE",
                "status": "VARCHAR(32) NOT NULL DEFAULT 'available'",
                "retrieval_weight": "INTEGER NOT NULL DEFAULT 1",
                "file_path": "VARCHAR(512)",
            },
        )
        # agents 表新增基础形象 / 模型参数扩展 / 记忆与高级机制字段
        ensure_columns(
            engine,
            "agents",
            {
                "avatar": "VARCHAR(512)",
                "greeting": "TEXT",
                "suggested_questions": "JSON",
                "context_turns": "INTEGER NOT NULL DEFAULT 10",
                "enable_memory": "BOOLEAN NOT NULL DEFAULT FALSE",
                "tone_style": "VARCHAR(32) NOT NULL DEFAULT 'professional'",
                "variables": "JSON",
                "tool_configs": "JSON",
                # 启用的技能 id 列表（注入到 system prompt，见 app/agent/prompt_assembler.py）
                "enabled_skills": "JSON",
                # 执行引擎选择：langgraph（默认）| hermes
                "engine": "VARCHAR(16) NOT NULL DEFAULT 'langgraph'",
            },
        )
        # tools 表新增声明式 HTTP 工具支持：tool_type + http_config + category
        ensure_columns(
            engine,
            "tools",
            {
                "tool_type": "VARCHAR(32) NOT NULL DEFAULT 'code'",
                "http_config": "JSON",
                "category": "VARCHAR(64)",
            },
        )
        # llm_configs 表新增 model_type 列（chat / embedding），区分对话模型与向量化模型
        ensure_columns(
            engine,
            "llm_configs",
            {"model_type": "VARCHAR(32) NOT NULL DEFAULT 'chat'"},
        )
        # banned_ips 表新增 source 列（来源标识：manual=手动添加，agent=智能体添加）
        ensure_columns(
            engine,
            "banned_ips",
            {"source": "VARCHAR(20) NOT NULL DEFAULT 'agent'"},
        )
        # knowledge_bases 表新增 embedding_config_id 列（关联 embedding 类型 LLMConfig）
        ensure_columns(
            engine,
            "knowledge_bases",
            {"embedding_config_id": "INTEGER"},
        )
        # agent_memories 表 GIN 索引（中文全文检索）
        # 表本身由 Base.metadata.create_all 创建，但 GIN 索引需原生 SQL
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_agent_memories_tsv "
                    "ON agent_memories USING gin(to_tsvector('chinese', content))"
                ))
                logger.info("轻量迁移: agent_memories GIN 索引已确保存在")
        except Exception as exc:  # noqa: BLE001
            # 中文分词配置可能不存在（如 SQLite 测试环境），降级用 ILIKE
            logger.warning("agent_memories GIN 索引创建失败（降级为 ILIKE 检索）: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("轻量迁移失败（忽略继续）: %s", exc)
    finally:
        if locked:
            try:
                cursor = lock_conn.cursor()
                cursor.execute("SELECT pg_advisory_unlock(77001)")
                cursor.close()
                lock_conn.commit()
            except Exception:  # noqa: BLE001
                pass
        lock_conn.close()
