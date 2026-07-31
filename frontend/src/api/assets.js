// 资产管理 API
import request from './client'

// 构造查询字符串（仅含非空参数）
function buildQuery(params = {}) {
  const qs = new URLSearchParams()
  if (params.agent_id != null) qs.set('agent_id', params.agent_id)
  if (params.kb_id != null) qs.set('kb_id', params.kb_id)
  if (params.asset_type) qs.set('asset_type', params.asset_type)
  if (params.department) qs.set('department', params.department)
  if (params.criticality) qs.set('criticality', params.criticality)
  if (params.source) qs.set('source', params.source)
  if (params.keyword) qs.set('keyword', params.keyword)
  if (params.page) qs.set('page', params.page)
  if (params.page_size) qs.set('page_size', params.page_size)
  const query = qs.toString()
  return query ? `?${query}` : ''
}

// 从 localStorage 读取 auth token（与 client.js 一致）
function authHeader() {
  const token = localStorage.getItem('soar_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export const assetsApi = {
  // 资产列表（分页 + 筛选 + 关键词搜索）
  list: (params = {}) => request(`/assets${buildQuery(params)}`),
  // 统计信息
  stats: (agent_id) =>
    request(`/assets/stats${agent_id != null ? `?agent_id=${agent_id}` : ''}`),
  // 单条详情
  get: (id) => request(`/assets/${id}`),
  // 手动新增（source=manual）
  create: (data) => request('/assets', { method: 'POST', body: data }),
  // 更新
  update: (id, data) => request(`/assets/${id}`, { method: 'PUT', body: data }),
  // 删除单条
  remove: (id) => request(`/assets/${id}`, { method: 'DELETE' }),
  // 批量删除
  batchRemove: (ids) =>
    request(`/assets?${ids.map((i) => `ids=${i}`).join('&')}`, {
      method: 'DELETE',
    }),
  // 手动触发资产扫描任务
  scan: () => request('/assets/scan', { method: 'POST' }),
  // 导出 CSV：直接触发浏览器下载
  exportCsv: async (agent_id) => {
    const url = `/api/v1/assets/export${agent_id != null ? `?agent_id=${agent_id}` : ''}`
    const resp = await fetch(url, { headers: { ...authHeader() } })
    if (!resp.ok) throw new Error(`导出失败: HTTP ${resp.status}`)
    const blob = await resp.blob()
    const blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = `assets_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(blobUrl)
  },
}

export default assetsApi
