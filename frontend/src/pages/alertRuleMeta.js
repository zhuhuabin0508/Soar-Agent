// 告警规则共享元数据与工具（列表页 / 编辑器 / 命中抽屉共用）
// 字段与枚举对齐后端标准告警模型（AlertEvent 列）

// ===== 条件操作符（与流水线 Filter 阶段 _match_op 一致）=====
export const OPS = [
  { value: 'eq', label: '等于' },
  { value: 'ne', label: '不等于' },
  { value: 'in', label: '属于集合' },
  { value: 'not_in', label: '不属于集合' },
  { value: 'gt', label: '大于' },
  { value: 'gte', label: '大于等于' },
  { value: 'lt', label: '小于' },
  { value: 'lte', label: '小于等于' },
  { value: 'contains', label: '包含' },
  { value: 'regex', label: '正则匹配' },
  { value: 'in_cidr', label: '属于网段' },
  { value: 'exists', label: '字段存在' },
  { value: 'empty', label: '字段为空' },
]
export const NO_VALUE_OPS = ['exists', 'empty']
export const SET_OPS = ['in', 'not_in']

// ===== 风险等级（必须用中文名选择，禁止直接填数字）=====
export const RISK_LEVELS = [
  { value: 0, label: '严重' }, { value: 1, label: '高危' }, { value: 2, label: '中危' },
  { value: 3, label: '低危' }, { value: 4, label: '信息' },
]
export const riskLevelName = (v) => (RISK_LEVELS.find((l) => l.value === Number(v)) || {}).label || '未知'

// ===== 规则动作 =====
export const ACTION_META = {
  alert: { label: '产生告警', variant: 'info' },
  suppress: { label: '抑制告警', variant: 'neutral' },
  adjust_level: { label: '调整等级', variant: 'warning' },
}

// ===== 规则类型（XDR 风格三 Tab：匹配 / 统计 / 关联[预留]）=====
export const RULE_TYPE_META = {
  match: { label: '匹配', desc: '单条日志命中条件即触发' },
  stats: { label: '统计', desc: '时间窗口内计数达阈值触发' },
  correlation: { label: '关联', desc: '多条件按时间先后关联触发（规划中）' },
}

// 类型列文案（对齐 XDR：匹配 / 统计(去重) / 统计(不去重)）
export const ruleTypeLabel = (rule) => {
  if (rule.type !== 'stats') return '匹配'
  const method = rule.stats_config?.method || 'count'
  return method === 'count_distinct' ? '统计(去重)' : '统计(不去重)'
}

// 统计配置摘要（列表「匹配条件」列 + 右栏摘要用）：如「按 源IP 5分钟 ≥10」
export const statsSummary = (rule) => {
  const cfg = rule.stats_config
  if (!cfg) return ''
  const unitName = { minute: '分钟', hour: '小时', day: '天' }[cfg.window?.unit] || cfg.window?.unit || '分钟'
  const groupPart = cfg.group_by?.length
    ? `按${cfg.group_by.map((f) => fieldLabel(f)).join('+')}分组 ` : ''
  const distinctPart = cfg.method === 'count_distinct' ? `去重(${fieldLabel(cfg.distinct_field)}) ` : ''
  return `${groupPart}${distinctPart}${cfg.window?.value ?? ''}${unitName} ≥${cfg.threshold ?? ''}`
}

// 告警聚合配置摘要：如「30分钟内 源IP+威胁类型 相同则聚合」
export const aggregationSummary = (agg) => {
  if (!agg || !agg.keys?.length) return ''
  const unitName = { minute: '分钟', hour: '小时', day: '天' }[agg.window?.unit] || agg.window?.unit || '分钟'
  return `${agg.window?.value ?? ''}${unitName}内 ${agg.keys.map((f) => fieldLabel(f)).join('+')} 相同则聚合`
}

