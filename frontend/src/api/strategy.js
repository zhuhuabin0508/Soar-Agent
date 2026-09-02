// 解析策略管理 API（告警解析引擎）
// 策略配置即引擎消费的 JSON 全文；测试解析纯内存执行不写库
import request from './client'

const _qs = (params = {}) => {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

export const strategyApi = {
  // 策略列表（含今日解析量/失败数/成功率统计）
  list: () => request('/ingest/strategies'),
  // 顶部统计卡片：启用策略数 / 接入设备类型数 / 今日总解析量 / 今日无匹配策略告警数
  stats: () => request('/ingest/strategies/stats'),
  // 标准模型可选目标字段清单（表单模式目标字段下拉）
  fields: () => request('/ingest/strategies/fields'),
  // 创建 / 更新（body 为策略配置 JSON 全文，后端做结构校验）
  create: (config) => request('/ingest/strategies', { method: 'POST', body: config }),
  update: (id, config) => request(`/ingest/strategies/${id}`, { method: 'PUT', body: config }),
  // 启停（enabled / disabled）
  toggleStatus: (id, status) =>
    request(`/ingest/strategies/${id}/status`, { method: 'PATCH', body: { status } }),
  // 删除（有关联告警记录时后端返回 409）
  remove: (id) => request(`/ingest/strategies/${id}`, { method: 'DELETE' }),
  // 测试解析：入参策略配置 + 样例数据，返回路由匹配过程/逐字段映射明细/校验警告/标准模型 JSON
  test: (config, sample) =>
    request('/ingest/strategies/test', { method: 'POST', body: { config, sample } }),
  // 解析错误队列（error_type 过滤，如 no_strategy_matched）
  errors: (params) => request(`/ingest/errors${_qs(params)}`),
}

export default strategyApi
