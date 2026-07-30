"""Workflow CRUD 路由 + 测试执行（test-run / test-node）。

安全说明（P0-1）：所有路由通过 router 级 ``dependencies=[Depends(get_current_user)]``
强制 JWT 登录。webhook 触发不需要登录（走 per-workflow secret）。
"""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.node_executors import execute_node
from app.core.security import generate_webhook_secret
from app.core.workflow_runner import run_workflow
from app.core.workflow_validator import validate_workflow
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Execution, ExecutionLog, ExecutionTrace, Workflow
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowListItem,
    WorkflowOut,
    WorkflowUpdate,
)

logger = logging.getLogger(__name__)

# router 级鉴权：所有工作流管理接口强制登录
router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Depends(get_current_user)],
)


@router.post("", response_model=WorkflowOut, status_code=201)
def create_workflow(
    workflow: WorkflowCreate, db: Session = Depends(get_db)
) -> Workflow:
    """创建工作流，自动生成 webhook 密钥。"""
    logger.info("Creating workflow: name=%s", workflow.name)
    db_workflow = Workflow(
        name=workflow.name,
        graph_config=workflow.graph_config,
        enabled=workflow.enabled,
        webhook_secret=generate_webhook_secret(),
    )
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    logger.info("Workflow created: id=%s", db_workflow.id)
    return db_workflow


@router.get("", response_model=list[WorkflowListItem])
def list_workflows(db: Session = Depends(get_db)) -> list[Workflow]:
    """列出所有工作流（列表不返回 webhook_secret，避免泄露）。"""
    logger.info("Listing all workflows")
    workflows = db.query(Workflow).all()
    logger.info("Found %d workflows", len(workflows))
    return workflows


class ValidateRequest(BaseModel):
    """工作流校验请求体。"""

    graph_config: dict[str, Any] = Field(..., description="工作流图配置，含 nodes 与 edges")


@router.post("/validate")
def validate_workflow_endpoint(body: ValidateRequest) -> dict:
    """校验工作流图配置的可运行性，返回 errors/warnings。

    不查库，纯结构校验，供前端在保存/运行前调用。
    """
    logger.info("校验工作流图配置")
    return validate_workflow(body.graph_config)


@router.get("/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: int, db: Session = Depends(get_db)) -> Workflow:
    """获取单个工作流详情（含 webhook_secret，供前端展示与触发配置）。"""
    logger.info("Fetching workflow: id=%s", workflow_id)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        logger.warning("Workflow not found: id=%s", workflow_id)
        raise HTTPException(status_code=404, detail="Workflow not found")
    return db_workflow


@router.put("/{workflow_id}", response_model=WorkflowOut)
def update_workflow(
    workflow_id: int,
    workflow: WorkflowUpdate,
    db: Session = Depends(get_db),
) -> Workflow:
    """更新工作流（支持 name / graph_config / enabled 字段）。"""
    logger.info("Updating workflow: id=%s", workflow_id)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        logger.warning("Workflow not found for update: id=%s", workflow_id)
        raise HTTPException(status_code=404, detail="Workflow not found")

    update_data = workflow.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_workflow, key, value)
        logger.debug("Updating field %s for workflow %s", key, workflow_id)

    db.commit()
    db.refresh(db_workflow)
    logger.info("Workflow updated: id=%s", db_workflow.id)
    return db_workflow


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)) -> None:
    """删除工作流。"""
    logger.info("Deleting workflow: id=%s", workflow_id)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        logger.warning("Workflow not found for delete: id=%s", workflow_id)
        raise HTTPException(status_code=404, detail="Workflow not found")

    db.delete(db_workflow)
    db.commit()
    logger.info("Workflow deleted: id=%s", workflow_id)
    return None


@router.post("/{workflow_id}/reset-secret", response_model=WorkflowOut)
def reset_webhook_secret(
    workflow_id: int, db: Session = Depends(get_db)
) -> Workflow:
    """重置工作流的 webhook 密钥（旧密钥立即失效）。

    用于密钥泄露后的快速轮换。重置后前端需更新外部系统的 webhook 配置。
    """
    logger.info("Resetting webhook secret: workflow_id=%s", workflow_id)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db_workflow.webhook_secret = generate_webhook_secret()
    db.commit()
    db.refresh(db_workflow)
    logger.info("Webhook secret reset: workflow_id=%s", workflow_id)
    return db_workflow


