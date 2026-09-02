"""标准告警列表 API。

- ``GET /alerts``：分页列表（筛选/排序全部后端执行，深分页用延迟关联）。
- ``GET /alerts/{id}``：详情（JSON 字段全部反序列化返回）。
- ``GET /alerts/stats``：列表页顶部统计卡片。
- ``POST /alerts/export``：CSV 导出（文件名 告警列表_YYYYMMDD_HHmmss.csv）。
"""
import csv
import io
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.timezone import beijing_now
from app.database import get_db
from app.dependencies import require_permission
from app.models.alert_event import AlertEvent
from app.models.ingestion_metric import IngestionMetric
from app.models.parse_error import ParseErrorQueue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])

# 支持排序的列（表头排序白名单）
SORTABLE_COLUMNS = {
    "occur_timestamp": AlertEvent.occur_timestamp,
    "risk_level": AlertEvent.risk_level,
    "severity": AlertEvent.severity,
    "created_at": AlertEvent.created_at,
}

# JSON 文本字段 → 详情反序列化
_JSON_FIELDS = (
    "devices", "host_ip", "risk_tag", "src_ip", "dst_ip",
    "attck_technique", "threat_define", "extensions", "parse_warnings",
)

# 导出 CSV 列（表头 → 取值字段）
_EXPORT_COLUMNS = [
    ("告警名称", "alert_name"), ("风险等级", "risk_level_name"), ("严重度", "severity"),
    ("置信度", "confidence"), ("设备类型", "device_type"), ("攻击状态", "attack_state_name"),
    ("源IP", "src_ip"), ("源端口", "src_port"), ("目的IP", "dst_ip"), ("目的端口", "dst_port"),
    ("方向", "direction_name"), ("协议", "protocol"), ("攻击阶段", "stage_name"),
    ("威胁大类", "threat_class"), ("威胁类型", "threat_type"),
    ("处置状态", "deal_status_name"), ("解析状态", "parse_status"),
    ("发生时间", "occur_timestamp"), ("上报时间", "upload_time"), ("uuid", "uuid"),
]


def _parse_int_list(raw: str) -> list[int]:
    """逗号分隔整数串 → int 列表（忽略非法片段）。"""
    if not raw:
        return []
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return out


def _parse_dt(raw: str) -> Optional[datetime]:
    """ISO 字符串 → 北京时间 naive datetime（与库内存储一致）。"""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz=None).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _build_query(
    db: Session,
    *,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    risk_levels: list[int],
    attack_states: list[int],
    deal_statuses: list[int],
    stages: list[int],
    directions: list[int],
    keyword: str,
    parse_status: str,
    device_type: str,
):
    """构造告警列表筛选查询（列表/统计/导出共用）。"""
    query = db.query(AlertEvent)
    if start_time is not None:
        query = query.filter(AlertEvent.occur_timestamp >= start_time)
    if end_time is not None:
        query = query.filter(AlertEvent.occur_timestamp < end_time)
    if risk_levels:
        query = query.filter(AlertEvent.risk_level.in_(risk_levels))
    if attack_states:
        query = query.filter(AlertEvent.attack_state.in_(attack_states))
    if deal_statuses:
        query = query.filter(AlertEvent.deal_status.in_(deal_statuses))
    if stages:
        query = query.filter(AlertEvent.stage.in_(stages))
    if directions:
        query = query.filter(AlertEvent.direction.in_(directions))
    if parse_status:
        query = query.filter(AlertEvent.parse_status == parse_status)
    if device_type:
        query = query.filter(AlertEvent.device_type == device_type)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                AlertEvent.alert_name.ilike(like),
                AlertEvent.src_ip.ilike(like),
                AlertEvent.dst_ip.ilike(like),
            )
        )
    return query


