import request from './client'

// 系统监控 API
export const systemMonitorApi = {
  // 服务健康检查
  health: () => request('/system-monitor/health'),
  // 系统性能指标（CPU/内存/磁盘）
  performance: () => request('/system-monitor/performance'),
  // 审计日志列表（分页+多维过滤）
  auditLogs: (params = {}) => {
    const {
      limit = 50, offset = 0,
      action, resource_type, username,
      ip_address, result, start_time, end_time,
    } = params
    const sp = new URLSearchParams({ limit, offset })
    if (action) sp.set('action', action)
    if (resource_type) sp.set('resource_type', resource_type)
    if (username) sp.set('username', username)
    if (ip_address) sp.set('ip_address', ip_address)
    if (result) sp.set('result', result)
    if (start_time) sp.set('start_time', start_time)
    if (end_time) sp.set('end_time', end_time)
    return request(`/system-monitor/audit-logs?${sp.toString()}`)
  },
  // 导出审计日志为 CSV（返回 API 路径，前端用 fetch 带 Authorization 头下载）
  auditLogsExportUrl: (params = {}) => {
    const { action, resource_type, username, ip_address, result, start_time, end_time } = params
    const sp = new URLSearchParams()
    if (action) sp.set('action', action)
    if (resource_type) sp.set('resource_type', resource_type)
    if (username) sp.set('username', username)
    if (ip_address) sp.set('ip_address', ip_address)
    if (result) sp.set('result', result)
    if (start_time) sp.set('start_time', start_time)
    if (end_time) sp.set('end_time', end_time)
    return `/api/v1/system-monitor/audit-logs/export?${sp.toString()}`
  },
  // 列出 SOAR 平台所有 Docker 容器及状态
  listServices: () => request('/system-monitor/services'),
  // 获取指定服务容器的最近日志
  getServiceLogs: (containerName, tail = 200) =>
    request(`/system-monitor/services/${encodeURIComponent(containerName)}/logs?tail=${tail}`),
}

export default systemMonitorApi
