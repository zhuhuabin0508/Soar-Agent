// 统一 API 客户端：基于 fetch，base 前缀 /api/v1（相对路径，由 nginx 代理）
// 所有页面统一引用本模块，集中处理 JSON 与错误抛出
//
// 资源 API：
//   llmConfigs        GET/POST/PUT/DELETE 模型配置
//   tools             GET/POST/PUT/DELETE 工具，POST /{id}/test，GET /templates
//   agents            GET/POST/PUT/DELETE 智能体，POST /{id}/test
//   knowledgeBases    GET/POST/DELETE 知识库 + documents + search
//   workflows         GET/POST/PUT/DELETE 工作流，POST /{id}/test-run，POST /test-node
//   executions        GET 列表/详情

const BASE_URL = '/api/v1'

/**
 * 发起 JSON 请求
 * @param {string} path 相对路径，例如 /llm-configs
 * @param {object} options fetch 配置（method/headers/body 等）
 * @returns {Promise<any>} 解析后的 JSON；空响应体返回 null
 */
export async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`
  const isFormData =
    typeof FormData !== 'undefined' && options.body instanceof FormData
  const token = localStorage.getItem('soar_token')
  const headers = {
    Accept: 'application/json',
    // JWT 鉴权：登录后所有请求携带 Bearer token
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    // FormData 由浏览器自动设置 Content-Type（含 boundary），不能手动覆盖
    ...(options.body && !isFormData
      ? { 'Content-Type': 'application/json' }
      : {}),
    ...(options.headers || {}),
  }
  // 自动序列化 body；FormData 直接透传
  const init = {
    ...options,
    headers,
    body:
      isFormData
        ? options.body
        : options.body !== undefined && options.body !== null && typeof options.body !== 'string'
        ? JSON.stringify(options.body)
        : options.body,
  }

  let res
  try {
    res = await fetch(url, init)
  } catch (err) {
    throw new Error(`网络错误：${err.message || err}`)
  }

  if (!res.ok) {
    // 401 未认证/token 过期：统一清除凭证 + 提示 + 跳转登录页
    // 使用全局标志避免并发请求触发多次跳转
    if (res.status === 401 && !window.location.pathname.startsWith('/login')) {
      if (!window.__SOAR_AUTH_EXPIRED__) {
        window.__SOAR_AUTH_EXPIRED__ = true
        localStorage.removeItem('soar_token')
        localStorage.removeItem('soar_user')
        // 延迟提示+跳转，让当前错误链先完成
        setTimeout(() => {
          window.alert('登录已过期或认证失效，请重新登录')
          window.location.href = '/login'
        }, 100)
      }
      throw new Error('登录已过期，请重新登录')
    }
    let detail = ''
    try {
      const data = await res.json()
      detail = data.detail || data.message || JSON.stringify(data)
    } catch {
      try {
        detail = await res.text()
      } catch {
        detail = ''
      }
    }
    throw new Error(`请求失败 ${res.status} ${res.statusText} ${detail}`.trim())
  }

  // 允许空响应体
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export default request

// ============ LLM 配置 ============
export const llmConfigs = {
  list: () => request('/llm-configs'),
  create: (body) => request('/llm-configs', { method: 'POST', body }),
  update: (id, body) => request(`/llm-configs/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/llm-configs/${id}`, { method: 'DELETE' }),
  test: (id) => request(`/llm-configs/${id}/test`, { method: 'POST' }),
  // 模型监控：聚合统计（按模型配置汇总调用次数/成功率/耗时/Token）
  monitorStats: (days = 7) => request(`/llm-configs/monitor/stats?days=${days}`),
  // 模型监控：单个配置的最近调用明细
  monitorCalls: (id, limit = 50, offset = 0) =>
    request(`/llm-configs/${id}/monitor/calls?limit=${limit}&offset=${offset}`),
}

// ============ 工具 ============
export const tools = {
  list: () => request('/tools'),
  create: (body) => request('/tools', { method: 'POST', body }),
  update: (id, body) => request(`/tools/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/tools/${id}`, { method: 'DELETE' }),
  test: (id, parameters) =>
    request(`/tools/${id}/test`, { method: 'POST', body: { parameters } }),
  templates: () => request('/tools/templates'),
  // 推断工具的输入输出 schema
  inferredSchema: (id) => request(`/tools/${id}/inferred-schema`),
  // 解析 OpenAPI/Swagger JSON 或 URL，返回操作列表
  importOpenapi: (body) =>
    request('/tools/import-openapi', { method: 'POST', body }),
  // 根据选定的 OpenAPI 操作构造工具配置
  buildFromOperation: (body) =>
    request('/tools/build-from-operation', { method: 'POST', body }),
  // AI 优化工具描述（写给 LLM 看）
  optimizeDescription: (body) =>
    request('/tools/optimize-description', { method: 'POST', body }),
  // 模拟对话调试：把工具绑定到 LLM，展示运行链路
  debugChat: (id, message) =>
    request(`/tools/${id}/debug-chat`, { method: 'POST', body: { message } }),
}

// ============ 智能体 ============
export const agents = {
  list: () => request('/agents'),
  get: (id) => request(`/agents/${id}`),
  create: (body) => request('/agents', { method: 'POST', body }),
  update: (id, body) => request(`/agents/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/agents/${id}`, { method: 'DELETE' }),
  test: (id, input) =>
    request(`/agents/${id}/test`, { method: 'POST', body: { input } }),
  // 流式测试（LangGraph 引擎）：返回 fetch Response，调用方用 ReadableStream 消费 SSE
  // signal 可选：传入 AbortSignal 以支持中途取消流式
  testStream: async (id, input, signal) => {
    const token = localStorage.getItem('soar_token')
    const resp = await fetch(`${BASE_URL}/agents/${id}/test/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ input }),
      ...(signal ? { signal } : {}),
    })
    return resp
  },
  // 流式对话（Hermes 引擎）：返回 fetch Response，SSE 事件契约见后端 chat_agent 端点
  // 事件类型：start | status | token | tool_start | tool_end | skill_interrupt | delegate | log | done | error
  // signal 可选：传入 AbortSignal 以支持中途取消流式
  // sessionId 可选：会话 ID，Hermes 引擎按 (agentId, sessionId) 持久化多轮对话上下文
  chatStream: async (id, input, signal, sessionId) => {
    const token = localStorage.getItem('soar_token')
    const resp = await fetch(`${BASE_URL}/agents/${id}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ input, session_id: sessionId || 'default' }),
      ...(signal ? { signal } : {}),
    })
    return resp
  },
  executions: (id, limit = 50) =>
    request(`/agents/${id}/executions?limit=${limit}`),
  monitor: (id) => request(`/agents/${id}/monitor`),
  // 工具搜索状态（tool_search 渐进式披露）：返回分类详情 + 装配预览
  toolSearchStatus: (id) => request(`/agents/${id}/tool-search-status`),
}

// ============ 知识库 ============
export const knowledgeBases = {
  list: () => request('/knowledge-bases'),
  get: (id) => request(`/knowledge-bases/${id}`),
  create: (body) => request('/knowledge-bases', { method: 'POST', body }),
  update: (id, body) => request(`/knowledge-bases/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/knowledge-bases/${id}`, { method: 'DELETE' }),
  documents: (kbId) => request(`/knowledge-bases/${kbId}/documents`),
  addDocument: (kbId, body) =>
    request(`/knowledge-bases/${kbId}/documents`, { method: 'POST', body }),
  updateDocument: (kbId, docId, body) =>
    request(`/knowledge-bases/${kbId}/documents/${docId}`, { method: 'PUT', body }),
  removeDocument: (kbId, docId) =>
    request(`/knowledge-bases/${kbId}/documents/${docId}`, { method: 'DELETE' }),
  search: (kbId, query, topK = 5) =>
    request(`/knowledge-bases/${kbId}/search`, {
      method: 'POST',
      body: { query, top_k: topK },
    }),
  // 文件上传：使用 FormData，由浏览器自动设置 multipart boundary
  uploadDocument: (kbId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request(`/knowledge-bases/${kbId}/documents/upload`, {
      method: 'POST',
      body: fd,
    })
  },
  // 网页抓取：从 URL 抓取内容存入知识库
  fetchUrlDocument: (kbId, body) =>
    request(`/knowledge-bases/${kbId}/documents/fetch-url`, { method: 'POST', body }),
  // 查看文档分段（解析与切片结果）
  segments: (kbId, docId) =>
    request(`/knowledge-bases/${kbId}/documents/${docId}/segments`),
  // 重新解析并分段单个文档
  reparseDocument: (kbId, docId) =>
    request(`/knowledge-bases/${kbId}/documents/${docId}/reparse`, { method: 'POST' }),
  // 批量重新解析知识库下所有文档
  reparseAll: (kbId) =>
    request(`/knowledge-bases/${kbId}/reparse-all`, { method: 'POST' }),
  // 文件查询（读取原始 Excel/CSV 按条件查询）
  fileQuery: (kbId, body) =>
    request(`/knowledge-bases/${kbId}/file-query`, { method: 'POST', body }),
}

// ============ 技能（纯文本指令，注入 Agent system prompt） ============
export const skills = {
  list: (params) => {
    const qs = new URLSearchParams()
    if (params) {
      if (params.category != null) qs.set('category', params.category)
      if (params.enabled != null) qs.set('enabled', params.enabled)
    }
    const query = qs.toString()
    return request(`/skills${query ? `?${query}` : ''}`)
  },
  get: (id) => request(`/skills/${id}`),
  create: (body) => request('/skills', { method: 'POST', body }),
  update: (id, body) => request(`/skills/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/skills/${id}`, { method: 'DELETE' }),
}

// ============ 智能体文件（不做 RAG，原样存储供 read_document 工具读取） ============
export const agentFiles = {
  list: () => request('/agent-files'),
  upload: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/agent-files/upload', { method: 'POST', body: fd })
  },
  remove: (id) => request(`/agent-files/${id}`, { method: 'DELETE' }),
}

// ============ 工作流 ============
export const workflows = {
  list: () => request('/workflows'),
  create: (body) => request('/workflows', { method: 'POST', body }),
  get: (id) => request(`/workflows/${id}`),
  update: (id, body) => request(`/workflows/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/workflows/${id}`, { method: 'DELETE' }),
  testRun: (id, payload) =>
    request(`/workflows/${id}/test-run`, { method: 'POST', body: { payload } }),
  testNode: (node, inputData) =>
    request('/workflows/test-node', {
      method: 'POST',
      body: { node, input_data: inputData },
    }),
  // 校验工作流图配置：返回 { valid, errors, warnings }
  validate: (graphConfig) =>
    request('/workflows/validate', {
      method: 'POST',
      body: { graph_config: graphConfig },
    }),
  // 重置 webhook 密钥：返回 { webhook_secret }
  resetSecret: (id) => request(`/workflows/${id}/reset-secret`, { method: 'POST' }),
  // 工作流版本管理
  versions: (id) => request(`/workflows/${id}/versions`),
  createVersion: (id, changeNote) =>
    request(`/workflows/${id}/versions`, { method: 'POST', body: { change_note: changeNote } }),
  getVersion: (workflowId, versionId) =>
    request(`/workflows/${workflowId}/versions/${versionId}`),
  rollbackVersion: (workflowId, versionId) =>
    request(`/workflows/${workflowId}/versions/${versionId}/rollback`, { method: 'POST' }),
}

// ============ 执行（保留与 executions.js 一致的入口） ============
export const executions = {
  list: () => request('/executions'),
  detail: (id) => request(`/executions/${id}`),
}

// ============ 安全设备 & 设备动作 ============
export const devices = {
  list: () => request('/devices'),
  create: (body) => request('/devices', { method: 'POST', body }),
  update: (id, body) => request(`/devices/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/devices/${id}`, { method: 'DELETE' }),
  // 设备下动作 CRUD
  listActions: (deviceId) => request(`/devices/${deviceId}/actions`),
  createAction: (deviceId, body) =>
    request(`/devices/${deviceId}/actions`, { method: 'POST', body }),
  updateAction: (deviceId, actionId, body) =>
    request(`/devices/${deviceId}/actions/${actionId}`, { method: 'PUT', body }),
  removeAction: (deviceId, actionId) =>
    request(`/devices/${deviceId}/actions/${actionId}`, { method: 'DELETE' }),
  // 测试动作连通性（实际调用设备 API）
  testAction: (deviceId, actionId, params) =>
    request(`/devices/${deviceId}/actions/${actionId}/test`, {
      method: 'POST',
      body: { params },
    }),
}
