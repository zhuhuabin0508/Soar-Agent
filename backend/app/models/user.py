"""用户数据模型。

存储平台登录账号，支持 RBAC 角色与启用状态。
密码以 bcrypt 哈希存储，永不存明文。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, JSON, func

from app.database import Base


class User(Base):
    """用户模型，用于 JWT 登录鉴权与操作审计。

    角色（role）取值：
    - ``admin``：超级管理员，可执行所有操作（含用户管理、工具编辑）。
    - ``analyst``：安全运营人员，可编辑工作流/智能体/知识库、处理审批工单。
    - ``viewer``：只读用户，仅可查看，不可修改。
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    # bcrypt 哈希后的密码（含 salt 与版本前缀），永不存明文
    password_hash = Column(String(255), nullable=False)
    # 显示名
    display_name = Column(String(128), nullable=True)
    email = Column(String(255), nullable=True)
    # 角色：admin / analyst / viewer（向后兼容字段，新逻辑优先用 role_id）
    role = Column(String(32), nullable=False, default="analyst")
    # 关联 roles 表 ID（可配置权限矩阵），为空时 fallback 到 role 字段
    role_id = Column(Integer, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    last_login_at = Column(DateTime, nullable=True)
    # 等保安全字段：登录失败计数与锁定截止时间
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    # 个人资料扩展字段
    phone = Column(String(32), nullable=True)
    department = Column(String(128), nullable=True)
    language = Column(String(16), nullable=False, default="zh-CN")
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai")
    bio = Column(Text, nullable=True)
    # 头像 URL（支持 data URL 或上传后的文件路径）
    avatar = Column(Text, nullable=True)
    # OTP 二次验证（TOTP）：密钥加密存储，otp_enabled 标记是否已启用
    otp_secret = Column(String(255), nullable=True)
    otp_enabled = Column(Boolean, nullable=False, default=False)
    # SSO 单点登录：第三方账号唯一标识（如 OIDC sub），用于关联外部身份
    sso_subject = Column(String(255), nullable=True)
    # 允许的登录方式（JSON 数组，如 ["password", "otp", "sso"]）
    # 为空时默认允许所有方式（向后兼容）
    allowed_login_methods = Column(JSON, nullable=True)
    # 首次登录/重置密码后强制改密标记：True 时登录后必须修改密码
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="false")

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role!r}>"
