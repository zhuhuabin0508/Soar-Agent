/**
 * 对话页面 —— 左右分栏布局
 *
 * 左侧（~280px）：智能体导航区（搜索 / 分组 / 选中高亮 / 置顶）
 * 右侧（flex-1）：对话功能区（欢迎态 / 消息气泡 / 流式打字机 / 自适应输入）
 *
 * 会话历史使用 localStorage 持久化（按 agentId 隔离），切换智能体不串对话。
 * 流式输出复用 AgentEditor 的 SSE 解析逻辑，支持 Hermes + LangGraph 双引擎。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { agents as agentsApi, agentFiles as agentFilesApi } from '../api/client'
import MarkdownRenderer from '../components/MarkdownRenderer'

// ============================================================================
// 常量 & 工具
// ============================================================================
const SIDEBAR_WIDTH = 280
const SIDEBAR_MIN = 240
const INPUT_MAX_HEIGHT = 200

// localStorage 键
const LS_HISTORY_PREFIX = 'soar_chat_history_'
const LS_PINNED = 'soar_chat_pinned_agents'
const LS_SELECTED = 'soar_chat_selected_agent'

// 生成唯一消息 ID
const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

// 读取智能体会话历史
function loadHistory(agentId) {
  try {
    const raw = localStorage.getItem(`${LS_HISTORY_PREFIX}${agentId}`)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

// 保存智能体会话历史
function saveHistory(agentId, messages) {
  try {
    // 限制存储条数，避免 localStorage 溢出
    const trimmed = messages.slice(-200)
    localStorage.setItem(`${LS_HISTORY_PREFIX}${agentId}`, JSON.stringify(trimmed))
  } catch {
    // localStorage 满了静默失败
  }
}

// 会话 ID（Hermes 引擎按 (agentId, sessionId) 持久化多轮对话上下文）
const LS_SESSION_PREFIX = 'soar_chat_session_'
const genSessionId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`

function loadSessionId(agentId) {
  try {
    return localStorage.getItem(`${LS_SESSION_PREFIX}${agentId}`) || ''
  } catch {
    return ''
  }
}

function saveSessionId(agentId, sid) {
  try {
    localStorage.setItem(`${LS_SESSION_PREFIX}${agentId}`, sid)
  } catch {
    // ignore
  }
}

// 读取置顶列表
function loadPinned() {
  try {
    const raw = localStorage.getItem(LS_PINNED)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function savePinned(ids) {
  try {
    localStorage.setItem(LS_PINNED, JSON.stringify(ids))
  } catch {
    // ignore
  }
}

// ============================================================================
// 主页面
// ============================================================================
export default function ChatPage() {
  // ----- 智能体列表 -----
  const [agentList, setAgentList] = useState([])
  const [loadingAgents, setLoadingAgents] = useState(true)

  // ----- 选中的智能体 -----
  const [selectedAgentId, setSelectedAgentId] = useState(() => {
    try {
      return localStorage.getItem(LS_SELECTED) || ''
    } catch {
      return ''
    }
  })

  // ----- 搜索 -----
  const [searchQuery, setSearchQuery] = useState('')

  // ----- 置顶 -----
  const [pinnedIds, setPinnedIds] = useState(() => loadPinned())

  // ----- 会话历史（按 agentId） -----
  const [histories, setHistories] = useState({})
  // 当前选中智能体的消息列表
  const currentMessages = selectedAgentId ? histories[selectedAgentId] || [] : []

  // 会话 ID（按 agentId 隔离）：Hermes 引擎多轮对话上下文持久化键
  const [sessionIds, setSessionIds] = useState({})

  // ----- 流式状态 -----
  const [streaming, setStreaming] = useState(false)
  const abortControllerRef = useRef(null)

  // ----- 输入文本 -----
  const [inputText, setInputText] = useState('')

  // ----- 上传文件（不做 RAG，供 read_document 工具读取） -----
  const [uploadedFiles, setUploadedFiles] = useState([])
  const [selectedFileIds, setSelectedFileIds] = useState(() => new Set())
  const [uploading, setUploading] = useState(false)

  // ----- 加载智能体列表 -----
  useEffect(() => {
    let alive = true
    ;(async () => {
      setLoadingAgents(true)
      try {
        const list = await agentsApi.list()
        if (!alive) return
        const arr = Array.isArray(list) ? list : []
        setAgentList(arr)
        // 首次加载：选中第一个或恢复上次选中
        if (!selectedAgentId && arr.length > 0) {
          const restored = localStorage.getItem(LS_SELECTED)
          const exists = restored && arr.find((a) => String(a.id) === String(restored))
          const firstId = exists ? String(exists.id) : String(arr[0].id)
          setSelectedAgentId(firstId)
        }
      } catch {
        // ignore
      } finally {
        if (alive) setLoadingAgents(false)
      }
    })()
    return () => { alive = false }
  }, [])

  // ----- 选中智能体变化时加载历史 -----
  useEffect(() => {
    if (!selectedAgentId) return
    try {
      localStorage.setItem(LS_SELECTED, selectedAgentId)
    } catch {
      // ignore
    }
    // 从 localStorage 加载历史到内存
    if (!histories[selectedAgentId]) {
      const msgs = loadHistory(selectedAgentId)
      setHistories((prev) => ({ ...prev, [selectedAgentId]: msgs }))
    }
    // 确保该智能体有会话 ID（无则生成并持久化）
    if (!sessionIds[selectedAgentId]) {
      const sid = loadSessionId(selectedAgentId) || genSessionId()
      saveSessionId(selectedAgentId, sid)
      setSessionIds((prev) => ({ ...prev, [selectedAgentId]: sid }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentId])

  // ----- 中止当前流式 -----
  const abortStream = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    setStreaming(false)
  }, [])

  // ----- 切换智能体 -----
  const selectAgent = useCallback(
    (agentId) => {
      if (agentId === selectedAgentId) return
      // 中止当前流式
      if (streaming) abortStream()
      setSelectedAgentId(String(agentId))
    },
    [selectedAgentId, streaming, abortStream]
  )

  // ----- 置顶/取消置顶 -----
  const togglePin = useCallback((agentId) => {
    const id = String(agentId)
    setPinnedIds((prev) => {
      const next = prev.includes(id)
        ? prev.filter((x) => x !== id)
        : [...prev, id]
      savePinned(next)
      return next
    })
  }, [])

  // ----- 新建会话（清空当前智能体历史 + 生成新会话 ID） -----
  const newConversation = useCallback(() => {
    if (!selectedAgentId) return
    if (streaming) abortStream()
    // 生成新 session_id，使后端加载空历史（与新对话匹配）
    const sid = genSessionId()
    saveSessionId(selectedAgentId, sid)
    setSessionIds((prev) => ({ ...prev, [selectedAgentId]: sid }))
    setHistories((prev) => ({ ...prev, [selectedAgentId]: [] }))
    saveHistory(selectedAgentId, [])
  }, [selectedAgentId, streaming, abortStream])

  // ----- 更新当前消息列表 -----
  const updateMessages = useCallback(
    (updater) => {
      if (!selectedAgentId) return
      setHistories((prev) => {
        const cur = prev[selectedAgentId] || []
        const next = typeof updater === 'function' ? updater(cur) : updater
        saveHistory(selectedAgentId, next)
        return { ...prev, [selectedAgentId]: next }
      })
    },
    [selectedAgentId]
  )

  // ----- 加载已上传文件列表 -----
  const loadUploadedFiles = useCallback(async () => {
    try {
      const list = await agentFilesApi.list()
      setUploadedFiles(Array.isArray(list) ? list : [])
    } catch {
      // 静默失败
    }
  }, [])

  useEffect(() => {
    loadUploadedFiles()
  }, [loadUploadedFiles])

  // ----- 上传文件 -----
  const handleFileUpload = useCallback(
    async (file) => {
      if (!file) return
      // 前端校验：文件大小和类型
      const MAX_SIZE = 50 * 1024 * 1024 // 50MB
      const ALLOWED_EXT = ['.xlsx', '.xls', '.docx', '.pdf', '.csv', '.txt', '.md', '.json']
      const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
      if (!ALLOWED_EXT.includes(ext)) {
        window.alert(`不支持的文件类型：${ext}，仅支持 ${ALLOWED_EXT.join(' / ')}`)
        return
      }
      if (file.size > MAX_SIZE) {
        window.alert(`文件超过 50MB（当前 ${(file.size / 1024 / 1024).toFixed(1)}MB），请压缩或拆分后上传`)
        return
      }
      setUploading(true)
      try {
        await agentFilesApi.upload(file)
        await loadUploadedFiles()
      } catch (err) {
        window.alert(`文件上传失败：${err.message || err}`)
      } finally {
        setUploading(false)
      }
    },
    [loadUploadedFiles]
  )

  // ----- 删除文件 -----
  const handleDeleteFile = useCallback(
    async (fileId) => {
      try {
        await agentFilesApi.remove(fileId)
        setUploadedFiles((prev) => prev.filter((f) => f.id !== fileId))
        setSelectedFileIds((prev) => {
          const next = new Set(prev)
          next.delete(fileId)
          return next
        })
      } catch (err) {
        window.alert(`文件删除失败：${err.message || err}`)
      }
    },
    []
  )

  // ----- 切换文件勾选 -----
  const toggleFileSelect = useCallback((fileId) => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev)
      if (next.has(fileId)) next.delete(fileId)
      else next.add(fileId)
      return next
    })
  }, [])

  // ----- 确保 read_document 工具已启用 -----
  const ensureReadDocumentEnabled = useCallback(
    async (agent) => {
      const tools = agent.enabled_tools || []
      if (tools.includes('read_document')) return agent
      try {
        const updated = { ...agent, enabled_tools: [...tools, 'read_document'] }
        await agentsApi.update(agent.id, updated)
        // 同步本地列表
        setAgentList((prev) =>
          prev.map((a) => (String(a.id) === String(agent.id) ? { ...a, enabled_tools: updated.enabled_tools } : a))
        )
        return updated
      } catch {
        // 启用失败不阻断发送，智能体可能仍能回答（无文件读取能力）
        return agent
      }
    },
    []
  )

  // ----- 发送消息 -----
  const sendMessage = useCallback(async () => {
    const text = inputText.trim()
    if (!text || !selectedAgentId || streaming) return

    const agent = agentList.find((a) => String(a.id) === String(selectedAgentId))
    if (!agent) return

    // 勾选的文件：自动启用 read_document 工具 + 将文件名注入消息上下文
    const selectedFiles = uploadedFiles.filter((f) => selectedFileIds.has(f.id))
    let messageText = text
    if (selectedFiles.length > 0) {
      // 自动启用 read_document（如果尚未启用）
      await ensureReadDocumentEnabled(agent)
      // 将文件名列表注入消息，让 LLM 知道可读取哪些文件
      const fileList = selectedFiles.map((f) => `- ${f.original_name}`).join('\n')
      messageText =
        `[用户上传了以下文件，可使用 read_document 工具按文件名读取完整内容：\n${fileList}\n]\n\n${text}`
    }

    // 1. 追加用户消息 + 空的 AI 消息
    const userMsg = {
      id: genId(),
      role: 'user',
      content: messageText,
      timestamp: Date.now(),
    }
    const aiMsg = {
      id: genId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      status: 'streaming',
      toolCalls: [],
      delegateGroups: [],
      statusMsgs: [],
    }
    updateMessages((prev) => [...prev, userMsg, aiMsg])
    setInputText('')
    setStreaming(true)

    // 2. 发起 SSE 流式请求
    const controller = new AbortController()
    abortControllerRef.current = controller
    const isHermes = (agent.engine || 'langgraph') === 'hermes'

    try {
      const resp = isHermes
        ? await agentsApi.chatStream(
            selectedAgentId,
            messageText,
            controller.signal,
            sessionIds[selectedAgentId] || 'default',
          )
        : await agentsApi.testStream(selectedAgentId, messageText, controller.signal)

      if (!resp.ok) {
        const errText = await resp.text().catch(() => '')
        throw new Error(errText || `HTTP ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let fullText = ''
      // 节流缓冲：累积 token/thinking 内容，每 60ms 批量更新 UI
      // 避免 240+184 个事件逐个触发 React 重渲染导致浏览器卡死
      let pendingContent = ''
      let pendingThinking = ''
      let flushTimer = null
      const flushPending = () => {
        if (flushTimer !== null) { clearTimeout(flushTimer); flushTimer = null }
        if (!pendingContent && !pendingThinking) return
        const cDelta = pendingContent
        const tDelta = pendingThinking
        pendingContent = ''
        pendingThinking = ''
        updateMessages((prev) =>
          prev.map((m) => {
            if (m.id !== aiMsg.id) return m
            const next = { ...m }
            if (cDelta) next.content = (m.content || '') + cDelta
            if (tDelta) next.thinking = (m.thinking || '') + tDelta
            return next
          })
        )
      }
      const scheduleFlush = () => {
        if (flushTimer === null) {
          flushTimer = setTimeout(flushPending, 60)
        }
      }

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

            if (isHermes) {
              // ===== Hermes 引擎事件 =====
              switch (data.type) {
                case 'thinking':
                  pendingThinking += data.content || ''
                  scheduleFlush()
                  break
                case 'status':
                  // 引擎状态消息（如「正在执行 N 个工具调用…」），加入执行过程日志
                  updateMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsg.id
                        ? {
                            ...m,
                            statusMsgs: [...(m.statusMsgs || []), data.message || ''],
                          }
                        : m
                    )
                  )
                  break
                case 'log':
                  // 引擎日志（level + message），加入执行过程日志
                  updateMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsg.id
                        ? {
                            ...m,
                            statusMsgs: [
                              ...(m.statusMsgs || []),
                              `[${data.level || 'info'}] ${data.message || ''}`,
                            ],
                          }
                        : m
                    )
                  )
                  break
                case 'token':
                  fullText += data.content || ''
                  pendingContent += data.content || ''
                  scheduleFlush()
                  break
                case 'tool_start':
                  flushPending()
                  updateMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsg.id
                        ? {
                            ...m,
                            toolCalls: [
                              ...(m.toolCalls || []),
                              {
                                name: data.tool_name || '',
                                call_id: data.tool_call_id || '',
                                status: 'running',
                                message: data.message || '',
                              },
                            ],
                          }
                        : m
                    )
                  )
                  break
                case 'tool_end':
                  updateMessages((prev) =>
                    prev.map((m) => {
                      if (m.id !== aiMsg.id) return m
                      const tcs = [...(m.toolCalls || [])]
                      const idx = tcs.findIndex(
                        (tc) => tc.call_id === data.tool_call_id && tc.status === 'running'
                      )
                      if (idx >= 0) {
                        tcs[idx] = {
                          ...tcs[idx],
                          status: 'done',
                          result: data.result,
                          message: data.message || tcs[idx].message,
                        }
                      }
                      return { ...m, toolCalls: tcs }
                    })
                  )
                  break
                case 'delegate': {
                  const info = data.result || {}
                  const sid = info.subagent_id || 'unknown'
                  const evt = info.event || {}
                  updateMessages((prev) =>
                    prev.map((m) => {
                      if (m.id !== aiMsg.id) return m
                      const groups = [...(m.delegateGroups || [])]
                      let gIdx = groups.findIndex((g) => g.subagent_id === sid)
                      if (gIdx < 0) {
                        groups.push({
                          subagent_id: sid,
                          task_index: info.task_index ?? 0,
                          status: 'running',
                          goal: '',
                          events: [],
                          expanded: false,
                        })
                        gIdx = groups.length - 1
                      }
                      if (evt.type === 'start' && evt.message) {
                        groups[gIdx].goal = evt.message
                      }
                      if (evt.type === 'done') groups[gIdx].status = 'completed'
                      else if (evt.type === 'error') groups[gIdx].status = 'failed'
                      groups[gIdx].events.push({
                        type: evt.type || 'unknown',
                        content: evt.content || '',
                        message: evt.message || '',
                        tool_name: evt.tool_name || '',
                        result: evt.result ?? null,
                      })
                      return { ...m, delegateGroups: groups }
                    })
                  )
                  break
                }
                case 'done':
                  flushPending()
                  // 不用 data.content 覆盖已累积的流式内容
                  // data.content 只包含最后一轮 LLM 回复，会丢失前面轮次的分析过程
                  // 保留 m.content（包含所有轮次的 token 累积），仅无累积时用 data.content 回退
                  updateMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsg.id
                        ? { ...m, content: m.content || data.content || fullText || '', status: 'done' }
                        : m
                    )
                  )
                  break
                case 'error':
                  flushPending()
                  updateMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsg.id
                        ? {
                            ...m,
                            status: 'error',
                            content: m.content || `[错误] ${data.message || ''}`,
                          }
                        : m
                    )
                  )
                  break
                default:
                  break
              }
            } else {
              // ===== LangGraph 引擎事件 =====
              // 有工具/知识库的智能体走流式 Agent 决策：
              // start(mode=agent) → log → status → tool_start → tool_end → token... → done(result)
              // 无工具的纯对话走流式：start(mode=chat) → token... → done(reply)
              if (data.type === 'start') {
                // 会话开始，无需额外处理（消息已是 streaming 状态）
              } else if (data.type === 'token') {
                fullText += data.content
                pendingContent += data.content || ''
                scheduleFlush()
              } else if (data.type === 'tool_start') {
                // 工具调用开始：加入工具调用列表
                flushPending()
                updateMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMsg.id
                      ? {
                          ...m,
                          toolCalls: [
                            ...(m.toolCalls || []),
                            {
                              name: data.tool_name || '',
                              call_id: data.tool_name || '',
                              status: 'running',
                              message: data.message || '',
                            },
                          ],
                        }
                      : m
                  )
                )
              } else if (data.type === 'tool_end') {
                // 工具调用结束：更新对应工具状态
                flushPending()
                updateMessages((prev) =>
                  prev.map((m) => {
                    if (m.id !== aiMsg.id) return m
                    const tcs = [...(m.toolCalls || [])]
                    const idx = tcs.findIndex(
                      (tc) => tc.call_id === (data.tool_name || '') && tc.status === 'running'
                    )
                    if (idx >= 0) {
                      tcs[idx] = {
                        ...tcs[idx],
                        status: 'done',
                        result: data.result,
                        message: data.message || tcs[idx].message,
                      }
                    }
                    return { ...m, toolCalls: tcs }
                  })
                )
              } else if (data.type === 'status') {
                // agent 决策模式的状态更新：显示进度，避免长时间空白
                flushPending()
                updateMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMsg.id
                      ? { ...m, content: fullText || `⚙️ ${data.message || '处理中…'}` }
                      : m
                  )
                )
              } else if (data.type === 'log') {
                // 日志：暂存，不覆盖主回复内容
              } else if (data.type === 'message') {
                // 推理过程消息：可选展示中间步骤
              } else if (data.type === 'done') {
                // 提取最终回复（兼容纯对话 + agent 决策两种模式）
                flushPending()
                let reply = ''
                if (data.reply !== undefined) {
                  // 纯对话流式模式：done 携带 reply 字段
                  reply = data.reply
                } else if (data.result) {
                  const r = data.result
                  if (typeof r.response === 'string' && r.response) {
                    // 真实 LangGraph + 自定义 system_prompt：返回 LLM 原始文本
                    reply = r.response
                  } else if (Array.isArray(r.messages) && r.messages.length > 0) {
                    // agent 决策模式：取最后一条 AI 消息
                    // 注意 LangChain 的 role 是 "ai" 而非 "assistant"
                    const lastAi = [...r.messages]
                      .reverse()
                      .find((m) =>
                        m.role === 'ai' ||
                        m.role === 'assistant' ||
                        m.role === 'AIMessage'
                      )
                    if (lastAi && lastAi.content) {
                      reply = lastAi.content
                    }
                  }
                  // 仅决策模式（无自然语言回复）：格式化可读文本
                  if (!reply && r.decision) {
                    reply = `决策：${r.decision}`
                    if (r.reason) reply += `\n原因：${r.reason}`
                    if (r.target_ip) reply += `\n目标 IP：${r.target_ip}`
                  }
                }
                updateMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMsg.id
                      ? { ...m, content: m.content || reply || fullText || '(无回复)', status: 'done' }
                      : m
                  )
                )
              } else if (data.type === 'error') {
                updateMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMsg.id
                      ? {
                          ...m,
                          status: 'error',
                          content: m.content || `[错误] ${data.message || ''}`,
                        }
                      : m
                  )
                )
              }
            }
          } catch {
            // JSON 解析错误忽略
          }
        }
      }

      // 流结束但未收到 done 事件，标记为 done
      flushPending()
      updateMessages((prev) =>
        prev.map((m) =>
          m.id === aiMsg.id && m.status === 'streaming'
            ? { ...m, content: m.content || fullText, status: 'done' }
            : m
        )
      )
    } catch (err) {
      flushPending()
      if (err.name === 'AbortError') {
        // 用户主动中止
        updateMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsg.id && m.status === 'streaming'
              ? {
                  ...m,
                  status: 'done',
                  content: m.content + '\n\n_[已中止]_',
                }
              : m
          )
        )
      } else {
        updateMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsg.id
              ? {
                  ...m,
                  status: 'error',
                  content: m.content || `[请求失败] ${err.message || err}`,
                }
              : m
          )
        )
      }
    } finally {
      setStreaming(false)
      abortControllerRef.current = null
    }
  }, [inputText, selectedAgentId, streaming, agentList, updateMessages, uploadedFiles, selectedFileIds, ensureReadDocumentEnabled])

  // ----- 重新生成最后一条 AI 消息 -----
  const regenerate = useCallback(() => {
    if (!selectedAgentId || streaming) return
    const msgs = histories[selectedAgentId] || []
    // 找最后一条 AI 消息
    let lastAiIdx = -1
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'assistant') {
        lastAiIdx = i
        break
      }
    }
    if (lastAiIdx < 0) return
    // 找它前面的用户消息
    let userIdx = -1
    for (let i = lastAiIdx - 1; i >= 0; i--) {
      if (msgs[i].role === 'user') {
        userIdx = i
        break
      }
    }
    if (userIdx < 0) return
    const userText = msgs[userIdx].content
    // 删除从用户消息之后的所有消息
    updateMessages((prev) => prev.slice(0, userIdx))
    // 重新发送
    setInputText(userText)
    // 延迟一帧让 inputText 更新后触发 sendMessage
    setTimeout(() => {
      sendMessage()
    }, 50)
  }, [selectedAgentId, streaming, histories, updateMessages, sendMessage])

  // ----- 删除单条消息 -----
  const deleteMessage = useCallback(
    (msgId) => {
      updateMessages((prev) => prev.filter((m) => m.id !== msgId))
    },
    [updateMessages]
  )

  // ----- 切换 delegate 分组展开 -----
  const toggleDelegateGroup = useCallback(
    (msgId, subagentId) => {
      updateMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? {
                ...m,
                delegateGroups: (m.delegateGroups || []).map((g) =>
                  g.subagent_id === subagentId
                    ? { ...g, expanded: !g.expanded }
                    : g
                ),
              }
            : m
        )
      )
    },
    [updateMessages]
  )

  // ----- 过滤后的智能体列表 -----
  const filteredAgents = useMemo(() => {
    if (!searchQuery.trim()) return agentList
    const q = searchQuery.toLowerCase()
    return agentList.filter(
      (a) =>
        (a.name || '').toLowerCase().includes(q) ||
        (a.description || '').toLowerCase().includes(q)
    )
  }, [agentList, searchQuery])

  // ----- 分组 -----
  const pinnedAgents = filteredAgents.filter((a) =>
    pinnedIds.includes(String(a.id))
  )
  const otherAgents = filteredAgents.filter(
    (a) => !pinnedIds.includes(String(a.id))
  )

  const selectedAgent = agentList.find(
    (a) => String(a.id) === String(selectedAgentId)
  )

  // ----- 页面卸载时中止流式 -----
  useEffect(() => {
    return () => abortStream()
  }, [abortStream])

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* ===== 左侧边栏 ===== */}
      <ChatSidebar
        width={SIDEBAR_WIDTH}
        minWidth={SIDEBAR_MIN}
        agents={agentList}
        filteredAgents={filteredAgents}
        pinnedAgents={pinnedAgents}
        otherAgents={otherAgents}
        selectedAgentId={selectedAgentId}
        searchQuery={searchQuery}
        loading={loadingAgents}
        onSelect={selectAgent}
        onSearch={setSearchQuery}
        onTogglePin={togglePin}
        onNewConversation={newConversation}
      />

      {/* ===== 右侧主区域 ===== */}
      <ChatMain
        agent={selectedAgent}
        messages={currentMessages}
        streaming={streaming}
        inputText={inputText}
        onInputChange={setInputText}
        onSend={sendMessage}
        onStop={abortStream}
        onRegenerate={regenerate}
        onDeleteMessage={deleteMessage}
        onToggleDelegate={toggleDelegateGroup}
        uploadedFiles={uploadedFiles}
        selectedFileIds={selectedFileIds}
        uploading={uploading}
        onFileUpload={handleFileUpload}
        onFileDelete={handleDeleteFile}
        onToggleFile={toggleFileSelect}
      />
    </div>
  )
}

