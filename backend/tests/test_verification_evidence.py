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
