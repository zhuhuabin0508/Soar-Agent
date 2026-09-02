"""Pydantic 日期时间序列化类型。

定义 :data:`BeijingDatetime` 注解类型，使所有 Pydantic 响应模型中的 datetime
字段在序列化为 JSON 时统一输出带 ``+08:00`` 偏移的 ISO 字符串，前端
``new Date()`` 跨时区正确解析，杜绝 8 小时偏差。

用法：将响应模型中的 ``Optional[datetime]`` 替换为 ``Optional[BeijingDatetime]``。
"""
from datetime import datetime
from typing import Annotated, Optional

from pydantic import PlainSerializer

from app.core.timezone import to_beijing_iso


def _serialize_beijing(dt: Optional[datetime]) -> Optional[str]:
    """PlainSerializer 回调：datetime → +08:00 ISO 字符串，None 透传。"""
    return to_beijing_iso(dt)


# 带 +08:00 序列化器的 datetime 注解类型
# PlainSerializer 在值非 None 时触发，None 由 Pydantic 正常输出为 null
BeijingDatetime = Annotated[datetime, PlainSerializer(_serialize_beijing, return_type=str)]
