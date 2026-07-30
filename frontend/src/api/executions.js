import request from './request'

// 执行列表（支持按 workflow_id / status 过滤）
export function getExecutions(limit = 50, offset = 0, workflowId = null, status = null) {
  let path = `/executions?limit=${limit}&offset=${offset}`
  if (workflowId != null && workflowId !== '') path += `&workflow_id=${workflowId}`
  if (status) path += `&status=${status}`
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
