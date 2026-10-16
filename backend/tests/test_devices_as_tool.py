# -*- coding: utf-8 -*-
"""P2-2a 单测：devices/as_tool.py 四个构建器（不接数据库）。"""
from types import SimpleNamespace

from app.devices.as_tool import (
    build_device_action_facade_tool,
    build_device_action_tool,
    build_list_device_actions_tool,
    build_list_devices_tool,
    is_write_action,
)
from app.core.tools.descriptor import ToolDescriptor


def _mock_device(id=3, name="测试防火墙"):
    return SimpleNamespace(id=id, name=name, type="firewall", vendor="测试厂商",
                           enabled=True, status="online", description="单测设备")


def _mock_action(id=7, device_id=3, action_type="block_ip", category="block",
                 risk_level="high_risk", params_schema=None, name="封禁IP",
                 description="封禁指定 IP"):
    return SimpleNamespace(
        id=id, device_id=device_id, name=name, action_type=action_type,
        category=category, risk_level=risk_level,
        params_schema=params_schema if params_schema is not None else "[]",
        description=description, enabled=True,
    )


class TestIsWriteAction:
    def test_high_risk_is_write(self):
        assert is_write_action(_mock_action(risk_level="high_risk", category="other"))

    def test_block_category_is_write(self):
        assert is_write_action(_mock_action(risk_level="readonly", category="block"))

    def test_dispose_category_is_write(self):
        assert is_write_action(_mock_action(risk_level="readonly", category="dispose"))

    def test_read_action_not_write(self):
        assert not is_write_action(_mock_action(risk_level="readonly", category="query"))

    def test_case_insensitive(self):
        assert is_write_action(_mock_action(risk_level="High_Risk", category="query"))
        assert is_write_action(_mock_action(risk_level="readonly", category="Block"))


class TestBuildDeviceActionTool:
    def test_name_projection(self):
        tool = build_device_action_tool(None, _mock_device(id=3), _mock_action(id=7))
        assert tool.name == "device_3_7"
        assert isinstance(tool, ToolDescriptor)

    def test_write_action_flags(self):
        tool = build_device_action_tool(
            None, _mock_device(),
            _mock_action(category="block", risk_level="high_risk"),
        )
        assert tool.mutating is True
        assert tool.verification == "device_action"
        assert tool.parallel_safe is False
        assert tool.deferrable is False

    def test_read_action_flags(self):
        tool = build_device_action_tool(
            None, _mock_device(),
            _mock_action(action_type="query_logs", category="query", risk_level="readonly"),
        )
        assert tool.mutating is False
        assert tool.verification is None
        assert tool.parallel_safe is True
        assert tool.deferrable is True

    def test_source_and_tool_type(self):
        tool = build_device_action_tool(None, _mock_device(), _mock_action())
        assert tool.source == "device"
        assert tool.tool_source == "device"
        assert tool.tool_type == "device"

    def test_args_schema_from_params_schema(self):
        import json
        schema = json.dumps([
            {"name": "ip", "type": "String", "required": True, "description": "目标 IP"},
            {"name": "duration", "type": "Number", "required": False, "description": "时长"},
        ])
        tool = build_device_action_tool(
            None, _mock_device(), _mock_action(params_schema=schema),
        )
        model = tool.args_schema
        assert model is not None
        assert "ip" in model.model_fields
        assert "duration" in model.model_fields
        # required 字段必填
        ip_field = model.model_fields["ip"]
        assert ip_field.is_required()

    def test_bad_params_schema_fallback(self):
        tool = build_device_action_tool(
            None, _mock_device(), _mock_action(params_schema="not-json{{{"),
        )
        assert tool.args_schema is not None  # 回退空 schema 仍产出模型

    def test_description_contains_usage_info(self):
        tool = build_device_action_tool(
            None, _mock_device(name="核心防火墙"),
            _mock_action(action_type="block_ip", risk_level="high_risk"),
        )
        desc = tool.description
        assert "核心防火墙" in desc
        assert "block_ip" in desc
        assert "high_risk" in desc
        assert "何时用" in desc


class TestEnumTools:
    def test_list_devices_tool(self):
        tool = build_list_devices_tool(None)
        assert tool.name == "list_devices"
        assert tool.source == "device"
        assert tool.tool_source == "device"
        assert tool.tool_type == "device"
        assert tool.mutating is False
        assert tool.verification is None
        assert tool.parallel_safe is True
        assert tool.deferrable is False
        assert tool.args_schema is None

    def test_list_device_actions_tool(self):
        tool = build_list_device_actions_tool(None)
        assert tool.name == "list_device_actions"
        assert tool.source == "device"
        assert tool.tool_source == "device"
        assert tool.tool_type == "device"
        assert tool.mutating is False
        assert tool.verification is None
        assert tool.parallel_safe is True
        assert tool.deferrable is False
        assert tool.args_schema is None
        # parameters 含可选 device_id
        props = tool.parameters["properties"]
        assert "device_id" in props
        assert props["device_id"]["type"] == "integer"
        assert "required" not in tool.parameters


class TestFacadeTool:
    def test_facade_flags(self):
        tool = build_device_action_facade_tool(None)
        assert tool.name == "device_action"
        assert tool.source == "device"
        assert tool.tool_source == "device"
        assert tool.tool_type == "device"
        # 门面按写动作处理（最保守）
        assert tool.mutating is True
        assert tool.verification == "device_action"
        assert tool.parallel_safe is False
        assert tool.deferrable is False

    def test_facade_parameters(self):
        tool = build_device_action_facade_tool(None)
        props = tool.parameters["properties"]
        assert set(props) == {"device_id", "action_type", "params"}
        assert tool.parameters["required"] == ["device_id", "action_type"]

    def test_facade_description_mentions_fallback(self):
        desc = build_device_action_facade_tool(None).description
        assert "兜底" in desc
        assert "优先" in desc

    async def _invoke_facade(self, **kwargs):
        tool = build_device_action_facade_tool(None)
        return await tool.coroutine(**kwargs)

    def test_facade_missing_args(self):
        import asyncio
        out = asyncio.run(self._invoke_facade(device_id=1))
        assert "error" in out
        out = asyncio.run(self._invoke_facade(action_type="block_ip"))
        assert "error" in out

    def test_facade_bad_device_id(self):
        import asyncio
        out = asyncio.run(self._invoke_facade(device_id="abc", action_type="block_ip"))
        assert "error" in out
