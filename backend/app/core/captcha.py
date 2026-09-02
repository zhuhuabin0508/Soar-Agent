"""图形验证码：生成 + 校验。

使用 ``captcha`` 库绘制 4 位字母数字验证码图片（base64 PNG），
验证码答案以 ``captcha:<id>`` 为键存入 Redis，默认 5 分钟过期、校验后立即删除。

设计要点：
- ``captcha_id`` 使用 ``secrets.token_urlsafe`` 生成，作为 Redis 键的一部分，难以枚举
- 校验时一次性消费（删除键），防止同一验证码被重复使用
- 大小写不敏感，提升用户体验
- 不过度依赖第三方图像库：``captcha`` 自身基于 Pillow，安装即用
"""
import base64
import io
import logging
import secrets
import uuid

from captcha.image import ImageCaptcha

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# Redis 键前缀与默认过期时间
CAPTCHA_KEY_PREFIX = "captcha:"
CAPTCHA_TTL_SECONDS = 300  # 5 分钟


def generate_captcha() -> dict:
    """生成一张图形验证码。

    返回:
        ``{"captcha_id": str, "image": "data:image/png;base64,..."}``，
        前端将 ``image`` 直接作为 ``<img src="...">`` 渲染。
    """
    image = ImageCaptcha(width=160, height=48)
    # 排除易混字符（0/O、1/I/l），降低用户输错概率
    code = _gen_code()
    # 用 uuid4 作为 captcha_id，附加随机 token 增强不可预测性
    captcha_id = f"{uuid.uuid4().hex}{secrets.token_urlsafe(8)}"
    # 绘制为 PNG 字节流
    buf = io.BytesIO()
    image.write(code, buf)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    # 存入 Redis（大小写不敏感，存储统一转小写）
    redis_client = get_redis()
    redis_client.setex(
        f"{CAPTCHA_KEY_PREFIX}{captcha_id}",
        CAPTCHA_TTL_SECONDS,
        code.lower(),
    )
    logger.debug("生成验证码: captcha_id=%s, ttl=%ds", captcha_id, CAPTCHA_TTL_SECONDS)
    return {
        "captcha_id": captcha_id,
        "image": f"data:image/png;base64,{b64}",
    }


def verify_captcha(captcha_id: str, captcha_code: str) -> bool:
    """校验验证码：通过则立即删除（一次性消费），失败则保留以便用户重试。

    Args:
        captcha_id: ``generate_captcha`` 返回的 captcha_id。
        captcha_code: 用户输入的验证码。

    Returns:
        True 表示校验通过；False 表示 captcha_id 不存在、已过期或答案错误。
    """
    if not captcha_id or not captcha_code:
        return False
    redis_client = get_redis()
    key = f"{CAPTCHA_KEY_PREFIX}{captcha_id}"
    stored = redis_client.get(key)
    if not stored:
        return False
    # 校验通过：立即删除（一次性消费，防止重放）
    if stored == captcha_code.strip().lower():
        redis_client.delete(key)
        logger.debug("验证码校验通过: captcha_id=%s", captcha_id)
        return True
    # 校验失败：保留键，用户可在过期前继续重试输入
    logger.debug("验证码校验失败: captcha_id=%s", captcha_id)
    return False


def _gen_code(length: int = 4) -> str:
    """生成指定长度的字母数字验证码，排除易混字符。"""
    import random
    import string
    # 排除 0/O、1/I/l，降低误识别
    chars = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1Il")
    return "".join(random.choices(chars, k=length))
