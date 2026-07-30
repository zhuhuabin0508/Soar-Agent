"""限流器单例（slowapi）。

独立模块避免 main.py 与路由之间的循环导入。
路由通过 ``from app.core.limiter import limiter`` 引用，并用 ``@limiter.limit(...)`` 装饰。
要求被装饰的路由函数第一个参数为 ``request: Request``。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# key_func 使用客户端 IP 作为限流维度
limiter = Limiter(key_func=get_remote_address, default_limits=[])
