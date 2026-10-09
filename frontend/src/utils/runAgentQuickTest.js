import { agents as agentsApi } from '../api/client'

/** 从同步 /test 响应提取可展示文本 */
export function extractSyncTestReply(res) {
  if (!res) return ''
  if (res.reply) return res.reply
  const parts = []
  if (res.decision) parts.push(`决策: ${res.decision}`)
  if (res.target_ip) parts.push(`目标 IP: ${res.target_ip}`)
  if (res.reason) parts.push(`理由: ${res.reason}`)
  if (parts.length) return parts.join('\n')
  const msgs = res.messages || []
  const last = [...msgs].reverse().find((m) => m.role === 'assistant' || m.role === 'ai')
  if (last?.content) {
    return typeof last.content === 'string' ? last.content : JSON.stringify(last.content, null, 2)
  }
  return ''
}

/**
 * 运行智能体试运行（Hermes → chat SSE；其他 → /test）
 * @param {number} agentId
 * @param {string} input
 * @param {{ engine?: string, onProgress?: (patch: object) => void }} options
 */
export async function runAgentQuickTest(agentId, input, options = {}) {
  const { engine = 'hermes', onProgress } = options
  const notify = (patch) => { if (onProgress) onProgress(patch) }

  if (engine === 'hermes') {
    const resp = await agentsApi.chatStream(
      agentId,
      input,
      undefined,
      `quick-create-${agentId}-${Date.now()}`,
    )
    if (!resp.ok) {
      const errText = await resp.text()
      throw new Error(errText || `HTTP ${resp.status}`)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullText = ''
    const toolCalls = []
    const logs = []
    const statusMsgs = []

    notify({
      mode: 'hermes',
      streaming: true,
      reply: '',
      toolCalls: [],
      logs: [],
      statusMsgs: [],
    })

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          switch (data.type) {
            case 'token':
              fullText += data.content || ''
              notify({ reply: fullText, streaming: true })
              break
            case 'status':
              statusMsgs.push(data.message || '')
              notify({ statusMsgs: [...statusMsgs] })
              break
            case 'tool_start':
              toolCalls.push({
                name: data.tool_name || '',
                call_id: data.tool_call_id || '',
                status: 'running',
                message: data.message || '',
                result: null,
              })
              logs.push({ level: 'info', message: `▶ 调用工具 ${data.tool_name || ''}` })
              notify({ toolCalls: [...toolCalls], logs: [...logs] })
              break
            case 'tool_end': {
              const idx = toolCalls.findIndex(
                (tc) => tc.call_id === data.tool_call_id && tc.status === 'running',
              )
              const entry = {
                name: data.tool_name || '',
                call_id: data.tool_call_id || '',
                status: 'done',
                message: data.message || '',
                result: data.result,
              }
              if (idx >= 0) toolCalls[idx] = { ...toolCalls[idx], ...entry }
              else toolCalls.push(entry)
              logs.push({
                level: 'info',
                message: `✓ 工具 ${data.tool_name || ''} 完成`,
                detail: data.result,
              })
              notify({ toolCalls: [...toolCalls], logs: [...logs] })
              break
            }
            case 'log':
              logs.push(data.log || { level: 'info', message: String(data.message || data) })
              notify({ logs: [...logs] })
              break
            case 'done':
              if (data.content) fullText = data.content
              notify({
                reply: fullText,
                streaming: false,
                tokenUsage: data.usage || null,
              })
              break
            case 'error':
              throw new Error(data.message || '测试失败')
            default:
              break
          }
        } catch (e) {
          if (e instanceof SyntaxError) continue
          throw e
        }
      }
    }

    return {
      mode: 'hermes',
      streaming: false,
      reply: fullText,
      toolCalls,
      logs,
      statusMsgs,
    }
  }

  const res = await agentsApi.test(agentId, input)
  const reply = extractSyncTestReply(res)
  const result = {
    mode: 'sync',
    streaming: false,
    reply,
    messages: res.messages || [],
    logs: res.logs || [],
    decision: res.decision,
    target_ip: res.target_ip,
    reason: res.reason,
    duration: res.duration,
    raw: res,
  }
  notify(result)
  return result
}
