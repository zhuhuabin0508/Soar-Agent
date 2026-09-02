"""通用序列化辅助。

提供 ``to_dict`` / ``to_dict_list``，将 SQLAlchemy 模型实例序列化为纯字典，
并把 ``datetime`` 转为带 ``+08:00`` 偏移的 ISO 字符串，便于 API 直接返回 JSON。

时间序列化统一走 :func:`app.core.timezone.to_beijing_iso`：DB 列内为北京时间
naive datetime，序列化时附 ``+08:00`` 偏移，前端 ``new Date()`` 跨时区正确解析。
"""
from typing import Any

from app.core.timezone import to_beijing_iso


def to_dict(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    """将 SQLAlchemy 模型实例序列化为字典。

    遍历 ``__table__.columns``，把 datetime 字段转为带 ``+08:00`` 偏移的 ISO 字符串，
    其余类型原样返回。``None`` 输入返回空字典。

    Args:
        obj: ORM 模型实例。
        exclude: 需要排除的字段名集合。

    Returns:
        可直接 JSON 序列化的字典。
    """
    if obj is None:
        return {}
    excluded = exclude or set()
    result: dict[str, Any] = {}
    for column in obj.__table__.columns:
        if column.name in excluded:
            continue
        value = getattr(obj, column.name)
        result[column.name] = _serialize_value(value)
    return result


def _serialize_value(value: Any) -> Any:
    """序列化单个值：datetime 转 +08:00 ISO 字符串，其余原样返回。"""
    if value is None:
        return None
    if hasattr(value, "isoformat"):  # datetime / date / time
        return to_beijing_iso(value)
    return value


def to_dict_list(objs: list[Any], exclude: set[str] | None = None) -> list[dict[str, Any]]:
    """批量序列化模型列表为字典列表。"""
    return [to_dict(obj, exclude) for obj in objs]


def paginate(
    query,
    page: int = 1,
    size: int = 20,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    """通用分页查询工具函数。

    对 SQLAlchemy Query 对象做分页，返回标准分页结构。

    Args:
        query: SQLAlchemy Query 对象（已含 filter/order_by，未含 offset/limit）。
        page: 页码（从 1 开始）。
        size: 每页条数。
        exclude: 序列化时排除的字段。

    Returns:
        ``{"items": [...], "total": int, "page": int, "size": int, "pages": int}``
    """
    page = max(1, page)
    size = max(1, min(size, 200))  # 防止超大 size 拖垮数据库
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return {
        "items": to_dict_list(items, exclude),
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size if total > 0 else 0,
    }
