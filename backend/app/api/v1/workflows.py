"""Workflow CRUD 路由 + 测试执行（test-run / test-node）。

安全说明（P0-1）：所有路由通过 router 级 ``dependencies=[Depends(get_current_user)]``
强制 JWT 登录。webhook 触发不需要登录（走 per-workflow secret）。
"""
import logging
from datetime import datetime, timedelta
from app.core.timezone import beijing_now, beijing_now_iso
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, case, extract
from sqlalchemy.orm import Session

from app.core.node_executors import execute_node
from app.core.security import (
    decrypt_env_value,
    encrypt_env_value,
    generate_webhook_secret,
)
from app.core.workflow_runner import run_workflow
from app.core.workflow_validator import validate_workflow
from app.database import get_db
from app.dependencies import check_resource_ownership, compute_can_edit_ids, get_current_user
from app.models import Execution, ExecutionLog, ExecutionTrace, Workflow
from app.models.user import User
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
    workflow: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Workflow:
    """创建工作流，自动生成 webhook 密钥。"""
    logger.info("Creating workflow: name=%s", workflow.name)
    db_workflow = Workflow(
        name=workflow.name,
        graph_config=workflow.graph_config,
        enabled=workflow.enabled,
        webhook_secret=generate_webhook_secret(),
        trigger_type=workflow.trigger_type,
        category=workflow.category,
        tags=workflow.tags,
        favorite=workflow.favorite,
        status=workflow.status,
        description=workflow.description,
        created_by=current_user.id,
    )
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    logger.info("Workflow created: id=%s", db_workflow.id)
    return db_workflow


def _build_workflow_stats(db: Session, workflow_ids: list[int]) -> dict[int, dict[str, Any]]:
    """批量计算工作流运行统计：最近运行状态/时间、今日次数、7天成功率、平均耗时。

    Args:
        db: 数据库会话。
        workflow_ids: 工作流 ID 列表。

    Returns:
        ``{workflow_id: {last_run_status, last_run_at, today_count,
                        success_rate_7d, avg_duration_seconds}}``。
    """
    if not workflow_ids:
        return {}
    now = beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_7d = now - timedelta(days=7)

    # 最近一次执行（按 workflow_id 分组取最新）
    latest_rows = (
        db.query(
            Execution.workflow_id,
            Execution.status,
            Execution.created_at,
        )
        .filter(Execution.workflow_id.in_(workflow_ids))
        .order_by(Execution.workflow_id, Execution.created_at.desc())
        .all()
    )
    latest_map: dict[int, dict[str, Any]] = {}
    for wid, status, created_at in latest_rows:
        if wid not in latest_map:
            latest_map[wid] = {
                "last_run_status": status,
                "last_run_at": created_at,
            }

    # 今日执行次数
    today_q = (
        db.query(Execution.workflow_id, func.count(Execution.id))
        .filter(
            Execution.workflow_id.in_(workflow_ids),
            Execution.created_at >= today_start,
        )
        .group_by(Execution.workflow_id)
        .all()
    )
    today_map = {wid: cnt for wid, cnt in today_q}

    # 最近 7 天统计：总数、成功数、平均耗时
    stats_q = (
        db.query(
            Execution.workflow_id,
            func.count(Execution.id).label("total"),
            func.sum(case((Execution.status == "success", 1), else_=0)).label("success"),
            func.avg(
                extract("epoch", Execution.finished_at - Execution.created_at)
            ).label("avg_dur"),
        )
        .filter(
            Execution.workflow_id.in_(workflow_ids),
            Execution.created_at >= since_7d,
            Execution.finished_at.isnot(None),
        )
        .group_by(Execution.workflow_id)
        .all()
    )
    stats_map: dict[int, dict[str, Any]] = {}
    for wid, total, success, avg_dur in stats_q:
        total_i = int(total or 0)
        success_i = int(success or 0)
        rate = round(success_i / total_i, 4) if total_i > 0 else 0.0
        stats_map[wid] = {
            "success_rate_7d": rate,
            "avg_duration_seconds": round(float(avg_dur or 0), 2),
        }

    # 考虑最近 7 天无完成记录但今日有 running/failed 的情况
    # 对于 7 天无 finished_at 但有执行的工作流，补 0 统计
    all_recent_q = (
        db.query(
            Execution.workflow_id,
            func.count(Execution.id).label("total"),
            func.sum(case((Execution.status == "success", 1), else_=0)).label("success"),
        )
        .filter(
            Execution.workflow_id.in_(workflow_ids),
            Execution.created_at >= since_7d,
        )
        .group_by(Execution.workflow_id)
        .all()
    )
    for wid, total, success in all_recent_q:
        if wid not in stats_map:
            total_i = int(total or 0)
            success_i = int(success or 0)
            rate = round(success_i / total_i, 4) if total_i > 0 else 0.0
            stats_map[wid] = {
                "success_rate_7d": rate,
                "avg_duration_seconds": 0.0,
            }

    result: dict[int, dict[str, Any]] = {}
    for wid in workflow_ids:
        latest = latest_map.get(wid, {})
        stats = stats_map.get(wid, {})
        result[wid] = {
            "last_run_status": latest.get("last_run_status"),
            "last_run_at": latest.get("last_run_at"),
            "today_count": today_map.get(wid, 0),
            "success_rate_7d": stats.get("success_rate_7d"),
            "avg_duration_seconds": stats.get("avg_duration_seconds"),
        }
    return result


