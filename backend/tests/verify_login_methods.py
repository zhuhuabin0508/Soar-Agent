# -*- coding: utf-8 -*-
"""登录页多登录方式后端功能端到端验证脚本。

流程（自建配置 + 还原，不破坏现有数据）：
1. GET /auth/login-methods：默认三方式、配置收紧后生效
2. GET /auth/login-methods/user：admin 用户、不存在用户（防枚举返回全集）、
   用户级 allowed_login_methods 与系统启用方式的交集
3. GET /auth/sso/providers：SSO 关闭返回空、单提供商 fallback、多提供商配置
4. POST /auth/otp/send：不存在用户 200 防枚举、正常发送（dev_code 模式，验证码
   同步写入 Redis otp_login:{uid}）、60 秒单用户重发被 429
5. POST /auth/login/otp-direct：错误验证码 401 且失败计数 +1、正确验证码登录
   成功拿 token 且验证码一次性消费、成功后计数清零、不存在用户 401
6. IP 限频：login-methods/user（60s 20 次）与 captcha（60s 20 次）超限 429
7. 清理：重置 admin 失败计数、还原系统配置

执行: python3 backend/tests/verify_login_methods.py（宿主机需可访问 localhost:8002 与 docker）
"""
import subprocess
import sys

import requests

BASE = "http://localhost:8002/api/v1"
ADMIN_USER = "admin"
ADMIN_PASS = "PIGskate123"
DEFAULT_METHODS = ["password", "otp", "sso"]

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    """记录断言结果。"""
    if cond:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(name)
        print(f"  [FAIL] {name} {detail}")


def api(method, path, token=None, body=None, params=None, timeout=15):
    """调用后端 API，返回 (status_code, json/文本)。"""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(
        method, BASE + path, json=body, params=params, headers=headers, timeout=timeout
    )
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def redis_cmd(*args):
    """执行 soar-redis 容器内 redis-cli 命令。"""
    return subprocess.check_output(
        ["docker", "exec", "soar-redis", "redis-cli", "--raw", *args]
    ).decode().strip()


def psql(sql):
    """对 soar_dev 库执行 SQL（查询/更新）。"""
    return subprocess.check_output(
        ["docker", "exec", "soar-postgres", "psql", "-U", "postgres", "-d", "soar_dev",
         "-t", "-A", "-c", sql]
    ).decode().strip()


def login(username, password):
    """登录获取 token：图形验证码答案从 Redis 读取（开发环境专用）。"""
    _, cap = api("GET", "/auth/captcha")
    out = redis_cmd("GET", f"captcha:{cap['captcha_id']}")
    if not out:
        raise RuntimeError("无法从 Redis 读取验证码答案")
    status, data = api("POST", "/auth/login", body={
        "username": username,
        "password": password,
        "captcha_id": cap["captcha_id"],
        "captcha_code": out,
    })
    if status != 200 or not data.get("access_token"):
        raise RuntimeError(f"登录失败: {status} {data}")
    return data["access_token"], data["user"]["id"]


def set_security(token, configs):
    """更新等保安全配置（仅接受 security.* 已知键）。"""
    status, body = api("PUT", "/system-config/security", token, body=configs)
    return status == 200, body


