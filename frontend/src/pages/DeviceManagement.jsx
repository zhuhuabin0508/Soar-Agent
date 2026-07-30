import { useEffect, useState, useCallback } from 'react'
import { devices as devicesApi } from '../api/client'
import { Modal } from '../components/Dialog'
import { inputCls, textareaCls } from '../components/property/FormControls'
import { TutorialButton, TutorialDrawer } from '../components/TutorialDrawer'
import { DEVICE_TUTORIAL } from '../components/tutorialContent'

// 设备类型选项
const DEVICE_TYPES = [
  { value: 'firewall', label: '防火墙 (Firewall)' },
  { value: 'waf', label: 'Web 应用防火墙 (WAF)' },
  { value: 'ips', label: '入侵防御 (IPS)' },
  { value: 'ids', label: '入侵检测 (IDS)' },
  { value: 'edr', label: '终端检测响应 (EDR)' },
  { value: 'soar', label: 'SOAR 平台' },
  { value: 'custom', label: '自定义设备' },
]

// 动作类型选项（SOAR 理论常见处置动作）
const ACTION_TYPES = [
  { value: 'block_ip', label: '封禁 IP (block_ip)' },
  { value: 'unblock_ip', label: '解封 IP (unblock_ip)' },
  { value: 'quarantine_host', label: '隔离主机 (quarantine_host)' },
  { value: 'isolate_endpoint', label: '隔离终端 (isolate_endpoint)' },
  { value: 'add_ioc', label: '添加 IOC (add_ioc)' },
  { value: 'delete_ioc', label: '删除 IOC (delete_ioc)' },
  { value: 'custom', label: '自定义动作 (custom)' },
]

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']
const AUTH_TYPES = [
  { value: 'api_key', label: 'API Key (Bearer)' },
  { value: 'bearer', label: 'Bearer Token' },
  { value: 'basic', label: 'Basic Auth' },
  { value: 'none', label: '无认证' },
]

function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 设备类型中文映射（用于展示）
const DEVICE_TYPE_LABELS = Object.fromEntries(
  DEVICE_TYPES.map((t) => [t.value, t.label])
)

// ============ 设备表单弹窗 ============
function DeviceFormModal({ open, initial, onClose, onSubmit, saving }) {
  const [form, setForm] = useState(() => ({
    name: '',
    type: 'firewall',
    vendor: '',
    api_url: '',
    api_key: '',
    username: '',
    password: '',
    enabled: true,
    description: '',
    ...(initial || {}),
  }))

  useEffect(() => {
    if (open) {
      setForm({
        name: '',
        type: 'firewall',
        vendor: '',
        api_url: '',
        api_key: '',
        username: '',
        password: '',
        enabled: true,
        description: '',
        ...(initial || {}),
      })
    }
  }, [open, initial])

  const set = (k) => (v) => setForm((p) => ({ ...p, [k]: v }))

  return (
    <Modal
      open={open}
      title={initial ? `编辑设备：${initial.name || ''}` : '新建安全设备'}
      onClose={onClose}
      maxWidth="max-w-2xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={() => onSubmit(form)}
            disabled={saving || !form.name}
            className="btn-primary"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">
              设备名称 <span className="text-danger-400">*</span>
            </div>
            <input
              className={inputCls}
              value={form.name}
              onChange={(e) => set('name')(e.target.value)}
              placeholder="如：核心防火墙-A"
            />
          </label>
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">设备类型</div>
            <select
              className={inputCls}
              value={form.type}
              onChange={(e) => set('type')(e.target.value)}
            >
              {DEVICE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">厂商</div>
            <input
              className={inputCls}
              value={form.vendor}
              onChange={(e) => set('vendor')(e.target.value)}
              placeholder="如：深信服 / 绿盟 / paloalto"
            />
          </label>
          <label className="flex items-end gap-2 pb-1">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => set('enabled')(e.target.checked)}
              className="h-4 w-4 accent-brand-500"
            />
            <span className="text-sm text-gray-300">启用设备</span>
          </label>
        </div>

        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">
            API 基地址
          </div>
          <input
            className={inputCls}
            value={form.api_url}
            onChange={(e) => set('api_url')(e.target.value)}
            placeholder="https://10.0.0.1:8443/api"
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">
              API Key / Token
            </div>
            <input
              className={inputCls}
              value={form.api_key}
              onChange={(e) => set('api_key')(e.target.value)}
              placeholder="API Key 或 Bearer Token"
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label>
              <div className="mb-1 text-xs font-medium text-gray-400">用户名</div>
              <input
                className={inputCls}
                value={form.username}
                onChange={(e) => set('username')(e.target.value)}
                placeholder="Basic Auth 用户名"
              />
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-gray-400">密码</div>
              <input
                type="password"
                className={inputCls}
                value={form.password}
                onChange={(e) => set('password')(e.target.value)}
                placeholder="Basic Auth 密码"
              />
            </label>
          </div>
        </div>

        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">设备描述</div>
          <input
            className={inputCls}
            value={form.description}
            onChange={(e) => set('description')(e.target.value)}
            placeholder="可选，对设备的简短说明"
          />
        </label>
      </div>
    </Modal>
  )
}

