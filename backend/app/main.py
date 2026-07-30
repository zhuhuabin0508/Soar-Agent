"""FastAPI 应用入口。

创建 ``SOAR Platform API`` 应用，配置 CORS、挂载 ``/api/v1`` 路由，
并在启动时建表、运行轻量迁移与种子内置工具模板。

安全说明（P0-1/P0-2 升级）：
- CORS 不再使用 ``allow_origins=["*"]``，改为从 ``settings.CORS_ORIGINS`` 读取白名单。
- 引入 slowapi 限流器，供 webhook 等高风险端点使用。
- 启动时运行轻量迁移（补齐 workflows 表的 webhook_secret/enabled 列）。
- 启动时种子默认 admin 用户（首次启动）。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1 import api_router
from app.config import settings

# 统一日志格式（便于调试）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _init_db() -> None:
    """建表、运行轻量迁移并种子内置工具模板与默认 admin 用户（幂等）。

    使用 ``Base.metadata.create_all`` 自动建表；
    随后运行 ``run_lightweight_migrations`` 补齐新增列（如 webhook_secret）；
    最后种子默认工具模板与 admin 用户。
    """
    from app.core.security import run_lightweight_migrations
    from app.core.tool_templates import TOOL_TEMPLATES
    from app.database import Base, SessionLocal, engine
    import app.models  # noqa: F401  触发 ORM 注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
    logger.info("DB tables ensured via Base.metadata.create_all")

    # 轻量迁移：补齐新增列（不引入 Alembic 的过渡方案）
    run_lightweight_migrations(engine)

    db = SessionLocal()
    try:
        from app.models.tool import Tool

        # 按 name 补齐缺失的内置工具模板（空表全量种子，已有表补齐新增模板）
        existing_names = {t.name for t in db.query(Tool).all()}
        new_added = 0
        for tpl in TOOL_TEMPLATES:
            if tpl["name"] in existing_names:
                continue
            tool = Tool(
                name=tpl["name"],
                description=tpl.get("description", ""),
                parameters_schema=tpl.get("parameters_schema"),
                code=tpl.get("code", ""),
                enabled=True,
            )
            db.add(tool)
            new_added += 1
        if new_added > 0:
            db.commit()
            logger.info("已补齐 %d 个内置工具模板（共 %d 个模板）", new_added, len(TOOL_TEMPLATES))
        else:
            logger.info("内置工具模板已齐全（%d 个），无需补齐", len(TOOL_TEMPLATES))

        # 种子默认 admin 用户（仅当 users 表为空时）
        _seed_admin_user(db)

        # 种子默认角色（独立调用，确保 roles 表在老库升级时也能补齐）
        _seed_default_roles(db)
    finally:
        db.close()


def _seed_admin_user(db) -> None:
    """首次启动时种子默认 admin 账号。

    账号密码由 ``settings.SEED_ADMIN_USERNAME`` / ``SEED_ADMIN_PASSWORD`` 控制。
    若 users 表已有数据则跳过。
    """
    from app.core.security import hash_password
    from app.models.user import User

    if db.query(User).count() > 0:
        logger.info("Users 表已有数据，跳过 admin 种子")
        return

    admin = User(
        username=settings.SEED_ADMIN_USERNAME,
        password_hash=hash_password(settings.SEED_ADMIN_PASSWORD),
        display_name="系统管理员",
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    logger.warning(
        "已种子默认管理员账号: username=%s, password=%s（请立即登录修改密码！）",
        settings.SEED_ADMIN_USERNAME,
        settings.SEED_ADMIN_PASSWORD,
    )

    # 种子默认角色（admin 用户种子后执行）
    _seed_default_roles(db)


def _seed_default_roles(db) -> None:
    """首次启动时种子默认角色（admin/analyst/viewer）。

    仅当 roles 表为空时执行，不覆盖用户自定义角色。
    种子后自动为 admin 用户关联 admin 角色 ID。
    """
    from app.core.permissions import DEFAULT_ROLES
    from app.models.role import Role
    from app.models.user import User

    if db.query(Role).count() > 0:
        logger.info("Roles 表已有数据，跳过角色种子")
        return

    for role_data in DEFAULT_ROLES:
        role = Role(
            name=role_data["name"],
            description=role_data.get("description"),
            permissions=role_data.get("permissions", {}),
            is_system=role_data.get("is_system", False),
        )
        db.add(role)
    db.commit()
    logger.info("已种子 %d 个默认角色", len(DEFAULT_ROLES))

    # 为已存在的 admin 用户关联 admin 角色 ID
    admin_user = db.query(User).filter(User.role == "admin").first()
    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if admin_user and admin_role:
        admin_user.role_id = admin_role.id
        db.commit()
        logger.info("已为 admin 用户关联 admin 角色ID: %s", admin_role.id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表并种子数据。"""
    logger.info("SOAR API starting...")
    try:
        _init_db()
    except Exception as exc:  # noqa: BLE001
        # 建表失败不应阻断 API 启动（例如 DB 暂未就绪时仍允许健康检查）
        logger.warning("启动初始化失败（忽略，继续启动）: %s", exc)
    # 推送系统更新通知（版本变化时广播到通知中心）
    try:
        from app.core.changelog import notify_system_update
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            notify_system_update(db)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("更新通知推送失败（忽略）: %s", exc)
    yield


