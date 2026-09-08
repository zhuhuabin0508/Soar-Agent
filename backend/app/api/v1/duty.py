"""值班管理 API。

核心能力：
- 值班人员 CRUD + Excel 批量导入 / 模板下载
- 值班表自动生成（白班/晚班轮换算法，按工作日/非工作日分流）+ 确认发布
- 值班表查看（列表 / 月视图，含人员姓名电话富化）+ 手动调班（记录调班日志）
- 请假申请 + 审批（请假期间自动跳过）
- 调班记录查询
- 特殊日期覆盖（手动标记某日为工作日/非工作日，覆盖内置节假日表）

权限：view 可查看/导出，edit 可新增/编辑/生成/调班/审批，delete 可删除人员/记录。
"""
import io
import logging
import uuid
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.holidays import get_holiday_name, is_holiday
from app.core.sanitizer import sanitize_text
from app.core.timezone import beijing_now, to_beijing_iso
from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.duty import (
    DutyAdjustmentLog,
    DutyLeaveLog,
    DutyMember,
    DutyRecord,
    DutyRotationCursor,
)
from app.models.system_config import SystemConfig
from app.models.user import User
from app.schemas.common import paginate as paginate_query
from app.schemas.duty import (
    BatchIds,
    DUTY_CATEGORIES,
    LeaveApprove,
    LeaveCreate,
    ManualAdjustRequest,
    MemberBatchStatusUpdate,
    MemberReorderRequest,
    RecordStatusUpdate,
    ScheduleCopyRequest,
    ScheduleGenerateRequest,
    SpecialDatesUpdate,
    DutyMemberCreate,
    DutyMemberUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/duty", tags=["duty"])

# 值班类别中文 → 标识映射（Excel 导入用）
_CATEGORY_LABEL_MAP = {
    "长期白班": "PERMANENT_DAY",
    "白班": "DAY",
    "晚班": "NIGHT",
    "permanent_day": "PERMANENT_DAY",
    "day": "DAY",
    "night": "NIGHT",
}
_SPECIAL_DATES_KEY = "duty_special_dates"
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


# ============ 辅助函数 ============

def _get_member_or_404(db: Session, member_id: int, include_deleted: bool = False) -> DutyMember:
    """按 ID 查值班人员，不存在/已删除抛 404。"""
    q = db.query(DutyMember).filter(DutyMember.id == member_id)
    if not include_deleted:
        q = q.filter(DutyMember.deleted_at.is_(None))
    member = q.first()
    if member is None:
        raise HTTPException(status_code=404, detail="值班人员不存在")
    return member


def _get_record_or_404(db: Session, record_id: int) -> DutyRecord:
    rec = db.query(DutyRecord).filter(DutyRecord.id == record_id).first()
    if rec is None:
        raise HTTPException(status_code=404, detail="值班记录不存在")
    return rec


def _load_special_dates(db: Session) -> dict[str, str]:
    """从 SystemConfig 读取特殊日期覆盖 {YYYY-MM-DD: holiday/workday}。"""
    cfg = db.query(SystemConfig).filter(SystemConfig.key == _SPECIAL_DATES_KEY).first()
    if not cfg or not cfg.value:
        return {}
    import json
    try:
        data = json.loads(cfg.value)
        return {k: v for k, v in data.items() if v in ("holiday", "workday")}
    except (ValueError, TypeError):
        return {}


def _save_special_dates(db: Session, overrides: dict[str, str]) -> None:
    import json
    cfg = db.query(SystemConfig).filter(SystemConfig.key == _SPECIAL_DATES_KEY).first()
    payload = json.dumps(overrides, ensure_ascii=False)
    if cfg is None:
        cfg = SystemConfig(key=_SPECIAL_DATES_KEY, value=payload,
                          description="值班管理-特殊日期覆盖（手动标记工作日/非工作日）")
        db.add(cfg)
    else:
        cfg.value = payload
    db.commit()


def _sync_records_is_holiday(db: Session, dates: set[date]) -> None:
    """特殊日期变更后，同步刷新受影响日期的排班记录 is_holiday。"""
    if not dates:
        return
    overrides = _load_special_dates(db)
    recs = db.query(DutyRecord).filter(DutyRecord.duty_date.in_(dates)).all()
    for r in recs:
        r.is_holiday = is_holiday(r.duty_date, overrides)
    db.commit()


def _active_members_by_category(db: Session, category: str) -> list[DutyMember]:
    """取某类别下启用且未删除的人员，按 sort_order、id 排序（轮换顺序）。"""
    return (
        db.query(DutyMember)
        .filter(
            DutyMember.duty_category == category,
            DutyMember.status == "active",
            DutyMember.deleted_at.is_(None),
        )
        .order_by(DutyMember.sort_order.asc(), DutyMember.id.asc())
        .all()
    )


def _day_rotation_pool(db: Session) -> list[DutyMember]:
    """非工作日白班轮换池：DAY + PERMANENT_DAY 合并，按 sort_order、id 全局排序。

    长期白班人员也参与节假日/周末白班轮换，故将其纳入同一轮换池。
    工作日白班仍优先取 PERMANENT_DAY 主值班人（见 generate 逻辑），仅在无长期白班时回退至此池轮换。
    """
    pool = _active_members_by_category(db, "DAY") + _active_members_by_category(db, "PERMANENT_DAY")
    return sorted(pool, key=lambda m: (m.sort_order, m.id))


def _get_cursor(db: Session, category: str) -> DutyRotationCursor:
    cur = db.query(DutyRotationCursor).filter(DutyRotationCursor.category == category).first()
    if cur is None:
        cur = DutyRotationCursor(category=category, last_index=-1)
        db.add(cur)
        db.flush()
    return cur


def _pick_next(members: list[DutyMember], last_index: int, skip_ids: set[int]):
    """从 last_index 的下一位开始轮换，跳过 skip_ids 中的人员。

    Returns:
        (member_or_None, new_index)。全员被跳过/列表为空时返回 (None, last_index)。
    """
    if not members:
        return None, last_index
    n = len(members)
    for offset in range(n):
        idx = (last_index + 1 + offset) % n  # 从下一位开始
        m = members[idx]
        if m.id in skip_ids:
            continue
        return m, idx
    return None, last_index


def _member_index(members: list[DutyMember], member_id: int) -> int:
    """返回 member_id 在轮换列表中的下标（按 sort_order 排序），不存在返回 -1。"""
    for i, m in enumerate(members):
        if m.id == member_id:
            return i
    return -1


def _load_approved_leaves(db: Session, start: date, end: date):
    """取日期范围内已批准的请假记录。"""
    return (
        db.query(DutyLeaveLog)
        .filter(
            DutyLeaveLog.status == "approved",
            DutyLeaveLog.start_date <= end,
            DutyLeaveLog.end_date >= start,
        )
        .all()
    )


def _leave_skip_ids(leaves, d: date, shift: str) -> set[int]:
    """计算某天某班次应跳过的请假人员 ID 集合。shift: DAY/NIGHT。"""
    skip = set()
    for lv in leaves:
        if lv.start_date <= d <= lv.end_date and lv.shift in ("ALL", shift):
            skip.add(lv.member_id)
    return skip


def _member_brief(member: DutyMember | None) -> dict | None:
    """人员精简信息（用于富化值班记录）。"""
    if member is None:
        return None
    return {
        "id": member.id,
        "name": member.name,
        "phone": member.phone,
        "group_name": member.group_name,
        "duty_category": member.duty_category,
    }


def _enrich_record(db: Session, rec: DutyRecord, approved_leaves: list = None) -> dict:
    """值班记录富化：附带白班/晚班人员信息、日期类型名称、星期、请假影响标记。

    - ``day_needs_adjust`` / ``night_needs_adjust``：该班次值班人员是否处于已批准请假
      范围内（需手动替换或重新分配）。
    - ``approved_leaves`` 可选预加载列表，避免 N+1 查询；为 None 时内部查询。
    """
    day_m = db.query(DutyMember).filter(DutyMember.id == rec.day_member_id).first() if rec.day_member_id else None
    night_m = db.query(DutyMember).filter(DutyMember.id == rec.night_member_id).first() if rec.night_member_id else None
    d = rec.duty_date
    # 查询覆盖该日的已批准请假（影响 DAY/NIGHT/ALL 班次）
    if approved_leaves is None:
        approved_leaves = (
            db.query(DutyLeaveLog)
            .filter(
                DutyLeaveLog.status == "approved",
                DutyLeaveLog.start_date <= d,
                DutyLeaveLog.end_date >= d,
            )
            .all()
        )
    day_needs = False
    night_needs = False
    for lv in approved_leaves:
        if lv.member_id == rec.day_member_id and lv.shift in ("DAY", "ALL"):
            day_needs = True
        if lv.member_id == rec.night_member_id and lv.shift in ("NIGHT", "ALL"):
            night_needs = True
    return {
        **rec.to_dict(),
        "weekday": WEEKDAY_CN[d.weekday()],
        "day_type": "非工作日" if rec.is_holiday else "工作日",
        "holiday_name": get_holiday_name(d) if rec.is_holiday else None,
        "day_member": _member_brief(day_m),
        "night_member": _member_brief(night_m),
        "day_needs_adjust": day_needs,
        "night_needs_adjust": night_needs,
    }


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _to_xlsx_bytes(rows: list[list], sheet_name: str = "Sheet1") -> bytes:
    """生成 .xlsx 字节流。rows[0] 为表头。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    header_fill = PatternFill(start_color="FF0066CC", end_color="FF0066CC", fill_type="solid")
    header_font = Font(color="FFFFFFFF", bold=True)
    for r_idx, row in enumerate(rows, 1):
        for c_idx, val in enumerate(row, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            if r_idx == 1:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
    # 自适应列宽
    for c_idx in range(1, len(rows[0]) + 1):
        max_len = 0
        for r_idx in range(1, len(rows) + 1):
            v = ws.cell(row=r_idx, column=c_idx).value
            if v is not None:
                # 中文按 2 计算宽度
                length = sum(2 if ord(ch) > 127 else 1 for ch in str(v))
                if length > max_len:
                    max_len = length
        ws.column_dimensions[get_column_letter(c_idx)].width = min(max(max_len + 2, 10), 40)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ============ 值班人员管理 ============

@router.get("/members")
def list_members(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    group_name: str = Query("", description="按组别筛选"),
    duty_category: str = Query("", description="按值班类别筛选"),
    keyword: str = Query("", description="姓名模糊搜索"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_member", "view")),
):
    """值班人员列表（分页，支持组别/类别筛选 + 姓名模糊搜索）。"""
    q = db.query(DutyMember).filter(DutyMember.deleted_at.is_(None))
    if group_name:
        q = q.filter(DutyMember.group_name == group_name)
    if duty_category in DUTY_CATEGORIES:
        q = q.filter(DutyMember.duty_category == duty_category)
    if keyword:
        q = q.filter(DutyMember.name.like(f"%{keyword}%"))
    q = q.order_by(DutyMember.sort_order.asc(), DutyMember.id.asc())
    return paginate_query(q, page, size)


@router.get("/members/all")
def list_all_members(
    category: str = Query("", description="按值班类别筛选（用于排班选择器）"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_member", "view")),
):
    """全部启用人员（不分页，供前端选择器/排班使用）。"""
    q = db.query(DutyMember).filter(
        DutyMember.deleted_at.is_(None), DutyMember.status == "active"
    )
    if category in DUTY_CATEGORIES:
        q = q.filter(DutyMember.duty_category == category)
    q = q.order_by(DutyMember.sort_order.asc(), DutyMember.id.asc())
    return [m.to_dict() for m in q.all()]


@router.post("/members", status_code=201)
def create_member(
    body: DutyMemberCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_member", "edit")),
):
    """新增值班人员。"""
    member = DutyMember(
        name=sanitize_text(body.name).strip(),
        phone=sanitize_text(body.phone).strip(),
        group_name=sanitize_text(body.group_name).strip(),
        duty_category=body.duty_category,
        is_primary=body.is_primary if body.duty_category == "PERMANENT_DAY" else False,
        sort_order=body.sort_order,
        status=body.status,
    )
    if not member.name:
        raise HTTPException(status_code=400, detail="姓名不能为空")
    if not member.phone:
        raise HTTPException(status_code=400, detail="电话不能为空")
    db.add(member)
    db.commit()
    db.refresh(member)
    return member.to_dict()


@router.put("/members/{member_id}")
def update_member(
    member_id: int,
    body: DutyMemberUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_member", "edit")),
):
    """编辑值班人员。修改值班类别后将影响后续值班表生成。"""
    member = _get_member_or_404(db, member_id)
    category_changed = body.duty_category is not None and body.duty_category != member.duty_category
    for field in ("name", "phone", "group_name", "duty_category", "is_primary", "sort_order", "status"):
        val = getattr(body, field, None)
        if val is not None:
            if field in ("name", "phone", "group_name"):
                val = sanitize_text(val).strip() if val else val
            setattr(member, field, val)
    # is_primary 仅对 PERMANENT_DAY 有效
    if member.duty_category != "PERMANENT_DAY":
        member.is_primary = False
    if member.name == "":
        raise HTTPException(status_code=400, detail="姓名不能为空")
    if member.phone == "":
        raise HTTPException(status_code=400, detail="电话不能为空")
    db.commit()
    db.refresh(member)
    return {**member.to_dict(), "category_changed": category_changed}


@router.delete("/members/{member_id}")
def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_member", "delete")),
):
    """软删除值班人员。历史值班记录保留；若有未来值班安排，返回需重新排班提示。"""
    member = _get_member_or_404(db, member_id)
    today = date.today()
    future_count = (
        db.query(DutyRecord)
        .filter(
            DutyRecord.duty_date >= today,
            (DutyRecord.day_member_id == member_id) | (DutyRecord.night_member_id == member_id),
        )
        .count()
    )
    member.deleted_at = beijing_now()
    db.commit()
    return {
        "deleted": True,
        "future_duty_count": future_count,
        "message": f"已删除该人员，历史值班记录保留；该人员有 {future_count} 条未来值班安排，建议重新生成值班表"
        if future_count else "已删除该人员",
    }


@router.get("/members/import-template")
def download_member_template(
    _user: User = Depends(require_permission("duty_member", "view")),
):
    """下载值班人员 Excel 导入模板。"""
    headers = ["姓名", "电话", "组别", "值班类别", "主值班人", "排序", "状态"]
    example = ["张三", "13800138000", "运维组", "晚班", "否", "0", "启用"]
    note = [
        ["# 导入说明：值班类别 可选值 长期白班 / 白班 / 晚班"],
        ["# 主值班人 仅长期白班 有效，可选 是 / 否"],
        ["# 状态 可选 启用 / 停用；排序 为数字，值小的优先轮换"],
        ["# 导入时请删除以 # 开头的说明行"],
    ]
    rows = [headers, example] + note
    content = _to_xlsx_bytes(rows, "值班人员导入模板")
    from urllib.parse import quote
    filename = quote("值班人员导入模板.xlsx")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/members/import")
def import_members(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_member", "edit")),
):
    """Excel 批量导入值班人员。返回成功/失败条数与错误明细。"""
    from openpyxl import load_workbook

    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")
    try:
        wb = load_workbook(file.file, read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Excel 文件解析失败，请使用下载的模板")
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = [str(c or "").strip() for c in next(rows_iter)]
    except StopIteration:
        raise HTTPException(status_code=400, detail="Excel 文件为空")

    # 列名 → 索引（容错匹配）
    def col(name: str) -> int:
        for i, h in enumerate(header):
            if name in h:
                return i
        return -1

    idx_name = col("姓名")
    idx_phone = col("电话")
    idx_group = col("组别")
    idx_cat = col("值班类别")
    idx_primary = col("主值班")
    idx_sort = col("排序")
    idx_status = col("状态")
    if idx_name < 0 or idx_phone < 0 or idx_cat < 0:
        raise HTTPException(status_code=400, detail="缺少必填列：姓名 / 电话 / 值班类别")

    success = 0
    errors: list[str] = []
    line = 1
    for row in rows_iter:
        line += 1
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        if str(row[0] or "").strip().startswith("#"):
            continue
        name = str(row[idx_name] or "").strip()
        phone = str(row[idx_phone] or "").strip()
        group_name = str(row[idx_group] or "").strip() if idx_group >= 0 else ""
        cat_raw = str(row[idx_cat] or "").strip()
        category = _CATEGORY_LABEL_MAP.get(cat_raw) or _CATEGORY_LABEL_MAP.get(cat_raw.lower())
        if category is None:
            errors.append(f"第{line}行：值班类别「{cat_raw}」无效")
            continue
        if not name or not phone:
            errors.append(f"第{line}行：姓名/电话不能为空")
            continue
        is_primary = False
        if idx_primary >= 0:
            pv = str(row[idx_primary] or "").strip()
            is_primary = pv in ("是", "1", "true", "Y", "y")
        sort_order = 0
        if idx_sort >= 0 and row[idx_sort] is not None:
            try:
                sort_order = int(row[idx_sort])
            except (TypeError, ValueError):
                sort_order = 0
        status = "active"
        if idx_status >= 0:
            sv = str(row[idx_status] or "").strip()
            status = "inactive" if sv in ("停用", "inactive", "0") else "active"
        member = DutyMember(
            name=sanitize_text(name), phone=sanitize_text(phone),
            group_name=sanitize_text(group_name), duty_category=category,
            is_primary=is_primary if category == "PERMANENT_DAY" else False,
            sort_order=sort_order, status=status,
        )
        db.add(member)
        success += 1
    db.commit()
    return {"success": success, "errors": errors, "total_errors": len(errors)}


# ============ 值班表生成 ============

@router.post("/schedule/generate")
def generate_schedule(
    body: ScheduleGenerateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "edit")),
):
    """自动生成值班表。

    轮换算法：
    - 工作日：白班由 PERMANENT_DAY 主值班人固定值守；晚班从 NIGHT 轮换。
    - 非工作日：白班从 DAY 轮换；晚班从 NIGHT 连续轮换（不重置）。
    - 轮换游标持久化，保证连续性。
    - 冲突处理：同人不可同时排白班+晚班；请假人员自动跳过；某类别无人则留空并告警。
    """
    if body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于起始日期")
    span = (body.end_date - body.start_date).days + 1
    if span > 366:
        raise HTTPException(status_code=400, detail="日期范围不能超过 366 天")

    overrides = _load_special_dates(db)
    perm_members = _active_members_by_category(db, "PERMANENT_DAY")
    day_members = _day_rotation_pool(db)  # 非工作日白班轮换池：DAY + PERMANENT_DAY
    night_members = _active_members_by_category(db, "NIGHT")
    leaves = _load_approved_leaves(db, body.start_date, body.end_date)

    night_cursor = _get_cursor(db, "NIGHT")
    day_cursor = _get_cursor(db, "DAY")
    night_idx = night_cursor.last_index
    day_idx = day_cursor.last_index

    batch = uuid.uuid4().hex[:12]
    warnings: list[str] = []
    if not perm_members:
        warnings.append("无「长期白班」人员，工作日白班将回退至白班轮换池")
    if not day_members:
        warnings.append("无「白班/长期白班」人员，非工作日白班将留空（待分配）")
    if not night_members:
        warnings.append("无「晚班」人员，所有晚班将留空（待分配）")

    # 已有记录（用于冲突策略）
    existing = {
        rec.duty_date: rec
        for rec in db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= body.start_date, DutyRecord.duty_date <= body.end_date)
        .all()
    }

    new_records: list[DutyRecord] = []
    for d in _daterange(body.start_date, body.end_date):
        is_hol = is_holiday(d, overrides)
        existing_rec = existing.get(d)

        # fill 策略：若该日已有记录，跳过（仅填充无记录的日期）
        if existing_rec is not None and body.conflict_strategy == "fill":
            continue

        night_skip = _leave_skip_ids(leaves, d, "NIGHT")
        day_skip = _leave_skip_ids(leaves, d, "DAY")

        # 白班
        day_member = None
        if not is_hol:
            # 工作日：长期白班主值班人
            primary = next((m for m in perm_members if m.id not in day_skip), None)
            if primary is None:
                primary = next((m for m in perm_members), None)  # 请假回退到任意长期白班
            if primary is not None:
                day_member = primary
            else:
                # 回退到白班轮换池（告警已在开头给出）
                day_member, day_idx = _pick_next(day_members, day_idx, day_skip)
        else:
            # 非工作日：白班轮换池（DAY + PERMANENT_DAY）轮换
            day_member, day_idx = _pick_next(day_members, day_idx, day_skip)

        # 晚班：NIGHT 连续轮换；避免与白班同人
        night_skip_with_day = set(night_skip)
        if day_member is not None:
            night_skip_with_day.add(day_member.id)
        night_member, night_idx = _pick_next(night_members, night_idx, night_skip_with_day)

        status = "published" if body.auto_publish else "draft"

        if existing_rec is not None and body.conflict_strategy == "overwrite":
            existing_rec.is_holiday = is_hol
            existing_rec.day_member_id = day_member.id if day_member else None
            existing_rec.night_member_id = night_member.id if night_member else None
            existing_rec.status = status
            existing_rec.generated_batch = batch
            rec = existing_rec
        else:
            rec = DutyRecord(
                duty_date=d,
                day_member_id=day_member.id if day_member else None,
                night_member_id=night_member.id if night_member else None,
                is_holiday=is_hol,
                status=status,
                generated_batch=batch,
            )
            db.add(rec)
            new_records.append(rec)

        if day_member is None and is_hol:
            pass  # 非工作日无白班人员，已在 warnings 提示
        if night_member is None:
            pass  # 无晚班人员，已在 warnings 提示

    # 更新游标（保证轮换连续性）
    night_cursor.last_index = night_idx
    day_cursor.last_index = day_idx
    db.commit()

    # 返回预览（富化）
    all_recs = (
        db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= body.start_date, DutyRecord.duty_date <= body.end_date)
        .order_by(DutyRecord.duty_date.asc())
        .all()
    )
    return {
        "batch": batch,
        "count": len(all_recs),
        "records": [_enrich_record(db, r) for r in all_recs],
        "warnings": warnings,
    }


@router.post("/schedule/confirm")
def confirm_schedule(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "edit")),
):
    """确认发布值班表（将范围内的草稿记录改为已发布）。"""
    recs = (
        db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= start_date, DutyRecord.duty_date <= end_date)
        .all()
    )
    published = 0
    for r in recs:
        if r.status == "draft":
            r.status = "published"
            published += 1
    db.commit()
    return {"published": published, "total": len(recs)}


@router.get("/schedule")
def list_schedule(
    start_date: date = Query(..., description="起始日期"),
    end_date: date = Query(..., description="结束日期"),
    group_name: str = Query("", description="按组别筛选"),
    member_id: int = Query(0, description="按人员筛选"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "view")),
):
    """值班表列表视图（富化人员信息）。"""
    q = (
        db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= start_date, DutyRecord.duty_date <= end_date)
        .order_by(DutyRecord.duty_date.asc())
    )
    recs = q.all()
    result = [_enrich_record(db, r) for r in recs]
    # 组别/人员筛选在富化后做
    if group_name or member_id:
        filtered = []
        for r in result:
            dm = r.get("day_member")
            nm = r.get("night_member")
            if group_name:
                g_ok = (dm and dm["group_name"] == group_name) or (nm and nm["group_name"] == group_name)
                if not g_ok:
                    continue
            if member_id:
                m_ok = (dm and dm["id"] == member_id) or (nm and nm["id"] == member_id)
                if not m_ok:
                    continue
            filtered.append(r)
        result = filtered
    return {"items": result, "total": len(result)}


@router.get("/schedule/month")
def month_schedule(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "view")),
):
    """值班表月视图：返回该月每天的记录（富化），便于日历渲染。"""
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    recs = (
        db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= start, DutyRecord.duty_date <= end)
        .order_by(DutyRecord.duty_date.asc())
        .all()
    )
    by_date = {r.duty_date.isoformat(): _enrich_record(db, r) for r in recs}
    overrides = _load_special_dates(db)
    today = date.today()
    # 补齐当月每一天（无记录的日期返回占位结构）
    days = []
    for d in _daterange(start, end):
        item = by_date.get(d.isoformat())
        if item is None:
            days.append({
                "duty_date": d.isoformat(),
                "weekday": WEEKDAY_CN[d.weekday()],
                "day_type": "非工作日" if is_holiday(d, overrides) else "工作日",
                "is_holiday": is_holiday(d, overrides),
                "holiday_name": get_holiday_name(d) if is_holiday(d, overrides) else None,
                "day_member": None,
                "night_member": None,
                "status": None,
                "is_today": d == today,
            })
        else:
            # 实时套用特殊日期覆盖重新计算，避免排班生成后设置的特殊日期不生效
            is_hol = is_holiday(d, overrides)
            item["is_holiday"] = is_hol
            item["day_type"] = "非工作日" if is_hol else "工作日"
            item["holiday_name"] = get_holiday_name(d) if is_hol else None
            item["is_today"] = d == today
            days.append(item)
    return {"year": year, "month": month, "days": days}


@router.put("/schedule/{record_id}")
def adjust_record(
    record_id: int,
    body: ManualAdjustRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_schedule", "edit")),
):
    """手动调班：替换某天某班次的值班人员，并记录调班日志。

    轮换游标重锚定规则：手动调整当前及未来班次时，按所派人员重置对应轮换游标，
    使后续自动排班从该员「下一位」顺序继续。例如周末白班手动设为 A，则下个周末/节假日
    白班自动排 B、再排 C、D……。历史日期修订不重锚定，避免干扰当前轮换进度。

    自动接排：当周末/节假日白班重锚定生效时，一并重生该日之后已存在的草稿非工作日白班，
    让后续排班立即按新顺序顺延（无需再次手动生成）。晚班同理：手动调晚班后重生该日之后
    全部草稿晚班（所有日期连续轮换）。仅作用于草稿状态记录；已发布/已过期记录不受影响。
    """
    rec = _get_record_or_404(db, record_id)
    if rec.status == "expired":
        raise HTTPException(status_code=400, detail="已过期的值班记录不可调整")
    new_member = None
    if body.new_member_id:
        new_member = _get_member_or_404(db, body.new_member_id)
    shift_key = "day_member_id" if body.shift == "DAY" else "night_member_id"
    original_id = getattr(rec, shift_key)
    # 避免同日同人既白班又晚班
    other_key = "night_member_id" if body.shift == "DAY" else "day_member_id"
    other_id = getattr(rec, other_key)
    if new_member and other_id == new_member.id:
        raise HTTPException(status_code=400, detail="同一人不能在同一天同时排白班和晚班")
    setattr(rec, shift_key, new_member.id if new_member else None)

    # 重锚定轮换游标：仅当前/未来日期、且新员属于该班次轮换池时生效
    # - DAY 仅在非工作日重锚定（工作日白班由 PERMANENT_DAY 固定，不走轮换池）
    #   DAY 轮换池含 DAY + PERMANENT_DAY，故两类人员手动调非工作日白班均会重锚定
    # - NIGHT 任意日均重锚定（晚班在所有日期连续轮换）
    anchor_applied = False
    auto_reordered = 0  # 自动接排：顺延改动的后续排班条数
    reordered_shift = None  # 本次接排的班次（DAY/NIGHT），用于前端提示
    if new_member and rec.duty_date >= date.today():
        if body.shift == "DAY" and rec.is_holiday and new_member.duty_category in ("DAY", "PERMANENT_DAY"):
            day_members = _day_rotation_pool(db)
            idx = _member_index(day_members, new_member.id)
            if idx >= 0:
                day_cursor = _get_cursor(db, "DAY")
                day_cursor.last_index = idx
                anchor_applied = True
                reordered_shift = "DAY"
                # 自动接排：重生该日之后已存在的草稿非工作日白班，按新锚点顺序顺延
                later = (
                    db.query(DutyRecord)
                    .filter(
                        DutyRecord.duty_date > rec.duty_date,
                        DutyRecord.is_holiday.is_(True),
                        DutyRecord.status == "draft",
                    )
                    .order_by(DutyRecord.duty_date.asc())
                    .all()
                )
                if later:
                    leaves = _load_approved_leaves(db, rec.duty_date, later[-1].duty_date)
                    cur_idx = idx
                    for s in later:
                        day_skip = _leave_skip_ids(leaves, s.duty_date, "DAY")
                        m, cur_idx = _pick_next(day_members, cur_idx, day_skip)
                        if m is not None:
                            if s.day_member_id != m.id:
                                s.day_member_id = m.id
                                auto_reordered += 1
                    day_cursor.last_index = cur_idx
        elif body.shift == "NIGHT" and new_member.duty_category == "NIGHT":
            night_members = _active_members_by_category(db, "NIGHT")
            idx = _member_index(night_members, new_member.id)
            if idx >= 0:
                night_cursor = _get_cursor(db, "NIGHT")
                night_cursor.last_index = idx
                anchor_applied = True
                reordered_shift = "NIGHT"
                # 自动接排：重生该日之后已存在的草稿晚班，按新锚点顺序顺延
                # 晚班在所有日期连续轮换，故取该日之后全部草稿记录（不限非工作日）
                later = (
                    db.query(DutyRecord)
                    .filter(
                        DutyRecord.duty_date > rec.duty_date,
                        DutyRecord.status == "draft",
                    )
                    .order_by(DutyRecord.duty_date.asc())
                    .all()
                )
                if later:
                    leaves = _load_approved_leaves(db, rec.duty_date, later[-1].duty_date)
                    cur_idx = idx
                    for s in later:
                        night_skip = _leave_skip_ids(leaves, s.duty_date, "NIGHT")
                        # 避免与当日白班同人（与生成逻辑一致）
                        if s.day_member_id:
                            night_skip = set(night_skip)
                            night_skip.add(s.day_member_id)
                        m, cur_idx = _pick_next(night_members, cur_idx, night_skip)
                        if m is not None:
                            if s.night_member_id != m.id:
                                s.night_member_id = m.id
                                auto_reordered += 1
                    night_cursor.last_index = cur_idx

    # 记录调班日志
    log = DutyAdjustmentLog(
        duty_record_id=rec.id,
        shift=body.shift,
        original_member_id=original_id,
        new_member_id=new_member.id if new_member else None,
        reason=sanitize_text(body.reason)[:500],
        operator_id=user.id,
        operated_at=beijing_now(),
    )
    db.add(log)
    db.commit()
    db.refresh(rec)
    result = _enrich_record(db, rec)
    result["rotation_anchored"] = anchor_applied
    result["auto_reordered"] = auto_reordered
    result["reordered_shift"] = reordered_shift
    return result


@router.put("/schedule/{record_id}/status")
def update_record_status(
    record_id: int,
    body: RecordStatusUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "edit")),
):
    """变更单条值班记录状态（发布/过期）。"""
    rec = _get_record_or_404(db, record_id)
    rec.status = body.status
    db.commit()
    db.refresh(rec)
    return _enrich_record(db, rec)


@router.delete("/schedule/{record_id}", status_code=204)
def delete_record(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_schedule", "delete")),
):
    """删除单条值班记录（admin / duty:delete）。硬删除，同时清理关联调班日志。

    适用于修正错误排班/移除孤立记录；整段重排请使用「生成值班表」(overwrite)。
    """
    rec = _get_record_or_404(db, record_id)
    # 级联清理该记录的调班日志（外键无约束，显式删除避免孤儿）
    db.query(DutyAdjustmentLog).filter(DutyAdjustmentLog.duty_record_id == record_id).delete(synchronize_session=False)
    db.delete(rec)
    db.commit()
    logger.warning("值班记录已删除: id=%s, date=%s, operator=%s", record_id, rec.duty_date, user.username)
    return None


@router.get("/schedule/export")
def export_schedule(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "view")),
):
    """导出值班表为 Excel。"""
    recs = (
        db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= start_date, DutyRecord.duty_date <= end_date)
        .order_by(DutyRecord.duty_date.asc())
        .all()
    )
    status_cn = {"draft": "草稿", "published": "已发布", "expired": "已过期"}
    headers = ["日期", "星期", "日期类型", "白班人员", "白班电话", "晚班人员", "晚班电话", "状态"]
    rows = [headers]
    member_cache: dict[int, DutyMember] = {}
    for rec in recs:
        def _get(mid):
            if mid is None:
                return None
            if mid not in member_cache:
                member_cache[mid] = db.query(DutyMember).filter(DutyMember.id == mid).first()
            return member_cache[mid]
        dm = _get(rec.day_member_id)
        nm = _get(rec.night_member_id)
        rows.append([
            rec.duty_date.isoformat(),
            WEEKDAY_CN[rec.duty_date.weekday()],
            "非工作日" if rec.is_holiday else "工作日",
            dm.name if dm else "待分配",
            dm.phone if dm else "",
            nm.name if nm else "待分配",
            nm.phone if nm else "",
            status_cn.get(rec.status, rec.status),
        ])
    content = _to_xlsx_bytes(rows, "值班表")
    from urllib.parse import quote
    filename = quote(f"值班表_{start_date}_{end_date}.xlsx")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# ============ 请假管理 ============

@router.get("/leaves")
def list_leaves(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status: str = Query("", description="按审批状态筛选"),
    member_id: int = Query(0, description="按人员筛选"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_leave", "view")),
):
    """请假记录列表（分页，富化人员姓名）。"""
    q = db.query(DutyLeaveLog)
    if status in ("pending", "approved", "rejected"):
        q = q.filter(DutyLeaveLog.status == status)
    if member_id:
        q = q.filter(DutyLeaveLog.member_id == member_id)
    q = q.order_by(DutyLeaveLog.created_at.desc())
    page = max(1, page)
    size = max(1, min(size, 200))
    total = q.count()
    items = q.offset((page - 1) * size).limit(size).all()
    member_ids = list({it.member_id for it in items})
    member_map = {m.id: m for m in db.query(DutyMember).filter(DutyMember.id.in_(member_ids)).all()} if member_ids else {}
    return {
        "items": [
            {**it.to_dict(), "member_name": member_map[it.member_id].name if it.member_id in member_map else None}
            for it in items
        ],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size if total > 0 else 0,
    }


@router.post("/leaves", status_code=201)
def create_leave(
    body: LeaveCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_leave", "edit")),
):
    """提交请假申请。"""
    _get_member_or_404(db, body.member_id)
    if body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="请假结束日期不能早于开始日期")
    leave = DutyLeaveLog(
        member_id=body.member_id,
        start_date=body.start_date,
        end_date=body.end_date,
        shift=body.shift,
        reason=sanitize_text(body.reason)[:500],
        status="pending",
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave.to_dict()


@router.put("/leaves/{leave_id}/approve")
def approve_leave(
    leave_id: int,
    body: LeaveApprove,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_leave", "edit")),
):
    """审批请假申请（approved=批准，rejected=拒绝）。

    批准后该人员请假期间自动跳过排班；已生成的班次会标记为 needs_adjust
    （由 _enrich_record 动态计算，无需主动改 DutyRecord）。
    """
    leave = db.query(DutyLeaveLog).filter(DutyLeaveLog.id == leave_id).first()
    if leave is None:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail="该请假申请已审批，不可重复审批")
    leave.status = body.status
    leave.operator_id = user.id
    leave.approve_reason = sanitize_text(body.reason)[:500] if body.reason else None
    db.commit()
    db.refresh(leave)
    # 批准时检查是否影响已发布值班表，返回影响天数供前端提示
    affected_count = 0
    if body.status == "approved":
        affected_recs = (
            db.query(DutyRecord)
            .filter(
                DutyRecord.duty_date >= leave.start_date,
                DutyRecord.duty_date <= leave.end_date,
                DutyRecord.status == "published",
            )
            .all()
        )
        for r in affected_recs:
            if r.day_member_id == leave.member_id and leave.shift in ("DAY", "ALL"):
                affected_count += 1
            if r.night_member_id == leave.member_id and leave.shift in ("NIGHT", "ALL"):
                affected_count += 1
    result = leave.to_dict()
    result["affected_count"] = affected_count
    return result


@router.delete("/leaves/{leave_id}", status_code=204)
def delete_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_leave", "delete")),
):
    """删除请假记录（admin / 拥有 duty:delete 权限）。硬删除，不可恢复。

    仅删除请假记录本身，不回溯已受影响的值班表（如需调整，手动调班或重新生成）。
    """
    leave = db.query(DutyLeaveLog).filter(DutyLeaveLog.id == leave_id).first()
    if leave is None:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    db.delete(leave)
    db.commit()
    logger.warning("请假记录已删除: id=%s, member_id=%s, operator=%s", leave_id, leave.member_id, user.username)
    return None


@router.post("/leaves/batch-delete")
def batch_delete_leaves(
    body: BatchIds,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_leave", "delete")),
):
    """批量删除请假记录（admin / duty:delete）。单次上限 50 条，跳过不存在的 ID。"""
    ids = [i for i in (body.ids or [])][:50]
    if not ids:
        raise HTTPException(status_code=400, detail="未提供待删除 ID")
    deleted = db.query(DutyLeaveLog).filter(DutyLeaveLog.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    logger.warning("批量删除请假记录 %d 条, operator=%s, ids=%s", deleted, user.username, ids)
    return {"deleted": deleted, "not_found": len(ids) - deleted}


# ============ 调班记录 ============

@router.get("/adjustment-logs")
def list_adjustment_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    start_date: date = Query(None, description="按调整日期起（关联值班记录日期）"),
    end_date: date = Query(None, description="按调整日期止"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_log", "view")),
):
    """调班记录列表（分页，富化人员姓名/操作人/值班日期）。"""
    q = db.query(DutyAdjustmentLog).order_by(DutyAdjustmentLog.operated_at.desc())
    if start_date or end_date:
        sub = db.query(DutyRecord.id).filter()
        if start_date:
            sub = sub.filter(DutyRecord.duty_date >= start_date)
        if end_date:
            sub = sub.filter(DutyRecord.duty_date <= end_date)
        rec_ids = [r[0] for r in sub.all()]
        q = q.filter(DutyAdjustmentLog.duty_record_id.in_(rec_ids)) if rec_ids else q.filter(False)
    page = max(1, page)
    size = max(1, min(size, 200))
    total = q.count()
    items = q.offset((page - 1) * size).limit(size).all()
    # 批量富化
    rec_ids = list({it.duty_record_id for it in items})
    rec_map = {r.id: r for r in db.query(DutyRecord).filter(DutyRecord.id.in_(rec_ids)).all()} if rec_ids else {}
    m_ids = list({x for it in items for x in (it.original_member_id, it.new_member_id) if x})
    op_ids = list({it.operator_id for it in items})
    member_rows = db.query(DutyMember).filter(DutyMember.id.in_(m_ids)).all() if m_ids else []
    member_map = {m.id: m.name for m in member_rows}
    member_phone_map = {m.id: m.phone for m in member_rows}
    op_map = {u.id: u.username for u in db.query(User).filter(User.id.in_(op_ids)).all()} if op_ids else {}
    return {
        "items": [
            {
                **it.to_dict(),
                "duty_date": rec_map[it.duty_record_id].duty_date.isoformat() if it.duty_record_id in rec_map else None,
                "original_member_name": member_map.get(it.original_member_id),
                "original_member_phone": member_phone_map.get(it.original_member_id),
                "new_member_name": member_map.get(it.new_member_id),
                "new_member_phone": member_phone_map.get(it.new_member_id),
                "operator_name": op_map.get(it.operator_id),
            }
            for it in items
        ],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size if total > 0 else 0,
    }


@router.delete("/adjustment-logs/{log_id}", status_code=204)
def delete_adjustment_log(
    log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_log", "delete")),
):
    """删除调班记录（admin / duty:delete）。硬删除日志条目，不回退实际班次变更。

    如需回退班次到调整前的人员，请先使用「撤销调班」(revert) 再删除日志。
    """
    log = db.query(DutyAdjustmentLog).filter(DutyAdjustmentLog.id == log_id).first()
    if log is None:
        raise HTTPException(status_code=404, detail="调班记录不存在")
    db.delete(log)
    db.commit()
    logger.warning("调班记录已删除: id=%s, record_id=%s, operator=%s", log_id, log.duty_record_id, user.username)
    return None


@router.post("/adjustment-logs/batch-delete")
def batch_delete_adjustment_logs(
    body: BatchIds,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_log", "delete")),
):
    """批量删除调班记录（admin / duty:delete）。单次上限 50 条，跳过不存在的 ID。"""
    ids = [i for i in (body.ids or [])][:50]
    if not ids:
        raise HTTPException(status_code=400, detail="未提供待删除 ID")
    deleted = db.query(DutyAdjustmentLog).filter(DutyAdjustmentLog.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    logger.warning("批量删除调班记录 %d 条, operator=%s, ids=%s", deleted, user.username, ids)
    return {"deleted": deleted, "not_found": len(ids) - deleted}


# ============ 特殊日期覆盖 ============

@router.get("/special-dates")
def get_special_dates(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "view")),
):
    """获取特殊日期覆盖列表。"""
    overrides = _load_special_dates(db)
    items = [{"date": k, "day_type": v} for k, v in sorted(overrides.items())]
    return {"items": items, "total": len(items)}


@router.put("/special-dates")
def update_special_dates(
    body: SpecialDatesUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "edit")),
):
    """批量设置特殊日期覆盖（整体覆盖式）。"""
    overrides: dict[str, str] = {}
    for item in body.items:
        overrides[item.date.isoformat()] = item.day_type
    _save_special_dates(db, overrides)
    return {"total": len(overrides)}


@router.post("/special-dates")
def add_special_date(
    item: SpecialDatesUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "edit")),
):
    """单条新增特殊日期（合并入已有覆盖，不覆盖整体）。"""
    overrides = _load_special_dates(db)
    for it in item.items:
        overrides[it.date.isoformat()] = it.day_type
    _save_special_dates(db, overrides)
    return {"total": len(overrides)}


@router.delete("/special-dates/{d}")
def delete_special_date(
    d: date,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "edit")),
):
    """删除单条特殊日期覆盖。"""
    overrides = _load_special_dates(db)
    key = d.isoformat()
    if key in overrides:
        del overrides[key]
        _save_special_dates(db, overrides)
        _sync_records_is_holiday(db, {d})
    return {"deleted": True, "total": len(overrides)}


# ============ 统计面板 ============

@router.get("/schedule/stats")
def schedule_stats(
    start_date: date = Query(..., description="起始日期"),
    end_date: date = Query(..., description="结束日期"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_schedule", "view")),
):
    """值班表统计面板：总天数、白班/晚班已排人次、待分配人次、需调整人次、已发布/草稿数。

    - ``needs_adjust_count``：受已批准请假影响、需手动替换的班次数（含白班+晚班）。
    """
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于起始日期")
    recs = (
        db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= start_date, DutyRecord.duty_date <= end_date)
        .all()
    )
    approved_leaves = _load_approved_leaves(db, start_date, end_date)
    total = len(recs)
    day_assigned = sum(1 for r in recs if r.day_member_id)
    night_assigned = sum(1 for r in recs if r.night_member_id)
    day_pending = total - day_assigned
    night_pending = total - night_assigned
    needs_adjust = 0
    for r in recs:
        for lv in approved_leaves:
            if lv.member_id == r.day_member_id and lv.start_date <= r.duty_date <= lv.end_date and lv.shift in ("DAY", "ALL"):
                needs_adjust += 1
                break
        for lv in approved_leaves:
            if lv.member_id == r.night_member_id and lv.start_date <= r.duty_date <= lv.end_date and lv.shift in ("NIGHT", "ALL"):
                needs_adjust += 1
                break
    published = sum(1 for r in recs if r.status == "published")
    draft = sum(1 for r in recs if r.status == "draft")
    return {
        "total": total,
        "day_assigned": day_assigned,
        "night_assigned": night_assigned,
        "day_pending": day_pending,
        "night_pending": night_pending,
        "needs_adjust": needs_adjust,
        "published": published,
        "draft": draft,
    }


# ============ 撤销调班 ============

@router.post("/adjustment-logs/{log_id}/revert")
def revert_adjustment(
    log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_log", "edit")),
):
    """撤销某次调班：将该班次恢复为调班前的原值班人，并记录一条反向调班日志。

    - 不影响轮换游标。
    - 已过期记录不可撤销。
    - 仅可撤销「最近一次」针对该班次的调整（避免连锁回退歧义）。
    """
    log = db.query(DutyAdjustmentLog).filter(DutyAdjustmentLog.id == log_id).first()
    if log is None:
        raise HTTPException(status_code=404, detail="调班记录不存在")
    rec = db.query(DutyRecord).filter(DutyRecord.id == log.duty_record_id).first()
    if rec is None:
        raise HTTPException(status_code=404, detail="关联值班记录已删除，无法撤销")
    if rec.status == "expired":
        raise HTTPException(status_code=400, detail="已过期的值班记录不可撤销调班")
    shift_key = "day_member_id" if log.shift == "DAY" else "night_member_id"
    current_id = getattr(rec, shift_key)
    # 当前班次的人员应与该日志记录的 new_member_id 一致（或同为 None）才允许撤销
    if current_id != log.new_member_id:
        raise HTTPException(
            status_code=400,
            detail="该班次在此次调班后又被调整，无法直接撤销（请手动调整）",
        )
    # 恢复为原值班人
    setattr(rec, shift_key, log.original_member_id)
    # 记录反向调班日志
    revert_log = DutyAdjustmentLog(
        duty_record_id=rec.id,
        shift=log.shift,
        original_member_id=log.new_member_id,
        new_member_id=log.original_member_id,
        reason=f"撤销调班 #{log.id}",
        operator_id=user.id,
        operated_at=beijing_now(),
    )
    db.add(revert_log)
    db.commit()
    db.refresh(rec)
    return {
        "reverted": True,
        "log_id": log_id,
        "new_log_id": revert_log.id,
        "record": _enrich_record(db, rec),
    }


# ============ 复制值班表 ============

@router.post("/schedule/copy")
def copy_schedule(
    body: ScheduleCopyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_schedule", "edit")),
):
    """复制值班表：将源日期范围的排班按天平移到目标起始日期。

    - 按天平移：target_date = source_date + (target_start - source_start)。
    - 目标日期已有记录时跳过（不覆盖），保证不误删已排班次。
    - 新记录状态默认 draft，auto_publish=True 时为 published。
    - 不会推进轮换游标（仅复制人员分配）。
    """
    if body.source_end < body.source_start:
        raise HTTPException(status_code=400, detail="源结束日期不能早于源起始日期")
    delta = (body.target_start - body.source_start).days
    if delta == 0:
        raise HTTPException(status_code=400, detail="目标起始日期与源起始日期相同")
    source_recs = (
        db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= body.source_start, DutyRecord.duty_date <= body.source_end)
        .order_by(DutyRecord.duty_date.asc())
        .all()
    )
    if not source_recs:
        raise HTTPException(status_code=400, detail="源日期范围内无值班记录可复制")
    # 目标范围内已有记录的日期集合（用于跳过）
    target_dates = [r.duty_date + timedelta(days=delta) for r in source_recs]
    existing = {
        r.duty_date
        for r in db.query(DutyRecord)
        .filter(DutyRecord.duty_date.in_(target_dates))
        .all()
    }
    batch = uuid.uuid4().hex[:12]
    status = "published" if body.auto_publish else "draft"
    copied = 0
    skipped = 0
    new_recs = []
    for src in source_recs:
        td = src.duty_date + timedelta(days=delta)
        if td in existing:
            skipped += 1
            continue
        overrides = _load_special_dates(db)
        is_hol = is_holiday(td, overrides)
        nr = DutyRecord(
            duty_date=td,
            day_member_id=src.day_member_id,
            night_member_id=src.night_member_id,
            is_holiday=is_hol,
            status=status,
            generated_batch=f"copy-{batch}",
        )
        db.add(nr)
        new_recs.append(nr)
        copied += 1
    db.commit()
    for nr in new_recs:
        db.refresh(nr)
    logger.info("用户 %s 复制值班表：源 %s~%s → 目标起始 %s，复制 %d 条，跳过 %d 条",
                user.username, body.source_start, body.source_end, body.target_start, copied, skipped)
    return {
        "copied": copied,
        "skipped": skipped,
        "batch": f"copy-{batch}",
        "target_start": body.target_start.isoformat(),
        "items": [_enrich_record(db, nr) for nr in new_recs],
    }


# ============ 轮班公平性统计 ============

@router.get("/members/stats")
def member_stats(
    start_date: date = Query(None, description="起始日期（默认近 90 天）"),
    end_date: date = Query(None, description="结束日期（默认今天）"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("duty_member", "view")),
):
    """轮班公平性统计：按人员统计白班/晚班次数，计算最大/最小/平均与偏离度。

    返回每人的 day_count / night_count / total，以及 fairness 摘要。
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=90)
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于起始日期")
    members = (
        db.query(DutyMember)
        .filter(DutyMember.deleted_at.is_(None))
        .order_by(DutyMember.duty_category.asc(), DutyMember.sort_order.asc(), DutyMember.id.asc())
        .all()
    )
    recs = (
        db.query(DutyRecord)
        .filter(DutyRecord.duty_date >= start_date, DutyRecord.duty_date <= end_date)
        .all()
    )
    day_map: dict[int, int] = {}
    night_map: dict[int, int] = {}
    for r in recs:
        if r.day_member_id:
            day_map[r.day_member_id] = day_map.get(r.day_member_id, 0) + 1
        if r.night_member_id:
            night_map[r.night_member_id] = night_map.get(r.night_member_id, 0) + 1
    items = []
    for m in members:
        dc = day_map.get(m.id, 0)
        nc = night_map.get(m.id, 0)
        items.append({
            "id": m.id,
            "name": m.name,
            "group_name": m.group_name,
            "duty_category": m.duty_category,
            "status": m.status,
            "day_count": dc,
            "night_count": nc,
            "total": dc + nc,
        })
    # 按类别分组计算公平性（同类别内才可比）
    by_cat: dict[str, list[int]] = {}
    for it in items:
        by_cat.setdefault(it["duty_category"], []).append(it["total"])
    fairness = {}
    for cat, totals in by_cat.items():
        active_totals = [t for t in totals if t > 0]
        if not active_totals:
            fairness[cat] = {"max": 0, "min": 0, "avg": 0, "gap": 0}
            continue
        mx = max(active_totals)
        mn = min(active_totals)
        avg = round(sum(active_totals) / len(active_totals), 1)
        fairness[cat] = {"max": mx, "min": mn, "avg": avg, "gap": mx - mn}
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "items": items,
        "fairness": fairness,
    }


