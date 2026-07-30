import { useEffect, useState, useCallback } from 'react'
import { llmConfigs as llmApi } from '../api/client'
import {
  Section,
  TextInput,
  SelectInput,
  CheckRow,
} from '../components/property/FormControls'
import { Modal } from '../components/Dialog'
import { TutorialButton, TutorialDrawer } from '../components/TutorialDrawer'
import { LLM_TUTORIAL } from '../components/tutorialContent'

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 把 api_key 脱敏显示（只显示前 4 位 + 后 4 位）
function maskKey(key) {
  if (!key || typeof key !== 'string') return ''
  if (key.length <= 8) return '****'
  return `${key.slice(0, 4)}****${key.slice(-4)}`
}

const PROVIDER_OPTIONS = [
  { value: 'anthropic', label: 'Anthropic (Claude)' },
  { value: 'openai', label: 'OpenAI (GPT)' },
  { value: 'azure', label: 'Azure OpenAI' },
  { value: 'google', label: 'Google (Gemini)' },
  { value: 'deepseek', label: 'DeepSeek (深度求索)' },
  { value: 'moonshot', label: 'Moonshot (月之暗面/Kimi)' },
  { value: 'zhipu', label: '智谱 AI (GLM)' },
  { value: 'volcengine', label: '火山引擎 (豆包)' },
  { value: 'baidu', label: '百度 (文心一言)' },
  { value: 'alibaba', label: '阿里 (通义千问)' },
  { value: 'tencent', label: '腾讯 (混元)' },
  { value: 'minimax', label: 'MiniMax' },
  { value: 'siliconflow', label: '硅基流动 (SiliconFlow)' },
  { value: 'ollama', label: 'Ollama (本地部署)' },
  { value: 'other', label: '其他 (OpenAI 兼容)' },
]

