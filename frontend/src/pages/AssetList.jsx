import { useEffect, useState, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Plus, Download, Upload, RefreshCw, Trash2, Pencil, Search,
  X, Tag as TagIcon, ChevronRight, ChevronDown, History, Server, Network, Globe, Boxes,
  Loader2, CheckCircle2, XCircle, SlidersHorizontal, RotateCcw, Copy, Eye,
  Save, Bookmark, MoreVertical,
} from 'lucide-react'
import { assetsApi } from '../api/assets'
import { Modal } from '../components/Dialog'
import { inputCls, inputBaseCls, labelCls } from '../components/property/FormControls'
import {
  PageContainer, Card, DataTable, Pagination, Badge, StatusBadge,
  LoadingState, ErrorState, EmptyState,
} from '../components/ui'
import { toast } from '../store/toastStore'
import { confirm } from '../components/ConfirmDialog'

// ===== 常量映射 =====
const STATUS_LABELS = { in_use: '在用', idle: '闲置', repair: '维修', retired: '报废', lost: '丢失' }
const STATUS_COLORS = { in_use: 'success', idle: 'neutral', repair: 'warning', retired: 'brand', lost: 'danger' }
const CRIT_LABELS = { low: '低', medium: '中', high: '高', critical: '严重' }
const CRIT_COLORS = { low: 'success', medium: 'warning', high: 'warning', critical: 'danger' }

const TEMPLATE_ICONS = { host_asset: Server, network_segment: Network, egress_ip: Globe }

// 从资产记录按字段定义取值
function getFieldValue(rec, fdef) {
  if (!rec || !fdef) return ''
  const mappedTo = fdef.mapped_to || 'extra'
  if (typeof mappedTo === 'string' && mappedTo.startsWith('standard:')) {
    const col = mappedTo.split(':', 2)[1]
    return rec[col] ?? ''
  }
  const extra = rec.extra_fields || {}
  return extra[fdef.key] ?? ''
}

