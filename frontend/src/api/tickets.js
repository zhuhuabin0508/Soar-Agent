// 工单 API 客户端
//
// 覆盖：工单处理分组管理、流程模板管理（含发布）、工单发起/列表/详情/流转/取消、附件上传。
// 后端路由前缀：/api/v1/ticket-config/*（配置）与 /api/v1/tickets（工单中心）。
import request from './client'

const _qs = (params = {}) => {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

export const ticketApi = {
  // ===== 处理分组 =====
  listGroups: () => request('/ticket-config/groups'),
  createGroup: (body) => request('/ticket-config/groups', { method: 'POST', body }),
  updateGroup: (id, body) => request(`/ticket-config/groups/${id}`, { method: 'PUT', body }),
  deleteGroup: (id) => request(`/ticket-config/groups/${id}`, { method: 'DELETE' }),
  updateGroupMembers: (id, userIds) =>
    request(`/ticket-config/groups/${id}/members`, { method: 'PUT', body: { user_ids: userIds } }),

  // ===== 流程模板 =====
  listFlows: () => request('/ticket-config/flows'),
  getFlow: (id) => request(`/ticket-config/flows/${id}`),
  createFlow: (body) => request('/ticket-config/flows', { method: 'POST', body }),
  updateFlow: (id, body) => request(`/ticket-config/flows/${id}`, { method: 'PUT', body }),
  publishFlow: (id) => request(`/ticket-config/flows/${id}/publish`, { method: 'POST' }),
  deleteFlow: (id) => request(`/ticket-config/flows/${id}`, { method: 'DELETE' }),

  // ===== SLA 目标配置 =====
  getSlaConfig: () => request('/ticket-config/sla'),
  updateSlaConfig: (config) => request('/ticket-config/sla', { method: 'PUT', body: { config } }),

  // ===== 工单中心 =====
  flowOptions: () => request('/tickets/flows/options'),
  createTicket: (body) => request('/tickets', { method: 'POST', body }),
  listTickets: (params) => request(`/tickets${_qs(params)}`),
  getTicket: (id) => request(`/tickets/${id}`),
  // 监控大屏聚合（KPI/趋势/分布/SLA/分组/流转节点/最新工单，一次返回）
  getMonitorStats: () => request('/tickets/monitor'),
  advanceTicket: (id, body) => request(`/tickets/${id}/advance`, { method: 'POST', body }),
  cancelTicket: (id, body) => request(`/tickets/${id}/cancel`, { method: 'POST', body }),
  archiveTicket: (id) => request(`/tickets/${id}/archive`, { method: 'POST' }),
  unarchiveTicket: (id) => request(`/tickets/${id}/unarchive`, { method: 'POST' }),

  // ===== 附件 =====
  uploadAttachment: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/tickets/attachments', { method: 'POST', body: fd })
  },
}

// 附件直链（<img>/<a> 无法带 Authorization 头，追加 query token）
export function attachmentUrl(url) {
  if (!url) return ''
  const token = localStorage.getItem('soar_token')
  if (!token) return url
  return url.includes('?') ? `${url}&token=${token}` : `${url}?token=${token}`
}

export default ticketApi
