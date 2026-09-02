"""C-12 API 验证脚本：登录 → 查询 agents → 更新 tool_configs → 验证持久化"""
import json
import urllib.request

BASE = 'http://localhost:8000/api/v1'


def api(method, path, token=None, body=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f'{BASE}{path}', data=data, headers=headers, method=method
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read()) if resp.length else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()) if e.length else None


# 1. 登录
status, data = api('POST', '/auth/login', body={'username': 'admin', 'password': 'admin123'})
print(f'[1] 登录: {status}')
assert status == 200, '登录失败'
token = data['access_token']

# 2. 查询 agents
status, agents = api('GET', '/agents', token=token)
print(f'[2] 查询 agents: {status}, 共 {len(agents)} 个')
if not agents:
    print('    无 agent，跳过验证')
    raise SystemExit(0)

agent = agents[0]
agent_id = agent['id']
print(f'    选中 agent: id={agent_id}, name={agent["name"]}, engine={agent.get("engine", "?")}')
print(f'    原 tool_configs: {agent.get("tool_configs")}')

# 3. 构造完整的 C-12 tool_configs 测试数据
test_tool_configs = {
    'guardrails': {
        'warnings_enabled': True,
        'hard_stop_enabled': True,
        'warn_after': {
            'exact_failure': 3,
            'same_tool_failure': 4,
            'idempotent_no_progress': 2,
        },
        'hard_stop_after': {
            'exact_failure': 6,
            'same_tool_failure': 10,
            'idempotent_no_progress': 5,
        },
    },
    'verification': {
        'verify_block_ip': True,
        'require_threat_intel': True,
        'verify_device_action': True,
        'verify_send_notification': False,
        'verify_trigger_workflow': True,
    },
    'middlewares': [
        {'name': 'audit', 'config': {}},
        {'name': 'redact'},
        {'name': 'rate_limit', 'config': {'max_calls_per_minute': 30}},
        {'name': 'timing'},
    ],
}

# 4. 更新 agent（带新 tool_configs）
update_body = {**agent, 'tool_configs': test_tool_configs}
# 清掉只读字段
for k in ('id', 'created_at', 'updated_at'):
    update_body.pop(k, None)
# 转换 enabled_kbs/enabled_skills 为 int 数组
update_body['enabled_kbs'] = [int(x) for x in (agent.get('enabled_kbs') or [])]
update_body['enabled_skills'] = [int(x) for x in (agent.get('enabled_skills') or [])]

status, updated = api('PUT', f'/agents/{agent_id}', token=token, body=update_body)
print(f'[3] 更新 agent: {status}')
if status != 200:
    print(f'    失败响应: {updated}')
    raise SystemExit(1)

# 5. 重新查询验证持久化（GET /agents 返回列表，从中查找）
status, agents_after = api('GET', '/agents', token=token)
print(f'[4] 重新查询列表: {status}, 共 {len(agents_after)} 个')
refreshed = next((a for a in agents_after if a['id'] == agent_id), None)
assert refreshed is not None, f'未在列表中找到 agent id={agent_id}'
saved_tc = refreshed.get('tool_configs') or {}
print(f'    保存的 tool_configs:')
print(f'      guardrails.warnings_enabled = {saved_tc.get("guardrails", {}).get("warnings_enabled")}')
print(f'      guardrails.hard_stop_enabled = {saved_tc.get("guardrails", {}).get("hard_stop_enabled")}')
print(f'      guardrails.warn_after = {saved_tc.get("guardrails", {}).get("warn_after")}')
print(f'      guardrails.hard_stop_after = {saved_tc.get("guardrails", {}).get("hard_stop_after")}')
print(f'      verification = {saved_tc.get("verification")}')
print(f'      middlewares = {saved_tc.get("middlewares")}')

# 6. 断言关键字段已持久化
g = saved_tc.get('guardrails', {})
v = saved_tc.get('verification', {})
m = saved_tc.get('middlewares', [])
assert g.get('warnings_enabled') is True, 'guardrails.warnings_enabled 未持久化'
assert g.get('hard_stop_enabled') is True, 'guardrails.hard_stop_enabled 未持久化'
assert g.get('warn_after', {}).get('exact_failure') == 3, 'warn_after.exact_failure 未持久化'
assert g.get('hard_stop_after', {}).get('same_tool_failure') == 10, 'hard_stop_after.same_tool_failure 未持久化'
assert v.get('require_threat_intel') is True, 'verification.require_threat_intel 未持久化'
assert v.get('verify_send_notification') is False, 'verification.verify_send_notification 未持久化'
assert len(m) == 4, f'middlewares 应有 4 个，实际 {len(m)}'
mw_names = [x.get('name') for x in m]
assert 'audit' in mw_names and 'rate_limit' in mw_names, f'middlewares 名单异常: {mw_names}'
rate_limit_entry = next((x for x in m if x.get('name') == 'rate_limit'), None)
assert rate_limit_entry and rate_limit_entry.get('config', {}).get('max_calls_per_minute') == 30, \
    f'rate_limit.config 未持久化: {rate_limit_entry}'

print()
print('=' * 60)
print('✅ C-12 tool_configs 持久化验证全部通过！')
print('=' * 60)
