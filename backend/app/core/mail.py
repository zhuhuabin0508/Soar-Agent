"""SMTP 邮件发送（登录 OTP 等系统邮件）。

配置来自 SystemConfig 的 ``security.smtp_*`` 键。
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def load_smtp_config(db: Session) -> Optional[dict]:
    """从系统设置读取 SMTP 配置。

    Returns:
        host/port/username/password/from_email/use_ssl；
        缺 host/username/password 任一项则返回 None。
    """
    from app.models.system_config import SystemConfig

    cfgs = (
        db.query(SystemConfig)
        .filter(SystemConfig.key.like("security.smtp_%"))
        .all()
    )
    m = {c.key: (c.value or "").strip() for c in cfgs}
    if not (m.get("security.smtp_host") and m.get("security.smtp_username")
            and m.get("security.smtp_password")):
        return None
    try:
        port = int(m.get("security.smtp_port") or 465)
    except ValueError:
        port = 465
    use_ssl_raw = m.get("security.smtp_ssl")
    use_ssl = (use_ssl_raw.lower() in ("true", "1", "yes", "on")) if use_ssl_raw else (port == 465)
    return {
        "host": m["security.smtp_host"],
        "port": port,
        "username": m["security.smtp_username"],
        "password": m["security.smtp_password"],
        "from_email": m.get("security.smtp_from") or m["security.smtp_username"],
        "use_ssl": use_ssl,
    }


def smtp_dict_from_fields(
    host: str,
    port: int,
    username: str,
    password: str,
    from_email: str = "",
    use_ssl: Optional[bool] = None,
) -> Optional[dict]:
    """用表单字段组装 SMTP 配置（测试连接用）。"""
    host = (host or "").strip()
    username = (username or "").strip()
    password = (password or "").strip()
    if not (host and username and password):
        return None
    if use_ssl is None:
        use_ssl = int(port or 465) == 465
    return {
        "host": host,
        "port": int(port or 465),
        "username": username,
        "password": password,
        "from_email": (from_email or "").strip() or username,
        "use_ssl": bool(use_ssl),
    }


def send_mail(smtp: dict, to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """发送纯文本邮件。

    Returns:
        (成功?, 错误信息；成功时为空串)
    """
    to_email = (to_email or "").strip()
    if not to_email:
        return False, "收件邮箱为空"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp["from_email"]
    msg["To"] = to_email

    try:
        context = ssl.create_default_context()
        port = int(smtp["port"])
        if smtp["use_ssl"]:
            server = smtplib.SMTP_SSL(smtp["host"], port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(smtp["host"], port, timeout=15)
            if port == 587:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
        try:
            server.login(smtp["username"], smtp["password"])
            server.sendmail(smtp["from_email"], [to_email], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP 认证失败：请确认已开启 SMTP，并使用授权码（不是登录密码）"
    except Exception as exc:  # noqa: BLE001
        logger.warning("邮件发送失败: to=%s, host=%s, error=%s", to_email, smtp.get("host"), exc)
        return False, str(exc)


def send_otp_email(smtp: dict, to_email: str, code: str) -> bool:
    """发送登录验证码邮件。成功返回 True。"""
    ok, err = send_mail(
        smtp,
        to_email,
        "SOAR 平台登录验证码",
        f"您的登录验证码为：{code}，5 分钟内有效。请勿泄露给他人。",
    )
    if not ok:
        logger.warning("OTP 验证码邮件发送失败: to=%s, host=%s, error=%s", to_email, smtp.get("host"), err)
    return ok