// ============ 设备动作表单弹窗 ============
function ActionFormModal({ open, initial, onClose, onSubmit, saving }) {
  const [form, setForm] = useState(() => ({
    name: '',
    action_type: 'block_ip',
    http_method: 'POST',
    api_path: '',
    params_schema: '[]',
    headers: '{}',
    body_template: '',
    auth_type: 'api_key',
    enabled: true,
    description: '',
    ...(initial || {}),
  }))

  useEffect(() => {
    if (open) {
      setForm({
        name: '',
        action_type: 'block_ip',
        http_method: 'POST',
        api_path: '',
        params_schema: '[]',
        headers: '{}',
        body_template: '',
        auth_type: 'api_key',
        enabled: true,
        description: '',
        ...(initial || {}),
      })
    }
  }, [open, initial])

  const set = (k) => (v) => setForm((p) => ({ ...p, [k]: v }))

  // 校验 JSON 字段
  const validateJson = (str) => {
    if (!str.trim()) return true
    try {
      JSON.parse(str)
      return true
    } catch {
      return false
    }
  }

  const handleSubmit = () => {
    if (!form.name) {
      window.alert('请填写动作名称')
      return
    }
    if (!validateJson(form.params_schema)) {
      window.alert('参数定义不是合法的 JSON 数组')
      return
    }
    if (!validateJson(form.headers)) {
      window.alert('请求头不是合法的 JSON 对象')
      return
    }
    onSubmit(form)
  }

  return (
    <Modal
      open={open}
      title={initial ? `编辑动作：${initial.name || ''}` : '新建设备动作'}
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saving}
            className="btn-primary"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">
              动作名称 <span className="text-danger-400">*</span>
            </div>
            <input
              className={inputCls}
              value={form.name}
              onChange={(e) => set('name')(e.target.value)}
              placeholder="如：封禁 IP"
            />
          </label>
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">动作类型</div>
            <select
              className={inputCls}
              value={form.action_type}
              onChange={(e) => set('action_type')(e.target.value)}
            >
              {ACTION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-[110px_1fr_140px] gap-3">
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">HTTP 方法</div>
            <select
              className={inputCls}
              value={form.http_method}
              onChange={(e) => set('http_method')(e.target.value)}
            >
              {HTTP_METHODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">API 路径</div>
            <input
              className={inputCls}
              value={form.api_path}
              onChange={(e) => set('api_path')(e.target.value)}
              placeholder="/block/ip"
            />
          </label>
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">认证方式</div>
            <select
              className={inputCls}
              value={form.auth_type}
              onChange={(e) => set('auth_type')(e.target.value)}
            >
              {AUTH_TYPES.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">
            参数定义（JSON 数组，每项：name/type/required/default/description）
          </div>
          <textarea
            className={`${textareaCls} text-xs`}
            rows={5}
            value={form.params_schema}
            onChange={(e) => set('params_schema')(e.target.value)}
            placeholder={
              '[\n  {"name":"ip","type":"string","required":true,"description":"要封禁的 IP"},\n  {"name":"duration","type":"number","required":false,"default":3600,"description":"封禁时长(秒)"}\n]'
            }
          />
        </label>

        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">
            请求头（JSON 对象，会合并到默认 Content-Type）
          </div>
          <textarea
            className={`${textareaCls} text-xs`}
            rows={3}
            value={form.headers}
            onChange={(e) => set('headers')(e.target.value)}
            placeholder='{"X-Tenant": "default"}'
          />
        </label>

        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">
            请求体模板（含 {`{{param}}`} 占位符；留空则用 params 自动构造 JSON）
          </div>
          <textarea
            className={`${textareaCls} text-xs`}
            rows={5}
            value={form.body_template}
            onChange={(e) => set('body_template')(e.target.value)}
            placeholder={'{"ip": "{{ip}}", "duration": {{duration}}}'}
          />
        </label>

        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">动作描述</div>
          <input
            className={inputCls}
            value={form.description}
            onChange={(e) => set('description')(e.target.value)}
            placeholder="可选，说明此动作的作用"
          />
        </label>

        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set('enabled')(e.target.checked)}
            className="h-4 w-4 accent-brand-500"
          />
          <span className="text-sm text-gray-300">启用此动作</span>
        </label>
      </div>
    </Modal>
  )
}

// ============ 动作测试弹窗 ============
// 根据 params_schema 动态生成参数输入表单
function ActionTestModal({ open, action, onClose, onSubmit, running }) {
  const [params, setParams] = useState({})

  useEffect(() => {
    if (open && action) {
      const init = {}
      let schema = []
      try {
        schema = JSON.parse(action.params_schema || '[]')
      } catch {
        schema = []
      }
      schema.forEach((p) => {
        init[p.name] = p.default !== undefined ? p.default : ''
      })
      setParams(init)
    }
  }, [open, action])

  if (!open || !action) return null

  let schema = []
  try {
    schema = JSON.parse(action.params_schema || '[]')
  } catch {
    schema = []
  }

  return (
    <Modal
      open={open}
      title={`测试动作：${action.name || ''}`}
      onClose={onClose}
      maxWidth="max-w-2xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={() => onSubmit(params)}
            disabled={running}
            className="btn-primary"
          >
            {running ? '测试中…' : '开始测试'}
          </button>
        </>
      }
    >
      {schema.length === 0 ? (
        <p className="text-sm text-gray-500">
          此动作未定义参数，可直接点击「开始测试」。
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {schema.map((p) => (
            <label key={p.name}>
              <div className="mb-1 text-xs font-medium text-gray-400">
                {p.name}
                <span className="ml-1 text-gray-500">({p.type || 'string'})</span>
                {p.required && <span className="ml-1 text-danger-400">*</span>}
              </div>
              <input
                className={inputCls}
                value={params[p.name] ?? ''}
                onChange={(e) =>
                  setParams((prev) => ({ ...prev, [p.name]: e.target.value }))
                }
                placeholder={p.description || ''}
              />
              {p.description && (
                <div className="mt-1 text-[11px] text-gray-500">
                  {p.description}
                </div>
              )}
            </label>
          ))}
        </div>
      )}
    </Modal>
  )
}

