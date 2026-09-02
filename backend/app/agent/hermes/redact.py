"""PII / 凭据脱敏 —— 移植自 Hermes ``agent/redact.py`` 并适配等保要求。

**等保要求**：日志、记忆、委派 transcript、LLM 错误信息中的敏感数据
必须脱敏。本模块是所有敏感数据外发前的统一脱敏入口。

被以下路径调用：

- ``delegation_live_log`` —— 子代理 transcript 写文件前（文件可被沙箱读取）
- ``middleware`` —— 审计日志记录前
- ``executor`` —— LLM 错误信息回写给模型前（防错误信息回显 API Key）
- ``memory`` —— 长期记忆写入前
- ``tool_engine`` —— HTTP 工具实际请求 URL 日志（防 query 中的 token 落日志）

设计原则（与 Hermes 一致）：

1. **永不抛异常**：脱敏是安全边界，失败时 withhold 该行而非泄露原文。
2. **保守优先**：宁可误脱敏（影响可读性）也不漏脱敏（泄露凭据）。
3. **可配置**：``force=True`` 即使全局开关关闭也脱敏（安全边界场景）。
4. **保留可用性**：脱敏后保留前缀/后缀若干字符便于辨识，中间用 ``***`` 替代。

SOAR 适配：

- IP 地址默认**不脱敏**（安全运营场景 IP 是核心数据），但可配置脱敏
- 新增火山引擎 / 通义 / 智谱 / 月之暗面 等国产 LLM API Key 模式
- 新增 SOAR 平台自身的 JWT token 模式
"""
from __future__ import annotations

import re
from typing import Optional

__all__ = [
    "redact_sensitive_text",
    "redact_url_credentials",
    "redact_headers",
    "REDACTED_PLACEHOLDER",
]


REDACTED_PLACEHOLDER = "[REDACTED]"


# ─── 凭据模式 ────────────────────────────────────────────────────

# API Key 类（长字符串，前缀 + 至少 20 字符）
# 覆盖：OpenAI (sk-)、Anthropic (sk-ant-)、火山引擎、通义、智谱、月之暗面、yunaq 等
_API_KEY_PATTERNS: list[tuple[re.Pattern, str]] = [
    # OpenAI
    (re.compile(r'sk-[A-Za-z0-9]{20,}'), "sk-***"),
    # Anthropic
    (re.compile(r'sk-ant-[A-Za-z0-9_-]{20,}'), "sk-ant-***"),
    # 火山引擎 / 豆包
    (re.compile(r'(?i)volc[a-z]*-sk-[A-Za-z0-9]{16,}'), "volc-sk-***"),
    # 通义千问
    (re.compile(r'sk-[a-f0-9]{32,}'), "sk-***"),
    # 智谱 GLM
    (re.compile(r'[a-f0-9]{32}\.[a-zA-Z0-9]{16}'), "***.***"),
    # 月之暗面
    (re.compile(r'sk-moonshot-[A-Za-z0-9]{20,}'), "sk-moonshot-***"),
    # 通用：xxx-ak / xxx-sk 前缀
    (re.compile(r'(?i)\b[a-z]{2,10}-(?:ak|sk)-[A-Za-z0-9]{16,}'), "***-***"),
]

# Bearer token（Authorization 头）
_BEARER_PATTERN = re.compile(
    r'(?i)(bearer\s+)([A-Za-z0-9_-]{20,})',
)

# JWT token（三段式 xxx.yyy.zzz，每段 base64url）
_JWT_PATTERN = re.compile(
    r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'
)

# connection string 中的 password
_CONN_STRING_PASSWORD_PATTERN = re.compile(
    r'(?i)(postgresql?|mysql|mongodb|redis|amqp)://([^:]+):([^@]+)@'
)

# password/key/secret/token = "xxx" 形式（key=value）
_KV_SECRET_PATTERN = re.compile(
    r'(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|'
    r'secret[_-]?key|auth[_-]?token|access[_-]?token|refresh[_-]?token|'
    r'client[_-]?secret|private[_-]?key)\s*[:=]\s*["\']?([^\s"\',;]{8,})["\']?'
)

# AWS 凭据
_AWS_ACCESS_KEY_PATTERN = re.compile(r'\bAKIA[0-9A-Z]{16}\b')
_AWS_SECRET_PATTERN = re.compile(r'(?i)aws[_-]?secret[_-]?access[_-]?key["\']?\s*[:=]\s*["\']?([A-Za-z0-9/+=]{40})["\']?')

# 私钥 PEM 块
_PRIVATE_KEY_PATTERN = re.compile(
    r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----',
    re.MULTILINE,
)

# 信用卡号（16 位，可选空格/连字符分组）
_CREDIT_CARD_PATTERN = re.compile(
    r'\b(?:\d[ -]*?){13,16}\b'
)

# 邮箱（用于 PII 脱敏，可配置）
_EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

# 中国手机号
_CN_PHONE_PATTERN = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')

# 中国身份证号（18 位，最后一位可为 X）
_CN_ID_CARD_PATTERN = re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)')