// ============ 调用监控 Tab ============
function MonitorTab() {
  const [stats, setStats] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [days, setDays] = useState(7)
  // 明细弹窗
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailConfig, setDetailConfig] = useState(null)
  const [calls, setCalls] = useState([])
  const [callsLoading, setCallsLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await llmApi.monitorStats(days)
      setStats(data?.stats || [])
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    load()
  }, [load])

  const openDetail = async (cfg) => {
    setDetailConfig(cfg)
    setDetailOpen(true)
    setCallsLoading(true)
    try {
      const data = await llmApi.monitorCalls(cfg.model_config_id, 100)
      setCalls(data?.calls || [])
    } catch {
      setCalls([])
    } finally {
      setCallsLoading(false)
    }
  }

  const dayOptions = [1, 7, 14, 30]

  return (
    <div className="flex flex-col gap-4">
      {/* 工具栏 */}
      <div className="flex items-center justify-between rounded-lg border border-gray-800 bg-gray-900/60 p-4">
        <span className="text-xs text-gray-500">
          统计各模型的调用次数、成功率、平均耗时、Token 用量（含智能体对话和手动测试）
        </span>
        <div className="flex items-center gap-1 rounded-lg border border-gray-800 bg-gray-900/60 p-1">
          {dayOptions.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                days === d ? 'bg-brand-500/20 text-brand-300' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              {d} 天
            </button>
          ))}
          <button onClick={load} disabled={loading} className="btn-secondary btn-sm ml-2">
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>
      </div>

      {error && (
        <div className="w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-40 items-center justify-center text-sm text-gray-500">加载中…</div>
      ) : stats.length === 0 ? (
        <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
          <div className="text-4xl">📊</div>
          <div className="text-sm">暂无调用记录</div>
          <div className="text-xs">进行智能体对话或测试模型配置后，此处将显示调用统计</div>
        </div>
      ) : (
        <div className="w-full overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full min-w-[1100px] table-fixed border-collapse text-sm">
            <thead className="bg-gray-900 text-gray-400">
              <tr>
                <th className="px-4 py-3 text-left font-medium">配置名称</th>
                <th className="w-32 px-4 py-3 text-left font-medium">模型</th>
                <th className="w-20 px-4 py-3 text-right font-medium">调用次数</th>
                <th className="w-24 px-4 py-3 text-right font-medium">成功率</th>
                <th className="w-24 px-4 py-3 text-right font-medium">平均耗时</th>
                <th className="w-24 px-4 py-3 text-right font-medium">最大耗时</th>
                <th className="w-28 px-4 py-3 text-right font-medium">输入Token</th>
                <th className="w-28 px-4 py-3 text-right font-medium">输出Token</th>
                <th className="w-36 px-4 py-3 text-left font-medium">最近调用</th>
                <th className="w-24 px-4 py-3 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {stats.map((s, idx) => (
                <tr
                  key={s.model_config_id || idx}
                  className={`border-t border-gray-800 hover:bg-brand-500/5 ${
                    idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
                  }`}
                >
                  <td className="truncate px-4 py-3 text-gray-200">{s.config_name}</td>
                  <td className="truncate px-4 py-3 text-gray-400">{s.model_name || '-'}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-200">{s.total_calls}</td>
                  <td className="px-4 py-3 text-right">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        s.success_rate >= 0.9
                          ? 'bg-success-500/20 text-success-300'
                          : s.success_rate >= 0.5
                          ? 'bg-warning-500/20 text-warning-300'
                          : 'bg-danger-500/20 text-danger-300'
                      }`}
                    >
                      {(s.success_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-300">{s.avg_latency_ms}ms</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">{s.max_latency_ms}ms</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">{s.total_input_tokens}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">{s.total_output_tokens}</td>
                  <td className="px-4 py-3 text-gray-500">{fmtTime(s.last_call_at)}</td>
                  <td className="px-4 py-3 text-center">
                    <button onClick={() => openDetail(s)} className="btn-secondary btn-sm">
                      明细
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 调用明细弹窗 */}
      <Modal
        open={detailOpen}
        title={`调用明细：${detailConfig?.config_name || ''}`}
        onClose={() => setDetailOpen(false)}
        maxWidth="max-w-3xl"
        footer={
          <button onClick={() => setDetailOpen(false)} className="btn-primary">
            关闭
          </button>
        }
      >
        {callsLoading ? (
          <div className="flex h-32 items-center justify-center text-sm text-gray-500">加载中…</div>
        ) : calls.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-sm text-gray-500">暂无调用记录</div>
        ) : (
          <div className="max-h-[60vh] overflow-auto rounded-md border border-gray-800">
            <table className="w-full table-fixed border-collapse text-xs">
              <thead className="sticky top-0 bg-gray-900 text-gray-400">
                <tr>
                  <th className="w-32 px-3 py-2 text-left font-medium">时间</th>
                  <th className="w-20 px-3 py-2 text-left font-medium">状态</th>
                  <th className="w-24 px-3 py-2 text-right font-medium">耗时</th>
                  <th className="w-20 px-3 py-2 text-right font-medium">输入Token</th>
                  <th className="w-20 px-3 py-2 text-right font-medium">输出Token</th>
                  <th className="w-24 px-3 py-2 text-left font-medium">来源</th>
                  <th className="px-3 py-2 text-left font-medium">错误信息</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c, idx) => (
                  <tr key={c.id || idx} className={`border-t border-gray-800 ${idx % 2 === 0 ? 'bg-gray-900/30' : ''}`}>
                    <td className="px-3 py-2 text-gray-400">{fmtTime(c.created_at)}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          c.status === 'success'
                            ? 'bg-success-500/20 text-success-300'
                            : 'bg-danger-500/20 text-danger-300'
                        }`}
                      >
                        {c.status === 'success' ? '成功' : '失败'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-gray-300">{c.latency_ms || '-'}ms</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-400">{c.input_tokens ?? '-'}</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-400">{c.output_tokens ?? '-'}</td>
                    <td className="px-3 py-2 text-gray-400">
                      {c.trigger_type === 'agent_test' ? '智能体对话' : c.trigger_type === 'manual_test' ? '手动测试' : c.trigger_type || '-'}
                    </td>
                    <td className="truncate px-3 py-2 text-danger-300" title={c.error_message || ''}>
                      {c.error_message ? c.error_message.slice(0, 80) : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>
    </div>
  )
}

