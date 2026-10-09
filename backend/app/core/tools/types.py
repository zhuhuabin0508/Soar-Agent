from typing import Literal

# MCP 暂不实施（见 docs/soar-agent-v2-master-plan.md §九）；有需求时可扩展为 Literal[..., "mcp"]
ToolSource = Literal["builtin", "framework", "security", "custom"]

TOOL_SOURCE_BUILTIN: ToolSource = "builtin"
TOOL_SOURCE_FRAMEWORK: ToolSource = "framework"
TOOL_SOURCE_SECURITY: ToolSource = "security"
TOOL_SOURCE_CUSTOM: ToolSource = "custom"