// ============ 主页面 ============
function DeviceManagement() {
  const [devices, setDevices] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 当前展开的设备 ID（展开后显示动作列表）
  const [expandedId, setExpandedId] = useState(null)
  const [actions, setActions] = useState([])
  const [loadingActions, setLoadingActions] = useState(false)

  // 弹窗状态
  const [devFormOpen, setDevFormOpen] = useState(false)
  const [devEditing, setDevEditing] = useState(null)
  const [devSaving, setDevSaving] = useState(false)

  const [actFormOpen, setActFormOpen] = useState(false)
  const [actEditing, setActEditing] = useState(null)
  const [actSaving, setActSaving] = useState(false)

  const [testOpen, setTestOpen] = useState(false)
  const [testAction, setTestAction] = useState(null)
  const [testRunning, setTestRunning] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [testResultOpen, setTestResultOpen] = useState(false)

  // 列表搜索关键字
  const [search, setSearch] = useState('')
  const [tutorialOpen, setTutorialOpen] = useState(false)

  const loadDevices = useCallback(async () => {
    try {
      const data = await devicesApi.list()
      setDevices(Array.isArray(data) ? data : [])
      setError('')
    } catch (err) {
      setError(err.message || '加载设备失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDevices()
  }, [loadDevices])

  const loadActions = useCallback(async (deviceId) => {
    setLoadingActions(true)
    try {
      const data = await devicesApi.listActions(deviceId)
      setActions(Array.isArray(data) ? data : [])
    } catch (err) {
      window.alert(`加载动作失败：${err.message || err}`)
      setActions([])
    } finally {
      setLoadingActions(false)
    }
  }, [])

  const handleToggleExpand = (device) => {
    if (expandedId === device.id) {
      setExpandedId(null)
      setActions([])
    } else {
      setExpandedId(device.id)
      loadActions(device.id)
    }
  }

  // 设备保存
  const handleDeviceSubmit = async (form) => {
    setDevSaving(true)
    try {
      if (devEditing) {
        await devicesApi.update(devEditing.id, form)
      } else {
        await devicesApi.create(form)
      }
      setDevFormOpen(false)
      setDevEditing(null)
      await loadDevices()
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setDevSaving(false)
    }
  }

  const handleDeviceDelete = async (device) => {
    if (!window.confirm(`确定删除设备「${device.name}」吗？将同时删除其下所有动作。`))
      return
    try {
      await devicesApi.remove(device.id)
      if (expandedId === device.id) {
        setExpandedId(null)
        setActions([])
      }
      await loadDevices()
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  // 动作保存
  const handleActionSubmit = async (form) => {
    if (!expandedId) return
    setActSaving(true)
    try {
      if (actEditing) {
        await devicesApi.updateAction(expandedId, actEditing.id, form)
      } else {
        await devicesApi.createAction(expandedId, form)
      }
      setActFormOpen(false)
      setActEditing(null)
      await loadActions(expandedId)
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setActSaving(false)
    }
  }

  const handleActionDelete = async (action) => {
    if (!expandedId) return
    if (!window.confirm(`确定删除动作「${action.name}」吗？`)) return
    try {
      await devicesApi.removeAction(expandedId, action.id)
      await loadActions(expandedId)
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  // 测试动作
  const handleActionTest = async (params) => {
    if (!expandedId || !testAction) return
    setTestOpen(false)
    setTestRunning(true)
    setTestResult(null)
    try {
      const res = await devicesApi.testAction(expandedId, testAction.id, params)
      setTestResult(res)
      setTestResultOpen(true)
    } catch (err) {
      setTestResult({
        success: false,
        status_code: null,
        response_body: null,
        error: err.message || String(err),
      })
      setTestResultOpen(true)
    } finally {
      setTestRunning(false)
    }
  }

  // 按名称/厂商/类型过滤设备列表
  const filteredDevices = search
    ? devices.filter((d) => {
        const q = search.toLowerCase()
        return (
          (d.name || '').toLowerCase().includes(q) ||
          (d.vendor || '').toLowerCase().includes(q) ||
          (d.type || '').toLowerCase().includes(q)
        )
      })
    : devices

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-100">设备对接</h1>
          <span className="text-xs text-gray-500">共 {devices.length} 台</span>
        </div>
        <div className="flex items-center gap-2">
          <TutorialButton onClick={() => setTutorialOpen(true)} />
          <button type="button" onClick={loadDevices} className="btn-secondary btn-sm">
            刷新
          </button>
          <button
            type="button"
            onClick={() => {
              setDevEditing(null)
              setDevFormOpen(true)
            }}
            className="btn-primary btn-sm"
          >
            + 新建设备
          </button>
        </div>
      </header>

      <div className="px-6 pb-3">
        <input
          className="w-full max-w-sm rounded-md border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          placeholder="搜索设备名称/厂商/类型..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : devices.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">🛡️</div>
            <div className="text-sm">暂无安全设备，点击右上角「新建设备」</div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {filteredDevices.map((dev) => (
              <div
                key={dev.id}
                className="w-full rounded-lg border border-gray-800 bg-gray-900/40 overflow-hidden"
              >
                {/* 设备行 */}
                <div className="flex items-center gap-3 p-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-brand-500/15 text-xl">
                    🛡️
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-gray-100">
                        {dev.name}
                      </span>
                      <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400">
                        #{dev.id}
                      </span>
                      <span className="rounded bg-brand-500/15 px-1.5 py-0.5 text-[10px] text-brand-300">
                        {DEVICE_TYPE_LABELS[dev.type] || dev.type}
                      </span>
                      {dev.vendor && (
                        <span className="text-[11px] text-gray-500">
                          {dev.vendor}
                        </span>
                      )}
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          dev.enabled
                            ? 'bg-success-500/20 text-success-300'
                            : 'bg-gray-700 text-gray-400'
                        }`}
                      >
                        {dev.enabled ? '启用' : '禁用'}
                      </span>
                    </div>
                    <div className="mt-0.5 truncate text-xs text-gray-500">
                      {dev.api_url || '未配置 API 地址'}
                      {dev.description ? ` · ${dev.description}` : ''}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => handleToggleExpand(dev)}
                      className="btn-secondary btn-sm"
                      title={expandedId === dev.id ? '收起动作' : '展开动作'}
                    >
                      {expandedId === dev.id ? '收起' : '动作'}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDevEditing(dev)
                        setDevFormOpen(true)
                      }}
                      className="btn-secondary btn-sm"
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeviceDelete(dev)}
                      className="btn-danger btn-sm"
                    >
                      删除
                    </button>
                  </div>
                </div>

                {/* 动作列表（展开时显示） */}
                {expandedId === dev.id && (
                  <div className="border-t border-gray-800 bg-gray-950/40 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                        设备动作（{loadingActions ? '...' : actions.length} 个）
                      </h3>
                      <button
                        type="button"
                        onClick={() => {
                          setActEditing(null)
                          setActFormOpen(true)
                        }}
                        className="btn-primary btn-sm"
                      >
                        + 新建动作
                      </button>
                    </div>

                    {loadingActions ? (
                      <div className="py-6 text-center text-xs text-gray-500">
                        加载中...
                      </div>
                    ) : actions.length === 0 ? (
                      <div className="py-6 text-center text-xs text-gray-600">
                        暂无动作，请新建
                      </div>
                    ) : (
                      <div className="overflow-x-auto rounded-md border border-gray-800">
                        <table className="w-full table-fixed border-collapse text-sm">
                          <thead className="bg-gray-900 text-gray-400">
                            <tr>
                              <th className="w-16 px-3 py-2 text-left font-medium">
                                ID
                              </th>
                              <th className="px-3 py-2 text-left font-medium">
                                动作名称
                              </th>
                              <th className="w-32 px-3 py-2 text-left font-medium">
                                类型
                              </th>
                              <th className="w-28 px-3 py-2 text-left font-medium">
                                方法
                              </th>
                              <th className="px-3 py-2 text-left font-medium">
                                API 路径
                              </th>
                              <th className="w-20 px-3 py-2 text-left font-medium">
                                启用
                              </th>
                              <th className="w-72 px-3 py-2 text-left font-medium">
                                操作
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {actions.map((a, idx) => (
                              <tr
                                key={a.id}
                                className={`border-t border-gray-800 ${
                                  idx % 2 === 0 ? 'bg-gray-900/30' : ''
                                }`}
                              >
                                <td className="px-3 py-2 font-mono text-brand-300">
                                  #{a.id}
                                </td>
                                <td className="truncate px-3 py-2 text-gray-200">
                                  {a.name}
                                </td>
                                <td className="truncate px-3 py-2 text-gray-400">
                                  {a.action_type}
                                </td>
                                <td className="px-3 py-2">
                                  <span className="rounded bg-gray-800 px-1.5 py-0.5 font-mono text-[11px] text-gray-300">
                                    {a.http_method}
                                  </span>
                                </td>
                                <td
                                  className="truncate px-3 py-2 font-mono text-xs text-gray-400"
                                  title={a.api_path}
                                >
                                  {a.api_path || '-'}
                                </td>
                                <td className="px-3 py-2">
                                  <span
                                    className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                                      a.enabled
                                        ? 'bg-success-500/20 text-success-300'
                                        : 'bg-gray-700 text-gray-400'
                                    }`}
                                  >
                                    {a.enabled ? '是' : '否'}
                                  </span>
                                </td>
                                <td className="px-3 py-2">
                                  <div className="flex gap-1.5">
                                    <button
                                      type="button"
                                      disabled={
                                        testRunning &&
                                        testAction?.id === a.id
                                      }
                                      onClick={() => {
                                        setTestAction(a)
                                        setTestOpen(true)
                                      }}
                                      className="btn-secondary btn-sm"
                                    >
                                      测试
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setActEditing(a)
                                        setActFormOpen(true)
                                      }}
                                      className="btn-secondary btn-sm"
                                    >
                                      编辑
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => handleActionDelete(a)}
                                      className="btn-danger btn-sm"
                                    >
                                      删除
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 设备表单 */}
      <DeviceFormModal
        open={devFormOpen}
        initial={devEditing}
        onClose={() => {
          setDevFormOpen(false)
          setDevEditing(null)
        }}
        onSubmit={handleDeviceSubmit}
        saving={devSaving}
      />

      {/* 动作表单 */}
      <ActionFormModal
        open={actFormOpen}
        initial={actEditing}
        onClose={() => {
          setActFormOpen(false)
          setActEditing(null)
        }}
        onSubmit={handleActionSubmit}
        saving={actSaving}
      />

      {/* 动作测试输入 */}
      <ActionTestModal
        open={testOpen}
        action={testAction}
        onClose={() => setTestOpen(false)}
        onSubmit={handleActionTest}
        running={testRunning}
      />

      {/* 动作测试结果 */}
      <Modal
        open={testResultOpen}
        title={`测试结果${testAction ? `：${testAction.name || ''}` : ''}`}
        onClose={() => setTestResultOpen(false)}
        maxWidth="max-w-3xl"
        footer={
          <button
            type="button"
            onClick={() => setTestResultOpen(false)}
            className="btn-primary"
          >
            关闭
          </button>
        }
      >
        {testResult ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <span
                className={`rounded px-2 py-1 text-xs font-semibold ${
                  testResult.success
                    ? 'bg-success-500/20 text-success-300'
                    : 'bg-danger-500/20 text-danger-300'
                }`}
              >
                {testResult.success ? '✓ 成功' : '✗ 失败'}
              </span>
              {testResult.status_code != null && (
                <span className="font-mono text-xs text-gray-400">
                  HTTP {testResult.status_code}
                </span>
              )}
            </div>
            {testResult.error && (
              <div className="rounded-md border border-danger-500/40 bg-danger-500/10 p-3 text-sm text-danger-300">
                {testResult.error}
              </div>
            )}
            <div>
              <div className="mb-1 text-xs text-gray-500">响应内容</div>
              <pre className="max-h-72 w-full overflow-auto rounded-md bg-gray-950 p-4 font-mono text-xs text-gray-200 ring-1 ring-gray-800">
                {testResult.response_body == null
                  ? '(空)'
                  : typeof testResult.response_body === 'string'
                  ? testResult.response_body
                  : JSON.stringify(testResult.response_body, null, 2)}
              </pre>
            </div>
          </div>
        ) : (
          <div className="text-sm text-gray-500">测试中...</div>
        )}
      </Modal>

      {/* 使用教程 */}
      <TutorialDrawer
        open={tutorialOpen}
        onClose={() => setTutorialOpen(false)}
        title="设备对接使用教程"
        subtitle="了解如何添加设备和配置操作"
        sections={DEVICE_TUTORIAL}
      />
    </div>
  )
}

export default DeviceManagement
