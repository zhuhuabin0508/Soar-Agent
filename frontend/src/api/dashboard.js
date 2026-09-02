import request from './request'

// 大屏统计
export function getDashboardStats() {
  return request('/dashboard/stats')
}

// AI 使用情况统计（智能体 + 大模型），days 默认 7 天
export function getAiUsageStats(days = 7) {
  return request(`/dashboard/ai-usage?days=${days}`)
}

export default { getDashboardStats, getAiUsageStats }