@router.get("", response_model=list[WorkflowListItem])
def list_workflows(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """列出所有工作流（列表不返回 webhook_secret，避免泄露）。

    返回字段扩展：触发方式、分类、标签、收藏、状态、描述，
    以及运行统计（最近运行状态/时间、今日次数、7天成功率、平均耗时）。
    每项附带 ``can_edit`` 标志（admin/owner/被授权用户为 True）。
    """
    logger.info("Listing all workflows")
    workflows = db.query(Workflow).all()
    logger.info("Found %d workflows", len(workflows))

    workflow_ids = [w.id for w in workflows]
    stats_map = _build_workflow_stats(db, workflow_ids)
    # 资源级 owner 控制：批量查共享授权集合，admin 在调用处直接判 True
    shared_ids = compute_can_edit_ids(db, current_user, "workflow", workflow_ids)

    result = []
    for w in workflows:
        item = {
            "id": w.id,
            "name": w.name,
            "enabled": w.enabled,
            "trigger_type": w.trigger_type,
            "category": w.category,
            "tags": w.tags,
            "favorite": w.favorite,
            "status": w.status,
            "description": w.description,
            "created_by": w.created_by,
            "created_at": w.created_at,
            "updated_at": w.updated_at,
            # 资源级 owner 控制：admin / owner / 被授权用户可编辑
            "can_edit": (
                current_user.role == "admin"
                or w.created_by == current_user.id
                or w.id in shared_ids
            ),
        }
        item.update(stats_map.get(w.id, {}))
        result.append(item)
    # 收藏置顶：favorite=True 优先排序
    result.sort(key=lambda x: (not x.get("favorite", False), x.get("id", 0)))
    return result


@router.patch("/{workflow_id}/favorite", response_model=WorkflowOut)
def toggle_favorite(workflow_id: int, db: Session = Depends(get_db)) -> Workflow:
    """切换工作流收藏状态（常用工作流置顶）。"""
    logger.info("Toggling favorite: workflow_id=%s", workflow_id)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db_workflow.favorite = not db_workflow.favorite
    db.commit()
    db.refresh(db_workflow)
    return db_workflow


class StatusUpdateRequest(BaseModel):
    """工作流状态变更请求体。"""

    status: str = Field(..., description="目标状态：draft / published / disabled")


@router.patch("/{workflow_id}/status", response_model=WorkflowOut)
def update_status(
    workflow_id: int, body: StatusUpdateRequest, db: Session = Depends(get_db)
) -> Workflow:
    """更新工作流生命周期状态（草稿/已发布/已停用）。"""
    if body.status not in ("draft", "published", "disabled"):
        raise HTTPException(status_code=400, detail="status 必须为 draft / published / disabled")
    logger.info("Updating status: workflow_id=%s, status=%s", workflow_id, body.status)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db_workflow.status = body.status
    # 已停用时同步禁用触发（webhook 触发返回 404）
    if body.status == "disabled":
        db_workflow.enabled = False
    elif body.status == "published":
        db_workflow.enabled = True
    db.commit()
    db.refresh(db_workflow)
    return db_workflow


class TagsUpdateRequest(BaseModel):
    """工作流标签更新请求体。"""

    tags: list[str] = Field(default_factory=list, description="标签数组")
    category: Optional[str] = Field(None, description="业务场景分类")


@router.patch("/{workflow_id}/tags", response_model=WorkflowOut)
def update_tags(
    workflow_id: int, body: TagsUpdateRequest, db: Session = Depends(get_db)
) -> Workflow:
    """更新工作流标签与分类。"""
    logger.info("Updating tags: workflow_id=%s, tags=%s, category=%s", workflow_id, body.tags, body.category)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db_workflow.tags = body.tags
    if body.category is not None:
        db_workflow.category = body.category
    db.commit()
    db.refresh(db_workflow)
    return db_workflow


class ImportRequest(BaseModel):
    """工作流导入请求体。"""

    name: Optional[str] = Field(None, description="导入后的工作流名称（为空则用导出名_导入）")
    graph_config: dict[str, Any] = Field(..., description="导入的工作流图配置")
    trigger_type: str = Field("webhook", description="触发方式")
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    description: Optional[str] = None


@router.post("/import", response_model=WorkflowOut, status_code=201)
def import_workflow(body: ImportRequest, db: Session = Depends(get_db)) -> Workflow:
    """导入工作流（从 JSON/YAML 导出文件恢复）。

    不复制 webhook_secret（新建一个），不复制 ID（自增）。
    """
    logger.info("Importing workflow: name=%s", body.name)
    name = body.name or "导入的工作流"
    db_workflow = Workflow(
        name=name,
        graph_config=body.graph_config,
        enabled=True,
        webhook_secret=generate_webhook_secret(),
        trigger_type=body.trigger_type,
        category=body.category,
        tags=body.tags,
        favorite=False,
        status="draft",  # 导入后默认为草稿，需手动发布
        description=body.description,
    )
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    logger.info("Workflow imported: id=%s", db_workflow.id)
    return db_workflow


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
def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowOut:
    """获取单个工作流详情（含 webhook_secret，供前端展示与触发配置）。

    附带 ``can_edit`` 标志（admin/owner/被授权用户为 True）。
    """
    logger.info("Fetching workflow: id=%s", workflow_id)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        logger.warning("Workflow not found: id=%s", workflow_id)
        raise HTTPException(status_code=404, detail="Workflow not found")
    out = WorkflowOut.model_validate(db_workflow)
    shared_ids = compute_can_edit_ids(db, current_user, "workflow", [db_workflow.id])
    out.can_edit = (
        current_user.role == "admin"
        or db_workflow.created_by == current_user.id
        or db_workflow.id in shared_ids
    )
    return out


@router.put("/{workflow_id}", response_model=WorkflowOut)
def update_workflow(
    workflow_id: int,
    workflow: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Workflow:
    """更新工作流（支持 name / graph_config / enabled 字段）。"""
    logger.info("Updating workflow: id=%s", workflow_id)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        logger.warning("Workflow not found for update: id=%s", workflow_id)
        raise HTTPException(status_code=404, detail="Workflow not found")
    # 资源级 owner 校验：仅 admin/owner/被授权用户可编辑
    check_resource_ownership(current_user, db, "workflow", workflow_id, db_workflow)

    update_data = workflow.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_workflow, key, value)
        logger.debug("Updating field %s for workflow %s", key, workflow_id)

    db.commit()
    db.refresh(db_workflow)
    logger.info("Workflow updated: id=%s", db_workflow.id)
    return db_workflow


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """删除工作流。"""
    logger.info("Deleting workflow: id=%s", workflow_id)
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if db_workflow is None:
        logger.warning("Workflow not found for delete: id=%s", workflow_id)
        raise HTTPException(status_code=404, detail="Workflow not found")
    # 资源级 owner 校验：仅 admin/owner/被授权用户可删除
    check_resource_ownership(current_user, db, "workflow", workflow_id, db_workflow)

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


# ============ 工作流环境变量（加密存储） ============


class EnvVarItem(BaseModel):
    """单个环境变量项。"""

    name: str = Field(..., description="变量名（如 api_key）")
    description: Optional[str] = Field(None, description="变量描述（可选）")
    value: Optional[str] = Field(None, description="变量值（敏感信息，加密存储）")


class EnvVarList(BaseModel):
    """环境变量列表请求体。"""

    items: list[EnvVarItem] = Field(default_factory=list, description="环境变量列表")


@router.get("/{workflow_id}/env-vars")
def get_env_vars(workflow_id: int, db: Session = Depends(get_db)) -> dict:
    """获取工作流环境变量列表。

    返回结构：
    - ``items``：环境变量列表，``value`` 字段返回掩码（``******``），
      若用户希望查看明文需调用 ``/{id}/env-vars/reveal``。

    安全说明：环境变量名与描述可直读，值默认掩码，避免列表页泄露敏感凭证。
    """
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    raw = wf.env_vars or []
    items = []
    for v in raw:
        if not isinstance(v, dict):
            continue
        value_cipher = v.get("value") or ""
        # 有值（无论加密与否）则展示掩码，空值则展示空字符串
        masked = "******" if decrypt_env_value(value_cipher) else ""
        items.append({
            "name": v.get("name", ""),
            "description": v.get("description") or "",
            "value": masked,
            "has_value": bool(masked),
        })
    return {"items": items}


@router.put("/{workflow_id}/env-vars")
def update_env_vars(
    workflow_id: int, body: EnvVarList, db: Session = Depends(get_db)
) -> dict:
    """保存工作流环境变量（值加密存储）。

    请求体：``{items: [{name, description, value}, ...]}``。
    若某项 ``value`` 为 ``"******"``，表示保留原值不变（前端仅展示掩码场景）。
    若 ``value`` 为空字符串，表示清空原值。

    安全说明：调用此接口需登录（router 级鉴权），值在数据库中加密存储。
    """
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 取原值用于"保留掩码项"
    prev_map: dict[str, str] = {}
    for v in (wf.env_vars or []):
        if isinstance(v, dict) and v.get("name"):
            prev_map[v["name"]] = v.get("value") or ""

    new_items = []
    for item in body.items:
        name = (item.name or "").strip()
        if not name:
            # 跳过空名项（前端可能误传空行）
            continue
        value = item.value
        if value == "******":
            # 保留原值（用户未修改）
            value_cipher = prev_map.get(name, "")
        else:
            # 新值或清空：加密后存储
            value_cipher = encrypt_env_value(value or "")
        new_items.append({
            "name": name,
            "description": (item.description or "").strip(),
            "value": value_cipher,
        })

    wf.env_vars = new_items if new_items else None
    db.commit()
    logger.info("工作流 %s 环境变量已更新，共 %d 项", workflow_id, len(new_items))
    # 返回掩码视图（与 GET 一致，避免明文回显）
    return {
        "items": [
            {
                "name": v["name"],
                "description": v["description"],
                "value": "******" if decrypt_env_value(v["value"]) else "",
                "has_value": bool(decrypt_env_value(v["value"])),
            }
            for v in new_items
        ]
    }


@router.post("/{workflow_id}/env-vars/reveal")
def reveal_env_var(
    workflow_id: int, body: dict, db: Session = Depends(get_db)
) -> dict:
    """查看单个环境变量的明文值（敏感操作，审计建议记录）。

    请求体：``{name: "变量名"}``。
    返回：``{name, value}``。

    安全说明：仅授权登录用户可调用；后续可扩展为按权限模块控制。
    """
    name = (body or {}).get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    for v in (wf.env_vars or []):
        if isinstance(v, dict) and v.get("name") == name:
            return {"name": name, "value": decrypt_env_value(v.get("value") or "")}
    raise HTTPException(status_code=404, detail=f"环境变量 '{name}' 不存在")


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
                    "timestamp": beijing_now_iso(),
                }))
        except RuntimeError:
            pass

    try:
        # 解密环境变量注入到 ctx.env（供节点参数 ${env.名称} 引用）
        env_vars_plain: dict[str, str] = {}
        for v in (workflow.env_vars or []):
            if isinstance(v, dict) and v.get("name"):
                env_vars_plain[v["name"]] = decrypt_env_value(v.get("value") or "")
        result = await run_workflow(
            graph_config=workflow.graph_config,
            payload=body.payload,
            log_callback=log_callback,
            trigger_type="test_run",
            execution_id=execution.id,
            workflow_id=workflow_id,
            env_vars=env_vars_plain,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("测试运行异常: %s", exc)
        execution.status = "failed"
        execution.result = {"error": str(exc)}
        execution.finished_at = beijing_now()
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
    execution.finished_at = beijing_now()
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