class TestRunRequest(BaseModel):
    """工作流测试运行请求体。"""

    payload: dict[str, Any] = Field(default_factory=dict, description="触发 payload")


class TestNodeRequest(BaseModel):
    """节点测试请求体。"""

    node: dict[str, Any] = Field(..., description="节点定义，含 id/type/data")
    input_data: dict[str, Any] = Field(default_factory=dict, description="节点输入数据")


@router.post("/{workflow_id}/test-run")
async def test_run_workflow(
    workflow_id: int, body: TestRunRequest, db: Session = Depends(get_db)
) -> dict:
    """测试运行整个工作流，写入 Execution（trigger_type=test_run）与 ExecutionLog。"""
    logger.info("测试运行工作流: id=%s", workflow_id)
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 创建执行记录（测试触发）
    execution = Execution(
        workflow_id=workflow_id,
        status="running",
        trigger_type="test_run",
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    def log_callback(node_id: str, level: str, message: str) -> None:
        logger.debug("[test-run] %s/%s: %s", node_id, level, message)
        # 通过 WebSocket 实时推送日志
        from app.core.ws_manager import ws_manager
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ws_manager.broadcast(execution.id, {
                    "type": "log",
                    "node_id": node_id,
                    "level": level,
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                }))
        except RuntimeError:
            pass

    try:
        result = await run_workflow(
            graph_config=workflow.graph_config,
            payload=body.payload,
            log_callback=log_callback,
            trigger_type="test_run",
            execution_id=execution.id,
            workflow_id=workflow_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("测试运行异常: %s", exc)
        execution.status = "failed"
        execution.result = {"error": str(exc)}
        execution.finished_at = datetime.now()
        db.commit()
        raise HTTPException(status_code=500, detail=f"workflow run failed: {exc}")

    status = result.get("status", "success")
    traces = result.get("traces", [])
    logs = result.get("logs", [])

    # 写入节点轨迹
    for trace in traces:
        db_trace = ExecutionTrace(
            execution_id=execution.id,
            node_id=trace.get("node_id"),
            node_type=trace.get("node_type"),
            input=trace.get("input"),
            output=trace.get("output"),
            status=trace.get("status", "success"),
        )
        db.add(db_trace)
    # 写入执行日志
    for log_entry in logs:
        db_log = ExecutionLog(
            execution_id=execution.id,
            node_id=log_entry.get("node_id"),
            level=log_entry.get("level", "info"),
            message=log_entry.get("message", ""),
        )
        db.add(db_log)

    execution.status = status
    execution.result = {"context": result.get("ctx", {})}
    execution.finished_at = datetime.now()
    db.commit()
    db.refresh(execution)

    # 通过 WebSocket 推送最终状态与 trace
    from app.core.ws_manager import ws_manager
    await ws_manager.broadcast(execution.id, {
        "type": "status",
        "execution_id": execution.id,
        "status": status,
        "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
    })
    for trace in traces:
        await ws_manager.broadcast(execution.id, {"type": "trace", **trace})

    logger.info("测试运行完成: execution_id=%s, status=%s", execution.id, status)
    return {
        "execution_id": execution.id,
        "status": status,
        "traces": traces,
        "logs": logs,
    }


@router.post("/test-node")
async def test_node(body: TestNodeRequest) -> dict:
    """测试单个节点，不写 Execution，仅返回 output 与 logs。"""
    logger.info("测试单节点: node=%s", body.node.get("id"))
    node = body.node or {}
    node_id = str(node.get("id", "test"))
    node_type = node.get("type", "unknown")
    node_data = {**(node.get("data", {}) or {}), "id": node_id}

    logs: list[dict[str, str]] = []

    def log(nid: str, level: str, message: str) -> None:
        logs.append({"node_id": nid or node_id, "level": level, "message": message})

    ctx: dict[str, Any] = {"payload": body.input_data}
    try:
        output = await execute_node(node_type, node_data, body.input_data, ctx, log)
        node_logs = logs
    except Exception as exc:  # noqa: BLE001
        logger.exception("节点测试异常: %s", exc)
        output = {"error": str(exc)}
        node_logs = logs + [{"node_id": node_id, "level": "error", "message": str(exc)}]

    return {"output": output, "logs": node_logs}
