"""告警解析入库 API。

- ``POST /ingest/alert``：接收原始告警 JSON（单条或批量），策略路由→解析→入库。
- ``GET/POST/PUT/PATCH/DELETE /ingest/strategies``：解析策略管理（引擎热更新，无需重启）。
- ``POST /ingest/strategies/test``：策略测试解析（纯内存执行，不写库）。
- ``GET /ingest/strategies/fields``：标准模型可选目标字段清单（供表单下拉）。
- ``GET /ingest/errors``：解析错误队列查看。
- ``GET /ingest/metrics``：按小时聚合的入库指标查看。

ingest 端点面向设备/上游系统推送（类 webhook），不做用户态鉴权；
策略/错误队列/指标等管理端点需要登录。
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.timezone import BEIJING_TZ, beijing_now
from app.database import SessionLocal, get_db
from app.dependencies import get_current_user, require_permission
from app.engine.enum_translator import translate as enum_translate
from app.engine.field_mapper import apply_mappings
from app.engine.parser_engine import ParseEngine, ParseSink
from app.engine.strategy_loader import StrategyLoader, get_path
from app.engine.validator import run_validations
from app.models.alert_event import AlertEvent
from app.models.ingestion_metric import IngestionMetric
from app.models.parse_error import ParseErrorQueue
from app.models.parse_strategy import ParseStrategy
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


# ======================================================================
# 策略缓存（进程级单例，策略变更时刷新）
# ======================================================================
_strategy_loader: Optional[StrategyLoader] = None


def _fetch_strategies() -> list[dict]:
    """从数据库加载全部策略（含 disabled，由 loader 过滤）。"""
    db = SessionLocal()
    try:
        rows = db.query(ParseStrategy).all()
        return [
            {
                "id": r.id,
                "strategy_name": r.strategy_name,
                "device_type": r.device_type,
                "version": r.version,
                "status": r.status,
                "config": r.config,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_strategy_loader() -> StrategyLoader:
    """获取（惰性创建）进程级策略缓存加载器。"""
    global _strategy_loader
    if _strategy_loader is None:
        _strategy_loader = StrategyLoader(fetch_strategies=_fetch_strategies)
    return _strategy_loader


def refresh_strategy_cache() -> None:
    """策略变更后刷新内存缓存。"""
    loader = get_strategy_loader()
    loader.refresh()


# ======================================================================
# SQLAlchemy 持久化后端（ParseSink 协议实现）
# ======================================================================
class SQLAlchemySink:
    """把解析结果写入 alert_events / parse_error_queue / ingestion_metrics。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save_alert(self, fields: dict[str, Any]) -> str:
        """写入标准告警表；uuid 重复时跳过并返回 duplicate（幂等）。

        入库成功（parse_status 为 success/partial）后发布 alert.ingested 事件，
        触发封禁工作流（进程内异步队列，不阻塞入库；发布失败不回滚）。
        """
        uuid_val = str(fields.get("uuid") or "")
        if not uuid_val:
            raise ValueError("uuid 缺失，无法入库")
        try:
            exists = self.db.query(AlertEvent.id).filter(AlertEvent.uuid == uuid_val).first()
            if exists:
                return "duplicate"
            alert_row = AlertEvent(**fields)
            self.db.add(alert_row)
            self.db.commit()
            # 发布入库事件（触发封禁工作流；只记日志不回滚入库）
            if str(fields.get("parse_status") or "") in ("success", "partial"):
                try:
                    from app.workflow.trigger import publish_alert_ingested
                    publish_alert_ingested({**fields, "id": alert_row.id})
                except Exception:  # noqa: BLE001
                    logger.exception("alert.ingested 事件发布失败（不影响入库）")
            return "inserted"
        except Exception:
            self.db.rollback()
            raise

    def save_error(
        self,
        raw_data: str,
        error_type: str,
        error_msg: str,
        uuid: Optional[str] = None,
        strategy_id: Optional[int] = None,
    ) -> None:
        """写入解析错误队列。"""
        try:
            self.db.add(
                ParseErrorQueue(
                    uuid=uuid,
                    strategy_id=strategy_id,
                    raw_data=raw_data,
                    error_type=error_type,
                    error_msg=error_msg[:2000],
                )
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def record_metrics(
        self,
        stat_hour: str,
        strategy_id: Optional[int],
        strategy_name: str,
        status: str,
        parse_ms: int,
    ) -> None:
        """按小时原子累加指标（UPDATE 命中则自增，否则 INSERT）。"""
        try:
            # 原子自增（total 与对应状态计数同时 +1）；
            # IS NOT DISTINCT FROM 兼容 strategy_id 为 NULL 的全局行
            sql = sa_text(
                """
                UPDATE ingestion_metrics
                SET total_count = total_count + 1,
                    {status_col} = {status_col} + 1,
                    total_parse_ms = total_parse_ms + :ms,
                    strategy_name = :sname,
                    updated_at = :now
                WHERE stat_hour = :hour AND strategy_id IS NOT DISTINCT FROM :sid
                """.format(status_col=f"{status}_count")
            )
            result = self.db.execute(
                sql,
                {"ms": parse_ms, "sname": strategy_name, "hour": stat_hour,
                 "sid": strategy_id, "now": beijing_now()},
            )
            if result.rowcount == 0:
                self.db.add(
                    IngestionMetric(
                        stat_hour=stat_hour,
                        strategy_id=strategy_id,
                        strategy_name=strategy_name,
                        total_count=1,
                        success_count=1 if status == "success" else 0,
                        partial_count=1 if status == "partial" else 0,
                        fail_count=1 if status == "fail" else 0,
                        total_parse_ms=parse_ms,
                    )
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


# ======================================================================
# Schemas
# ======================================================================
class StrategyStatusBody(BaseModel):
    """策略启停请求体。"""

    status: str = Field(..., description="enabled / disabled")


class StrategyTestRequest(BaseModel):
    """策略测试请求体：策略配置 + 样例原始数据。"""

    config: dict = Field(..., description="策略配置 JSON 全文")
    sample: dict = Field(..., description="样例原始日志 JSON")


class IngestResponse(BaseModel):
    """入库结果汇总。"""

    total: int
    success: int
    partial: int
    fail: int
    duplicates: int
    results: list[dict]


# 支持的字段转换类型（表单模式下拉用，与 field_mapper.convert_value 一致）
CONVERT_TYPES = {
    "string", "int", "float", "bool",
    "json_array_to_string", "json_object_to_string",
    "timestamp_to_datetime", "comma_split_to_json", "enum_int",
}

# 支持的校验规则类型（与 validator.run_validations 一致）
VALIDATION_RULES = {"regex", "range", "ip_list_valid", "positive_int"}

# 标准模型中由引擎自动写入的系统字段，不出现在目标字段下拉里
SYSTEM_TARGET_FIELDS = {"id", "created_at", "raw_data", "parse_status", "parse_warnings", "strategy_id", "device_type", "extensions"}


def _validate_strategy_config(config: dict) -> None:
    """校验策略配置结构，失败抛 422（带具体原因）。"""
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="策略配置必须是 JSON 对象")

    name = config.get("strategy_name")
    if not name or not str(name).strip():
        raise HTTPException(status_code=422, detail="strategy_name 不能为空")

    device_type = config.get("device_type")
    if not device_type or not str(device_type).strip():
        raise HTTPException(status_code=422, detail="device_type 不能为空")

    status = config.get("status", "enabled")
    if status not in ("enabled", "disabled"):
        raise HTTPException(status_code=422, detail=f"status 仅支持 enabled/disabled，当前 {status!r}")

    rules = config.get("route_rules")
    if not isinstance(rules, dict) or not rules.get("match_field"):
        raise HTTPException(status_code=422, detail="route_rules.match_field 不能为空")
    match_type = str(rules.get("match_type") or "exact").lower()
    if match_type not in ("exact", "regex"):
        raise HTTPException(status_code=422, detail=f"route_rules.match_type 仅支持 exact/regex，当前 {match_type!r}")
    if rules.get("match_value") in (None, ""):
        raise HTTPException(status_code=422, detail="route_rules.match_value 不能为空")
    if match_type == "regex":
        try:
            re.compile(str(rules["match_value"]))
        except re.error as exc:
            raise HTTPException(status_code=422, detail=f"route_rules.match_value 正则非法: {exc}")

    wrapper = config.get("outer_wrapper")
    if wrapper is not None and not isinstance(wrapper, dict):
        raise HTTPException(status_code=422, detail="outer_wrapper 必须是对象")

    mappings = config.get("field_mappings")
    if mappings is not None:
        if not isinstance(mappings, list):
            raise HTTPException(status_code=422, detail="field_mappings 必须是数组")
        for i, m in enumerate(mappings, 1):
            if not isinstance(m, dict) or not m.get("source") or not m.get("target"):
                raise HTTPException(status_code=422, detail=f"field_mappings 第 {i} 行缺少 source/target")
            if m.get("type") and m["type"] not in CONVERT_TYPES:
                raise HTTPException(
                    status_code=422,
                    detail=f"field_mappings 第 {i} 行转换类型 {m['type']!r} 不支持（可选：{', '.join(sorted(CONVERT_TYPES))}）",
                )

    enum_maps = config.get("enum_maps")
    if enum_maps is not None:
        if not isinstance(enum_maps, dict):
            raise HTTPException(status_code=422, detail="enum_maps 必须是对象（枚举名 → 原值→翻译值 映射）")
        for ename, table in enum_maps.items():
            if not isinstance(table, dict):
                raise HTTPException(status_code=422, detail=f"enum_maps.{ename} 必须是对象（原值 → 翻译值）")

    validations = config.get("validations")
    if validations is not None:
        if not isinstance(validations, list):
            raise HTTPException(status_code=422, detail="validations 必须是数组")
        for i, v in enumerate(validations, 1):
            if not isinstance(v, dict) or not v.get("field") or not v.get("rule"):
                raise HTTPException(status_code=422, detail=f"validations 第 {i} 行缺少 field/rule")
            if v["rule"] not in VALIDATION_RULES:
                raise HTTPException(
                    status_code=422,
                    detail=f"validations 第 {i} 行规则 {v['rule']!r} 不支持（可选：{', '.join(sorted(VALIDATION_RULES))}）",
                )
            if v["rule"] == "regex":
                try:
                    re.compile(str(v.get("pattern") or ""))
                except re.error as exc:
                    raise HTTPException(status_code=422, detail=f"validations 第 {i} 行正则非法: {exc}")

    ext_fields = config.get("extension_fields")
    if ext_fields is not None and not isinstance(ext_fields, list):
        raise HTTPException(status_code=422, detail="extension_fields 必须是字符串数组")


def _json_safe(value: Any) -> Any:
    """递归把值转为可 JSON 序列化结构（datetime → ISO 字符串）。"""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _preview(value: Any, limit: int = 80) -> Any:
    """测试结果展示用：长值截断。"""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


# ======================================================================
# 告警接入（设备/上游系统推送）
# ======================================================================
@router.post("/alert", response_model=IngestResponse)
async def ingest_alert(request: Request, db: Session = Depends(get_db)) -> IngestResponse:
    """接收原始告警 JSON（单条对象或数组），解析入库。

    - 单条：直接传对象 ``{"type": "security_alert", ...}``；
    - 批量：传数组 ``[ {...}, {...} ]``；
    - 无匹配策略 / 解析失败的数据进入错误队列，不阻断其余数据。
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")

    items = payload if isinstance(payload, list) else [payload]
    if not items:
        raise HTTPException(status_code=400, detail="请求体为空")

    # 策略缓存为空时自动刷新（首次请求或策略刚创建）
    loader = get_strategy_loader()
    if not loader.strategies:
        loader.refresh()

    engine = ParseEngine(loader=loader, sink=SQLAlchemySink(db))
    stats = engine.process(items)
    return IngestResponse(**stats)


# ======================================================================
# 策略管理（需要登录 + strategy 权限）
# ======================================================================
def _today_metrics_by_strategy(db: Session) -> dict[int, dict]:
    """按 strategy_id 聚合今日指标 ``{sid: {"total": n, "fail": n}}``。"""
    today_prefix = beijing_now().strftime("%Y-%m-%dT")
    rows = (
        db.query(IngestionMetric)
        .filter(IngestionMetric.stat_hour.like(today_prefix + "%"))
        .all()
    )
    agg: dict[int, dict] = {}
    for m in rows:
        if m.strategy_id is None:
            continue  # strategy_id 为 NULL 的行是无匹配策略告警，不计入单策略
        item = agg.setdefault(m.strategy_id, {"total": 0, "fail": 0})
        item["total"] += m.total_count or 0
        item["fail"] += m.fail_count or 0
    return agg


@router.get("/strategies", dependencies=[Depends(require_permission("strategy", "view"))])
def list_strategies(db: Session = Depends(get_db)) -> list[dict]:
    """列出全部解析策略（含今日解析统计，走 ingestion_metrics 聚合）。"""
    rows = db.query(ParseStrategy).order_by(ParseStrategy.id.desc()).all()
    today_stats = _today_metrics_by_strategy(db)
    result = []
    for r in rows:
        try:
            config = json.loads(r.config) if isinstance(r.config, str) else (r.config or {})
        except (ValueError, TypeError):
            config = {}
        stat = today_stats.get(r.id, {"total": 0, "fail": 0})
        total, fail = stat["total"], stat["fail"]
        result.append(
            {
                "id": r.id,
                "strategy_name": r.strategy_name,
                "device_type": r.device_type,
                "version": r.version,
                "status": r.status,
                "config": config,
                "today_total": total,
                "today_fail": fail,
                "today_success_rate": round((total - fail) * 100.0 / total, 1) if total else None,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
        )
    return result


@router.get("/strategies/stats", dependencies=[Depends(require_permission("strategy", "view"))])
def strategy_stats(db: Session = Depends(get_db)) -> dict:
    """策略列表页顶部统计卡片数据。"""
    rows = db.query(ParseStrategy).all()
    enabled_count = sum(1 for r in rows if r.status == "enabled")
    device_types = {r.device_type for r in rows if r.device_type}

    today_prefix = beijing_now().strftime("%Y-%m-%dT")
    mrows = (
        db.query(IngestionMetric)
        .filter(IngestionMetric.stat_hour.like(today_prefix + "%"))
        .all()
    )
    today_total = 0
    today_no_match = 0
    for m in mrows:
        today_total += m.total_count or 0
        if m.strategy_id is None:
            # strategy_id 为 NULL 的指标行来自「无匹配策略」错误路径
            today_no_match += m.total_count or 0

    return {
        "enabled_count": enabled_count,
        "strategy_count": len(rows),
        "device_type_count": len(device_types),
        "today_total": today_total,
        "today_no_match": today_no_match,
    }


@router.get("/strategies/fields", dependencies=[Depends(require_permission("strategy", "view"))])
def strategy_target_fields() -> list[dict]:
    """返回标准模型（alert_events）全部可选目标字段及类型，供表单模式下拉选择。"""
    type_map = {"VARCHAR": "string", "TEXT": "string", "INTEGER": "int", "DATETIME": "datetime"}
    result = []
    for col in AlertEvent.__table__.columns:
        if col.name in SYSTEM_TARGET_FIELDS:
            continue
        result.append(
            {
                "name": col.name,
                "type": type_map.get(str(col.type).split("(")[0].upper(), "string"),
                "comment": col.comment or "",
            }
        )
    return result


@router.post("/strategies", status_code=201, dependencies=[Depends(require_permission("strategy", "edit"))])
def create_strategy(body: dict, db: Session = Depends(get_db)) -> dict:
    """创建解析策略（创建后立即生效，刷新内存缓存）。"""
    _validate_strategy_config(body)
    strat = ParseStrategy(
        strategy_name=str(body["strategy_name"]).strip(),
        device_type=str(body["device_type"]).strip(),
        version=str(body.get("version") or "1.0"),
        status=body.get("status") or "enabled",
        config=json.dumps(body, ensure_ascii=False),
    )
    db.add(strat)
    db.commit()
    db.refresh(strat)
    refresh_strategy_cache()
    logger.info("解析策略创建: id=%s name=%s", strat.id, strat.strategy_name)
    return {"id": strat.id, "strategy_name": strat.strategy_name}


@router.put("/strategies/{strategy_id}", dependencies=[Depends(require_permission("strategy", "edit"))])
def update_strategy(
    strategy_id: int,
    body: dict,
    db: Session = Depends(get_db),
) -> dict:
    """更新解析策略（立即生效）。"""
    strat = db.query(ParseStrategy).filter(ParseStrategy.id == strategy_id).first()
    if not strat:
        raise HTTPException(status_code=404, detail="策略不存在")
    _validate_strategy_config(body)
    strat.strategy_name = str(body["strategy_name"]).strip()
    strat.device_type = str(body["device_type"]).strip()
    strat.version = str(body.get("version") or "1.0")
    strat.status = body.get("status") or "enabled"
    strat.config = json.dumps(body, ensure_ascii=False)
    db.commit()
    refresh_strategy_cache()
    logger.info("解析策略更新: id=%s", strat.id)
    return {"id": strat.id, "updated": True}


@router.patch("/strategies/{strategy_id}/status", dependencies=[Depends(require_permission("strategy", "edit"))])
def update_strategy_status(
    strategy_id: int,
    body: StrategyStatusBody,
    db: Session = Depends(get_db),
) -> dict:
    """启用/停用解析策略（立即生效）。"""
    if body.status not in ("enabled", "disabled"):
        raise HTTPException(status_code=422, detail="status 仅支持 enabled/disabled")
    strat = db.query(ParseStrategy).filter(ParseStrategy.id == strategy_id).first()
    if not strat:
        raise HTTPException(status_code=404, detail="策略不存在")
    strat.status = body.status
    db.commit()
    refresh_strategy_cache()
    logger.info("解析策略启停: id=%s status=%s", strat.id, body.status)
    return {"id": strat.id, "status": strat.status}


@router.delete("/strategies/{strategy_id}", status_code=204, dependencies=[Depends(require_permission("strategy", "delete"))])
def delete_strategy(strategy_id: int, db: Session = Depends(get_db)) -> None:
    """删除解析策略（有关联告警记录时返回 409 禁止删除）。"""
    strat = db.query(ParseStrategy).filter(ParseStrategy.id == strategy_id).first()
    if not strat:
        raise HTTPException(status_code=404, detail="策略不存在")
    alert_count = (
        db.query(AlertEvent.id).filter(AlertEvent.strategy_id == strategy_id).count()
    )
    if alert_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"该策略已关联 {alert_count} 条告警记录，禁止删除。可先停用策略以停止解析。",
        )
    db.delete(strat)
    db.commit()
    refresh_strategy_cache()
    logger.info("解析策略删除: id=%s", strategy_id)


# ======================================================================
# 策略测试（纯内存执行，不写库）
# ======================================================================
def _eval_route(rules: dict, raw: dict) -> bool:
    """评估单条路由规则是否命中（与 StrategyLoader.match 逻辑一致）。"""
    match_type = str(rules.get("match_type") or "exact").lower()
    match_field = rules.get("match_field") or ""
    match_value = rules.get("match_value")
    if not match_field:
        return False
    actual = get_path(raw, match_field)
    if match_type == "regex":
        try:
            return re.fullmatch(str(match_value), str(actual)) is not None
        except re.error:
            return False
    return actual == match_value


@router.post("/strategies/test", dependencies=[Depends(require_permission("strategy", "edit"))])
def test_strategy(body: StrategyTestRequest) -> dict:
    """测试解析：路由匹配过程 + 逐字段映射明细 + 校验警告 + 标准模型 JSON 预览。

    纯内存执行，不写库。
    """
    config = body.config or {}
    sample = body.sample or {}
    started = time.perf_counter()

    # 1. 路由匹配过程：提交的策略 + 全部已启用策略逐一评估
    rules = config.get("route_rules") or {}
    actual_value = get_path(sample, rules.get("match_field") or "")
    route = {
        "match_type": str(rules.get("match_type") or "exact").lower(),
        "match_field": rules.get("match_field") or "",
        "match_value": rules.get("match_value"),
        "actual_value": actual_value,
        "matched": _eval_route(rules, sample),
    }

    db_hits = []
    try:
        loader = get_strategy_loader()
        if not loader.strategies:
            loader.refresh()
        for strat in loader.strategies:
            s_rules = (strat.get("config") or {}).get("route_rules") or {}
            db_hits.append(
                {
                    "id": strat.get("id"),
                    "strategy_name": strat.get("strategy_name"),
                    "version": strat.get("version"),
                    "match_field": s_rules.get("match_field"),
                    "match_value": s_rules.get("match_value"),
                    "hit": _eval_route(s_rules, sample),
                }
            )
    except Exception:  # noqa: BLE001
        logger.exception("测试解析：数据库策略路由评估失败（忽略）")

    # 2. 外层解包
    wrapper = config.get("outer_wrapper") or {}
    data_path = wrapper.get("data_path") or ""
    data = get_path(sample, data_path, default={})
    unwrap_ok = isinstance(data, dict)
    if not unwrap_ok:
        data = {}

    # 3. 字段映射（逐字段明细）
    fields, mapping_warnings, enum_specs = apply_mappings(
        data, config.get("field_mappings") or [], sample,
    )

    # 4. 枚举翻译
    enum_translations = []
    enum_translate(fields, enum_specs, config.get("enum_maps") or {})
    for spec in enum_specs:
        enum_translations.append(
            {
                "target": spec.get("target"),
                "enum_target": spec.get("enum_target"),
                "value": fields.get(spec.get("target")),
                "translated": fields.get(spec.get("enum_target")),
            }
        )

    # 5. 校验
    validation_warnings = run_validations(fields, config.get("validations") or [])
    warnings = mapping_warnings + validation_warnings

    # 6. 扩展归档（header + extension_fields → extensions）
    headers = {k: sample.get(k) for k in wrapper.get("header_fields") or [] if k in sample}
    extensions: dict[str, Any] = dict(headers)
    for src in config.get("extension_fields") or []:
        if src in data:
            extensions[src] = data[src]
    fields["extensions"] = json.dumps(extensions, ensure_ascii=False)
    fields["device_type"] = config.get("device_type") or ""
    uuid_source = wrapper.get("uuid_source") or ""
    uuid_val = get_path(sample, uuid_source)
    if uuid_val is not None:
        fields["uuid"] = str(uuid_val)

    # 逐字段明细表（源值 → 目标字段 → 转换后值 → 是否警告）
    warning_by_field: dict[str, dict] = {}
    for w in warnings:
        warning_by_field.setdefault(w.get("field") or "", w)
    mappings_detail = []
    for m in config.get("field_mappings") or []:
        source = m.get("source") or ""
        target = m.get("target") or ""
        mappings_detail.append(
            {
                "source": source,
                "target": target,
                "type": m.get("type") or "string",
                "raw_value": _preview(data.get(source)) if source in data else None,
                "missing": bool(source) and source not in data,
                "converted": _preview(fields.get(target)),
                "warning": (warning_by_field.get(target) or {}).get("message"),
            }
        )

    return {
        "route": route,
        "db_hits": db_hits,
        "unwrap": {"data_path": data_path, "found": unwrap_ok},
        "mappings": mappings_detail,
        "enum_translations": enum_translations,
        "warnings": warnings,
        "status": "partial" if warnings else "success",
        "fields": _json_safe(fields),
        "parse_ms": int((time.perf_counter() - started) * 1000),
    }


# ======================================================================
# 错误队列与指标（需要登录）
# ======================================================================
@router.get("/errors", dependencies=[Depends(get_current_user)])
def list_errors(
    error_type: str = Query("", description="错误类型过滤"),
    status: str = Query("", description="状态过滤：pending/reprocessing/manual/resolved"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """查看解析错误队列。"""
    query = db.query(ParseErrorQueue)
    if error_type:
        query = query.filter(ParseErrorQueue.error_type == error_type)
    if status:
        query = query.filter(ParseErrorQueue.status == status)
    total = query.count()
    rows = (
        query.order_by(ParseErrorQueue.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "uuid": r.uuid,
                "strategy_id": r.strategy_id,
                "error_type": r.error_type,
                "error_msg": r.error_msg,
                "retry_count": r.retry_count,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


@router.get("/metrics", dependencies=[Depends(get_current_user)])
def list_metrics(
    hours: int = Query(24, ge=1, le=720, description="最近 N 小时"),
    db: Session = Depends(get_db),
) -> list[dict]:
    """查看按小时聚合的入库指标。"""
    since = (datetime.now(BEIJING_TZ) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H")
    rows = (
        db.query(IngestionMetric)
        .filter(IngestionMetric.stat_hour >= since)
        .order_by(IngestionMetric.stat_hour.desc())
        .all()
    )
    return [
        {
            "stat_hour": r.stat_hour,
            "strategy_id": r.strategy_id,
            "strategy_name": r.strategy_name,
            "total_count": r.total_count,
            "success_count": r.success_count,
            "partial_count": r.partial_count,
            "fail_count": r.fail_count,
            "avg_parse_ms": round(r.total_parse_ms / r.total_count, 1) if r.total_count else 0,
        }
        for r in rows
    ]
