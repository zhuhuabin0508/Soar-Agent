import request from './request'

// 大屏统计
export function getDashboardStats() {
  return request('/dashboard/stats')
}

export default { getDashboardStats }
