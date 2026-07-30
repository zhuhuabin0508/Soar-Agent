// 已封禁 IP 管理 API
import request from './client'

// 构造查询字符串（仅含非空参数）
function buildQuery(params = {}) {
  const qs = new URLSearchParams()
  if (params.search) qs.set('search', params.search)
  if (params.status) qs.set('status', params.status)
  const query = qs.toString()
  return query ? `?${query}` : ''
}

// 从 localStorage 读取 auth token（与 client.js 一致）
function authHeader() {
  const token = localStorage.getItem('soar_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export const bannedIpsApi = {
  list: (params = {}) => request(`/banned-ips${buildQuery(params)}`),
  stats: () => request('/banned-ips/stats'),
  get: (ip) => request(`/banned-ips/${encodeURIComponent(ip)}`),
  // 手动新增封禁 IP（仅管理员，source=manual）
  create: (data) => request('/banned-ips', { method: 'POST', body: data }),
  unban: (id) => request(`/banned-ips/${id}`, { method: 'DELETE' }),
  // 硬删除：从数据库物理删除记录（不可恢复），与解封（逻辑删除）区分
  hardDelete: (id) => request(`/banned-ips/${id}/hard`, { method: 'DELETE' }),
  // 导出 CSV：直接触发浏览器下载
  exportCsv: async () => {
    const resp = await fetch(`/api/v1/banned-ips/export/csv`, {
      headers: { ...authHeader() },
    })
    if (!resp.ok) throw new Error(`导出失败: HTTP ${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `banned_ips_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },
  // 导入 CSV：上传文件
  importCsv: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    const resp = await fetch(`/api/v1/banned-ips/import/csv`, {
      method: 'POST',
      headers: { ...authHeader() },
      body: formData,
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || `导入失败: HTTP ${resp.status}`)
    }
    return resp.json()
  },
}

export default bannedIpsApi
