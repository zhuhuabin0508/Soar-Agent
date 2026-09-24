// 策略编辑页：表单/JSON 双模式（双向同步）+ 内嵌测试面板
// - 规则化：一个策略内包含多条规则（rules[]），每条规则负责一种日志类型
// - 每条规则 = match（识别日志类别）+ extract（提取字段，fields/regex/template 三选）+ map（映射/枚举/默认值/校验）
// - 表单模式：基本信息 / 外层解包 / 规则列表（增删、切换活跃规则）+ 活跃规则编辑区
// - JSON 模式：直接编辑策略 JSON 全文，保存前解析校验，错误提示具体行号
// - 测试面板：粘贴样例原始日志 → 测试解析，展示命中规则 / 提取明细 / 校验警告 / 标准模型 JSON
import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft, Save, Plus, Trash2, FlaskConical, FileJson,
  Settings2, Table2, Braces, AlertTriangle, CheckCircle2, XCircle, ChevronRight,
  Layers, Crosshair, Scissors,
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
  { value: 'qt_datetime', label: 'qt_datetime（快速时间格式）' },
]

const VALIDATION_RULE_TYPES = [
  { value: 'regex', label: 'regex（正则）' },
  { value: 'range', label: 'range（数值范围）' },
  { value: 'ip_list_valid', label: 'ip_list_valid（IP 合法性）' },
  { value: 'positive_int', label: 'positive_int（正整数）' },
]

const MATCH_OPS = [
  { value: 'eq', label: 'eq（等于）' },
  { value: 'not_eq', label: 'not_eq（不等于）' },
  { value: 'in', label: 'in（属于集合）' },
  { value: 'not_in', label: 'not_in（不属于）' },
  { value: 'contains', label: 'contains（包含）' },
  { value: 'regex', label: 'regex（正则）' },
  { value: 'gte', label: 'gte（≥）' },
  { value: 'gt', label: 'gt（＞）' },
  { value: 'lte', label: 'lte（≤）' },
  { value: 'lt', label: 'lt（＜）' },
]

const EXTRACT_TYPES = [
  { value: 'fields', label: 'fields（字段路径取数）' },
  { value: 'regex', label: 'regex（正则命名组）' },
  { value: 'template', label: 'template（分隔符模板）' },
]

// 默认的单条 extract.fields 映射行
const emptyMappingRow = () => ({ source: '', target: '', type: 'string', required: false, default: '', enum_map: '', enum_target: '' })

// 新建规则默认结构
const emptyRule = (idx) => ({
  rule_id: `rule_${idx + 1}`,
  log_type: `日志类型 ${idx + 1}`,
  enabled: true,
  match: { type: 'all', conditions: [{ field: 'type', op: 'eq', value: '' }] },
  extract: { type: 'fields', fields: [emptyMappingRow()] },
  map: { enum_maps: {}, defaults: [], validations: [] },
  extension_fields: [],
})

