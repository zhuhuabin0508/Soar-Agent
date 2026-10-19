"""平台层第二入口：invoke_tool（统一工具执行）。

架构 §7.1 双入口：
    invoke_agent → Hermes → tool_engine → 治理链 → Provider → L1
    invoke_tool  → ToolRegistryBuilder → 同一治理链 → Provider → L1

调用方：工作流写节点、管理 API、Celery/脚本直调工具。禁止第三条工具执行路径。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session


@dataclass
class ToolInvokeResult:
    """invoke_tool 结果（content 已过治理链：不可信包装 / 威胁扫描）。"""
    name: str
    ok: bool
    content: Any = None
    error: str = ""
    duration_ms: int = 0
    guardrail_action: str = "allow"
    persisted: bool = False
    preview: str = ""
    full_result_ref: str = ""
    threat_findings: list[str] = field(default_factory=list)
    raw_content: Any = None      # 工具原始返回（结构化）；错误分支可能为 None


def _resolve_agent(db: Session, agent=None, agent_id: Optional[int] = None):
    if agent is not None:
        return agent
    if agent_id is None:
        return None                      # 系统级
    from app.models.agent import Agent
    return db.query(Agent).filter(Agent.id == agent_id).first()


async def invoke_tool(
    name: str,
    args: dict | None = None,
    *,
    db: Session,
    agent=None,
    agent_id: Optional[int] = None,
    user=None,
    log_handler=None,
    verify: bool = True,
    approved_ticket_id: Optional[int] = None,      # 审批通过后的执行凭据
) -> ToolInvokeResult:
    """经与 Agent 相同的注册表与治理链执行单个工具。

    Args:
        name: 工具名（注册表键）
        args: 工具参数
        db: 数据库会话
        agent / agent_id: Agent 作用域；**都不传 = 系统级**（全部启用工具）
        user: 调用用户（工具沙箱 current_user_id / 文件归属）
        verify: 是否启用写工具**证据验证**。无证据上下文的调用方（工作流 SOP /
                脚本直调 / 管理测试）传 False，由 SOP 或人工保证
        approved_ticket_id: 审批工单 id（阶段 6b）。校验通过（status=approved 且
                工具名一致）后放行确认闸并跳过证据链

    注：不传 middleware/guardrail/budget —— 前两者是 per-turn 循环守卫（单次调用
        无意义），budget 需 Execution.variables 挂载点（无则降级为截断）。
    """
    from app.agent.hermes.tool_engine import HermesToolEngine
    from app.agent.hermes.types import ToolCall
    from app.agent.hermes.verification import VerificationConfig

    if approved_ticket_id is not None:
        from app.models.workflow_ban import ApprovalTicket

        _t = db.query(ApprovalTicket).filter(ApprovalTicket.id == approved_ticket_id).first()
        if _t is None or _t.status != "approved" or (_t.tool_name or "") != name:
            return ToolInvokeResult(
                name=name, ok=False,
                error=f"审批凭据无效（ticket={approved_ticket_id}）",
            )
        if _t.result:
            try:
                _prev = json.loads(_t.result) if isinstance(_t.result, str) else (_t.result or {})
            except Exception:  # noqa: BLE001
                _prev = {}
            if not (isinstance(_prev, dict) and _prev.get("status") == "executing"):
                return ToolInvokeResult(
                    name=name, ok=False,
                    error=f"审批凭据已使用（ticket={approved_ticket_id}）",
                )
        verify = False

    agent_obj = _resolve_agent(db, agent, agent_id)

    # verification_config=None ⇒ tool_engine 直接跳过证据验证（tool_engine.py:552）
    engine = HermesToolEngine(
        db,
        agent_obj,
        log_handler=log_handler,
        user=user,
        verification_config=(VerificationConfig() if verify else None),
        approved_ticket_id=approved_ticket_id,
    )
    if not engine.has_tool(name):
        return ToolInvokeResult(
            name=name,
            ok=False,
            error=(
                f"工具不在注册表中: {name}（系统级注册表仅含全部启用工具；"
                "KB/资产/工作流/设备类工具需传 agent 或 agent_id）"
            ),
        )

    tc = ToolCall(original_index=0, id=f"invoke_tool:{name}",
                  name=name, arguments=args or {})
    r = (await engine.execute_tool_calls([tc]))[0]
    return ToolInvokeResult(
        name=name,
        ok=not r.is_error,
        content=r.content,
        error="" if not r.is_error else str(r.content),
        duration_ms=r.duration_ms,
        guardrail_action=r.guardrail_action,
        persisted=r.persisted,
        preview=r.preview,
        full_result_ref=r.full_result_ref,
        threat_findings=list(r.threat_findings or []),
        raw_content=getattr(r, "raw_content", None),
    )
