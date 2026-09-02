import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import {
  Shield, Check, X, Plus, Search, RefreshCw, Copy, Eye, EyeOff,
  ChevronDown, ChevronRight, ExternalLink, History, Files,
  LayoutGrid, List, Columns, TestTube, AlertTriangle, Cloud,
  Activity, Download, Upload, Wifi, WifiOff, Settings, Cpu,
} from 'lucide-react'
import { devices as devicesApi } from '../api/client'
import { Modal } from '../components/Dialog'
import { confirm } from '../components/ConfirmDialog'
import { toast } from '../store/toastStore'
import { inputCls, textareaCls } from '../components/property/FormControls'
import { TutorialButton, TutorialDrawer } from '../components/TutorialDrawer'
import { DEVICE_TUTORIAL } from '../components/tutorialContent'
import { useUnsavedChanges } from '../hooks/useUnsavedChanges'
import { usePersistedFilters } from '../hooks/usePersistedFilters'
import FilterBar from '../components/FilterBar'

// ============ 常量映射 ============
const DEVICE_TYPES = [
  { value: 'firewall', label: '防火墙', icon: Shield },
  { value: 'waf', label: 'WAF', icon: Shield },
  { value: 'ips', label: 'IPS', icon: Shield },
  { value: 'ids', label: 'IDS', icon: Shield },
  { value: 'edr', label: 'EDR', icon: Cpu },
  { value: 'soar', label: 'SOAR 平台', icon: Settings },
  { value: 'switch', label: '交换机', icon: Cpu },
  { value: 'cloud', label: '云平台', icon: Cloud },
  { value: 'custom', label: '自定义', icon: Settings },
]
const DEVICE_TYPE_LABELS = Object.fromEntries(
  DEVICE_TYPES.map((t) => [t.value, t.label])
)
const DEVICE_TYPE_ICON = Object.fromEntries(
  DEVICE_TYPES.map((t) => [t.value, t.icon])
)

// 设备状态元数据
const STATUS_META = {
  online: { label: '在线', dot: 'bg-success', cls: 'bg-success/15 text-success' },
  offline: { label: '离线', dot: 'bg-destructive', cls: 'bg-destructive/15 text-destructive' },
  abnormal: { label: '异常', dot: 'bg-warning', cls: 'bg-warning/15 text-warning' },
  unconfigured: { label: '未配置', dot: 'bg-muted-foreground/60', cls: 'bg-secondary text-muted-foreground' },
  disabled: { label: '停用', dot: 'bg-zinc-700', cls: 'bg-zinc-700/20 text-zinc-400' },
}
const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'online', label: '在线' },
  { value: 'offline', label: '离线' },
  { value: 'abnormal', label: '异常' },
  { value: 'unconfigured', label: '未配置' },
  { value: 'disabled', label: '停用' },
]

// 动作分类
const ACTION_CATEGORIES = {
  block: { label: '阻断', cls: 'bg-destructive/15 text-destructive' },
  query: { label: '查询', cls: 'bg-primary/15 text-primary' },
  dispose: { label: '处置', cls: 'bg-success/15 text-success' },
  notify: { label: '通知', cls: 'bg-purple-500/15 text-purple-400' },
  other: { label: '其他', cls: 'bg-secondary text-muted-foreground' },
}
const CATEGORY_OPTIONS = [
  { value: '', label: '全部分类' },
  { value: 'block', label: '阻断' },
  { value: 'query', label: '查询' },
  { value: 'dispose', label: '处置' },
  { value: 'notify', label: '通知' },
  { value: 'other', label: '其他' },
]

// 风险等级
const RISK_META = {
  readonly: { label: '只读', cls: 'bg-success/15 text-success' },
  high_risk: { label: '高风险', cls: 'bg-destructive/15 text-destructive' },
}
const RISK_OPTIONS = [
  { value: 'readonly', label: '只读' },
  { value: 'high_risk', label: '高风险' },
]

// HTTP 方法颜色
const HTTP_METHOD_CLS = {
  GET: 'bg-success/20 text-success',
  POST: 'bg-warning/20 text-warning',
  DELETE: 'bg-destructive/20 text-destructive',
  PUT: 'bg-primary/20 text-primary',
  PATCH: 'bg-purple-500/20 text-purple-400',
}
const HTTP_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']

// 动作类型
const ACTION_TYPES = [
  { value: 'block_ip', label: '封禁 IP' },
  { value: 'unblock_ip', label: '解封 IP' },
  { value: 'quarantine_host', label: '隔离主机' },
  { value: 'isolate_endpoint', label: '隔离终端' },
  { value: 'add_ioc', label: '添加 IOC' },
  { value: 'delete_ioc', label: '删除 IOC' },
  { value: 'custom', label: '自定义' },
]

// 设备认证方式
const DEVICE_AUTH_TYPES = [
  { value: 'none', label: '无认证' },
  { value: 'api_key', label: 'API Key' },
  { value: 'basic', label: 'Basic Auth' },
  { value: 'bearer', label: 'Bearer Token' },
  { value: 'oauth2', label: 'OAuth2' },
  { value: 'mtls', label: 'mTLS 双向证书' },
]

// 动作认证方式
const ACTION_AUTH_TYPES = [
  { value: 'inherit', label: '继承设备' },
  { value: 'none', label: '无认证' },
  { value: 'api_key', label: 'API Key' },
  { value: 'bearer', label: 'Bearer Token' },
]

// 参数类型支持
const PARAM_TYPES = ['string', 'number', 'boolean', 'enum', 'ip', 'port', 'domain', 'array', 'object']

// 视图模式
const VIEW_MODES = [
  { value: 'card', icon: LayoutGrid, label: '卡片视图' },
  { value: 'table', icon: List, label: '列表视图' },
  { value: 'split', icon: Columns, label: '分栏视图' },
]

// ============ 工具函数 ============
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}
function fmtRelative(t) {
  if (!t) return '-'
  try {
    const diff = Date.now() - new Date(t).getTime()
    if (diff < 0) return fmtTime(t)
    if (diff < 60000) return `${Math.floor(diff / 1000)} 秒前`
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
    return `${Math.floor(diff / 86400000)} 天前`
  } catch {
    return t
  }
}
function copyText(text) {
  if (!text) return
  try {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => toast.success('已复制')).catch(() => {})
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      toast.success('已复制')
    }
  } catch {
    toast.error('复制失败')
  }
}
function safeParseJson(str, fallback) {
  if (!str) return fallback
  try {
    return JSON.parse(str)
  } catch {
    return fallback
  }
}
function truncate(s, n = 30) {
  if (!s) return ''
  return s.length > n ? `${s.slice(0, n)}...` : s
}
function parseTags(tags) {
  if (!tags) return []
  if (Array.isArray(tags)) return tags
  const arr = safeParseJson(tags, [])
  return Array.isArray(arr) ? arr : []
}
function successRate(action) {
  const total = action.call_count_24h ?? 0
  const ok = action.success_count_24h ?? 0
  if (!total) return null
  return ok / total
}

// ============ 设备类型图标 ============
function DeviceTypeIcon({ type, className = 'h-5 w-5' }) {
  const Icon = DEVICE_TYPE_ICON[type] || Shield
  return <Icon className={className} />
}

// ============ 状态徽章 ============
function StatusBadge({ status }) {
  const meta = STATUS_META[status] || STATUS_META.unconfigured
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded px-2 py-0.5 text-[11px] font-medium ${meta.cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  )
}

// ============ 动作分类徽章 ============
function CategoryBadge({ category }) {
  const meta = ACTION_CATEGORIES[category] || ACTION_CATEGORIES.other
  return (
    <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium ${meta.cls}`}>
      {meta.label}
    </span>
  )
}

// ============ 风险等级徽章 ============
function RiskBadge({ level }) {
  const meta = RISK_META[level] || RISK_META.readonly
  return (
    <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium ${meta.cls}`}>
      {meta.label}
    </span>
  )
}

// ============ HTTP 方法徽章 ============
function MethodBadge({ method }) {
  const cls = HTTP_METHOD_CLS[method] || 'bg-secondary text-muted-foreground'
  return (
    <span className={`whitespace-nowrap rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${cls}`}>
      {method}
    </span>
  )
}

// ============ Switch 开关 ============
function Switch({ checked, onChange, disabled, size = 'md' }) {
  const w = size === 'sm' ? 'w-8' : 'w-10'
  const h = size === 'sm' ? 'h-4' : 'h-5'
  const knob = size === 'sm' ? 'h-3 w-3' : 'h-4 w-4'
  const translate = size === 'sm' ? 'translate-x-4' : 'translate-x-5'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={`relative inline-flex ${w} ${h} shrink-0 items-center rounded-full transition-colors ${
        checked ? 'bg-primary' : 'bg-secondary border border-border'
      } disabled:cursor-not-allowed disabled:opacity-50`}
    >
      <span
        className={`inline-block ${knob} transform rounded-full bg-background shadow transition-transform ${
          checked ? translate : 'translate-x-0.5'
        }`}
      />
    </button>
  )
}

