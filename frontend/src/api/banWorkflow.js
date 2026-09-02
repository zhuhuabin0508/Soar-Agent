// 告警自动封禁工作流 API：实例管理 / 审批中心 / 封禁工作台 / 触发规则 / 熔断 / 统计
import request from './request'

function qs(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== '' && v != null && v !== 0 && !(Array.isArray(v) && v.length === 0)) search.set(k, v)
  })
  const s = search.toString()
  return s ? `?${s}` : ''
}

export const banWorkflowApi = {
  // ===== 实例管理 =====
  instances: (params = {}) => request(`/ban-workflow/instances${qs(params)}`),
  instance: (id) => request(`/ban-workflow/instances/${id}`),
  cancelInstance: (id, reason) => request(`/ban-workflow/instances/${id}/cancel`, {
    method: 'POST', body: { reason },
  }),

  // ===== 审批中心 =====
  approvals: (params = {}) => request(`/ban-workflow/approvals${qs(params)}`),
  approval: (id) => request(`/ban-workflow/approvals/${id}`),
  approveTicket: (id, comment) => request(`/ban-workflow/approvals/${id}/approve`, {
    method: 'POST', body: { comment },
  }),
  rejectTicket: (id, reason) => request(`/ban-workflow/approvals/${id}/reject`, {
    method: 'POST', body: { reason },
  }),
  escalateTicket: (id, comment) => request(`/ban-workflow/approvals/${id}/escalate`, {
    method: 'POST', body: { comment },
  }),

  // ===== 封禁工作台 =====
  bannedIps: (params = {}) => request(`/ban-workflow/banned-ips${qs(params)}`),
  bannedIp: (id) => request(`/ban-workflow/banned-ips/${id}`),
  unbanIp: (id, reason) => request(`/ban-workflow/banned-ips/${id}/unban`, {
    method: 'POST', body: { reason },
  }),
  // 手动发起封禁（来源标记 manual）
  createManualBan: (data) => request('/ban-workflow/banned-ips', { method: 'POST', body: data }),
  // 删除封禁记录（仅 admin）
  deleteBannedIp: (id) => request(`/ban-workflow/banned-ips/${id}`, { method: 'DELETE' }),
  // 删除审批工单（仅 admin）
  deleteApproval: (id) => request(`/ban-workflow/approvals/${id}`, { method: 'DELETE' }),

  // ===== 触发规则 =====
  rules: () => request('/ban-workflow/rules'),
  createRule: (data) => request('/ban-workflow/rules', { method: 'POST', body: data }),
  updateRule: (id, data) => request(`/ban-workflow/rules/${id}`, { method: 'PUT', body: data }),
  deleteRule: (id) => request(`/ban-workflow/rules/${id}`, { method: 'DELETE' }),

  // ===== 熔断与统计 =====
  circuitBreaker: () => request('/ban-workflow/circuit-breaker'),
  resetCircuitBreaker: () => request('/ban-workflow/circuit-breaker/reset', { method: 'POST' }),
  stats: () => request('/ban-workflow/stats'),
}

export default banWorkflowApi