// ===== 枚举字段（值选择器显示中文名）=====
export const ENUM_FIELDS = {
  risk_level: RISK_LEVELS,
  parse_status: [
    { value: 'success', label: '成功' }, { value: 'partial', label: '部分解析' }, { value: 'fail', label: '失败' },
  ],
  direction: [
    { value: 0, label: '无' }, { value: 1, label: '内到外' }, { value: 2, label: '外到内' }, { value: 3, label: '内对内' },
  ],
  attack_state: [
    { value: 0, label: '尝试' }, { value: 1, label: '失败' }, { value: 2, label: '成功' }, { value: 3, label: '失利' },
  ],
  deal_status: [
    { value: 0, label: '未处置' }, { value: 10, label: '生成事件' }, { value: 20, label: '已关闭' },
    { value: 30, label: '已加白' }, { value: 40, label: '已驳回' }, { value: 50, label: '已忽略' },
    { value: 60, label: '已遏制' }, { value: 70, label: '处置中' }, { value: 80, label: '误报' },
  ],
  stage: [
    { value: 0, label: '默认' }, { value: 10, label: '存在风险' }, { value: 20, label: '扫描探测' },
    { value: 30, label: '遭受攻击' }, { value: 40, label: '主机异常' }, { value: 50, label: '内网扩散' },
    { value: 60, label: 'C&C通信' }, { value: 70, label: '黑产牟利' }, { value: 80, label: '窃取数据' },
  ],
}

// ===== 字段类型（值输入联动：数字 / IP 支持 CIDR）=====
export const NUMERIC_FIELDS = [
  'risk_level', 'severity', 'confidence', 'src_port', 'dst_port',
  'direction', 'attack_state', 'stage', 'deal_status',
]
export const IP_FIELDS = ['src_ip', 'dst_ip', 'host_ip']

// ===== 字段下拉分组（常用 + 全部）=====
export const COMMON_FIELDS = ['risk_level', 'threat_type', 'device_type', 'src_ip', 'dst_ip', 'alert_name']
export const FIELD_GROUPS = [
  {
    label: '常用字段',
    fields: COMMON_FIELDS,
  },
  {
    label: '等级与状态',
    fields: ['risk_level', 'risk_level_name', 'severity', 'confidence', 'parse_status', 'deal_status', 'attack_state', 'attack_state_name', 'stage', 'stage_name', 'direction', 'direction_name'],
  },
  {
    label: '威胁与内容',
    fields: ['alert_name', 'threat_class', 'threat_type', 'threat_sub_type', 'log_type', 'rule_id', 'description'],
  },
  {
    label: '网络与主机',
    fields: ['src_ip', 'src_port', 'dst_ip', 'dst_port', 'protocol', 'host_ip', 'device_type', 'device_name', 'user_name'],
  },
  {
    label: '租户与来源',
    fields: ['tenant', 'customer'],
  },
]
export const ALL_FIELDS = FIELD_GROUPS.flatMap((g) => g.fields)
export const fieldLabel = (f) => {
  const labels = {
    risk_level: '风险等级', risk_level_name: '风险等级名', alert_name: '告警名称', threat_type: '威胁类型',
    threat_class: '威胁分类', threat_sub_type: '威胁子类', device_type: '设备类型', device_name: '设备名称',
    src_ip: '源 IP', src_port: '源端口', dst_ip: '目的 IP', dst_port: '目的端口', host_ip: '主机 IP',
    protocol: '协议', user_name: '用户名', parse_status: '解析状态', log_type: '日志类型', rule_id: '解析规则',
    severity: '原始严重度', confidence: '置信度', tenant: '租户', customer: '客户', description: '告警描述',
    direction: '方向', direction_name: '方向名', attack_state: '攻击状态', attack_state_name: '攻击状态名',
    deal_status: '处置状态', stage: '阶段', stage_name: '阶段名', threat_sub_type_alias: '威胁子类',
  }
  return labels[f] || f
}

// ===== 工具 =====
export const opLabel = (v) => (OPS.find((o) => o.value === v) || {}).label || v

// 数字比较值：形如数字的字符串转数字（与后端 coerce 语义一致）；in/not_in 拆分为数组；in_cidr 逗号拆分为 CIDR 数组
export const coerceValue = (op, raw) => {
  const v = typeof raw === 'string' ? raw.trim() : raw
  if (op === 'in' || op === 'not_in') {
    return (Array.isArray(v) ? v : String(v ?? '').split(/[,，]/))
      .map((s) => (typeof s === 'string' ? s.trim() : s)).filter((s) => s !== '' && s != null)
      .map((s) => (/^-?\d+(\.\d+)?$/.test(String(s)) ? Number(s) : s))
  }
  if (op === 'in_cidr') {
    return (Array.isArray(v) ? v : String(v ?? '').split(/[,，]/))
      .map((s) => (typeof s === 'string' ? s.trim() : s)).filter((s) => s !== '' && s != null)
  }
  if (typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v)) return Number(v)
  return v
}