# ============ 批量启用/停用 ============

@router.post("/members/batch-update-status")
def batch_update_member_status(
    body: MemberBatchStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_member", "edit")),
):
    """批量启用/停用值班人员。停用后该人员不再参与后续轮换（已有排班保留）。"""
    ids = list(dict.fromkeys(body.ids))  # 去重保序
    members = (
        db.query(DutyMember)
        .filter(DutyMember.id.in_(ids), DutyMember.deleted_at.is_(None))
        .all()
    )
    updated = []
    for m in members:
        if m.status != body.status:
            m.status = body.status
            updated.append(m.id)
    db.commit()
    logger.info("用户 %s 批量%s %d 名值班人员", user.username,
                "启用" if body.status == "active" else "停用", len(updated))
    return {
        "updated": len(updated),
        "updated_ids": updated,
        "skipped": len(ids) - len(members),
    }


@router.post("/members/reorder")
def reorder_members(
    body: MemberReorderRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("duty_member", "edit")),
):
    """批量重排值班人员顺序：按传入的 ordered_ids 顺序依次赋予 sort_order=1,2,3...

    用于前端拖拽排序后持久化。轮换顺序由 sort_order（升序）决定，重排后立即
    影响后续值班表生成。未传入的人员保持原 sort_order 不变。
    """
    ordered_ids = list(dict.fromkeys(body.ordered_ids))  # 去重保序
    members = (
        db.query(DutyMember)
        .filter(DutyMember.id.in_(ordered_ids), DutyMember.deleted_at.is_(None))
        .all()
    )
    by_id = {m.id: m for m in members}
    updated = 0
    for new_order, mid in enumerate(ordered_ids, start=1):
        m = by_id.get(mid)
        if m is not None and m.sort_order != new_order:
            m.sort_order = new_order
            updated += 1
    db.commit()
    logger.info("用户 %s 重排 %d 名值班人员顺序（更新 %d 项）", user.username, len(ordered_ids), updated)
    return {"updated": updated, "total": len(ordered_ids)}


