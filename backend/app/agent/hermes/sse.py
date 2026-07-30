"""SSE 事件序列化与流式生成器。

提供 ``SSEEvent`` 的 ``to_sse()`` 序列化方法和 ``sse_stream`` 异步生成器，
供 FastAPI ``StreamingResponse`` 使用。
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)


@dataclass
class SSEEventDict:
    """SSE 事件数据类（与 types.SSEEvent 同构，额外提供 to_sse 方法）。

    type 取值（现有契约的超集，前端兼容）：
    - start: 会话开始
    - status: 状态更新
    - thinking: LLM 思考过程（<think> 块内容，供前端折叠展示）
    - token: LLM 流式 token
    - tool_start: 工具开始执行
    - tool_end: 工具执行结束
    - skill_interrupt: 技能被中断
    - delegate: 子代理事件
    - log: 日志
    - done: 会话结束
    - error: 错误
    """

    type: str
    content: str = ""
    message: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    args: Any = None
    result: Any = None
    log: Optional[dict] = None
    skill: Optional[dict] = None

    def to_sse(self) -> str:
        """序列化为 SSE 格式字符串。"""
        data = {k: v for k, v in asdict(self).items() if v not in ("", None, [], {})}
        return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def sse_stream(executor, user_input: str, session_id: str = "") -> AsyncIterator[str]:
    """FastAPI StreamingResponse 用的异步生成器。

    Args:
        executor: HermesAgentExecutor 实例
        user_input: 用户输入
        session_id: 会话 ID

    Yields:
        SSE 格式字符串
    """
    try:
        async for event in executor.run(user_input, session_id=session_id):
            yield event.to_sse()
    except Exception as exc:  # noqa: BLE001
        logger.exception("SSE 流异常: %s", exc)
        error_event = SSEEventDict(type="error", message=str(exc))
        yield error_event.to_sse()


def make_event(type: str, **kwargs) -> SSEEventDict:
    """快捷构造 SSE 事件。"""
    return SSEEventDict(type=type, **kwargs)
