from typing import Literal

ToolSource = Literal["builtin", "framework", "security", "custom"]

TOOL_SOURCE_BUILTIN: ToolSource = "builtin"
TOOL_SOURCE_FRAMEWORK: ToolSource = "framework"
TOOL_SOURCE_SECURITY: ToolSource = "security"
TOOL_SOURCE_CUSTOM: ToolSource = "custom"