def _serialize(row: AlertEvent, *, full: bool = False) -> dict[str, Any]:
    """行序列化；full=True 时反序列化 JSON 字段并携带全部字段。"""
    data: dict[str, Any] = {
        "id": row.id,
        "uuid": row.uuid,
        "alert_name": row.alert_name,
        "risk_level": row.risk_level,
        "risk_level_name": row.risk_level_name,
        "severity": row.severity,
        "confidence": row.confidence,
        "device_type": row.device_type,
        "attack_state": row.attack_state,
        "attack_state_name": row.attack_state_name,
        "src_ip": row.src_ip,
        "src_port": row.src_port,
        "dst_ip": row.dst_ip,
        "dst_port": row.dst_port,
        "direction": row.direction,
        "direction_name": row.direction_name,
        "protocol": row.protocol,
        "stage": row.stage,
        "stage_name": row.stage_name,
        "deal_status": row.deal_status,
        "deal_status_name": row.deal_status_name,
        "parse_status": row.parse_status,
        "occur_timestamp": row.occur_timestamp,
        "created_at": row.created_at,
    }
    if not full:
        return data
    # ===== 详情：全部字段 + JSON 反序列化 =====
    data.update({
        "seq_id": row.seq_id,
        "tenant": row.tenant,
        "customer": row.customer,
        "data_version": row.data_version,
        "strategy_id": row.strategy_id,
        "agent_id": row.agent_id,
        "asset_id": row.asset_id,
        "region_id": row.region_id,
        "relate_asset_type": row.relate_asset_type,
        "relate_asset_type_name": row.relate_asset_type_name,
        "group_id": row.group_id,
        "subject_type": row.subject_type,
        "user_name": row.user_name,
        "account_id": row.account_id,
        "account_name": row.account_name,
        "first_timestamp": row.first_timestamp,
        "last_timestamp": row.last_timestamp,
        "upload_timestamp": row.upload_timestamp,
        "upload_time": row.upload_time,
        "upload_time_raw": row.upload_time_raw,
        "time_region": row.time_region,
        "description": row.description,
        "recommendation": row.recommendation,
        "src_asset_id": row.src_asset_id,
        "src_ip_tag": row.src_ip_tag,
        "src_ip_tag_name": row.src_ip_tag_name,
        "src_region_id": row.src_region_id,
        "src_region_name": row.src_region_name,
        "dst_asset_id": row.dst_asset_id,
        "dst_region_id": row.dst_region_id,
        "dst_region_name": row.dst_region_name,
        "xff_client_ip": row.xff_client_ip,
        "src_country": row.src_country,
        "src_province": row.src_province,
        "src_city": row.src_city,
        "threat_class": row.threat_class,
        "threat_type": row.threat_type,
        "threat_sub_type": row.threat_sub_type,
        "proof_type": row.proof_type,
        "proof_description": row.proof_description,
        "base_content": row.base_content,
    })
    for field in _JSON_FIELDS:
        raw = getattr(row, field, None)
        if isinstance(raw, str) and raw:
            try:
                data[field] = json.loads(raw)
            except (ValueError, TypeError):
                data[field] = raw
        else:
            data[field] = raw
    # raw_data 单独处理：尝试格式化为对象（前端再做格式化高亮）
    if row.raw_data:
        try:
            data["raw_data"] = json.loads(row.raw_data)
        except (ValueError, TypeError):
            data["raw_data"] = row.raw_data
    else:
        data["raw_data"] = None
    return data


