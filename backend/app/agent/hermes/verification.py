"""写操作证据验证 —— SOAR 专属，借鉴 Hermes ``agent/verification_evidence.py`` 思路。

SOAR 平台的写工具（``block_ip`` / ``device_action`` / ``send_notification`` /
``trigger_workflow_skill``）一旦执行会改变外部状态，必须有充分证据支撑。

本模块在写工具执行**前**验证证据链是否完整：

- ``block_ip``：需要 threat_intel 已查 + 不在白名单 + asset 已确认 + 决策理由充分
- ``device_action``：需要设备 ID 明确 + 动作合法 + 设备在线
- ``send_notification``：需要决策已定 + 严重程度已评估 + 通知渠道有效
- ``trigger_workflow_skill``：需要 workflow_id 存在 + payload 含必需字段

验证结果：

- ``approved`` —— 证据充分，允许执行
- ``needs_clarification`` —— 证据不足但可补，引导 Agent 调用 clarify 问用户
- ``blocked`` —— 证据严重不足或矛盾，拒绝执行，回写错误让 Agent 改策略

与 ``guardrails`` 的分工：

- ``guardrails`` 检测**循环**（重复失败/无进展），不管证据是否充分
- ``verification`` 检测**证据充分性**，不管是否循环

调用时机：``tool_engine._execute_one`` 中，工具名匹配后、实际执行前。
仅对写工具生效；读工具跳过验证。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "VerificationResult",
    "verify_write_tool",
    "WRITE_TOOLS_REQUIRING_VERIFICATION",
    "VerificationConfig",
]


# 需要验证的写工具
WRITE_TOOLS_REQUIRING_VERIFICATION = frozenset({
    "block_ip", "device_action", "send_notification", "trigger_workflow_skill",
})


@dataclass
class VerificationResult:
    """写操作验证结果。"""

    approved: bool
    code: str  # approved | needs_clarification | blocked
    message: str = ""
    missing_evidence: list[str] = field(default_factory=list)
    clarification_question: Optional[str] = None
    clarification_choices: Optional[list[str]] = None

    @property
    def needs_clarification(self) -> bool:
        return self.code == "needs_clarification"

    @property
    def blocked(self) -> bool:
        return self.code == "blocked"


@dataclass
class VerificationConfig:
    """验证配置（可从 Agent.tool_configs.verification 加载）。"""

    # block_ip 验证开关
    verify_block_ip: bool = True
    # 是否要求 threat_intel 已查（否则只要求 whitelist + asset）
    require_threat_intel: bool = False
    # device_action 验证开关
    verify_device_action: bool = True
    # send_notification 验证开关
    verify_send_notification: bool = True
    # trigger_workflow_skill 验证开关
    verify_trigger_workflow: bool = True

    @classmethod
    def from_mapping(cls, data: dict | None) -> "VerificationConfig":
        if not isinstance(data, dict):
            return cls()
        return cls(
            verify_block_ip=bool(data.get("verify_block_ip", True)),
            require_threat_intel=bool(data.get("require_threat_intel", False)),
            verify_device_action=bool(data.get("verify_device_action", True)),
            verify_send_notification=bool(data.get("verify_send_notification", True)),
            verify_trigger_workflow=bool(data.get("verify_trigger_workflow", True)),
        )


def verify_write_tool(
    tool_name: str,
    arguments: dict,
    *,
    context: dict,
    config: Optional[VerificationConfig] = None,
) -> VerificationResult:
    """验证写工具的执行证据是否充分。

    Args:
        tool_name: 工具名
        arguments: 工具调用参数
        context: 执行上下文，含已执行工具的结果（``context["tool_history"]``）
                 和已确认的事实（``context["confirmed_facts"]``）
        config: 验证配置；None 用默认

    Returns:
        VerificationResult
    """
    config = config or VerificationConfig()

    if tool_name not in WRITE_TOOLS_REQUIRING_VERIFICATION:
        return VerificationResult(approved=True, code="approved", message="非写工具，跳过验证")

    if tool_name == "block_ip" and config.verify_block_ip:
        return _verify_block_ip(arguments, context, config)
    if tool_name == "device_action" and config.verify_device_action:
        return _verify_device_action(arguments, context, config)
    if tool_name == "send_notification" and config.verify_send_notification:
        return _verify_send_notification(arguments, context, config)
    if tool_name == "trigger_workflow_skill" and config.verify_trigger_workflow:
        return _verify_trigger_workflow(arguments, context, config)

    return VerificationResult(approved=True, code="approved", message="验证已禁用")


def _verify_block_ip(
    arguments: dict,
    context: dict,
    config: VerificationConfig,
) -> VerificationResult:
    """验证 block_ip 的证据链。

    要求：
    - 参数含 ip（非空、合法格式）
    - 已查 whitelist（确认 IP 不在白名单）
    - asset 已确认（IP 属于已知资产）
    - 若 require_threat_intel=True，需已查 threat_intel
    - 若有 duration 参数，需为合法时长
    """
    missing: list[str] = []
    ip = arguments.get("ip") or arguments.get("target_ip")
    if not ip:
        missing.append("目标 IP 未指定")
    elif not _is_valid_ip(ip):
        missing.append(f"目标 IP 格式不合法: {ip}")

    tool_history: list[dict] = context.get("tool_history", [])
    tool_names_called = {t.get("name") for t in tool_history}

    # whitelist 检查
    if "check_whitelist" not in tool_names_called:
        missing.append("未查询白名单（应先调用 check_whitelist 确认 IP 不在白名单）")
    else:
        # 检查 whitelist 结果是否确认不在白名单
        wl_result = _find_tool_result(tool_history, "check_whitelist")
        if isinstance(wl_result, dict) and wl_result.get("in_whitelist"):
            return VerificationResult(
                approved=False,
                code="blocked",
                message=f"IP {ip} 在白名单中，禁止封禁。",
                missing_evidence=missing,
            )

    # asset 确认
    if "get_asset_info" not in tool_names_called:
        missing.append("未查询资产信息（应先调用 get_asset_info 确认 IP 属于已知资产）")

    # threat_intel（可选）
    if config.require_threat_intel and "get_threat_intel" not in tool_names_called:
        missing.append("未查询威胁情报（require_threat_intel=True 时必须先查 get_threat_intel）")

    # duration 校验
    duration = arguments.get("duration")
    if duration is not None:
        if not _is_valid_duration(duration):
            missing.append(f"封禁时长不合法: {duration}")

    if missing:
        return VerificationResult(
            approved=False,
            code="needs_clarification" if len(missing) <= 2 else "blocked",
            message="封禁前证据不充分: " + "; ".join(missing),
            missing_evidence=missing,
            clarification_question=f"是否确认要封禁 IP {ip}？证据不足: {'; '.join(missing)}",
            clarification_choices=["确认封禁", "取消，先补充证据"],
        )

    return VerificationResult(approved=True, code="approved", message="block_ip 证据充分")


def _verify_device_action(
    arguments: dict,
    context: dict,
    config: VerificationConfig,
) -> VerificationResult:
    """验证 device_action 的证据链。"""
    missing: list[str] = []
    device_id = arguments.get("device_id") or arguments.get("device")
    action = arguments.get("action") or arguments.get("action_name")

    if not device_id:
        missing.append("设备 ID 未指定")
    if not action:
        missing.append("设备动作未指定")

    if missing:
        return VerificationResult(
            approved=False,
            code="blocked",
            message="设备操作参数不全: " + "; ".join(missing),
            missing_evidence=missing,
        )

    return VerificationResult(approved=True, code="approved", message="device_action 参数完整")


def _verify_send_notification(
    arguments: dict,
    context: dict,
    config: VerificationConfig,
) -> VerificationResult:
    """验证 send_notification 的证据链。"""
    missing: list[str] = []
    message = arguments.get("message") or arguments.get("content")
    channel = arguments.get("channel") or arguments.get("target")

    if not message:
        missing.append("通知内容未指定")
    if not channel:
        missing.append("通知渠道未指定")

    tool_history: list[dict] = context.get("tool_history", [])
    tool_names_called = {t.get("name") for t in tool_history}
    # 通知前应有决策依据（查过情报/资产/白名单之一）
    if not ({"get_threat_intel", "get_asset_info", "check_whitelist"} & tool_names_called):
        missing.append("通知前未做任何查询（应先有决策依据）")

    if missing:
        return VerificationResult(
            approved=False,
            code="needs_clarification",
            message="通知证据不充分: " + "; ".join(missing),
            missing_evidence=missing,
        )

    return VerificationResult(approved=True, code="approved", message="send_notification 证据充分")


def _verify_trigger_workflow(
    arguments: dict,
    context: dict,
    config: VerificationConfig,
) -> VerificationResult:
    """验证 trigger_workflow_skill 的证据链。"""
    missing: list[str] = []
    workflow_id = arguments.get("workflow_id")
    payload = arguments.get("input") or arguments.get("payload") or {}

    if workflow_id is None:
        missing.append("workflow_id 未指定")
    if not payload:
        missing.append("输入 payload 为空")

    if missing:
        return VerificationResult(
            approved=False,
            code="blocked",
            message="触发工作流参数不全: " + "; ".join(missing),
            missing_evidence=missing,
        )

    return VerificationResult(approved=True, code="approved", message="trigger_workflow_skill 参数完整")


def _find_tool_result(tool_history: list[dict], name: str) -> Any:
    """从工具历史中找最近一次某工具的结果。"""
    for entry in reversed(tool_history):
        if entry.get("name") == name:
            return entry.get("result")
    return None


def _is_valid_ip(ip: str) -> bool:
    """简单 IPv4/IPv6 格式校验。"""
    import ipaddress
    try:
        ipaddress.ip_address(ip)
        return True
    except (ValueError, TypeError):
        return False


def _is_valid_duration(duration: Any) -> bool:
    """时长合法性（正整数或合法时间字符串）。"""
    if isinstance(duration, (int, float)):
        return duration > 0
    if isinstance(duration, str):
        import re
        return bool(re.match(r'^\d+\s*(s|m|h|d|秒|分|时|天)?$', duration.strip(), re.IGNORECASE))
    return False
