import request from './request'

// 执行列表（支持按 workflow_id / status / trigger_type / agent_id / since / until 过滤）
// filters.since / filters.until 支持 ISO 日期字符串（如 2026-08-01 或 2026-08-01T00:00:00）
export function getExecutions(limit = 50, offset = 0, workflowId = null, status = null, filters = {}) {
  let path = `/executions?limit=${limit}&offset=${offset}`
  if (workflowId != null && workflowId !== '') path += `&workflow_id=${workflowId}`
  if (status) path += `&status=${status}`
  if (filters.trigger_type) path += `&trigger_type=${filters.trigger_type}`
  if (filters.agent_id != null && filters.agent_id !== '') path += `&agent_id=${filters.agent_id}`
  if (filters.since) path += `&since=${encodeURIComponent(filters.since)}`
  if (filters.until) path += `&until=${encodeURIComponent(filters.until)}`
  return request(path)
}

// 执行详情含轨迹
export function getExecutionDetail(id) {
  return request(`/executions/${id}`)
}

// 监测统计概览：成功率/平均耗时/按天趋势/触发类型分布/节点瓶颈
// workflowId 可选，传入则只统计指定工作流的数据
export function getStatsOverview(days = 7, workflowId = null) {
  let path = `/executions/stats/overview?days=${days}`
  if (workflowId != null && workflowId !== '') path += `&workflow_id=${workflowId}`
  return request(path)
}

export default { getExecutions, getExecutionDetail, getStatsOverview }