// 条件值显示（枚举值显示中文名）
export const fmtCondValue = (field, op, value) => {
  if (NO_VALUE_OPS.includes(op)) return ''
  const enumList = ENUM_FIELDS[field]
  const fmtOne = (v) => {
    if (enumList) {
      const hit = enumList.find((o) => String(o.value) === String(v))
      if (hit) return hit.label
    }
    return String(v)
  }
  if (op === 'in' || op === 'not_in' || op === 'in_cidr') {
    const arr = Array.isArray(value) ? value : [value]
    return `[${arr.map(fmtOne).join(', ')}]`
  }
  return fmtOne(value)
}

// ===== 嵌套条件树（XDR 条件构建器：叶 {field,op,value} / 组 {type:'group',logic,items}）=====

// 单个节点摘要（组递归加括号）
const nodeSummary = (node) => {
  if (node?.type === 'group') {
    const joiner = node.logic === 'any' ? ' 或 ' : ' 且 '
    return `(${node.items.map(nodeSummary).join(joiner)})`
  }
  if (!node?.field) return ''
  return `${fieldLabel(node.field)} ${opLabel(node.op)}${NO_VALUE_OPS.includes(node.op) ? '' : ` ${fmtCondValue(node.field, node.op, node.value)}`}`
}

// 条件树叶子计数
export const treeLeafCount = (node) => {
  if (!node) return 0
  if (node.type === 'group') return (node.items || []).reduce((acc, it) => acc + treeLeafCount(it), 0)
  return node.field ? 1 : 0
}

// 条件摘要（双代兼容：扁平 list + match 列 / 嵌套 {logic,items} 树；tooltip 用完整串）
export const condSummary = (rule) => {
  const conds = rule?.conditions
  // 新版嵌套树
  if (conds && !Array.isArray(conds) && typeof conds === 'object' && Array.isArray(conds.items)) {
    const joiner = (conds.logic || rule.match) === 'any' ? ' 或 ' : ' 且 '
    return conds.items.map(nodeSummary).filter(Boolean).join(joiner)
  }
  // 旧版扁平
  const joiner = rule?.match === 'any' ? ' 或 ' : ' 且 '
  return (Array.isArray(conds) ? conds : [])
    .map((c) => `${fieldLabel(c.field)} ${opLabel(c.op)}${NO_VALUE_OPS.includes(c.op) ? '' : ` ${fmtCondValue(c.field, c.op, c.value)}`}`)
    .join(joiner)
}

// 嵌套树深度（组节点占一层；顶层容器 {logic,items} 不占层。
// 两层组合法（=2），第三层组（=3）应被拒绝——与后端 _validate_condition_tree 一致）
export const treeDepth = (node) => {
  if (!node || !Array.isArray(node.items)) return 0
  const child = Math.max(0, ...node.items.map(treeDepth))
  return node.type === 'group' ? child + 1 : child
}

// 相对时间（悬停显示绝对时间 YYYY-MM-DD HH:mm:ss）
export const absTime = (t) => {
  if (!t) return ''
  const d = new Date(String(t).includes('T') ? `${String(t).slice(0, 19)}Z` : t)
  if (Number.isNaN(d.getTime())) return String(t).slice(0, 19)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
export const relTime = (t) => {
  if (!t) return '--'
  const d = new Date(String(t).includes('T') ? `${String(t).slice(0, 19)}Z` : t)
  if (Number.isNaN(d.getTime())) return '--'
  const diff = Date.now() - d.getTime()
  if (diff < 0) return absTime(t)
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  const day = Math.floor(h / 24)
  if (day < 30) return `${day} 天前`
  return `${Math.floor(day / 30)} 个月前`
}

// 名称模板本地渲染（{field} 插值，缺失留空；与后端 render_name_template 一致，编辑器实时预览用）
export const renderTemplateLocal = (template, fields = {}) => {
  if (!template) return ''
  return String(template).replace(/\{([^{}]+)\}/g, (_, k) => {
    const v = fields[k]
    return v === undefined || v === null ? '' : String(v)
  })
}

export const fmtTime = (t) => (t ? String(t).replace('T', ' ').slice(0, 19) : '--')
