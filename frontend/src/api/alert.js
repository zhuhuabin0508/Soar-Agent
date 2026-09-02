// 告警列表 API：分页筛选 / 详情 / 统计 / CSV 导出
import { request } from './client'

function _qs(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && v.length === 0)) {
      search.set(k, Array.isArray(v) ? v.join(',') : String(v))
    }
  })
  const s = search.toString()
  return s ? `?${s}` : ''
}

export const alertApi = {
  // 分页列表：筛选排序分页全部后端执行
  // filters: { start_time, end_time, risk_levels[], attack_states[], deal_statuses[],
  //            stages[], directions[], keyword, parse_status, device_type, sort, order }
  list: (page, pageSize, filters = {}) => request(`/alerts${_qs({ page, page_size: pageSize, ...filters })}`),

  // 详情：JSON 字段已反序列化（extensions/raw_data/attck_technique 等为对象）
  detail: (id) => request(`/alerts/${id}`),

  // 顶部统计卡片
  stats: () => request('/alerts/stats'),

  // CSV 导出（按当前筛选，POST body；返回 Blob）
  async export(filters = {}) {
    const token = localStorage.getItem('soar_token')
    const res = await fetch('/api/v1/alerts/export', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/csv',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(filters),
    })
    if (!res.ok) {
      let msg = '导出失败'
      try {
        const d = await res.json()
        msg = d.detail || msg
      } catch { /* ignore */ }
      throw new Error(msg)
    }
    return res.blob()
  },
}