@router.get("", dependencies=[Depends(require_permission("alert", "view"))])
def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("occur_timestamp", description="排序字段：occur_timestamp/risk_level/severity/created_at"),
    order: str = Query("desc", description="asc / desc"),
    start_time: str = Query("", description="发生时间起（ISO），默认最近24小时"),
    end_time: str = Query("", description="发生时间止（ISO）"),
    risk_levels: str = Query("", description="风险等级多选，逗号分隔"),
    attack_states: str = Query("", description="攻击状态多选，逗号分隔"),
    deal_statuses: str = Query("", description="处置状态多选，逗号分隔"),
    stages: str = Query("", description="告警阶段多选，逗号分隔"),
    directions: str = Query("", description="访问方向多选，逗号分隔"),
    keyword: str = Query("", description="源IP/目的IP/告警名称模糊匹配"),
    parse_status: str = Query("", description="success/partial/fail"),
    device_type: str = Query("", description="设备类型"),
    db: Session = Depends(get_db),
) -> dict:
    """分页查询告警（深分页用延迟关联：先取 id 子查询再回表）。"""
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    if st is None and et is None:
        st = beijing_now() - timedelta(hours=24)

    query = _build_query(
        db,
        start_time=st, end_time=et,
        risk_levels=_parse_int_list(risk_levels),
        attack_states=_parse_int_list(attack_states),
        deal_statuses=_parse_int_list(deal_statuses),
        stages=_parse_int_list(stages),
        directions=_parse_int_list(directions),
        keyword=keyword.strip(),
        parse_status=parse_status,
        device_type=device_type,
    )
    total = query.count()

    col = SORTABLE_COLUMNS.get(sort)
    if col is None:
        col = AlertEvent.occur_timestamp
    order_col = col.desc() if str(order).lower() == "desc" else col.asc()

    # 延迟关联：offset/limit 只作用在 id 子查询上，大偏移时避免整行扫描排序
    subq = (
        query.with_entities(AlertEvent.id)
        .order_by(order_col, AlertEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .subquery()
    )
    rows = (
        db.query(AlertEvent)
        .join(subq, AlertEvent.id == subq.c.id)
        .order_by(order_col, AlertEvent.id.desc())
        .all()
    )
    return {
        "total": total,
        "items": [_serialize(r) for r in rows],
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats", dependencies=[Depends(require_permission("alert", "view"))])
def alert_stats(db: Session = Depends(get_db)) -> dict:
    """列表页顶部统计卡片：今日告警总数（对比昨日）、今日高危及以上、解析失败数、接入设备类型数。"""
    now = beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    today_total = db.query(func.count(AlertEvent.id)).filter(
        AlertEvent.occur_timestamp >= today_start,
        AlertEvent.occur_timestamp < now,
    ).scalar() or 0
    yesterday_total = db.query(func.count(AlertEvent.id)).filter(
        AlertEvent.occur_timestamp >= yesterday_start,
        AlertEvent.occur_timestamp < today_start,
    ).scalar() or 0
    # 高危及以上：risk_level 0=严重 1=高危
    today_high = db.query(func.count(AlertEvent.id)).filter(
        AlertEvent.occur_timestamp >= today_start,
        AlertEvent.occur_timestamp < now,
        AlertEvent.risk_level.in_([0, 1]),
    ).scalar() or 0
    # 解析失败数：今日入库指标 fail（含无匹配策略）
    today_fail = db.query(func.coalesce(func.sum(IngestionMetric.fail_count), 0)).filter(
        IngestionMetric.stat_hour >= today_start.strftime("%Y-%m-%dT%H"),
    ).scalar() or 0
    # 接入设备类型数：告警表中出现过的设备类型
    device_types = db.query(AlertEvent.device_type).filter(
        AlertEvent.device_type != "",
    ).distinct().all()

    delta = today_total - yesterday_total if yesterday_total else (today_total if today_total else 0)
    return {
        "today_total": today_total,
        "yesterday_total": yesterday_total,
        "delta": delta,
        "today_high": today_high,
        "today_fail": int(today_fail),
        "device_type_count": len(device_types),
        "device_types": sorted({t[0] for t in device_types}),
    }


@router.get("/{alert_id}", dependencies=[Depends(require_permission("alert", "view"))])
def get_alert(alert_id: int, db: Session = Depends(get_db)) -> dict:
    """告警详情：全部字段 + JSON 字段反序列化。"""
    row = db.query(AlertEvent).filter(AlertEvent.id == alert_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="告警不存在或已被删除")
    return _serialize(row, full=True)


@router.post("/export", dependencies=[Depends(require_permission("alert", "view"))])
def export_alerts(
    body: dict,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """按当前筛选条件导出 CSV（UTF-8 BOM，Excel 可直接打开）。"""
    st = _parse_dt(str(body.get("start_time") or ""))
    et = _parse_dt(str(body.get("end_time") or ""))
    if st is None and et is None:
        st = beijing_now() - timedelta(hours=24)
    query = _build_query(
        db,
        start_time=st, end_time=et,
        risk_levels=_parse_int_list(str(body.get("risk_levels") or "")),
        attack_states=_parse_int_list(str(body.get("attack_states") or "")),
        deal_statuses=_parse_int_list(str(body.get("deal_statuses") or "")),
        stages=_parse_int_list(str(body.get("stages") or "")),
        directions=_parse_int_list(str(body.get("directions") or "")),
        keyword=str(body.get("keyword") or "").strip(),
        parse_status=str(body.get("parse_status") or ""),
        device_type=str(body.get("device_type") or ""),
    )
    sort = str(body.get("sort") or "occur_timestamp")
    col = SORTABLE_COLUMNS.get(sort, AlertEvent.occur_timestamp)
    order_col = col.desc() if str(body.get("order") or "desc").lower() != "asc" else col.asc()
    rows = query.order_by(order_col, AlertEvent.id.desc()).limit(10000).all()

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM
    writer = csv.writer(buf)
    writer.writerow([h for h, _ in _EXPORT_COLUMNS])
    for row in rows:
        cells = []
        for _, field in _EXPORT_COLUMNS:
            val = getattr(row, field, None)
            if isinstance(val, datetime):
                val = val.strftime("%Y-%m-%d %H:%M:%S")
            elif val is None:
                val = ""
            cells.append(str(val))
        writer.writerow(cells)

    filename = f"告警列表_{beijing_now().strftime('%Y%m%d_%H%M%S')}.csv"
    content = buf.getvalue()
    from urllib.parse import quote
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Content-Length": str(len(content.encode("utf-8"))),
        },
    )
