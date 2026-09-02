// 策略编辑页：表单/JSON 双模式（双向同步）+ 内嵌测试面板
// - 表单模式：基本信息 / 路由规则 / 外层解包 / 字段映射（增删行+拖拽排序）/ 枚举映射 / 校验规则 / 扩展字段
// - JSON 模式：直接编辑策略 JSON 全文，保存前解析校验，错误提示具体行号
// - 测试面板：粘贴样例原始日志 → 测试解析（纯内存不写库），展示路由匹配过程 / 逐字段映射 / 校验警告 / 标准模型 JSON
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft, Save, Plus, Trash2, FlaskConical, GripVertical, FileJson,
  Settings2, Table2, Braces, AlertTriangle, CheckCircle2, XCircle, ChevronRight,
} from 'lucide-react'
import { toast } from '../store/toastStore'
import { Button, PageContainer, Card, Badge, EmptyState } from '../components/ui'
import { inputCls, inputBaseCls, labelCls } from '../components/property/FormControls'
import { hasPermission } from '../utils/permissions'
import strategyApi from '../api/strategy'

// 全部转换类型（与后端 field_mapper 支持一致）
const CONVERT_TYPES = [
  { value: 'string', label: 'string（字符串）' },
  { value: 'int', label: 'int（整数）' },
  { value: 'float', label: 'float（浮点）' },
  { value: 'bool', label: 'bool（布尔）' },
  { value: 'json_array_to_string', label: 'json_array_to_string（数组→JSON串）' },
  { value: 'json_object_to_string', label: 'json_object_to_string（对象→JSON串）' },
  { value: 'timestamp_to_datetime', label: 'timestamp_to_datetime（时间戳→时间）' },
  { value: 'comma_split_to_json', label: 'comma_split_to_json（逗号串→JSON数组）' },
  { value: 'enum_int', label: 'enum_int（int 枚举）' },
]

const VALIDATION_RULE_TYPES = [
  { value: 'regex', label: 'regex（正则）' },
  { value: 'range', label: 'range（数值范围）' },
  { value: 'ip_list_valid', label: 'ip_list_valid（IP 合法性）' },
  { value: 'positive_int', label: 'positive_int（正整数）' },
]

// 新建策略默认配置
const EMPTY_CONFIG = {
  strategy_name: '',
  device_type: '',
  status: 'enabled',
  version: '1.0',
  route_rules: { match_type: 'exact', match_field: 'type', match_value: '' },
  outer_wrapper: { data_path: 'data', header_fields: [], uuid_source: 'data.uuId' },
  field_mappings: [{ source: '', target: '', type: 'string', required: false, default: '', enum_map: '', enum_target: '' }],
  enum_maps: {},
  validations: [],
  extension_fields: [],
}

// 从 JSON 解析错误信息提取行号（Chrome: "at position N" / Firefox: "at line L column C"）
function jsonErrorLine(text, err) {
  const msg = String(err?.message || err || '')
  let pos = null
  const m = msg.match(/position (\d+)/i)
  if (m) pos = Number(m[1])
  if (pos == null) {
    const lm = msg.match(/line (\d+)/i)
    if (lm) return Number(lm[1])
    return null
  }
  return text.slice(0, pos).split('\n').length
}

// ===== 小组件 =====
function SectionTitle({ icon: Icon, children, desc }) {
  return (
    <div className="mb-4 flex items-start gap-2">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <div>
        <h3 className="text-sm font-semibold text-foreground">{children}</h3>
        {desc && <p className="mt-0.5 text-xs text-muted-foreground">{desc}</p>}
      </div>
    </div>
  )
}