// ============================================================================
// 左侧边栏：智能体导航区
// ============================================================================
function ChatSidebar({
  width,
  minWidth,
  agents,
  filteredAgents,
  pinnedAgents,
  otherAgents,
  selectedAgentId,
  searchQuery,
  loading,
  onSelect,
  onSearch,
  onTogglePin,
  onNewConversation,
}) {
  return (
    <aside
      className="flex shrink-0 flex-col border-r border-gray-800 bg-gray-900/50"
      style={{ width: `${width}px`, minWidth: `${minWidth}px` }}
    >
      {/* 顶部功能区 */}
      <div className="shrink-0 border-b border-gray-800 p-3">
        <button
          type="button"
          onClick={onNewConversation}
          className="btn-primary btn-sm mb-2 w-full"
        >
          ✨ 新建会话
        </button>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="搜索智能体…"
          className="input-base !py-1.5 text-xs"
        />
      </div>

      {/* 智能体列表区 */}
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {loading && (
          <div className="py-8 text-center text-xs text-gray-600">加载中…</div>
        )}

        {!loading && filteredAgents.length === 0 && (
          <div className="py-8 text-center text-xs text-gray-600">
            {searchQuery ? '未找到匹配的智能体' : '暂无智能体'}
          </div>
        )}

        {/* 已置顶分组 */}
        {pinnedAgents.length > 0 && (
          <AgentGroup
            title="已置顶"
            agents={pinnedAgents}
            selectedAgentId={selectedAgentId}
            onSelect={onSelect}
            onTogglePin={onTogglePin}
            defaultExpanded
          />
        )}

        {/* 全部智能体分组 */}
        {otherAgents.length > 0 && (
          <AgentGroup
            title="全部智能体"
            agents={otherAgents}
            selectedAgentId={selectedAgentId}
            onSelect={onSelect}
            onTogglePin={onTogglePin}
            defaultExpanded
          />
        )}
      </div>

      {/* 底部入口 */}
      <div className="shrink-0 border-t border-gray-800 p-2">
        <a
          href="/agents"
          className="flex items-center gap-2 rounded-md px-3 py-2 text-xs text-gray-500 transition-colors hover:bg-gray-800/60 hover:text-gray-300"
        >
          <span>⚙️</span>
          <span>管理智能体</span>
        </a>
      </div>
    </aside>
  )
}