// 新建策略默认配置（规则化结构）
const EMPTY_CONFIG = {
  strategy_name: '',
  device_type: '',
  status: 'enabled',
  version: '1.0',
  outer_wrapper: { data_path: 'data', header_fields: [], uuid_source: 'data.uuId' },
  rules: [emptyRule(0)],
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

  // 规则列表：当前激活编辑的规则索引
  const [activeRuleIdx, setActiveRuleIdx] = useState(0)

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
          const merged = { ...EMPTY_CONFIG, ...(row.config || {}) }
          // 旧结构策略（无 rules）在表单中展示为单规则
          if (!Array.isArray(merged.rules) || merged.rules.length === 0) {
            merged.rules = [emptyRule(0)]
          }
          setConfig(merged)
          setActiveRuleIdx(0)
          setJsonText(JSON.stringify(merged, null, 2))
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
    if (!Array.isArray(parsed.rules) || parsed.rules.length === 0) {
      parsed = { ...parsed, rules: [emptyRule(0)] }
    }
    setConfig({ ...EMPTY_CONFIG, ...parsed })
    setActiveRuleIdx(0)
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
  const setWrapper = (patch) => setConfig((c) => ({ ...c, outer_wrapper: { ...c.outer_wrapper, ...patch } }))

  // ===== 规则列表操作 =====
  const rules = config.rules || []
  const activeRule = rules[activeRuleIdx] || rules[0] || emptyRule(0)
  const activeIdx = Math.min(activeRuleIdx, Math.max(0, rules.length - 1))

  const updateRule = (idx, patch) => {
    setConfig((c) => {
      const list = [...(c.rules || [])]
      list[idx] = { ...(list[idx] || emptyRule(idx)), ...patch }
      return { ...c, rules: list }
    })
  }
  const addRule = () => {
    setConfig((c) => {
      const list = [...(c.rules || []), emptyRule((c.rules || []).length)]
      return { ...c, rules: list }
    })
    setActiveRuleIdx(rules.length)
  }
  const removeRule = (idx) => {
    setConfig((c) => {
      const list = (c.rules || []).filter((_, i) => i !== idx)
      return { ...c, rules: list.length ? list : [emptyRule(0)] }
    })
    // 移除的是激活规则 → 回退到第一条
    setActiveRuleIdx((cur) => (cur === idx ? 0 : Math.max(0, cur - 1)))
  }

  // 更新活跃规则深层结构
  const updateActiveRule = (patch) => updateRule(activeIdx, patch)
  const setActiveMatch = (patch) => updateActiveRule({ match: { ...(activeRule.match || {}), ...patch } })
  const setActiveExtract = (patch) => updateActiveRule({ extract: { ...(activeRule.extract || {}), ...patch } })
  const setActiveMap = (patch) => updateActiveRule({ map: { ...(activeRule.map || {}), ...patch } })

  // match 条件操作
  const defaultCond = () => ({ field: 'type', op: 'eq', value: '' })
  const activeConditions = (activeRule.match || {}).conditions || []
  const updateCondition = (ci, patch) => {
    const list = [...activeConditions]
    list[ci] = { ...list[ci], ...patch }
    setActiveMatch({ conditions: list })
  }
  const addCondition = () => setActiveMatch({ conditions: [...activeConditions, defaultCond()] })
  const removeCondition = (ci) => setActiveMatch({ conditions: activeConditions.filter((_, i) => i !== ci) })

  // extract.fields 映射行操作（活跃规则）
  const extractFields = ((activeRule.extract || {}).type === 'fields') ? ((activeRule.extract || {}).fields || []) : []
  const updateExtractField = (fi, patch) => {
    const list = [...extractFields]
    list[fi] = { ...list[fi], ...patch }
    setActiveExtract({ type: 'fields', fields: list })
  }
  const addExtractField = () => setActiveExtract({ type: 'fields', fields: [...extractFields, emptyMappingRow()] })
  const removeExtractField = (fi) => setActiveExtract({ type: 'fields', fields: extractFields.filter((_, i) => i !== fi) })

  // regex / template 的 mappings 操作（用 index/group 定位，命名为 rowKey）
  const regexMappings = ((activeRule.extract || {}).mappings) || []
  const updateRegexMapping = (ri, patch) => {
    const list = [...regexMappings]
    list[ri] = { ...(list[ri] || {}), ...patch }
    setActiveExtract({ type: 'regex', regex: (activeRule.extract || {}).regex || '', source: (activeRule.extract || {}).source || '', mappings: list })
  }
  const addRegexMapping = () => setActiveExtract({ type: 'regex', regex: (activeRule.extract || {}).regex || '', source: (activeRule.extract || {}).source || '', mappings: [...regexMappings, { group: '', target: '', type: 'string', default: '' }] })
  const removeRegexMapping = (ri) => setActiveExtract({ type: 'regex', regex: (activeRule.extract || {}).regex || '', source: (activeRule.extract || {}).source || '', mappings: regexMappings.filter((_, i) => i !== ri) })

  const templateMappings = ((activeRule.extract || {}).mappings) || []
  const updateTemplateMapping = (ri, patch) => {
    const list = [...templateMappings]
    list[ri] = { ...(list[ri] || {}), ...patch }
    setActiveExtract({ type: 'template', sep: (activeRule.extract || {}).sep || '\\s+', columns: (activeRule.extract || {}).columns || [], source: (activeRule.extract || {}).source || '', mappings: list })
  }
  const addTemplateMapping = () => setActiveExtract({ type: 'template', sep: (activeRule.extract || {}).sep || '\\s+', columns: (activeRule.extract || {}).columns || [], source: (activeRule.extract || {}).source || '', mappings: [...templateMappings, { index: (activeRule.extract || {}).columns?.length || 0, target: '', type: 'string' }] })
  const removeTemplateMapping = (ri) => setActiveExtract({ type: 'template', sep: (activeRule.extract || {}).sep || '\\s+', columns: (activeRule.extract || {}).columns || [], source: (activeRule.extract || {}).source || '', mappings: templateMappings.filter((_, i) => i !== ri) })

  // map.enum_maps 操作（活跃规则）
  const ruleEnumMaps = ((activeRule.map || {}).enum_maps) || {}
  const ruleEnumNames = Object.keys(ruleEnumMaps)
  const addRuleEnumGroup = () => {
    const name = `ENUM_${ruleEnumNames.length + 1}`
    setActiveMap({ enum_maps: { ...ruleEnumMaps, [name]: { '0': '' } } })
  }
  const removeRuleEnumGroup = (name) => {
    const maps = { ...ruleEnumMaps }
    delete maps[name]
    // 同步 extract.fields / map.defaults 引用（字段映射里 enum_map 引用）
    setActiveMap({ enum_maps: maps })
    const fields = extractFields.map((m) => (m.enum_map === name ? { ...m, enum_map: '', enum_target: '' } : m))
    if (activeRule.extract?.type === 'fields') setActiveExtract({ type: 'fields', fields })
  }
  const addRuleEnumPair = (group) => setActiveMap({ enum_maps: { ...ruleEnumMaps, [group]: { ...ruleEnumMaps[group], '': '' } } })
  const updateRuleEnumPair = (group, oldKey, patch) => {
    const table = { ...ruleEnumMaps[group] }
    const nextKey = patch.key !== undefined ? patch.key : oldKey
    const rebuilt = {}
    Object.entries(table).forEach(([k, v]) => {
      if (k === oldKey) rebuilt[nextKey] = patch.value !== undefined ? patch.value : v
      else rebuilt[k] = v
    })
    setActiveMap({ enum_maps: { ...ruleEnumMaps, [group]: rebuilt } })
  }
  const removeRuleEnumPair = (group, key) => {
    const table = { ...ruleEnumMaps[group] }
    delete table[key]
    setActiveMap({ enum_maps: { ...ruleEnumMaps, [group]: table } })
  }

  // map.defaults 操作（活跃规则）
  const ruleDefaults = ((activeRule.map || {}).defaults) || []
  const updateRuleDefault = (di, patch) => {
    const list = [...ruleDefaults]
    list[di] = { ...list[di], ...patch }
    setActiveMap({ defaults: list })
  }
  const addRuleDefault = () => setActiveMap({ defaults: [...ruleDefaults, { target: '', value: '' }] })
  const removeRuleDefault = (di) => setActiveMap({ defaults: ruleDefaults.filter((_, i) => i !== di) })

  // map.validations 操作（活跃规则）
  const ruleValidations = ((activeRule.map || {}).validations) || []
  const updateRuleValidation = (vi, patch) => {
    const list = [...ruleValidations]
    list[vi] = { ...list[vi], ...patch }
    setActiveMap({ validations: list })
  }
  const addRuleValidation = () => setActiveMap({ validations: [...ruleValidations, { field: '', rule: 'regex', pattern: '', severity: 'warning' }] })
  const removeRuleValidation = (vi) => setActiveMap({ validations: ruleValidations.filter((_, i) => i !== vi) })

  // extension_fields（活跃规则）
  const ruleExtFields = (activeRule.extension_fields) || []
  const setRuleExtFields = (val) => updateActiveRule({ extension_fields: val })

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
    if (!Array.isArray(cfg.rules) || cfg.rules.length === 0) return toast.error('至少需要一条解析规则')

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
  const activeExtractType = (activeRule.extract || {}).type || 'fields'

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
          {/* 基本信息 */}
          <Card>
            <SectionTitle icon={Settings2} desc="策略标识，绑定到设备 / 日志渠道后对推送日志生效">基本信息</SectionTitle>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
              <div>
                <label className={labelCls}>策略名称 *</label>
                <input className={inputCls} value={config.strategy_name || ''} placeholder="如：青藤万相全日志 v3.4"
                  onChange={(e) => setCfg({ strategy_name: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>设备类型 *（可自定义）</label>
                <input className={inputCls} value={config.device_type || ''} list="device-type-options" placeholder="如：qingteng_wanxiang"
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
            </div>
          </Card>

          {/* 外层解包 */}
          <Card>
            <SectionTitle icon={FileJson} desc="业务数据在原始日志中的位置；header 字段与规则扩展字段一起归档到 extensions">外层解包</SectionTitle>
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

          {/* 规则列表 + 活跃规则编辑 */}
          <Card>
            <SectionTitle icon={Layers} desc="一个策略可含多条规则，每条负责一种日志类型；先按 match 识别类别，再按 extract 提取字段">解析规则（rules）</SectionTitle>

            {/* 规则标签页 */}
            <div className="mb-4 flex flex-wrap items-center gap-2">
              {rules.map((r, i) => (
                <div key={i} className="flex items-center">
                  <button
                    onClick={() => setActiveRuleIdx(i)}
                    className={`flex items-center gap-1.5 rounded-l-md border border-r-0 px-3 py-1.5 text-xs transition ${
                      activeIdx === i ? 'border-primary bg-primary/10 font-medium text-primary' : 'border-border bg-muted/30 text-muted-foreground hover:bg-accent'
                    }`}
                    title={r.enabled === false ? '（已停用）' : `规则：${r.rule_id}`}
                  >
                    {r.enabled === false && <span className="text-muted-foreground">（停用）</span>}
                    <span className="max-w-[140px] truncate">{r.log_type || r.rule_id || `规则 ${i + 1}`}</span>
                  </button>
                  <button
                    title="删除该规则"
                    onClick={() => removeRule(i)}
                    className="flex h-7 w-7 items-center justify-center rounded-r-md border border-border bg-muted/30 text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
              <Button size="sm" onClick={addRule}><Plus className="h-3.5 w-3.5" /> 添加规则</Button>
            </div>

            {/* 活跃规则编辑区 */}
            <div className="space-y-4 rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center gap-3">
                <label className={labelCls}>规则标识（rule_id）</label>
                <input className={`${inputBaseCls} w-40 font-mono`} value={activeRule.rule_id || ''} placeholder="如：alert"
                  onChange={(e) => updateActiveRule({ rule_id: e.target.value })} />
                <label className={labelCls}>日志类型名</label>
                <input className={`${inputBaseCls} w-48`} value={activeRule.log_type || ''} placeholder="如：安全告警"
                  onChange={(e) => updateActiveRule({ log_type: e.target.value })} />
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input type="checkbox" className="h-3.5 w-3.5 accent-primary" checked={activeRule.enabled !== false}
                    onChange={(e) => updateActiveRule({ enabled: e.target.checked })} />
                  启用该规则
                </label>
                <div className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
                  当前规则 #{activeIdx + 1} / {rules.length}
                </div>
              </div>

              {/* 1. 匹配条件（识别） */}
              <div className="rounded-lg border border-border/70 p-3">
                <div className="mb-2 flex items-center gap-2">
                  <Crosshair className="h-4 w-4 text-primary" />
                  <span className="text-sm font-semibold text-foreground">匹配条件（识别日志类别）</span>
                  <select className={`${inputBaseCls} ml-2 w-24 text-xs`} value={(activeRule.match || {}).type || 'all'}
                    onChange={(e) => setActiveMatch({ type: e.target.value })}>
                    <option value="all">all（全部满足）</option>
                    <option value="any">any（任一满足）</option>
                  </select>
                </div>
                {activeConditions.length === 0 ? (
                  <EmptyState icon={Crosshair} title="无条件（恒命中）" description="添加条件后按原始日志字段识别本次日志类别" />
                ) : (
                  <div className="space-y-2">
                    {activeConditions.map((cond, ci) => (
                      <div key={ci} className="flex items-center gap-2">
                        <input className={`${inputBaseCls} w-44 font-mono`} value={cond.field || ''} placeholder="字段路径（如 type）"
                          onChange={(e) => updateCondition(ci, { field: e.target.value })} />
                        <select className={`${inputBaseCls} w-36`} value={cond.op || 'eq'}
                          onChange={(e) => updateCondition(ci, { op: e.target.value })}>
                          {MATCH_OPS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                        <input className={`${inputBaseCls} flex-1 font-mono`} value={cond.value ?? ''}
                          placeholder={cond.op === 'in' || cond.op === 'not_in' ? 'JSON 数组，如 ["a","b"]' : '匹配值'}
                          onChange={(e) => updateCondition(ci, { value: e.target.value })} />
                        <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                          title="删除条件" onClick={() => removeCondition(ci)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-2">
                  <Button size="sm" onClick={addCondition}><Plus className="h-3.5 w-3.5" /> 添加条件</Button>
                </div>
              </div>

              {/* 2. 字段提取（extract） */}
              <div className="rounded-lg border border-border/70 p-3">
                <div className="mb-2 flex items-center gap-2">
                  <Scissors className="h-4 w-4 text-primary" />
                  <span className="text-sm font-semibold text-foreground">字段提取（extract）</span>
                  <select className={`${inputBaseCls} ml-2 w-56 text-xs`} value={activeExtractType}
                    onChange={(e) => {
                      const t = e.target.value
                      if (t === 'fields') setActiveExtract({ type: 'fields', fields: extractFields.length ? extractFields : [emptyMappingRow()] })
                      else if (t === 'regex') setActiveExtract({ type: 'regex', regex: (activeRule.extract || {}).regex || '', source: (activeRule.extract || {}).source || '', mappings: (activeRule.extract || {}).mappings || [] })
                      else setActiveExtract({ type: 'template', sep: (activeRule.extract || {}).sep || '\\s+', columns: (activeRule.extract || {}).columns || [], source: (activeRule.extract || {}).source || '', mappings: (activeRule.extract || {}).mappings || [] })
                    }}>
                    {EXTRACT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                  </select>
                </div>

                {activeExtractType === 'regex' && (
                  <div className="space-y-3">
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                      <div>
                        <label className={labelCls}>提取源路径（可选，从原始日志取文本）</label>
                        <input className={inputCls} value={(activeRule.extract || {}).source || ''} placeholder="如：data.message（留空用解包后业务数据）"
                          onChange={(e) => setActiveExtract({ type: 'regex', regex: (activeRule.extract || {}).regex || '', source: e.target.value, mappings: (activeRule.extract || {}).mappings || [] })} />
                      </div>
                      <div>
                        <label className={labelCls}>正则表达式（命名组或编号组）</label>
                        <input className={`${inputCls} font-mono`} value={(activeRule.extract || {}).regex || ''} placeholder='如：user=(\w+)\s+ip=(\d+\.\d+\.\d+\.\d+)'
                          onChange={(e) => setActiveExtract({ type: 'regex', regex: e.target.value, source: (activeRule.extract || {}).source || '', mappings: (activeRule.extract || {}).mappings || [] })} />
                      </div>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full border-collapse text-sm">
                        <thead>
                          <tr className="border-b border-border text-left text-xs text-muted-foreground">
                            <th className="px-2 py-2 font-semibold">捕获组（编号或命名）</th>
                            <th className="px-2 py-2 font-semibold">目标字段</th>
                            <th className="px-2 py-2 font-semibold">转换类型</th>
                            <th className="px-2 py-2 font-semibold">默认值</th>
                            <th className="w-10 px-2 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {regexMappings.map((m, ri) => (
                            <tr key={ri} className="border-b border-border/60">
                              <td className="px-2 py-1.5">
                                <input className={`${inputBaseCls} w-40 font-mono`} value={m.group ?? ''} placeholder="如 1 或 username"
                                  onChange={(e) => updateRegexMapping(ri, { group: e.target.value })} />
                              </td>
                              <td className="px-2 py-1.5">
                                <input className={`${inputBaseCls} w-40`} value={m.target || ''} list="target-field-options" placeholder="目标字段"
                                  onChange={(e) => updateRegexMapping(ri, { target: e.target.value })} />
                              </td>
                              <td className="px-2 py-1.5">
                                <select className={`${inputBaseCls} w-48`} value={m.type || 'string'}
                                  onChange={(e) => updateRegexMapping(ri, { type: e.target.value })}>
                                  {CONVERT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                                </select>
                              </td>
                              <td className="px-2 py-1.5">
                                <input className={`${inputBaseCls} w-24`} value={m.default ?? ''} placeholder="默认值"
                                  onChange={(e) => updateRegexMapping(ri, { default: e.target.value })} />
                              </td>
                              <td className="px-2 py-1.5">
                                <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                                  title="删除该映射" onClick={() => removeRegexMapping(ri)}>
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Button size="sm" onClick={addRegexMapping}><Plus className="h-3.5 w-3.5" /> 添加捕获映射</Button>
                  </div>
                )}

                {activeExtractType === 'template' && (
                  <div className="space-y-3">
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                      <div>
                        <label className={labelCls}>提取源路径（可选）</label>
                        <input className={`${inputCls} font-mono`} value={(activeRule.extract || {}).source || ''} placeholder="如：data.message"
                          onChange={(e) => setActiveExtract({ type: 'template', sep: (activeRule.extract || {}).sep || '\\s+', columns: (activeRule.extract || {}).columns || [], source: e.target.value, mappings: (activeRule.extract || {}).mappings || [] })} />
                      </div>
                      <div>
                        <label className={labelCls}>分隔符（正则）</label>
                        <input className={`${inputCls} font-mono`} value={(activeRule.extract || {}).sep || '\\s+'} placeholder={'如 \\s+ 或 |'}
                          onChange={(e) => setActiveExtract({ type: 'template', sep: e.target.value, columns: (activeRule.extract || {}).columns || [], source: (activeRule.extract || {}).source || '', mappings: (activeRule.extract || {}).mappings || [] })} />
                      </div>
                      <div>
                        <label className={labelCls}>列名（逗号分隔，按顺序对应分割结果）</label>
                        <input className={inputCls} value={((activeRule.extract || {}).columns || []).join(', ')} placeholder="如：time, level, event_type"
                          onChange={(e) => setActiveExtract({ type: 'template', sep: (activeRule.extract || {}).sep || '\\s+', columns: e.target.value.split(',').map((s) => s.trim()).filter(Boolean), source: (activeRule.extract || {}).source || '', mappings: (activeRule.extract || {}).mappings || [] })} />
                      </div>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full border-collapse text-sm">
                        <thead>
                          <tr className="border-b border-border text-left text-xs text-muted-foreground">
                            <th className="px-2 py-2 font-semibold">列索引</th>
                            <th className="px-2 py-2 font-semibold">目标字段</th>
                            <th className="px-2 py-2 font-semibold">转换类型</th>
                            <th className="w-10 px-2 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {templateMappings.map((m, ri) => (
                            <tr key={ri} className="border-b border-border/60">
                              <td className="px-2 py-1.5">
                                <input className={`${inputBaseCls} w-24 font-mono`} type="number" value={m.index ?? ''} placeholder="列号"
                                  onChange={(e) => updateTemplateMapping(ri, { index: e.target.value === '' ? null : Number(e.target.value) })} />
                              </td>
                              <td className="px-2 py-1.5">
                                <input className={`${inputBaseCls} w-40`} value={m.target || ''} list="target-field-options" placeholder="目标字段"
                                  onChange={(e) => updateTemplateMapping(ri, { target: e.target.value })} />
                              </td>
                              <td className="px-2 py-1.5">
                                <select className={`${inputBaseCls} w-48`} value={m.type || 'string'}
                                  onChange={(e) => updateTemplateMapping(ri, { type: e.target.value })}>
                                  {CONVERT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                                </select>
                              </td>
                              <td className="px-2 py-1.5">
                                <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                                  title="删除该映射" onClick={() => removeTemplateMapping(ri)}>
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Button size="sm" onClick={addTemplateMapping}><Plus className="h-3.5 w-3.5" /> 添加列映射</Button>
                  </div>
                )}

                {activeExtractType === 'fields' && (
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-border text-left text-xs text-muted-foreground">
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
                        {extractFields.map((m, fi) => (
                          <tr key={fi} className="border-b border-border/60">
                            <td className="px-2 py-1.5">
                              <input className={`${inputBaseCls} w-36 font-mono`} value={m.source || ''} placeholder="源字段名"
                                onChange={(e) => updateExtractField(fi, { source: e.target.value })} />
                            </td>
                            <td className="px-2 py-1.5">
                              <input className={`${inputBaseCls} w-40`} value={m.target || ''} list="target-field-options" placeholder="目标字段"
                                onChange={(e) => updateExtractField(fi, { target: e.target.value })} />
                            </td>
                            <td className="px-2 py-1.5">
                              <select className={`${inputBaseCls} w-52`} value={m.type || 'string'}
                                onChange={(e) => updateExtractField(fi, { type: e.target.value })}>
                                {CONVERT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                              </select>
                            </td>
                            <td className="px-2 py-1.5 text-center">
                              <input type="checkbox" className="h-4 w-4 cursor-pointer accent-primary" checked={!!m.required}
                                onChange={(e) => updateExtractField(fi, { required: e.target.checked })} />
                            </td>
                            <td className="px-2 py-1.5">
                              <input className={`${inputBaseCls} w-24`} value={m.default ?? ''} placeholder="默认值"
                                onChange={(e) => updateExtractField(fi, { default: e.target.value })} />
                            </td>
                            <td className="px-2 py-1.5">
                              <select className={`${inputBaseCls} w-32`} value={m.enum_map || ''}
                                onChange={(e) => {
                                  const enumMap = e.target.value
                                  updateExtractField(fi, { enum_map: enumMap, enum_target: enumMap && !m.enum_target ? `${m.target || ''}_name` : m.enum_target || '' })
                                }}>
                                <option value="">（无）</option>
                                {ruleEnumNames.map((n) => <option key={n} value={n}>{n}</option>)}
                              </select>
                            </td>
                            <td className="px-2 py-1.5">
                              <input className={`${inputBaseCls} w-36`} value={m.enum_target || ''} placeholder="枚举翻译写入字段"
                                onChange={(e) => updateExtractField(fi, { enum_target: e.target.value })} />
                            </td>
                            <td className="px-2 py-1.5">
                              <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                                title="删除该行" onClick={() => removeExtractField(fi)}>
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="mt-3">
                      <Button size="sm" onClick={addExtractField}><Plus className="h-3.5 w-3.5" /> 添加字段映射</Button>
                    </div>
                  </div>
                )}
              </div>

              {/* 3. 映射补充（map）：枚举 / 默认值 / 校验 */}
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {/* 枚举映射 */}
                <div className="rounded-lg border border-border/70 p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <Braces className="h-4 w-4 text-primary" />
                    <span className="text-sm font-semibold text-foreground">枚举映射（map.enum_maps）</span>
                  </div>
                  {ruleEnumNames.length === 0 ? (
                    <EmptyState icon={Braces} title="暂无枚举映射" description="添加枚举组后可在字段提取中选择枚举，把 int 值翻译为中文" />
                  ) : (
                    <div className="space-y-3">
                      {ruleEnumNames.map((name) => {
                        const table = ruleEnumMaps[name] || {}
                        return (
                          <div key={name} className="rounded-md border border-border p-2">
                            <div className="mb-1.5 flex items-center gap-2">
                              <input className={`${inputBaseCls} w-40 font-mono`} value={name} placeholder="枚举名"
                                onChange={(e) => {
                                  const newName = e.target.value
                                  if (!newName || newName === name) return
                                  const maps = {}
                                  Object.entries(ruleEnumMaps).forEach(([k, v]) => { maps[k === name ? newName : k] = v })
                                  // 同步字段映射引用
                                  const fields = extractFields.map((m) => (m.enum_map === name ? { ...m, enum_map: newName } : m))
                                  const next = { enum_maps: maps }
                                  if (activeRule.extract?.type === 'fields') setActiveExtract({ type: 'fields', fields })
                                  setActiveMap(next)
                                }} />
                              <div className="ml-auto flex items-center gap-1">
                                <Button size="sm" onClick={() => addRuleEnumPair(name)}><Plus className="h-3 w-3" /> 添加</Button>
                                <button className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                                  title="删除枚举组" onClick={() => removeRuleEnumGroup(name)}>
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              </div>
                            </div>
                            {Object.entries(table).map(([k, v]) => (
                              <div key={k} className="flex items-center gap-1.5 py-0.5">
                                <input className={`${inputBaseCls} w-28`} value={k} placeholder="原值"
                                  onChange={(e) => updateRuleEnumPair(name, k, { key: e.target.value })} />
                                <span className="text-muted-foreground">→</span>
                                <input className={`${inputBaseCls} w-32`} value={v} placeholder="翻译值"
                                  onChange={(e) => updateRuleEnumPair(name, k, { value: e.target.value })} />
                                <button className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                                  onClick={() => removeRuleEnumPair(name, k)}>
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              </div>
                            ))}
                          </div>
                        )
                      })}
                    </div>
                  )}
                  <div className="mt-2">
                    <Button size="sm" onClick={addRuleEnumGroup}><Plus className="h-3.5 w-3.5" /> 添加枚举组</Button>
                  </div>
                </div>

                {/* 默认值补充 */}
                <div className="rounded-lg border border-border/70 p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <Settings2 className="h-4 w-4 text-primary" />
                    <span className="text-sm font-semibold text-foreground">默认值补充（map.defaults）</span>
                  </div>
                  {ruleDefaults.length === 0 ? (
                    <EmptyState icon={Settings2} title="暂无默认值" description="目标字段若在提取阶段未赋值，则补充固定值（如 source_type、async_source）" />
                  ) : (
                    <div className="space-y-2">
                      {ruleDefaults.map((d, di) => (
                        <div key={di} className="flex items-center gap-2">
                          <input className={`${inputBaseCls} w-40`} value={d.target || ''} list="target-field-options" placeholder="目标字段"
                            onChange={(e) => updateRuleDefault(di, { target: e.target.value })} />
                          <span className="text-muted-foreground">=</span>
                          <input className={`${inputBaseCls} flex-1`} value={d.value ?? ''} placeholder="固定值"
                            onChange={(e) => updateRuleDefault(di, { value: e.target.value })} />
                          <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                            onClick={() => removeRuleDefault(di)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="mt-2">
                    <Button size="sm" onClick={addRuleDefault}><Plus className="h-3.5 w-3.5" /> 添加默认值</Button>
                  </div>
                </div>
              </div>

              {/* 校验规则 */}
              <div className="rounded-lg border border-border/70 p-3">
                <div className="mb-2 flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-primary" />
                  <span className="text-sm font-semibold text-foreground">校验规则（map.validations）</span>
                </div>
                {ruleValidations.length === 0 ? (
                  <EmptyState icon={AlertTriangle} title="暂无校验规则" description="可对提取后的标准字段做正则 / 范围 / IP 合法性校验，失败记入 warnings" />
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
                        {ruleValidations.map((v, vi) => (
                          <tr key={vi} className="border-b border-border/60">
                            <td className="px-2 py-1.5">
                              <input className={`${inputBaseCls} w-44`} value={v.field || ''} list="target-field-options" placeholder="标准字段"
                                onChange={(e) => updateRuleValidation(vi, { field: e.target.value })} />
                            </td>
                            <td className="px-2 py-1.5">
                              <select className={`${inputBaseCls} w-44`} value={v.rule || 'regex'}
                                onChange={(e) => updateRuleValidation(vi, { rule: e.target.value })}>
                                {VALIDATION_RULE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                              </select>
                            </td>
                            <td className="px-2 py-1.5">
                              {v.rule === 'regex' && (
                                <input className={`${inputBaseCls} w-52 font-mono`} value={v.pattern || ''} placeholder="正则表达式"
                                  onChange={(e) => updateRuleValidation(vi, { pattern: e.target.value })} />
                              )}
                              {v.rule === 'range' && (
                                <div className="flex items-center gap-1.5">
                                  <input className={`${inputBaseCls} w-16`} type="number" value={v.min ?? ''} placeholder="最小"
                                    onChange={(e) => updateRuleValidation(vi, { min: e.target.value === '' ? null : Number(e.target.value) })} />
                                  <span className="text-muted-foreground">~</span>
                                  <input className={`${inputBaseCls} w-16`} type="number" value={v.max ?? ''} placeholder="最大"
                                    onChange={(e) => updateRuleValidation(vi, { max: e.target.value === '' ? null : Number(e.target.value) })} />
                                </div>
                              )}
                              {(v.rule === 'ip_list_valid' || v.rule === 'positive_int') && (
                                <span className="text-xs text-muted-foreground">（无需参数）</span>
                              )}
                            </td>
                            <td className="px-2 py-1.5">
                              <select className={`${inputBaseCls} w-28`} value={v.severity || 'warning'}
                                onChange={(e) => updateRuleValidation(vi, { severity: e.target.value })}>
                                <option value="warning">warning</option>
                                <option value="error">error</option>
                              </select>
                            </td>
                            <td className="px-2 py-1.5">
                              <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                                title="删除该规则" onClick={() => removeRuleValidation(vi)}>
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="mt-2">
                  <Button size="sm" onClick={addRuleValidation}><Plus className="h-3.5 w-3.5" /> 添加校验规则</Button>
                </div>
              </div>

              {/* 扩展字段 */}
              <div className="rounded-lg border border-border/70 p-3">
                <div className="mb-2 flex items-center gap-2">
                  <FileJson className="h-4 w-4 text-primary" />
                  <span className="text-sm font-semibold text-foreground">扩展字段归档（该规则）</span>
                </div>
                <textarea
                  className={`${inputCls} min-h-[72px] font-mono`}
                  value={ruleExtFields.join('\n')}
                  placeholder={'containerName\ncontainerId'}
                  onChange={(e) => setRuleExtFields(e.target.value.split('\n').map((s) => s.trim()).filter(Boolean))}
                />
              </div>
            </div>
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
          <SectionTitle icon={FlaskConical} desc="纯内存执行不写库；验证规则命中 → 解包 → 提取 → 枚举翻译 → 校验全链路">测试解析</SectionTitle>
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
                <EmptyState icon={FlaskConical} title="尚未执行测试" description="粘贴样例数据后点击「测试解析」查看规则命中与提取明细" className="h-full" />
              ) : (
                <div className="space-y-4">
                  {/* 规则匹配 */}
                  <div className="rounded-lg border border-border p-3">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-xs font-semibold text-muted-foreground">规则匹配</span>
                      {testResult.rule
                        ? <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" />命中该策略</Badge>
                        : <Badge variant="danger"><XCircle className="mr-1 h-3 w-3" />未命中任何规则</Badge>}
                      {testResult.rule && (
                        <span className="text-xs text-muted-foreground">
                          <code className="rounded bg-muted px-1.5 py-0.5">{testResult.rule.rule_id}</code>
                          {' · '}{testResult.rule.log_type || '未命名类型'}
                        </span>
                      )}
                    </div>
                    {(testResult.db_hits || []).length > 0 && (
                      <div className="space-y-1">
                        <div className="text-[11px] text-muted-foreground">已启用策略匹配过程：</div>
                        {testResult.db_hits.map((h) => (
                          <div key={h.id} className="flex items-center gap-2 text-xs">
                            <ChevronRight className="h-3 w-3 text-muted-foreground" />
                            <span className="max-w-[220px] truncate">{h.strategy_name}</span>
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

                  {/* 提取明细 */}
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
