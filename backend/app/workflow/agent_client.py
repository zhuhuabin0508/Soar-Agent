"""IP 风险研判智能体调用封装。

契约：``POST {AGENT_BASE_URL}/agent/ip-risk-analyze``
请求体 ``{"ip": "...", "alert_context": {...}}``；
响应体为智能体输出的结构化 JSON，必含字段：
``is_banned / risk_level / action / need_confirm / ban_plan / monitoring_advice / reasons``。

要求：
- 超时 60 秒，失败重试 2 次（共 3 次尝试）
- 每次调用全链路记录到 agent_invocation_logs（请求/响应/模型/token/耗时/状态）
- 响应缺少必填字段按解析失败处理，不猜测填充
"""
import json
import logging
import os
import time
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

from app.models.workflow_ban import AgentInvocationLog

logger = logging.getLogger(__name__)

# mock 智能体服务地址（默认指向本进程内置 mock；可用环境变量切换真实服务）
AGENT_BASE_URL = os.environ.get("BAN_AGENT_BASE_URL", "http://127.0.0.1:8000/api/v1/internal")
AGENT_TIMEOUT_SECONDS = 60
AGENT_MAX_ATTEMPTS = 3  # 1 次原始调用 + 2 次重试

# 智能体输出必填字段（缺失按解析失败处理，不猜测填充）
REQUIRED_FIELDS = ("is_banned", "risk_level", "action", "need_confirm", "ban_plan", "monitoring_advice", "reasons")


class AgentCallError(Exception):
    """智能体调用失败（网络/超时/HTTP 错误/JSON 结构不完整）。"""


def analyze_ip_risk(
    db: Session,
    ip: str,
    alert_context: dict[str, Any],
    *,
    instance_id: Optional[int] = None,
    node_key: str = "agent_analyze",
) -> dict[str, Any]:
    """调用 IP 风险研判智能体并记录全链路日志。

    Args:
        db: 数据库会话（写 agent_invocation_logs）。
        ip: 待研判 IP。
        alert_context: 告警上下文摘要（alert_name/risk_level/threat_class/occur_timestamp/src_country）。
        instance_id: 工作流实例 ID（日志关联）。
        node_key: 调用节点标识。

    Returns:
        智能体输出的完整 JSON（已校验必填字段）。

    Raises:
        AgentCallError: 重试耗尽仍失败，或响应 JSON 缺少必填字段。
    """
    request_body = {"ip": ip, "alert_context": alert_context}
    last_error = ""
    response_body: Optional[dict] = None
    model_name = ""
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    status = "fail"

    started = time.perf_counter()
    for attempt in range(1, AGENT_MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(
                f"{AGENT_BASE_URL}/agent/ip-risk-analyze",
                json=request_body,
                timeout=AGENT_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            body = resp.json()
            # 结构完整性校验：必填字段缺失按解析失败处理
            missing = [f for f in REQUIRED_FIELDS if f not in body]
            if missing:
                raise AgentCallError(f"响应缺少必填字段: {', '.join(missing)}")
            response_body = body
            # mock/真实服务约定的元数据字段（无则不记录）
            meta = body.get("_meta") or {}
            model_name = str(meta.get("model") or "")
            input_tokens = meta.get("input_tokens")
            output_tokens = meta.get("output_tokens")
            status = "success"
            last_error = ""
            break
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)[:500]
            logger.warning(
                "智能体研判失败(第 %d/%d 次) ip=%s: %s",
                attempt, AGENT_MAX_ATTEMPTS, ip, last_error,
            )
            if attempt < AGENT_MAX_ATTEMPTS:
                time.sleep(min(2 ** attempt, 5))  # 退避重试

    duration_ms = int((time.perf_counter() - started) * 1000)

    # 全链路日志（成功与失败均记录）
    try:
        db.add(AgentInvocationLog(
            workflow_instance_id=instance_id,
            node_key=node_key,
            request_body=json.dumps(request_body, ensure_ascii=False),
            response_body=json.dumps(response_body, ensure_ascii=False) if response_body is not None else None,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            status=status,
            error_msg=last_error or None,
        ))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("智能体调用日志写入失败（不影响流程）")

    if status != "success":
        raise AgentCallError(f"智能体研判失败（已重试 {AGENT_MAX_ATTEMPTS} 次）: {last_error}")
    return response_body
