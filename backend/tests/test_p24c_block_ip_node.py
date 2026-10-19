# -*- coding: utf-8 -*-
"""P2-4c：工作流 block_ip 节点走 DeviceGateway。"""
import asyncio
from types import SimpleNamespace

import app.database as database
import app.devices.as_tool as as_tool
from app.core.node_executors import execute_block_ip
from app.devices.gateway import DeviceGateway


def test_block_ip_node_uses_gateway(monkeypatch):
    fake_db = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(database, "SessionLocal", lambda: fake_db)

    device = SimpleNamespace(id=3, name="FW-3")
    action = SimpleNamespace(id=7, action_type="block_ip")
    monkeypatch.setattr(
        as_tool, "resolve_default_block_device",
        lambda db, agent, allowed: SimpleNamespace(
            ok=True, device=device, action=action, error=None, hint=None,
        ),
    )

    called = {}

    async def fake_invoke(db, device_id, **kw):
        called["device_id"] = device_id
        called.update(kw)
        return {"success": True, "status_code": 200,
                "response_body": {"rule_id": "r-1"}, "error": None}

    monkeypatch.setattr(DeviceGateway, "invoke", staticmethod(fake_invoke))

    logs = []
    out = asyncio.run(execute_block_ip(
        {"id": "n1", "target_ip": "1.1.1.1"},
        {},
        {"workflow_id": 5},
        lambda nid, level, msg: logs.append((level, msg)),
    ))

    assert out["status"] == "success" and out["success"] is True
    assert called["device_id"] == 3
    assert called["action_id"] == 7
    assert called["source"] == "workflow"
    assert called["workflow_id"] == 5
    assert called["idempotency_key"]          # 写动作带幂等键
    assert out["ip"] == "1.1.1.1"