def redact_sensitive_text(
    text: str,
    *,
    force: bool = False,
    redact_pii: bool = False,
    redact_ip: bool = False,
) -> str:
    """脱敏文本中的凭据与 PII。

    Args:
        text: 原始文本
        force: 即使全局开关关闭也脱敏（安全边界场景，如委派 transcript）
        redact_pii: 是否脱敏 PII（邮箱、手机、身份证）。默认关闭，
                    SOAR 场景日志通常需要这些信息。
        redact_ip: 是否脱敏 IP。默认关闭，SOAR 场景 IP 是核心数据。

    Returns:
        脱敏后的文本。永不抛异常；失败时返回空串（宁失勿泄）。
    """
    if not text:
        return text

    try:
        result = text

        # API Keys
        for pattern, replacement in _API_KEY_PATTERNS:
            result = pattern.sub(replacement, result)

        # Bearer token
        result = _BEARER_PATTERN.sub(r'\1***', result)

        # JWT
        result = _JWT_PATTERN.sub(REDACTED_PLACEHOLDER, result)

        # Connection string password
        result = _CONN_STRING_PASSWORD_PATTERN.sub(
            lambda m: f'{m.group(1)}://{m.group(2)}:{REDACTED_PLACEHOLDER}@',
            result,
        )

        # key=value 形式的密钥
        result = _KV_SECRET_PATTERN.sub(
            lambda m: f'{m.group(1)}={REDACTED_PLACEHOLDER}',
            result,
        )

        # AWS
        result = _AWS_ACCESS_KEY_PATTERN.sub(REDACTED_PLACEHOLDER, result)
        result = _AWS_SECRET_PATTERN.sub(
            lambda m: m.group(0).replace(m.group(1), REDACTED_PLACEHOLDER),
            result,
        )

        # 私钥 PEM
        result = _PRIVATE_KEY_PATTERN.sub(f'{REDACTED_PLACEHOLDER}[PRIVATE KEY]', result)

        # 信用卡
        result = _CREDIT_CARD_PATTERN.sub(REDACTED_PLACEHOLDER, result)

        # PII（可选）
        if redact_pii:
            result = _EMAIL_PATTERN.sub('[EMAIL]', result)
            result = _CN_PHONE_PATTERN.sub('[PHONE]', result)
            result = _CN_ID_CARD_PATTERN.sub('[IDCARD]', result)

        # IP（可选，SOAR 默认不脱敏）
        if redact_ip:
            result = _IPV4_PATTERN.sub('[IP]', result)

        return result
    except Exception:
        # 脱敏失败：宁失勿泄
        return REDACTED_PLACEHOLDER


_IPV4_PATTERN = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')


def redact_url_credentials(url: str) -> str:
    """脱敏 URL 中的 query 参数凭据（如 ?api_key=xxx & token=yyy）。

    用于 HTTP 工具请求日志：记录"实际请求 URL"时必须脱敏 query 中的敏感参数，
    防止日志泄露凭据（如 yunaq 的 API-TOKEN 若误放 query）。
    """
    if not url:
        return url
    try:
        # 脱敏 URL 中的 userinfo
        result = _CONN_STRING_PASSWORD_PATTERN.sub(
            lambda m: f'{m.group(1)}://{m.group(2)}:{REDACTED_PLACEHOLDER}@',
            url,
        )
        # 脱敏 query 中的敏感参数
        sensitive_query_params = re.compile(
            r'(?i)([?&](?:api[_-]?key|token|access[_-]?token|secret|password|passwd|'
            r'api[_-]?secret|client[_-]?secret|refresh[_-]?token|api[_-]?token)=)([^&]+)',
        )
        result = sensitive_query_params.sub(r'\1' + REDACTED_PLACEHOLDER, result)
        return result
    except Exception:
        return REDACTED_PLACEHOLDER


def redact_headers(headers: dict | None) -> dict:
    """脱敏 HTTP headers 中的敏感值。

    用于 HTTP 工具请求日志：记录"实际请求头"时脱敏 Authorization / API-Key 等。
    保留 header 名和值的前缀（如 ``Bearer ***``）便于调试。
    """
    if not headers:
        return headers or {}
    sensitive_header_names = {
        'authorization', 'api-key', 'apikey', 'api_key', 'x-api-key',
        'x-auth-token', 'x-api-token', 'api-token', 'cookie', 'set-cookie',
        'proxy-authorization', 'x-csrf-token', 'x-xsrf-token',
    }
    redacted = {}
    try:
        for k, v in headers.items():
            if k.lower() in sensitive_header_names:
                if v is None:
                    redacted[k] = None
                else:
                    s = str(v)
                    # 保留前缀（如 "Bearer "）+ ***
                    if ' ' in s:
                        prefix = s.split(' ', 1)[0]
                        redacted[k] = f'{prefix} ***'
                    else:
                        redacted[k] = REDACTED_PLACEHOLDER
            else:
                # 值本身可能含凭据（如自定义头值里嵌了 token）
                redacted[k] = redact_sensitive_text(str(v)) if v is not None else v
        return redacted
    except Exception:
        return {k: REDACTED_PLACEHOLDER for k in (headers or {})}
