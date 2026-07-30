"""威胁模式扫描器 —— 移植自 Hermes ``tools/threat_patterns.py``。

SOAR 平台本身处理安全告警，知识库/HTTP 工具/威胁情报 API 返回的内容
可能携带 prompt injection、C2 指令、凭据外泄 payload。本模块是上下文
窗口安全扫描的唯一真相源，被以下路径复用：

- ``untrusted.maybe_wrap_untrusted`` —— 不可信工具结果包装前扫描
- ``memory`` 写入前 strict 扫描（等保要求）
- ``prompt_assembler`` 技能注入前 strict 扫描
- ``message_sanitization`` 送 LLM 前 context 扫描

与 Hermes 一致的设计：

1. **按攻击类别组织**，而非按源文件。每条 pattern 是
   ``(regex, pattern_id, scope)`` 三元组，``scope`` 控制哪些扫描器使用它：

   - ``"all"``     —— 经典 prompt injection + 凭据外泄，处处应用
   - ``"context"`` —— 上下文/记忆/工具结果（promptware / C2 / 角色劫持）
   - ``"strict"``  —— 仅记忆写入 + 技能安装（激进检查，可接受误报）

2. **有界 filler**：``(?:\\w+\\s+){0,8}`` 防止攻击者插入少量词绕过，
   同时避免无界回溯。

3. **NFKC 归一化**：全宽字符（ｃａｔ → cat）折叠为 ASCII，防同形字绕过。

4. **不可见 Unicode 检测**：零宽字符、双向控制字符（U+202A-E、U+2066-9）
   是真实攻击工具，单独检测并返回码点。

5. **有界扫描**：``MAX_SCAN_CHARS = 65536``，扫描器是建议性守卫而非
   归档搜索，有界输入保证最坏情况运行时可预测。

SOAR 适配：

- 工具名替换为 Soar 实际工具（``get_threat_intel`` / ``query_kb_file`` /
  ``search_knowledge_base`` / ``http_*`` / ``openapi_*``）
- 新增 SOAR 写工具劫持检测（``block_ip`` / ``send_notification`` /
  ``device_action`` / ``trigger_workflow_skill``）
- 新增等保相关：凭据外泄到外网、未授权设备操作
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 有界扫描上限。上下文/工具结果字符串可能任意大，扫描器是建议性守卫
# 而非归档搜索；有界输入保证最坏情况运行时可预测，同时保留注入内容
# 开头部分的检测。
MAX_SCAN_CHARS = 65_536

# 关键攻击词之间的有界 filler。早期 pattern 用 ``(?:\w+\s+)*`` 歧义且
# 在对抗性近似匹配上会严重回溯。8 个 filler 词足够覆盖意图混淆绕过，
# 又不引入无界重复。
_FILLER = r"(?:\w+\s+){0,8}"


# 每条：(regex, pattern_id, scope)
# scope ∈ {"all", "context", "strict"}
_PATTERNS: List[Tuple[str, str, str]] = [
    # ── 经典 prompt injection（处处应用）────────────────────────
    (rf'ignore\s+{_FILLER}(previous|all|above|prior)\s+{_FILLER}instructions', "prompt_injection", "all"),
    (r'system\s+prompt\s+override', "sys_prompt_override", "all"),
    (rf'disregard\s+{_FILLER}(your|all|any)\s+{_FILLER}(instructions|rules|guidelines)', "disregard_rules", "all"),
    (rf'act\s+as\s+(if|though)\s+{_FILLER}you\s+{_FILLER}(have\s+no|don\'t\s+have)\s+{_FILLER}(restrictions|limits|rules)', "bypass_restrictions", "all"),
    (r'<!--[^>]{0,512}(?:ignore|override|system|secret|hidden)[^>]{0,512}-->', "html_comment_injection", "all"),
    (r'<\s*div\s+style\s*=\s*["\'][^>]{0,2048}display\s*:\s*none', "hidden_div", "all"),
    (r'translate\s+[^\n]{0,512}\s+into\s+[^\n]{0,512}\s+and\s+(execute|run|eval)', "translate_execute", "all"),
    (rf'do\s+not\s+{_FILLER}tell\s+{_FILLER}the\s+user', "deception_hide", "all"),

    # ── 角色扮演 / 身份劫持（context + strict）──────────────────
    (rf'you\s+are\s+{_FILLER}now\s+(?:a|an|the)\s+', "role_hijack", "context"),
    (rf'pretend\s+{_FILLER}(you\s+are|to\s+be)\s+', "role_pretend", "context"),
    (rf'output\s+{_FILLER}(system|initial)\s+prompt', "leak_system_prompt", "context"),
    (rf'(respond|answer|reply)\s+without\s+{_FILLER}(restrictions|limitations|filters|safety)', "remove_filters", "context"),
    (rf'you\s+have\s+been\s+{_FILLER}(updated|upgraded|patched)\s+to', "fake_update", "context"),
    (r'\bname\s+yourself\s+\w+', "identity_override", "context"),

    # ── C2 / Brainworm 风格 promptware（context scope）──────────
    (r'register\s+(as\s+)?a?\s*node', "c2_node_registration", "context"),
    (r'(heartbeat|beacon|check[\s\-]?in)\s+(to|with)\s+', "c2_heartbeat", "context"),
    (r'pull\s+(down\s+)?(?:new\s+)?task(?:ing|s)?\b', "c2_task_pull", "context"),
    (r'connect\s+to\s+the\s+network\b', "c2_network_connect", "context"),
    (r'you\s+must\s+(?:\w+\s+){0,3}(register|connect|report|beacon)\b', "forced_action", "context"),
    (r'only\s+use\s+one[\s\-]?liners?\b', "anti_forensic_oneliner", "context"),
    (rf'never\s+{_FILLER}(?:create|write)\s+{_FILLER}(?:script|file)\s+{_FILLER}disk', "anti_forensic_disk", "context"),
    # 针对 Agent 运行时的环境变量 unset —— 纯攻击行为
    (r'unset\s+\w*(?:CLAUDE|CODEX|HERMES|AGENT|OPENAI|ANTHROPIC|SOAR)\w*', "env_var_unset_agent", "context"),

    # ── 已知 C2 / 红队框架名（安全研究外近乎零误报）────────────
    (r'\b(?:cobalt\s*strike|sliver|havoc|mythic|metasploit|brainworm)\b', "known_c2_framework", "context"),
    (r'\bc2\s+(?:server|channel|infrastructure|beacon)\b', "c2_explicit", "context"),
    (r'\bcommand\s+and\s+control\b', "c2_explicit_long", "context"),

    # ── 凭据外泄 via curl/wget/cat（处处应用）──────────────────
    (r'curl\s+[^\n]{0,2048}\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl", "all"),
    (r'wget\s+[^\n]{0,2048}\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget", "all"),
    (r'cat\s+[^\n]{0,2048}(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)', "read_secrets", "all"),
    (r'(send|post|upload|transmit)\s+[^\n]{0,2048}\s+(to|at)\s+https?://', "send_to_url", "strict"),
    (rf'(include|output|print|share)\s+{_FILLER}(conversation|chat\s+history|previous\s+messages|full\s+context|entire\s+context)', "context_exfil", "strict"),

    # ── 持久化 / SSH 后门（strict scope —— 记忆 + 技能）────────
    (r'authorized_keys', "ssh_backdoor", "strict"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access", "strict"),
    (r'\$HOME/\.soar/\.env|\~/\.soar/\.env|\.env\.docker', "soar_env", "strict"),
    (r'(update|modify|edit|write|change|append|add\s+to)\s+[^\n]{0,2048}(?:AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules|SOUL\.md)', "agent_config_mod", "strict"),
    (r'(update|modify|edit|write|change|append|add\s+to)\s+[^\n]{0,2048}config\.ya?ml', "config_mod", "strict"),

    # ── 硬编码凭据 ────────────────────────────────────────────
    (r'(?:api[_-]?key|token|secret|password|access[_-]?key)\s*[=:]\s*["\'][A-Za-z0-9+/=_-]{20,}', "hardcoded_secret", "strict"),

    # ── SOAR 专属：写工具劫持检测（context scope）─────────────
    # 攻击者通过工具结果诱导 Agent 执行未授权的写操作
    (rf'(block|ban|blacklist)\s+{_FILLER}(?:ip|address|host)\s+{_FILLER}(?:0\.0\.0\.0|255\.255\.255\.255|\*|all|everyone)', "blocklist_wildcard", "context"),
    (r'(execute|run|call|invoke)\s+(?:block_ip|send_notification|device_action|trigger_workflow)\s+without\s+(?:approval|confirm)', "unauthorized_write_tool", "context"),
    (r'disable\s+(?:firewall|ids|ips|siem|logging|audit)', "disable_security_control", "context"),
    (r'(grant|give)\s+(?:admin|root|superuser)\s+(?:access|privileges|rights)', "privilege_escalation", "context"),
]

# 不可见 / 双向 Unicode 字符，用于注入攻击。
# 与 skills_guard.py INVISIBLE_CHARS 对齐 —— 方向隔离符（U+2066-U+2069）
# 和不可见数学运算符（U+2062-U+2064）是真实攻击工具。
INVISIBLE_CHARS = frozenset({
    '\u200b',  # 零宽空格
    '\u200c',  # 零宽非连接符
    '\u200d',  # 零宽连接符
    '\u2060',  # 词连接符
    '\u2062',  # 不可见乘
    '\u2063',  # 不可见分隔符
    '\u2064',  # 不可见加
    '\ufeff',  # 零宽不换行空格（BOM）
    '\u202a',  # 从左到右嵌入
    '\u202b',  # 从右到左嵌入
    '\u202c',  # 弹出方向格式
    '\u202d',  # 从左到右覆盖
    '\u202e',  # 从右到左覆盖
    '\u2066',  # 从左到右隔离
    '\u2067',  # 从右到左隔离
    '\u2068',  # 第一强隔离
    '\u2069',  # 弹出方向隔离
})


# 按 scope 索引的编译后 pattern 集。导入时编译一次；scan_for_threats 查找。
_COMPILED: dict[str, List[Tuple[re.Pattern, str]]] = {}


def _compile() -> None:
    """为每个 scope 编译 pattern 集（all / context / strict）。

    scope="all" 的 pattern 进入每个集合。
    scope="context" 的 pattern 进入 context + strict（context 意味着 strict 也想要）。
    scope="strict" 的 pattern 只进入 strict。
    """
    global _COMPILED
    if _COMPILED:
        return

    all_patterns: List[Tuple[re.Pattern, str]] = []
    context_patterns: List[Tuple[re.Pattern, str]] = []
    strict_patterns: List[Tuple[re.Pattern, str]] = []

    for pattern, pid, scope in _PATTERNS:
        compiled = re.compile(pattern, re.IGNORECASE)
        entry = (compiled, pid)
        if scope == "all":
            all_patterns.append(entry)
            context_patterns.append(entry)
            strict_patterns.append(entry)
        elif scope == "context":
            context_patterns.append(entry)
            strict_patterns.append(entry)
        elif scope == "strict":
            strict_patterns.append(entry)
        else:
            raise ValueError(f"threat_scanner: 未知 scope {scope!r}，pattern {pid!r}")

    _COMPILED = {
        "all": all_patterns,
        "context": context_patterns,
        "strict": strict_patterns,
    }


_compile()


def scan_for_threats(content: str, scope: str = "context") -> List[str]:
    """返回 ``content`` 在指定 scope 下匹配的 pattern ID 列表。

    ``scope`` 选择应用哪个 pattern 集：

    - ``"all"``（窄）：经典注入 + 外泄，最小误报，适合任何文本。
    - ``"context"``（默认）：加 promptware / C2 / 角色扮演 pattern，
      适合上下文文件、记忆条目、工具结果。
    - ``"strict"``（宽）：加持久化 / SSH 后门 / 外泄 URL pattern，
      适合用户中介的写入（记忆工具、技能安装），误报可交互解决。

    也检查不可见 Unicode 字符（返回 ``"invisible_unicode_U+XXXX"``，
    以便调用方在日志行中暴露违规码点）。
    """
    if not content:
        return []

    findings: List[str] = []

    content = content[:MAX_SCAN_CHARS]

    # 不可见 Unicode —— 对 content 字符集做单次遍历，而非 17 次 ``in`` 查找。
    # 在 NFKC 归一化前对原始 content 运行，因为归一化可能剥离部分码点。
    char_set = set(content)
    invisible_hits = char_set & INVISIBLE_CHARS
    for ch in invisible_hits:
        findings.append(f"invisible_unicode_U+{ord(ch):04X}")

    # NFKC 归一化，使全宽 / 兼容 Unicode 变体（ｃａｔ → cat，Ａ → A）折叠为
    # ASCII 对应字符，再交给 regex 引擎。防同形字替换绕过
    # （``ｃａｔ ~/.soar/.env``）。
    # 注意：不防御跨脚本同形字（Cyrillic ``а`` U+0430），NFKC 不动它，
    # 那需要 TR#39 同形字数据库。
    normalised = unicodedata.normalize("NFKC", content)

    patterns = _COMPILED.get(scope)
    if patterns is None:
        raise ValueError(f"scan_for_threats: 未知 scope {scope!r}")
    for compiled, pid in patterns:
        if compiled.search(normalised):
            findings.append(pid)

    return findings


def first_threat_message(content: str, scope: str = "strict") -> Optional[str]:
    """返回首个威胁的可读错误串，或 None。

    供首次命中即 block 的路径使用（记忆工具写入、技能安装），
    调用方只需 yes/no + 消息。
    """
    findings = scan_for_threats(content, scope=scope)
    if not findings:
        return None
    pid = findings[0]
    if pid.startswith("invisible_unicode_"):
        codepoint = pid.replace("invisible_unicode_", "")
        return f"已拦截：内容包含不可见 Unicode 字符 {codepoint}（可能的注入）。"
    return (
        f"已拦截：内容匹配威胁模式 '{pid}'。"
        f"该内容将被注入到系统提示词，不得包含注入或外泄 payload。"
    )


def scan_tool_result(tool_name: str, content: str) -> List[str]:
    """扫描工具结果（context scope）。

    供 ``untrusted.maybe_wrap_untrusted`` 包装前调用，记录威胁发现到
    ``ToolResult.threat_findings``。不阻断（包装仍进行），但发现会被
    记录并影响 guardrail 决策。
    """
    if not content:
        return []
    # 工具结果用 context scope —— 宽检测但不阻断（外网内容可能合法提及 C2）
    return scan_for_threats(content, scope="context")


def scan_memory_write(content: str) -> tuple[bool, Optional[str]]:
    """扫描记忆写入（strict scope，阻断式）。

    等保要求：用户长期记忆不得包含注入 payload 或凭据外泄内容。
    返回 ``(allowed, block_message)``。``allowed=False`` 时 ``block_message``
    说明拦截原因，应回写给 LLM 让其调整。
    """
    msg = first_threat_message(content, scope="strict")
    if msg is None:
        return True, None
    return False, msg


def scan_skill_injection(content: str) -> tuple[bool, Optional[str]]:
    """扫描技能正文（strict scope，阻断式）。

    技能被注入到 system prompt，是最高权限上下文。任何注入迹象都应阻断。
    """
    msg = first_threat_message(content, scope="strict")
    if msg is None:
        return True, None
    return False, msg


__all__ = [
    "INVISIBLE_CHARS",
    "MAX_SCAN_CHARS",
    "scan_for_threats",
    "first_threat_message",
    "scan_tool_result",
    "scan_memory_write",
    "scan_skill_injection",
]
