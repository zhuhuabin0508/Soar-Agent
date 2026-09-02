"""OTP 二次验证（TOTP）核心模块。

基于 pyotp 实现 RFC 6238 TOTP 算法，兼容 Google Authenticator / Microsoft
Authenticator 等主流 OTP 应用。

安全设计：
- 密钥使用 pyotp 随机生成（base32 编码，32 字符）
- 存储时使用 XOR + base64 对称加密（复用 security.encrypt_env_value）
- 二维码以 otpauth:// URI 编码，前端可直接渲染为 <img>
- 验证时先解密密钥再校验 6 位动态码
"""
import base64
import hashlib
import io
import logging
from typing import Optional

import pyotp
import qrcode

from app.core.security import encrypt_env_value, decrypt_env_value
from app.config import settings

logger = logging.getLogger(__name__)

# OTP 应用名称（显示在 Authenticator 中）
_OTP_ISSUER = "SOAR-Platform"


def generate_otp_secret() -> str:
    """生成随机 TOTP 密钥（base32 编码，32 字符）。"""
    return pyotp.random_base32()


def encrypt_otp_secret(secret: str) -> str:
    """加密 OTP 密钥后存储（复用环境变量加密方案）。"""
    return encrypt_env_value(secret)


def decrypt_otp_secret(cipher: Optional[str]) -> str:
    """解密存储的 OTP 密钥。"""
    return decrypt_env_value(cipher)


def build_otpauth_uri(username: str, secret: str) -> str:
    """构造 otpauth:// URI，供二维码扫码导入 Authenticator。

    格式：otpauth://totp/<Issuer>:<account>?secret=<secret>&issuer=<Issuer>&digits=6&period=30
    """
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=_OTP_ISSUER,
    )


def generate_qr_code_base64(uri: str) -> str:
    """将 otpauth:// URI 生成为二维码图片，返回 data URL（base64 PNG）。

    前端可直接 <img src="data:image/png;base64,..." /> 渲染。
    """
    img = qrcode.make(uri)
    # 增加边距与尺寸，便于手机扫描
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def verify_otp_code(cipher_secret: Optional[str], code: str) -> bool:
    """验证 6 位 OTP 动态码。

    Args:
        cipher_secret: 加密后的 OTP 密钥（数据库中存储的值）。
        code: 用户输入的 6 位动态码。

    Returns:
        True 验证通过，False 验证失败。
    """
    if not cipher_secret or not code:
        return False
    secret = decrypt_otp_secret(cipher_secret)
    if not secret:
        return False
    totp = pyotp.TOTP(secret)
    # valid_window=1 允许前后 30 秒时间漂移（共 90 秒窗口）
    return totp.verify(code, valid_window=1)