// 模型配置管理：列表 + 编辑弹窗 + 调用监控
function LLMConfig() {
  const [activeTab, setActiveTab] = useState('configs') // configs | monitor
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tutorialOpen, setTutorialOpen] = useState(false)

  // 编辑相关
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    name: '', provider: 'anthropic', api_key: '', base_url: '', model_name: '', model_type: 'chat', is_default: false,
  })
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await llmApi.list()
      setRows(Array.isArray(data) ? data : [])
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    setForm({ name: '', provider: 'anthropic', api_key: '', base_url: '', model_name: '', model_type: 'chat', is_default: false })
    setEditOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    setForm({
      name: row.name || '', provider: row.provider || 'anthropic', api_key: '',
      base_url: row.base_url || '', model_name: row.model_name || '', model_type: row.model_type || 'chat', is_default: !!row.is_default,
    })
    setEditOpen(true)
  }

  const setField = (field) => (value) => setForm((prev) => ({ ...prev, [field]: value }))

  const handleSave = async () => {
    if (!form.name.trim()) { window.alert('请填写配置名称'); return }
    setSaving(true)
    try {
      const body = { name: form.name, provider: form.provider, api_key: form.api_key, base_url: form.base_url, model_name: form.model_name, model_type: form.model_type, is_default: form.is_default }
      if (editing && !body.api_key) delete body.api_key
      if (editing) { await llmApi.update(editing.id, body) } else { await llmApi.create(body) }
      setEditOpen(false)
      await load()
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (row) => {
    if (!window.confirm(`确定删除模型配置「${row.name || row.id}」吗？`)) return
    try { await llmApi.remove(row.id); await load() } catch (err) { window.alert(`删除失败：${err.message || err}`) }
  }

  const [testing, setTesting] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [testResultOpen, setTestResultOpen] = useState(false)

  const handleTest = async (row) => {
    setTesting(row.id)
    try {
      const res = await llmApi.test(row.id)
      setTestResult({ ...res, configName: row.name })
      setTestResultOpen(true)
    } catch (err) {
      setTestResult({ success: false, error: err.message || String(err), configName: row.name })
      setTestResultOpen(true)
    } finally {
      setTesting(null)
    }
  }

  const tabs = [
    { key: 'configs', label: '模型配置' },
    { key: 'monitor', label: '调用监控' },
  ]

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between gap-4 border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-100">模型设置</h1>
          {activeTab === 'configs' && <span className="text-xs text-gray-500">共 {rows.length} 个</span>}
        </div>
        {activeTab === 'configs' && (
          <div className="flex shrink-0 items-center gap-2">
            <TutorialButton onClick={() => setTutorialOpen(true)} />
            <button type="button" onClick={load} className="btn-secondary btn-sm">刷新</button>
            <button type="button" onClick={openCreate} className="btn-primary btn-sm">+ 新建配置</button>
          </div>
        )}
      </header>

      {/* Tab 切换 */}
      <div className="flex items-center gap-1 border-b border-gray-800 bg-gray-900/30 px-6">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveTab(t.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
              activeTab === t.key ? 'border-brand-500 text-white' : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === 'monitor' ? (
          <MonitorTab />
        ) : (
          <>
            {error && (
              <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
                {error}
              </div>
            )}
            {loading ? (
              <div className="flex h-40 items-center justify-center text-sm text-gray-500">加载中...</div>
            ) : rows.length === 0 ? (
              <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
                <div className="text-4xl">🧠</div>
                <div className="text-sm">暂无模型配置</div>
              </div>
            ) : (
              <div className="w-full overflow-x-auto rounded-lg border border-gray-800">
                <table className="w-full min-w-[820px] table-fixed border-collapse text-sm">
                  <thead className="bg-gray-900 text-gray-400">
                    <tr>
                      <th className="w-20 px-4 py-3 text-left font-medium">ID</th>
                      <th className="px-4 py-3 text-left font-medium">名称</th>
                      <th className="w-32 px-4 py-3 text-left font-medium">Provider</th>
                      <th className="w-24 px-4 py-3 text-left font-medium">类型</th>
                      <th className="px-4 py-3 text-left font-medium">模型</th>
                      <th className="px-4 py-3 text-left font-medium">API Key</th>
                      <th className="w-32 px-4 py-3 text-left font-medium">默认</th>
                      <th className="w-40 px-4 py-3 text-left font-medium">创建时间</th>
                      <th className="w-56 px-4 py-3 text-left font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, idx) => (
                      <tr key={r.id} className={`border-t border-gray-800 transition-colors hover:bg-brand-500/5 ${idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'}`}>
                        <td className="truncate px-4 py-3 font-mono text-brand-300">#{r.id}</td>
                        <td className="truncate px-4 py-3 text-gray-200">{r.name || '-'}</td>
                        <td className="truncate px-4 py-3 text-gray-300">{r.provider || '-'}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${(r.model_type || 'chat') === 'embedding' ? 'bg-purple-500/20 text-purple-300' : 'bg-brand-500/20 text-brand-300'}`}>
                            {(r.model_type || 'chat') === 'embedding' ? '向量化' : '对话'}
                          </span>
                        </td>
                        <td className="truncate px-4 py-3 text-gray-300">{r.model_name || '-'}</td>
                        <td className="truncate px-4 py-3 font-mono text-xs text-gray-400">{maskKey(r.api_key)}</td>
                        <td className="px-4 py-3">
                          {r.is_default ? (
                            <span className="rounded bg-success-500/20 px-2 py-0.5 text-[11px] font-medium text-success-300">默认</span>
                          ) : (
                            <span className="text-xs text-gray-600">-</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-gray-400">{fmtTime(r.created_at)}</td>
                        <td className="px-4 py-3">
                          <div className="flex gap-2">
                            <button type="button" onClick={() => handleTest(r)} disabled={testing === r.id} className="btn-secondary btn-sm">
                              {testing === r.id ? '测试中…' : '测试'}
                            </button>
                            <button type="button" onClick={() => openEdit(r)} className="btn-secondary btn-sm">编辑</button>
                            <button type="button" onClick={() => handleDelete(r)} className="btn-danger btn-sm">删除</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {/* 新建/编辑弹窗 */}
      <Modal open={editOpen} title={editing ? `编辑模型配置：${editing.name || ''}` : '新建模型配置'} onClose={() => setEditOpen(false)} maxWidth="max-w-xl"
        footer={<><button type="button" onClick={() => setEditOpen(false)} className="btn-secondary">取消</button><button type="button" onClick={handleSave} disabled={saving} className="btn-primary">{saving ? '保存中…' : '保存'}</button></>}>
        <Section title="基础配置">
          <TextInput label="名称" value={form.name} onChange={setField('name')} placeholder="如：Claude 默认配置" />
          <SelectInput label="Provider" value={form.provider} onChange={setField('provider')} options={PROVIDER_OPTIONS} />
          <SelectInput label="模型类型" value={form.model_type} onChange={setField('model_type')} options={[
            { value: 'chat', label: '对话模型 (chat)' },
            { value: 'embedding', label: '向量化模型 (embedding)' },
          ]} hint={form.model_type === 'embedding' ? '向量化模型用于知识库 Embedding，测试时走 /embeddings 端点。' : '对话模型用于智能体对话与节点执行。'} />
          <TextInput label="Model Name" value={form.model_name} onChange={setField('model_name')} placeholder={form.model_type === 'embedding' ? '如：doubao-embedding-text-240715' : '如：claude-3-5-sonnet-20240620'} />
        </Section>
        <Section title="凭证" hint={editing ? 'API Key 留空表示不修改现有值。' : ''}>
          <TextInput label="API Key" value={form.api_key} onChange={setField('api_key')} placeholder={editing ? '（留空不修改）' : 'sk-...'} />
          <TextInput label="Base URL" value={form.base_url} onChange={setField('base_url')} placeholder="https://api.anthropic.com" />
        </Section>
        <Section title="其它">
          <CheckRow label="设为默认配置" checked={form.is_default} onChange={setField('is_default')} hint="设为默认后，新建智能体时将默认选中该模型。" />
        </Section>
      </Modal>

      {/* 测试结果弹窗 */}
      <Modal open={testResultOpen} title={`LLM 连通性测试：${testResult?.configName || ''}`} onClose={() => setTestResultOpen(false)} maxWidth="max-w-lg"
        footer={<button type="button" onClick={() => setTestResultOpen(false)} className="btn-primary">关闭</button>}>
        {testResult?.success ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 rounded-md border border-success-500/40 bg-success-500/10 px-4 py-3">
              <span className="text-success-300">✓</span><span className="text-sm text-success-300">连接成功</span>
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">模型回复</div>
              <pre className="w-full overflow-auto rounded-md bg-gray-950 p-4 font-mono text-xs text-gray-200 ring-1 ring-gray-800">{testResult.response || '(空)'}</pre>
            </div>
            {testResult.model && <div className="text-xs text-gray-500">模型: {testResult.model}</div>}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-3">
              <span className="text-danger-300">✕</span><span className="text-sm text-danger-300">连接失败</span>
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">错误信息</div>
              <pre className="w-full overflow-auto rounded-md bg-gray-950 p-4 font-mono text-xs text-red-300 ring-1 ring-gray-800">{testResult?.error || '未知错误'}</pre>
            </div>
            <div className="text-[11px] text-gray-500">常见原因：API Key 无效、Base URL 错误、模型名不存在、网络不通</div>
          </div>
        )}
      </Modal>

      {/* 使用教程 */}
      <TutorialDrawer
        open={tutorialOpen}
        onClose={() => setTutorialOpen(false)}
        title="模型设置使用教程"
        subtitle="了解如何配置模型、测试连通性和查看调用监控"
        sections={LLM_TUTORIAL}
      />
    </div>
  )
}

export default LLMConfig
