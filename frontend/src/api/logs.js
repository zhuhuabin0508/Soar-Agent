// 日志中心 API：统一查询操作日志/执行记录/执行日志/模型调用日志 + 保留策略
import request from './request'

// 仅当值为有效正整数时返回数字，否则返回 null（不传该参数给后端，避免 422）
function asInt(v) {
  if (v === '' || v == null) return null
  const n = Number(v)
  return Number.isInteger(n) && n > 0 ? n : null
}

export const logsApi = {
  // 操作审计日志
  audit: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.limit != null) qs.set('limit', params.limit)
    if (params.offset != null) qs.set('offset', params.offset)
    if (params.action) qs.set('action', params.action)
    if (params.resource_type) qs.set('resource_type', params.resource_type)
    if (params.username) qs.set('username', params.username)
    if (params.result) qs.set('result', params.result)
    if (params.start_time) qs.set('start_time', params.start_time)
    if (params.end_time) qs.set('end_time', params.end_time)
    const s = qs.toString()
    return request(`/logs/audit${s ? '?' + s : ''}`)
  },
  // 执行记录
  executions: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.limit != null) qs.set('limit', params.limit)
    if (params.offset != null) qs.set('offset', params.offset)
    const wfId = asInt(params.workflow_id)
    if (wfId != null) qs.set('workflow_id', wfId)
    if (params.status) qs.set('status', params.status)
    if (params.trigger_type) qs.set('trigger_type', params.trigger_type)
    if (params.start_time) qs.set('start_time', params.start_time)
    if (params.end_time) qs.set('end_time', params.end_time)
    const s = qs.toString()
    return request(`/logs/executions${s ? '?' + s : ''}`)
  },
  // 执行日志（节点级）
  executionLogs: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.limit != null) qs.set('limit', params.limit)
    if (params.offset != null) qs.set('offset', params.offset)
    const execId = asInt(params.execution_id)
    if (execId != null) qs.set('execution_id', execId)
    if (params.node_id) qs.set('node_id', params.node_id)
    if (params.level) qs.set('level', params.level)
    if (params.keyword) qs.set('keyword', params.keyword)
    const s = qs.toString()
    return request(`/logs/execution-logs${s ? '?' + s : ''}`)
  },
  // 模型调用日志
  modelCalls: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.limit != null) qs.set('limit', params.limit)
    if (params.offset != null) qs.set('offset', params.offset)
    if (params.status) qs.set('status', params.status)
    if (params.model_name) qs.set('model_name', params.model_name)
    if (params.provider) qs.set('provider', params.provider)
    if (params.trigger_type) qs.set('trigger_type', params.trigger_type)
    if (params.agent_id != null) qs.set('agent_id', params.agent_id)
    if (params.start_time) qs.set('start_time', params.start_time)
    if (params.end_time) qs.set('end_time', params.end_time)
    const s = qs.toString()
    return request(`/logs/model-calls${s ? '?' + s : ''}`)
  },
  // 日志统计（含趋势/错误聚合/成功率）
  stats: () => request('/logs/stats'),
  // 保留策略配置（全局 + 分类）
  getRetention: () => request('/logs/retention'),
  updateRetention: (body) =>
    request('/logs/retention', { method: 'PUT', body }),
  // 手动清理过期日志（按分类保留天数）
  cleanup: () => request('/logs/cleanup', { method: 'POST' }),
  // 模型调用详情（单条完整信息）
  modelCallDetail: (logId) => request(`/logs/model-calls/${logId}`),
}

export default logsApi
