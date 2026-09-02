import { useEffect, useState, useCallback } from 'react'
import {
  Plus, Pencil, Trash2, Save, X, ArrowUp, ArrowDown, Boxes,
  Server, Network, Globe, Tag as TagIcon, RefreshCw,
} from 'lucide-react'
import { assetsApi } from '../api/assets'
import { Modal } from '../components/Dialog'
import { inputCls, labelCls } from '../components/property/FormControls'
import {
  PageContainer, Card, Badge, LoadingState, ErrorState, EmptyState, StatusBadge,
} from '../components/ui'
import { useUnsavedChanges } from '../hooks/useUnsavedChanges'

const TEMPLATE_ICONS = { host_asset: Server, network_segment: Network, egress_ip: Globe }
const FIELD_TYPES = ['text', 'number', 'date', 'select', 'textarea', 'ip', 'cidr']
const STANDARD_COLS = ['name', 'asset_type', 'department', 'owner', 'location', 'ip', 'criticality', 'status']
const COLOR_TOKENS = ['chart-1', 'chart-2', 'chart-3', 'chart-4', 'chart-5']

// ===== 模板编辑器 =====
function TemplateEditor({ open, template, onClose, onSaved }) {
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  // 未保存修改检测：编辑器打开期间跟踪表单是否被改过
  const [dirty, setDirty] = useState(false)
  const bypassGuard = useUnsavedChanges(dirty)

  useEffect(() => {
    if (!open) return
    setErr('')
    if (template) {
      // 深拷贝用于编辑
      setForm({
        code: template.code,
        name: template.name,
        description: template.description || '',
        icon: template.icon || 'server',
        color: template.color || 'chart-1',
        identifier_field: template.identifier_field || 'ip',
        fields: (template.fields || []).map((f) => ({ ...f })),
        is_preset: template.is_preset,
        allow_aggregate: !!template.allow_aggregate,
      })
    } else {
      setForm({
        code: '', name: '', description: '', icon: 'server', color: 'chart-1',
        identifier_field: 'ip', fields: [], is_preset: false, allow_aggregate: false,
      })
    }
    setDirty(false)
  }, [open, template])

  if (!open || !form) return null

  const isCreate = !template
  const update = (patch) => { setForm((p) => ({ ...p, ...patch })); setDirty(true) }

  const updateField = (idx, patch) => {
    setForm((p) => {
      const fields = p.fields.slice()
      fields[idx] = { ...fields[idx], ...patch }
      return { ...p, fields }
    })
    setDirty(true)
  }
  const addField = () => {
    setForm((p) => ({
      ...p,
      fields: [
        ...p.fields,
        {
          key: '', label: '', type: 'text', mapped_to: 'extra',
          required: false, unique: false, options: [], placeholder: '',
          default: '', width: 'half', sort_order: p.fields.length + 1,
          show_in_list: true, show_in_detail: true,
        },
      ],
    }))
    setDirty(true)
  }
  const removeField = (idx) => { setForm((p) => ({ ...p, fields: p.fields.filter((_, i) => i !== idx) })); setDirty(true) }
  const moveField = (idx, dir) => {
    setForm((p) => {
      const fields = p.fields.slice()
      const ni = idx + dir
      if (ni < 0 || ni >= fields.length) return p
      ;[fields[idx], fields[ni]] = [fields[ni], fields[idx]]
      return { ...p, fields }
    })
    setDirty(true)
  }

  const handleSave = async () => {
    setSaving(true); setErr('')
    try {
      // 校验
      if (!form.name.trim()) throw new Error('模板名称不能为空')
      if (isCreate && !form.code.trim()) throw new Error('模板代码不能为空')
      if (form.fields.length === 0) throw new Error('至少需要定义一个字段')
      const fieldKeys = form.fields.map((f) => f.key)
      if (fieldKeys.some((k) => !k)) throw new Error('所有字段必须填写 key')
      if (new Set(fieldKeys).size !== fieldKeys.length) throw new Error('字段 key 不能重复')
      if (!fieldKeys.includes(form.identifier_field)) {
        throw new Error(`标识字段 "${form.identifier_field}" 必须在字段列表中`)
      }
      const payload = {
        name: form.name, description: form.description, icon: form.icon,
        color: form.color, identifier_field: form.identifier_field,
        allow_aggregate: !!form.allow_aggregate,
        fields: form.fields.map((f, i) => ({
          ...f,
          key: f.key.trim(), label: f.label.trim() || f.key,
          sort_order: f.sort_order ?? i + 1,
          options: f.type === 'select' ? (f.options || []) : [],
        })),
      }
      if (isCreate) {
        payload.code = form.code.trim()
        await assetsApi.createTemplate(payload)
      } else {
        await assetsApi.updateTemplate(form.code, payload)
      }
      setDirty(false)
      bypassGuard() // 放行下一次导航，避免点保存也弹未保存修改弹窗
      onSaved?.()
      onClose()
    } catch (e) {
      setErr(e.message || '保存失败')
    } finally { setSaving(false) }
  }

  // 关闭编辑器：放弃当前编辑，重置 dirty 并放行后续导航
  const handleClose = () => {
    setDirty(false)
    bypassGuard()
    onClose()
  }

  return (
    <Modal
      open={open}
      title={isCreate ? '新建资产类型' : `编辑「${template.name}」`}
      onClose={handleClose}
      maxWidth="max-w-4xl"
      footer={
        <>
          <button onClick={handleClose} className="btn-secondary">取消</button>
          <button onClick={handleSave} disabled={saving} className="btn-primary btn-sm flex items-center gap-1">
            <Save className="h-3.5 w-3.5" /> {saving ? '保存中...' : '保存'}
          </button>
        </>
      }
    >
      {err && <div className="mb-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-danger">{err}</div>}
      {/* 基本信息 */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        {isCreate && (
          <div>
            <label className={labelCls}>模板代码（唯一，英文）</label>
            <input className={inputCls} value={form.code} onChange={(e) => update({ code: e.target.value })} placeholder="如 web_service" />
          </div>
        )}
        <div>
          <label className={labelCls}>模板名称</label>
          <input className={inputCls} value={form.name} onChange={(e) => update({ name: e.target.value })} placeholder="如 Web 服务资产" />
        </div>
        <div className="col-span-2">
          <label className={labelCls}>描述</label>
          <input className={inputCls} value={form.description} onChange={(e) => update({ description: e.target.value })} />
        </div>
        <div>
          <label className={labelCls}>图标（lucide 名称）</label>
          <input className={inputCls} value={form.icon} onChange={(e) => update({ icon: e.target.value })} placeholder="server / network / globe ..." />
        </div>
        <div>
          <label className={labelCls}>主题色</label>
          <select className={inputCls} value={form.color} onChange={(e) => update({ color: e.target.value })}>
            {COLOR_TOKENS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className={labelCls}>标识字段（唯一标识）</label>
          <select className={inputCls} value={form.identifier_field} onChange={(e) => update({ identifier_field: e.target.value })}>
            {form.fields.map((f) => <option key={f.key} value={f.key}>{f.label || f.key}</option>)}
          </select>
        </div>
      </div>

      {/* 标识聚合开关 */}
      <div className="mt-3 flex items-start gap-3 rounded-lg border border-border bg-muted/20 p-3">
        <label className="mt-0.5 flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-border"
            checked={!!form.allow_aggregate}
            onChange={(e) => update({ allow_aggregate: e.target.checked })}
          />
          <span className="text-sm font-medium text-foreground">允许标识聚合</span>
        </label>
        <p className="flex-1 text-xs leading-relaxed text-muted-foreground">
          开启后，同一标识（如同一网段）允许存在多条不同使用单位的记录，
          资产清单中按标识分组展开显示各使用单位子项；
          关闭时标识在该类型下全局唯一，同标识不同部门视为冲突。
        </p>
      </div>

      {/* 字段定义 */}
      <div className="mt-5 border-t border-border pt-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">字段定义（{form.fields.length}）</h3>
          <button onClick={addField} className="btn-secondary btn-sm flex items-center gap-1">
            <Plus className="h-3.5 w-3.5" /> 添加字段
          </button>
        </div>
        <div className="space-y-2">
          {form.fields.map((f, idx) => (
            <div key={idx} className="rounded-lg border border-border bg-muted/20 p-3">
              <div className="grid grid-cols-12 items-end gap-2">
                <div className="col-span-3">
                  <label className="text-[10px] text-muted-foreground">字段 key</label>
                  <input className={inputCls} value={f.key} onChange={(e) => updateField(idx, { key: e.target.value })} placeholder="ip" />
                </div>
                <div className="col-span-3">
                  <label className="text-[10px] text-muted-foreground">显示标签</label>
                  <input className={inputCls} value={f.label} onChange={(e) => updateField(idx, { label: e.target.value })} placeholder="IP 地址" />
                </div>
                <div className="col-span-2">
                  <label className="text-[10px] text-muted-foreground">类型</label>
                  <select className={inputCls} value={f.type} onChange={(e) => updateField(idx, { type: e.target.value })}>
                    {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div className="col-span-3">
                  <label className="text-[10px] text-muted-foreground">映射目标</label>
                  <select className={inputCls} value={f.mapped_to} onChange={(e) => updateField(idx, { mapped_to: e.target.value })}>
                    <option value="extra">extra（扩展字段）</option>
                    {STANDARD_COLS.map((c) => <option key={c} value={`standard:${c}`}>standard:{c}</option>)}
                  </select>
                </div>
                <div className="col-span-1 flex items-center justify-end gap-1">
                  <button onClick={() => moveField(idx, -1)} disabled={idx === 0} className="rounded p-1 text-muted-foreground hover:bg-accent disabled:opacity-30" title="上移">
                    <ArrowUp className="h-3.5 w-3.5" />
                  </button>
                  <button onClick={() => moveField(idx, 1)} disabled={idx === form.fields.length - 1} className="rounded p-1 text-muted-foreground hover:bg-accent disabled:opacity-30" title="下移">
                    <ArrowDown className="h-3.5 w-3.5" />
                  </button>
                  <button onClick={() => removeField(idx)} className="rounded p-1 text-danger hover:bg-destructive/10" title="删除">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input type="checkbox" checked={!!f.required} onChange={(e) => updateField(idx, { required: e.target.checked })} /> 必填
                </label>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input type="checkbox" checked={!!f.show_in_list} onChange={(e) => updateField(idx, { show_in_list: e.target.checked })} /> 列表显示
                </label>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input type="checkbox" checked={!!f.show_in_detail} onChange={(e) => updateField(idx, { show_in_detail: e.target.checked })} /> 详情显示
                </label>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  宽度
                  <select className="h-7 rounded border border-border bg-transparent px-1 text-xs" value={f.width || 'half'} onChange={(e) => updateField(idx, { width: e.target.value })}>
                    <option value="half">半行</option>
                    <option value="full">整行</option>
                  </select>
                </label>
                <input className={`${inputCls} h-7 max-w-[160px]`} value={f.placeholder || ''} onChange={(e) => updateField(idx, { placeholder: e.target.value })} placeholder="占位提示" />
                {f.type === 'select' && (
                  <input
                    className={`${inputCls} h-7 min-w-[200px] flex-1`}
                    value={(f.options || []).join(', ')}
                    onChange={(e) => updateField(idx, { options: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
                    placeholder="选项（逗号分隔）"
                  />
                )}
              </div>
            </div>
          ))}
          {form.fields.length === 0 && (
            <div className="rounded-lg border border-dashed border-border py-6 text-center text-xs text-muted-foreground">
              点击「添加字段」定义资产属性
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}

// ===== 标签管理 =====
function TagManager() {
  const [tags, setTags] = useState([])
  const [loading, setLoading] = useState(true)
  const [name, setName] = useState('')
  const [color, setColor] = useState('brand')
  const [category, setCategory] = useState('')
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try { setTags(await assetsApi.listTags()) } catch (e) { setErr(e.message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    if (!name.trim()) return
    setErr('')
    try {
      await assetsApi.createTag({ name: name.trim(), color, category: category.trim() || null })
      setName(''); setCategory('')
      load()
    } catch (e) { setErr(e.message || '创建失败') }
  }
  const handleDelete = async (t) => {
    if (!confirm(`确认删除标签「${t.name}」？关联资产的标签会自动解除。`)) return
    await assetsApi.deleteTag(t.id)
    load()
  }

  // 按 category 分组
  const grouped = tags.reduce((acc, t) => {
    const cat = t.category || '未分类'
    ;(acc[cat] = acc[cat] || []).push(t)
    return acc
  }, {})

  return (
    <Card>
      <div className="border-b border-border p-4">
        <h3 className="text-sm font-semibold text-foreground">标签管理</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">全局共享，多对多分组，按分类组织</p>
      </div>
      <div className="space-y-4 p-4">
        {/* 新建 */}
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-border bg-muted/20 p-3">
          <div className="min-w-[140px] flex-1">
            <label className={labelCls}>标签名称</label>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="如：核心系统" onKeyDown={(e) => e.key === 'Enter' && handleCreate()} />
          </div>
          <div className="min-w-[120px]">
            <label className={labelCls}>分类</label>
            <input className={inputCls} value={category} onChange={(e) => setCategory(e.target.value)} placeholder="如：安全等级" />
          </div>
          <div>
            <label className={labelCls}>颜色</label>
            <select className={inputCls} value={color} onChange={(e) => setColor(e.target.value)}>
              {['brand', 'success', 'warning', 'danger', 'neutral', 'info'].map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <button onClick={handleCreate} disabled={!name.trim()} className="btn-primary btn-sm flex items-center gap-1">
            <Plus className="h-3.5 w-3.5" /> 添加
          </button>
        </div>
        {err && <div className="text-xs text-danger">{err}</div>}
        {/* 列表（按分类分组） */}
        {loading ? (
          <LoadingState rows={3} />
        ) : tags.length === 0 ? (
          <EmptyState icon={TagIcon} title="暂无标签" description="创建标签用于资产分组与筛选" />
        ) : (
          <div className="space-y-4">
            {Object.entries(grouped).map(([cat, list]) => (
              <div key={cat}>
                <div className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">{cat}</div>
                <div className="flex flex-wrap gap-2">
                  {list.map((t) => (
                    <div key={t.id} className="group flex items-center gap-1.5 rounded-full border border-border bg-card py-1 pl-3 pr-1.5">
                      <Badge variant={t.color || 'brand'}>{t.name}</Badge>
                      <span className="text-[10px] text-muted-foreground">{t.asset_count}</span>
                      <button onClick={() => handleDelete(t)} className="rounded-full p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-danger group-hover:opacity-100" title="删除">
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

// ===== 主页面 =====
export default function AssetTemplates() {
  const [tab, setTab] = useState('templates') // templates | tags
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setTemplates(await assetsApi.listTemplates()) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const handleDelete = async (t) => {
    if (t.is_preset) { alert('预设模板不可删除'); return }
    if (!confirm(`确认删除模板「${t.name}」？已关联的资产数据保留（type_code 仍存）。`)) return
    await assetsApi.deleteTemplate(t.code)
    load()
  }

  return (
    <PageContainer>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">类型模板与标签</h1>
          <p className="mt-1 text-sm text-muted-foreground">定义资产数据模型（字段 schema）与全局标签</p>
        </div>
        <div className="flex items-center gap-2">
          {tab === 'templates' && (
            <button onClick={() => { setEditing(null); setEditorOpen(true) }} className="btn-primary btn-sm flex items-center gap-1">
              <Plus className="h-4 w-4" /> 新建类型
            </button>
          )}
          <button onClick={load} className="btn-secondary btn-sm flex items-center gap-1">
            <RefreshCw className="h-4 w-4" /> 刷新
          </button>
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="mb-4 flex items-center gap-1.5 border-b border-border pb-px">
        <button onClick={() => setTab('templates')} className={`relative rounded-t-md px-3 py-2 text-sm ${tab === 'templates' ? 'text-primary' : 'text-muted-foreground hover:text-foreground'}`}>
          类型模板
          {tab === 'templates' && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-primary" />}
        </button>
        <button onClick={() => setTab('tags')} className={`relative rounded-t-md px-3 py-2 text-sm ${tab === 'tags' ? 'text-primary' : 'text-muted-foreground hover:text-foreground'}`}>
          标签管理
          {tab === 'tags' && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-primary" />}
        </button>
      </div>

      {tab === 'templates' ? (
        loading ? <LoadingState rows={3} /> : error ? <ErrorState description={error} onRetry={load} /> : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {templates.map((t) => {
              const Icon = TEMPLATE_ICONS[t.code] || Boxes
              return (
                <Card key={t.code} hover className="flex flex-col">
                  <div className="flex items-start gap-3 border-b border-border p-4">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold text-foreground">{t.name}</span>
                        {t.is_preset ? (
                          <Badge variant="brand">预设</Badge>
                        ) : (
                          <Badge variant="neutral">自定义</Badge>
                        )}
                      </div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {t.code} · 标识：{t.identifier_field}
                        {t.allow_aggregate && (
                          <span className="ml-1 inline-flex items-center rounded border border-primary/40 bg-primary/10 px-1 text-[10px] text-primary">
                            聚合
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="min-h-0 flex-1 p-4">
                    {t.description && <p className="mb-3 text-xs text-muted-foreground">{t.description}</p>}
                    <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                      字段（{(t.fields || []).length}）
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {(t.fields || []).slice(0, 12).map((f) => (
                        <span key={f.key} className={`rounded border px-1.5 py-0.5 text-[10px] ${
                          f.key === t.identifier_field
                            ? 'border-primary/40 bg-primary/10 text-primary'
                            : 'border-border text-muted-foreground'
                        }`}>
                          {f.label || f.key}
                          {f.required && <span className="ml-0.5 text-danger">*</span>}
                        </span>
                      ))}
                      {(t.fields || []).length > 12 && (
                        <span className="text-[10px] text-muted-foreground">+{(t.fields || []).length - 12}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center justify-end gap-1 border-t border-border px-3 py-2">
                    <button onClick={() => { setEditing(t); setEditorOpen(true) }} className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
                      <Pencil className="h-3.5 w-3.5" /> 编辑
                    </button>
                    {!t.is_preset && (
                      <button onClick={() => handleDelete(t)} className="flex items-center gap-1 rounded px-2 py-1 text-xs text-danger hover:bg-destructive/10">
                        <Trash2 className="h-3.5 w-3.5" /> 删除
                      </button>
                    )}
                  </div>
                </Card>
              )
            })}
            {templates.length === 0 && (
              <div className="col-span-full">
                <EmptyState icon={Boxes} title="暂无资产类型" description="点击「新建类型」定义第一个资产数据模型" />
              </div>
            )}
          </div>
        )
      ) : (
        <TagManager />
      )}

      {/* 模板编辑器 */}
      <TemplateEditor
        open={editorOpen}
        template={editing}
        onClose={() => { setEditorOpen(false); setEditing(null) }}
        onSaved={load}
      />
    </PageContainer>
  )
}
