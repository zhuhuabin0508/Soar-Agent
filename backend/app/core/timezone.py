"""统一时区工具。

全系统时间处理的一致约定：
- 数据库 ``TIMESTAMP WITHOUT TIME ZONE`` 列统一存「北京时间 naive datetime」
  （即真实北京时间，但不携带 tzinfo）。这样无论容器/数据库时区如何，
  列值本身就是正确的北京时间字面量。
- 所有写入 DB 的时间一律通过 :func:`beijing_now` 生成，确保 naive 北京时间。
- 序列化给前端时一律通过 :func:`to_beijing_iso`，输出带 ``+08:00`` 偏移的
  ISO 字符串（如 ``2026-08-03 10:39:46+08:00``）。前端 ``new Date(...)`` 在
  任意时区浏览器中都能正确解析为北京时间并按本地时区显示，杜绝 8 小时偏差。

中国自 1991 年起不实行夏令时，故采用固定 ``UTC+8`` 偏移即可，无需 tzdata。
"""
from datetime import datetime, timedelta, timezone

# 北京时区：固定 UTC+8 偏移（中国无夏令时，零依赖、永远正确）
BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> datetime:
    """返回当前北京时间（naive datetime，不带 tzinfo）。

    供所有 ORM 列默认值与代码赋值使用，保证 DB 列内为北京时间字面量。
    显式基于 ``UTC+8`` 构造，不依赖容器/系统时区。

    Returns:
        naive datetime，值为当前北京时间。
    """
    return datetime.now(BEIJING_TZ).replace(tzinfo=None)


def to_beijing_iso(dt) -> str | None:
    """将 datetime 序列化为带 ``+08:00`` 偏移的 ISO 字符串。

    - naive datetime：视为北京时间字面量，直接附 ``+08:00``。
    - aware datetime：转换到北京时间后输出。
    - ``None`` 或非 datetime：原样返回。

    供 :func:`app.schemas.common.to_dict` 及 CSV 导出等所有面向前端的
    序列化路径使用，确保前端 ``new Date()`` 跨时区正确解析。
    """
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        # naive：按北京时间字面量解释
        dt = dt.replace(tzinfo=BEIJING_TZ)
    else:
        dt = dt.astimezone(BEIJING_TZ)
    return dt.isoformat()


def beijing_now_iso() -> str:
    """当前北京时间的带偏移 ISO 字符串（便捷方法，用于 JSON 内嵌时间戳）。"""
    return to_beijing_iso(beijing_now())
