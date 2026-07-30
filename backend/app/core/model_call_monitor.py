"""模型调用监控：记录每次 LLM 调用的指标到 ``model_call_logs`` 表。

供「模型设置」页的监控功能展示每个模型的调用次数、成功率、平均耗时、
Token 用量及最近调用明细。

设计要点：
- 所有写入都吞掉异常（监控日志不应影响主业务流程）。
- 在独立数据库会话中写入（避免污染调用方的会话/事务）。
- 提供 ``record_model_call`` 同步函数与 ``record_model_call_async`` 异步包装。
"""
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _extract_usage(response: Any) -> tuple[Optional[int], Optional[int]]:
    """从 LangChain AIMessage 响应中提取 token 用量。

    不同供应商返回的 usage 结构略有差异，此处做容错提取。

    Returns:
        ``(input_tokens, output_tokens)``，无法提取时对应字段为 None。
    """
    if response is None:
        return None, None

    # LangChain AIMessage 的 usage_metadata 字段（统一格式）
    usage_meta = getattr(response, "usage_metadata", None)
    if isinstance(usage_meta, dict):
        input_t = usage_meta.get("input_tokens") or usage_meta.get("prompt_tokens")
        output_t = usage_meta.get("output_tokens") or usage_meta.get("completion_tokens")
        if input_t is not None or output_t is not None:
            return input_t, output_t

    # 原生 response_metadata 里的 token_usage / usage
    resp_meta = getattr(response, "response_metadata", None)
    if isinstance(resp_meta, dict):
        # OpenAI 格式
        token_usage = resp_meta.get("token_usage") or resp_meta.get("usage")
        if isinstance(token_usage, dict):
            input_t = token_usage.get("prompt_tokens") or token_usage.get("input_tokens")
            output_t = token_usage.get("completion_tokens") or token_usage.get("output_tokens")
            if input_t is not None or output_t is not None:
                return input_t, output_t

    return None, None


def record_model_call(
    *,
    model_config_id: Optional[int],
    model_name: str,
    provider: str,
    status: str,
    latency_ms: Optional[int] = None,
    response: Any = None,
    error_message: str = "",
    trigger_type: str = "",
    agent_id: Optional[int] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
) -> None:
    """记录一次模型调用到 ``model_call_logs`` 表（吞掉所有异常）。

    Args:
        model_config_id: 关联的 LLMConfig.id。
        model_name: 模型名（如 claude-3-5-sonnet-20241022）。
        provider: 供应商（anthropic / openai / ...）。
        status: ``success`` 或 ``failed``。
        latency_ms: 调用耗时（毫秒）。
        response: LangChain 响应对象（成功时用于提取 token 用量）。
        error_message: 失败时的错误信息。
        trigger_type: 触发来源（agent_test / workflow / manual_test 等）。
        agent_id: 关联的智能体 ID。
        input_tokens: 直接传入的输入 token 数（优先于 response 提取；
            适用于 httpx 直接调用 OpenAI 兼容接口的场景）。
        output_tokens: 直接传入的输出 token 数。
    """
    try:
        from app.database import SessionLocal
        from app.models.model_call_log import ModelCallLog

        # token 用量：优先用调用方直接传入的；均为 None 时从 response 提取
        if input_tokens is None and output_tokens is None:
            if status == "success" and response is not None:
                input_tokens, output_tokens = _extract_usage(response)
            else:
                input_tokens, output_tokens = (None, None)

        total_tokens = None
        if input_tokens is not None or output_tokens is not None:
            total_tokens = (input_tokens or 0) + (output_tokens or 0)

        # 截断错误信息，避免超长文本
        if error_message and len(error_message) > 2000:
            error_message = error_message[:2000]

        db = SessionLocal()
        try:
            log = ModelCallLog(
                model_config_id=model_config_id,
                model_name=model_name or "",
                provider=provider or "",
                status=status,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                error_message=error_message or None,
                trigger_type=trigger_type or "",
                agent_id=agent_id,
            )
            db.add(log)
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("记录模型调用日志失败（不影响业务）: %s", exc)


class ModelCallTimer:
    """上下文管理器：计时并在退出时记录模型调用。

    用法::

        with ModelCallTimer(model_config_id=1, model_name="gpt-4o", provider="openai",
                             trigger_type="agent_test", agent_id=5) as timer:
            response = await llm.ainvoke(messages)
            timer.set_response(response)  # 成功时设置响应以提取 token
        # 退出时自动记录 success；with 块内抛异常则记录 failed
    """

    def __init__(
        self,
        *,
        model_config_id: Optional[int] = None,
        model_name: str = "",
        provider: str = "",
        trigger_type: str = "",
        agent_id: Optional[int] = None,
    ):
        self.model_config_id = model_config_id
        self.model_name = model_name
        self.provider = provider
        self.trigger_type = trigger_type
        self.agent_id = agent_id
        self._response: Any = None
        self._start: Optional[float] = None

    def set_response(self, response: Any) -> None:
        """设置成功响应（用于提取 token 用量）。"""
        self._response = response

    def __enter__(self) -> "ModelCallTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        latency_ms = None
        if self._start is not None:
            latency_ms = int((time.monotonic() - self._start) * 1000)

        if exc_type is not None:
            # 异常 → 记录失败
            record_model_call(
                model_config_id=self.model_config_id,
                model_name=self.model_name,
                provider=self.provider,
                status="failed",
                latency_ms=latency_ms,
                error_message=str(exc_val) if exc_val else "",
                trigger_type=self.trigger_type,
                agent_id=self.agent_id,
            )
        else:
            # 成功
            record_model_call(
                model_config_id=self.model_config_id,
                model_name=self.model_name,
                provider=self.provider,
                status="success",
                latency_ms=latency_ms,
                response=self._response,
                trigger_type=self.trigger_type,
                agent_id=self.agent_id,
            )
        # 不吞异常
        return False
