// 值班管理 API 客户端
//
// 覆盖：值班人员 CRUD + Excel 导入/模板、值班表生成/确认/查看/导出/手动调班、
//       请假申请/审批、调班记录、特殊日期覆盖。
// 后端路由前缀 /api/v1/duty。
import request from './client'

const _qs = (params = {}) => {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

// 带 Authorization 头下载文件（GET 端点要求登录，<a> 直链不可用）
async function _download(url, fallbackName) {
  const token = localStorage.getItem('soar_token')
  const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!res.ok) {
    let detail = '下载失败'
    try { const d = await res.json(); detail = d.detail || detail } catch { /* ignore */ }
    throw new Error(detail)
  }
  const blob = await res.blob()
  const objUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objUrl
  // 从响应头取文件名，兜底用传入名
  const cd = res.headers.get('Content-Disposition') || ''
  const m = cd.match(/filename\*=UTF-8''([^;]+)/)
  a.download = m ? decodeURIComponent(m[1]) : fallbackName
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(objUrl)
}

export const dutyApi = {
  // ===== 值班人员 =====
  members: (params) => request(`/duty/members${_qs(params)}`),
  allMembers: (category = '') => request(`/duty/members/all${_qs({ category })}`),
  createMember: (body) => request('/duty/members', { method: 'POST', body }),
  updateMember: (id, body) => request(`/duty/members/${id}`, { method: 'PUT', body }),
  deleteMember: (id) => request(`/duty/members/${id}`, { method: 'DELETE' }),
  memberStats: (params) => request(`/duty/members/stats${_qs(params)}`),
  batchUpdateStatus: (body) => request('/duty/members/batch-update-status', { method: 'POST', body }),
  reorderMembers: (orderedIds) => request('/duty/members/reorder', { method: 'POST', body: { ordered_ids: orderedIds } }),
  // 模板下载（带 auth）/ Excel 导入（FormData）
  downloadMemberTemplate: () => _download('/api/v1/duty/members/import-template', '值班人员导入模板.xlsx'),
  importMembers: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/duty/members/import', { method: 'POST', body: fd })
  },

  // ===== 值班表生成 / 查看 / 调整 =====
  generate: (body) => request('/duty/schedule/generate', { method: 'POST', body }),
  confirm: (startDate, endDate) =>
    request(`/duty/schedule/confirm?start_date=${startDate}&end_date=${endDate}`, { method: 'POST' }),
  scheduleStats: (params) => request(`/duty/schedule/stats${_qs(params)}`),
  copySchedule: (body) => request('/duty/schedule/copy', { method: 'POST', body }),
  listSchedule: (params) => request(`/duty/schedule${_qs(params)}`),
  monthSchedule: (year, month) => request(`/duty/schedule/month?year=${year}&month=${month}`),
  adjust: (recordId, body) => request(`/duty/schedule/${recordId}`, { method: 'PUT', body }),
  updateRecordStatus: (recordId, status) =>
    request(`/duty/schedule/${recordId}/status`, { method: 'PUT', body: { status } }),
  exportSchedule: (startDate, endDate) =>
    _download(`/api/v1/duty/schedule/export?start_date=${startDate}&end_date=${endDate}`, `值班表_${startDate}_${endDate}.xlsx`),

  // ===== 请假管理 =====
  leaves: (params) => request(`/duty/leaves${_qs(params)}`),
  createLeave: (body) => request('/duty/leaves', { method: 'POST', body }),
  approveLeave: (id, body) => request(`/duty/leaves/${id}/approve`, { method: 'PUT', body }),
  deleteLeave: (id) => request(`/duty/leaves/${id}`, { method: 'DELETE' }),
  batchDeleteLeaves: (ids) => request('/duty/leaves/batch-delete', { method: 'POST', body: { ids } }),

  // ===== 调班记录 =====
  adjustmentLogs: (params) => request(`/duty/adjustment-logs${_qs(params)}`),
  revertAdjust: (logId) => request(`/duty/adjustment-logs/${logId}/revert`, { method: 'POST' }),
  deleteAdjustLog: (id) => request(`/duty/adjustment-logs/${id}`, { method: 'DELETE' }),
  batchDeleteAdjustLogs: (ids) => request('/duty/adjustment-logs/batch-delete', { method: 'POST', body: { ids } }),

  // ===== 值班记录删除 =====
  deleteRecord: (recordId) => request(`/duty/schedule/${recordId}`, { method: 'DELETE' }),

  // ===== 特殊日期覆盖 =====
  specialDates: () => request('/duty/special-dates'),
  setSpecialDates: (items) => request('/duty/special-dates', { method: 'PUT', body: { items } }),
  deleteSpecialDate: (d) => request(`/duty/special-dates/${d}`, { method: 'DELETE' }),

  // ===== 值班监控大屏 =====
  dashboard: () => request('/duty/dashboard'),
}

export default dutyApi
