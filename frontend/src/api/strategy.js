// 解析模板管理 API（告警解析引擎）
// 模板配置即引擎消费的 JSON 全文；测试解析纯内存执行不写库
import request from './client'

const _qs = (params = {}) => {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

export const strategyApi = {
  // 模板列表（含今日解析量/失败数/成功率/引用条目数统计）
  list: () => request('/ingest/strategies'),
  // 顶部统计卡片：启用模板数 / 接入设备类型数 / 今日总解析量 / 今日无匹配模板告警数
  stats: () => request('/ingest/strategies/stats'),
  // 标准模型可选目标字段清单（表单模式目标字段下拉）
  fields: () => request('/ingest/strategies/fields'),
  // 按设备类型推荐解析模板（存量 enabled 优先 + 内置补充），供接入向导第 3 步选择
  recommend: (deviceType = '') =>
    request(`/ingest/strategies/recommend${deviceType ? `?device_type=${encodeURIComponent(deviceType)}` : ''}`),
  // 创建 / 更新（创建即发布 v1；更新写草稿副本，线上版本继续生效）
  create: (config) => request('/ingest/strategies', { method: 'POST', body: config }),
  update: (id, config) => request(`/ingest/strategies/${id}`, { method: 'PUT', body: config }),
  // 模板详情：线上版本 config + 草稿 draft_config（存在时）+ 版本摘要
  detail: (id) => request(`/ingest/strategies/${id}`),
  // 发布草稿：draft_config 替换线上 config，生成版本快照 + 审计
  publish: (id, remark = '') =>
    request(`/ingest/strategies/${id}/publish`, { method: 'POST', body: { remark } }),
  // 丢弃草稿（恢复以线上版本为准）
  discardDraft: (id) => request(`/ingest/strategies/${id}/draft`, { method: 'DELETE' }),
  // 版本历史列表（含 is_current 标记）
  versions: (id) => request(`/ingest/strategies/${id}/versions`),
  // 单版本完整配置（diff 取数）
  versionDetail: (id, versionNo) => request(`/ingest/strategies/${id}/versions/${versionNo}`),
  // 回滚：以历史版本内容发布为新版本
  rollback: (id, versionNo, remark = '') =>
    request(`/ingest/strategies/${id}/rollback`, { method: 'POST', body: { version_no: versionNo, remark } }),
  // 测试解析（按模板 ID）：多条原始日志走完整管道（预处理→解析→校验），不落库
  testParse: (id, logs, useDraft = true, context = {}) =>
    request(`/ingest/strategies/${id}/test-parse`, { method: 'POST', body: { logs, use_draft: useDraft, context } }),
  // 失败样本下钻（原因四分类统计 + 按原因筛选 + 分页）
  failureSamples: (id, params) => request(`/ingest/strategies/${id}/failure-samples${_qs(params)}`),
  // 启停（enabled / disabled）
  toggleStatus: (id, status) =>
    request(`/ingest/strategies/${id}/status`, { method: 'PATCH', body: { status } }),
  // 删除（有关联告警记录时后端返回 409）
  remove: (id) => request(`/ingest/strategies/${id}`, { method: 'DELETE' }),
  // 导出模板为 JSON 文件下载（测试/生产环境迁移）
  exportUrl: (id) => `/api/v1/ingest/strategies/${id}/export`,
  // 从 JSON 导入模板：payload 为 { config } / { configs }，冲突项后端自动重命名
  import: (payload) => request('/ingest/strategies/import', { method: 'POST', body: payload }),
  // 测试解析：入参策略配置 + 样例数据，返回路由匹配过程/逐字段映射明细/校验警告/标准模型 JSON
  test: (config, sample) =>
    request('/ingest/strategies/test', { method: 'POST', body: { config, sample } }),
  // 解析错误队列（error_type 过滤，如 no_strategy_matched）
  errors: (params) => request(`/ingest/errors${_qs(params)}`),
}

export default strategyApi
