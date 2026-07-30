// 系统配置 API：平台名称/Logo/主题色/CORS白名单/限流配置 + 等保安全策略
import request from './client'

export const systemConfigApi = {
  // 获取全部系统配置（键值对列表）
  list: () => request('/system-config'),
  // 批量更新系统配置
  update: (body) => request('/system-config', { method: 'PUT', body: { configs: body } }),
  // 获取等保安全策略
  getSecurity: () => request('/system-config/security'),
  // 更新等保安全策略
  updateSecurity: (body) => request('/system-config/security', { method: 'PUT', body }),
}

export default systemConfigApi
