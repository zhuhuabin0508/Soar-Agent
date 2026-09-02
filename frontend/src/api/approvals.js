import request from './request'

/**
 * 查询审批工单列表（支持状态/工作流/关键词筛选）
 * @param {Object} params - { status, workflow_id, q, limit }
 *   - status: 'waiting_for_approval' | 'all' | 'success' | 'failed'（默认待处理）
 *   - workflow_id: 按工作流 ID 筛选
 *   - q: 关键词（匹配告警类型/IP/工作流名等）
 *   - limit: 返回条数上限
 */
export function getApprovals(params = {}) {
  const qs = new URLSearchParams()
  if (params.status) qs.append('status', params.status)
  if (params.workflow_id) qs.append('workflow_id', params.workflow_id)
  if (params.q) qs.append('q', params.q)
  if (params.limit) qs.append('limit', params.limit)
  const query = qs.toString()
  return request(query ? `/approvals?${query}` : '/approvals')
}

// 获取工作台统计看板数据
export function getApprovalStats() {
  return request('/approvals/stats')
}

// 同意封禁
export function approveExecution(executionId) {
  return request(`/approvals/${executionId}/approve`, { method: 'POST' })
}

// 拒绝（忽略）
export function rejectExecution(executionId) {
  return request(`/approvals/${executionId}/reject`, { method: 'POST' })
}

// 删除执行记录（仅 admin）
export function deleteExecution(executionId) {
  return request(`/approvals/${executionId}`, { method: 'DELETE' })
}

export default {
  getApprovals,
  getApprovalStats,
  approveExecution,
  rejectExecution,
  deleteExecution,
}
