"""P0-③ 证据链验证单测：block_ip_on_firewall 纳入验证集 + 证据绑定 IP。"""
from app.agent.hermes.verification import VerificationConfig, verify_write_tool


def _entry(name, ip, result):
    return {"name": name, "arguments": {"ip": ip}, "result": result, "is_error": False}


def test_empty_history_blocks_ban():
    res = verify_write_tool(
        "block_ip_on_firewall",
        {"ip": "1.1.1.1"},
        context={"tool_history": []},
        config=VerificationConfig(),
    )
    assert not res.approved
    assert res.code in ("blocked", "needs_clarification")


def test_mismatched_ip_rejected():
    history = [
        _entry("check_whitelist", "1.1.1.1", {"ip": "1.1.1.1", "in_whitelist": False}),
    ]
    res = verify_write_tool(
        "block_ip_on_firewall",
        {"ip": "2.2.2.2"},
        context={"tool_history": history},
        config=VerificationConfig(),
    )
    assert not res.approved


def test_matching_evidence_approved():
    history = [
        _entry("check_whitelist", "1.1.1.1", {"ip": "1.1.1.1", "in_whitelist": False}),
        _entry("get_asset_info", "1.1.1.1", {"ip": "1.1.1.1", "found": True}),
    ]
    res = verify_write_tool(
        "block_ip_on_firewall",
        {"ip": "1.1.1.1"},
        context={"tool_history": history},
        config=VerificationConfig(),
    )
    assert res.approved


def test_in_whitelist_blocked():
    history = [
        _entry("check_whitelist", "1.1.1.1", {"ip": "1.1.1.1", "in_whitelist": True}),
        _entry("get_asset_info", "1.1.1.1", {"ip": "1.1.1.1", "found": True}),
    ]
    res = verify_write_tool(
        "block_ip_on_firewall",
        {"ip": "1.1.1.1"},
        context={"tool_history": history},
        config=VerificationConfig(),
    )
    assert res.code == "blocked"


def test_trigger_workflow_still_verified():
    res = verify_write_tool(
        "trigger_workflow_skill",
        {"workflow_id": 1},
        context={"tool_history": []},
        config=VerificationConfig(),
    )
    assert not res.approved


# ---------- P2-2b 设备工具验证（投影 / 门面两种形态） ----------

_DEVICE_WRITE_TOOLS = frozenset({"device_3_7", "device_3_8", "device_action"})


def test_device_projection_ip_without_evidence_rejected():
    res = verify_write_tool(
        "device_3_7",
        {"ip": "1.1.1.1"},
        context={"tool_history": []},
        config=VerificationConfig(),
        write_tools=_DEVICE_WRITE_TOOLS,
    )
    assert not res.approved
    assert res.missing_evidence  # 缺白名单/资产证据


def test_device_projection_ip_with_evidence_approved():
    history = [
        _entry("check_whitelist", "1.1.1.1", {"ip": "1.1.1.1", "in_whitelist": False}),
        _entry("get_asset_info", "1.1.1.1", {"ip": "1.1.1.1", "found": True}),
    ]
    res = verify_write_tool(
        "device_3_7",
        {"ip": "1.1.1.1"},
        context={"tool_history": history},
        config=VerificationConfig(),
        write_tools=_DEVICE_WRITE_TOOLS,
    )
    assert res.approved


def test_device_facade_block_without_evidence_rejected():
    res = verify_write_tool(
        "device_action",
        {"device_id": 3, "action_type": "block_ip", "params": {"ip": "1.1.1.1"}},
        context={"tool_history": []},
        config=VerificationConfig(),
        write_tools=_DEVICE_WRITE_TOOLS,
    )
    assert not res.approved
    assert res.missing_evidence


def test_device_facade_block_with_evidence_approved():
    history = [
        _entry("check_whitelist", "1.1.1.1", {"ip": "1.1.1.1", "in_whitelist": False}),
        _entry("get_asset_info", "1.1.1.1", {"ip": "1.1.1.1", "found": True}),
    ]
    res = verify_write_tool(
        "device_action",
        {"device_id": 3, "action_type": "block_ip", "ip": "1.1.1.1"},
        context={"tool_history": history},
        config=VerificationConfig(),
        write_tools=_DEVICE_WRITE_TOOLS,
    )
    assert res.approved


def test_device_facade_non_block_full_args_approved():
    res = verify_write_tool(
        "device_action",
        {"device_id": 3, "action_type": "query_logs"},
        context={"tool_history": []},
        config=VerificationConfig(),
        write_tools=_DEVICE_WRITE_TOOLS,
    )
    assert res.approved


def test_device_facade_missing_action_rejected():
    res = verify_write_tool(
        "device_action",
        {"device_id": 3},
        context={"tool_history": []},
        config=VerificationConfig(),
        write_tools=_DEVICE_WRITE_TOOLS,
    )
    assert not res.approved
    assert res.code == "blocked"
    assert "设备动作未指定" in res.missing_evidence


def test_device_projection_non_ip_with_args_approved():
    res = verify_write_tool(
        "device_3_8",
        {"hostname": "web-01"},
        context={"tool_history": []},
        config=VerificationConfig(),
        write_tools=_DEVICE_WRITE_TOOLS,
    )
    assert res.approved


def test_device_projection_empty_args_rejected():
    res = verify_write_tool(
        "device_3_8",
        {},
        context={"tool_history": []},
        config=VerificationConfig(),
        write_tools=_DEVICE_WRITE_TOOLS,
    )
    assert not res.approved
    assert res.code == "needs_clarification"
