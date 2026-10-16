# -*- coding: utf-8 -*-
"""P2-4a 单测：resolve_default_block_device + build_block_ip_tool。"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# fake db：支持 Device / DeviceAction 查询，能解析常见 filter（eq/in_/is_）
# ---------------------------------------------------------------------------

def _match(row, expr) -> bool:
    try:
        left = expr.left
        key = getattr(left, "key", None)
        if key is None:
            return True
        val = getattr(row, key, None)
        op_name = getattr(expr.operator, "__name__", "")
        right = expr.right
        if op_name == "in_op":
            if hasattr(right, "element"):
                rv = list(right.element)
            elif hasattr(right, "value"):
                rv = right.value
            else:
                rv = list(right)
            return val in rv
        if op_name in ("is_", "eq"):
            rv = right.value if hasattr(right, "value") else right
            return val == rv
        if op_name == "ne":
            rv = right.value if hasattr(right, "value") else right
            return val != rv
    except Exception:
        pass
    return True


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []

    def filter(self, *clauses):
        self._filters.extend(clauses)
        return self

    def all(self):
        return [r for r in self._rows if all(_match(r, c) for c in self._filters)]

    def first(self):
        rows = self.all()
        return rows[0] if rows else None


def _fake_db(devices, actions):
    from app.models.device import Device, DeviceAction
    db = MagicMock()
    db.query.side_effect = lambda m: (
        _FakeQuery(devices) if m is Device else _FakeQuery(actions)
    )
    return db


def _device(id, status="online", enabled=True, tags="[]"):
    return SimpleNamespace(id=id, name=f"设备{id}", enabled=enabled,
                           status=status, tags=tags)


def _action(id, device_id, action_type="block_ip", enabled=True):
    return SimpleNamespace(id=id, device_id=device_id, action_type=action_type,
                           enabled=enabled)


def _agent(**kwargs):
    defaults = dict(id=1, variables={}, enabled_devices=[])
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# resolve_default_block_device
# ---------------------------------------------------------------------------

class TestResolveDefaultBlockDevice:
    def _db(self):
        devices = [
            _device(3, tags='["封禁"]'),
            _device(4, tags='["production"]'),
            _device(5, status="offline", tags='["封禁"]'),
            _device(6, enabled=False, tags='["封禁"]'),
        ]
        actions = [
            _action(1, 3, "block_ip"),
            _action(2, 4, "block_ip"),
            _action(3, 3, "query_logs"),
            _action(4, 6, "block_ip"),
        ]
        return _fake_db(devices, actions)

    def test_default_device_id_hit(self):
        from app.devices.as_tool import resolve_default_block_device
        db = self._db()
        agent = _agent(variables={"default_device_id": 3})
        res = resolve_default_block_device(db, agent, allowed_device_ids={3, 4})
        assert res.ok
        assert res.device.id == 3
        assert res.action.action_type == "block_ip"

    def test_default_device_id_out_of_scope(self):
        from app.devices.as_tool import resolve_default_block_device
        db = self._db()
        agent = _agent(variables={"default_device_id": 3})
        res = resolve_default_block_device(db, agent, allowed_device_ids={4})
        assert not res.ok
        assert "不可用" in res.error

    def test_default_device_id_offline(self):
        from app.devices.as_tool import resolve_default_block_device
        db = self._db()
        agent = _agent(variables={"default_device_id": 5})
        res = resolve_default_block_device(db, agent, allowed_device_ids={5})
        assert not res.ok

    def test_default_device_id_disabled(self):
        from app.devices.as_tool import resolve_default_block_device
        db = self._db()
        agent = _agent(variables={"default_device_id": 6})
        res = resolve_default_block_device(db, agent, allowed_device_ids={6})
        assert not res.ok

    def test_tags_fallback_unique(self):
        from app.devices.as_tool import resolve_default_block_device
        db = self._db()
        agent = _agent(variables={})
        res = resolve_default_block_device(db, agent, allowed_device_ids={3})
        assert res.ok
        assert res.device.id == 3

    def test_tags_fallback_ambiguous(self):
        from app.devices.as_tool import resolve_default_block_device
        db = self._db()
        agent = _agent(variables={})
        res = resolve_default_block_device(db, agent, allowed_device_ids={3, 4})
        assert not res.ok
        assert "多个候选" in res.error

    def test_tags_fallback_no_match(self):
        from app.devices.as_tool import resolve_default_block_device
        db = self._db()
        agent = _agent(variables={})
        # 只允许离线设备 5 → 无候选
        res = resolve_default_block_device(db, agent, allowed_device_ids={5})
        assert not res.ok
        assert "无法解析" in res.error

    def test_default_device_id_invalid(self):
        from app.devices.as_tool import resolve_default_block_device
        db = self._db()
        agent = _agent(variables={"default_device_id": "abc"})
        res = resolve_default_block_device(db, agent, allowed_device_ids={3})
        assert not res.ok
        assert "非法" in res.error

    def test_no_candidates_returns_structured_error(self):
        from app.devices.as_tool import resolve_default_block_device
        db = _fake_db([], [])
        agent = _agent(variables={})
        res = resolve_default_block_device(db, agent, allowed_device_ids=set())
        assert not res.ok
        assert res.error
        assert res.hint  # 不静默失败，给提示


# ---------------------------------------------------------------------------
# build_block_ip_tool
# ---------------------------------------------------------------------------

class TestBuildBlockIpTool:
    def test_tool_metadata_and_governance_flags(self):
        from app.devices.as_tool import build_block_ip_tool
        db = _fake_db([], [])
        tool = build_block_ip_tool(db, _agent(), allowed_device_ids={3})
        assert tool.name == "block_ip"
        assert tool.mutating is True
        assert tool.parallel_safe is False
        assert tool.deferrable is False
        assert tool.verification is not None  # 进 write_tools_requiring_verification
        # 参数含 ip（必填）、duration、reason（pydantic 模型字段）
        model_fields = tool.args_schema.model_fields if tool.args_schema else {}
        assert "ip" in model_fields
        assert "duration" in model_fields
        assert "reason" in model_fields

    def test_coroutine_returns_error_when_no_device(self):
        from app.devices.as_tool import build_block_ip_tool
        db = _fake_db([], [])
        tool = build_block_ip_tool(db, _agent(variables={}), allowed_device_ids=set())
        out = asyncio.run(tool.coroutine(ip="1.1.1.1"))
        assert isinstance(out, dict) and "error" in out

    def test_coroutine_invokes_gateway_on_success(self):
        from app.devices.as_tool import build_block_ip_tool
        devices = [_device(3, tags='["封禁"]')]
        actions = [_action(1, 3, "block_ip")]
        db = _fake_db(devices, actions)
        tool = build_block_ip_tool(db, _agent(variables={}), allowed_device_ids={3})
        with patch("app.devices.gateway.DeviceGateway.invoke") as mock_invoke:
            mock_invoke.return_value = {"ok": True, "banned_ip": "1.1.1.1"}
            out = asyncio.run(tool.coroutine(ip="1.1.1.1", reason="恶意IP"))
        assert out == {"ok": True, "banned_ip": "1.1.1.1"}
        mock_invoke.assert_called_once()
        # 传参包含 ip + reason
        _, kwargs = mock_invoke.call_args
        assert kwargs["action_id"] == 1
        assert kwargs["params"]["ip"] == "1.1.1.1"
        assert kwargs["params"]["reason"] == "恶意IP"

    def test_verification_routes_block_ip_to_evidence_chain(self):
        # block_ip 与 block_ip_on_firewall 一样走封禁证据链（白名单+资产）
        from app.agent.hermes.verification import VerificationConfig, verify_write_tool
        res = verify_write_tool(
            "block_ip",
            {"ip": "1.1.1.1"},
            context={"tool_history": []},
            config=VerificationConfig(),
            write_tools=frozenset({"block_ip"}),
        )
        assert not res.approved  # 缺白名单/资产证据
