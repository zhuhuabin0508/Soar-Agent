"""已封禁 IP 管理 API。

提供已封禁 IP 列表查看、详情查询、手动解封、统计信息、导入导出。
供前端「已封禁 IP」页面和智能体工具使用。
"""
import csv
import io
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.banned_ip import BannedIP, _beijing_now
from app.schemas.common import to_dict, to_dict_list

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/banned-ips",
    tags=["banned-ips"],
    dependencies=[Depends(get_current_user)],
)


class ManualBanRequest(BaseModel):
    """手动新增封禁 IP 请求体。"""

    ip: str = Field(..., description="待封禁的 IP 地址")
    ban_level: str = Field("medium", description="封禁等级：low/medium/high/serious")
    ban_duration: int = Field(3600, description="封禁时长（秒），0 表示永久")
    region: str = Field("", description="归属地区")
    reason: str = Field("", description="封禁原因")


@router.get("")
def list_banned_ips(
    search: str = Query("", description="搜索 IP 地址"),
    status: str = Query("", description="状态过滤：active/expired/unblocked"),
    db: Session = Depends(get_db),
) -> list[dict]:
    """列出所有已封禁 IP（自动更新过期状态）。"""
    query = db.query(BannedIP)
    if search:
        query = query.filter(BannedIP.ip.contains(search))
    if status:
        query = query.filter(BannedIP.status == status)

    records = query.order_by(BannedIP.created_at.desc()).all()

    # 自动将过期的 active 记录标记为 expired
    # 北京时间（UTC+8）：数据库内统一存北京时间，与前端显示一致
    now = datetime.utcnow() + timedelta(hours=8)
    changed = False
    for r in records:
        if r.status == "active" and r.expired_at < now:
            r.status = "expired"
            changed = True
    if changed:
        db.commit()

    return to_dict_list(records)


@router.get("/stats")
def get_banned_stats(db: Session = Depends(get_db)) -> dict:
    """已封禁 IP 统计信息。"""
    total = db.query(BannedIP).count()
    active = db.query(BannedIP).filter(BannedIP.status == "active").count()
    expired = db.query(BannedIP).filter(BannedIP.status == "expired").count()
    unblocked = db.query(BannedIP).filter(BannedIP.status == "unblocked").count()
    return {"total": total, "active": active, "expired": expired, "unblocked": unblocked}


