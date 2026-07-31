"""Celery 应用实例与配置。

broker / backend 均指向 Redis，时区设置为 ``Asia/Shanghai``。
启动时会自动发现 ``app`` 包下的 ``tasks`` 模块。
"""
import logging

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

logger.info(
    "Creating Celery app: broker=%s, backend=%s",
    settings.CELERY_BROKER_URL,
    settings.CELERY_RESULT_BACKEND,
)

celery_app = Celery(
    "soar_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    worker_log_format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    worker_task_log_format=(
        "[%(asctime)s] [%(levelname)s] [%(task_name)s(%(task_id)s)] %(message)s"
    ),
    # P0-5：任务超时保护，防止死循环节点或卡住的 AI 调用永久占用 worker
    # soft_time_limit：软超时（300s），抛 SoftTimeLimitExceeded，任务可捕获清理
    # time_limit：硬超时（360s），worker 强制终止任务
    task_soft_time_limit=300,
    task_time_limit=360,
    # 任务确认延迟到执行完成，worker 崩溃时任务会被重新投递
    task_acks_late=True,
    # worker 并发数（默认 4，可根据机器调整）
    worker_concurrency=4,
    # 预取策略：一次只预取 1 个任务，避免长任务时其他 worker 空闲
    worker_prefetch_multiplier=1,
    # 任务失败最大重试次数（0 = 不自动重试，由业务逻辑控制）
    task_default_max_retries=0,
)

# ============================================================================
# Celery Beat 定时任务调度
# ============================================================================
# beat 服务通过 `celery -A app.core.celery_app beat` 启动（见 docker-compose beat 服务）。
# 每个条目：{"task-name": {"task": "celery_task_name", "schedule": crontab(...)}}
from celery.schedules import crontab  # noqa: E402

celery_app.conf.beat_schedule = {
    # 资产管理智能体定时扫描：每小时整点检查新知识库并自动梳理资产
    "scan-asset-agents-hourly": {
        "task": "scan_asset_agents",
        "schedule": crontab(minute=0),  # 每小时整点执行
    },
}

# 自动发现 app 包下的 tasks 模块（即 app.tasks）
celery_app.autodiscover_tasks(["app"])

logger.info("Celery app configured and tasks autodiscovered")