// 动态表单字段渲染
function FieldInput({ fdef, value, onChange, fieldOptions }) {
  const ftype = fdef.type || 'text'
  const placeholder = fdef.placeholder || ''
  const common = {
    className: inputCls,
    value: value ?? '',
    onChange: (e) => onChange(e.target.value),
    placeholder,
  }
  if (ftype === 'select') {
    return (
      <select {...common}>
        <option value="">{fdef.placeholder || '请选择'}</option>
        {(fdef.options || []).map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    )
  }
  if (ftype === 'textarea') {
    return <textarea {...common} rows={3} />
  }
  if (ftype === 'number') {
    return <input type="number" {...common} />
  }
  if (ftype === 'date') {
    return <input type="date" {...common} />
  }
  // text / ip / cidr
  return <input type="text" {...common} />
}

// ===== 动态表单弹窗 =====
function AssetFormModal({ open, template, templates, initial, onClose, onSubmit, fieldOptions }) {
  const [fields, setFields] = useState({})
  const [tagIds, setTagIds] = useState([])
  const [tags, setTags] = useState([])
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  // 「全部」Tab 下 activeTemplate 为 null，编辑时按记录自身 type_code 匹配模板
  const effTemplate = useMemo(() => {
    if (!initial) return template || null
    if (template && template.code === initial.type_code) return template
    return (templates || []).find((t) => t.code === initial.type_code) || template || null
  }, [template, templates, initial])

  useEffect(() => {
    if (!open || !effTemplate) return
    // 初始化字段值
    const init = {}
    for (const f of (effTemplate.fields || [])) {
      const v = initial ? getFieldValue(initial, f) : (f.default || '')
      init[f.key] = v ?? ''
    }
    setFields(init)
    setTagIds(initial?.tags?.map((t) => t.id) || [])
    setErr('')
    // 加载标签列表
    assetsApi.listTags().then(setTags).catch(() => {})
  }, [open, effTemplate, initial])

  const fieldDefs = useMemo(
    () => (effTemplate?.fields || []).slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)),
    [effTemplate]
  )

  const handleSubmit = async () => {
    setSaving(true)
    setErr('')
    try {
      // 校验必填
      for (const f of fieldDefs) {
        if (f.required && !(fields[f.key]?.toString().trim())) {
          throw new Error(`"${f.label}" 为必填项`)
        }
      }
      await onSubmit({ fields, tag_ids: tagIds })
      onClose()
    } catch (e) {
      setErr(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (!effTemplate) return null

  return (
    <Modal
      open={open}
      title={initial ? `编辑${effTemplate.name}` : `新增${effTemplate.name}`}
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">取消</button>
          <button type="button" onClick={handleSubmit} disabled={saving} className="btn-primary btn-sm">
            {saving ? '保存中...' : '保存'}
          </button>
        </>
      }
    >
      {err && (
        <div className="mb-3 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-xs text-danger">
          {err}
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        {fieldDefs.map((f) => (
          <div key={f.key} className={f.width === 'full' ? 'col-span-2' : ''}>
            <label className={labelCls}>
              {f.label}
              {f.required && <span className="ml-0.5 text-danger">*</span>}
              {f.unique && <span className="ml-1 text-[10px] text-muted-foreground">(标识)</span>}
            </label>
            <FieldInput
              fdef={f}
              value={fields[f.key]}
              onChange={(v) => setFields((p) => ({ ...p, [f.key]: v }))}
              fieldOptions={fieldOptions}
            />
          </div>
        ))}
      </div>
      {/* 标签 */}
      <div className="mt-4 border-t border-border pt-3">
        <label className={labelCls}>标签</label>
        <div className="flex flex-wrap gap-2">
          {tags.length === 0 && <span className="text-xs text-muted-foreground">暂无标签，可在类型模板页创建</span>}
          {tags.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() =>
                setTagIds((p) => (p.includes(t.id) ? p.filter((x) => x !== t.id) : [...p, t.id]))
              }
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                tagIds.includes(t.id)
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-border text-muted-foreground hover:border-primary/40'
              }`}
            >
              {t.name}
            </button>
          ))}
        </div>
      </div>
    </Modal>
  )
}

// ===== 详情抽屉 =====
function DetailDrawer({ open, record, template, templates, onClose, onEdit, onDelete, canManage, canDelete }) {
  const [changes, setChanges] = useState([])
  const [loadingChanges, setLoadingChanges] = useState(false)

  useEffect(() => {
    if (!open || !record) return
    setLoadingChanges(true)
    assetsApi
      .listChanges(record.id)
      .then(setChanges)
      .catch(() => setChanges([]))
      .finally(() => setLoadingChanges(false))
  }, [open, record])

  if (!record) return null
  // 「全部」Tab 下 activeTemplate 为 null，需按记录自身的 type_code 查找对应模板
  const recordTemplate =
    template && template.code === record.type_code
      ? template
      : (templates || []).find((t) => t.code === record.type_code) || null
  const fieldDefs = (recordTemplate?.fields || [])
    .slice()
    .sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))

  return (
    <>
      {/* 遮罩 */}
      {open && (
        <div
          className="fixed inset-0 z-drawer bg-black/40 backdrop-blur-sm"
          onClick={onClose}
        />
      )}
      {/* 抽屉 */}
      <div
        className={`fixed right-0 top-0 z-drawer flex h-screen w-full max-w-xl flex-col border-l border-border bg-card shadow-2xl transition-transform duration-200 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-foreground">
              {record.name || record.identifier || `资产 #${record.id}`}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {recordTemplate?.name || record.type_code || '未分类'} · {record.identifier}
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-accent">
            <X className="h-4 w-4" />
          </button>
        </div>
        {/* 内容 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {/* 字段信息 */}
          <div className="mb-5">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              字段信息
            </h3>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              {fieldDefs.map((f) => {
                const v = getFieldValue(record, f)
                const isStatus = f.key === 'status' || f.mapped_to === 'standard:status'
                const isCrit = f.mapped_to === 'standard:criticality'
                return (
                  <div key={f.key} className="flex flex-col">
                    <span className="text-[11px] text-muted-foreground/70">{f.label}</span>
                    {isStatus ? (
                      <StatusBadge color={STATUS_COLORS[record.status] || 'neutral'} label={STATUS_LABELS[record.status] || record.status || '-'} />
                    ) : isCrit ? (
                      <StatusBadge color={CRIT_COLORS[record.criticality] || 'neutral'} label={CRIT_LABELS[record.criticality] || record.criticality || '-'} />
                    ) : (
                      <span className={`mt-0.5 text-sm text-foreground ${f.type === 'ip' || f.type === 'cidr' ? 'font-mono' : ''}`}>
                        {v === '' || v == null ? '-' : String(v)}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
          {/* 标签 */}
          {record.tags?.length > 0 && (
            <div className="mb-5">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">标签</h3>
              <div className="flex flex-wrap gap-1.5">
                {record.tags.map((t) => (
                  <Badge key={t.id} variant="brand">{t.name}</Badge>
                ))}
              </div>
            </div>
          )}
          {/* 变更历史时间线 */}
          <div>
            <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <History className="h-3.5 w-3.5" /> 变更历史
            </h3>
            {loadingChanges ? (
              <div className="py-4 text-center text-xs text-muted-foreground">加载中...</div>
            ) : changes.length === 0 ? (
              <div className="py-4 text-center text-xs text-muted-foreground">暂无变更记录</div>
            ) : (
              <div className="relative space-y-3 pl-4">
                <div className="absolute left-[5px] top-1 bottom-1 w-px bg-border" />
                {changes.slice(0, 30).map((c) => (
                  <div key={c.id} className="relative">
                    <div className="absolute -left-[11px] top-1 h-2.5 w-2.5 rounded-full border-2 border-card bg-primary" />
                    <div className="text-xs text-foreground">{c.summary || c.action}</div>
                    <div className="mt-0.5 text-[10px] text-muted-foreground">
                      {c.username || '系统'} · {fmtTime(c.created_at)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        {/* 底部操作 */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <button type="button" onClick={onClose} className="btn-secondary btn-sm">关闭</button>
          {canManage && (
            <button type="button" onClick={() => onEdit(record)} className="btn-primary btn-sm flex items-center gap-1">
              <Pencil className="h-3.5 w-3.5" /> 编辑
            </button>
          )}
          {canDelete && (
            <button type="button" onClick={() => onDelete(record)} className="btn-danger btn-sm flex items-center gap-1">
              <Trash2 className="h-3.5 w-3.5" /> 删除
            </button>
          )}
        </div>
      </div>
    </>
  )
}

function fmtTime(t) {
  if (!t) return '-'
  try { return new Date(t).toLocaleString('zh-CN', { hour12: false }) } catch { return t }
}

// 复制文本到剪贴板
function copyText(text) {
  if (!text) return
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => toast.success(`已复制：${text}`)).catch(() => {})
  } else {
    const ta = document.createElement('textarea')
    ta.value = text; document.body.appendChild(ta); ta.select()
    try { document.execCommand('copy'); toast.success(`已复制：${text}`) } catch { /* ignore */ }
    document.body.removeChild(ta)
  }
}

// 标签色块：优先用标签自带 color，否则用品牌色
function TagChip({ tag }) {
  const style = tag.color ? { backgroundColor: tag.color + '20', color: tag.color, borderColor: tag.color + '50' } : null
  return (
    <span
      className="inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium"
      style={style || { borderColor: 'rgb(var(--primary) / 0.3)', backgroundColor: 'rgb(var(--primary) / 0.1)', color: 'rgb(var(--primary))' }}
    >
      {tag.name}
    </span>
  )
}

// 长文本截断（hover 显示完整内容）
function TruncateCell({ text, maxWidth = 160, mono = false }) {
  const v = text == null || text === '' ? '-' : String(text)
  if (v === '-') return <span className="text-xs text-muted-foreground">-</span>
  return (
    <span
      className={`block truncate text-xs text-foreground ${mono ? 'font-mono' : ''}`}
      style={{ maxWidth: `${maxWidth}px` }}
      title={v}
    >
      {v}
    </span>
  )
}

// 筛选条件 Tag（支持单个删除）
function FilterChip({ label, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] text-primary">
      {label}
      <button type="button" onClick={onRemove} className="hover:text-destructive"><X className="h-2.5 w-2.5" /></button>
    </span>
  )
}

// 骨架屏（表格加载占位）
function SkeletonRows({ rows = 8, cols = 8 }) {
  return (
    <div className="w-full">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex border-b border-border/50 px-4 py-3" style={{ animationDelay: `${i * 60}ms` }}>
          {Array.from({ length: cols }).map((__, j) => (
            <div key={j} className="flex-1 px-2">
              <div className="h-3.5 animate-pulse rounded bg-muted" style={{ width: `${40 + Math.random() * 50}%` }} />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// 格式化文件大小
function fmtSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

// 导入进度条组件
// phase: 'uploading'（真实上传百分比） | 'processing'（服务器处理，不确定） | 'done' | 'error'
function ImportProgressBar({ progress, fileName }) {
  const { phase, percent, loaded, total } = progress
  // 状态文案与图标
  let icon, label, percentText
  if (phase === 'uploading') {
    icon = <Upload className="h-4 w-4 text-primary" />
    label = `上传中${fileName ? ` · ${fileName}` : ''}${total ? ` · ${fmtSize(loaded)} / ${fmtSize(total)}` : ''}`
    percentText = `${percent}%`
  } else if (phase === 'processing') {
    icon = <Loader2 className="h-4 w-4 animate-spin text-primary" />
    label = '上传完成，服务器正在解析并写入数据库...'
    percentText = ''
  } else if (phase === 'done') {
    icon = <CheckCircle2 className="h-4 w-4 text-success" />
    label = '导入完成'
    percentText = '100%'
  } else {
    icon = <XCircle className="h-4 w-4 text-danger" />
    label = '导入失败'
    percentText = ''
  }
  // 进度条宽度与配色
  const width = phase === 'uploading' ? `${percent}%`
    : phase === 'done' ? '100%'
    : phase === 'error' ? '100%'
    : '100%' // processing: 满宽 + 动画
  const barColor = phase === 'done' ? 'bg-success'
    : phase === 'error' ? 'bg-danger'
    : 'bg-primary'
  const isProcessing = phase === 'processing'
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <div className="mb-2 flex items-center justify-between gap-2 text-xs">
        <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
          {icon}
          <span className="truncate">{label}</span>
        </span>
        {percentText && <span className="shrink-0 font-medium text-foreground">{percentText}</span>}
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full transition-all duration-300 ease-out ${barColor} ${
            isProcessing ? 'animate-pulse opacity-80' : ''
          }`}
          style={{ width }}
        />
        {isProcessing && (
          // 处理阶段：叠加一个左右滑动的亮色块，表达"正在进行中"
          // keyframes 与 .animate-indeterminate 定义在 index.css 全局
          <div className="animate-indeterminate absolute inset-y-0 left-0 w-1/3 rounded-full bg-primary/40" />
        )}
      </div>
    </div>
  )
}

// ===== 导入弹窗 =====
function ImportModal({ open, template, onClose, onDone }) {
  const [file, setFile] = useState(null)
  const [strategy, setStrategy] = useState('skip')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [err, setErr] = useState('')
  // 导入进度：{ phase: 'idle'|'uploading'|'processing'|'done'|'error', percent, loaded, total }
  const [progress, setProgress] = useState({ phase: 'idle', percent: 0 })

  useEffect(() => {
    if (open) { setFile(null); setResult(null); setErr(''); setProgress({ phase: 'idle', percent: 0 }) }
  }, [open])

  const handleImport = async () => {
    if (!file) { setErr('请选择文件'); return }
    setLoading(true); setErr(''); setResult(null)
    setProgress({ phase: 'uploading', percent: 0 })
    try {
      const res = await assetsApi.importAssetsWithProgress(
        file, strategy, template?.code,
        (p) => setProgress(p),
      )
      setResult(res)
      setProgress({ phase: 'done', percent: 100 })
      onDone?.()
    } catch (e) {
      setErr(e.message || '导入失败')
      setProgress((p) => ({ ...p, phase: 'error' }))
    } finally { setLoading(false) }
  }

  return (
    <Modal
      open={open}
      title={`导入资产${template ? ` · ${template.name}` : ''}`}
      onClose={onClose}
      maxWidth="max-w-lg"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">关闭</button>
          <button type="button" onClick={handleImport} disabled={loading || !file} className="btn-primary btn-sm flex items-center gap-1.5">
            {loading ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 导入中...</> : '开始导入'}
          </button>
        </>
      }
    >
      {err && <div className="mb-3 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-xs text-danger">{err}</div>}
      <div className="space-y-3">
        <div>
          <label className={labelCls}>选择文件（CSV / Excel）</label>
          <input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-xs file:text-primary-foreground" />
        </div>
        <div>
          <label className={labelCls}>冲突策略</label>
          <select className={inputCls} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="skip">跳过已存在</option>
            <option value="overwrite">覆盖已存在</option>
            <option value="error">遇冲突报错中止</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => assetsApi.downloadImportTemplate(template?.code)} className="btn-secondary btn-sm flex items-center gap-1">
            <Download className="h-3.5 w-3.5" /> 下载模板
          </button>
          {template && (
            <span className="text-[11px] text-muted-foreground">
              模板将按「{template.name}」字段映射，标识字段为「{template.identifier_field}」
            </span>
          )}
        </div>
        {/* 导入进度条 */}
        {progress.phase !== 'idle' && (
          <ImportProgressBar progress={progress} fileName={file?.name} />
        )}
        {result && (
          <div className="rounded-md border border-border bg-muted/30 p-3 text-xs">
            <div className="mb-1 font-medium text-foreground">导入结果</div>
            <div className="grid grid-cols-2 gap-1 text-muted-foreground">
              <span>总计：{result.total}</span>
              <span className="text-success">新增：{result.inserted}</span>
              <span className="text-primary">更新：{result.updated}</span>
              <span className="text-warning">跳过：{result.skipped}</span>
            </div>
            {result.errors?.length > 0 && (
              <div className="mt-2 max-h-32 overflow-y-auto border-t border-border pt-2 text-danger">
                {result.errors.slice(0, 20).map((e, i) => (
                  <div key={i}>第{e.row}行：{e.msg}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}

// ===== 聚合分组表格（allow_aggregate=true 时使用）=====
// 同标识（如网段）的多条记录合并为一个可展开的分组，展开后显示各使用单位子行。
// 复用 columns 定义渲染子行单元格，保持与非聚合表格一致的列展示。
function AggregateTable({ columns, data, selected, onToggleRow, onToggleGroup, allGroupChecked, onRowClick }) {
  // 按 identifier 分组（保持原顺序）
  const groups = useMemo(() => {
    const map = new Map()
    for (const row of data) {
      const key = row.identifier || '(空)'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(row)
    }
    return Array.from(map.entries()).map(([identifier, records]) => ({ identifier, records }))
  }, [data])

  const [expanded, setExpanded] = useState(() => new Set())
  // 切换分组展开/收起
  const toggleExpand = (identifier) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(identifier)) next.delete(identifier)
      else next.add(identifier)
      return next
    })
  }

  // 过滤掉选择列和标签列用于组头汇总展示（组头只展示标识 + 数量）
  const dataColumns = columns.filter((c) => !c.key?.startsWith('__'))

  if (groups.length === 0) return null

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground">
            {columns.map((col) => (
              <th key={col.key || col.header} className="whitespace-nowrap px-4 py-3 font-medium">
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const isOpen = expanded.has(group.identifier)
            const groupIds = group.records.map((r) => r.id)
            const groupChecked = groupIds.every((id) => selected.has(id))
            const groupSome = groupIds.some((id) => selected.has(id))
            // 组头行：取组内第一条记录的列值作为汇总展示（标识列显示 identifier + 数量徽章）
            const headRow = group.records[0]
            return (
              <FragmentGroup
                key={group.identifier}
                group={group}
                isOpen={isOpen}
                onToggleExpand={() => toggleExpand(group.identifier)}
                columns={columns}
                dataColumns={dataColumns}
                headRow={headRow}
                groupChecked={groupChecked}
                groupSome={groupSome}
                onToggleGroup={() => onToggleGroup(groupIds)}
                selected={selected}
                onToggleRow={onToggleRow}
                onRowClick={onRowClick}
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// 单个分组的组头行 + 展开后的子行
function FragmentGroup({
  group, isOpen, onToggleExpand, columns, dataColumns, headRow,
  groupChecked, groupSome, onToggleGroup, selected, onToggleRow, onRowClick,
}) {
  return (
    <>
      {/* 组头行 */}
      <tr
        className="border-b border-border bg-primary/5 transition-colors hover:bg-primary/10"
        onClick={onToggleExpand}
      >
        {columns.map((col, idx) => {
          // 第一列：展开图标 + 组级 checkbox
          if (col.key === '__select') {
            return (
              <td key="__select" className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={groupChecked}
                    ref={(el) => { if (el) el.indeterminate = !groupChecked && groupSome }}
                    onChange={onToggleGroup}
                  />
                  <button
                    onClick={(e) => { e.stopPropagation(); onToggleExpand() }}
                    className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                    title={isOpen ? '收起' : '展开'}
                  >
                    {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </button>
                </div>
              </td>
            )
          }
          // 标识列：显示 identifier + 数量徽章
          if (col.key === '__tags') {
            return (
              <td key="__tags" className="px-4 py-3">
                <Badge variant="brand">{group.records.length} 个使用单位</Badge>
              </td>
            )
          }
          // 数据列：组头展示首行值
          return (
            <td key={col.key || idx} className="px-4 py-3">
              {col.render ? col.render(headRow) : null}
            </td>
          )
        })}
      </tr>
      {/* 展开的子行：各使用单位 */}
      {isOpen && group.records.map((row) => (
        <tr
          key={row.id}
          className="border-b border-border/60 bg-background transition-colors hover:bg-muted/40"
          onClick={() => onRowClick(row)}
        >
          {columns.map((col, idx) => {
            if (col.key === '__select') {
              return (
                <td key="__select" className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selected.has(row.id)}
                    onChange={() => onToggleRow(row.id)}
                  />
                </td>
              )
            }
            if (col.key === '__tags') {
              return (
                <td key="__tags" className="px-4 py-3 pl-8">
                  {col.render ? col.render(row) : null}
                </td>
              )
            }
            // 子行数据列缩进显示
            return (
              <td key={col.key || idx} className="px-4 py-3 pl-8">
                {col.render ? col.render(row) : null}
              </td>
            )
          })}
        </tr>
      ))}
    </>
  )
}

// ===== 主页面 =====
export default function AssetList() {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlTypeCode = searchParams.get('type_code') || ''

  const [templates, setTemplates] = useState([])
  const [activeTypeCode, setActiveTypeCode] = useState(urlTypeCode)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 概览统计（用于 Tab 数量徽章）
  const [overview, setOverview] = useState(null)

  // 筛选
  const [keyword, setKeyword] = useState('')
  const [fStatus, setFStatus] = useState('')
  const [fCrit, setFCrit] = useState('')
  const [fDept, setFDept] = useState('')
  const [fTag, setFTag] = useState('')
  const [tags, setTags] = useState([])
  const [deptOptions, setDeptOptions] = useState([])
  // 高级筛选面板折叠状态（默认收起，只留搜索框 + 筛选按钮）
  const [filterOpen, setFilterOpen] = useState(false)
  // 已激活的高级筛选项数量（不含 keyword，keyword 由搜索框直接体现）
  const activeFilterCount = [fStatus, fCrit, fDept, fTag].filter(Boolean).length
  const resetFilters = () => {
    setKeyword(''); setFStatus(''); setFCrit(''); setFDept(''); setFTag(''); setPage(1)
  }

  // 保存的筛选视图（localStorage）
  const [savedViews, setSavedViews] = useState(() => {
    try { return JSON.parse(localStorage.getItem('soar_asset_views') || '[]') } catch { return [] }
  })
  const [viewName, setViewName] = useState('')
  const [viewDropdownOpen, setViewDropdownOpen] = useState(false)

  const persistViews = (views) => {
    setSavedViews(views)
    try { localStorage.setItem('soar_asset_views', JSON.stringify(views)) } catch { /* ignore */ }
  }
  const saveCurrentView = () => {
    const name = viewName.trim()
    if (!name) { toast.warning('请输入视图名称'); return }
    const view = { name, type_code: activeTypeCode, keyword, fStatus, fCrit, fDept, fTag }
    const exists = savedViews.some((v) => v.name === name)
    if (exists) {
      persistViews(savedViews.map((v) => v.name === name ? view : v))
      toast.success(`视图「${name}」已更新`)
    } else {
      persistViews([...savedViews, view])
      toast.success(`视图「${name}」已保存`)
    }
    setViewName(''); setViewDropdownOpen(false)
  }
  const applyView = (v) => {
    setKeyword(v.keyword || ''); setFStatus(v.fStatus || ''); setFCrit(v.fCrit || '')
    setFDept(v.fDept || ''); setFTag(v.fTag || ''); setPage(1)
    switchType(v.type_code || '')
    setViewDropdownOpen(false)
  }
  const deleteView = (name) => {
    persistViews(savedViews.filter((v) => v.name !== name))
    toast.info(`视图「${name}」已删除`)
  }

  // 选择
  const [selected, setSelected] = useState(new Set())
  const [selectAllMode, setSelectAllMode] = useState(false) // 三级选择：false/当前页/全选所有

  // 弹窗
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [detail, setDetail] = useState(null)
  const [importOpen, setImportOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchEditOpen, setBatchEditOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)

  const canManage = true // 简化：admin/analyst（后端鉴权）
  const canDelete = true

  const activeTemplate = useMemo(
    () => templates.find((t) => t.code === activeTypeCode) || null,
    [templates, activeTypeCode]
  )

  // 聚合模式：模板开启 allow_aggregate 时，列表按标识分组展开显示
  const isAggregateMode = !!activeTemplate?.allow_aggregate

  // 加载模板列表 + 概览统计（Tab 数量徽章）
  useEffect(() => {
    assetsApi.listTemplates().then(setTemplates).catch(() => {})
    assetsApi.listTags().then(setTags).catch(() => {})
    assetsApi.overview().then(setOverview).catch(() => {})
  }, [])

  // URL ↔ activeTypeCode 同步
  useEffect(() => {
    setActiveTypeCode(urlTypeCode)
  }, [urlTypeCode])
  const switchType = (code) => {
    setPage(1); setSelected(new Set()); setSelectAllMode(false)
    const next = new URLSearchParams(searchParams)
    if (code) next.set('type_code', code); else next.delete('type_code')
    setSearchParams(next, { replace: true })
  }

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await assetsApi.list({
        type_code: activeTypeCode || undefined,
        keyword: keyword || undefined,
        status: fStatus || undefined,
        criticality: fCrit || undefined,
        department: fDept || undefined,
        tag_id: fTag || undefined,
        page, page_size: pageSize,
        sort_by: 'id', order: 'desc',
      })
      setItems(res.items || [])
      setTotal(res.total || 0)
    } catch (e) {
      setError(e.message || '加载失败')
    } finally { setLoading(false) }
  }, [activeTypeCode, keyword, fStatus, fCrit, fDept, fTag, page, pageSize])

  useEffect(() => { load() }, [load])

  // 加载部门选项（按当前类型）
  useEffect(() => {
    assetsApi.fieldOptions(activeTypeCode || undefined).then((r) => setDeptOptions(r.departments || [])).catch(() => {})
  }, [activeTypeCode])

  // 一键全选：先同步全选本页保证立即反馈；多页时再拉取全量 ID 升级为“全选所有匹配结果”
  const handleHeaderSelectAll = useCallback(async () => {
    const allSelected = selectAllMode !== false && items.length > 0 && items.every((it) => selected.has(it.id))
    const filter = {
      type_code: activeTypeCode || undefined,
      keyword, status: fStatus, criticality: fCrit, department: fDept, tag_id: fTag,
    }
    if (allSelected) {
      // 已全选 → 取消全部
      setSelected(new Set())
      setSelectAllMode(false)
      return
    }
    // 1) 先同步全选本页，保证点击立即有反馈（当前页 checkbox 立即勾上）
    setSelected(new Set(items.map((it) => it.id)))
    setSelectAllMode('page')
    // 2) 多页时再拉取全量匹配 ID 升级为“全选所有匹配结果”
    if (total > items.length) {
      try {
        const r = await assetsApi.listIds(filter)
        const ids = (r.ids || []).filter((id) => typeof id !== 'undefined')
        setSelected(new Set(ids))
        setSelectAllMode('all')
      } catch {
        // 拉取全量失败时不阻塞，保留“仅当前页”，并提示
        toast.error('跨页全选失败，本次仅选中当前页')
      }
    }
  }, [selectAllMode, items, selected, total, activeTypeCode, keyword, fStatus, fCrit, fDept, fTag])

  // 动态列：根据模板字段 show_in_list 生成
  const columns = useMemo(() => {
    const cols = []
    // 选择列
    cols.push({
      key: '__select',
      header: (
        <input
          type="checkbox"
          checked={selectAllMode !== false && items.length > 0 && items.every((it) => selected.has(it.id))}
          onChange={handleHeaderSelectAll}
        />
      ),
      render: (row) => (
        <input
          type="checkbox"
          checked={selected.has(row.id)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => {
            setSelected((p) => {
              const n = new Set(p)
              if (n.has(row.id)) n.delete(row.id); else n.add(row.id)
              return n
            })
          }}
        />
      ),
    })
    // 标识字段列（始终显示）
    if (activeTemplate) {
      const fieldCols = (activeTemplate.fields || [])
        .filter((f) => f.show_in_list)
        .sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))
      fieldCols.forEach((f) => {
        cols.push({
          key: f.key,
          header: f.label,
          render: (row) => {
            const v = getFieldValue(row, f)
            if (f.key === activeTemplate.identifier_field) {
              return <TruncateCell text={v} maxWidth={140} mono />
            }
            if (f.mapped_to === 'standard:status') {
              return <StatusBadge color={STATUS_COLORS[row.status] || 'neutral'} label={STATUS_LABELS[row.status] || row.status || '-'} />
            }
            if (f.mapped_to === 'standard:criticality') {
              return <StatusBadge color={CRIT_COLORS[row.criticality] || 'neutral'} label={CRIT_LABELS[row.criticality] || row.criticality || '-'} />
            }
            // 长文本截断 + hover 显示完整内容
            return <TruncateCell text={v} maxWidth={180} />
          },
        })
      })
    } else {
      // 无模板：默认列
      cols.push({ key: 'identifier', header: '标识', render: (r) => <TruncateCell text={r.identifier} maxWidth={140} mono /> })
      cols.push({ key: 'name', header: '名称', render: (r) => <TruncateCell text={r.name} maxWidth={140} /> })
      cols.push({ key: 'ip', header: 'IP', render: (r) => <TruncateCell text={r.ip} maxWidth={130} mono /> })
      cols.push({ key: 'department', header: '部门', render: (r) => <TruncateCell text={r.department} maxWidth={160} /> })
      cols.push({ key: 'owner', header: '负责人', render: (r) => <TruncateCell text={r.owner} maxWidth={100} /> })
      cols.push({
        key: 'status', header: '状态',
        render: (r) => <StatusBadge color={STATUS_COLORS[r.status] || 'neutral'} label={STATUS_LABELS[r.status] || r.status || '-'} />,
      })
    }
    // 标签列（彩色 Tag 色块，前 2 个 + +N）
    cols.push({
      key: '__tags', header: '标签',
      render: (row) =>
        row.tags?.length ? (
          <div className="flex flex-wrap items-center gap-1" title={row.tags.map((t) => t.name).join('、')}>
            {row.tags.slice(0, 2).map((t) => <TagChip key={t.id} tag={t} />)}
            {row.tags.length > 2 && <span className="text-[10px] text-muted-foreground" title={`共 ${row.tags.length} 个标签`}>+{row.tags.length - 2}</span>}
          </div>
        ) : <span className="text-xs text-muted-foreground">-</span>,
    })
    // 操作列（行操作显性化：详情/编辑/删除/复制 IP）
    cols.push({
      key: '__actions', header: '操作', width: '200px',
      render: (row) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button type="button" onClick={() => setDetail(row)} className="inline-flex items-center gap-1 rounded border border-border bg-secondary px-2 py-1 text-[11px] text-muted-foreground hover:bg-secondary/70" title="查看详情">
            <Eye className="h-3 w-3" /> 详情
          </button>
          {canManage && (
            <button type="button" onClick={() => { setEditing(row); setFormOpen(true) }} className="inline-flex items-center gap-1 rounded border border-border bg-secondary px-2 py-1 text-[11px] text-muted-foreground hover:bg-secondary/70" title="编辑">
              <Pencil className="h-3 w-3" /> 编辑
            </button>
          )}
          <button type="button" onClick={() => copyText(row.ip || row.identifier)} className="inline-flex h-7 w-7 items-center justify-center rounded border border-border bg-secondary text-muted-foreground hover:bg-secondary/70" title="复制 IP">
            <Copy className="h-3 w-3" />
          </button>
          {canDelete && (
            <button type="button" onClick={() => handleDelete(row)} className="inline-flex h-7 w-7 items-center justify-center rounded border border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/20" title="删除">
              <Trash2 className="h-3 w-3" />
            </button>
          )}
        </div>
      ),
    })
    return cols
  }, [activeTemplate, items, selected, selectAllMode, handleHeaderSelectAll])

  // 新增/编辑提交
  const handleSubmit = async ({ fields, tag_ids }) => {
    if (editing) {
      await assetsApi.update(editing.id, { type_code: editing.type_code, fields, tag_ids: tag_ids })
    } else {
      await assetsApi.create({ type_code: activeTypeCode, fields, tag_ids: tag_ids })
    }
    setFormOpen(false); setEditing(null)
    load()
  }

  // 删除
  const handleDelete = async (rec) => {
    const ok = await confirm({ message: `确认删除资产「${rec.name || rec.identifier}」？此操作不可恢复。`, variant: 'danger', confirmText: '确定删除' })
    if (!ok) return
    await assetsApi.remove(rec.id)
    setDetail(null); load()
  }
  const handleBatchDelete = async () => {
    let ids = [...selected]
    if (selectAllMode === 'all') {
      const r = await assetsApi.listIds({ type_code: activeTypeCode || undefined, keyword, status: fStatus, criticality: fCrit, department: fDept, tag_id: fTag })
      ids = r.ids
    }
    if (ids.length === 0) return
    const ok = await confirm({ message: `确认删除选中的 ${ids.length} 条资产？此操作不可恢复。`, variant: 'danger', confirmText: '确定删除' })
    if (!ok) return
    await assetsApi.batchRemove(ids)
    setSelected(new Set()); setSelectAllMode(false); load()
  }

  // 导出（打开导出弹窗，支持选择导出范围和字段）
  const handleExport = () => setExportOpen(true)

  // 实际执行导出（由导出弹窗确认后调用）
  const doExport = async (scope, selectedFields) => {
    let ids = null
    if (scope === 'selected') {
      ids = selectAllMode === 'all'
        ? (await assetsApi.listIds({ type_code: activeTypeCode || undefined, keyword, status: fStatus, criticality: fCrit, department: fDept, tag_id: fTag })).ids
        : [...selected]
    }
    await assetsApi.exportCsv(activeTypeCode || undefined, ids, selectedFields.length > 0 ? selectedFields : undefined)
    setExportOpen(false)
    toast.success('导出已开始')
  }

  return (
    <PageContainer>
      {/* 标题 */}
      <div className="mb-3">
        <h1 className="text-xl font-semibold text-foreground">资产清单</h1>
        <p className="mt-1 text-sm text-muted-foreground">按类型多维度筛选、查询与管理资产</p>
      </div>

      {/* 类型 Tab（含数量徽章） */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5 border-b border-border pb-px">
        <button
          onClick={() => switchType('')}
          className={`relative flex items-center gap-1.5 rounded-t-md px-4 py-3 text-sm transition-colors ${
            !activeTypeCode ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          全部
          {overview && (
            <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-secondary px-1.5 text-[10px] font-medium text-muted-foreground">
              {overview.total ?? 0}
            </span>
          )}
          {!activeTypeCode && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-primary" />}
        </button>
        {templates.map((t) => {
          const Icon = TEMPLATE_ICONS[t.code] || Boxes
          const active = activeTypeCode === t.code
          const count = overview?.by_template?.[t.code] ?? 0
          return (
            <button
              key={t.code}
              onClick={() => switchType(t.code)}
              className={`relative flex items-center gap-1.5 rounded-t-md px-4 py-3 text-sm transition-colors ${
                active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <Icon className="h-3.5 w-3.5" /> {t.name}
              <span className={`inline-flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10px] font-medium ${count > 0 ? 'bg-primary/15 text-primary' : 'bg-secondary text-muted-foreground/60'}`}>
                {count}
              </span>
              {active && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-primary" />}
            </button>
          )
        })}
      </div>

      {/* 工具栏：搜索 + 筛选触发（左）与 新增/导入/导出/刷新（右）合并同一行 */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-center justify-between gap-2 p-2.5">
          {/* 左：搜索框 + 高级筛选触发按钮 */}
          <div className="flex items-center gap-2">
            <div className="relative w-52">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                className={`${inputCls} pl-8`}
                placeholder="搜索 IP / 名称 / 标识"
                value={keyword}
                onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
                onKeyDown={(e) => e.key === 'Enter' && load()}
              />
            </div>
            <button
              type="button"
              onClick={() => setFilterOpen((o) => !o)}
              className={`btn-sm flex items-center gap-1.5 rounded-md border transition-colors ${
                activeFilterCount > 0
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
              title={filterOpen ? '收起高级筛选' : '展开高级筛选'}
            >
              <SlidersHorizontal className="h-4 w-4" /> 筛选
              {activeFilterCount > 0 && (
                <span className="inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground">
                  {activeFilterCount}
                </span>
              )}
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${filterOpen ? 'rotate-180' : ''}`} />
            </button>
          </div>
          {/* 右：操作按钮 */}
          <div className="flex items-center gap-2">
            <button onClick={() => { setEditing(null); setFormOpen(true) }} disabled={!activeTemplate} className="btn-primary btn-sm flex items-center gap-1" title={!activeTemplate ? '请先选择资产类型' : ''}>
              <Plus className="h-4 w-4" /> 新增
            </button>
            <button onClick={() => setImportOpen(true)} disabled={!activeTemplate} className="btn-secondary btn-sm flex items-center gap-1">
              <Upload className="h-4 w-4" /> 导入
            </button>
            <button onClick={handleExport} className="btn-secondary btn-sm flex items-center gap-1">
              <Download className="h-4 w-4" /> 导出
            </button>
            <button onClick={load} className="btn-secondary btn-sm flex items-center gap-1">
              <RefreshCw className="h-4 w-4" /> 刷新
            </button>
          </div>
        </div>
        {/* 高级筛选面板（可折叠，默认收起；展开显示 4 个筛选项 + 一键重置） */}
        {filterOpen && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border bg-muted/20 p-2.5">
            <span className="mr-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
              <SlidersHorizontal className="h-3.5 w-3.5" /> 高级筛选
            </span>
            <select className={`${inputBaseCls} w-[108px]`} value={fStatus} onChange={(e) => { setFStatus(e.target.value); setPage(1) }}>
              <option value="">全部状态</option>
              {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select className={`${inputBaseCls} w-[116px]`} value={fCrit} onChange={(e) => { setFCrit(e.target.value); setPage(1) }}>
              <option value="">全部重要性</option>
              {Object.entries(CRIT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select className={`${inputBaseCls} w-[144px]`} value={fDept} onChange={(e) => { setFDept(e.target.value); setPage(1) }}>
              <option value="">全部部门</option>
              {deptOptions.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <select className={`${inputBaseCls} w-[124px]`} value={fTag} onChange={(e) => { setFTag(e.target.value); setPage(1) }}>
              <option value="">全部标签</option>
              {tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <button
              type="button"
              onClick={resetFilters}
              disabled={!keyword && !fStatus && !fCrit && !fDept && !fTag}
              className="btn-secondary btn-sm flex items-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <RotateCcw className="h-3.5 w-3.5" /> 一键重置
            </button>
            {/* 保存视图 */}
            <div className="relative ml-auto">
              <button type="button" onClick={() => setViewDropdownOpen((o) => !o)} className="btn-secondary btn-sm flex items-center gap-1">
                <Bookmark className="h-3.5 w-3.5" /> 我的视图
                <ChevronDown className="h-3 w-3" />
              </button>
              {viewDropdownOpen && (
                <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-lg border border-border bg-card p-3 shadow-xl">
                  <div className="mb-2 flex items-center gap-1">
                    <input className={`${inputBaseCls} flex-1`} placeholder="视图名称..." value={viewName} onChange={(e) => setViewName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && saveCurrentView()} />
                    <button type="button" onClick={saveCurrentView} className="btn-primary btn-sm flex items-center gap-1"><Save className="h-3 w-3" /> 保存</button>
                  </div>
                  <div className="max-h-48 overflow-y-auto">
                    {savedViews.length === 0 ? (
                      <p className="py-2 text-center text-[11px] text-muted-foreground">暂无保存的视图</p>
                    ) : savedViews.map((v) => (
                      <div key={v.name} className="flex items-center justify-between rounded px-2 py-1.5 text-xs hover:bg-muted">
                        <button type="button" onClick={() => applyView(v)} className="flex-1 text-left text-foreground">{v.name}</button>
                        <button type="button" onClick={() => deleteView(v.name)} className="text-destructive hover:underline"><X className="h-3 w-3" /></button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
        {/* 已选筛选条件可视化（Tag 形式，支持单个删除和一键清空） */}
        {(keyword || fStatus || fCrit || fDept || fTag) && (
          <div className="flex flex-wrap items-center gap-1.5 border-t border-border bg-muted/10 p-2.5">
            <span className="text-[11px] text-muted-foreground">当前筛选：</span>
            {keyword && (
              <FilterChip label={`关键词: ${keyword}`} onRemove={() => { setKeyword(''); setPage(1) }} />
            )}
            {fStatus && (
              <FilterChip label={`状态: ${STATUS_LABELS[fStatus] || fStatus}`} onRemove={() => { setFStatus(''); setPage(1) }} />
            )}
            {fCrit && (
              <FilterChip label={`重要性: ${CRIT_LABELS[fCrit] || fCrit}`} onRemove={() => { setFCrit(''); setPage(1) }} />
            )}
            {fDept && (
              <FilterChip label={`部门: ${fDept}`} onRemove={() => { setFDept(''); setPage(1) }} />
            )}
            {fTag && (
              <FilterChip label={`标签: ${tags.find((t) => String(t.id) === fTag)?.name || fTag}`} onRemove={() => { setFTag(''); setPage(1) }} />
            )}
            <button type="button" onClick={resetFilters} className="ml-1 text-[11px] text-primary hover:underline">清空全部</button>
          </div>
        )}
      </Card>

      {/* 批量操作栏（有选中时显示） */}
      {selected.size > 0 && (
        <div className="mb-3 flex items-center justify-between rounded-lg border border-primary/30 bg-primary/5 px-4 py-2 text-sm">
          <div className="flex items-center gap-3">
            <span className="text-foreground">
              已选 {selected.size} 项
              {selectAllMode === 'all' && '（全选所有匹配）'}
            </span>
            {selectAllMode === 'page' && total > items.length && (
              <button onClick={async () => {
                const r = await assetsApi.listIds({ type_code: activeTypeCode || undefined, keyword, status: fStatus, criticality: fCrit, department: fDept, tag_id: fTag })
                setSelected(new Set(r.ids)); setSelectAllMode('all')
              }} className="text-xs text-primary hover:underline">
                选择所有匹配的 {total} 条
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setBatchOpen(true)} className="btn-secondary btn-sm flex items-center gap-1">
              <TagIcon className="h-3.5 w-3.5" /> 批量打标
            </button>
            <button onClick={() => setBatchEditOpen(true)} className="btn-secondary btn-sm flex items-center gap-1">
              <Pencil className="h-3.5 w-3.5" /> 批量编辑
            </button>
            <button onClick={handleBatchDelete} className="btn-danger btn-sm flex items-center gap-1">
              <Trash2 className="h-3.5 w-3.5" /> 批量删除
            </button>
            <button onClick={() => { setSelected(new Set()); setSelectAllMode(false) }} className="text-xs text-muted-foreground hover:text-foreground">取消选择</button>
          </div>
        </div>
      )}

      {/* 表格 */}
      <Card bodyClassName="p-0">
        {loading ? (
          <SkeletonRows rows={8} cols={columns.length} />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={Boxes}
            title={activeTemplate ? `暂无${activeTemplate.name}` : '暂无资产'}
            description={activeTemplate ? '点击「新增」或「导入」添加资产' : '请先在类型模板页创建资产类型'}
            action={activeTemplate && canManage ? (
              <button onClick={() => { setEditing(null); setFormOpen(true) }} className="btn-primary btn-sm flex items-center gap-1">
                <Plus className="h-4 w-4" /> 新增资产
              </button>
            ) : null}
          />
        ) : isAggregateMode ? (
          <AggregateTable
            columns={columns}
            data={items}
            selected={selected}
            onToggleRow={(id) => setSelected((p) => {
              const n = new Set(p)
              if (n.has(id)) n.delete(id); else n.add(id)
              return n
            })}
            onToggleGroup={(groupIds) => setSelected((p) => {
              const n = new Set(p)
              const allChecked = groupIds.every((id) => n.has(id))
              if (allChecked) groupIds.forEach((id) => n.delete(id))
              else groupIds.forEach((id) => n.add(id))
              return n
            })}
            onRowClick={(row) => setDetail(row)}
          />
        ) : (
          <DataTable
            columns={columns}
            data={items}
            onRowClick={(row) => setDetail(row)}
            rowKey="id"
            stickyHeader
            maxHeight="calc(100vh - 280px)"
          />
        )}
        {total > 0 && (
          <Pagination
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={setPage}
            onPageSizeChange={(s) => { setPageSize(s); setPage(1) }}
            pageSizeOptions={[20, 50, 100, 200]}
          />
        )}
      </Card>

      {/* 新增/编辑弹窗 */}
      <AssetFormModal
        open={formOpen}
        template={activeTemplate}
        templates={templates}
        initial={editing}
        onClose={() => { setFormOpen(false); setEditing(null) }}
        onSubmit={handleSubmit}
      />

      {/* 详情抽屉 */}
      <DetailDrawer
        open={!!detail}
        record={detail}
        template={activeTemplate}
        templates={templates}
        onClose={() => setDetail(null)}
        onEdit={(rec) => { setDetail(null); setEditing(rec); setFormOpen(true) }}
        onDelete={handleDelete}
        canManage={canManage}
        canDelete={canDelete}
      />

      {/* 导入弹窗 */}
      <ImportModal
        open={importOpen}
        template={activeTemplate}
        onClose={() => setImportOpen(false)}
        onDone={load}
      />

      {/* 批量打标弹窗 */}
      {batchOpen && (
        <BatchTagModal
          open={batchOpen}
          tags={tags}
          onClose={() => setBatchOpen(false)}
          onConfirm={async (addTags, removeTags) => {
            let ids = [...selected]
            if (selectAllMode === 'all') {
              const r = await assetsApi.listIds({ type_code: activeTypeCode || undefined, keyword, status: fStatus, criticality: fCrit, department: fDept, tag_id: fTag })
              ids = r.ids
            }
            await assetsApi.batchUpdate(ids, {}, { addTags, removeTags })
            setBatchOpen(false); load()
          }}
        />
      )}

      {/* 批量编辑弹窗（修改部门/负责人/状态） */}
      {batchEditOpen && (
        <BatchEditModal
          open={batchEditOpen}
          selectedCount={selected.size}
          deptOptions={deptOptions}
          onClose={() => setBatchEditOpen(false)}
          onConfirm={async (fields) => {
            let ids = [...selected]
            if (selectAllMode === 'all') {
              const r = await assetsApi.listIds({ type_code: activeTypeCode || undefined, keyword, status: fStatus, criticality: fCrit, department: fDept, tag_id: fTag })
              ids = r.ids
            }
            await assetsApi.batchUpdate(ids, fields)
            setBatchEditOpen(false); load()
            toast.success(`已批量更新 ${ids.length} 条资产`)
          }}
        />
      )}

      {/* 导出弹窗（选择导出范围和字段） */}
      {exportOpen && (
        <ExportModal
          open={exportOpen}
          template={activeTemplate}
          selectedCount={selected.size}
          totalCount={total}
          onClose={() => setExportOpen(false)}
          onConfirm={(scope, fields) => doExport(scope, fields)}
        />
      )}
    </PageContainer>
  )
}

// 批量打标弹窗
function BatchTagModal({ open, tags, onClose, onConfirm }) {
  const [addTags, setAddTags] = useState([])
  const [removeTags, setRemoveTags] = useState([])
  return (
    <Modal
      open={open}
      title="批量打标"
      onClose={onClose}
      maxWidth="max-w-md"
      footer={
        <>
          <button onClick={onClose} className="btn-secondary">取消</button>
          <button
            onClick={() => onConfirm(addTags, removeTags)}
            disabled={addTags.length === 0 && removeTags.length === 0}
            className="btn-primary btn-sm"
          >确定</button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <label className={labelCls}>添加标签</label>
          <div className="flex flex-wrap gap-2">
            {tags.map((t) => (
              <button key={t.id} type="button"
                onClick={() => setAddTags((p) => p.includes(t.id) ? p.filter((x) => x !== t.id) : [...p, t.id])}
                className={`rounded-full border px-3 py-1 text-xs ${addTags.includes(t.id) ? 'border-primary bg-primary/15 text-primary' : 'border-border text-muted-foreground'}`}
              >{t.name}</button>
            ))}
          </div>
        </div>
        <div>
          <label className={labelCls}>移除标签</label>
          <div className="flex flex-wrap gap-2">
            {tags.map((t) => (
              <button key={t.id} type="button"
                onClick={() => setRemoveTags((p) => p.includes(t.id) ? p.filter((x) => x !== t.id) : [...p, t.id])}
                className={`rounded-full border px-3 py-1 text-xs ${removeTags.includes(t.id) ? 'border-destructive bg-destructive/15 text-danger' : 'border-border text-muted-foreground'}`}
              >{t.name}</button>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  )
}

// ===== 批量编辑弹窗（修改部门/负责人/状态） =====
function BatchEditModal({ open, selectedCount, deptOptions, onClose, onConfirm }) {
  const [department, setDepartment] = useState('')
  const [owner, setOwner] = useState('')
  const [status, setStatus] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSubmit = async () => {
    const fields = {}
    if (department) fields.department = department
    if (owner) fields.owner = owner
    if (status) fields.status = status
    if (Object.keys(fields).length === 0) { toast.warning('请至少填写一个要修改的字段'); return }
    setSaving(true)
    try { await onConfirm(fields) } catch (err) { toast.error(err.message || '批量更新失败') } finally { setSaving(false) }
  }

  return (
    <Modal open={open} title={`批量编辑（${selectedCount} 条）`} onClose={onClose} maxWidth="max-w-md"
      footer={<>
        <button onClick={onClose} className="btn-secondary">取消</button>
        <button onClick={handleSubmit} disabled={saving} className="btn-primary btn-sm">{saving ? '更新中...' : '确定更新'}</button>
      </>}
    >
      <div className="space-y-3">
        <p className="text-[11px] text-muted-foreground">仅填写需要修改的字段，留空的字段保持原值不变。</p>
        <div>
          <label className={labelCls}>部门</label>
          <input className={inputCls} value={department} onChange={(e) => setDepartment(e.target.value)} list="dept-list" placeholder="留空保持不变" />
          <datalist id="dept-list">{deptOptions.map((d) => <option key={d} value={d} />)}</datalist>
        </div>
        <div>
          <label className={labelCls}>负责人</label>
          <input className={inputCls} value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="留空保持不变" />
        </div>
        <div>
          <label className={labelCls}>状态</label>
          <select className={inputCls} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">留空保持不变</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </div>
    </Modal>
  )
}

// ===== 导出弹窗（选择导出范围和字段） =====
function ExportModal({ open, template, selectedCount, totalCount, onClose, onConfirm }) {
  const [scope, setScope] = useState('all')
  const [selectedFields, setSelectedFields] = useState(new Set())
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (open) { setScope(selectedCount > 0 ? 'selected' : 'all'); setSelectedFields(new Set()) }
  }, [open, selectedCount])

  const fieldDefs = useMemo(() => {
    if (!template) return []
    return (template.fields || []).slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))
  }, [template])

  const toggleField = (key) => setSelectedFields((p) => {
    const n = new Set(p)
    if (n.has(key)) n.delete(key); else n.add(key)
    return n
  })

  const handleExport = async () => {
    setExporting(true)
    try { await onConfirm(scope, [...selectedFields]) } catch (err) { toast.error(err.message || '导出失败') } finally { setExporting(false) }
  }

  return (
    <Modal open={open} title="导出资产" onClose={onClose} maxWidth="max-w-lg"
      footer={<>
        <button onClick={onClose} className="btn-secondary">取消</button>
        <button onClick={handleExport} disabled={exporting} className="btn-primary btn-sm flex items-center gap-1">
          {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          {exporting ? '导出中...' : '开始导出'}
        </button>
      </>}
    >
      <div className="space-y-4">
        {/* 导出范围 */}
        <div>
          <label className={labelCls}>导出范围</label>
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={() => setScope('all')} className={`rounded-md border p-2 text-left text-xs transition ${scope === 'all' ? 'border-primary bg-primary/10' : 'border-border hover:border-primary/50'}`}>
              <div className="font-medium">全部筛选结果</div>
              <div className="text-[10px] text-muted-foreground/70">共 {totalCount} 条</div>
            </button>
            <button type="button" onClick={() => setScope('selected')} disabled={selectedCount === 0} className={`rounded-md border p-2 text-left text-xs transition disabled:opacity-40 ${scope === 'selected' ? 'border-primary bg-primary/10' : 'border-border hover:border-primary/50'}`}>
              <div className="font-medium">仅选中项</div>
              <div className="text-[10px] text-muted-foreground/70">{selectedCount} 条</div>
            </button>
          </div>
        </div>
        {/* 字段选择 */}
        {template && fieldDefs.length > 0 && (
          <div>
            <label className={labelCls}>导出字段 <span className="text-muted-foreground/50">(不选则导出全部)</span></label>
            <div className="grid max-h-48 grid-cols-2 gap-1.5 overflow-y-auto rounded-md border border-border bg-secondary/40 p-2">
              {fieldDefs.map((f) => (
                <label key={f.key} className="flex items-center gap-1.5 text-xs">
                  <input type="checkbox" checked={selectedFields.has(f.key)} onChange={() => toggleField(f.key)} className="accent-primary" />
                  {f.label}
                </label>
              ))}
            </div>
          </div>
        )}
        {!template && (
          <p className="text-[11px] text-muted-foreground">未选择资产类型，将导出标准列 + 全局自定义字段。</p>
        )}
      </div>
    </Modal>
  )
}
