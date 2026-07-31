"""资产管理 API。

提供资产列表查看（分页+筛选+搜索）、统计、详情、手动新增/编辑/删除、
CSV 导出，以及手动触发资产扫描任务。

供前端「资产管理」页面使用。资产数据由资产管理智能体的工具自动梳理录入，
也可通过本 API 手动管理。
"""
import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.agent import Agent
from app.models.asset import Asset
from app.schemas.common import to_dict

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[Depends(get_current_user)],
)


# ============================================================================
# 请求模型
# ============================================================================


class AssetCreateRequest(BaseModel):
    """手动新增资产请求体。"""

    agent_id: int = Field(..., description="归属智能体 ID")
    identifier: str = Field(..., description="资产唯一标识（IP/主机名/工号等）")
    identifier_type: str = Field("custom", description="标识类型：ip/hostname/asset_name/employee_id/mac/custom")
    name: str = Field("", description="资产名称")
    asset_type: str = Field("", description="资产类型")
    department: str = Field("", description="归属部门")
    owner: str = Field("", description="负责人")
    location: str = Field("", description="物理位置")
    ip: str = Field("", description="IP 地址")
    criticality: str = Field("medium", description="重要性：low/medium/high/critical")
    kb_id: int = Field(0, description="来源知识库 ID")
    kb_name: str = Field("", description="来源知识库名称")
    extra_fields: dict | None = Field(None, description="灵活字段（JSON 对象）")


class AssetUpdateRequest(BaseModel):
    """更新资产请求体（所有字段可选）。"""

    identifier: str | None = Field(None, description="资产唯一标识")
    identifier_type: str | None = Field(None, description="标识类型")
    name: str | None = Field(None, description="资产名称")
    asset_type: str | None = Field(None, description="资产类型")
    department: str | None = Field(None, description="归属部门")
    owner: str | None = Field(None, description="负责人")
    location: str | None = Field(None, description="物理位置")
    ip: str | None = Field(None, description="IP 地址")
    criticality: str | None = Field(None, description="重要性")
    kb_id: int | None = Field(None, description="来源知识库 ID")
    kb_name: str | None = Field(None, description="来源知识库名称")
    extra_fields: dict | None = Field(None, description="灵活字段（与已有 extra_fields 合并）")


# ============================================================================
# 查询端点
# ============================================================================