# ============ 值班监控大屏 ============

@router.get("/dashboard")
def duty_dashboard(db: Session = Depends(get_db), _user = Depends(require_permission("duty_dashboard", "view"))):
    """值班监控大屏聚合数据：当前班次/主备、今日记录、近7天排班、异常提醒、本月轮换统计。

    服务端按北京时间判断当前班次：09:00~18:00 为白班，其余为晚班。
    所有日期/人员信息均富化，前端可直接渲染。
    """
    now = beijing_now()
    today = now.date()
    current_shift = "DAY" if time(9, 0) <= now.time() < time(18, 0) else "NIGHT"
    weekday_cn = WEEKDAY_CN[today.weekday()]

    # 今日记录
    today_rec = db.query(DutyRecord).filter(DutyRecord.duty_date == today).first()
    today_info = _enrich_record(db, today_rec) if today_rec else None

    # 当前班次值班人 + 备份
    cur_member_id = None
    if today_rec:
        cur_member_id = today_rec.day_member_id if current_shift == "DAY" else today_rec.night_member_id
    current_member = _member_brief(db.query(DutyMember).filter(DutyMember.id == cur_member_id).first()) if cur_member_id else None
    if current_member and current_member.get("duty_category") == "PERMANENT_DAY":
        # 长期白班主备：取另一名启用的长期白班人员作为备份
        backup_row = (
            db.query(DutyMember)
            .filter(
                DutyMember.id != cur_member_id,
                DutyMember.duty_category == "PERMANENT_DAY",
                DutyMember.status == "active",
                DutyMember.deleted_at.is_(None),
            )
            .order_by(DutyMember.is_primary.desc(), DutyMember.sort_order.asc(), DutyMember.id.asc())
            .first()
        )
        backup_member = _member_brief(backup_row)
    else:
        backup_member = None
    if current_member:
        current_member["is_primary"] = bool(db.query(DutyMember).get(cur_member_id).is_primary)

    # 近 7 天排班（含今天）
    end7 = today + timedelta(days=6)
    recs7 = {r.duty_date: r for r in db.query(DutyRecord).filter(DutyRecord.duty_date >= today, DutyRecord.duty_date <= end7).all()}
    leaves7 = _load_approved_leaves(db, today, end7)
    upcoming_7days = []
    pending_anomalies = []
    for i in range(7):
        d = today + timedelta(days=i)
        rec = recs7.get(d)
        if rec:
            info = _enrich_record(db, rec, approved_leaves=leaves7)
        else:
            info = {
                "duty_date": d.isoformat(),
                "weekday": WEEKDAY_CN[d.weekday()],
                "day_type": "非工作日" if is_holiday(d) else "工作日",
                "holiday_name": get_holiday_name(d) if is_holiday(d) else None,
                "is_today": d == today,
                "is_holiday": is_holiday(d),
                "day_member": None,
                "night_member": None,
                "day_needs_adjust": False,
                "night_needs_adjust": False,
                "status": None,
            }
        # 待分配异常
        if rec is None or not rec.day_member_id:
            pending_anomalies.append({"date": d.isoformat(), "weekday": WEEKDAY_CN[d.weekday()], "shift": "白班", "is_holiday": is_holiday(d)})
        if rec is None or not rec.night_member_id:
            pending_anomalies.append({"date": d.isoformat(), "weekday": WEEKDAY_CN[d.weekday()], "shift": "晚班", "is_holiday": is_holiday(d)})
        upcoming_7days.append(info)

    # 请假影响（覆盖近7天）
    leave_anomalies = []
    for lv in leaves7:
        m = db.query(DutyMember).filter(DutyMember.id == lv.member_id).first()
        leave_anomalies.append({
            "member_name": m.name if m else "未知",
            "start_date": lv.start_date.isoformat(),
            "end_date": lv.end_date.isoformat(),
            "shift": lv.shift,
            "reason": lv.reason,
        })

    # 近期调班记录（近7天 operated_at）
    since = now - timedelta(days=7)
    recent_logs = (
        db.query(DutyAdjustmentLog)
        .filter(DutyAdjustmentLog.operated_at >= since)
        .order_by(DutyAdjustmentLog.operated_at.desc())
        .limit(10)
        .all()
    )
    log_rec_ids = list({x.duty_record_id for x in recent_logs})
    log_rec_map = {r.id: r for r in db.query(DutyRecord).filter(DutyRecord.id.in_(log_rec_ids)).all()} if log_rec_ids else {}
    log_m_ids = list({x for x in recent_logs for x in (x.original_member_id, x.new_member_id) if x})
    log_m_map = {m.id: m.name for m in db.query(DutyMember).filter(DutyMember.id.in_(log_m_ids)).all()} if log_m_ids else {}
    adjustment_anomalies = []
    for lg in recent_logs:
        rec = log_rec_map.get(lg.duty_record_id)
        adjustment_anomalies.append({
            "duty_date": rec.duty_date.isoformat() if rec else None,
            "original_member_name": log_m_map.get(lg.original_member_id),
            "new_member_name": log_m_map.get(lg.new_member_id),
            "shift": lg.shift,
            "operated_at": lg.operated_at.isoformat() if lg.operated_at else None,
        })

    # 即将交班
    if current_shift == "DAY":
        handover_time = "18:00"
        next_shift = "NIGHT"
        next_member_id = today_rec.night_member_id if today_rec else None
    else:
        handover_time = "明日 09:00"
        next_shift = "DAY"
        tom = db.query(DutyRecord).filter(DutyRecord.duty_date == today + timedelta(days=1)).first()
        next_member_id = tom.day_member_id if tom else None
    next_member_row = db.query(DutyMember).filter(DutyMember.id == next_member_id).first() if next_member_id else None
    upcoming_handover = {
        "next_shift": next_shift,
        "time": handover_time,
        "member": _member_brief(next_member_row),
    }

    # 本月轮换统计（按人员，分类别）
    month_start = today.replace(day=1)
    if today.month == 12:
        month_end = today.replace(day=31)
    else:
        month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    month_recs = db.query(DutyRecord).filter(DutyRecord.duty_date >= month_start, DutyRecord.duty_date <= month_end).all()
    day_map: dict = {}
    night_map: dict = {}
    for r in month_recs:
        if r.day_member_id:
            day_map[r.day_member_id] = day_map.get(r.day_member_id, 0) + 1
        if r.night_member_id:
            night_map[r.night_member_id] = night_map.get(r.night_member_id, 0) + 1
    members_all = (
        db.query(DutyMember)
        .filter(DutyMember.deleted_at.is_(None), DutyMember.status == "active")
        .order_by(DutyMember.duty_category.asc(), DutyMember.sort_order.asc(), DutyMember.id.asc())
        .all()
    )
    rotation_stats = []
    for m in members_all:
        dc = day_map.get(m.id, 0)
        nc = night_map.get(m.id, 0)
        rotation_stats.append({
            "id": m.id,
            "name": m.name,
            "duty_category": m.duty_category,
            "day_count": dc,
            "night_count": nc,
            "total": dc + nc,
        })

    needs_adjust_count = sum(1 for r in upcoming_7days if r.get("day_needs_adjust") or r.get("night_needs_adjust"))
    has_anomaly = bool(pending_anomalies) or needs_adjust_count > 0

    return {
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "today": today.isoformat(),
        "weekday": weekday_cn,
        "current_shift": current_shift,
        "current_member": current_member,
        "backup_member": backup_member,
        "today_record": today_info,
        "upcoming_7days": upcoming_7days,
        "anomalies": {
            "pending": pending_anomalies,
            "leaves": leave_anomalies,
            "adjustments": adjustment_anomalies,
            "upcoming_handover": upcoming_handover,
            "needs_adjust_count": needs_adjust_count,
        },
        "rotation_stats": rotation_stats,
        "month_range": {"start": month_start.isoformat(), "end": month_end.isoformat()},
        "has_anomaly": has_anomaly,
    }
