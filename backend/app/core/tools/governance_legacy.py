"""工作流节点类型、遗留工具名等不在 Agent 注册表内的治理名单（派生时合并）。"""

LEGACY_NEVER_PARALLEL = frozenset({
    "block_ip",
    "send_notification",
    "device_action",
    "execute_code",
    "delegate_task",
    "trigger_workflow_skill",
    "memory_write",
    "query_persisted_result",
})

LEGACY_PARALLEL_SAFE = frozenset({
    "check_whitelist",
    "get_asset_info",
    "get_threat_intel",
    "check_subnet",
    "search_knowledge_base",
    "query_kb_file",
    "web_search",
    "web_extract",
    "read_file",
    "session_search",
    "memory_search",
    "tool_search",
    "tool_describe",
})

PARALLEL_SAFE_PREFIXES = ("query_", "get_", "list_", "search_")

LEGACY_SOAR_WRITE = frozenset({
    "block_ip",
    "send_notification",
    "device_action",
    "trigger_workflow_skill",
    "delegate_task",
    "memory_write",
    "execute_code",
})

LEGACY_FILE_MUTATING = frozenset({
    "block_ip",
    "device_action",
    "trigger_workflow_skill",
    "memory_write",
})

LEGACY_NO_EFFECT = frozenset({
    "check_whitelist",
    "get_asset_info",
    "get_threat_intel",
    "check_subnet",
    "search_knowledge_base",
    "query_kb_file",
    "read_file",
    "session_search",
    "memory_search",
    "tool_search",
    "tool_describe",
    "list_workflow_skills",
    "web_search",
    "web_extract",
})

FRAMEWORK_REQUIRES_EXPLICIT_ENABLE = frozenset({
    "computer_use",
    "schedule_cron",
})
