"""设备日志接收（被动接入）API。

供"对方设备主动推送日志"场景配置 syslog/kafka 等接收渠道，并查看
接收情况（指标 / 接收日志 / 运行状态）与触发接收异常通知。

主要端点：
- ``GET/POST /log-receivers``：全局接收渠道列表 / 创建
- ``GET /devices/{id}/receivers``：某设备的接收渠道列表（供设备对接页使用）
- ``GET/PUT/DELETE /log-receivers/{id}``：详情 / 更新 / 删除
- ``POST /log-receivers/{id}/reload``：应用配置（启动/停止/重启监听）
- ``GET /log-receivers/metrics``：接收指标（按渠道按小时）
- ``GET /log-receivers/receive-logs``：接收日志明细
- ``GET /log-receivers/summary``：接收情况总览
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.log_receiver_manager import (
    get_receiver_runtime_status,
    start_receiver_sync,
)
from app.core.timezone import BEIJING_TZ, beijing_now
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.device import Device
from app.models.log_receiver import (
    DeviceReceiveLog,
    DeviceReceiveMetric,
    LogReceiver,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/log-receivers",
    tags=["log-receivers"],
)


# ============ Schemas ============
class LogReceiverBase(BaseModel):
    """接收渠道创建/更新请求体（仅协议相关字段，公共校验在 handler 内）。"""

    device_id: int = Field(..., description="所属设备 ID")
    name: str = Field(..., description="接收渠道名称，如 syslog-514")
    protocol: str = Field("syslog", description="接收协议: syslog/kafka")
    enabled: bool = Field(True, description="是否启用")
    syslog_port: int | None = Field(None, ge=1, le=65535, description="syslog 监听端口")
    syslog_proto: str = Field("udp", description="syslog 传输: udp/tcp")
    syslog_bind: str = Field("0.0.0.0", description="syslog 监听地址")
    kafka_bootstrap: str = Field("", description="kafka bootstrap servers（逗号分隔）")
    kafka_topic: str = Field("", description="kafka topic（逗号分隔）")
    kafka_group: str = Field("soar-ingest", description="kafka 消费组")
    kafka_security: str = Field("", description="kafka 安全配置 JSON")
    format: str = Field("json", description="内容格式: json/raw")
    strategy_id: int | None = Field(None, description="手动绑定的解析策略 ID（NULL/0=自动匹配，>0 固定用该策略解析）")
    notify_interval_minutes: int = Field(0, ge=0, description="异常通知间隔（分钟）：0=仅首次通知一次，>0=异常期间每 N 分钟重复提醒")
    description: str = Field("", description="描述")


class ReceiverReloadResponse(BaseModel):
    id: int
    status: str
    message: str


# ============ 内部工具 ============
def _serialize(rec: LogReceiver, runtime: dict | None = None) -> dict:
    rr = runtime or get_receiver_runtime_status(rec.id)
    return {
        "id": rec.id,
        "device_id": rec.device_id,
        "device_name": rec.device_name,
        "name": rec.name,
        "protocol": rec.protocol,
        "enabled": bool(rec.enabled),
        "syslog_port": rec.syslog_port,
        "syslog_proto": rec.syslog_proto,
        "syslog_bind": rec.syslog_bind,
        "kafka_bootstrap": rec.kafka_bootstrap,
        "kafka_topic": rec.kafka_topic,
        "kafka_group": rec.kafka_group,
        "kafka_security": rec.kafka_security,
        "format": rec.format,
        "strategy_id": rec.strategy_id,
        "notify_interval_minutes": rec.notify_interval_minutes,
        "description": rec.description,
        "status": rec.status,
        "alive": rr.get("alive", False),
        "last_received_at": rec.last_received_at,
        "last_error": rec.last_error,
        "received_count": rec.received_count,
        "error_count": rec.error_count,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
    }


def _validate_payload(body: LogReceiverBase) -> None:
    """协议相关参数校验。"""
    protocol = body.protocol.lower()
    if protocol not in ("syslog", "kafka"):
        raise HTTPException(status_code=422, detail=f"不支持的接收协议: {body.protocol}，可选 syslog/kafka")
    if protocol == "syslog":
        if not body.syslog_port:
            raise HTTPException(status_code=422, detail="syslog 协议必须配置监听端口 syslog_port")
    else:  # kafka
        if not body.kafka_bootstrap or not body.kafka_topic:
            raise HTTPException(status_code=422, detail="kafka 协议必须配置 kafka_bootstrap 与 kafka_topic")


def _apply_fields(rec: LogReceiver, body: LogReceiverBase, device: Device) -> None:
    rec.device_id = device.id
    rec.device_name = device.name
    rec.name = body.name.strip()
    rec.protocol = body.protocol.lower()
    rec.enabled = 1 if body.enabled else 0
    rec.syslog_port = body.syslog_port
    rec.syslog_proto = body.syslog_proto
    rec.syslog_bind = body.syslog_bind
    rec.kafka_bootstrap = body.kafka_bootstrap
    rec.kafka_topic = body.kafka_topic
    rec.kafka_group = body.kafka_group
    rec.kafka_security = body.kafka_security
    rec.format = body.format
    rec.strategy_id = body.strategy_id
    rec.notify_interval_minutes = body.notify_interval_minutes
    rec.description = body.description


# ============ 全局列表 / 创建 ============
@router.get("", dependencies=[Depends(get_current_user)])
def list_receivers(
    device_id: int = Query(0, description="按设备过滤"),
    protocol: str = Query("", description="按协议过滤: syslog/kafka"),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = db.query(LogReceiver)
    if device_id:
        q = q.filter(LogReceiver.device_id == device_id)
    if protocol:
        q = q.filter(LogReceiver.protocol == protocol)
    rows = q.order_by(LogReceiver.id.desc()).all()
    return [_serialize(r) for r in rows]


@router.get("/summary", dependencies=[Depends(get_current_user)])
def receiver_summary(db: Session = Depends(get_db)) -> dict:
    """接收情况总览：渠道数 / 运行中数 / 异常数 / 今日接收与失败数。"""
    rows = db.query(LogReceiver).all()
    # 健康 = syslog 已 listening / kafka 已 running；binding/connecting 为过渡态不计入
    running = sum(1 for r in rows if r.status in ("listening", "running") and bool(r.enabled))
    abnormal = sum(
        1 for r in rows
        if r.status in ("start_failed", "failed", "stopped") and bool(r.enabled)
    )

    today_prefix = beijing_now().strftime("%Y-%m-%dT")
    mrows = (
        db.query(DeviceReceiveMetric)
        .filter(DeviceReceiveMetric.stat_hour.like(today_prefix + "%"))
        .all()
    )
    today_total = sum(m.total_count or 0 for m in mrows)
    today_fail = sum(m.fail_count or 0 for m in mrows)

    return {
        "receiver_count": len(rows),
        "running_count": running,
        "abnormal_count": abnormal,
        "today_total": today_total,
        "today_fail": today_fail,
    }


@router.post("", status_code=201, dependencies=[Depends(require_role("admin"))])
def create_receiver(body: LogReceiverBase, db: Session = Depends(get_db)) -> dict:
    """创建接收渠道并立即应用（启动监听）。"""
    _validate_payload(body)
    device = db.query(Device).filter(Device.id == body.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    dup = (
        db.query(LogReceiver)
        .filter(LogReceiver.device_id == body.device_id, LogReceiver.name == body.name.strip())
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"该设备下已存在同名接收渠道: {body.name}",
        )
    rec = LogReceiver()
    _apply_fields(rec, body, device)
    # 先停用，等校验通过后再启动（避免端口冲突导致失败时留下异常状态）
    rec.enabled = 1 if body.enabled else 0
    db.add(rec)
    db.commit()
    db.refresh(rec)
    logger.info("日志接收渠道创建: id=%s device=%s protocol=%s", rec.id, device.name, rec.protocol)

    # 应用配置（启动监听并同步核实 bind/connect 结果）
    if rec.enabled:
        result = start_receiver_sync(rec.id)
        if result == "failed":
            # 端口占用/连接失败：回滚本次创建，避免留下无效渠道
            db.refresh(rec)
            error = (rec.last_error or "") or "绑定/连接失败"
            db.query(DeviceReceiveLog).filter(DeviceReceiveLog.receiver_id == rec.id).delete()
            db.delete(rec)
            db.commit()
            raise HTTPException(status_code=409, detail=f"接收渠道启动失败：{error}")
    db.refresh(rec)
    return _serialize(rec)


# ============ 设备维度接收渠道（供设备对接页使用） ============
@router.get("/by-device/{device_id}", dependencies=[Depends(get_current_user)])
def list_receivers_by_device(device_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(LogReceiver)
        .filter(LogReceiver.device_id == device_id)
        .order_by(LogReceiver.id.desc())
        .all()
    )
    return [_serialize(r) for r in rows]


# ============ 指标 & 接收日志（静态路径，需在 /{receiver_id} 之前注册） ============
@router.get("/metrics", dependencies=[Depends(get_current_user)])
def receive_metrics(
    hours: int = Query(24, ge=1, le=720, description="最近 N 小时"),
    receiver_id: int = Query(0, description="按渠道过滤"),
    db: Session = Depends(get_db),
) -> list[dict]:
    since = (datetime.now(BEIJING_TZ) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H")
    q = db.query(DeviceReceiveMetric).filter(DeviceReceiveMetric.stat_hour >= since)
    if receiver_id:
        q = q.filter(DeviceReceiveMetric.receiver_id == receiver_id)
    rows = q.order_by(DeviceReceiveMetric.stat_hour.desc()).all()
    return [
        {
            "stat_hour": m.stat_hour,
            "receiver_id": m.receiver_id,
            "receiver_name": m.receiver_name,
            "device_id": m.device_id,
            "protocol": m.protocol,
            "total_count": m.total_count,
            "success_count": m.success_count,
            "partial_count": m.partial_count,
            "fail_count": m.fail_count,
        }
        for m in rows
    ]


@router.get("/receive-logs", dependencies=[Depends(get_current_user)])
def receive_logs(
    receiver_id: int = Query(0, description="按渠道过滤"),
    device_id: int = Query(0, description="按设备过滤"),
    parse_status: str = Query("", description="解析状态过滤: success/partial/fail/received"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(DeviceReceiveLog)
    if receiver_id:
        q = q.filter(DeviceReceiveLog.receiver_id == receiver_id)
    if device_id:
        q = q.filter(DeviceReceiveLog.device_id == device_id)
    if parse_status:
        q = q.filter(DeviceReceiveLog.parse_status == parse_status)
    total = q.count()
    rows = (
        q.order_by(DeviceReceiveLog.received_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "receiver_id": r.receiver_id,
                "device_id": r.device_id,
                "device_name": r.device_name,
                "protocol": r.protocol,
                "raw_data": r.raw_data,
                "source_ip": r.source_ip,
                "parse_status": r.parse_status,
                "parse_error": r.parse_error,
                "alert_id": r.alert_id,
                "received_at": r.received_at,
            }
            for r in rows
        ],
    }


# ============ 详情 / 更新 / 删除 / 启停 ============
@router.get("/{receiver_id}", dependencies=[Depends(get_current_user)])
def get_receiver(receiver_id: int, db: Session = Depends(get_db)) -> dict:
    rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="接收渠道不存在")
    return _serialize(rec)


@router.put("/{receiver_id}", dependencies=[Depends(require_role("admin"))])
def update_receiver(receiver_id: int, body: LogReceiverBase, db: Session = Depends(get_db)) -> dict:
    """更新接收渠道，若被启用则重启监听以应用新配置。"""
    rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="接收渠道不存在")
    _validate_payload(body)
    if rec.device_id != body.device_id:
        device = db.query(Device).filter(Device.id == body.device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
    else:
        device = db.query(Device).filter(Device.id == rec.device_id).first()

    _apply_fields(rec, body, device)
    db.commit()
    logger.info("日志接收渠道更新: id=%s", rec.id)

    # 应用配置：停掉旧线程再按需要重启（start_receiver_sync 内部会停止旧代线程）
    if rec.enabled:
        result = start_receiver_sync(rec.id)
        if result == "failed":
            db.refresh(rec)
            raise HTTPException(
                status_code=409,
                detail=f"接收渠道更新后启动失败：{rec.last_error or '绑定/连接失败'}",
            )
    else:
        from app.core.log_receiver_manager import stop_receiver_thread

        stop_receiver_thread(rec.id)
        rec.status = "stopped"
        db.commit()

    db.refresh(rec)
    return _serialize(rec)


@router.patch("/{receiver_id}/reload", dependencies=[Depends(require_role("admin"))])
def reload_receiver(receiver_id: int, db: Session = Depends(get_db)) -> ReceiverReloadResponse:
    """启停/重启指定接收渠道的监听线程。"""
    rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="接收渠道不存在")
    from app.core.log_receiver_manager import stop_receiver_thread

    if rec.enabled:
        result = start_receiver_sync(rec.id)
        if result == "failed":
            rec.status = "failed"
            db.commit()
            db.refresh(rec)
            return ReceiverReloadResponse(
                id=rec.id, status="failed",
                message=f"接收渠道启动失败：{rec.last_error or '绑定/连接失败'}",
            )
        db.refresh(rec)
        return ReceiverReloadResponse(id=rec.id, status="running", message="接收渠道已启动")
    stop_receiver_thread(rec.id)
    rec.status = "stopped"
    db.commit()
    return ReceiverReloadResponse(id=rec.id, status="stopped", message="接收渠道已停止")


@router.delete("/{receiver_id}", status_code=204, dependencies=[Depends(require_role("admin"))])
def delete_receiver(receiver_id: int, db: Session = Depends(get_db)) -> None:
    """删除接收渠道并停止监听。"""
    rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="接收渠道不存在")
    from app.core.log_receiver_manager import stop_receiver_thread

    stop_receiver_thread(rec.id)
    # 级联清理该渠道的接收明细与聚合指标（孤儿数据）
    db.query(DeviceReceiveLog).filter(DeviceReceiveLog.receiver_id == receiver_id).delete()
    db.query(DeviceReceiveMetric).filter(DeviceReceiveMetric.receiver_id == receiver_id).delete()
    db.delete(rec)
    db.commit()
    logger.info("日志接收渠道删除: id=%s", receiver_id)
