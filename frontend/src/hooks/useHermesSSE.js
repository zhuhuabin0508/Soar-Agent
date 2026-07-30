/**
 * Hermes SSE 流式事件解析共享 hook。
 *
 * 统一处理 Hermes 引擎的 SSE 事件解析，消除 AgentEditor.jsx 和 ChatPage.jsx
 * 之间的重复逻辑。支持所有事件类型：start / thinking / token / status /
 * tool_start / tool_end / delegate / log / done / error。
 *
 * 用法：
 *   const { reply, thinking, toolCalls, isStreaming, parseChunk, reset } = useHermesSSE()
 *   // 在 fetch SSE 流中：
 *   for (const line of lines) {
 *     parseChunk(line)  // 自动更新内部状态
 *   }
 */
import { useState, useCallback, useRef } from 'react'

// SSE 事件类型常量（前后端契约，见 backend/app/agent/hermes/sse.py）
export const SSE_EVENT_TYPES = {
  START: 'start',
  THINKING: 'thinking',
  TOKEN: 'token',
  STATUS: 'status',
  TOOL_START: 'tool_start',
  TOOL_END: 'tool_end',
  DELEGATE: 'delegate',
  LOG: 'log',
  DONE: 'done',
  ERROR: 'error',
}

/**
 * 解析单行 SSE 数据，返回事件对象或 null。
 * 可独立使用（不需要 hook 上下文），适合在组件自定义状态管理中复用。
 */
export function parseSSELine(line) {
  if (!line || !line.startsWith('data: ')) return null
  try {
    return JSON.parse(line.slice(6))
  } catch {
    return null
  }
}

export function useHermesSSE() {
  const [reply, setReply] = useState('')
  const [thinking, setThinking] = useState('')
  const [toolCalls, setToolCalls] = useState([])
  const [delegateGroups, setDelegateGroups] = useState([])
  const [statusMsgs, setStatusMsgs] = useState([])
  const [logs, setLogs] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState('')
  const fullTextRef = useRef('')

  const reset = useCallback(() => {
    setReply('')
    setThinking('')
    setToolCalls([])
    setDelegateGroups([])
    setStatusMsgs([])
    setLogs([])
    setIsStreaming(false)
    setError('')
    fullTextRef.current = ''
  }, [])

  /**
   * 解析一个 SSE chunk 行，自动更新内部状态。
   * 返回解析后的事件对象（供调用方做额外处理），无法解析时返回 null。
   */
  const parseChunk = useCallback((line) => {
    const data = parseSSELine(line)
    if (!data) return null

    switch (data.type) {
      case SSE_EVENT_TYPES.START:
        setIsStreaming(true)
        break
      case SSE_EVENT_TYPES.THINKING:
        setThinking((prev) => prev + (data.content || ''))
        break
      case SSE_EVENT_TYPES.TOKEN:
        fullTextRef.current += data.content || ''
        setReply(fullTextRef.current)
        break
      case SSE_EVENT_TYPES.STATUS:
        setStatusMsgs((prev) => [...prev, data.message || ''])
        break
      case SSE_EVENT_TYPES.TOOL_START:
        setToolCalls((prev) => [
          ...prev,
          {
            name: data.tool_name || '',
            id: data.tool_call_id || '',
            status: 'running',
            result: null,
          },
        ])
        break
      case SSE_EVENT_TYPES.TOOL_END:
        setToolCalls((prev) =>
          prev.map((tc, i) =>
            i === prev.length - 1
              ? { ...tc, status: 'done', result: data.result }
              : tc
          )
        )
        break
      case SSE_EVENT_TYPES.DELEGATE:
        setDelegateGroups((prev) => [...prev, data])
        break
      case SSE_EVENT_TYPES.LOG:
        setLogs((prev) => [
          ...prev,
          { level: data.level || 'info', message: data.message || '' },
        ])
        break
      case SSE_EVENT_TYPES.DONE:
        setIsStreaming(false)
        setReply(data.content || data.reply || fullTextRef.current)
        break
      case SSE_EVENT_TYPES.ERROR:
        setError(data.message || '未知错误')
        setIsStreaming(false)
        break
      default:
        break
    }
    return data
  }, [])

  return {
    reply,
    thinking,
    toolCalls,
    delegateGroups,
    statusMsgs,
    logs,
    isStreaming,
    error,
    parseChunk,
    reset,
    fullTextRef,
  }
}
