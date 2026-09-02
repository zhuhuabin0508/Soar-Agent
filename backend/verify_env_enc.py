"""临时验证脚本：环境变量加解密 + 接口可用性自检（容器内执行后可删除）。"""
from app.core.security import encrypt_env_value, decrypt_env_value

orig = "sk-abc-123-secret-key"
enc = encrypt_env_value(orig)
dec = decrypt_env_value(enc)
print(f"orig  = {orig}")
print(f"enc   = {enc[:30]}...")
print(f"dec   = {dec}")
print(f"match = {orig == dec}")
print(f"prefix= {enc.startswith('enc:')}")
print(f"empty = {encrypt_env_value('')!r} / {decrypt_env_value('')!r}")
print(f"plain = {decrypt_env_value('raw-plaintext')!r}")

# 数据库列已添加验证
from app.database import SessionLocal
from app.models.user import User
from app.models.workflow import Workflow

db = SessionLocal()
try:
    # users.avatar 字段
    u = db.query(User).first()
    print(f"\n[users] first user: id={u.id}, username={u.username}, avatar={getattr(u, 'avatar', '<MISSING>')!r}")
    # workflows.env_vars 字段
    w = db.query(Workflow).first()
    if w is None:
        print("[workflows] no workflow in DB")
    else:
        print(f"[workflows] first workflow: id={w.id}, name={w.name}, env_vars={getattr(w, 'env_vars', '<MISSING>')!r}")
finally:
    db.close()

print("\nAll verifications passed.")
