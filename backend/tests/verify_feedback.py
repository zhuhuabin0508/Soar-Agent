# -*- coding: utf-8 -*-
"""反馈（系统 BUG 与优化建议）后端功能端到端验证脚本。

流程（只读 + 自建数据，不破坏现有数据）：
1. admin 登录（验证码经 Redis 读取，仅开发环境可用）
2. 创建临时 viewer 用户并用其登录
3. viewer 提交完整 BUG 反馈（含复现步骤）
4. 验证 BUG 缺复现步骤被 400 拒绝
5. 验证 XSS 过滤（标题中的 <script> 被转义）
6. 验证提交频率限制（1 小时 10 次，第 11 次 429）
7. 权限验证：viewer 访问管理列表 403
8. admin 列表 / viewer 我的反馈 / 详情 / 编辑 / 附件上传下载与非法类型拒绝
9. admin 回复 + 改状态（含非法流转 400）
10. 通知验证：admin 收"收到新反馈/反馈已重新打开"，viewer 收"您的反馈有新回复/状态已更新"（psql 查库，viewer 无通知 API 权限）
11. 完结不可编辑、reopen 闭环、批量操作
12. 清理临时用户

执行: python3 backend/tests/verify_feedback.py（宿主机需可访问 localhost:8002 与 docker）
"""
import json
import subprocess
import sys
import time

import requests

BASE = "http://localhost:8002/api/v1"
ADMIN_USER = "admin"
ADMIN_PASS = "PIGskate123"
TEST_USERNAME = "fb_verify_tmp"
TEST_PASSWORD = "FbTest#2026"

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


def login(username, password):
    """登录获取 token：图形验证码答案从 Redis 读取（开发环境专用）。"""
    _, cap = api("GET", "/auth/captcha")
    captcha_id = cap["captcha_id"]
    out = subprocess.check_output(
        ["docker", "exec", "soar-redis", "redis-cli", "--raw", "GET", f"captcha:{captcha_id}"]
    ).decode().strip()
    if not out:
        raise RuntimeError("无法从 Redis 读取验证码答案")
    status, data = api("POST", "/auth/login", body={
        "username": username,
        "password": password,
        "captcha_id": captcha_id,
        "captcha_code": out,
    })
    if status != 200 or not data.get("access_token"):
        raise RuntimeError(f"登录失败: {status} {data}")
    return data["access_token"], data["user"]["id"]


def psql_query(sql):
    """只读查询 soar_dev 库（用 subprocess 调 docker exec psql）。"""
    out = subprocess.check_output(
        ["docker", "exec", "soar-postgres", "psql", "-U", "postgres", "-d", "soar_dev",
         "-t", "-A", "-c", sql]
    ).decode().strip()
    return [line for line in out.split("\n") if line]


