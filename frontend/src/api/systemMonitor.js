import request from './client'

// 系统监控 API
export const systemMonitorApi = {
  // 服务健康检查
  health: () => request('/system-monitor/health'),
  // 系统性能指标（CPU/内存/磁盘）
  performance: () => request('/system-monitor/performance'),
  // 审计日志列表（分页+过滤）
  auditLogs: (params = {}) => {
    const { limit = 50, offset = 0, action, resource_type, username } = params
    let path = `/system-monitor/audit-logs?limit=${limit}&offset=${offset}`
    if (action) path += `&action=${action}`
    if (resource_type) path += `&resource_type=${resource_type}`
    if (username) path += `&username=${encodeURIComponent(username)}`
    return request(path)
  },
  // 列出 SOAR 平台所有 Docker 容器及状态
  listServices: () => request('/system-monitor/services'),
  // 获取指定服务容器的最近日志
  getServiceLogs: (containerName, tail = 200) =>
    request(`/system-monitor/services/${encodeURIComponent(containerName)}/logs?tail=${tail}`),
}

export default systemMonitorApi
