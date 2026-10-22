from typing import Literal

# MCP 暂不实施（见 docs/soar-agent-v2-master-plan.md §九）；有需求时可扩展为 Literal[..., "mcp"]
ToolSource = Literal["builtin", "framework", "security", "device", "custom"]

TOOL_SOURCE_BUILTIN: ToolSource = "builtin"
TOOL_SOURCE_FRAMEWORK: ToolSource = "framework"
TOOL_SOURCE_SECURITY: ToolSource = "security"
# 设备对接模块工具（如 query_device_actions 设备信息及动作查询）
TOOL_SOURCE_DEVICE: ToolSource = "device"
TOOL_SOURCE_CUSTOM: ToolSource = "custom"