def main():
    print("=" * 70)
    print("[1] admin 登录")
    admin_token, admin_uid = login(ADMIN_USER, ADMIN_PASS)
    check("admin 登录成功", bool(admin_token))

    # 清理历史遗留的临时用户（幂等）
    status, users = api("GET", "/users", admin_token)
    stale = next((u for u in users if u["username"] == TEST_USERNAME), None)
    if stale:
        api("DELETE", f"/users/{stale['id']}", admin_token)
        print(f"  已清理历史遗留临时用户 id={stale['id']}")

    print("[2] 创建临时 viewer 用户并登录")
    status, body = api("POST", "/users", admin_token, body={
        "username": TEST_USERNAME,
        "password": TEST_PASSWORD,
        "display_name": "反馈验证临时用户",
        "role": "viewer",
    })
    check("创建 viewer 用户", status == 201, f"status={status} body={body}")
    viewer_uid = body["id"]
    viewer_token, _ = login(TEST_USERNAME, TEST_PASSWORD)
    check("viewer 登录成功", bool(viewer_token))

    marker = f"verifyfb{int(time.time())}"

    print("[3] viewer 提交完整 BUG 反馈")
    bug_body = {
        "type": "bug",
        "title": f"{marker} 仪表盘图表加载失败",
        "module": "仪表盘",
        "priority": "high",
        "description": "打开安全大盘页面后，攻击趋势图表偶发空白",
        "reproduce_steps": "1. 登录平台 2. 进入安全大盘 3. 切换时间范围为 7 天",
        "expected_result": "图表正常渲染近 7 天数据",
        "actual_result": "图表空白，控制台报 TypeError",
        "contact": "fb-verify@example.com",
        "page_title": "安全大盘",
        "page_url": "/dashboard",
    }
    status, fb = api("POST", "/feedbacks", viewer_token, body=bug_body)
    check("提交 BUG 反馈 201", status == 201, f"status={status} body={fb}")
    fid = fb["id"]
    check("创建后状态 pending", fb.get("status") == "pending")
    check("详情含提交人用户名", fb.get("user_username") == TEST_USERNAME)
    check("历史含 created 动作", any(h["action"] == "created" for h in fb.get("histories", [])))

    print("[4] BUG 缺复现步骤被 400 拒绝")
    bad_bug = {k: v for k, v in bug_body.items() if k != "reproduce_steps"}
    bad_bug["title"] = f"{marker} 缺复现步骤的BUG"
    status, body = api("POST", "/feedbacks", viewer_token, body=bad_bug)
    check("缺复现步骤返回 400", status == 400, f"status={status} body={body}")
    check("400 提示含必填字段", "复现步骤" in str(body))

    print("[5] XSS 过滤验证")
    status, xss_fb = api("POST", "/feedbacks", viewer_token, body={
        "type": "suggestion",
        "title": f"{marker} <script>alert(1)</script> 建议",
        "description": "希望支持 <img src=x onerror=alert(2)> 导出",
    })
    check("XSS 反馈提交 201", status == 201, f"status={status} body={xss_fb}")
    xss_fid = xss_fb.get("id")
    check("标题中 script 标签被转义", "&lt;script&gt;" in xss_fb.get("title", ""), xss_fb.get("title"))

    print("[6] 频率限制（1 小时最多 10 次，已成功 2 次）")
    ok_count = 2
    last_status = None
    for i in range(9):  # 再提交 9 次：第 8 次凑满 10，第 9 次应 429
        status, body = api("POST", "/feedbacks", viewer_token, body={
            "type": "suggestion",
            "title": f"{marker} 频率测试第{i + 3}条",
            "description": "频率限制验证用的临时反馈",
        })
        last_status = status
        if status == 201:
            ok_count += 1
        else:
            break
    check("前 10 次提交均成功", ok_count == 10, f"ok_count={ok_count}")
    check("第 11 次提交返回 429", last_status == 429, f"last_status={last_status}")
    check("429 提示语正确", "提交过于频繁" in str(body), body)

    print("[7] 权限验证：viewer 访问管理列表 403")
    status, body = api("GET", "/feedbacks", viewer_token)
    check("viewer 访问管理列表 403", status == 403, f"status={status}")

    print("[8] admin 列表 + viewer 我的反馈 + 详情 + 编辑 + 附件")
    status, lst = api("GET", "/feedbacks", admin_token, params={"keyword": marker})
    check("admin 列表 200", status == 200)
    ids_in_list = [it["id"] for it in lst.get("items", [])]
    check("列表含目标反馈", fid in ids_in_list)
    item = next((it for it in lst["items"] if it["id"] == fid), {})
    check("列表项含提交人用户名", item.get("user_username") == TEST_USERNAME, item.get("user_username"))

    status, mine = api("GET", "/feedbacks/mine", viewer_token, params={"type": "bug"})
    check("我的反馈 200", status == 200)
    mine_item = next((it for it in mine.get("items", []) if it["id"] == fid), {})
    check("我的反馈按类型筛选到目标", bool(mine_item))
    check("我的反馈含 history_count", mine_item.get("history_count", 0) >= 1, mine_item.get("history_count"))

    status, detail = api("GET", f"/feedbacks/{fid}", viewer_token)
    check("viewer 查看自己反馈详情 200", status == 200)
    check("详情历史含 operator 用户名",
          all(h.get("operator_username") for h in detail.get("histories", [])),
          detail.get("histories"))

    status, updated = api("PUT", f"/feedbacks/{fid}", viewer_token, body={"priority": "urgent"})
    check("提交人编辑反馈 200", status == 200, f"status={status}")
    check("优先级已更新", updated.get("priority") == "urgent")
    check("历史含 edit 动作", any(h["action"] == "edit" for h in updated.get("histories", [])))

    # 附件：txt 上传 + 下载 + 非法扩展名拒绝 + 路径穿越拒绝
    files = {"file": ("复现日志.txt", "step1 error\nstep2 blank chart".encode("utf-8"), "text/plain")}
    r = requests.post(f"{BASE}/feedbacks/{fid}/attachments", files=files,
                      headers={"Authorization": f"Bearer {viewer_token}"}, timeout=15)
    check("上传 txt 附件 201", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    att = r.json() if r.status_code == 201 else {}
    check("附件返回 url", att.get("url", "").startswith(f"/api/v1/feedbacks/{fid}/attachments/"), att)

    status, detail = api("GET", f"/feedbacks/{fid}", viewer_token)
    check("详情附件清单已更新", len(detail.get("attachments", [])) == 1, detail.get("attachments"))

    saved_name = att.get("url", "").rsplit("/", 1)[-1]
    status, _ = api("GET", f"/feedbacks/{fid}/attachments/{saved_name}", viewer_token)
    check("下载附件 200", status == 200, f"status={status}")
    status, _ = api("GET", f"/feedbacks/{fid}/attachments/..%2F..%2Fetc%2Fpasswd", viewer_token)
    check("路径穿越文件名被拒绝", status in (400, 404), f"status={status}")

    files = {"file": ("evil.sh", b"#!/bin/sh\nrm -rf /", "application/x-sh")}
    r = requests.post(f"{BASE}/feedbacks/{fid}/attachments", files=files,
                      headers={"Authorization": f"Bearer {viewer_token}"}, timeout=15)
    check("可执行文件被 400 拒绝", r.status_code == 400, f"{r.status_code}")
    check("拒绝提示为不支持的文件类型", "不支持的文件类型" in str(r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text))

    print("[9] admin 回复 + 状态流转")
    status, replied = api("POST", f"/feedbacks/{fid}/replies", admin_token, body={
        "content": "已定位为图表组件数据源为空时未判空，下版本修复。",
        "new_status": "processing",
    })
    check("admin 回复 200", status == 200, f"status={status} body={replied}")
    check("回复后状态 processing", replied.get("status") == "processing")
    check("历史含 reply 动作", any(h["action"] == "reply" for h in replied.get("histories", [])))

    status, body = api("PUT", f"/feedbacks/{fid}/status", admin_token, body={"status": "pending"})
    check("非法流转 processing→pending 返回 400", status == 400, f"status={status}")
    check("非法流转提示", "非法的状态流转" in str(body), body)

    status, resolved = api("PUT", f"/feedbacks/{fid}/status", admin_token, body={"status": "resolved"})
    check("合法流转 processing→resolved 200", status == 200)
    check("状态已变为 resolved", resolved.get("status") == "resolved")

    print("[10] 通知验证")
    status, notif = api("GET", "/notifications", admin_token, params={"limit": 100})
    admin_titles = [n["title"] for n in notif.get("notifications", []) if n.get("related_id") == fid]
    check("admin 收到新反馈通知", "收到新反馈" in " ".join(admin_titles), admin_titles)

    # viewer 无通知 API 权限，直接查库（只读）
    rows = psql_query(
        f"SELECT title FROM notifications WHERE user_id={viewer_uid} AND related_id={fid} ORDER BY id"
    )
    check("提交人收到回复通知", "您的反馈有新回复" in rows, rows)
    check("提交人收到状态更新通知", "您的反馈状态已更新" in rows, rows)

    print("[11] 完结不可编辑 + reopen 闭环 + 批量操作")
    status, body = api("PUT", f"/feedbacks/{fid}", viewer_token, body={"title": f"{marker} 已完结后编辑"})
    check("resolved 状态编辑被 400 拒绝", status == 400, f"status={status}")
    check("完结不可编辑提示", "不可编辑" in str(body), body)

    status, body = api("POST", f"/feedbacks/{fid}/reopen", viewer_token)
    check("提交人 reopen resolved 反馈 200", status == 200, f"status={status} body={body}")
    check("reopen 后状态 pending", (body or {}).get("status") == "pending")

    status, body = api("POST", f"/feedbacks/{fid}/reopen", viewer_token)
    check("pending 状态 reopen 被 400 拒绝", status == 400, f"status={status}")

    status, batch = api("POST", "/feedbacks/batch", admin_token,
                        body={"ids": [fid, xss_fid], "action": "close"})
    check("批量关闭 200", status == 200, f"status={status} body={batch}")
    check("批量关闭数量为 2", batch.get("updated") == 2, batch)

    status, detail = api("GET", f"/feedbacks/{fid}", viewer_token)
    check("批量关闭后状态 closed", detail.get("status") == "closed")

    status, body = api("POST", f"/feedbacks/{fid}/reopen", viewer_token)
    check("closed 状态 reopen 200", status == 200)
    check("reopen 后状态回到 pending", (body or {}).get("status") == "pending")

    rows = psql_query(
        f"SELECT title FROM notifications WHERE user_id={viewer_uid} AND related_id={fid} ORDER BY id"
    )
    check("批量操作已通知提交人", rows.count("您的反馈状态已更新") >= 2, rows)
    admin_rows = psql_query(
        f"SELECT title FROM notifications WHERE user_id={admin_uid} AND related_id={fid} ORDER BY id"
    )
    check("admin 收到重新打开通知", "反馈已重新打开" in admin_rows, admin_rows)

    print("[12] 清理临时用户")
    status, _ = api("DELETE", f"/users/{viewer_uid}", admin_token)
    check("删除临时用户 204", status == 204, f"status={status}")

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