// 可折叠的智能体分组
function AgentGroup({
  title,
  agents,
  selectedAgentId,
  onSelect,
  onTogglePin,
  defaultExpanded = true,
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-gray-500 transition hover:text-gray-300"
      >
        <span className="text-[9px]">{expanded ? '▼' : '▶'}</span>
        <span>{title}</span>
        <span className="ml-auto rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-500">
          {agents.length}
        </span>
      </button>
      {expanded && (
        <div className="mt-0.5 flex flex-col gap-0.5">
          {agents.map((agent) => (
            <AgentItem
              key={agent.id}
              agent={agent}
              selected={String(agent.id) === String(selectedAgentId)}
              onSelect={onSelect}
              onTogglePin={onTogglePin}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// 单个智能体条目
function AgentItem({ agent, selected, onSelect, onTogglePin }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const name = agent.name || `智能体 ${agent.id}`
  const avatar = agent.avatar
  const desc = agent.description || ''
  const isPinned = agent._pinned

  return (
    <div
      className={`group relative flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 transition-colors ${
        selected
          ? 'bg-gradient-to-r from-brand-500/20 to-brand-500/5 text-brand-200 ring-1 ring-inset ring-brand-500/30'
          : 'text-gray-300 hover:bg-gray-800/60'
      }`}
      onClick={() => onSelect(agent.id)}
    >
      {/* 选中指示条 */}
      {selected && (
        <span className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-full bg-brand-400" />
      )}
      {/* 头像 */}
      <div className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-500/15 text-sm">
        {avatar ? (
          <img src={avatar} alt={name} className="h-full w-full object-cover" />
        ) : (
          <span className="font-semibold text-brand-300">
            {name.charAt(0).toUpperCase()}
          </span>
        )}
      </div>
      {/* 名称 + 描述 */}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{name}</div>
        {desc && (
          <div className="truncate text-[10px] text-gray-500">{desc}</div>
        )}
      </div>
      {/* 右键菜单触发 */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          setMenuOpen((o) => !o)
        }}
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-gray-600 opacity-0 transition hover:bg-gray-700 hover:text-gray-300 group-hover:opacity-100"
        title="更多操作"
      >
        ⋯
      </button>
      {menuOpen && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={(e) => {
              e.stopPropagation()
              setMenuOpen(false)
            }}
          />
          <div className="absolute right-2 top-8 z-50 w-28 overflow-hidden rounded-lg border border-gray-700 bg-gray-800 py-1 shadow-xl">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onTogglePin(agent.id)
                setMenuOpen(false)
              }}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-gray-300 transition hover:bg-gray-700"
            >
              <span>{isPinned ? '📌' : '📍'}</span>
              <span>{isPinned ? '取消置顶' : '置顶'}</span>
            </button>
          </div>
        </>
      )}
    </div>
  )
}

// ============================================================================
// 右侧主区域：对话功能区
// ============================================================================
function ChatMain({
  agent,
  messages,
  streaming,
  inputText,
  onInputChange,
  onSend,
  onStop,
  onRegenerate,
  onDeleteMessage,
  onToggleDelegate,
  uploadedFiles,
  selectedFileIds,
  uploading,
  onFileUpload,
  onFileDelete,
  onToggleFile,
}) {
  const messagesEndRef = useRef(null)
  const scrollContainerRef = useRef(null)
  // 首次进入 / 切换会话 / 历史加载完成时用瞬时滚动（直接定位到最新消息），
  // 新消息到达用平滑滚动。解决"从其他页面进入对话停在顶部要手动下拉"的问题。
  const instantScrollRef = useRef(true)
  const prevAgentIdRef = useRef(agent?.id)
  const prevMsgLenRef = useRef(0)

  const scrollToBottom = useCallback((instant = false) => {
    const container = scrollContainerRef.current
    if (!container) return
    // 直接操作滚动容器（比 scrollIntoView 更可靠，不依赖末尾元素渲染状态）
    container.scrollTo({
      top: container.scrollHeight,
      behavior: instant ? 'auto' : 'smooth',
    })
  }, [])

  // 切换智能体时：标记瞬时滚动并主动触发（切换会话时 messages 引用可能不变，
  // 单靠 messages useEffect 不会触发，必须在此主动滚一次）
  useEffect(() => {
    if (agent?.id !== prevAgentIdRef.current) {
      prevAgentIdRef.current = agent?.id
      instantScrollRef.current = true
      // 双 rAF 确保新会话消息渲染完成后再瞬时定位
      requestAnimationFrame(() => requestAnimationFrame(() => scrollToBottom(true)))
    }
  }, [agent?.id, scrollToBottom])

  // messages 变化时滚动到底部
  useEffect(() => {
    const curLen = messages.length
    // 历史"空→非空"（首次加载历史 / 进入对话页历史加载完成）也视为瞬时滚动场景，
    // 避免首次进入时 messages 先为 [] 把 instantScrollRef 提前耗尽，历史加载完只能平滑滚动
    const loadedFromEmpty = prevMsgLenRef.current === 0 && curLen > 0
    prevMsgLenRef.current = curLen
    const instant = instantScrollRef.current || loadedFromEmpty
    if (instant) {
      // 瞬时定位：用 rAF 等 DOM 渲染完成后再滚动
      requestAnimationFrame(() => {
        scrollToBottom(true)
        instantScrollRef.current = false
      })
    } else {
      scrollToBottom(false)
    }
  }, [messages, scrollToBottom])

  // 没有选中智能体
  if (!agent) {
    return (
      <div className="flex min-w-[400px] flex-1 items-center justify-center bg-gray-950">
        <div className="text-center">
          <div className="mb-3 text-5xl">💬</div>
          <div className="text-lg font-medium text-gray-400">请选择一个智能体</div>
          <div className="mt-1 text-sm text-gray-600">
            从左侧选择智能体开始对话
          </div>
        </div>
      </div>
    )
  }

  const showWelcome = messages.length === 0
  const name = agent.name || `智能体 ${agent.id}`
  const suggestedQuestions = agent.suggested_questions || []

  return (
    <div className="flex min-w-[400px] flex-1 flex-col bg-gray-950">
      {/* 顶部栏：智能体名称 + 引擎标识 */}
      <div className="flex shrink-0 items-center gap-3 border-b border-gray-800 bg-gray-900/30 px-6 py-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-500/15 text-sm">
          {agent.avatar ? (
            <img src={agent.avatar} alt={name} className="h-full w-full object-cover" />
          ) : (
            <span className="font-semibold text-brand-300">
              {name.charAt(0).toUpperCase()}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-gray-100">{name}</div>
          <div className="text-[10px] text-gray-500">
            {(agent.engine || 'langgraph') === 'hermes' ? 'Hermes 引擎' : 'LangGraph 引擎'}
            {streaming && (
              <span className="ml-2 inline-flex items-center gap-1 text-brand-300">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-400" />
                生成中
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 对话内容区 */}
      <div
        ref={scrollContainerRef}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {showWelcome ? (
          // 欢迎态
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-500/15 text-3xl">
              {agent.avatar ? (
                <img src={agent.avatar} alt={name} className="h-full w-full rounded-2xl object-cover" />
              ) : (
                <span className="font-bold text-brand-300">
                  {name.charAt(0).toUpperCase()}
                </span>
              )}
            </div>
            <h2 className="mb-2 text-2xl font-bold text-gray-100">{name}</h2>
            <p className="max-w-md text-sm leading-relaxed text-gray-500">
              {agent.description ||
                `你可以向我提问任何问题，我会结合上下文为你解答。`}
            </p>
            {/* 引导问题 */}
            {suggestedQuestions.length > 0 && (
              <div className="mt-6 flex max-w-lg flex-col gap-2">
                {suggestedQuestions.slice(0, 4).map((q, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      onInputChange(q)
                    }}
                    className="rounded-lg border border-gray-800 bg-gray-900/40 px-4 py-2.5 text-left text-sm text-gray-400 transition hover:border-brand-500/40 hover:bg-gray-800/40 hover:text-gray-200"
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          // 消息列表
          <div className="mx-auto flex max-w-4xl flex-col gap-4 px-6 py-6">
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                msg={msg}
                onRegenerate={onRegenerate}
                onDelete={() => onDeleteMessage(msg.id)}
                onToggleDelegate={(sid) => onToggleDelegate(msg.id, sid)}
                isLast={msg.id === messages[messages.length - 1]?.id}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* 底部输入区 */}
      <ChatInput
        value={inputText}
        onChange={onInputChange}
        onSend={onSend}
        onStop={onStop}
        streaming={streaming}
        agentName={name}
        uploadedFiles={uploadedFiles}
        selectedFileIds={selectedFileIds}
        uploading={uploading}
        onFileUpload={onFileUpload}
        onFileDelete={onFileDelete}
        onToggleFile={onToggleFile}
      />
    </div>
  )
}

// ============================================================================
// 消息气泡
// ============================================================================
function MessageBubble({ msg, onRegenerate, onDelete, onToggleDelegate, isLast }) {
  const isUser = msg.role === 'user'
  const [copied, setCopied] = useState(false)
  const [thinkingOpen, setThinkingOpen] = useState(true)
  const [processOpen, setProcessOpen] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(msg.content || '').then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className={`group flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`flex max-w-[85%] gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
        {/* 头像 */}
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
            isUser
              ? 'bg-brand-500/20 text-brand-300'
              : 'bg-gray-700 text-gray-300'
          }`}
        >
          {isUser ? '我' : 'AI'}
        </div>

        {/* 消息体 */}
        <div className={`min-w-0 ${isUser ? 'items-end' : 'items-start'}`}>
          {/* 气泡 */}
          <div
            className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
              isUser
                ? 'bg-brand-600 text-white'
                : msg.status === 'error'
                ? 'border border-danger-500/40 bg-danger-500/10 text-danger-200'
                : 'bg-gray-800 text-gray-100'
            }`}
          >
            {/* 流式光标 */}
            {msg.status === 'streaming' && !msg.content ? (
              <span className="inline-flex gap-1">
                <span className="h-2 w-2 animate-bounce rounded-full bg-gray-500 [animation-delay:-0.3s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-gray-500 [animation-delay:-0.15s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-gray-500" />
              </span>
            ) : (
              <div className="break-words">
                {isUser ? (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                ) : msg.status === 'streaming' ? (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                ) : (
                  <MarkdownRenderer content={msg.content} />
                )}
                {msg.status === 'streaming' && (
                  <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-brand-400 align-middle" />
                )}
              </div>
            )}
          </div>

          {/* 思考过程折叠区（仅 AI 消息有 thinking 时显示） */}
          {!isUser && msg.thinking && (
            <div className="mt-1.5">
              <button
                type="button"
                onClick={() => setThinkingOpen((v) => !v)}
                className="flex items-center gap-1 text-[11px] text-gray-500 transition hover:text-gray-400"
              >
                <span className={`inline-block transition-transform ${thinkingOpen ? 'rotate-90' : ''}`}>▶</span>
                <span>🧠 思考过程</span>
                {msg.status === 'streaming' && (
                  <span className="text-brand-400">(思考中…)</span>
                )}
              </button>
              {thinkingOpen && (
                <div className="mt-1 max-h-60 overflow-y-auto rounded-lg border border-gray-800 bg-gray-900/60 p-2.5 text-[12px] leading-relaxed text-gray-400 whitespace-pre-wrap break-words">
                  {msg.thinking}
                </div>
              )}
            </div>
          )}

          {/* 执行过程日志（状态/日志消息，仅 AI 消息） */}
          {!isUser && msg.statusMsgs && msg.statusMsgs.length > 0 && (
            <div className="mt-1.5">
              <button
                type="button"
                onClick={() => setProcessOpen((v) => !v)}
                className="flex items-center gap-1 text-[11px] text-gray-500 transition hover:text-gray-400"
              >
                <span className={`inline-block transition-transform ${processOpen ? 'rotate-90' : ''}`}>▶</span>
                <span>📜 执行过程</span>
                <span className="text-gray-600">({msg.statusMsgs.length})</span>
              </button>
              {processOpen && (
                <div className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-gray-800 bg-gray-900/60 p-2.5 text-[12px] leading-relaxed text-gray-400 whitespace-pre-wrap break-words">
                  {msg.statusMsgs.map((s, i) => (
                    <div key={i} className="py-0.5">{s}</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 工具调用区（仅 AI 消息，可折叠查看结果） */}
          {!isUser && msg.toolCalls && msg.toolCalls.length > 0 && (
            <div className="mt-1.5 flex flex-col gap-1">
              {msg.toolCalls.map((tc, idx) => (
                <ToolCallItem key={tc.call_id || idx} tc={tc} />
              ))}
            </div>
          )}

          {/* 子代理委派事件折叠区 */}
          {!isUser && msg.delegateGroups && msg.delegateGroups.length > 0 && (
            <div className="mt-1.5 flex flex-col gap-1">
              {msg.delegateGroups.map((g) => (
                <DelegateGroupMini
                  key={g.subagent_id}
                  group={g}
                  onToggle={() => onToggleDelegate(g.subagent_id)}
                />
              ))}
            </div>
          )}

          {/* 操作按钮 */}
          {!isUser && msg.status !== 'streaming' && (
            <div className="mt-1 flex items-center gap-2 opacity-0 transition group-hover:opacity-100">
              <button
                type="button"
                onClick={handleCopy}
                className="text-[10px] text-gray-600 hover:text-gray-400"
                title="复制"
              >
                {copied ? '✓ 已复制' : '复制'}
              </button>
              {isLast && msg.status === 'done' && (
                <button
                  type="button"
                  onClick={onRegenerate}
                  className="text-[10px] text-gray-600 hover:text-gray-400"
                  title="重新生成"
                >
                  重新生成
                </button>
              )}
              <button
                type="button"
                onClick={onDelete}
                className="text-[10px] text-gray-600 hover:text-danger-400"
                title="删除"
              >
                删除
              </button>
            </div>
          )}

          {/* 时间戳 */}
          <div className={`mt-0.5 text-[10px] text-gray-700 ${isUser ? 'text-right' : 'text-left'}`}>
            {new Date(msg.timestamp).toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

// 工具调用卡片：可折叠展示工具名、状态、执行结果
// 透明化工具调用与知识库检索过程（search_knowledge_base 的检索片段也会在此展示）
function ToolCallItem({ tc }) {
  const [open, setOpen] = useState(false)
  const running = tc.status === 'running'
  const isError = !!(tc.message && tc.message.includes('错误'))
  // 序列化结果
  let resultStr = ''
  if (tc.result !== null && tc.result !== undefined) {
    if (typeof tc.result === 'string') {
      resultStr = tc.result
    } else {
      try {
        resultStr = JSON.stringify(tc.result, null, 2)
      } catch {
        resultStr = String(tc.result)
      }
    }
  }
  return (
    <div className="rounded-md border border-gray-800 bg-gray-900/60 text-[11px]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-gray-400 transition hover:bg-gray-800/40"
      >
        <span className="shrink-0">{running ? '⏳' : isError ? '⚠️' : '✓'}</span>
        <span className="shrink-0 font-mono text-purple-400">{tc.name}</span>
        {tc.message && (
          <span className="truncate text-gray-600">{tc.message}</span>
        )}
        {resultStr && (
          <span className="ml-auto shrink-0 text-gray-600">
            {open ? '收起' : '详情'}
          </span>
        )}
      </button>
      {open && resultStr && (
        <div className="max-h-48 overflow-y-auto border-t border-gray-800 px-2 py-1.5 font-mono text-[11px] leading-relaxed text-gray-400 whitespace-pre-wrap break-words">
          {resultStr}
        </div>
      )}
    </div>
  )
}

// 子代理委派事件迷你卡片（简化版）
function DelegateGroupMini({ group, onToggle }) {
  const statusIcon = {
    running: '⏳',
    completed: '✓',
    failed: '✗',
  }
  const statusColor = {
    running: 'text-brand-300',
    completed: 'text-emerald-300',
    failed: 'text-danger-300',
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex items-center gap-1.5 rounded border border-purple-800/40 bg-purple-900/10 px-2 py-1 text-[10px] transition hover:bg-purple-900/20"
    >
      <span className="text-[8px] text-gray-600">{group.expanded ? '▼' : '▶'}</span>
      <span className={statusColor[group.status] || 'text-gray-400'}>
        {statusIcon[group.status] || '•'}
      </span>
      <span className="font-mono text-purple-400">{group.subagent_id}</span>
      <span className="text-gray-600">
        ({group.events.length} 事件)
      </span>
      {group.expanded && (
        <span className="ml-1 flex max-w-md flex-col gap-0.5 text-left text-[10px] text-gray-500">
          {group.events
            .filter((e) => e.type !== 'token')
            .slice(-5)
            .map((e, i) => (
              <span key={i}>
                <span className="text-gray-600">
                  {e.type === 'tool_start' ? '🔧' : e.type === 'tool_end' ? '✓' : e.type === 'done' ? '🏁' : '•'}
                </span>{' '}
                {e.tool_name || e.message || e.content || e.type}
              </span>
            ))}
        </span>
      )}
    </button>
  )
}

// ============================================================================
// 底部输入区
// ============================================================================
function ChatInput({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  agentName,
  uploadedFiles = [],
  selectedFileIds = new Set(),
  uploading = false,
  onFileUpload,
  onFileDelete,
  onToggleFile,
}) {
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)
  const [showFileList, setShowFileList] = useState(false)

  // 自适应高度
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, INPUT_MAX_HEIGHT)}px`
  }, [value])

  // 文件选择：实际上传到服务器
  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || [])
    files.forEach((f) => onFileUpload?.(f))
    e.target.value = ''
  }

  // 键盘事件：Enter 发送，Shift+Enter 换行
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!streaming && value.trim()) {
        onSend()
      }
    }
  }

  const handleSendClick = () => {
    onSend()
  }

  // 文件类型图标
  const fileIcon = (type) => {
    const icons = {
      xlsx: '📊', xls: '📊', csv: '📋',
      docx: '📄', pdf: '📕',
      txt: '📝', md: '📝', json: '📝',
    }
    return icons[type] || '📎'
  }

  // 文件大小格式化
  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  const selectedCount = selectedFileIds.size

  return (
    <div className="shrink-0 border-t border-gray-800 bg-gray-900/30 px-6 py-4">
      <div className="mx-auto max-w-4xl">
        {/* 文件列表区（可折叠） */}
        {uploadedFiles.length > 0 && (
          <div className="mb-2 rounded-lg border border-gray-800 bg-gray-900/60">
            <button
              type="button"
              onClick={() => setShowFileList((s) => !s)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] text-gray-400 transition hover:text-gray-200"
            >
              <span className="text-[9px]">{showFileList ? '▼' : '▶'}</span>
              <span>📎 已上传文件 ({uploadedFiles.length})</span>
              {selectedCount > 0 && (
                <span className="rounded bg-brand-500/20 px-1.5 py-0.5 text-[10px] text-brand-300">
                  已选 {selectedCount} 个
                </span>
              )}
              <span className="ml-auto text-[10px] text-gray-600">
                勾选后发送，智能体将自主读取
              </span>
            </button>
            {showFileList && (
              <div className="max-h-40 overflow-y-auto border-t border-gray-800 p-1.5">
                {uploadedFiles.map((f) => {
                  const checked = selectedFileIds.has(f.id)
                  return (
                    <div
                      key={f.id}
                      className={`flex items-center gap-2 rounded px-2 py-1.5 text-xs transition ${
                        checked ? 'bg-brand-500/10' : 'hover:bg-gray-800/50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => onToggleFile?.(f.id)}
                        className="h-3.5 w-3.5 rounded border-gray-600 bg-gray-800 text-brand-500 focus:ring-brand-500"
                      />
                      <span className="shrink-0">{fileIcon(f.file_type)}</span>
                      <span className="min-w-0 flex-1 truncate text-gray-300" title={f.original_name}>
                        {f.original_name}
                      </span>
                      <span className="shrink-0 text-[10px] text-gray-600">{formatSize(f.file_size)}</span>
                      <button
                        type="button"
                        onClick={() => onFileDelete?.(f.id)}
                        className="shrink-0 text-gray-700 hover:text-danger-400"
                        title="删除文件"
                      >
                        ✕
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* 上传中提示 */}
        {uploading && (
          <div className="mb-2 flex items-center gap-2 text-[11px] text-brand-300">
            <span className="h-2 w-2 animate-pulse rounded-full bg-brand-400" />
            正在上传文件…
          </div>
        )}

        {/* 输入行：附件按钮 + textarea + 发送按钮，统一 h-9 高度居中对齐 */}
        <div className="flex items-center gap-2">
          {/* 附件按钮 */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming || uploading}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-gray-700 bg-gray-800 text-gray-500 transition hover:bg-gray-700 hover:text-gray-300 disabled:opacity-50"
            title="上传文件（Excel/Word/PDF 等，不做 RAG）"
          >
            📎
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            accept=".xlsx,.xls,.docx,.pdf,.csv,.txt,.json,.md"
            onChange={handleFileSelect}
          />

          {/* 输入框：py-2 使单行高度 = 8+8+20 = 36px = h-9，与按钮对齐 */}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`和 ${agentName || '智能体'} 对话中…`}
            rows={1}
            className="w-full flex-1 resize-none rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 transition focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            style={{ maxHeight: `${INPUT_MAX_HEIGHT}px`, minHeight: '36px' }}
            disabled={streaming}
          />

          {/* 发送/停止按钮 */}
          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-danger-600 px-4 text-sm font-medium text-white transition hover:bg-danger-500"
            >
              <span className="h-3 w-3 rounded-sm bg-white" />
              停止
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSendClick}
              disabled={!value.trim()}
              className="btn-primary flex h-9 shrink-0 items-center gap-1.5 px-4"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
              发送
            </button>
          )}
        </div>

        {/* 底部提示 */}
        <div className="mt-1.5 flex items-center justify-between text-[10px] text-gray-700">
          <span>Enter 发送 · Shift+Enter 换行</span>
          <span>{value.length} 字</span>
        </div>
      </div>
    </div>
  )
}
