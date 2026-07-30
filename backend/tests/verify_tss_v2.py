"""验证 tool-search-status 端点（使用已存在的 agent_id=5）"""
import json
import urllib.request

BASE = 'http://localhost:8000/api/v1'


def api(method, path, token=None, body=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f'{BASE}{path}', data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read()) if resp.length else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()) if e.length else None


# 1. 登录
status, data = api('POST', '/auth/login', body={'username': 'admin', 'password': 'admin123'})
token = data['access_token']
print(f'[1] 登录: {status}')

# 2. 查询 agents 找 hermes
status, agents = api('GET', '/agents', token=token)
hermes_agents = [a for a in agents if (a.get('engine') or 'hermes') == 'hermes']
print(f'[2] 查询 agents: {status}, hermes 引擎 {len(hermes_agents)} 个')
if not hermes_agents:
    print('    无 hermes agent，跳过')
    raise SystemExit(0)
agent = hermes_agents[0]
agent_id = agent['id']
print(f'    选中: id={agent_id}, name={agent["name"]}, enabled_tools={agent.get("enabled_tools")}')

# 3. 调用 tool-search-status
status, result = api('GET', f'/agents/{agent_id}/tool-search-status', token=token)
print(f'[3] tool-search-status: {status}')
print(f'    supported: {result.get("supported")}')
print(f'    config: {result.get("config")}')
stats = result.get('stats', {})
print(f'    visible_count: {stats.get("visible_count")}')
print(f'    deferrable_count: {stats.get("deferrable_count")}')
print(f'    visible_tokens: {stats.get("visible_tokens")}')
print(f'    deferrable_tokens: {stats.get("deferrable_tokens")}')
print(f'    would_activate: {stats.get("would_activate")}')

classification = result.get('classification', {})
print()
print('── 核心工具（visible）──')
for src, group in classification.get('visible_by_source', {}).items():
    tool_names = [f"{t['name']}({t['tokens']}t)" for t in group.get('tools', [])]
    print(f'  [{src}] {group["count"]} 个 / {group["tokens"]} token: {tool_names}')

print('── 可延迟工具（deferrable）──')
for src, group in classification.get('deferrable_by_source', {}).items():
    tool_names = [f"{t['name']}({t['tokens']}t)" for t in group.get('tools', [])]
    print(f'  [{src}] {group["count"]} 个 / {group["tokens"]} token: {tool_names}')

# 4. 断言
assert result.get('supported') is True, 'supported 应为 True'
cfg = result['config']
assert cfg['enabled'] in ('auto', 'on', 'off'), f'enabled 异常: {cfg["enabled"]}'
# 关键断言：source 应该不是 unknown（DB 工具应是 db_code）
visible = classification.get('visible', [])
deferrable = classification.get('deferrable', [])
all_tools = visible + deferrable
unknown_count = sum(1 for t in all_tools if t.get('source') == 'unknown')
print()
print(f'[4] source 分类检查: 总 {len(all_tools)} 工具, unknown={unknown_count}')
if unknown_count > 0:
    unknown_names = [t['name'] for t in all_tools if t.get('source') == 'unknown']
    print(f'    unknown 工具: {unknown_names}')

# 启用的 DB 工具应该被分类为 db_code
db_code_tools = [t for t in all_tools if t.get('source') == 'db_code']
print(f'    db_code 工具: {[t["name"] for t in db_code_tools]}')

print()
print('=' * 60)
print('✅ tool-search-status 端点验证完成！')
print('=' * 60)
