// 数据备份与恢复 API：列表/创建/下载/恢复/删除
import request from './client'

export const backupApi = {
  // 获取备份列表
  list: (limit = 50, offset = 0) =>
    request(`/system/backup?limit=${limit}&offset=${offset}`),
  // 创建手动备份
  create: (backupType = 'manual') =>
    request('/system/backup', { method: 'POST', body: { backup_type: backupType } }),
  // 下载备份文件（返回下载 URL，注意：直接访问不带 token，仅用于展示）
  downloadUrl: (id) => `/api/v1/system/backup/${id}/download`,
  // 从备份恢复
  restore: (id) =>
    request(`/system/backup/${id}/restore`, { method: 'POST', body: { confirm: true } }),
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
    // 从 Content-Disposition 提取文件名，或用默认名
    const disposition = res.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    a.download = match ? match[1] : `backup_${id}.sql`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },
}

export default backupApi