def main():
    print("=" * 70)
    print("[0] admin 登录 + 环境清理（幂等，还原上次运行残留）")
    admin_token, admin_uid = login(ADMIN_USER, ADMIN_PASS)
    check("admin 登录成功", bool(admin_token))
    psql(f"UPDATE users SET failed_login_count=0, locked_until=NULL, allowed_login_methods=NULL WHERE id={admin_uid}")
    redis_cmd("DEL", f"otp_send_limit:{admin_uid}", f"otp_login:{admin_uid}")
    ok, _ = set_security(admin_token, {
        "security.login_methods": '["password", "otp", "sso"]',
        "security.sso_enabled": False,
        "security.sso_provider": "",
        "security.sso_providers": "",
    })
    check("还原系统登录方式配置", ok)

    print("[1] GET /auth/login-methods 默认三方式")
    status, data = api("GET", "/auth/login-methods")
    check("login-methods 200", status == 200, f"status={status} body={data}")
    check("默认返回三种登录方式", data.get("methods") == DEFAULT_METHODS, data)
    check("captcha_enabled 为 True", data.get("captcha_enabled") is True, data)
    check("sso_enabled 字段存在", "sso_enabled" in data, data)

    print("[2] GET /auth/login-methods/user")
    status, data = api("GET", "/auth/login-methods/user", params={"username": ADMIN_USER})
    check("admin 用户登录方式 200", status == 200, f"status={status}")
    check("admin 未配置时返回全集", data.get("methods") == DEFAULT_METHODS, data)

    status, data = api("GET", "/auth/login-methods/user", params={"username": "no_such_user_xyz"})
    check("不存在用户 200 且返回全集（防枚举）",
          status == 200 and data.get("methods") == DEFAULT_METHODS, f"status={status} body={data}")

    # 用户级 allowed_login_methods 与系统启用方式取交集（临时改库，finally 还原）
    psql(f"UPDATE users SET allowed_login_methods='[\"otp\"]' WHERE id={admin_uid}")
    try:
        status, data = api("GET", "/auth/login-methods/user", params={"username": ADMIN_USER})
        check("用户配置交集返回 ['otp']", data.get("methods") == ["otp"], data)
        status, data = api("GET", "/auth/login-methods/user", params={"username": "no_such_user_xyz"})
        check("交集测试中不存在用户仍返回系统全集", data.get("methods") == DEFAULT_METHODS, data)
    finally:
        psql(f"UPDATE users SET allowed_login_methods=NULL WHERE id={admin_uid}")

    print("[3] 系统配置 security.login_methods 收紧生效")
    ok, _ = set_security(admin_token, {"security.login_methods": '["password","otp"]'})
    check("更新 login_methods 配置成功", ok)
    status, data = api("GET", "/auth/login-methods")
    check("收紧后返回 ['password','otp']", data.get("methods") == ["password", "otp"], data)
    status, data = api("GET", "/auth/login-methods/user", params={"username": ADMIN_USER})
    check("收紧后用户可用方式同步收缩", data.get("methods") == ["password", "otp"], data)
    ok, _ = set_security(admin_token, {"security.login_methods": '["password", "otp", "sso"]'})
    status, data = api("GET", "/auth/login-methods")
    check("还原后返回三种方式", ok and data.get("methods") == DEFAULT_METHODS, data)

    print("[4] GET /auth/sso/providers")
    status, data = api("GET", "/auth/sso/providers")
    check("SSO 关闭时 providers 为空", status == 200 and data.get("providers") == [], f"status={status} body={data}")

    ok, _ = set_security(admin_token, {
        "security.sso_enabled": True, "security.sso_provider": "keycloak"})
    status, data = api("GET", "/auth/sso/providers")
    check("单提供商 fallback 生效", data.get("providers") == [
        {"id": "keycloak", "name": "Keycloak", "type": "oauth2"}], data)

    ok, _ = set_security(admin_token, {
        "security.sso_providers": '[{"id":"wecom","name":"企业微信"},{"id":"ldap"}]'})
    status, data = api("GET", "/auth/sso/providers")
    check("多提供商配置生效（含名称映射与 ldap 类型）", data.get("providers") == [
        {"id": "wecom", "name": "企业微信", "type": "oauth2"},
        {"id": "ldap", "name": "LDAP 域账号", "type": "ldap"}], data)

    status, data = api("GET", "/auth/login-methods")
    check("sso_enabled 联动返回 True", data.get("sso_enabled") is True, data)

    ok, _ = set_security(admin_token, {
        "security.sso_enabled": False, "security.sso_provider": "",
        "security.sso_providers": ""})
    status, data = api("GET", "/auth/sso/providers")
    check("还原后 providers 为空", ok and data.get("providers") == [], data)

    print("[5] POST /auth/otp/send")
    status, data = api("POST", "/auth/otp/send", body={"username": "no_such_user_xyz"})
    check("不存在用户返回 200 sent=true（防枚举）",
          status == 200 and data.get("sent") is True, f"status={status} body={data}")
    check("不存在用户不返回 dev_code", "dev_code" not in data, data)

    status, data = api("POST", "/auth/otp/send", body={"username": ADMIN_USER})
    check("admin 发送验证码 200", status == 200 and data.get("sent") is True, f"status={status} body={data}")
    dev_code = data.get("dev_code")
    check("无邮件设施时返回 dev_code（开发模式）", bool(dev_code), data)
    stored = redis_cmd("GET", f"otp_login:{admin_uid}")
    check("Redis otp_login 与 dev_code 一致", stored == dev_code, f"stored={stored} dev={dev_code}")
    ttl = redis_cmd("TTL", f"otp_login:{admin_uid}")
    check("验证码 TTL 300 秒内", 0 < int(ttl or 0) <= 300, f"ttl={ttl}")
    limit_ttl = redis_cmd("TTL", f"otp_send_limit:{admin_uid}")
    check("单用户发送限频键 60 秒内", 0 < int(limit_ttl or 0) <= 60, f"ttl={limit_ttl}")

    status, data = api("POST", "/auth/otp/send", body={"username": ADMIN_USER})
    check("60 秒内重发返回 429", status == 429, f"status={status} body={data}")
    check("429 提示 60 秒后重试", "60" in str(data.get("detail", "")), data)

    print("[6] POST /auth/login/otp-direct")
    status, data = api("POST", "/auth/login/otp-direct", body={
        "username": ADMIN_USER, "otp_code": "000000"})
    check("错误验证码返回 401", status == 401, f"status={status} body={data}")
    check("401 模糊提示（防枚举）", "用户名或验证码错误" in str(data.get("detail", "")), data)
    cnt = psql(f"SELECT failed_login_count FROM users WHERE id={admin_uid}")
    check("失败计数 +1", cnt == "1", f"failed_login_count={cnt}")

    status, data = api("POST", "/auth/login/otp-direct", body={
        "username": ADMIN_USER, "otp_code": dev_code})
    check("正确验证码登录 200 且返回 token",
          status == 200 and bool(data.get("access_token")), f"status={status} body={data}")
    check("返回用户信息", (data.get("user") or {}).get("username") == ADMIN_USER, data.get("user"))
    left = redis_cmd("GET", f"otp_login:{admin_uid}")
    check("验证码登录成功后一次性消费", left == "", f"otp_login 剩余={left!r}")
    cnt = psql(f"SELECT failed_login_count FROM users WHERE id={admin_uid}")
    check("登录成功后失败计数清零", cnt == "0", f"failed_login_count={cnt}")

    status, data = api("POST", "/auth/login/otp-direct", body={
        "username": "no_such_user_xyz", "otp_code": "123456"})
    check("不存在用户 OTP 登录 401 模糊提示",
          status == 401 and "用户名或验证码错误" in str(data.get("detail", "")),
          f"status={status} body={data}")

    status, data = api("POST", "/auth/login/otp-direct", body={
        "username": ADMIN_USER, "otp_code": "000001"})
    check("已消费的验证码再次使用返回 401", status == 401, f"status={status} body={data}")

    print("[7] IP 限频（放在最后，避免影响前面用例）")
    hit_429 = False
    for _ in range(25):
        status, _ = api("GET", "/auth/login-methods/user", params={"username": ADMIN_USER})
        if status == 429:
            hit_429 = True
            break
    check("login-methods/user IP 限频 429", hit_429)

    hit_429 = False
    detail = ""
    for _ in range(25):
        status, body = api("GET", "/auth/captcha")
        if status == 429:
            hit_429 = True
            detail = str(body)
            break
    check("captcha IP 限频 429", hit_429)
    check("captcha 429 提示请求过于频繁", "请求过于频繁" in detail, detail)

    print("[8] 清理")
    psql(f"UPDATE users SET failed_login_count=0, locked_until=NULL WHERE id={admin_uid}")
    check("admin 失败计数已重置为 0",
          psql(f"SELECT failed_login_count FROM users WHERE id={admin_uid}") == "0")

    print("=" * 70)
    print(f"验证结果: 通过 {len(PASSED)} 项, 失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项:")
        for name in FAILED:
            print(f"  - {name}")
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    main()