// ============ Section 表单分组 ============
function Section({ title, hint, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-md border border-border bg-card/30">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center justify-between px-3 py-2 text-left"
      >
        <div className="flex items-center gap-1.5">
          {open ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</span>
        </div>
        {hint && <span className="text-[10px] text-muted-foreground/60">{hint}</span>}
      </button>
      {open && <div className="border-t border-border p-3">{children}</div>}
    </div>
  )
}

// ============ 设备表单弹窗 ============
function DeviceFormModal({ open, initial, onClose, onSubmit, saving, onTest }) {
  const [form, setForm] = useState(() => buildInitialDeviceForm(initial))
  const [dirty, setDirty] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [tagsInput, setTagsInput] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const bypassGuard = useUnsavedChanges(dirty)

  useEffect(() => {
    if (open) {
      setForm(buildInitialDeviceForm(initial))
      setDirty(false)
      setShowApiKey(false)
      setTestResult(null)
      const tags = parseTags(initial?.tags)
      setTagsInput(tags.join(', '))
    }
  }, [open, initial])

  function buildInitialDeviceForm(src) {
    return {
      name: '',
      type: 'firewall',
      vendor: '',
      api_url: '',
      api_key: '',
      username: '',
      password: '',
      auth_type: 'api_key',
      timeout: 30,
      max_retries: 2,
      verify_tls: true,
      enabled: true,
      description: '',
      icon: '',
      tags: '[]',
      ...(src || {}),
    }
  }

  const set = (k) => (v) => {
    setForm((p) => ({ ...p, [k]: v }))
    setDirty(true)
  }

  const handleClose = () => {
    setDirty(false)
    bypassGuard()
    onClose()
  }

  const handleSubmit = async () => {
    // 同步 tags 到 form
    const tagsArr = tagsInput.split(',').map((s) => s.trim()).filter(Boolean)
    const finalForm = { ...form, tags: JSON.stringify(tagsArr) }
    const ok = await onSubmit(finalForm)
    if (ok) {
      setDirty(false)
      bypassGuard()
    }
  }

  const handleTestInDialog = async () => {
    if (!form.api_url) {
      toast.warning('请先填写 API 地址')
      return
    }
    setTesting(true)
    setTestResult(null)
    try {
      // 先保存再测试，或直接传表单给父组件测试
      const res = await onTest(form)
      setTestResult(res)
    } catch (err) {
      setTestResult({ success: false, error: err.message || String(err) })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Modal
      open={open}
      title={initial ? `编辑设备：${initial.name || ''}` : '新建安全设备'}
      onClose={handleClose}
      maxWidth="max-w-3xl"
      footer={
        <>
          <button
            type="button"
            onClick={handleTestInDialog}
            disabled={testing || !form.api_url}
            className="mr-auto btn-secondary btn-sm"
            title="测试设备连接"
          >
            {testing ? '测试中…' : '测试连接'}
          </button>
          <button type="button" onClick={handleClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saving || !form.name}
            className="btn-primary"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {/* 基础信息 */}
        <Section title="基础信息">
          <div className="grid grid-cols-2 gap-3">
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">
                设备名称 <span className="text-destructive">*</span>
              </div>
              <input
                className={inputCls}
                value={form.name}
                onChange={(e) => set('name')(e.target.value)}
                placeholder="如：核心防火墙-A"
              />
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">设备类型</div>
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
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">厂商</div>
              <input
                className={inputCls}
                value={form.vendor}
                onChange={(e) => set('vendor')(e.target.value)}
                placeholder="如：深信服 / 绿盟 / paloalto"
              />
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">设备图标（emoji 或 URL）</div>
              <input
                className={inputCls}
                value={form.icon || ''}
                onChange={(e) => set('icon')(e.target.value)}
                placeholder="🛡️ 或留空使用默认图标"
              />
            </label>
            <label className="col-span-2">
              <div className="mb-1 text-xs font-medium text-muted-foreground">设备描述</div>
              <input
                className={inputCls}
                value={form.description}
                onChange={(e) => set('description')(e.target.value)}
                placeholder="可选，对设备的简短说明"
              />
            </label>
            <label className="col-span-2">
              <div className="mb-1 text-xs font-medium text-muted-foreground">
                标签（逗号分隔，如：核心, 生产环境）
              </div>
              <input
                className={inputCls}
                value={tagsInput}
                onChange={(e) => setTagsInput(e.target.value)}
                placeholder="核心, 生产, 北京机房"
              />
            </label>
          </div>
        </Section>

        {/* 连接配置 */}
        <Section title="连接配置">
          <label className="mb-3 block">
            <div className="mb-1 text-xs font-medium text-muted-foreground">
              API 基地址 <span className="text-destructive">*</span>
            </div>
            <input
              className={inputCls}
              value={form.api_url}
              onChange={(e) => set('api_url')(e.target.value)}
              placeholder="https://10.0.0.1:8443/api"
            />
          </label>
          <div className="grid grid-cols-3 gap-3">
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">超时时间（秒）</div>
              <input
                type="number"
                className={inputCls}
                value={form.timeout ?? 30}
                onChange={(e) => set('timeout')(Number(e.target.value))}
                placeholder="30"
              />
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">最大重试次数</div>
              <input
                type="number"
                className={inputCls}
                value={form.max_retries ?? 2}
                onChange={(e) => set('max_retries')(Number(e.target.value))}
                placeholder="2"
              />
            </label>
            <label className="flex items-end gap-2 pb-1">
              <Switch checked={!!form.verify_tls} onChange={(v) => set('verify_tls')(v)} />
              <span className="text-xs text-muted-foreground">TLS 证书校验</span>
            </label>
          </div>
        </Section>

        {/* 认证配置 */}
        <Section title="认证配置">
          <label className="mb-3 block">
            <div className="mb-1 text-xs font-medium text-muted-foreground">认证方式</div>
            <select
              className={inputCls}
              value={form.auth_type}
              onChange={(e) => set('auth_type')(e.target.value)}
            >
              {DEVICE_AUTH_TYPES.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>

          {form.auth_type === 'api_key' && (
            <label className="block">
              <div className="mb-1 text-xs font-medium text-muted-foreground">API Key</div>
              <div className="flex items-center gap-1">
                <input
                  className={inputCls}
                  type={showApiKey ? 'text' : 'password'}
                  value={form.api_key}
                  onChange={(e) => set('api_key')(e.target.value)}
                  placeholder="API Key"
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey((p) => !p)}
                  className="rounded-md border border-border bg-secondary px-2 py-2 text-muted-foreground hover:text-foreground"
                  title={showApiKey ? '隐藏' : '显示'}
                >
                  {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
                <button
                  type="button"
                  onClick={() => copyText(form.api_key)}
                  disabled={!form.api_key}
                  className="rounded-md border border-border bg-secondary px-2 py-2 text-muted-foreground hover:text-primary disabled:opacity-40"
                  title="复制"
                >
                  <Copy className="h-4 w-4" />
                </button>
              </div>
            </label>
          )}

          {form.auth_type === 'basic' && (
            <div className="grid grid-cols-2 gap-3">
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">用户名</div>
                <input
                  className={inputCls}
                  value={form.username}
                  onChange={(e) => set('username')(e.target.value)}
                  placeholder="Basic Auth 用户名"
                />
              </label>
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">密码</div>
                <input
                  type="password"
                  className={inputCls}
                  value={form.password}
                  onChange={(e) => set('password')(e.target.value)}
                  placeholder="Basic Auth 密码"
                />
              </label>
            </div>
          )}

          {form.auth_type === 'bearer' && (
            <label className="block">
              <div className="mb-1 text-xs font-medium text-muted-foreground">Bearer Token</div>
              <input
                className={inputCls}
                type={showApiKey ? 'text' : 'password'}
                value={form.api_key}
                onChange={(e) => set('api_key')(e.target.value)}
                placeholder="Bearer Token"
              />
            </label>
          )}

          {form.auth_type === 'none' && (
            <div className="text-xs text-muted-foreground/70">无认证模式，直接访问 API。</div>
          )}

          {(form.auth_type === 'oauth2' || form.auth_type === 'mtls') && (
            <div className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
              {form.auth_type === 'oauth2'
                ? 'OAuth2 需在服务端配置客户端凭证、Token URL 等参数。'
                : 'mTLS 双向认证需在服务端配置客户端证书。'}
            </div>
          )}
        </Section>

        {/* 其他设置 */}
        <Section title="其他设置" defaultOpen={false}>
          <label className="flex items-center gap-2">
            <Switch checked={!!form.enabled} onChange={(v) => set('enabled')(v)} />
            <span className="text-sm text-muted-foreground">启用设备</span>
          </label>
        </Section>

        {/* 弹窗内测试结果 */}
        {testResult && (
          <div
            className={`rounded-md border px-4 py-3 ${
              testResult.success
                ? 'border-success/40 bg-success/10'
                : 'border-destructive/40 bg-destructive/10'
            }`}
          >
            <div className="flex items-center gap-2">
              {testResult.success ? (
                <Check className="h-4 w-4 text-success" />
              ) : (
                <X className="h-4 w-4 text-destructive" />
              )}
              <span
                className={`text-sm ${
                  testResult.success ? 'text-success' : 'text-destructive'
                }`}
              >
                {testResult.success
                  ? `连接成功 · 延迟 ${testResult.latency_ms ?? testResult.latency ?? '-'}ms`
                  : '连接失败'}
              </span>
            </div>
            {!testResult.success && testResult.error && (
              <pre className="mt-2 overflow-auto rounded bg-background p-2 font-mono text-[11px] text-destructive ring-1 ring-border">
                {testResult.error}
              </pre>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}

// ============ 参数行编辑器 ============
function ParamsEditor({ value, onChange }) {
  const rows = useMemo(() => {
    const arr = safeParseJson(value, [])
    return Array.isArray(arr) ? arr : []
  }, [value])

  const update = (next) => {
    onChange(JSON.stringify(next, null, 2))
  }
  const addRow = () => {
    update([...rows, { name: '', type: 'string', required: false, default: '', description: '' }])
  }
  const removeRow = (idx) => {
    update(rows.filter((_, i) => i !== idx))
  }
  const editRow = (idx, patch) => {
    update(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  return (
    <div className="flex flex-col gap-2">
      {rows.length === 0 && (
        <div className="rounded-md border border-dashed border-border bg-background/40 px-3 py-3 text-center text-xs text-muted-foreground/70">
          暂无参数，点击下方按钮添加
        </div>
      )}
      {rows.map((row, idx) => (
        <div
          key={idx}
          className="grid grid-cols-[1fr_100px_60px_1fr_28px] items-center gap-2 rounded-md border border-border bg-background/60 px-2 py-1.5"
        >
          <input
            className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground outline-none focus:border-primary"
            placeholder="参数名"
            value={row.name}
            onChange={(e) => editRow(idx, { name: e.target.value })}
          />
          <select
            className="rounded border border-border bg-background px-1 py-1 text-xs text-foreground outline-none focus:border-primary"
            value={row.type}
            onChange={(e) => editRow(idx, { type: e.target.value })}
          >
            {PARAM_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              className="h-3 w-3 accent-primary"
              checked={!!row.required}
              onChange={(e) => editRow(idx, { required: e.target.checked })}
            />
            必填
          </label>
          <input
            className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground outline-none focus:border-primary"
            placeholder="默认值 / 描述"
            value={`${row.default ?? ''}${row.description ? ` | ${row.description}` : ''}`}
            onChange={(e) => {
              const [def, desc] = e.target.value.split('|').map((s) => s.trim())
              editRow(idx, { default: def || '', description: desc || '' })
            }}
          />
          <button
            type="button"
            onClick={() => removeRow(idx)}
            className="text-muted-foreground hover:text-destructive"
            title="删除参数"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <button type="button" onClick={addRow} className="btn-secondary btn-sm self-start">
        <Plus className="mr-1 h-3 w-3" /> 添加参数
      </button>
    </div>
  )
}

// ============ 请求头编辑器 ============
function HeadersEditor({ value, onChange }) {
  const rows = useMemo(() => {
    const obj = safeParseJson(value, {})
    if (Array.isArray(obj)) return obj
    return Object.entries(obj).map(([k, v]) => ({ key: k, value: v }))
  }, [value])

  const update = (next) => {
    onChange(JSON.stringify(next, null, 2))
  }
  const addRow = () => {
    update([...rows, { key: '', value: '' }])
  }
  const removeRow = (idx) => {
    update(rows.filter((_, i) => i !== idx))
  }
  const editRow = (idx, patch) => {
    update(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  return (
    <div className="flex flex-col gap-2">
      {rows.length === 0 && (
        <div className="rounded-md border border-dashed border-border bg-background/40 px-3 py-3 text-center text-xs text-muted-foreground/70">
          暂无自定义请求头
        </div>
      )}
      {rows.map((row, idx) => (
        <div
          key={idx}
          className="grid grid-cols-[1fr_1fr_28px] items-center gap-2 rounded-md border border-border bg-background/60 px-2 py-1.5"
        >
          <input
            className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground outline-none focus:border-primary"
            placeholder="Header Key"
            value={row.key}
            onChange={(e) => editRow(idx, { key: e.target.value })}
          />
          <input
            className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground outline-none focus:border-primary"
            placeholder="Header Value"
            value={row.value}
            onChange={(e) => editRow(idx, { value: e.target.value })}
          />
          <button
            type="button"
            onClick={() => removeRow(idx)}
            className="text-muted-foreground hover:text-destructive"
            title="删除"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <button type="button" onClick={addRow} className="btn-secondary btn-sm self-start">
        <Plus className="mr-1 h-3 w-3" /> 添加请求头
      </button>
    </div>
  )
}

// ============ 动作表单弹窗 ============
function ActionFormModal({ open, initial, onClose, onSubmit, saving }) {
  const [form, setForm] = useState(() => buildInitialActionForm(initial))
  const [dirty, setDirty] = useState(false)
  const bypassGuard = useUnsavedChanges(dirty)

  useEffect(() => {
    if (open) {
      setForm(buildInitialActionForm(initial))
      setDirty(false)
    }
  }, [open, initial])

  function buildInitialActionForm(src) {
    return {
      name: '',
      action_type: 'block_ip',
      http_method: 'POST',
      api_path: '',
      params_schema: '[]',
      headers: '{}',
      body_template: '',
      auth_type: 'inherit',
      enabled: true,
      description: '',
      category: 'block',
      risk_level: 'readonly',
      example_payload: '',
      example_response: '',
      version: 1,
      ...(src || {}),
    }
  }

  const set = (k) => (v) => {
    setForm((p) => ({ ...p, [k]: v }))
    setDirty(true)
  }

  const handleClose = () => {
    setDirty(false)
    bypassGuard()
    onClose()
  }

  const handleSubmit = async () => {
    if (!form.name) {
      toast.warning('请填写动作名称')
      return false
    }
    // 验证 params_schema
    const params = safeParseJson(form.params_schema, null)
    if (params === null) {
      toast.error('参数定义不是合法的 JSON')
      return false
    }
    const headers = safeParseJson(form.headers, null)
    if (headers === null) {
      toast.error('请求头不是合法的 JSON')
      return false
    }
    // 编辑时版本号 +1
    const finalForm = { ...form }
    if (initial) {
      finalForm.version = (initial.version || 1) + 1
    }
    const ok = await onSubmit(finalForm)
    if (ok) {
      setDirty(false)
      bypassGuard()
    }
  }

  // 从 body_template 中提取 {{param}} 占位符
  const bodyPlaceholders = useMemo(() => {
    const matches = (form.body_template || '').matchAll(/\{\{(\w+)\}\}/g)
    const set = new Set()
    for (const m of matches) set.add(m[1])
    return Array.from(set)
  }, [form.body_template])

  return (
    <Modal
      open={open}
      title={initial ? `编辑动作：${initial.name || ''}` : '新建设备动作'}
      onClose={handleClose}
      maxWidth="max-w-4xl"
      footer={
        <>
          <button type="button" onClick={handleClose} className="btn-secondary">
            取消
          </button>
          <button type="button" onClick={handleSubmit} disabled={saving} className="btn-primary">
            {saving ? '保存中…' : '保存'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {/* 基础信息 */}
        <Section title="基础信息">
          <div className="grid grid-cols-2 gap-3">
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">
                动作名称 <span className="text-destructive">*</span>
              </div>
              <input
                className={inputCls}
                value={form.name}
                onChange={(e) => set('name')(e.target.value)}
                placeholder="如：封禁 IP"
              />
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">动作类型</div>
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
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">分类</div>
              <select
                className={inputCls}
                value={form.category}
                onChange={(e) => set('category')(e.target.value)}
              >
                {Object.entries(ACTION_CATEGORIES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">风险等级</div>
              <select
                className={inputCls}
                value={form.risk_level}
                onChange={(e) => set('risk_level')(e.target.value)}
              >
                {RISK_OPTIONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="col-span-2">
              <div className="mb-1 text-xs font-medium text-muted-foreground">动作描述</div>
              <input
                className={inputCls}
                value={form.description}
                onChange={(e) => set('description')(e.target.value)}
                placeholder="可选，说明此动作的作用"
              />
            </label>
          </div>
        </Section>

        {/* 请求配置 */}
        <Section title="请求配置">
          <div className="grid grid-cols-[110px_1fr_140px] gap-3">
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">HTTP 方法</div>
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
              <div className="mb-1 text-xs font-medium text-muted-foreground">API 路径</div>
              <input
                className={inputCls}
                value={form.api_path}
                onChange={(e) => set('api_path')(e.target.value)}
                placeholder="/block/ip"
              />
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">认证方式</div>
              <select
                className={inputCls}
                value={form.auth_type}
                onChange={(e) => set('auth_type')(e.target.value)}
              >
                {ACTION_AUTH_TYPES.map((a) => (
                  <option key={a.value} value={a.value}>
                    {a.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </Section>

        {/* 参数定义 */}
        <Section title="参数定义" hint="表单化编辑，自动生成 JSON Schema">
          <ParamsEditor
            value={form.params_schema}
            onChange={(v) => set('params_schema')(v)}
          />
        </Section>

        {/* 请求头 */}
        <Section title="请求头" defaultOpen={false}>
          <HeadersEditor value={form.headers} onChange={(v) => set('headers')(v)} />
        </Section>

        {/* 请求体模板 */}
        <Section title="请求体模板" defaultOpen={false}>
          <label className="block">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">
                请求体模板（支持 {`{{参数名}}`} 占位符）
              </span>
              {bodyPlaceholders.length > 0 && (
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
                  <span>检测到变量：</span>
                  {bodyPlaceholders.map((p) => (
                    <code
                      key={p}
                      className="rounded bg-primary/10 px-1 py-0.5 font-mono text-primary"
                    >
                      {`{{${p}}}`}
                    </code>
                  ))}
                </div>
              )}
            </div>
            <textarea
              className={`${textareaCls} text-xs`}
              rows={5}
              value={form.body_template}
              onChange={(e) => set('body_template')(e.target.value)}
              placeholder={'{"ip": "{{ip}}", "duration": {{duration}}}'}
            />
          </label>
        </Section>

        {/* 示例与返回 */}
        <Section title="示例与返回" defaultOpen={false}>
          <label className="mb-3 block">
            <div className="mb-1 text-xs font-medium text-muted-foreground">示例 Payload</div>
            <textarea
              className={`${textareaCls} text-xs`}
              rows={3}
              value={form.example_payload}
              onChange={(e) => set('example_payload')(e.target.value)}
              placeholder='{"ip": "192.168.1.1"}'
            />
          </label>
          <label className="block">
            <div className="mb-1 text-xs font-medium text-muted-foreground">示例返回结果</div>
            <textarea
              className={`${textareaCls} text-xs`}
              rows={3}
              value={form.example_response}
              onChange={(e) => set('example_response')(e.target.value)}
              placeholder='{"code": 0, "message": "ok"}'
            />
          </label>
        </Section>

        {/* 其他 */}
        <Section title="其他" defaultOpen={false}>
          <label className="flex items-center gap-2">
            <Switch checked={!!form.enabled} onChange={(v) => set('enabled')(v)} />
            <span className="text-sm text-muted-foreground">启用此动作</span>
          </label>
          {initial && (
            <div className="mt-2 text-[11px] text-muted-foreground/70">
              当前版本：v{initial.version || 1}（保存后将升级为 v{(initial.version || 1) + 1}）
            </div>
          )}
        </Section>
      </div>
    </Modal>
  )
}

// ============ 模板选择弹窗 ============
function TemplateModal({ open, templates, onClose, onSelect }) {
  const [loading, setLoading] = useState(false)
  return (
    <Modal
      open={open}
      title="从模板创建设备"
      onClose={onClose}
      maxWidth="max-w-4xl"
      footer={
        <button type="button" onClick={onClose} className="btn-secondary">
          取消
        </button>
      }
    >
      {loading ? (
        <div className="flex h-40 items-center justify-center text-sm text-muted-foreground/70">
          加载中...
        </div>
      ) : !templates || templates.length === 0 ? (
        <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted-foreground/70">
          <Files className="h-8 w-8" />
          <div className="text-sm">暂无可用模板</div>
        </div>
      ) : (
        <div className="grid max-h-[60vh] grid-cols-2 gap-3 overflow-y-auto p-1">
          {templates.map((tpl, idx) => (
            <button
              key={tpl.id || idx}
              type="button"
              onClick={() => onSelect(tpl)}
              className="flex flex-col gap-2 rounded-lg border border-border bg-card/40 p-3 text-left transition hover:border-primary hover:bg-primary/5"
            >
              <div className="flex items-center gap-2">
                <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/15 text-primary">
                  <DeviceTypeIcon type={tpl.type} className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-foreground">{tpl.name}</div>
                  <div className="truncate text-[11px] text-muted-foreground/70">
                    {tpl.vendor || '未知厂商'} · {DEVICE_TYPE_LABELS[tpl.type] || tpl.type}
                  </div>
                </div>
              </div>
              {tpl.description && (
                <div className="line-clamp-2 text-[11px] text-muted-foreground/70">
                  {tpl.description}
                </div>
              )}
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span className="rounded bg-primary/15 px-1.5 py-0.5 text-primary">
                  预置 {tpl.action_count ?? tpl.actions?.length ?? 0} 个动作
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </Modal>
  )
}

// ============ 从模板创建设备弹窗 ============
function TemplateCreateModal({ open, template, onClose, onSubmit, saving }) {
  const [form, setForm] = useState({ name: '', api_url: '', api_key: '', vendor: '' })

  useEffect(() => {
    if (open && template) {
      setForm({
        name: template.name || '',
        api_url: '',
        api_key: '',
        vendor: template.vendor || '',
      })
    }
  }, [open, template])

  if (!open || !template) return null

  return (
    <Modal
      open={open}
      title={`从模板创建：${template.name || ''}`}
      onClose={onClose}
      maxWidth="max-w-lg"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={() => onSubmit(form)}
            disabled={saving || !form.name || !form.api_url}
            className="btn-primary"
          >
            {saving ? '创建中…' : '一键创建'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <label>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            设备名称 <span className="text-destructive">*</span>
          </div>
          <input
            className={inputCls}
            value={form.name}
            onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
            placeholder="设备名称"
          />
        </label>
        <label>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            API 地址 <span className="text-destructive">*</span>
          </div>
          <input
            className={inputCls}
            value={form.api_url}
            onChange={(e) => setForm((p) => ({ ...p, api_url: e.target.value }))}
            placeholder="https://10.0.0.1:8443/api"
          />
        </label>
        <label>
          <div className="mb-1 text-xs font-medium text-muted-foreground">API Key</div>
          <input
            className={inputCls}
            type="password"
            value={form.api_key}
            onChange={(e) => setForm((p) => ({ ...p, api_key: e.target.value }))}
            placeholder="API Key"
          />
        </label>
        <label>
          <div className="mb-1 text-xs font-medium text-muted-foreground">厂商</div>
          <input
            className={inputCls}
            value={form.vendor}
            onChange={(e) => setForm((p) => ({ ...p, vendor: e.target.value }))}
            placeholder="厂商"
          />
        </label>
        <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-[11px] text-primary/80">
          将自动创建设备和预置的 {template.action_count ?? template.actions?.length ?? 0} 个动作。
        </div>
      </div>
    </Modal>
  )
}

// ============ 动作测试抽屉 ============
function ActionTestDrawer({ open, action, onClose, onRun, running, result }) {
  const [params, setParams] = useState({})

  useEffect(() => {
    if (open && action) {
      const init = {}
      const schema = safeParseJson(action.params_schema, [])
      schema.forEach((p) => {
        init[p.name] = p.default !== undefined ? p.default : ''
      })
      setParams(init)
    }
  }, [open, action])

  if (!open || !action) return null

  const schema = safeParseJson(action.params_schema, [])

  const renderParamInput = (p) => {
    const val = params[p.name] ?? ''
    const setVal = (v) => setParams((prev) => ({ ...prev, [p.name]: v }))
    if (p.type === 'boolean') {
      return (
        <label className="flex items-center gap-2">
          <Switch checked={!!val} onChange={setVal} />
          <span className="text-xs text-muted-foreground">{val ? 'true' : 'false'}</span>
        </label>
      )
    }
    if (p.type === 'enum' && Array.isArray(p.options)) {
      return (
        <select className={inputCls} value={val} onChange={(e) => setVal(e.target.value)}>
          <option value="">请选择</option>
          {p.options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      )
    }
    return (
      <input
        className={inputCls}
        type={p.type === 'number' ? 'number' : 'text'}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder={p.description || `请输入 ${p.name}`}
      />
    )
  }

  return (
    <div className="fixed inset-0 z-[9000] flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-2xl flex-col bg-background shadow-2xl ring-1 ring-border">
        {/* 头部 */}
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-2">
            <TestTube className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold text-foreground">
              测试动作：{action.name}
            </h2>
            <MethodBadge method={action.http_method} />
            <code className="text-xs text-muted-foreground">{action.api_path}</code>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="flex flex-col gap-4">
            {/* 参数输入 */}
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                参数输入
              </h3>
              {schema.length === 0 ? (
                <div className="rounded-md border border-dashed border-border bg-background/40 px-3 py-3 text-center text-xs text-muted-foreground/70">
                  此动作未定义参数
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  {schema.map((p) => (
                    <label key={p.name}>
                      <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                        <span>{p.name}</span>
                        <code className="rounded bg-secondary px-1 text-[10px] text-muted-foreground/70">
                          {p.type}
                        </code>
                        {p.required && <span className="text-destructive">*</span>}
                        {p.description && (
                          <span className="text-muted-foreground/60">— {p.description}</span>
                        )}
                      </div>
                      {renderParamInput(p)}
                    </label>
                  ))}
                </div>
              )}
            </div>

            {/* 请求预览 */}
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                请求预览
              </h3>
              <pre className="overflow-auto rounded-md bg-card p-3 font-mono text-[11px] text-foreground ring-1 ring-border">
                {action.http_method} {action.api_path}
                {'\n'}
                {(() => {
                  const headers = safeParseJson(action.headers, {})
                  const hArr = Array.isArray(headers)
                    ? headers.map((h) => [h.key, h.value])
                    : Object.entries(headers)
                  return hArr.map(([k, v]) => `${k}: ${v}`).join('\n')
                })()}
                {action.body_template ? '\n\n' + action.body_template.replace(/\{\{(\w+)\}\}/g, (_, k) => params[k] ?? '') : ''}
              </pre>
            </div>

            {/* 响应结果 */}
            {result && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  响应结果
                </h3>
                <div
                  className={`mb-2 flex items-center gap-3 rounded-md border px-3 py-2 ${
                    result.success
                      ? 'border-success/40 bg-success/10'
                      : 'border-destructive/40 bg-destructive/10'
                  }`}
                >
                  <span
                    className={`inline-flex items-center gap-1 text-sm font-medium ${
                      result.success ? 'text-success' : 'text-destructive'
                    }`}
                  >
                    {result.success ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}
                    {result.success ? '成功' : '失败'}
                  </span>
                  {result.status_code != null && (
                    <span className="font-mono text-xs text-muted-foreground">
                      HTTP {result.status_code}
                    </span>
                  )}
                  {result.latency_ms != null && (
                    <span className="font-mono text-xs text-muted-foreground">
                      耗时 {result.latency_ms}ms
                    </span>
                  )}
                </div>
                {result.error && (
                  <div className="mb-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
                    {result.error}
                  </div>
                )}
                <pre className="max-h-72 overflow-auto rounded-md bg-card p-3 font-mono text-[11px] text-foreground ring-1 ring-border">
                  {result.response_body == null
                    ? '(空)'
                    : typeof result.response_body === 'string'
                    ? result.response_body
                    : JSON.stringify(result.response_body, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>

        {/* 底部操作 */}
        <footer className="flex items-center justify-end gap-2 border-t border-border px-6 py-3">
          <button type="button" onClick={onClose} className="btn-secondary btn-sm">
            关闭
          </button>
          <button
            type="button"
            onClick={() => onRun(params)}
            disabled={running}
            className="btn-primary btn-sm"
          >
            {running ? '测试中…' : '开始测试'}
          </button>
        </footer>
      </div>
    </div>
  )
}

// ============ 动作历史弹窗 ============
function ActionHistoryModal({ open, deviceId, actionId, actionName, onClose }) {
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (!deviceId || !actionId) return
    setLoading(true)
    try {
      const res = await devicesApi.actionHistory(deviceId, actionId, 50)
      setHistory(Array.isArray(res) ? res : res?.history || [])
    } catch (err) {
      toast.error(`加载历史失败：${err.message || err}`)
      setHistory([])
    } finally {
      setLoading(false)
    }
  }, [deviceId, actionId])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  return (
    <Modal
      open={open}
      title={`执行历史：${actionName || ''}`}
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={
        <button type="button" onClick={onClose} className="btn-primary">
          关闭
        </button>
      }
    >
      {loading ? (
        <div className="flex h-32 items-center justify-center text-sm text-muted-foreground/70">
          加载中...
        </div>
      ) : history.length === 0 ? (
        <div className="flex h-32 items-center justify-center text-sm text-muted-foreground/70">
          暂无执行记录
        </div>
      ) : (
        <div className="max-h-[60vh] overflow-auto rounded-lg border border-border">
          <table className="w-full table-fixed border-collapse text-sm">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                <th className="w-40 px-3 py-2 text-left font-medium">时间</th>
                <th className="w-20 px-3 py-2 text-left font-medium">状态</th>
                <th className="w-24 px-3 py-2 text-right font-medium">耗时</th>
                <th className="px-3 py-2 text-left font-medium">来源 / 错误</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h, idx) => (
                <tr
                  key={h.id || idx}
                  className={`border-t border-border ${
                    h.status === 'failed' || h.success === false
                      ? 'bg-destructive/5'
                      : idx % 2 === 0
                      ? 'bg-card/30'
                      : ''
                  }`}
                >
                  <td className="px-3 py-2 text-[11px] text-muted-foreground" title={fmtTime(h.created_at)}>
                    {fmtRelative(h.created_at)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        h.status === 'success' || h.success === true
                          ? 'bg-success/20 text-success'
                          : 'bg-destructive/20 text-destructive'
                      }`}
                    >
                      {h.status === 'success' || h.success === true ? '成功' : '失败'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-[11px] text-muted-foreground">
                    {h.latency_ms != null ? `${h.latency_ms}ms` : '-'}
                  </td>
                  <td className="truncate px-3 py-2 text-[11px] text-muted-foreground" title={h.error_message || h.source || ''}>
                    {h.source && <span className="mr-2 text-primary">{h.source}</span>}
                    {h.error_message ? (
                      <span className="text-destructive">{truncate(h.error_message, 60)}</span>
                    ) : (
                      '-'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}

// ============ 调用日志 Tab ============
function CallLogsTab() {
  const [stats, setStats] = useState(null)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [days, setDays] = useState(7)
  const [filters, setFilters] = usePersistedFilters('device_call_logs', {
    search: '',
    deviceId: '',
    source: '',
    status: '',
  })
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLog, setDetailLog] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [statsRes, logsRes] = await Promise.all([
        devicesApi.callLogStats(days),
        devicesApi.callLogs({
          device_id: filters.deviceId || undefined,
          source: filters.source || undefined,
          status: filters.status || undefined,
          limit: 200,
        }),
      ])
      setStats(statsRes)
      setLogs(Array.isArray(logsRes) ? logsRes : logsRes?.logs || logsRes?.items || [])
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [days, filters.deviceId, filters.source, filters.status])

  useEffect(() => {
    load()
  }, [load])

  const openDetail = async (log) => {
    setDetailLog(log)
    setDetailOpen(true)
    if (log.id) {
      setDetailLoading(true)
      try {
        const res = await devicesApi.callLogDetail(log.id)
        setDetailLog({ ...log, ...res })
      } catch {
        // 忽略
      } finally {
        setDetailLoading(false)
      }
    }
  }

  const filteredLogs = useMemo(() => {
    if (!filters.search) return logs
    const q = filters.search.toLowerCase()
    return logs.filter((l) =>
      [l.device_name, l.action_name, l.error_message, l.source_ip]
        .filter(Boolean)
        .some((v) => v.toLowerCase().includes(q))
    )
  }, [logs, filters.search])

  const dayOptions = [1, 7, 14, 30]
  const sourceOptions = [
    { value: '', label: '全部来源' },
    { value: 'manual_test', label: '手动测试' },
    { value: 'workflow', label: '工作流' },
    { value: 'agent', label: '智能体' },
    { value: 'api', label: 'API 调用' },
  ]
  const statusOptions = [
    { value: '', label: '全部状态' },
    { value: 'success', label: '成功' },
    { value: 'failed', label: '失败' },
  ]

  const summary = stats || {}
  const totalCalls = summary.total_calls ?? 0
  const successRate = summary.success_rate ?? 0
  const avgLatency = summary.avg_latency_ms ?? 0
  const failedCount = summary.failed_count ?? 0
  const topErrors = summary.top_errors || []

  return (
    <div className="flex flex-col gap-4">
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card/60 p-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">时间范围：</span>
          {dayOptions.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                days === d
                  ? 'bg-primary/20 text-primary'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {d} 天
            </button>
          ))}
        </div>
        <button type="button" onClick={load} disabled={loading} className="btn-secondary btn-sm">
          {loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      {error && (
        <div className="w-full rounded-md border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* 统计卡片 */}
      {!loading && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">总调用次数</span>
              <Activity className="h-4 w-4 text-primary" />
            </div>
            <div className="text-2xl font-bold text-foreground">{totalCalls}</div>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">成功率</span>
              <Check className={`h-4 w-4 ${successRate >= 0.9 ? 'text-success' : 'text-warning'}`} />
            </div>
            <div
              className={`text-2xl font-bold ${
                successRate >= 0.9 ? 'text-success' : 'text-warning'
              }`}
            >
              {(successRate * 100).toFixed(1)}
              <span className="text-sm text-muted-foreground">%</span>
            </div>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">平均耗时</span>
              <RefreshCw className="h-4 w-4 text-primary" />
            </div>
            <div className="text-2xl font-bold text-foreground">
              {avgLatency}
              <span className="text-sm text-muted-foreground"> ms</span>
            </div>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">失败次数</span>
              <AlertTriangle className="h-4 w-4 text-destructive" />
            </div>
            <div className="text-2xl font-bold text-destructive">{failedCount}</div>
          </div>
        </div>
      )}

      {/* Top 错误 */}
      {!loading && topErrors.length > 0 && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-destructive">
            <AlertTriangle className="h-4 w-4" />
            Top 错误原因
          </h3>
          <div className="flex flex-col gap-2">
            {topErrors.slice(0, 5).map((e, i) => (
              <div
                key={i}
                className="flex items-start gap-2 rounded-md border border-destructive/20 bg-background/60 px-3 py-2"
              >
                <span className="shrink-0 rounded bg-destructive/20 px-1.5 py-0.5 text-[10px] font-bold text-destructive">
                  #{i + 1}
                </span>
                <code className="flex-1 break-all text-[11px] text-destructive/90">
                  {e.error || e.message}
                </code>
                <span className="shrink-0 text-[11px] font-mono text-muted-foreground">
                  {e.count} 次
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 筛选器 */}
      <FilterBar
        search={{
          value: filters.search,
          onChange: (v) => setFilters({ search: v }),
          placeholder: '搜索设备 / 动作 / 错误信息...',
        }}
        filters={[
          {
            key: 'source',
            label: '来源',
            value: filters.source,
            onChange: (v) => setFilters({ source: v }),
            options: sourceOptions,
          },
          {
            key: 'status',
            label: '状态',
            value: filters.status,
            onChange: (v) => setFilters({ status: v }),
            options: statusOptions,
          },
        ]}
      />

      {/* 明细表格 */}
      {loading ? (
        <div className="flex h-40 items-center justify-center text-sm text-muted-foreground/70">
          加载中...
        </div>
      ) : filteredLogs.length === 0 ? (
        <div className="flex h-60 flex-col items-center justify-center gap-2 text-muted-foreground/70">
          <History className="h-10 w-10" />
          <div className="text-sm">暂无调用记录</div>
        </div>
      ) : (
        <div className="w-full overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[1100px] table-fixed border-collapse text-sm">
            <thead className="bg-card text-muted-foreground">
              <tr>
                <th className="w-40 px-4 py-3 text-left font-medium">时间</th>
                <th className="w-16 px-4 py-3 text-left font-medium">状态</th>
                <th className="px-4 py-3 text-left font-medium">设备 / 动作</th>
                <th className="w-20 px-4 py-3 text-left font-medium">来源</th>
                <th className="w-20 px-4 py-3 text-right font-medium">耗时</th>
                <th className="w-20 px-4 py-3 text-right font-medium">状态码</th>
                <th className="w-32 px-4 py-3 text-left font-medium">来源 IP</th>
                <th className="px-4 py-3 text-left font-medium">错误信息</th>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.slice(0, 200).map((l, idx) => (
                <tr
                  key={l.id || idx}
                  className={`cursor-pointer border-t border-border hover:bg-primary/5 ${
                    l.status === 'failed'
                      ? 'bg-destructive/5'
                      : idx % 2 === 0
                      ? 'bg-card/30'
                      : ''
                  }`}
                  onClick={() => openDetail(l)}
                >
                  <td className="px-4 py-3 text-[11px] text-muted-foreground" title={fmtTime(l.created_at)}>
                    {fmtRelative(l.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        l.status === 'success'
                          ? 'bg-success/20 text-success'
                          : 'bg-destructive/20 text-destructive'
                      }`}
                    >
                      {l.status === 'success' ? '成功' : '失败'}
                    </span>
                  </td>
                  <td className="truncate px-4 py-3 text-foreground">
                    <div className="truncate">{l.device_name || '-'}</div>
                    <div className="truncate text-[11px] text-muted-foreground/70">
                      {l.action_name || '-'}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[11px] text-muted-foreground">
                    {l.source || '-'}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[11px] text-muted-foreground">
                    {l.latency_ms != null ? `${l.latency_ms}ms` : '-'}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[11px] text-muted-foreground">
                    {l.status_code ?? '-'}
                  </td>
                  <td className="truncate px-4 py-3 font-mono text-[11px] text-muted-foreground">
                    {l.source_ip || '-'}
                  </td>
                  <td className="truncate px-4 py-3 text-[11px] text-destructive" title={l.error_message || ''}>
                    {l.error_message ? truncate(l.error_message, 50) : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 详情弹窗 */}
      <Modal
        open={detailOpen}
        title="调用日志详情"
        onClose={() => setDetailOpen(false)}
        maxWidth="max-w-2xl"
        footer={
          <button type="button" onClick={() => setDetailOpen(false)} className="btn-primary">
            关闭
          </button>
        }
      >
        {detailLoading ? (
          <div className="flex h-32 items-center justify-center text-sm text-muted-foreground/70">
            加载中...
          </div>
        ) : detailLog ? (
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[11px] text-muted-foreground">设备</div>
                <div className="text-sm text-foreground">{detailLog.device_name || '-'}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">动作</div>
                <div className="text-sm text-foreground">{detailLog.action_name || '-'}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">状态</div>
                <span
                  className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium ${
                    detailLog.status === 'success'
                      ? 'bg-success/20 text-success'
                      : 'bg-destructive/20 text-destructive'
                  }`}
                >
                  {detailLog.status === 'success' ? '成功' : '失败'}
                </span>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">HTTP 状态码</div>
                <div className="font-mono text-sm text-foreground">{detailLog.status_code ?? '-'}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">耗时</div>
                <div className="font-mono text-sm text-foreground">
                  {detailLog.latency_ms != null ? `${detailLog.latency_ms}ms` : '-'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">来源</div>
                <div className="text-sm text-foreground">{detailLog.source || '-'}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">来源 IP</div>
                <div className="font-mono text-sm text-foreground">{detailLog.source_ip || '-'}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">时间</div>
                <div className="text-sm text-foreground">{fmtTime(detailLog.created_at)}</div>
              </div>
            </div>
            {detailLog.request_summary && (
              <div>
                <div className="mb-1 text-[11px] text-muted-foreground">请求摘要</div>
                <pre className="max-h-40 overflow-auto rounded-md bg-card p-3 font-mono text-[11px] text-foreground ring-1 ring-border">
                  {typeof detailLog.request_summary === 'string'
                    ? detailLog.request_summary
                    : JSON.stringify(detailLog.request_summary, null, 2)}
                </pre>
              </div>
            )}
            {detailLog.response_summary && (
              <div>
                <div className="mb-1 text-[11px] text-muted-foreground">响应摘要</div>
                <pre className="max-h-40 overflow-auto rounded-md bg-card p-3 font-mono text-[11px] text-foreground ring-1 ring-border">
                  {typeof detailLog.response_summary === 'string'
                    ? detailLog.response_summary
                    : JSON.stringify(detailLog.response_summary, null, 2)}
                </pre>
              </div>
            )}
            {detailLog.error_message && (
              <div>
                <div className="mb-1 text-[11px] text-destructive">错误信息</div>
                <pre className="max-h-40 overflow-auto rounded-md border border-destructive/40 bg-destructive/10 p-3 font-mono text-[11px] text-destructive">
                  {detailLog.error_message}
                </pre>
              </div>
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  )
}

// ============ 设备卡片组件 ============
function DeviceCard({
  device,
  expanded,
  onToggleExpand,
  onEdit,
  onDelete,
  onTest,
  testing,
  actions,
  loadingActions,
  onEditAction,
  onDeleteAction,
  onTestAction,
  onToggleAction,
  onNewAction,
  onActionHistory,
  togglingActionId,
}) {
  const api_url = device.api_url || ''
  const tags = parseTags(device.tags)

  return (
    <div
      className={`w-full overflow-hidden rounded-lg border transition ${
        expanded
          ? 'border-primary bg-primary/5'
          : 'border-border bg-card/40 hover:border-primary/50'
      }`}
    >
      {/* 设备行 */}
      <div
        className="flex cursor-pointer items-center gap-3 p-4"
        onClick={() => onToggleExpand(device)}
      >
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary">
          <DeviceTypeIcon type={device.type} className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground">{device.name}</span>
            <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
              #{device.id}
            </span>
            <span className="whitespace-nowrap rounded bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary">
              {DEVICE_TYPE_LABELS[device.type] || device.type}
            </span>
            {device.vendor && (
              <span className="whitespace-nowrap text-[11px] text-muted-foreground/70">
                {device.vendor}
              </span>
            )}
            <StatusBadge status={device.status || (device.enabled ? 'unconfigured' : 'disabled')} />
            {tags.map((t) => (
              <span
                key={t}
                className="whitespace-nowrap rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {t}
              </span>
            ))}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/70">
            <span
              className="truncate"
              title={api_url || '未配置 API 地址'}
              style={{ maxWidth: 360 }}
            >
              {api_url ? (
                truncate(api_url, 30)
              ) : (
                <span className="text-destructive">未配置</span>
              )}
            </span>
            <span>·</span>
            <span>动作 {device.action_count ?? '-'}</span>
            <span>·</span>
            <span>今日 {device.today_call_count ?? 0} 次</span>
            {device.last_heartbeat && (
              <>
                <span>·</span>
                <span title={fmtTime(device.last_heartbeat)}>
                  心跳 {fmtRelative(device.last_heartbeat)}
                </span>
              </>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={() => onTest(device)}
            disabled={testing}
            className="btn-secondary btn-sm"
            title="测试连接"
          >
            {testing ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />}
          </button>
          <button type="button" onClick={() => onEdit(device)} className="btn-secondary btn-sm">
            编辑
          </button>
          <button type="button" onClick={() => onDelete(device)} className="btn-danger btn-sm">
            删除
          </button>
          <button
            type="button"
            onClick={() => onToggleExpand(device)}
            className="btn-secondary btn-sm"
            title={expanded ? '收起' : '展开'}
          >
            {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      {/* 动作列表（展开时显示） */}
      {expanded && (
        <div className="border-t border-border bg-background/40 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              设备动作（{loadingActions ? '...' : actions.length} 个）
            </h3>
            <button type="button" onClick={() => onNewAction()} className="btn-primary btn-sm">
              <Plus className="mr-1 h-3 w-3" /> 新建动作
            </button>
          </div>
          <ActionTable
            actions={actions}
            loading={loadingActions}
            onEdit={onEditAction}
            onDelete={onDeleteAction}
            onTest={onTestAction}
            onToggle={onToggleAction}
            onHistory={onActionHistory}
            togglingActionId={togglingActionId}
          />
        </div>
      )}
    </div>
  )
}

// ============ 动作表格 ============
function ActionTable({
  actions,
  loading,
  onEdit,
  onDelete,
  onTest,
  onToggle,
  onHistory,
  togglingActionId,
}) {
  if (loading) {
    return <div className="py-6 text-center text-xs text-muted-foreground/70">加载中...</div>
  }
  if (actions.length === 0) {
    return <div className="py-6 text-center text-xs text-muted-foreground/60">暂无动作，请新建</div>
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[1100px] table-fixed border-collapse text-sm">
        <thead className="bg-card text-muted-foreground">
          <tr>
            <th className="w-16 px-3 py-2 text-left font-medium">ID</th>
            <th className="w-40 px-3 py-2 text-left font-medium">动作名称</th>
            <th className="w-20 px-3 py-2 text-left font-medium">分类</th>
            <th className="w-16 px-3 py-2 text-left font-medium">方法</th>
            <th className="px-3 py-2 text-left font-medium">API 路径</th>
            <th className="w-16 px-3 py-2 text-left font-medium">版本</th>
            <th className="w-28 px-3 py-2 text-left font-medium">最后调用</th>
            <th className="w-16 px-3 py-2 text-right font-medium">24h调用</th>
            <th className="w-16 px-3 py-2 text-right font-medium">成功率</th>
            <th className="w-16 px-3 py-2 text-right font-medium">平均响应</th>
            <th className="w-16 px-3 py-2 text-center font-medium">风险</th>
            <th className="w-16 px-3 py-2 text-center font-medium">启用</th>
            <th className="w-44 px-3 py-2 text-left font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((a, idx) => {
            const rate = successRate(a)
            return (
              <tr
                key={a.id}
                className={`border-t border-border hover:bg-primary/5 ${idx % 2 === 0 ? 'bg-card/30' : ''}`}
              >
                <td className="px-3 py-2 font-mono text-primary">#{a.id}</td>
                <td className="truncate px-3 py-2 text-foreground" title={a.name}>
                  {a.name}
                </td>
                <td className="px-3 py-2">
                  <CategoryBadge category={a.category} />
                </td>
                <td className="px-3 py-2">
                  <MethodBadge method={a.http_method} />
                </td>
                <td className="truncate px-3 py-2 font-mono text-muted-foreground" title={a.api_path}>
                  {a.api_path || '-'}
                </td>
                <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
                  v{a.version || 1}
                </td>
                <td className="px-3 py-2 text-[11px] text-muted-foreground" title={fmtTime(a.last_call_at)}>
                  {fmtRelative(a.last_call_at)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-[11px] text-foreground">
                  {a.call_count_24h ?? 0}
                </td>
                <td className="px-3 py-2 text-right">
                  {rate == null ? (
                    <span className="text-[11px] text-muted-foreground/60">-</span>
                  ) : (
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        rate >= 0.9
                          ? 'bg-success/20 text-success'
                          : rate >= 0.5
                          ? 'bg-warning/20 text-warning'
                          : 'bg-destructive/20 text-destructive'
                      }`}
                    >
                      {(rate * 100).toFixed(0)}%
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-mono text-[11px] text-muted-foreground">
                  {a.avg_latency_ms != null ? `${a.avg_latency_ms}ms` : '-'}
                </td>
                <td className="px-3 py-2 text-center">
                  <RiskBadge level={a.risk_level} />
                </td>
                <td className="px-3 py-2 text-center">
                  <Switch
                    checked={!!a.enabled}
                    onChange={() => onToggle(a)}
                    disabled={togglingActionId === a.id}
                    size="sm"
                  />
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    <button
                      type="button"
                      onClick={() => onTest(a)}
                      className="btn-secondary btn-sm"
                      title="测试动作"
                    >
                      <TestTube className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onHistory(a)}
                      className="btn-secondary btn-sm"
                      title="执行历史"
                    >
                      <History className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onEdit(a)}
                      className="btn-secondary btn-sm"
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(a)}
                      className="btn-danger btn-sm"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ============ 设备列表行（用于分栏视图和列表视图） ============
function DeviceRow({ device, selected, onClick, onTest, testing }) {
  return (
    <div
      onClick={onClick}
      className={`flex cursor-pointer items-center gap-3 border-b border-border px-3 py-2.5 transition ${
        selected ? 'bg-primary/10' : 'hover:bg-accent'
      }`}
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-primary/15 text-primary">
        <DeviceTypeIcon type={device.type} className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">{device.name}</span>
          <StatusBadge status={device.status || (device.enabled ? 'unconfigured' : 'disabled')} />
        </div>
        <div className="truncate text-[11px] text-muted-foreground/70">
          {device.api_url ? truncate(device.api_url, 30) : '未配置'}
        </div>
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onTest(device)
        }}
        disabled={testing}
        className="text-muted-foreground hover:text-primary disabled:opacity-40"
        title="测试连接"
      >
        {testing ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}

// ============ 主页面 ============
function DeviceManagement() {
  const [activeTab, setActiveTab] = useState('devices') // devices | logs
  const [devices, setDevices] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 视图模式：card / table / split
  const [viewMode, setViewMode] = useState(() => {
    try {
      return localStorage.getItem('soar_device_view') || 'card'
    } catch {
      return 'card'
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('soar_device_view', viewMode)
    } catch {
      // ignore
    }
  }, [viewMode])

  // 筛选
  const [filters, setFilters] = usePersistedFilters('device_mgmt', {
    search: '',
    type: '',
    vendor: '',
    status: '',
    tag: '',
  })

  // 展开状态（记忆展开）
  const [expandedIds, setExpandedIds] = useState(() => {
    try {
      const raw = localStorage.getItem('soar_device_expanded')
      return raw ? JSON.parse(raw) : []
    } catch {
      return []
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('soar_device_expanded', JSON.stringify(expandedIds))
    } catch {
      // ignore
    }
  }, [expandedIds])

  // 选中设备（分栏视图用）
  const [selectedId, setSelectedId] = useState(null)
  const [actions, setActions] = useState([])
  const [loadingActions, setLoadingActions] = useState(false)

  // 弹窗状态
  const [devFormOpen, setDevFormOpen] = useState(false)
  const [devEditing, setDevEditing] = useState(null)
  const [devSaving, setDevSaving] = useState(false)

  const [actFormOpen, setActFormOpen] = useState(false)
  const [actEditing, setActEditing] = useState(null)
  const [actSaving, setActSaving] = useState(false)
  const [actDeviceId, setActDeviceId] = useState(null)

  // 测试连接
  const [testingDeviceId, setTestingDeviceId] = useState(null)
  const [testConnResult, setTestConnResult] = useState(null)
  const [testConnOpen, setTestConnOpen] = useState(false)

  // 动作测试抽屉
  const [testDrawerOpen, setTestDrawerOpen] = useState(false)
  const [testAction, setTestAction] = useState(null)
  const [testRunning, setTestRunning] = useState(false)
  const [testResult, setTestResult] = useState(null)

  // 动作启用切换
  const [togglingActionId, setTogglingActionId] = useState(null)

  // 动作历史
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyAction, setHistoryAction] = useState(null)
  const [historyDeviceId, setHistoryDeviceId] = useState(null)

  // 模板
  const [templates, setTemplates] = useState([])
  const [templateOpen, setTemplateOpen] = useState(false)
  const [templateCreateOpen, setTemplateCreateOpen] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState(null)
  const [templateSaving, setTemplateSaving] = useState(false)

  // 健康检查
  const [healthChecking, setHealthChecking] = useState(false)

  const [tutorialOpen, setTutorialOpen] = useState(false)

  // 导入文件 input ref
  const importInputRef = useRef(null)

  // 加载设备
  const loadDevices = useCallback(async () => {
    setLoading(true)
    try {
      const data = await devicesApi.list()
      const list = Array.isArray(data) ? data : []
      setDevices(list)
      setError('')
      // 失败告警：状态由 online 变为 offline 时提示
      // 通过对比前后状态实现
    } catch (err) {
      setError(err.message || '加载设备失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 用 ref 记录上次状态用于失败告警
  const prevStatusRef = useRef({})
  useEffect(() => {
    if (!devices.length) return
    const prev = prevStatusRef.current
    const next = {}
    devices.forEach((d) => {
      next[d.id] = d.status
      if (prev[d.id] === 'online' && d.status === 'offline') {
        toast.error(`设备「${d.name}」已离线`)
      }
    })
    prevStatusRef.current = next
  }, [devices])

  useEffect(() => {
    loadDevices()
  }, [loadDevices])

  const loadActions = useCallback(async (deviceId) => {
    if (!deviceId) return
    setLoadingActions(true)
    try {
      const data = await devicesApi.listActions(deviceId)
      setActions(Array.isArray(data) ? data : [])
    } catch (err) {
      toast.error(`加载动作失败：${err.message || err}`)
      setActions([])
    } finally {
      setLoadingActions(false)
    }
  }, [])

  const handleToggleExpand = (device) => {
    setExpandedIds((prev) => {
      if (prev.includes(device.id)) {
        return prev.filter((id) => id !== device.id)
      }
      loadActions(device.id)
      return [...prev, device.id]
    })
  }

  // 切换分栏视图选中
  const handleSelectDevice = (device) => {
    setSelectedId(device.id)
    loadActions(device.id)
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
      toast.success(devEditing ? '设备已更新' : '设备已创建')
      return true
    } catch (err) {
      toast.error(`保存失败：${err.message || err}`)
      return false
    } finally {
      setDevSaving(false)
    }
  }

  const handleDeviceDelete = async (device) => {
    const ok = await confirm({
      message: `确定删除设备「${device.name}」吗？将同时删除其下所有动作。`,
      variant: 'danger',
      confirmText: '确定删除',
    })
    if (!ok) return
    try {
      await devicesApi.remove(device.id)
      if (selectedId === device.id) {
        setSelectedId(null)
        setActions([])
      }
      setExpandedIds((prev) => prev.filter((id) => id !== device.id))
      await loadDevices()
      toast.success('设备已删除')
    } catch (err) {
      toast.error(`删除失败：${err.message || err}`)
    }
  }

  // 测试设备连接
  const handleTestDevice = async (device) => {
    setTestingDeviceId(device.id)
    try {
      const res = await devicesApi.test(device.id)
      setTestConnResult({ ...res, deviceName: device.name })
      setTestConnOpen(true)
      await loadDevices()
    } catch (err) {
      setTestConnResult({
        success: false,
        error: err.message || String(err),
        deviceName: device.name,
      })
      setTestConnOpen(true)
      await loadDevices()
    } finally {
      setTestingDeviceId(null)
    }
  }

  // 弹窗内测试设备连接（先保存或直接传表单测试）
  const handleTestInDialog = async (form) => {
    // 如果是编辑模式，直接测试；否则提示先保存
    if (devEditing) {
      const res = await devicesApi.test(devEditing.id)
      return res
    }
    throw new Error('请先保存设备后再测试')
  }

  // 健康检查
  const handleHealthCheck = async () => {
    setHealthChecking(true)
    try {
      const res = await devicesApi.healthCheck()
      toast.success(
        `健康检查完成：${res.healthy ?? res.online ?? 0} 在线 / ${res.abnormal ?? 0} 异常 / 共 ${res.checked ?? res.total ?? 0} 个`
      )
      await loadDevices()
    } catch (err) {
      toast.error(`健康检查失败：${err.message || err}`)
    } finally {
      setHealthChecking(false)
    }
  }

  // 动作保存
  const handleActionSubmit = async (form) => {
    if (!actDeviceId) return false
    setActSaving(true)
    try {
      if (actEditing) {
        await devicesApi.updateAction(actDeviceId, actEditing.id, form)
      } else {
        await devicesApi.createAction(actDeviceId, form)
      }
      setActFormOpen(false)
      setActEditing(null)
      await loadActions(actDeviceId)
      await loadDevices()
      toast.success(actEditing ? '动作已更新' : '动作已创建')
      return true
    } catch (err) {
      toast.error(`保存失败：${err.message || err}`)
      return false
    } finally {
      setActSaving(false)
    }
  }

  const handleActionDelete = async (action) => {
    const ok = await confirm({
      message: `确定删除动作「${action.name}」吗？`,
      variant: 'danger',
      confirmText: '确定删除',
    })
    if (!ok) return
    try {
      await devicesApi.removeAction(actDeviceId, action.id)
      await loadActions(actDeviceId)
      await loadDevices()
      toast.success('动作已删除')
    } catch (err) {
      toast.error(`删除失败：${err.message || err}`)
    }
  }

  // 切换动作启用
  const handleToggleAction = async (action) => {
    setTogglingActionId(action.id)
    try {
      await devicesApi.toggleAction(actDeviceId, action.id)
      await loadActions(actDeviceId)
      toast.success(`动作「${action.name}」已${action.enabled ? '禁用' : '启用'}`)
    } catch (err) {
      toast.error(`切换失败：${err.message || err}`)
    } finally {
      setTogglingActionId(null)
    }
  }

  // 动作测试
  const handleActionTest = async (params) => {
    if (!actDeviceId || !testAction) return
    setTestRunning(true)
    setTestResult(null)
    try {
      const res = await devicesApi.testAction(actDeviceId, testAction.id, params)
      setTestResult(res)
    } catch (err) {
      setTestResult({
        success: false,
        status_code: null,
        response_body: null,
        error: err.message || String(err),
      })
    } finally {
      setTestRunning(false)
    }
  }

  // 打开动作测试抽屉
  const openActionTestDrawer = (action) => {
    setTestAction(action)
    setTestResult(null)
    setTestDrawerOpen(true)
  }

  // 动作历史
  const openActionHistory = (action) => {
    setHistoryAction(action)
    setHistoryDeviceId(actDeviceId)
    setHistoryOpen(true)
  }

  // 新建动作
  const handleNewAction = (deviceId) => {
    const did = deviceId || selectedId || expandedIds[0]
    if (!did) {
      toast.warning('请先选择或展开一个设备')
      return
    }
    setActDeviceId(did)
    setActEditing(null)
    setActFormOpen(true)
  }

  // 编辑动作
  const handleEditAction = (action, deviceId) => {
    setActDeviceId(deviceId || actDeviceId || selectedId)
    setActEditing(action)
    setActFormOpen(true)
  }

  // ============ 模板相关 ============
  const loadTemplates = useCallback(async () => {
    try {
      const res = await devicesApi.templates()
      setTemplates(Array.isArray(res) ? res : res?.templates || [])
    } catch (err) {
      toast.error(`加载模板失败：${err.message || err}`)
    }
  }, [])

  const handleOpenTemplate = async () => {
    await loadTemplates()
    setTemplateOpen(true)
  }

  const handleSelectTemplate = (tpl) => {
    setSelectedTemplate(tpl)
    setTemplateOpen(false)
    setTemplateCreateOpen(true)
  }

  const handleTemplateCreate = async (form) => {
    setTemplateSaving(true)
    try {
      await devicesApi.fromTemplate({
        template_id: selectedTemplate.id,
        name: form.name,
        api_url: form.api_url,
        api_key: form.api_key,
        vendor: form.vendor,
      })
      setTemplateCreateOpen(false)
      setSelectedTemplate(null)
      await loadDevices()
      toast.success('设备已从模板创建')
    } catch (err) {
      toast.error(`创建失败：${err.message || err}`)
    } finally {
      setTemplateSaving(false)
    }
  }

  // ============ 导入导出 ============
  const handleExport = async () => {
    try {
      const data = await devicesApi.export()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `devices-export-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      toast.success('导出成功')
    } catch (err) {
      toast.error(`导出失败：${err.message || err}`)
    }
  }

  const handleImport = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = '' // 清空以便重复导入同名文件
    try {
      const text = await file.text()
      const body = JSON.parse(text)
      await devicesApi.import(body)
      await loadDevices()
      toast.success('导入成功')
    } catch (err) {
      toast.error(`导入失败：${err.message || err}`)
    }
  }

  // ============ 筛选后的设备列表 ============
  const filteredDevices = useMemo(() => {
    let r = devices
    if (filters.search) {
      const q = filters.search.toLowerCase()
      r = r.filter((d) =>
        [d.name, d.vendor, d.type, d.description]
          .filter(Boolean)
          .some((v) => v.toLowerCase().includes(q))
      )
    }
    if (filters.type) r = r.filter((d) => d.type === filters.type)
    if (filters.vendor) r = r.filter((d) => (d.vendor || '').toLowerCase() === filters.vendor.toLowerCase())
    if (filters.status) {
      r = r.filter((d) => (d.status || (d.enabled ? 'unconfigured' : 'disabled')) === filters.status)
    }
    if (filters.tag) {
      r = r.filter((d) => {
        const tags = parseTags(d.tags)
        return tags.includes(filters.tag)
      })
    }
    return r
  }, [devices, filters.search, filters.type, filters.vendor, filters.status, filters.tag])

  // 厂商选项
  const vendorOptions = useMemo(() => {
    const set = new Set()
    devices.forEach((d) => d.vendor && set.add(d.vendor))
    return [{ value: '', label: '全部厂商' }, ...Array.from(set).map((v) => ({ value: v, label: v }))]
  }, [devices])

  // 标签选项
  const tagOptions = useMemo(() => {
    const set = new Set()
    devices.forEach((d) => parseTags(d.tags).forEach((t) => set.add(t)))
    return [{ value: '', label: '全部标签' }, ...Array.from(set).map((t) => ({ value: t, label: t }))]
  }, [devices])

  // 选中的设备（分栏视图）
  const selectedDevice = useMemo(
    () => devices.find((d) => d.id === selectedId),
    [devices, selectedId]
  )

  // 视图模式切换按钮组
  const viewModeButtons = (
    <div className="flex items-center gap-0.5 rounded-md border border-border bg-secondary p-0.5">
      {VIEW_MODES.map((m) => {
        const Icon = m.icon
        return (
          <button
            key={m.value}
            type="button"
            onClick={() => setViewMode(m.value)}
            className={`rounded p-1.5 transition ${
              viewMode === m.value
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            title={m.label}
          >
            <Icon className="h-3.5 w-3.5" />
          </button>
        )
      })}
    </div>
  )

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      <header className="flex items-center justify-between gap-4 border-b border-border bg-card/60 px-6 py-4">
        <div className="flex min-w-0 items-center gap-4">
          <h1 className="text-xl font-semibold text-foreground">设备对接</h1>
          {activeTab === 'devices' && (
            <span className="text-xs text-muted-foreground/70">共 {filteredDevices.length} 台</span>
          )}
        </div>
        {activeTab === 'devices' && (
          <div className="flex shrink-0 items-center gap-2">
            <TutorialButton onClick={() => setTutorialOpen(true)} />
            <button
              type="button"
              onClick={handleHealthCheck}
              disabled={healthChecking}
              className="btn-secondary btn-sm"
              title="对所有启用的设备执行健康检查"
            >
              {healthChecking ? '检查中…' : '健康检查'}
            </button>
            <button type="button" onClick={handleExport} className="btn-secondary btn-sm" title="导出 JSON">
              <Download className="mr-1 h-3.5 w-3.5" /> 导出
            </button>
            <button
              type="button"
              onClick={() => importInputRef.current?.click()}
              className="btn-secondary btn-sm"
              title="导入 JSON"
            >
              <Upload className="mr-1 h-3.5 w-3.5" /> 导入
            </button>
            <input
              ref={importInputRef}
              type="file"
              accept="application/json,.json"
              onChange={handleImport}
              className="hidden"
            />
            <button type="button" onClick={loadDevices} className="btn-secondary btn-sm">
              <RefreshCw className="mr-1 h-3.5 w-3.5" /> 刷新
            </button>
            <button
              type="button"
              onClick={handleOpenTemplate}
              className="btn-secondary btn-sm"
              title="从模板创建设备"
            >
              <Files className="mr-1 h-3.5 w-3.5" /> 从模板
            </button>
            <button
              type="button"
              onClick={() => {
                setDevEditing(null)
                setDevFormOpen(true)
              }}
              className="btn-primary btn-sm"
            >
              <Plus className="mr-1 h-3.5 w-3.5" /> 新建设备
            </button>
          </div>
        )}
      </header>

      {/* Tab 切换 */}
      <div className="flex items-center gap-1 border-b border-border bg-card/30 px-6">
        <button
          type="button"
          onClick={() => setActiveTab('devices')}
          className={`-mb-px border-b-2 px-4 py-3 text-sm transition ${
            activeTab === 'devices'
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          设备管理
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('logs')}
          className={`-mb-px border-b-2 px-4 py-3 text-sm transition ${
            activeTab === 'logs'
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          调用日志
        </button>
      </div>

      <div className="flex-1 overflow-hidden">
        {activeTab === 'logs' ? (
          <div className="h-full overflow-y-auto p-6">
            <CallLogsTab />
          </div>
        ) : (
          <div className="flex h-full flex-col overflow-hidden">
            {/* 工具栏：筛选器 + 视图切换 */}
            <div className="border-b border-border bg-card/30 px-6 py-3">
              <FilterBar
                search={{
                  value: filters.search,
                  onChange: (v) => setFilters({ search: v }),
                  placeholder: '搜索设备名称 / 厂商 / 类型...',
                }}
                filters={[
                  {
                    key: 'type',
                    label: '类型',
                    value: filters.type,
                    onChange: (v) => setFilters({ type: v }),
                    options: [
                      { value: '', label: '全部类型' },
                      ...DEVICE_TYPES.map((t) => ({ value: t.value, label: t.label })),
                    ],
                  },
                  {
                    key: 'vendor',
                    label: '厂商',
                    value: filters.vendor,
                    onChange: (v) => setFilters({ vendor: v }),
                    options: vendorOptions,
                  },
                  {
                    key: 'status',
                    label: '状态',
                    value: filters.status,
                    onChange: (v) => setFilters({ status: v }),
                    options: STATUS_OPTIONS,
                  },
                  {
                    key: 'tag',
                    label: '标签',
                    value: filters.tag,
                    onChange: (v) => setFilters({ tag: v }),
                    options: tagOptions,
                  },
                ]}
                actions={viewModeButtons}
              />
            </div>

            {/* 内容区 */}
            <div className="flex-1 overflow-hidden">
              {error && (
                <div className="m-4 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm text-destructive">
                  {error}
                </div>
              )}

              {loading ? (
                <div className="flex h-40 items-center justify-center text-sm text-muted-foreground/70">
                  加载中...
                </div>
              ) : filteredDevices.length === 0 ? (
                <div className="flex h-60 flex-col items-center justify-center gap-2 text-muted-foreground/70">
                  <Shield className="h-10 w-10" />
                  <div className="text-sm">暂无安全设备，点击右上角「新建设备」</div>
                </div>
              ) : viewMode === 'split' ? (
                // 分栏视图：左设备列表 + 右详情
                <div className="flex h-full">
                  <div className="w-80 shrink-0 overflow-y-auto border-r border-border bg-card/30">
                    {filteredDevices.map((dev) => (
                      <DeviceRow
                        key={dev.id}
                        device={dev}
                        selected={selectedId === dev.id}
                        onClick={() => handleSelectDevice(dev)}
                        onTest={handleTestDevice}
                        testing={testingDeviceId === dev.id}
                      />
                    ))}
                  </div>
                  <div className="flex-1 overflow-y-auto p-6">
                    {selectedDevice ? (
                      <div className="flex flex-col gap-4">
                        {/* 设备详情 */}
                        <div className="rounded-lg border border-border bg-card/40 p-4">
                          <div className="mb-3 flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/15 text-primary">
                              <DeviceTypeIcon type={selectedDevice.type} className="h-5 w-5" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="truncate text-base font-semibold text-foreground">
                                  {selectedDevice.name}
                                </span>
                                <StatusBadge
                                  status={
                                    selectedDevice.status ||
                                    (selectedDevice.enabled ? 'unconfigured' : 'disabled')
                                  }
                                />
                              </div>
                              <div className="mt-0.5 text-xs text-muted-foreground/70">
                                #{selectedDevice.id} · {DEVICE_TYPE_LABELS[selectedDevice.type]} ·{' '}
                                {selectedDevice.vendor || '未知厂商'}
                              </div>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                onClick={() => handleTestDevice(selectedDevice)}
                                disabled={testingDeviceId === selectedDevice.id}
                                className="btn-secondary btn-sm"
                              >
                                {testingDeviceId === selectedDevice.id ? (
                                  <RefreshCw className="mr-1 h-3 w-3 animate-spin" />
                                ) : (
                                  <Wifi className="mr-1 h-3 w-3" />
                                )}
                                测试
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setDevEditing(selectedDevice)
                                  setDevFormOpen(true)
                                }}
                                className="btn-secondary btn-sm"
                              >
                                编辑
                              </button>
                            </div>
                          </div>
                          <div className="grid grid-cols-2 gap-3 text-xs lg:grid-cols-4">
                            <div>
                              <div className="text-muted-foreground/70">API 地址</div>
                              <div
                                className="truncate text-foreground"
                                title={selectedDevice.api_url}
                              >
                                {selectedDevice.api_url || (
                                  <span className="text-destructive">未配置</span>
                                )}
                              </div>
                            </div>
                            <div>
                              <div className="text-muted-foreground/70">动作数</div>
                              <div className="text-foreground">
                                {selectedDevice.action_count ?? '-'}
                              </div>
                            </div>
                            <div>
                              <div className="text-muted-foreground/70">今日调用</div>
                              <div className="text-foreground">
                                {selectedDevice.today_call_count ?? 0}
                              </div>
                            </div>
                            <div>
                              <div className="text-muted-foreground/70">最后心跳</div>
                              <div
                                className="text-foreground"
                                title={fmtTime(selectedDevice.last_heartbeat)}
                              >
                                {fmtRelative(selectedDevice.last_heartbeat)}
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* 动作列表 */}
                        <div className="rounded-lg border border-border bg-card/40 p-4">
                          <div className="mb-3 flex items-center justify-between">
                            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                              设备动作（{loadingActions ? '...' : actions.length} 个）
                            </h3>
                            <button
                              type="button"
                              onClick={() => handleNewAction(selectedDevice.id)}
                              className="btn-primary btn-sm"
                            >
                              <Plus className="mr-1 h-3 w-3" /> 新建动作
                            </button>
                          </div>
                          <ActionTable
                            actions={actions}
                            loading={loadingActions}
                            onEdit={(a) => handleEditAction(a, selectedDevice.id)}
                            onDelete={handleActionDelete}
                            onTest={openActionTestDrawer}
                            onToggle={handleToggleAction}
                            onHistory={openActionHistory}
                            togglingActionId={togglingActionId}
                          />
                        </div>
                      </div>
                    ) : (
                      <div className="flex h-60 flex-col items-center justify-center gap-2 text-muted-foreground/70">
                        <Columns className="h-10 w-10" />
                        <div className="text-sm">请从左侧选择一个设备查看详情</div>
                      </div>
                    )}
                  </div>
                </div>
              ) : viewMode === 'table' ? (
                // 列表视图
                <div className="h-full overflow-y-auto p-6">
                  <div className="overflow-hidden rounded-lg border border-border">
                    <table className="w-full min-w-[1000px] table-fixed border-collapse text-sm">
                      <thead className="bg-card text-muted-foreground">
                        <tr>
                          <th className="w-16 px-4 py-3 text-left font-medium">ID</th>
                          <th className="w-48 px-4 py-3 text-left font-medium">设备名称</th>
                          <th className="w-24 px-4 py-3 text-left font-medium">类型</th>
                          <th className="w-32 px-4 py-3 text-left font-medium">厂商</th>
                          <th className="px-4 py-3 text-left font-medium">API 地址</th>
                          <th className="w-24 px-4 py-3 text-left font-medium">状态</th>
                          <th className="w-20 px-4 py-3 text-right font-medium">动作数</th>
                          <th className="w-20 px-4 py-3 text-right font-medium">今日调用</th>
                          <th className="w-32 px-4 py-3 text-left font-medium">最后心跳</th>
                          <th className="w-44 px-4 py-3 text-left font-medium">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredDevices.map((dev, idx) => (
                          <tr
                            key={dev.id}
                            className={`border-t border-border hover:bg-primary/5 ${
                              idx % 2 === 0 ? 'bg-card/30' : ''
                            }`}
                          >
                            <td className="px-4 py-3 font-mono text-primary">#{dev.id}</td>
                            <td className="truncate px-4 py-3 text-foreground">{dev.name}</td>
                            <td className="truncate px-4 py-3 text-muted-foreground">
                              {DEVICE_TYPE_LABELS[dev.type] || dev.type}
                            </td>
                            <td className="truncate px-4 py-3 text-muted-foreground">
                              {dev.vendor || '-'}
                            </td>
                            <td
                              className="truncate px-4 py-3 font-mono text-xs text-muted-foreground"
                              title={dev.api_url}
                            >
                              {dev.api_url ? (
                                truncate(dev.api_url, 30)
                              ) : (
                                <span className="text-destructive">未配置</span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <StatusBadge
                                status={dev.status || (dev.enabled ? 'unconfigured' : 'disabled')}
                              />
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-foreground">
                              {dev.action_count ?? '-'}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-foreground">
                              {dev.today_call_count ?? 0}
                            </td>
                            <td
                              className="px-4 py-3 text-[11px] text-muted-foreground"
                              title={fmtTime(dev.last_heartbeat)}
                            >
                              {fmtRelative(dev.last_heartbeat)}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex flex-wrap gap-1">
                                <button
                                  type="button"
                                  onClick={() => handleTestDevice(dev)}
                                  disabled={testingDeviceId === dev.id}
                                  className="btn-secondary btn-sm"
                                >
                                  {testingDeviceId === dev.id ? '测试中' : '测试'}
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
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                // 卡片视图（默认）
                <div className="h-full overflow-y-auto p-6">
                  <div className="flex flex-col gap-3">
                    {filteredDevices.map((dev) => (
                      <DeviceCard
                        key={dev.id}
                        device={dev}
                        expanded={expandedIds.includes(dev.id)}
                        onToggleExpand={handleToggleExpand}
                        onEdit={(d) => {
                          setDevEditing(d)
                          setDevFormOpen(true)
                        }}
                        onDelete={handleDeviceDelete}
                        onTest={handleTestDevice}
                        testing={testingDeviceId === dev.id}
                        actions={expandedIds.includes(dev.id) ? actions : []}
                        loadingActions={loadingActions && expandedIds.includes(dev.id)}
                        onEditAction={(a) => {
                          setActDeviceId(dev.id)
                          handleEditAction(a, dev.id)
                        }}
                        onDeleteAction={handleActionDelete}
                        onTestAction={openActionTestDrawer}
                        onToggleAction={handleToggleAction}
                        onNewAction={() => handleNewAction(dev.id)}
                        onActionHistory={openActionHistory}
                        togglingActionId={togglingActionId}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
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
        onTest={handleTestInDialog}
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

      {/* 动作测试抽屉 */}
      <ActionTestDrawer
        open={testDrawerOpen}
        action={testAction}
        onClose={() => {
          setTestDrawerOpen(false)
          setTestAction(null)
          setTestResult(null)
        }}
        onRun={handleActionTest}
        running={testRunning}
        result={testResult}
      />

      {/* 动作历史 */}
      <ActionHistoryModal
        open={historyOpen}
        deviceId={historyDeviceId}
        actionId={historyAction?.id}
        actionName={historyAction?.name}
        onClose={() => {
          setHistoryOpen(false)
          setHistoryAction(null)
        }}
      />

      {/* 设备连接测试结果 */}
      <Modal
        open={testConnOpen}
        title={`连接测试${testConnResult?.deviceName ? `：${testConnResult.deviceName}` : ''}`}
        onClose={() => setTestConnOpen(false)}
        maxWidth="max-w-lg"
        footer={
          <button type="button" onClick={() => setTestConnOpen(false)} className="btn-primary">
            关闭
          </button>
        }
      >
        {testConnResult ? (
          <div className="flex flex-col gap-3">
            <div
              className={`flex items-center gap-2 rounded-md border px-4 py-3 ${
                testConnResult.success
                  ? 'border-success/40 bg-success/10'
                  : 'border-destructive/40 bg-destructive/10'
              }`}
            >
              {testConnResult.success ? (
                <Wifi className="h-4 w-4 text-success" />
              ) : (
                <WifiOff className="h-4 w-4 text-destructive" />
              )}
              <span
                className={`text-sm font-medium ${
                  testConnResult.success ? 'text-success' : 'text-destructive'
                }`}
              >
                {testConnResult.success
                  ? `连接成功 · 延迟 ${testConnResult.latency_ms ?? testConnResult.latency ?? '-'}ms`
                  : '连接失败'}
              </span>
            </div>
            {testConnResult.error && (
              <div>
                <div className="mb-1 text-xs text-muted-foreground/70">错误信息</div>
                <pre className="overflow-auto rounded-md bg-background p-3 font-mono text-xs text-destructive ring-1 ring-border">
                  {testConnResult.error}
                </pre>
              </div>
            )}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground/70">测试中...</div>
        )}
      </Modal>

      {/* 模板选择 */}
      <TemplateModal
        open={templateOpen}
        templates={templates}
        onClose={() => setTemplateOpen(false)}
        onSelect={handleSelectTemplate}
      />

      {/* 从模板创建 */}
      <TemplateCreateModal
        open={templateCreateOpen}
        template={selectedTemplate}
        onClose={() => {
          setTemplateCreateOpen(false)
          setSelectedTemplate(null)
        }}
        onSubmit={handleTemplateCreate}
        saving={templateSaving}
      />

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
