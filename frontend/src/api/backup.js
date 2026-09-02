// 数据备份与恢复 API：列表/创建/下载/恢复/删除/策略/统计/详情/校验/清理/上传
import request from './client'

export const backupApi = {
  // 获取备份列表
  list: (limit = 50, offset = 0) =>
    request(`/system/backup?limit=${limit}&offset=${offset}`),
  // 创建备份（支持自定义名称/范围/备注/加密）
  create: (body) =>
    request('/system/backup', { method: 'POST', body }),
  // 查询备份进度状态（轮询用）
  status: (id) => request(`/system/backup/${id}/status`),
  // 下载备份文件 URL
  downloadUrl: (id) => `/api/v1/system/backup/${id}/download`,
  // 从备份恢复（支持完全/部分恢复模式）
  restore: (id, body = { confirm: true }) =>
    request(`/system/backup/${id}/restore`, { method: 'POST', body }),
  // 删除备份
  remove: (id) => request(`/system/backup/${id}`, { method: 'DELETE' }),
  // 下载备份文件（携带 token）
  download: async (id) => {
    const token = localStorage.getItem('soar_token')
    const res = await fetch(`/api/v1/system/backup/${id}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error('下载失败')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const disposition = res.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    a.download = match ? match[1] : `backup_${id}.sql`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },
  // 获取备份策略配置
  getStrategy: () => request('/system/backup/strategy'),
  // 更新备份策略配置
  setStrategy: (body) => request('/system/backup/strategy', { method: 'PUT', body }),
  // 备份概览统计（上次/下次/存储占用/健康度）
  stats: () => request('/system/backup/stats'),
  // 备份详情（范围/文件清单/校验信息/操作日志）
  detail: (id) => request(`/system/backup/${id}/detail`),
  // 校验备份文件完整性
  verify: (id) => request(`/system/backup/${id}/verify`, { method: 'POST' }),
  // 清理过期备份
  cleanupExpired: () => request('/system/backup/cleanup-expired', { method: 'POST' }),
  // 上传本地备份文件
  upload: async (file) => {
    const token = localStorage.getItem('soar_token')
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/v1/system/backup/upload', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    })
    if (!res.ok) {
      const d = await res.json().catch(() => ({}))
      throw new Error(d.detail || '上传失败')
    }
    return res.json()
  },
}

export default backupApi