@router.post("", status_code=201)
def manual_ban_ip(
    body: ManualBanRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("admin")),
) -> dict:
    """手动新增封禁 IP（仅管理员）。

    与智能体自动封禁区分：source 字段标记为 ``manual``。
    若该 IP 已存在封禁记录，返回 409 冲突（不覆盖）。
    """
    # 校验封禁等级
    if body.ban_level not in ("low", "medium", "high", "serious"):
        raise HTTPException(status_code=400, detail="封禁等级必须为 low/medium/high/serious")

    # 查重：同 IP 已有记录则拒绝
    existing = db.query(BannedIP).filter(BannedIP.ip == body.ip).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"IP {body.ip} 已存在封禁记录（id={existing.id}, status={existing.status}）",
        )

    now = _beijing_now()
    # ban_duration=0 视为永久封禁（过期时间设为 9999 年）
    if body.ban_duration <= 0:
        expired_at = datetime(9999, 12, 31, 23, 59, 59)
    else:
        expired_at = now + timedelta(seconds=body.ban_duration)

    record = BannedIP(
        ip=body.ip,
        ban_level=body.ban_level,
        ban_duration=body.ban_duration,
        expired_at=expired_at,
        region=body.region or "",
        violation_count=1,
        reason=body.reason or "手动添加封禁",
        status="active",
        source="manual",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("手动新增封禁 IP: %s, level=%s, duration=%s", body.ip, body.ban_level, body.ban_duration)
    return to_dict(record)


@router.get("/{ip}")
def get_banned_ip(ip: str, db: Session = Depends(get_db)) -> dict:
    """查询单个 IP 的封禁状态。"""
    record = db.query(BannedIP).filter(BannedIP.ip == ip).first()
    if record is None:
        raise HTTPException(status_code=404, detail="该 IP 不在封禁列表中")
    return to_dict(record)


@router.delete("/{ip_id}")
def unban_ip(
    ip_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("admin")),
) -> dict:
    """手动解封 IP（仅管理员，逻辑删除：保留记录，状态置为 unblocked）。"""
    record = db.query(BannedIP).filter(BannedIP.id == ip_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    record.status = "unblocked"
    db.commit()
    logger.info("手动解封 IP: %s (id=%s)", record.ip, ip_id)
    return {"ok": True, "ip": record.ip}


@router.delete("/{ip_id}/hard")
def hard_delete_banned_ip(
    ip_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("admin")),
) -> dict:
    """硬删除已封禁 IP 记录（仅管理员，物理删除：从数据库彻底移除）。

    与 ``DELETE /{ip_id}``（解封，逻辑删除）区分：本端点直接 ``db.delete``，
    记录不可恢复。适用于清理误录/测试数据等场景。
    """
    record = db.query(BannedIP).filter(BannedIP.id == ip_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    ip_addr = record.ip
    db.delete(record)
    db.commit()
    logger.info("硬删除已封禁 IP 记录: id=%s, ip=%s", ip_id, ip_addr)
    return {"ok": True, "ip": ip_addr, "deleted": True}


# CSV 导出的列顺序（与导入保持一致）
_CSV_COLUMNS = [
    "ip", "ban_level", "ban_duration", "expired_at", "region",
    "violation_count", "reason", "status", "created_at",
]

# ban_level 中文映射（导出时友好显示）
_LEVEL_LABELS = {"low": "低", "medium": "中", "high": "高", "serious": "严重"}
_LEVEL_REVERSE = {v: k for k, v in _LEVEL_LABELS.items()}


@router.get("/export/csv")
def export_banned_ips(db: Session = Depends(get_db)):
    """导出所有已封禁 IP 为 CSV 文件。"""
    records = db.query(BannedIP).order_by(BannedIP.created_at.desc()).all()

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM，确保 Excel 正确识别 UTF-8
    writer = csv.writer(buf)
    # 表头
    writer.writerow(["IP地址", "封禁等级", "封禁时长(秒)", "过期时间", "归属地",
                      "违规次数", "封禁原因", "状态", "创建时间"])
    for r in records:
        writer.writerow([
            r.ip,
            _LEVEL_LABELS.get(r.ban_level, r.ban_level),
            r.ban_duration,
            r.expired_at.strftime("%Y-%m-%d %H:%M:%S") if r.expired_at else "",
            r.region or "",
            r.violation_count or 0,
            r.reason or "",
            r.status or "",
            r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        ])

    content = buf.getvalue()
    buf.close()
    filename = f"banned_ips_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import/csv")
async def import_banned_ips(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: object = Depends(require_role("admin")),
) -> dict:
    """从 CSV 文件导入已封禁 IP（仅管理员）。

    CSV 格式与导出一致，第一行为表头（跳过）。
    已存在的 IP（按 ip 去重）跳过，不覆盖。
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("gbk")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="文件编码不支持，请使用 UTF-8 编码")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="CSV 文件为空或只有表头")

    now = _beijing_now()
    imported = 0
    skipped = 0
    errors = []

    # 获取已存在的 IP 集合（去重）
    existing_ips = {r.ip for r in db.query(BannedIP).all()}

    for idx, row in enumerate(rows[1:], start=2):  # 从第 2 行开始（跳过表头）
        if not row or not row[0].strip():
            continue
        try:
            ip = row[0].strip()
            if ip in existing_ips:
                skipped += 1
                continue

            level_raw = row[1].strip() if len(row) > 1 else "medium"
            ban_level = _LEVEL_REVERSE.get(level_raw, level_raw if level_raw in _LEVEL_LABELS else "medium")
            ban_duration = int(row[2].strip()) if len(row) > 2 and row[2].strip() else 3600

            # 解析过期时间
            expired_at_str = row[3].strip() if len(row) > 3 else ""
            if expired_at_str:
                try:
                    expired_at = datetime.strptime(expired_at_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    expired_at = now + timedelta(seconds=ban_duration)
            else:
                expired_at = now + timedelta(seconds=ban_duration)

            region = row[4].strip() if len(row) > 4 else ""
            violation_count = int(row[5].strip()) if len(row) > 5 and row[5].strip() else 1
            reason = row[6].strip() if len(row) > 6 else ""
            status = row[7].strip() if len(row) > 7 else "active"

            record = BannedIP(
                ip=ip,
                ban_level=ban_level,
                ban_duration=ban_duration,
                expired_at=expired_at,
                region=region,
                violation_count=violation_count,
                reason=reason,
                status=status,
                source="manual",  # CSV 导入视为手动添加
            )
            db.add(record)
            existing_ips.add(ip)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"第 {idx} 行: {exc}")
            continue

    if imported > 0:
        db.commit()
    logger.info("CSV 导入完成: 导入 %d 条, 跳过 %d 条, 错误 %d 条", imported, skipped, len(errors))
    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }
