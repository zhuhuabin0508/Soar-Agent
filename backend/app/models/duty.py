"""值班管理模型。

包含 5 张表：
- ``DutyMember``：值班人员（含姓名/电话/组别/值班类别/排序/状态，软删除）
- ``DutyRecord``：值班记录（按日生成，含白班/晚班人员ID、日期类型、状态）
- ``DutyRotationCursor``：轮换游标（NIGHT / DAY 类别的上次轮换位置）
- ``DutyAdjustmentLog``：调班日志（手动替换记录）
- ``DutyLeaveLog``：请假记录（关联人员/日期范围/班次/审批状态）
"""
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Text, func

from app.core.timezone import to_beijing_iso
from app.database import Base


class DutyMember(Base):
    """值班人员。

    - ``duty_category``：值班类别，决定排班行为：
      - ``PERMANENT_DAY``：长期白班，工作日白班固定值守，不参与轮换
      - ``DAY``：白班，仅节假日白班轮换
      - ``NIGHT``：晚班，所有日期晚班轮换
    - ``is_primary``：是否主值班人（仅 PERMANENT_DAY 有效，主值班人默认排班）
    - ``sort_order``：排序权重，轮换顺序依据（值小的优先）
    - ``status``：启用/停用
    - ``deleted_at``：软删除时间
    """

    __tablename__ = "duty_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(50), nullable=False)
    group_name = Column(String(100), nullable=False, default="")
    duty_category = Column(String(20), nullable=False, index=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="active")  # active / inactive
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True)  # 软删除

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result

    def __repr__(self) -> str:
        return f"<DutyMember id={self.id} name={self.name!r} category={self.duty_category!r}>"


class DutyRecord(Base):
    """值班记录：按日生成，每天一条，含白班和晚班两个排班位。

    - ``duty_date``：值班日期
    - ``day_member_id`` / ``night_member_id``：白班/晚班人员ID（关联 duty_members）
    - ``is_holiday``：是否非工作日（周末/法定节假日）
    - ``status``：草稿 draft / 已发布 published / 已过期 expired
    - ``generated_batch``：生成批次号（同一次自动生成的记录共用）
    """

    __tablename__ = "duty_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    duty_date = Column(Date, nullable=False, index=True)
    day_member_id = Column(Integer, nullable=True, index=True)
    night_member_id = Column(Integer, nullable=True, index=True)
    is_holiday = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="draft", index=True)
    generated_batch = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result

    def __repr__(self) -> str:
        return f"<DutyRecord id={self.id} date={self.duty_date} status={self.status!r}>"


class DutyRotationCursor(Base):
    """轮换游标：记录 NIGHT / DAY 类别上次轮换到的位置索引。

    每次自动生成值班表时从游标的下一个位置开始轮换，
    生成完成后更新游标，保证轮换连续性。
    """

    __tablename__ = "duty_rotation_cursors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(20), nullable=False, unique=True)  # NIGHT / DAY
    last_index = Column(Integer, nullable=False, default=-1)  # 上次轮换到的位置（-1 表示尚未轮换）
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result


class DutyAdjustmentLog(Base):
    """调班日志：记录所有手动替换值班人员的操作。"""

    __tablename__ = "duty_adjustment_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    duty_record_id = Column(Integer, nullable=False, index=True)
    shift = Column(String(10), nullable=False)  # DAY / NIGHT
    original_member_id = Column(Integer, nullable=True)
    new_member_id = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)
    operator_id = Column(Integer, nullable=False)
    operated_at = Column(DateTime, server_default=func.now())

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result


class DutyLeaveLog(Base):
    """请假记录：人员提交请假申请，关联值班表调整。"""

    __tablename__ = "duty_leave_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(Integer, nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    shift = Column(String(10), nullable=False, default="ALL")  # DAY / NIGHT / ALL
    reason = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending / approved / rejected
    operator_id = Column(Integer, nullable=True)
    approve_reason = Column(Text, nullable=True)  # 审批意见（approve/reject 时填写）
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            result[column.name] = to_beijing_iso(value) if hasattr(value, "isoformat") else value
        return result
