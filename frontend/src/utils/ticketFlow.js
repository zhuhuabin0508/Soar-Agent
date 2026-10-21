// 工单流程前端工具：字段渲染类型、条件路由建议、字段值格式化展示

export const FIELD_TYPE_LABELS = {
  text: '单行文本',
  textarea: '多行文本',
  number: '数字',
  datetime: '日期时间',
  select: '下拉选择',
  switch: '是否开关',
  ip: 'IP 地址',
  url: 'URL',
  file: '附件/截图',
}

// 字段定义（key → label）映射，用于详情只读展示
export function fieldDefMap(fields) {
  const m = {}
  ;(fields || []).forEach((f) => { m[f.key] = f })
  return m
}

// 条件路由评估（与后端 suggest_route 保持一致：布尔值归一化为 是/否）
function _norm(v) {
  if (typeof v === 'boolean') return v ? '是' : '否'
  return v
}

// 返回 { options: [{to, label, when}], suggested: 命中条件的建议去向 key }
export function evalRoutes(routes, fieldValues) {
  const options = (routes || []).filter((r) => r && r.to).map((r) => ({ ...r }))
  let suggested = null
  for (const r of options) {
    const when = r.when
    if (!when || !when.field) continue
    const actual = _norm(fieldValues?.[when.field])
    const expected = _norm(when.value)
    if (actual === undefined || actual === null || actual === '') continue
    const op = when.op || 'eq'
    const matched = op === 'ne' ? String(actual) !== String(expected) : String(actual) === String(expected)
    if (matched) { suggested = r.to; break }
  }
  return { options, suggested }
}

// 字段值展示格式化：布尔 → 是/否；空 → '--'；附件 → 文件名
export function fieldValueText(field, value) {
  if (value === null || value === undefined || value === '') return '--'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}
