"""Webhook 路由：接收告警 payload 并触发工作流异步执行。

安全防护（P0-2）：
1. **per-workflow 密钥校验**：请求需携带 ``X-Webhook-Secret`` 头，与 workflow.webhook_secret 比对。
2. **限流**：每个客户端 IP 限 ``settings.WEBHOOK_RATE_LIMIT_PER_MINUTE`` 次/分钟。
3. **payload 大小限制**：超过 ``settings.WEBHOOK_MAX_BODY_BYTES`` 拒绝。
4. **启用开关**：workflow.enabled 为 False 时返回 404，禁止触发。
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.core.limiter import limiter
from app.database import get_db
from app.dependencies import verify_webhook_secret
from app.models import Execution, Workflow
from app.tasks.workflow_tasks import execute_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/{workflow_id}")
@limiter.limit(f"{settings.WEBHOOK_RATE_LIMIT_PER_MINUTE}/minute")
async def trigger_workflow(
    request: Request,
    workflow_id: int,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict:
    """接收告警 payload，创建执行记录并触发 Celery 异步执行。

    安全校验：
    - workflow 必须存在且 ``enabled=True``，否则 404。
    - 请求头 ``X-Webhook-Secret`` 必须与 ``workflow.webhook_secret`` 匹配。
    - payload 字节数不超过 ``settings.WEBHOOK_MAX_BODY_BYTES``。
    - 限流：每 IP 每分钟 ``settings.WEBHOOK_RATE_LIMIT_PER_MINUTE`` 次。

    Args:
        request: FastAPI Request（限流器依赖）。
        workflow_id: 目标工作流 ID。
        payload: 任意告警 JSON 数据（已由 FastAPI 解析为 dict）。
        db: 数据库会话。

    Returns:
        ``{"execution_id": ..., "status": "running"}``。
    """
    client_ip = request.client.host if request.client else "unknown"
    logger.info("Webhook received: workflow_id=%s, client=%s", workflow_id, client_ip)

    # payload 大小校验（基于 content-length）
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.WEBHOOK_MAX_BODY_BYTES:
        logger.warning(
            "Webhook payload 过大: workflow_id=%s, content_length=%s, limit=%s",
            workflow_id, content_length, settings.WEBHOOK_MAX_BODY_BYTES,
        )
        raise HTTPException(status_code=413, detail="请求体过大，超过 webhook 上限")

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if workflow is None:
        logger.warning("Workflow not found: id=%s", workflow_id)
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not workflow.enabled:
        logger.warning("Workflow disabled, webhook rejected: id=%s", workflow_id)
        raise HTTPException(status_code=404, detail="Workflow not found")

    # per-workflow 密钥校验
    verify_webhook_secret(workflow, request.headers.get("X-Webhook-Secret"))

    logger.debug("Webhook payload: %s", payload)

    # 创建执行记录，初始状态 pending
    execution = Execution(workflow_id=workflow_id, status="pending")
    db.add(execution)
    db.commit()
    db.refresh(execution)
    logger.info("Execution created: id=%s, status=pending", execution.id)

    # 异步派发 Celery 任务（传入 execution_id 以便回写状态与节点轨迹）
    execute_workflow.delay(workflow_id, payload, workflow.graph_config, execution.id)
    logger.info(
        "Celery task dispatched: workflow_id=%s, execution_id=%s",
        workflow_id,
        execution.id,
    )

    return {"execution_id": execution.id, "status": "running"}
