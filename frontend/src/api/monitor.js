// 解析入库监控 API：概览 / 策略统计 / 趋势 / 分布 / 服务日志 / 健康 / 错误队列
import { request } from './client'

function _qs(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') search.set(k, String(v))
  })
  const s = search.toString()
  return s ? `?${s}` : ''
}

export const monitorApi = {
  // 概览卡片（6 张：今日接收/成功/失败/部分/成功率/平均耗时 + 昨日对比 + 24h 趋势）
  overview: () => request('/monitor/overview'),

  // 策略维度统计表（含"无匹配策略"汇总行）
  strategyStats: () => request('/monitor/strategy-stats'),

  // 入库量 / 成功率趋势（window: 24h | 7d；strategy_id 0=全部）
  trend: (window = '24h', strategyId = 0) =>
    request(`/monitor/trend${_qs({ window, strategy_id: strategyId || 0 })}`),

  // 今日风险等级分布（环形图）
  riskDistribution: () => request('/monitor/risk-distribution'),

  // 今日告警类型 TOP10（横向条形图）
  topThreats: (limit = 10) => request(`/monitor/top-threats${_qs({ limit })}`),

  // 服务日志（内存环形缓冲；after_id 增量拉取）
  logs: ({ level = '', keyword = '', afterId = 0, limit = 200 } = {}) =>
    request(`/monitor/logs${_qs({ level, keyword, after_id: afterId, limit })}`),

  // 服务健康：解析服务 / 数据库连接 / 待处理积压
  health: () => request('/monitor/health'),

  // 错误队列列表（含原始数据摘要 + 策略名；error_type / keyword 过滤）
  errors: ({ error_type = '', keyword = '', page = 1, page_size = 20 } = {}) =>
    request(`/monitor/errors${_qs({ error_type, keyword, page, page_size })}`),

  // 错误记录原始数据全文（查看 JSON）
  errorRaw: (id) => request(`/monitor/errors/${id}/raw`),

  // 错误队列重试（成功后移出队列；超 3 次转人工）
  retryError: (id) => request(`/monitor/errors/${id}/retry`, { method: 'POST' }),

  // 批量重试
  retryBatch: (ids) => request('/monitor/errors/retry-batch', { method: 'POST', body: { ids } }),

  // 删除错误记录
  removeError: (id) => request(`/monitor/errors/${id}`, { method: 'DELETE' }),

  // 错误队列列表（复用 ingest 端点）
  errors: (params = {}) => request(`/ingest/errors${_qs(params)}`),
}
