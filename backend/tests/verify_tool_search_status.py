"""验证 GET /agents/{id}/tool-search-status 端点"""
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
print(f'[1] 登录: {status}')
assert status == 200
token = data['access_token']

# 2. 查询 agents
status, agents = api('GET', '/agents', token=token)
print(f'[2] 查询 agents: {status}, 共 {len(agents)} 个')
for a in agents:
    print(f'    id={a["id"]}, name={a["name"]}, engine={a.get("engine","?")}, enabled_tools={a.get("enabled_tools")}')

# 3. 找一个 hermes 引擎的 agent 测试（如果没有，用任意一个）
test_agent = next((a for a in agents if (a.get('engine') or 'hermes') == 'hermes'), agents[0])
agent_id = test_agent['id']
print(f'[3] 选中 agent: id={agent_id}, name={test_agent["name"]}, engine={test_agent.get("engine","?")}')

# 4. 调用 tool-search-status 端点
status, result = api('GET', f'/agents/{agent_id}/tool-search-status', token=token)
print(f'[4] tool-search-status: {status}')
if status != 200:
    print(f'    失败: {result}')
    raise SystemExit(1)

print(f'    supported: {result.get("supported")}')
print(f'    config: {result.get("config")}')
stats = result.get('stats', {})
print(f'    stats.visible_count: {stats.get("visible_count")}')
print(f'    stats.deferrable_count: {stats.get("deferrable_count")}')
print(f'    stats.visible_tokens: {stats.get("visible_tokens")}')
print(f'    stats.deferrable_tokens: {stats.get("deferrable_tokens")}')
print(f'    stats.would_activate: {stats.get("would_activate")}')
print(f'    stats.activated: {stats.get("activated")}')

classification = result.get('classification', {})
print(f'    classification.visible: {len(classification.get("visible", []))} 个')
print(f'    classification.deferrable: {len(classification.get("deferrable", []))} 个')
print(f'    visible_by_source: {list(classification.get("visible_by_source", {}).keys())}')
print(f'    deferrable_by_source: {list(classification.get("deferrable_by_source", {}).keys())}')

# 5. 打印详细工具分类
print()
print('── 核心工具（visible）──')
for src, group in classification.get('visible_by_source', {}).items():
    tool_names = [t['name'] for t in group.get('tools', [])]
    print(f'  [{src}] {group["count"]} 个 / {group["tokens"]} token: {tool_names}')

print('── 可延迟工具（deferrable）──')
for src, group in classification.get('deferrable_by_source', {}).items():
    tool_names = [t['name'] for t in group.get('tools', [])]
    print(f'  [{src}] {group["count"]} 个 / {group["tokens"]} token: {tool_names}')

# 6. 断言关键字段
assert result.get('supported') is True, 'supported 应为 True（hermes 引擎）'
assert 'config' in result, 'config 字段缺失'
cfg = result['config']
assert cfg['enabled'] in ('auto', 'on', 'off'), f'enabled 值异常: {cfg["enabled"]}'
assert 0 <= cfg['threshold_pct'] <= 100, f'threshold_pct 越界: {cfg["threshold_pct"]}'
assert 'classification' in result, 'classification 字段缺失'
assert 'stats' in result, 'stats 字段缺失'
assert 'source_catalog' in result, 'source_catalog 字段缺失'
assert isinstance(result['source_catalog']['core_sources'], list), 'core_sources 应为列表'
assert isinstance(result['source_catalog']['deferrable_sources'], list), 'deferrable_sources 应为列表'

print()
print('=' * 60)
print('✅ tool-search-status 端点验证全部通过！')
print('=' * 60)