from app.core.changelog import CURRENT_VERSION  # noqa: E402

app = FastAPI(title="SOAR Platform API", version=CURRENT_VERSION, lifespan=lifespan)

# ============ 限流器（slowapi）============
# 限流器实例在 app.core.limiter 中定义（独立模块避免循环导入），
# 此处挂到 app.state 并注册异常处理器与中间件。
from app.core.limiter import limiter  # noqa: E402

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ============ CORS（P0-1 修复：白名单 + 关闭通配）============
# 解析 settings.CORS_ORIGINS（逗号分隔）为列表
_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
logger.info("CORS 允许源: %s", _cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 全局审计中间件（记录用户所有写操作：模块+IP+结果）============
from app.core.audit import audit_middleware  # noqa: E402


@app.middleware("http")
async def _audit_middleware(request, call_next):
    """记录用户写操作到审计日志（操作者/模块/资源ID/IP/结果）。"""
    return await audit_middleware(request, call_next)

# 所有业务路由统一前缀 /api/v1
app.include_router(api_router, prefix="/api/v1")


# ============ 公开端点：版本号（供前端左下角显示，无需认证）============
@app.get("/api/v1/version")
def get_version():
    """返回当前系统版本号与平台名称（供前端左下角与页签显示）。"""
    from app.database import SessionLocal
    from app.models.system_config import SystemConfig
    db = SessionLocal()
    try:
        cfg = db.query(SystemConfig).filter(SystemConfig.key == "platform_name").first()
        platform_name = cfg.value if cfg else "SOAR 平台"
    finally:
        db.close()
    return {"version": CURRENT_VERSION, "platform_name": platform_name}

# ============ WebSocket 端点：执行进度实时推送 ============
from fastapi import WebSocket as _WS  # noqa: E402
from app.core.ws_manager import ws_manager  # noqa: E402


@app.websocket("/ws/executions/{execution_id}")
async def ws_execution_progress(websocket: _WS, execution_id: int) -> None:
    """WebSocket 端点：客户端连接后订阅指定 execution_id 的执行进度。

    推送的消息类型：
    - ``{"type": "log", "node_id": "...", "level": "info", "message": "..."}``
    - ``{"type": "trace", "node_id": "...", "node_type": "...", "status": "success", ...}``
    - ``{"type": "status", "execution_id": N, "status": "success"/"failed"}``
    """
    await ws_manager.connect(execution_id, websocket)
    try:
        # 保持连接，等待服务端推送；客户端也可发送心跳
        while True:
            await websocket.receive_text()
    except Exception:
        ws_manager.disconnect(execution_id, websocket)
