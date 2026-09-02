"""端到端接口验证：登录 → 头像上传 → 环境变量 CRUD → 强制下线。

执行后可删除。"""
import json
import urllib.request


BASE = "http://localhost:8000/api/v1"


def _req(method, path, body=None, token=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8")
        try:
            return e.code, json.loads(text)
        except Exception:
            return e.code, text


# 1. 获取验证码
status, captcha = _req("GET", "/auth/captcha")
print(f"[captcha] status={status}, captcha_id={captcha.get('captcha_id')[:12]}...")
captcha_id = captcha["captcha_id"]
# 验证码无法在脚本中识别，但可通过开发环境跳过——这里尝试直接登录
# 若失败，提示手动测试

# 2. 尝试登录（验证码不匹配会失败，但我们看错误是否为验证码错误而非 500）
status, body = _req("POST", "/auth/login", {
    "username": "admin",
    "password": "admin123",
    "captcha_id": captcha_id,
    "captcha_code": "wrong",
})
print(f"[login wrong captcha] status={status}, body={body}")

# 3. 用 DB 直接生成 token（绕过验证码）
from app.core.security import create_access_token
from app.database import SessionLocal
from app.models.user import User

db = SessionLocal()
try:
    user = db.query(User).filter(User.username == "admin").first()
    token, jti, sid = create_access_token(user.id, user.username, user.role)
    print(f"[token] generated for user={user.username}, jti={jti[:12]}...")
finally:
    db.close()

# 4. 测试 /auth/me（应返回 avatar 字段）
status, me = _req("GET", "/auth/me", token=token)
print(f"[auth/me] status={status}, avatar field present: {'avatar' in (me or {})}")

# 5. 测试头像上传 PUT /auth/profile
status, updated = _req("PUT", "/auth/profile", {
    "avatar": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==",
}, token=token)
print(f"[profile avatar upload] status={status}, avatar returned: {(updated or {}).get('avatar', '<MISSING>')[:40]}")

# 6. 验证 /auth/me 返回新头像
status, me2 = _req("GET", "/auth/me", token=token)
print(f"[auth/me after upload] avatar={me2.get('avatar')[:40] if me2 else 'N/A'}")

# 7. 清空头像
status, cleared = _req("PUT", "/auth/profile", {"avatar": ""}, token=token)
print(f"[profile avatar clear] status={status}, avatar now: {(cleared or {}).get('avatar')!r}")

# 8. 测试工作流环境变量 CRUD
# 先创建一个临时工作流
status, wf = _req("POST", "/workflows", {
    "name": "verify_env_vars_test",
    "graph_config": {"nodes": [], "edges": []},
}, token=token)
print(f"[workflow create] status={status}, id={wf.get('id') if isinstance(wf, dict) else wf}")
wf_id = wf["id"] if isinstance(wf, dict) else None

if wf_id:
    # GET 空列表
    status, env1 = _req("GET", f"/workflows/{wf_id}/env-vars", token=token)
    print(f"[env-vars GET empty] status={status}, items={env1}")

    # PUT 设置 2 个变量
    status, env2 = _req("PUT", f"/workflows/{wf_id}/env-vars", {
        "items": [
            {"name": "api_key", "description": "测试 API Key", "value": "sk-test-12345"},
            {"name": "webhook_url", "description": "回调地址", "value": "https://example.com/hook"},
        ]
    }, token=token)
    print(f"[env-vars PUT] status={status}")
    if isinstance(env2, dict):
        for item in env2.get("items", []):
            print(f"  - name={item.get('name')}, value={item.get('value')!r}, has_value={item.get('has_value')}")

    # 验证 GET 返回掩码
    status, env3 = _req("GET", f"/workflows/{wf_id}/env-vars", token=token)
    print(f"[env-vars GET after PUT] status={status}")
    if isinstance(env3, dict):
        for item in env3.get("items", []):
            print(f"  - name={item.get('name')}, value={item.get('value')!r}, has_value={item.get('has_value')}")

    # 验证 reveal 接口返回明文
    status, rev = _req("POST", f"/workflows/{wf_id}/env-vars/reveal", {"name": "api_key"}, token=token)
    print(f"[env-vars reveal api_key] status={status}, value={rev.get('value') if isinstance(rev, dict) else rev}")

    # 验证 PUT 时 value='******' 保留原值
    status, env4 = _req("PUT", f"/workflows/{wf_id}/env-vars", {
        "items": [
            {"name": "api_key", "description": "更新描述", "value": "******"},  # 保留原值
            {"name": "new_var", "description": "新变量", "value": "new_value"},
        ]
    }, token=token)
    # 再次 reveal api_key，应仍为 sk-test-12345
    status, rev2 = _req("POST", f"/workflows/{wf_id}/env-vars/reveal", {"name": "api_key"}, token=token)
    print(f"[env-vars reveal after keep] status={status}, value={rev2.get('value') if isinstance(rev2, dict) else rev2}")

    # 清理测试工作流
    status, _ = _req("DELETE", f"/workflows/{wf_id}", token=token)
    print(f"[workflow delete] status={status}")

# 9. 测试 force-logout（尝试下线自己应失败）
status, body = _req("POST", f"/users/{user.id}/force-logout", token=token)
print(f"[force-logout self] status={status}, body={body}")

print("\nAll E2E verifications done.")