function ModeTab({ active, icon: Icon, label, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition ${
        active ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground'
      }`}
    >
      <Icon className="h-4 w-4" /> {label}
    </button>
  )
}

export default function StrategyEdit() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const isNew = !id
  const canEdit = hasPermission('strategy', 'edit')

  const [config, setConfig] = useState(EMPTY_CONFIG)
  const [mode, setMode] = useState('form') // form | json
  const [jsonText, setJsonText] = useState('')
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)

  // 下拉数据源
  const [targetFields, setTargetFields] = useState([])
  const [deviceTypes, setDeviceTypes] = useState([])

  // 测试面板
  const testRef = useRef(null)
  const [sampleText, setSampleText] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  // ===== 数据加载 =====
  useEffect(() => {
    strategyApi.fields().then(setTargetFields).catch(() => {})
    strategyApi.list().then((items) => {
      setDeviceTypes([...new Set((items || []).map((i) => i.device_type).filter(Boolean))])
    }).catch(() => {})
    if (!isNew) {
      setLoading(true)
      strategyApi.list()
        .then((items) => {
          const row = (items || []).find((i) => String(i.id) === String(id))
          if (!row) { toast.error('策略不存在'); navigate('/strategies'); return }
          setConfig({ ...EMPTY_CONFIG, ...(row.config || {}) })
          setJsonText(JSON.stringify({ ...EMPTY_CONFIG, ...(row.config || {}) }, null, 2))
        })
        .catch((e) => toast.error(e.message || '加载失败'))
        .finally(() => setLoading(false))
    }
  }, [id, isNew, navigate])

  // ?tab=test 时滚动到测试面板
  useEffect(() => {
    if (searchParams.get('tab') === 'test' && testRef.current) {
      testRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [searchParams])

  // ===== 模式切换（双向同步） =====
  const switchToForm = () => {
    // JSON → 表单：先校验
    let parsed
    try {
      parsed = JSON.parse(jsonText)
    } catch (e) {
      const line = jsonErrorLine(jsonText, e)
      toast.error(`JSON 格式错误${line ? `（约第 ${line} 行）` : ''}：${e.message}`)
      return
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      toast.error('策略配置必须是 JSON 对象')
      return
    }
    setConfig({ ...EMPTY_CONFIG, ...parsed })
    setMode('form')
  }

  const switchToJson = () => {
    // 表单 → JSON：序列化
    setJsonText(JSON.stringify(config, null, 2))
    setMode('json')
  }

  // 当前生效的配置（JSON 模式下从文本解析；解析失败返回 null）
  const effectiveConfig = useMemo(() => {
    if (mode === 'form') return config
    try {
      const parsed = JSON.parse(jsonText)
      return typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
    } catch {
      return null
    }
  }, [mode, config, jsonText])

  // ===== 表单更新辅助 =====
  const setCfg = (patch) => setConfig((c) => ({ ...c, ...patch }))
  const setRoute = (patch) => setConfig((c) => ({ ...c, route_rules: { ...c.route_rules, ...patch } }))
  const setWrapper = (patch) => setConfig((c) => ({ ...c, outer_wrapper: { ...c.outer_wrapper, ...patch } }))

  // ===== 字段映射行操作 =====
  const updateMapping = (idx, patch) => {
    setConfig((c) => {
      const list = [...c.field_mappings]
      list[idx] = { ...list[idx], ...patch }
      return { ...c, field_mappings: list }
    })
  }
  const addMapping = () => setConfig((c) => ({
    ...c,
    field_mappings: [...c.field_mappings, { source: '', target: '', type: 'string', required: false, default: '', enum_map: '', enum_target: '' }],
  }))
  const removeMapping = (idx) => setConfig((c) => ({ ...c, field_mappings: c.field_mappings.filter((_, i) => i !== idx) }))
  const reorderMapping = (from, to) => {
    setConfig((c) => {
      const list = [...c.field_mappings]
      const [item] = list.splice(from, 1)
      list.splice(to, 0, item)
      return { ...c, field_mappings: list }
    })
  }

  // 拖拽排序状态
  const [dragIdx, setDragIdx] = useState(null)
  const [overIdx, setOverIdx] = useState(null)

  // ===== 枚举映射操作 =====
  const enumNames = Object.keys(config.enum_maps || {})
  const addEnumGroup = () => {
    const name = `ENUM_${enumNames.length + 1}`
    setConfig((c) => ({ ...c, enum_maps: { ...c.enum_maps, [name]: { '0': '' } } }))
  }
  const renameEnumGroup = (oldName, newName) => {
    if (!newName || newName === oldName) return
    setConfig((c) => {
      const maps = {}
      Object.entries(c.enum_maps || {}).forEach(([k, v]) => { maps[k === oldName ? newName : k] = v })
      // 同步 field_mappings 中的 enum_map 引用
      const field_mappings = (c.field_mappings || []).map((m) => (m.enum_map === oldName ? { ...m, enum_map: newName } : m))
      return { ...c, enum_maps: maps, field_mappings }
    })
  }
  const removeEnumGroup = (name) => {
    setConfig((c) => {
      const maps = { ...c.enum_maps }
      delete maps[name]
      const field_mappings = (c.field_mappings || []).map((m) => (m.enum_map === name ? { ...m, enum_map: '' } : m))
      return { ...c, enum_maps: maps, field_mappings }
    })
  }
  const addEnumPair = (group) => {
    setConfig((c) => ({ ...c, enum_maps: { ...c.enum_maps, [group]: { ...c.enum_maps[group], '': '' } } }))
  }
  const updateEnumPair = (group, oldKey, patch) => {
    setConfig((c) => {
      const table = { ...c.enum_maps[group] }
      const nextKey = patch.key !== undefined ? patch.key : oldKey
      const rebuilt = {}
      Object.entries(table).forEach(([k, v]) => {
        if (k === oldKey) rebuilt[nextKey] = patch.value !== undefined ? patch.value : v
        else rebuilt[k] = v
      })
      return { ...c, enum_maps: { ...c.enum_maps, [group]: rebuilt } }
    })
  }
  const removeEnumPair = (group, key) => {
    setConfig((c) => {
      const table = { ...c.enum_maps[group] }
      delete table[key]
      return { ...c, enum_maps: { ...c.enum_maps, [group]: table } }
    })
  }

  // ===== 校验规则操作 =====
  const updateValidation = (idx, patch) => {
    setConfig((c) => {
      const list = [...(c.validations || [])]
      list[idx] = { ...list[idx], ...patch }
      return { ...c, validations: list }
    })
  }
  const addValidation = () => {
    setConfig((c) => ({ ...c, validations: [...(c.validations || []), { field: '', rule: 'regex', pattern: '', severity: 'warning' }] }))
  }
  const removeValidation = (idx) => setConfig((c) => ({ ...c, validations: (c.validations || []).filter((_, i) => i !== idx) }))

  // ===== 保存 =====
  const handleSave = () => {
    const cfg = effectiveConfig
    if (!cfg) {
      const err = 'JSON 格式错误，请先修正后再保存'
      toast.error(mode === 'json' ? err : '策略配置无效')
      return
    }
    if (!cfg.strategy_name?.trim()) return toast.error('策略名称不能为空')
    if (!cfg.device_type?.trim()) return toast.error('设备类型不能为空')
    if (!cfg.route_rules?.match_field) return toast.error('路由匹配字段不能为空')
    if (cfg.route_rules?.match_value == null || cfg.route_rules?.match_value === '') return toast.error('路由匹配值不能为空')

    setSaving(true)
    const req = isNew ? strategyApi.create(cfg) : strategyApi.update(id, cfg)
    req
      .then(() => {
        toast.success(isNew ? '策略已创建并生效' : '策略已保存并生效')
        if (isNew) navigate(`/strategies`)
        else {
          setConfig({ ...EMPTY_CONFIG, ...cfg })
          setJsonText(JSON.stringify(cfg, null, 2))
        }
      })
      .catch((e) => toast.error(e.message || '保存失败'))
      .finally(() => setSaving(false))
  }

  // ===== 测试解析 =====
  const handleTest = () => {
    const cfg = effectiveConfig
    if (!cfg) return toast.error('策略配置 JSON 格式错误，请先修正')
    let sample
    try {
      sample = JSON.parse(sampleText)
    } catch (e) {
      const line = jsonErrorLine(sampleText, e)
      return toast.error(`样例数据不是合法 JSON${line ? `（约第 ${line} 行）` : ''}：${e.message}`)
    }
    if (typeof sample !== 'object' || Array.isArray(sample)) return toast.error('样例数据必须是 JSON 对象')
    setTesting(true)
    strategyApi.test(cfg, sample)
      .then((res) => { setTestResult(res); toast.success(`解析完成（${res.parse_ms}ms）`) })
      .catch((e) => toast.error(e.message || '测试失败'))
      .finally(() => setTesting(false))
  }

  // ===== 渲染 =====
  if (loading) {
    return <PageContainer><div className="py-20 text-center text-sm text-muted-foreground">加载中…</div></PageContainer>
  }

  const headerFieldsText = (config.outer_wrapper?.header_fields || []).join(', ')

  return (
    <PageContainer>
      {/* 顶部操作栏 */}
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate('/strategies')}>
            <ArrowLeft className="h-4 w-4" /> 返回
          </Button>
          <h1 className="text-lg font-semibold text-foreground">{isNew ? '新建解析策略' : '编辑解析策略'}</h1>
          {!isNew && <Badge variant="neutral">ID {id}</Badge>}
        </div>
        <div className="flex items-center gap-2">
          <div className="mr-2 flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-1">
            <ModeTab active={mode === 'form'} icon={Table2} label="表单模式" onClick={switchToForm} />
            <ModeTab active={mode === 'json'} icon={Braces} label="JSON 模式" onClick={switchToJson} />
          </div>
          {canEdit && (
            <Button variant="primary" loading={saving} onClick={handleSave}>
              <Save className="h-4 w-4" /> 保存
            </Button>
          )}
        </div>
      </div>

      {mode === 'form' ? (
        <div className="space-y-4">
          {/* 基本信息 + 路由规则 */}
          <Card>
            <SectionTitle icon={Settings2} desc="策略标识与外层路由匹配规则（按原始日志外层字段匹配策略）">基本信息与路由规则</SectionTitle>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
              <div>
                <label className={labelCls}>策略名称 *</label>
                <input className={inputCls} value={config.strategy_name || ''} placeholder="如：Sangfor XDR 安全告警 v1.30"
                  onChange={(e) => setCfg({ strategy_name: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>设备类型 *（可自定义）</label>
                <input className={inputCls} value={config.device_type || ''} list="device-type-options" placeholder="如：sangfor_xdr"
                  onChange={(e) => setCfg({ device_type: e.target.value })} />
                <datalist id="device-type-options">
                  {deviceTypes.map((t) => <option key={t} value={t} />)}
                </datalist>
              </div>
              <div>
                <label className={labelCls}>版本号</label>
                <input className={inputCls} value={config.version || ''} placeholder="1.0"
                  onChange={(e) => setCfg({ version: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>状态</label>
                <select className={inputCls} value={config.status || 'enabled'}
                  onChange={(e) => setCfg({ status: e.target.value })}>
                  <option value="enabled">启用</option>
                  <option value="disabled">停用</option>
                </select>
              </div>
              <div>
                <label className={labelCls}>匹配字段 *</label>
                <input className={inputCls} value={config.route_rules?.match_field || ''} placeholder="如：type（支持点分路径）"
                  onChange={(e) => setRoute({ match_field: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>匹配方式</label>
                <select className={inputCls} value={config.route_rules?.match_type || 'exact'}
                  onChange={(e) => setRoute({ match_type: e.target.value })}>
                  <option value="exact">exact（精确匹配）</option>
                  <option value="regex">regex（正则匹配）</option>
                </select>
              </div>
              <div>
                <label className={labelCls}>匹配值 *</label>
                <input className={inputCls} value={config.route_rules?.match_value ?? ''} placeholder="如：security_alert"
                  onChange={(e) => setRoute({ match_value: e.target.value })} />
              </div>
            </div>
          </Card>

          {/* 外层解包 */}
          <Card>
            <SectionTitle icon={FileJson} desc="业务数据在原始日志中的位置；header 字段与扩展字段一起归档到 extensions">外层解包</SectionTitle>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-3">
              <div>
                <label className={labelCls}>data 路径</label>
                <input className={inputCls} value={config.outer_wrapper?.data_path || ''} placeholder="如：data"
                  onChange={(e) => setWrapper({ data_path: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>uuid 来源路径</label>
                <input className={inputCls} value={config.outer_wrapper?.uuid_source || ''} placeholder="如：data.uuId"
                  onChange={(e) => setWrapper({ uuid_source: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>header 字段（逗号分隔）</label>
                <input className={inputCls} value={headerFieldsText} placeholder="如：sendTime, tenant, type"
                  onChange={(e) => setWrapper({ header_fields: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} />
              </div>
            </div>
          </Card>

          {/* 字段映射 */}
          <Card>
            <SectionTitle icon={Table2} desc="源字段 → 标准模型字段；拖动行可调整顺序">字段映射</SectionTitle>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="w-8 px-2 py-2" />
                    <th className="px-2 py-2 font-semibold">源字段路径</th>
                    <th className="px-2 py-2 font-semibold">目标字段</th>
                    <th className="px-2 py-2 font-semibold">转换类型</th>
                    <th className="w-14 px-2 py-2 font-semibold">必填</th>
                    <th className="px-2 py-2 font-semibold">默认值</th>
                    <th className="px-2 py-2 font-semibold">枚举映射名</th>
                    <th className="px-2 py-2 font-semibold">枚举目标字段</th>
                    <th className="w-10 px-2 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {(config.field_mappings || []).map((m, i) => (
                    <tr
                      key={i}
                      draggable
                      onDragStart={(e) => { setDragIdx(i); e.dataTransfer.effectAllowed = 'move' }}
                      onDragOver={(e) => { if (dragIdx == null) return; e.preventDefault(); if (overIdx !== i) setOverIdx(i) }}
                      onDragLeave={() => overIdx === i && setOverIdx(null)}
                      onDrop={(e) => {
                        e.preventDefault()
                        if (dragIdx != null && dragIdx !== i) reorderMapping(dragIdx, i)
                        setDragIdx(null); setOverIdx(null)
                      }}
                      onDragEnd={() => { setDragIdx(null); setOverIdx(null) }}
                      className={`border-b border-border/60 ${dragIdx === i ? 'opacity-40' : ''} ${overIdx === i && dragIdx !== null && dragIdx !== i ? 'bg-primary/5 ring-2 ring-inset ring-primary/40' : ''}`}
                    >
                      <td className="px-2 py-1.5"><GripVertical className="h-4 w-4 cursor-grab text-muted-foreground active:cursor-grabbing" /></td>
                      <td className="px-2 py-1.5">
                        <input className={`${inputBaseCls} w-36`} value={m.source || ''} placeholder="源字段名"
                          onChange={(e) => updateMapping(i, { source: e.target.value })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <input className={`${inputBaseCls} w-40`} value={m.target || ''} list="target-field-options" placeholder="目标字段"
                          onChange={(e) => updateMapping(i, { target: e.target.value })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <select className={`${inputBaseCls} w-52`} value={m.type || 'string'}
                          onChange={(e) => updateMapping(i, { type: e.target.value })}>
                          {CONVERT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        <input type="checkbox" className="h-4 w-4 cursor-pointer accent-primary" checked={!!m.required}
                          onChange={(e) => updateMapping(i, { required: e.target.checked })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <input className={`${inputBaseCls} w-24`} value={m.default ?? ''} placeholder="默认值"
                          onChange={(e) => updateMapping(i, { default: e.target.value })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <select className={`${inputBaseCls} w-32`} value={m.enum_map || ''}
                          onChange={(e) => {
                            const enumMap = e.target.value
                            updateMapping(i, { enum_map, enum_target: enumMap && !m.enum_target ? `${m.target || ''}_name` : m.enum_target || '' })
                          }}>
                          <option value="">（无）</option>
                          {enumNames.map((n) => <option key={n} value={n}>{n}</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-1.5">
                        <input className={`${inputBaseCls} w-36`} value={m.enum_target || ''} placeholder="枚举翻译写入字段"
                          onChange={(e) => updateMapping(i, { enum_target: e.target.value })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                          title="删除该行" onClick={() => removeMapping(i)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3">
              <Button size="sm" onClick={addMapping}><Plus className="h-3.5 w-3.5" /> 添加映射</Button>
            </div>
          </Card>

          {/* 枚举映射 */}
          <Card>
            <SectionTitle icon={Braces} desc="枚举名对应多组「原值 → 翻译值」，供字段映射引用">枚举映射</SectionTitle>
            {enumNames.length === 0 ? (
              <EmptyState icon={Braces} title="暂无枚举映射" description="添加枚举映射后可在字段映射中选择枚举名，实现 int 值翻译为中文" />
            ) : (
              <div className="space-y-4">
                {enumNames.map((name) => {
                  const table = config.enum_maps[name] || {}
                  return (
                    <div key={name} className="rounded-lg border border-border p-3">
                      <div className="mb-2 flex items-center gap-2">
                        <input className={`${inputBaseCls} w-44 font-mono`} value={name}
                          onChange={(e) => renameEnumGroup(name, e.target.value)} />
                        <span className="text-xs text-muted-foreground">枚举名（字段映射中引用）</span>
                        <div className="ml-auto flex items-center gap-1">
                          <Button size="sm" onClick={() => addEnumPair(name)}><Plus className="h-3.5 w-3.5" /> 添加</Button>
                          <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                            title="删除该枚举组" onClick={() => removeEnumGroup(name)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                      <table className="w-full border-collapse text-sm">
                        <tbody>
                          {Object.entries(table).map(([k, v]) => (
                            <tr key={k} className="border-b border-border/40 last:border-0">
                              <td className="w-40 py-1.5 pr-2">
                                <input className={`${inputBaseCls} w-full`} value={k} placeholder="原值"
                                  onChange={(e) => updateEnumPair(name, k, { key: e.target.value })} />
                              </td>
                              <td className="w-6 py-1.5 text-center text-muted-foreground">→</td>
                              <td className="w-48 py-1.5 pr-2">
                                <input className={`${inputBaseCls} w-full`} value={v} placeholder="翻译值"
                                  onChange={(e) => updateEnumPair(name, k, { value: e.target.value })} />
                              </td>
                              <td className="w-10 py-1.5">
                                <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                                  title="删除该对" onClick={() => removeEnumPair(name, k)}>
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="mt-3">
              <Button size="sm" onClick={addEnumGroup}><Plus className="h-3.5 w-3.5" /> 添加枚举组</Button>
            </div>
          </Card>

          {/* 校验规则 */}
          <Card>
            <SectionTitle icon={AlertTriangle} desc="校验失败不阻断入库，记入 parse_warnings 并使解析状态降为 partial">校验规则</SectionTitle>
            {(config.validations || []).length === 0 ? (
              <EmptyState icon={AlertTriangle} title="暂无校验规则" description="可对解析后的标准字段做正则 / 范围 / IP 合法性校验" />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="px-2 py-2 font-semibold">校验字段</th>
                      <th className="px-2 py-2 font-semibold">规则类型</th>
                      <th className="px-2 py-2 font-semibold">参数</th>
                      <th className="px-2 py-2 font-semibold">严重级别</th>
                      <th className="w-10 px-2 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {(config.validations || []).map((v, i) => (
                      <tr key={i} className="border-b border-border/60">
                        <td className="px-2 py-1.5">
                          <input className={`${inputBaseCls} w-44`} value={v.field || ''} list="target-field-options" placeholder="标准字段"
                            onChange={(e) => updateValidation(i, { field: e.target.value })} />
                        </td>
                        <td className="px-2 py-1.5">
                          <select className={`${inputBaseCls} w-44`} value={v.rule || 'regex'}
                            onChange={(e) => updateValidation(i, { rule: e.target.value })}>
                            {VALIDATION_RULE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          {v.rule === 'regex' && (
                            <input className={`${inputBaseCls} w-52 font-mono`} value={v.pattern || ''} placeholder="正则表达式"
                              onChange={(e) => updateValidation(i, { pattern: e.target.value })} />
                          )}
                          {v.rule === 'range' && (
                            <div className="flex items-center gap-1.5">
                              <input className={`${inputBaseCls} w-16`} type="number" value={v.min ?? ''} placeholder="最小"
                                onChange={(e) => updateValidation(i, { min: e.target.value === '' ? null : Number(e.target.value) })} />
                              <span className="text-muted-foreground">~</span>
                              <input className={`${inputBaseCls} w-16`} type="number" value={v.max ?? ''} placeholder="最大"
                                onChange={(e) => updateValidation(i, { max: e.target.value === '' ? null : Number(e.target.value) })} />
                            </div>
                          )}
                          {(v.rule === 'ip_list_valid' || v.rule === 'positive_int') && (
                            <span className="text-xs text-muted-foreground">（无需参数）</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5">
                          <select className={`${inputBaseCls} w-28`} value={v.severity || 'warning'}
                            onChange={(e) => updateValidation(i, { severity: e.target.value })}>
                            <option value="warning">warning</option>
                            <option value="error">error</option>
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                            title="删除该规则" onClick={() => removeValidation(i)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-3">
              <Button size="sm" onClick={addValidation}><Plus className="h-3.5 w-3.5" /> 添加规则</Button>
            </div>
          </Card>

          {/* 扩展字段 */}
          <Card>
            <SectionTitle icon={FileJson} desc="策略特有、标准模型未覆盖的源字段，一行一个字段名，归档到 extensions JSON">扩展字段归档</SectionTitle>
            <textarea
              className={`${inputCls} min-h-[96px] font-mono`}
              value={(config.extension_fields || []).join('\n')}
              placeholder={'containerName\ncontainerId\nclusterName'}
              onChange={(e) => setCfg({ extension_fields: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean) })}
            />
          </Card>

          {/* 标准字段 datalist（目标字段下拉建议，来自后端） */}
          <datalist id="target-field-options">
            {targetFields.map((f) => (
              <option key={f.name} value={f.name}>{f.comment || f.name}（{f.type}）</option>
            ))}
          </datalist>
        </div>
      ) : (
        // JSON 模式
        <Card>
          <SectionTitle icon={Braces} desc="直接编辑策略 JSON 全文；保存前会做结构与正则校验">策略 JSON</SectionTitle>
          <textarea
            className="w-full rounded-md border border-input bg-background p-4 font-mono text-[13px] leading-relaxed text-foreground outline-none transition hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary"
            style={{ minHeight: 520 }}
            spellCheck={false}
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
          />
          {effectiveConfig == null && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-destructive">
              <AlertTriangle className="h-3.5 w-3.5" /> JSON 格式错误：切换到表单模式或保存时可查看具体错误位置
            </div>
          )}
        </Card>
      )}

      {/* 测试面板 */}
      <div ref={testRef} className="mt-4 scroll-mt-4">
        <Card>
          <SectionTitle icon={FlaskConical} desc="纯内存执行不写库；验证路由命中 → 解包 → 映射 → 枚举翻译 → 校验全链路">测试解析</SectionTitle>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
            {/* 左侧：样例输入 */}
            <div className="lg:col-span-2">
              <label className={labelCls}>样例原始日志 JSON</label>
              <textarea
                className="w-full rounded-md border border-input bg-background p-3 font-mono text-xs leading-relaxed text-foreground outline-none transition hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary"
                style={{ minHeight: 240 }}
                spellCheck={false}
                placeholder='粘贴设备推送的原始告警 JSON，如：
{
  "type": "security_alert",
  "data": { ... }
}'
                value={sampleText}
                onChange={(e) => setSampleText(e.target.value)}
              />
              <div className="mt-3 flex items-center gap-2">
                <Button variant="primary" size="sm" loading={testing} onClick={handleTest}>
                  <FlaskConical className="h-4 w-4" /> 测试解析
                </Button>
                {testResult && (
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    解析用时 {testResult.parse_ms}ms
                  </span>
                )}
              </div>
            </div>

            {/* 右侧：解析结果 */}
            <div className="lg:col-span-3">
              {!testResult ? (
                <EmptyState icon={FlaskConical} title="尚未执行测试" description="粘贴样例数据后点击「测试解析」查看逐字段解析明细" className="h-full" />
              ) : (
                <div className="space-y-4">
                  {/* 路由匹配 */}
                  <div className="rounded-lg border border-border p-3">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-xs font-semibold text-muted-foreground">路由匹配</span>
                      {testResult.route.matched
                        ? <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" />命中</Badge>
                        : <Badge variant="danger"><XCircle className="mr-1 h-3 w-3" />未命中</Badge>}
                      <span className="text-xs text-muted-foreground">
                        {testResult.route.match_type} · {testResult.route.match_field} = {String(testResult.route.actual_value ?? 'null')}
                      </span>
                    </div>
                    {(testResult.db_hits || []).length > 0 && (
                      <div className="space-y-1">
                        <div className="text-[11px] text-muted-foreground">已启用策略匹配过程：</div>
                        {testResult.db_hits.map((h) => (
                          <div key={h.id} className="flex items-center gap-2 text-xs">
                            <ChevronRight className="h-3 w-3 text-muted-foreground" />
                            <span className="max-w-[220px] truncate">{h.strategy_name}</span>
                            <span className="text-muted-foreground">{h.match_field} == {String(h.match_value)}</span>
                            {h.hit ? <Badge variant="success">命中</Badge> : <Badge variant="neutral">未命中</Badge>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* 解包 */}
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-semibold text-muted-foreground">外层解包：</span>
                    <code className="rounded bg-muted px-1.5 py-0.5">{testResult.unwrap.data_path || '(根对象)'}</code>
                    {testResult.unwrap.found ? <Badge variant="success">成功</Badge> : <Badge variant="danger">data 路径不存在</Badge>}
                  </div>

                  {/* 字段映射明细 */}
                  <div className="overflow-x-auto rounded-lg border border-border">
                    <table className="w-full border-collapse text-xs">
                      <thead>
                        <tr className="border-b border-border bg-muted/50 text-left text-muted-foreground">
                          <th className="px-2 py-1.5 font-semibold">源字段</th>
                          <th className="px-2 py-1.5 font-semibold">目标字段</th>
                          <th className="px-2 py-1.5 font-semibold">类型</th>
                          <th className="px-2 py-1.5 font-semibold">源值</th>
                          <th className="px-2 py-1.5 font-semibold">转换后</th>
                          <th className="px-2 py-1.5 font-semibold">状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        {testResult.mappings.map((m, i) => (
                          <tr key={i} className="border-b border-border/40 last:border-0">
                            <td className="px-2 py-1.5 font-mono">{m.source || '-'}</td>
                            <td className="px-2 py-1.5 font-mono">{m.target || '-'}</td>
                            <td className="px-2 py-1.5 font-mono text-muted-foreground">{m.type}</td>
                            <td className="max-w-[160px] truncate px-2 py-1.5" title={String(m.raw_value ?? '')}>
                              {m.missing ? <span className="text-muted-foreground">(缺失)</span> : String(m.raw_value ?? 'null')}
                            </td>
                            <td className="max-w-[160px] truncate px-2 py-1.5" title={String(m.converted ?? '')}>{String(m.converted ?? 'null')}</td>
                            <td className="px-2 py-1.5">
                              {m.warning
                                ? <span className="text-warning" title={m.warning}>⚠ 警告</span>
                                : <span className="text-success">✓</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* 校验警告 */}
                  <div>
                    <div className="mb-1.5 flex items-center gap-2 text-xs">
                      <span className="font-semibold text-muted-foreground">校验与警告</span>
                      <Badge variant={testResult.warnings.length ? 'warning' : 'success'}>
                        {testResult.warnings.length ? `${testResult.warnings.length} 条警告 · 状态 partial` : '无警告 · 状态 success'}
                      </Badge>
                    </div>
                    {testResult.warnings.length > 0 && (
                      <ul className="space-y-1 rounded-lg border border-warning/30 bg-warning/5 p-2">
                        {testResult.warnings.map((w, i) => (
                          <li key={i} className="flex items-start gap-1.5 text-xs text-warning">
                            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                            <span><code className="font-mono">{w.field || w.source}</code>：{w.message}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {/* 标准模型 JSON 预览 */}
                  <div>
                    <div className="mb-1.5 text-xs font-semibold text-muted-foreground">标准模型 JSON 预览（入库 alert_events 字段）</div>
                    <pre className="max-h-64 overflow-auto rounded-lg border border-border bg-muted/30 p-3 font-mono text-[11px] leading-relaxed text-foreground">
                      {JSON.stringify(testResult.fields, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </Card>
      </div>
    </PageContainer>
  )
}