@router.get("")
def list_assets(
    agent_id: int | None = Query(None, description="按智能体筛选"),
    kb_id: int | None = Query(None, description="按来源知识库筛选"),
    asset_type: str = Query("", description="按资产类型筛选"),
    department: str = Query("", description="按部门筛选"),
    criticality: str = Query("", description="按重要性筛选：low/medium/high/critical"),
    source: str = Query("", description="按来源筛选：kb_ingest/agent_add/manual"),
    keyword: str = Query("", description="模糊搜索 identifier/name/ip/owner"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
) -> dict:
    """资产列表（分页 + 多维筛选 + 关键词搜索）。"""
    query = db.query(Asset)
    if agent_id is not None:
        query = query.filter(Asset.agent_id == agent_id)
    if kb_id is not None:
        query = query.filter(Asset.kb_id == kb_id)
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if department:
        query = query.filter(Asset.department == department)
    if criticality:
        query = query.filter(Asset.criticality == criticality)
    if source:
        query = query.filter(Asset.source == source)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                Asset.identifier.like(like),
                Asset.name.like(like),
                Asset.ip.like(like),
                Asset.owner.like(like),
            )
        )

    total = query.count()
    records = (
        query.order_by(Asset.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": to_dict_list_with_agent_name(records, db),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


def to_dict_list_with_agent_name(records: list, db: Session) -> list[dict]:
    """序列化资产列表，冗余附加 agent_name 便于前端展示。"""
    if not records:
        return []
    agent_ids = {r.agent_id for r in records}
    agent_map = {
        a.id: a.name for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    }
    result = []
    for r in records:
        d = to_dict(r)
        d["agent_name"] = agent_map.get(r.agent_id, f"智能体-{r.agent_id}")
        result.append(d)
    return result


@router.get("/stats")
def get_asset_stats(
    agent_id: int | None = Query(None, description="按智能体筛选统计"),
    db: Session = Depends(get_db),
) -> dict:
    """资产统计信息（总数 / 按类型 / 按来源 / 按重要性 / 按智能体）。"""
    query = db.query(Asset)
    if agent_id is not None:
        query = query.filter(Asset.agent_id == agent_id)

    total = query.count()

    # Python 侧聚合（数据量不大时更清晰，避免复杂 SQL）
    all_records = query.with_entities(
        Asset.asset_type, Asset.source, Asset.criticality
    ).all()

    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_criticality: dict[str, int] = {}
    for r in all_records:
        t = r.asset_type or "未分类"
        by_type[t] = by_type.get(t, 0) + 1
        s = r.source or "unknown"
        by_source[s] = by_source.get(s, 0) + 1
        c = r.criticality or "medium"
        by_criticality[c] = by_criticality.get(c, 0) + 1

    # 按智能体统计（始终全局，不应用 agent_id 筛选）
    agent_rows = (
        db.query(Asset.agent_id)
        .group_by(Asset.agent_id)
        .all()
    )
    agent_ids = {r[0] for r in agent_rows}
    agent_map = {
        a.id: a.name for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    }
    by_agent: dict[str, int] = {}
    for r in agent_rows:
        name = agent_map.get(r[0], f"智能体-{r[0]}")
        by_agent[name] = by_agent.get(name, 0) + 1

    return {
        "total": total,
        "by_type": by_type,
        "by_source": by_source,
        "by_criticality": by_criticality,
        "by_agent": by_agent,
    }


@router.get("/export")
def export_assets(
    agent_id: int | None = Query(None, description="按智能体筛选"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """导出资产为 CSV。"""
    query = db.query(Asset)
    if agent_id is not None:
        query = query.filter(Asset.agent_id == agent_id)
    records = query.order_by(Asset.id.desc()).all()

    output = io.StringIO()
    output.write("\ufeff")  # BOM for Excel
    writer = csv.writer(output)
    writer.writerow([
        "ID", "智能体ID", "知识库ID", "知识库名称",
        "标识", "标识类型", "名称", "资产类型",
        "部门", "负责人", "位置", "IP",
        "重要性", "来源", "灵活字段",
        "创建时间", "更新时间",
    ])
    for r in records:
        writer.writerow([
            r.id, r.agent_id, r.kb_id, r.kb_name,
            r.identifier, r.identifier_type, r.name, r.asset_type,
            r.department, r.owner, r.location, r.ip,
            r.criticality, r.source,
            str(r.extra_fields) if r.extra_fields else "",
            r.created_at, r.updated_at,
        ])

    output.seek(0)
    filename = "assets.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{asset_id}")
def get_asset(asset_id: int, db: Session = Depends(get_db)) -> dict:
    """获取单个资产详情。"""
    record = db.query(Asset).filter(Asset.id == asset_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="资产不存在")
    d = to_dict(record)
    agent = db.query(Agent).filter(Agent.id == record.agent_id).first()
    d["agent_name"] = agent.name if agent else f"智能体-{record.agent_id}"
    return d


# ============================================================================
# 写操作端点
# ============================================================================


@router.post("", status_code=201)
def create_asset(
    body: AssetCreateRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("admin", "analyst")),
) -> dict:
    """手动新增资产（管理员/分析师）。

    source 标记为 ``manual``，与智能体自动录入（agent_add / kb_ingest）区分。
    若 (agent_id, identifier) 已存在则返回 409 冲突。
    """
    # 校验智能体存在
    agent = db.query(Agent).filter(Agent.id == body.agent_id).first()
    if agent is None:
        raise HTTPException(status_code=400, detail=f"智能体不存在: {body.agent_id}")

    # 查重
    existing = db.query(Asset).filter(
        Asset.agent_id == body.agent_id,
        Asset.identifier == body.identifier,
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"资产已存在（identifier={body.identifier}, id={existing.id}）",
        )

    record = Asset(
        agent_id=body.agent_id,
        identifier=body.identifier,
        identifier_type=body.identifier_type,
        name=body.name,
        asset_type=body.asset_type,
        department=body.department,
        owner=body.owner,
        location=body.location,
        ip=body.ip,
        criticality=body.criticality,
        kb_id=body.kb_id,
        kb_name=body.kb_name,
        source="manual",
        extra_fields=body.extra_fields or {},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("手动新增资产: id=%s, agent=%s, identifier=%s", record.id, record.agent_id, record.identifier)
    return to_dict(record)


@router.put("/{asset_id}")
def update_asset(
    asset_id: int,
    body: AssetUpdateRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("admin", "analyst")),
) -> dict:
    """更新资产（管理员/分析师）。

    仅更新传入的非 None 字段。extra_fields 与已有值合并（不覆盖整个对象）。
    """
    record = db.query(Asset).filter(Asset.id == asset_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="资产不存在")

    # 标量字段
    for field in [
        "identifier", "identifier_type", "name", "asset_type",
        "department", "owner", "location", "ip", "criticality", "kb_name",
    ]:
        v = getattr(body, field, None)
        if v is not None:
            setattr(record, field, v)
    if body.kb_id is not None:
        record.kb_id = body.kb_id
    # extra_fields 合并
    if body.extra_fields is not None:
        cur = dict(record.extra_fields or {})
        cur.update(body.extra_fields)
        record.extra_fields = cur

    db.commit()
    db.refresh(record)
    logger.info("更新资产: id=%s", asset_id)
    return to_dict(record)


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("admin")),
) -> dict:
    """删除资产（仅管理员）。"""
    record = db.query(Asset).filter(Asset.id == asset_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="资产不存在")
    db.delete(record)
    db.commit()
    logger.info("删除资产: id=%s, identifier=%s", asset_id, record.identifier)
    return {"ok": True, "deleted": asset_id}


@router.delete("")
def batch_delete_assets(
    ids: list[int] = Query(..., description="要删除的资产 ID 列表"),
    db: Session = Depends(get_db),
    _: object = Depends(require_role("admin")),
) -> dict:
    """批量删除资产（仅管理员）。"""
    if not ids:
        return {"ok": True, "deleted": 0}
    deleted = db.query(Asset).filter(Asset.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    logger.info("批量删除资产: ids=%s, deleted=%d", ids, deleted)
    return {"ok": True, "deleted": deleted}


# ============================================================================
# 扫描触发
# ============================================================================


@router.post("/scan")
def trigger_asset_scan(
    _: object = Depends(require_role("admin", "analyst")),
) -> dict:
    """手动触发资产扫描任务（异步）。

    调用 Celery 任务 ``scan_asset_agents``，扫描所有资产管理智能体的新知识库。
    立即返回任务 ID，扫描结果在 Celery worker 中异步产出。
    """
    from app.tasks.asset_tasks import scan_asset_agents

    task = scan_asset_agents.delay()
    logger.info("手动触发资产扫描任务: task_id=%s", task.id)
    return {
        "ok": True,
        "task_id": task.id,
        "message": "资产扫描任务已提交，将在后台异步执行",
    }
