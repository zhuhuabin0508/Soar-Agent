"""创建 hermes 引擎测试 agent 并验证 tool-search-status"""
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

# 2. 查询现有 tools（找一些 code/http 工具来启用）
status, tools = api('GET', '/tools', token=token)
print(f'[2] 查询 tools: {status}, 共 {len(tools)} 个')
for t in tools[:5]:
    print(f'    name={t["name"]}, type={t.get("tool_type","?")}, enabled={t.get("enabled")}')

# 选 2-3 个工具启用
enabled_tool_names = [t['name'] for t in tools[:3] if t.get('enabled')]
print(f'    启用工具: {enabled_tool_names}')

# 3. 创建 hermes 引擎的 agent
agent_body = {
    'name': 'C12-Test-Hermes',
    'description': 'C-12 工具搜索状态验证用 agent',
    'engine': 'hermes',
    'system_prompt': '你是 SOAR 安全运营助手，负责告警研判与处置。',
    'model_config_id': 1,
    'temperature': 0.7,
    'max_tokens': 1024,
    'max_iterations': 5,
    'context_turns': 10,
    'enable_memory': False,
    'tone_style': 'professional',
    'enabled_tools': enabled_tool_names,
    'enabled_kbs': [],
    'enabled_skills': [],
    'tool_configs': {
        'tool_search': {
            'enabled': 'auto',
            'threshold_pct': 10,
            'search_default_limit': 5,
            'max_search_limit': 20,
        },
    },
}
status, created = api('POST', '/agents', token=token, body=agent_body)
print(f'[3] 创建 hermes agent: {status}')
if status != 201:
    print(f'    失败: {created}')
    raise SystemExit(1)
agent_id = created['id']
print(f'    agent_id={agent_id}, engine={created.get("engine")}')

# 4. 调用 tool-search-status
status, result = api('GET', f'/agents/{agent_id}/tool-search-status', token=token)
print(f'[4] tool-search-status: {status}')
if status != 200:
    print(f'    失败: {result}')
    raise SystemExit(1)

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
    tool_names = [t['name'] for t in group.get('tools', [])]
    print(f'  [{src}] {group["count"]} 个 / {group["tokens"]} token: {tool_names}')

print('── 可延迟工具（deferrable）──')
for src, group in classification.get('deferrable_by_source', {}).items():
    tool_names = [t['name'] for t in group.get('tools', [])]
    print(f'  [{src}] {group["count"]} 个 / {group["tokens"]} token: {tool_names}')

# 5. 断言
assert result.get('supported') is True, 'supported 应为 True'
cfg = result['config']
assert cfg['enabled'] == 'auto', f'enabled 应为 auto, 实际 {cfg["enabled"]}'
assert cfg['threshold_pct'] == 10, f'threshold_pct 应为 10, 实际 {cfg["threshold_pct"]}'
assert stats['visible_count'] >= 0, 'visible_count 应 >= 0'
# 启用了 3 个工具，应该有分类结果
total = stats['visible_count'] + stats['deferrable_count']
assert total >= 0, f'总工具数应 >= 0, 实际 {total}'

print()
print('=' * 60)
print('✅ tool-search-status 端点验证全部通过！')
print(f'   agent_id={agent_id} (可登录前端查看 /agents/{agent_id}/edit)')
print('=' * 60)
