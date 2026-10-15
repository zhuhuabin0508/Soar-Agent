"""工作流节点类型、遗留工具名等不在 Agent 注册表内的治理名单（派生时合并）。

注：节点类型名（block_ip/send_notification/device_action）与 Hermes 原生遗留死名
（execute_code/memory_write/memory_search/read_file/session_search/web_search/web_extract）
已从名单清理——它们不是真实智能体工具，真实写工具/只读工具由注册表派生覆盖。
"""

LEGACY_NEVER_PARALLEL = frozenset({
    "delegate_task",
    "trigger_workflow_skill",
    "query_persisted_result",
})

LEGACY_PARALLEL_SAFE = frozenset({
    "check_whitelist",
    "get_asset_info",
    "get_threat_intel",
    "check_subnet",
    "search_knowledge_base",
    "query_kb_file",
    "tool_search",
    "tool_describe",
})

PARALLEL_SAFE_PREFIXES = ("query_", "get_", "list_", "search_")

LEGACY_SOAR_WRITE = frozenset({
    "trigger_workflow_skill",
    "delegate_task",
})

LEGACY_FILE_MUTATING = frozenset({
    "trigger_workflow_skill",
})

LEGACY_NO_EFFECT = frozenset({
    "check_whitelist",
    "get_asset_info",
    "get_threat_intel",
    "check_subnet",
    "search_knowledge_base",
    "query_kb_file",
    "tool_search",
    "tool_describe",
    "list_workflow_skills",
})

FRAMEWORK_REQUIRES_EXPLICIT_ENABLE = frozenset({
    "computer_use",
    "schedule_cron",
})
