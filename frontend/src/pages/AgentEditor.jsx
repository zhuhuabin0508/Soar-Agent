import { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  agents as agentsApi,
  llmConfigs as llmApi,
  tools as toolsApi,
  knowledgeBases as kbApi,
  skills as skillsApi,
} from '../api/client'
import {
  Section,
  TextInput,
  NumberInput,
  SelectInput,
  TextArea,
  CheckboxGroup,
} from '../components/property/FormControls'
import { inputCls, textareaCls } from '../components/property/FormControls'
import MiddlewareConfig from '../components/MiddlewareConfig'
import ToolSearchStatus from '../components/ToolSearchStatus'
import InfoTip from '../components/InfoTip'
import { CATEGORY_META, UNCATEGORIZED, groupToolsByCategory } from '../constants/toolCategories'
import { useUnsavedChanges } from '../hooks/useUnsavedChanges'

// 语气风格选项
const TONE_STYLES = [
  { value: 'professional', label: '专业严谨' },
  { value: 'humorous', label: '幽默风趣' },
  { value: 'casual', label: '轻松随意' },
  { value: 'formal', label: '正式礼貌' },
  { value: 'concise', label: '简洁明了' },
]

// 可折叠卡片
function Card({ title, icon, children, defaultOpen = true, hint, extra }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/40">
      <div className="flex w-full items-center justify-between px-4 py-2.5">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex flex-1 items-center gap-2 text-left transition hover:text-brand-300"
        >
          <span className="flex items-center gap-2 text-sm font-semibold text-gray-200">
            <span>{icon}</span>
            {title}
            {hint && <InfoTip text={hint} />}
          </span>
          <span className="text-gray-600">{open ? '▼' : '▶'}</span>
        </button>
        {extra && <div className="shrink-0">{extra}</div>}
      </div>
      {open && <div className="flex flex-col gap-3 border-t border-gray-800 p-4">{children}</div>}
    </div>
  )
}

// 智能体编辑器：左侧6模块配置 + 右侧调试预览
function AgentEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const isEdit = !!id

  const [form, setForm] = useState({
    name: '',
    description: '',
    avatar: '',
    greeting: '',
    suggested_questions: [],
    model_config_id: '',
    system_prompt: '',
    temperature: 0.7,
    max_tokens: 1024,
    context_turns: 10,
    enabled_tools: [],
    enabled_kbs: [],
    enabled_skills: [],
    max_iterations: 5,
    enable_memory: false,
    tone_style: 'professional',
    variables: {},
    tool_configs: {},
  })
  const [llmOptions, setLlmOptions] = useState([])
  const [toolOptions, setToolOptions] = useState([])
  const [kbOptions, setKbOptions] = useState([])
  const [skillOptions, setSkillOptions] = useState([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [dirty, setDirty] = useState(false)

  // 变量编辑器
  const [varRows, setVarRows] = useState([{ key: '', value: '' }])
  // 标准模式 / 开发者模式
  const [devMode, setDevMode] = useState(false)
  // 展开的工具配置项
  const [expandedTool, setExpandedTool] = useState(null)

  // 按分类分组的工具列表（标准模式 + 开发者模式共用）
  const groupedTools = useMemo(() => groupToolsByCategory(toolOptions), [toolOptions])

  // ===== 调试预览状态 =====
  const [testInput, setTestInput] = useState('')
  const [testing, setTesting] = useState(false)
  // testResult 结构因 engine 而异：
  //   langgraph: { mode:'agent', streaming, decision, target_ip, reason, duration, messages, logs }
  //   hermes:    { mode:'hermes', streaming, reply, toolCalls:[], delegateGroups:[], logs, statusMsgs:[] }
  //   delegateGroups 项: { subagent_id, task_index, status:'running'|'completed'|'failed', goal, events:[], expanded }
  const [testResult, setTestResult] = useState(null)
  const [testError, setTestError] = useState('')
  const [showMessages, setShowMessages] = useState(true)
  const [showLogs, setShowLogs] = useState(false)
  const [showToolCalls, setShowToolCalls] = useState(true)
  const [showDelegates, setShowDelegates] = useState(true)
  // 流式输出文本（requestAnimationFrame 节流，避免每个 token 都触发重渲染）
  const [streamText, setStreamText] = useState('')
  const rafRef = useRef(null)
  const pendingTextRef = useRef('')
  const scheduleStreamUpdate = useCallback((text) => {
    pendingTextRef.current = text
    if (rafRef.current) return // 已有调度中的帧，复用
    rafRef.current = requestAnimationFrame(() => {
      setStreamText(pendingTextRef.current)
      rafRef.current = null
    })
  }, [])

  const bypassGuard = useUnsavedChanges(dirty)

  useEffect(() => {
    let alive = true
    ;(async () => {
      setLoading(true)
      try {
        const [llms, tls, kbs, sks] = await Promise.all([
          llmApi.list(),
          toolsApi.list(),
          kbApi.list(),
          skillsApi.list({ enabled: true }),
        ])
        if (!alive) return
        setLlmOptions(Array.isArray(llms) ? llms : [])
        setToolOptions(
          (Array.isArray(tls) ? tls : []).map((t) => ({
            value: t.name || `工具 ${t.id}`,
            label: `${t.name || `工具 ${t.id}`}${t.enabled === false ? '（已禁用）' : ''}`,
            category: t.category || '',
          }))
        )
        setKbOptions(
          (Array.isArray(kbs) ? kbs : []).map((k) => ({
            value: String(k.id),
            label: k.name || `知识库 ${k.id}`,
          }))
        )
        // 仅展示启用中的技能（禁用的技能不会注入 prompt，不应被勾选）
        setSkillOptions(
          (Array.isArray(sks) ? sks : []).map((s) => ({
            value: String(s.id),
            label: `${s.name || `技能 ${s.id}`}${s.category ? `（${s.category}）` : ''}`,
          }))
        )
        if (isEdit) {
          const agent = await agentsApi.list().then((arr) =>
            (Array.isArray(arr) ? arr : []).find((x) => String(x.id) === String(id))
          )
          if (!alive) return
          if (agent) {
            setForm({
              id: agent.id,
              name: agent.name || '',
              description: agent.description || '',
              avatar: agent.avatar || '',
              greeting: agent.greeting || '',
              suggested_questions: agent.suggested_questions || [],
              model_config_id: agent.model_config_id ?? '',
              system_prompt: agent.system_prompt || '',
              temperature: agent.temperature ?? 0.7,
              max_tokens: agent.max_tokens ?? 1024,
              context_turns: agent.context_turns ?? 10,
              enabled_tools: (agent.enabled_tools || []).map(String),
              enabled_kbs: (agent.enabled_kbs || []).map(String),
              enabled_skills: (agent.enabled_skills || []).map(String),
              max_iterations: agent.max_iterations ?? 5,
              enable_memory: agent.enable_memory ?? false,
              tone_style: agent.tone_style || 'professional',
              variables: agent.variables || {},
              tool_configs: agent.tool_configs || {},
              engine: agent.engine || 'langgraph',
            })
            // 同步变量编辑器行
            const varObj = agent.variables || {}
            const rows = Object.keys(varObj).length > 0
              ? Object.entries(varObj).map(([k, v]) => ({ key: k, value: String(v) }))
              : [{ key: '', value: '' }]
            setVarRows(rows)
          } else {
            setError('未找到该智能体')
          }
        }
      } catch (err) {
        if (!alive) return
        setError(err.message || '加载失败')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [id, isEdit])

  const setField = (field) => (value) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    setDirty(true)
  }

  // 变量编辑器：更新某行
  const updateVarRow = (idx, key, value) => {
    const next = [...varRows]
    next[idx] = { key, value }
    setVarRows(next)
    // 同步到 form.variables
    const varObj = {}
    next.forEach((r) => { if (r.key.trim()) varObj[r.key.trim()] = r.value })
    setForm((prev) => ({ ...prev, variables: varObj }))
    setDirty(true)
  }

  // 保存
  const handleSave = async (silent = false) => {
    if (!form.name.trim()) {
      if (!silent) window.alert('请填写智能体名称')
      return null
    }
    setSaving(true)
    try {
      const body = {
        name: form.name,
        description: form.description,
        avatar: form.avatar || null,
        greeting: form.greeting || null,
        suggested_questions: form.suggested_questions,
        model_config_id: form.model_config_id || null,
        system_prompt: form.system_prompt,
        temperature: Number(form.temperature),
        max_tokens: Number(form.max_tokens),
        context_turns: Number(form.context_turns),
        enabled_tools: form.enabled_tools,
        enabled_kbs: form.enabled_kbs.map((v) => Number(v)),
        enabled_skills: form.enabled_skills.map((v) => Number(v)),
        max_iterations: Number(form.max_iterations),
        enable_memory: form.enable_memory,
        tone_style: form.tone_style,
        variables: form.variables,
        tool_configs: form.tool_configs,
        engine: form.engine || 'langgraph',
      }
      let result
      if (isEdit) {
        result = await agentsApi.update(id, body)
      } else {
        result = await agentsApi.create(body)
      }
      setDirty(false)
      bypassGuard()
      if (!silent) navigate('/agents')
      return result
    } catch (err) {
      if (!silent) window.alert(`保存失败：${err.message || err}`)
      return null
    } finally {
      setSaving(false)
    }
  }

  // ===== 调试运行（流式） =====
  // 按 engine 分支：hermes 走 /chat（支持 delegate 嵌套事件），langgraph 走 /test/stream
  const handleTest = async () => {
    let agentId = id
    if (!agentId) {
      const saved = await handleSave(true)
      if (saved && saved.id) {
        agentId = saved.id
        navigate(`/agents/${saved.id}/edit`, { replace: true })
      } else {
        return
      }
    }
    if (dirty) {
      const saved = await handleSave(true)
      if (!saved) return
    }
    setTesting(true)
    setTestError('')
    setTestResult(null)
    setStreamText('')

    const isHermes = form.engine === 'hermes'
    try {
      const resp = isHermes
        ? await agentsApi.chatStream(agentId, testInput || '你好')
        : await agentsApi.testStream(agentId, testInput || '你好')
      if (!resp.ok) {
        const errText = await resp.text()
        throw new Error(errText || `HTTP ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      if (isHermes) {
        // ===== Hermes 引擎：解析 start/token/tool_start/tool_end/delegate/log/done/error =====
        let fullText = ''
        let toolCalls = []
        let delegateGroups = []
        let logs = []
        let statusMsgs = []

        // 初始化 Hermes 结果结构
        setTestResult({
          mode: 'hermes',
          streaming: true,
          reply: '',
          toolCalls: [],
          delegateGroups: [],
          logs: [],
          statusMsgs: [],
        })

        const flush = (patch) => {
          setTestResult((prev) => prev ? { ...prev, ...patch } : prev)
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
              switch (data.type) {
                case 'start':
                  // 会话开始
                  break
                case 'thinking':
                  setTestResult((prev) => prev ? { ...prev, thinking: (prev.thinking || '') + (data.content || '') } : prev)
                  break
                case 'token':
                  fullText += data.content || ''
                  scheduleStreamUpdate(fullText)
                  flush({ reply: fullText, streaming: true })
                  break
                case 'status':
                  statusMsgs.push(data.message || '')
                  flush({ statusMsgs: [...statusMsgs] })
                  break
                case 'tool_start': {
                  // 工具开始执行：加入 toolCalls（状态 running）
                  toolCalls.push({
                    name: data.tool_name || '',
                    call_id: data.tool_call_id || '',
                    status: 'running',
                    message: data.message || '',
                    result: null,
                  })
                  flush({ toolCalls: [...toolCalls] })
                  break
                }
                case 'tool_end': {
                  // 工具执行结束：更新对应 toolCalls 项
                  const idx = toolCalls.findIndex(
                    (tc) => tc.call_id === data.tool_call_id && tc.status === 'running'
                  )
                  if (idx >= 0) {
                    toolCalls[idx] = {
                      ...toolCalls[idx],
                      status: 'done',
                      result: data.result,
                      message: data.message || toolCalls[idx].message,
                    }
                  } else {
                    // 未找到对应的 tool_start，直接追加
                    toolCalls.push({
                      name: data.tool_name || '',
                      call_id: data.tool_call_id || '',
                      status: 'done',
                      message: data.message || '',
                      result: data.result,
                    })
                  }
                  flush({ toolCalls: [...toolCalls] })
                  break
                }
                case 'delegate': {
                  // 子代理委派嵌套事件：按 subagent_id 分组
                  // data.result = { subagent_id, task_index, event: { type, content, message, tool_name, ... } }
                  const info = data.result || {}
                  const sid = info.subagent_id || 'unknown'
                  const tidx = info.task_index ?? 0
                  const evt = info.event || {}
                  // 查找已有分组
                  let gIdx = delegateGroups.findIndex((g) => g.subagent_id === sid)
                  if (gIdx < 0) {
                    // 新建分组
                    delegateGroups.push({
                      subagent_id: sid,
                      task_index: tidx,
                      status: 'running',
                      goal: '',
                      events: [],
                      expanded: true,
                    })
                    gIdx = delegateGroups.length - 1
                  }
                  // 从 start 事件提取 goal
                  if (evt.type === 'start' && evt.message) {
                    delegateGroups[gIdx].goal = evt.message
                  }
                  // 更新分组状态
                  if (evt.type === 'done') {
                    delegateGroups[gIdx].status = 'completed'
                  } else if (evt.type === 'error') {
                    delegateGroups[gIdx].status = 'failed'
                  }
                  // 追加嵌套事件
                  delegateGroups[gIdx].events.push({
                    type: evt.type || 'unknown',
                    content: evt.content || '',
                    message: evt.message || '',
                    tool_name: evt.tool_name || '',
                    tool_call_id: evt.tool_call_id || '',
                    result: evt.result ?? null,
                  })
                  flush({ delegateGroups: [...delegateGroups] })
                  break
                }
                case 'log':
                  logs.push(data.log)
                  flush({ logs: [...logs] })
                  break
                case 'done':
                  if (data.content) {
                    fullText = data.content
                    scheduleStreamUpdate(fullText)
                  }
                  flush({ reply: fullText, streaming: false })
                  break
                case 'error':
                  setTestError(data.message || '测试失败')
                  flush({ streaming: false })
                  break
                default:
                  // 忽略未知事件类型（skill_interrupt 等暂不专门处理）
                  break
              }
            } catch {
              // 忽略 JSON 解析错误
            }
          }
        }
      } else {
        // ===== LangGraph 引擎：原有逻辑 =====
        let fullText = ''
        let logs = []
        let messages = []

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          // 按 SSE 格式解析（data: {...}\n\n）
          const lines = buffer.split('\n')
          buffer = lines.pop() || '' // 保留最后不完整的行

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const data = JSON.parse(line.slice(6))
              if (data.type === 'start') {
                setTestResult({ mode: data.mode, streaming: true, reply: '', messages: [], logs: [] })
              } else if (data.type === 'token') {
                fullText += data.content
                scheduleStreamUpdate(fullText)
                setTestResult((prev) => prev ? { ...prev, reply: fullText, streaming: true } : prev)
              } else if (data.type === 'status') {
                logs.push({ level: 'info', message: data.message })
                setTestResult((prev) => prev ? { ...prev, logs: [...logs] } : prev)
              } else if (data.type === 'log') {
                logs.push(data.log)
                setTestResult((prev) => prev ? { ...prev, logs: [...logs] } : prev)
              } else if (data.type === 'message') {
                messages.push(data.message)
                setTestResult((prev) => prev ? { ...prev, messages: [...messages] } : prev)
              } else if (data.type === 'done') {
                if (data.reply !== undefined) {
                  setTestResult((prev) => prev ? { ...prev, reply: data.reply, streaming: false } : { reply: data.reply, streaming: false })
                } else if (data.result) {
                  const r = data.result
                  setTestResult({
                    streaming: false,
                    decision: r.decision,
                    target_ip: r.target_ip,
                    reason: r.reason,
                    duration: r.duration,
                    messages: r.messages || [],
                    logs: r.logs || [],
                  })
                }
              } else if (data.type === 'error') {
                setTestError(data.message || '测试失败')
              }
            } catch {
              // 忽略 JSON 解析错误
            }
          }
        }
      }
    } catch (err) {
      setTestError(err.message || '测试失败')
    } finally {
      setTesting(false)
    }
  }

  const fillExample = () => {
    setTestInput(JSON.stringify(
      { alert_type: 'brute_force', source_ip: '192.168.1.100', target_ip: '10.0.0.5', port: 22, count: 50 },
      null, 2
    ))
  }

  // 切换 delegate 分组的展开/折叠状态（按 subagent_id 查找）
  const toggleDelegateGroup = (subagentId) => {
    setTestResult((prev) => {
      if (!prev || !prev.delegateGroups) return prev
      return {
        ...prev,
        delegateGroups: prev.delegateGroups.map((g) =>
          g.subagent_id === subagentId ? { ...g, expanded: !g.expanded } : g
        ),
      }
    })
  }

  // 全部展开/折叠 delegate 分组
  const toggleAllDelegates = (expanded) => {
    setTestResult((prev) => {
      if (!prev || !prev.delegateGroups) return prev
      return {
        ...prev,
        delegateGroups: prev.delegateGroups.map((g) => ({ ...g, expanded })),
      }
    })
  }

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-gray-950 text-sm text-gray-500">
        加载中...
      </div>
    )
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex shrink-0 items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <button type="button" onClick={() => navigate('/agents')} className="btn-secondary btn-sm">
            ← 返回列表
          </button>
          <h1 className="text-xl font-semibold">{isEdit ? '编辑智能体' : '新建智能体'}</h1>
        </div>
        <button type="button" onClick={() => handleSave(false)} disabled={saving} className="btn-primary">
          {saving ? '保存中…' : '保存'}
        </button>
      </header>

      {/* 左右分栏：左侧6模块配置 + 右侧调试预览 */}
      <div className="flex min-h-0 flex-1">
        {/* ===== 左侧：6模块配置 ===== */}
        <div className="w-1/2 min-w-0 overflow-y-auto border-r border-gray-800 p-6">
          {error && (
            <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          <div className="flex flex-col gap-4">
            {/* 模块一：基础信息与形象 */}
            <Card title="基础信息与形象" icon="👤">
              <TextInput label="智能体名称" value={form.name} onChange={setField('name')} placeholder="如：告警研判智能体" />
              <TextInput label="头像 URL" value={form.avatar} onChange={setField('avatar')} placeholder="https://example.com/avatar.png（可选）" />
              <TextInput label="简介" value={form.description} onChange={setField('description')} placeholder="对外展示的功能描述" />
              <TextArea label="开场白" value={form.greeting} onChange={setField('greeting')} rows={3} placeholder="用户与 Agent 开启对话时自动发送的第一条消息（支持 Markdown）" />
              <div>
                <div className="mb-1 text-xs font-medium text-gray-400">开场引导问题</div>
                <SuggestedQuestionsEditor
                  value={form.suggested_questions}
                  onChange={setField('suggested_questions')}
                />
              </div>
            </Card>

            {/* 模块二：核心人设与提示词 */}
            <Card title="核心人设与提示词" icon="🧠">
              <TextArea
                label="System Prompt"
                value={form.system_prompt}
                onChange={setField('system_prompt')}
                rows={6}
                placeholder="你是一名 SOC 高级安全专家。接收到告警后，请利用工具查询源 IP 的白名单状态、资产归属、网段和威胁情报……"
              />
              <div>
                <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-gray-400">
                  变量配置
                  <InfoTip text={<>在提示词中用 <code className="rounded bg-gray-800 px-1 text-brand-300">{'{{key}}'}</code> 引用变量值</>} />
                </div>
                {varRows.map((row, idx) => (
                  <div key={idx} className="mb-1 flex items-center gap-1.5">
                    <input
                      className={`${inputCls} flex-1`}
                      placeholder="变量名"
                      value={row.key}
                      onChange={(e) => updateVarRow(idx, e.target.value, row.value)}
                    />
                    <input
                      className={`${inputCls} flex-1`}
                      placeholder="变量值"
                      value={row.value}
                      onChange={(e) => updateVarRow(idx, row.key, e.target.value)}
                    />
                    {varRows.length > 1 && (
                      <button
                        type="button"
                        onClick={() => {
                          const next = varRows.filter((_, i) => i !== idx)
                          setVarRows(next)
                          const varObj = {}
                          next.forEach((r) => { if (r.key.trim()) varObj[r.key.trim()] = r.value })
                          setForm((prev) => ({ ...prev, variables: varObj }))
                          setDirty(true)
                        }}
                        className="shrink-0 rounded border border-gray-700 px-1.5 py-1 text-[11px] text-gray-500 hover:text-danger-400"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => setVarRows([...varRows, { key: '', value: '' }])}
                  className="text-[11px] text-brand-400 hover:text-brand-300"
                >
                  + 添加变量
                </button>
              </div>
            </Card>

            {/* 模块三：模型与参数设置 */}
            <Card title="模型与参数设置" icon="⚙️">
              <SelectInput
                label="推理引擎"
                value={form.engine || 'langgraph'}
                onChange={setField('engine')}
                options={[
                  { value: 'hermes', label: 'Hermes 引擎（支持工具调用 / 委派 / 技能触发，推荐）' },
                  { value: 'langgraph', label: 'LangGraph 引擎（兼容模式，基础对话 + 工具）' },
                ]}
              />
              <SelectInput
                label="大语言模型 LLM"
                value={form.model_config_id}
                onChange={setField('model_config_id')}
                options={[
                  { value: '', label: '请选择…' },
                  ...llmOptions.map((l) => ({
                    value: String(l.id),
                    label: `${l.name || `#${l.id}`}（${l.provider || '-'} / ${l.model_name || '-'}）`,
                  })),
                ]}
              />
              <div className="grid grid-cols-3 gap-2">
                <NumberInput label="温度" value={form.temperature} onChange={setField('temperature')} min={0} max={2} step={0.1} hint="0=确定，2=发散" />
                <NumberInput label="Max Tokens" value={form.max_tokens} onChange={setField('max_tokens')} min={1} max={8192} />
                <NumberInput label="上下文轮数" value={form.context_turns} onChange={setField('context_turns')} min={1} max={50} hint="记忆对话轮数" />
              </div>
            </Card>

            {/* 模块四：能力扩展：知识与工具 */}
            <Card
              title="能力扩展：知识与工具"
              icon="🔧"
              hint="（不勾选则不启用任何工具/知识库）"
              extra={
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-gray-500">标准</span>
                  <button
                    type="button"
                    onClick={() => setDevMode((d) => !d)}
                    className={`relative h-4 w-8 rounded-full transition ${devMode ? 'bg-brand-500' : 'bg-gray-700'}`}
                  >
                    <span
                      className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${devMode ? 'left-4' : 'left-0.5'}`}
                    />
                  </button>
                  <span className="text-[10px] text-gray-500">开发者</span>
                </div>
              }
            >
              <div>
                <div className="mb-1 text-xs font-medium text-gray-400">知识库挂载</div>
                <CheckboxGroup
                  value={form.enabled_kbs}
                  onChange={setField('enabled_kbs')}
                  options={kbOptions}
                  columns={2}
                />
              </div>
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-gray-400">
                  插件 / 工具调用
                  <InfoTip text="按类型分组展示，勾选后智能体可调用该工具。不勾选则不启用任何工具。" />
                </div>
                {toolOptions.length === 0 ? (
                  <p className="text-[11px] text-gray-600">暂无可用工具</p>
                ) : !devMode ? (
                  /* 标准模式：按分类分组勾选 */
                  <div className="flex flex-col gap-3">
                    {groupedTools.map((grp) => (
                      <div key={grp.category}>
                        <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-gray-500">
                          <span>{grp.meta.icon}</span>
                          <span>{grp.meta.label}</span>
                          <span className="text-gray-700">({grp.tools.length})</span>
                        </div>
                        <CheckboxGroup
                          value={form.enabled_tools}
                          onChange={setField('enabled_tools')}
                          options={grp.tools}
                          columns={2}
                        />
                      </div>
                    ))}
                  </div>
                ) : (
                  /* 开发者模式：按分类分组的增强工具配置面板 */
                  <div className="flex flex-col gap-3">
                    {groupedTools.map((grp) => (
                      <div key={grp.category}>
                        <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-gray-500">
                          <span>{grp.meta.icon}</span>
                          <span>{grp.meta.label}</span>
                          <span className="text-gray-700">({grp.tools.length})</span>
                        </div>
                        <div className="flex flex-col gap-1.5">
                          {grp.tools.map((tool) => {
                            const enabled = form.enabled_tools.includes(tool.value)
                            const cfg = form.tool_configs[tool.value] || {}
                            const isExpanded = expandedTool === tool.value
                            const isSensitive = /send|email|delete|block|ban|exec|shutdown|reboot/i.test(tool.value)
                            return (
                              <div key={tool.value} className={`rounded-md border ${enabled ? 'border-gray-700' : 'border-gray-800'} ${isSensitive && enabled ? 'bg-danger-500/5' : 'bg-gray-800/30'}`}>
                                <div className="flex items-center gap-2 px-2 py-1.5">
                                  <input
                                    type="checkbox"
                                    checked={enabled}
                                    onChange={(e) => {
                                      const next = e.target.checked
                                        ? [...form.enabled_tools, tool.value]
                                        : form.enabled_tools.filter((t) => t !== tool.value)
                                      setField('enabled_tools')(next)
                                      if (!next) setExpandedTool(null)
                                    }}
                                    className="h-4 w-4 accent-brand-500"
                                  />
                                  <span className="flex-1 text-xs text-gray-300">{tool.label}</span>
                                  {isSensitive && enabled && (
                                    <span className="rounded bg-danger-500/20 px-1.5 py-0.5 text-[10px] font-medium text-danger-300">
                                      ⚠ 敏感操作
                                    </span>
                                  )}
                                  {enabled && (
                                    <button
                                      type="button"
                                      onClick={() => setExpandedTool(isExpanded ? null : tool.value)}
                                      className="text-[10px] text-brand-400 hover:text-brand-300"
                                    >
                                      {isExpanded ? '收起' : '配置'}
                                    </button>
                                  )}
                                </div>
                                {enabled && isExpanded && (
                                  <div className="grid grid-cols-3 gap-2 border-t border-gray-800 p-2">
                                    <label>
                                      <div className="mb-0.5 text-[10px] text-gray-500">超时（秒）</div>
                                      <input
                                        type="number"
                                        className={inputCls}
                                        value={cfg.timeout ?? 10}
                                        onChange={(e) => {
                                          const next = { ...form.tool_configs }
                                          next[tool.value] = { ...next[tool.value], timeout: Number(e.target.value) }
                                          setField('tool_configs')(next)
                                        }}
                                        min={1}
                                        max={120}
                                      />
                                    </label>
                                    <label>
                                      <div className="mb-0.5 text-[10px] text-gray-500">失败重试</div>
                                      <input
                                        type="number"
                                        className={inputCls}
                                        value={cfg.retry ?? 0}
                                        onChange={(e) => {
                                          const next = { ...form.tool_configs }
                                          next[tool.value] = { ...next[tool.value], retry: Number(e.target.value) }
                                          setField('tool_configs')(next)
                                        }}
                                        min={0}
                                        max={5}
                                      />
                                    </label>
                                    <label className="flex flex-col">
                                      <div className="mb-0.5 text-[10px] text-gray-500">执行模式</div>
                                      <select
                                        className={inputCls}
                                        value={cfg.require_confirm ? 'confirm' : 'auto'}
                                        onChange={(e) => {
                                          const next = { ...form.tool_configs }
                                          next[tool.value] = { ...next[tool.value], require_confirm: e.target.value === 'confirm' }
                                          setField('tool_configs')(next)
                                        }}
                                      >
                                        <option value="auto">自动调用</option>
                                        <option value="confirm">需用户确认</option>
                                      </select>
                                    </label>
                                    {cfg.require_confirm && (
                                      <div className="col-span-3 rounded bg-amber-500/10 px-2 py-1 text-[10px] text-amber-300">
                                        ⚠ 此工具标记为"需用户确认"，Agent 调用前会暂停等待确认
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Card>

            {/* 模块四补：技能注入（纯文本指令注入 system prompt） */}
            <Card
              title="技能注入"
              icon="🎯"
              hint="选中的技能正文会拼接到 system prompt 末尾，持续塑造 AI 行为"
            >
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-gray-400">
                    启用技能
                    <InfoTip text={<>技能正文支持 <code className="rounded bg-gray-800 px-1 text-brand-300">{'{{key}}'}</code> 引用下方「变量」中配置的值；按优先级降序注入，禁用或删除的技能会自动从 prompt 移除。</>} />
                  </span>
                  <span className="text-[10px] text-gray-600">
                    已选 {form.enabled_skills.length} / {skillOptions.length} 个
                  </span>
                </div>
                {skillOptions.length === 0 ? (
                  <p className="rounded-md border border-dashed border-gray-800 px-3 py-4 text-center text-[11px] text-gray-600">
                    暂无可用技能，请先到「技能」页面创建并启用
                  </p>
                ) : (
                  <CheckboxGroup
                    value={form.enabled_skills}
                    onChange={setField('enabled_skills')}
                    options={skillOptions}
                    columns={2}
                  />
                )}
              </div>
            </Card>

            {/* 模块五：记忆与高级机制 */}
            <Card title="记忆与高级机制" icon="🧩" defaultOpen={false}>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.enable_memory}
                  onChange={(e) => setField('enable_memory')(e.target.checked)}
                  className="h-4 w-4 accent-brand-500"
                />
                <span className="text-sm text-gray-300">长期记忆（自动提取对话关键信息保存）</span>
              </label>
              <SelectInput
                label="语气风格"
                value={form.tone_style}
                onChange={setField('tone_style')}
                options={TONE_STYLES}
              />
              <NumberInput
                label="最大迭代次数"
                value={form.max_iterations}
                onChange={setField('max_iterations')}
                min={1}
                max={20}
                hint="工具调用循环上限"
              />
            </Card>

            {/* 模块六：中间件与安全配置（guardrails / verification / middlewares） */}
            <Card
              title="中间件与安全配置"
              icon="🛡️"
              defaultOpen={false}
              hint="Hermes 引擎专属：工具循环守卫、写操作证据验证、中间件链"
            >
              <MiddlewareConfig
                value={form.tool_configs}
                onChange={setField('tool_configs')}
              />
              <div className="rounded-md border border-gray-800 bg-gray-900/40 p-2 font-mono text-[10px] text-gray-500">
                <div className="mb-1 text-gray-400">当前 tool_configs（只读预览）：</div>
                <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-all">
                  {JSON.stringify(form.tool_configs, null, 2) || '{}'}
                </pre>
              </div>
            </Card>

            {/* 模块七：工具搜索状态（tool_search 渐进式披露） */}
            <Card
              title="工具搜索状态"
              icon="🔍"
              defaultOpen={false}
              hint="Hermes 引擎专属：可延迟工具按需检索，节省上下文（auto 模式按阈值门控）"
            >
              <ToolSearchStatus
                agentId={form.id}
                value={form.tool_configs}
                onChange={setField('tool_configs')}
              />
            </Card>
          </div>
        </div>

        {/* ===== 右侧：调试预览面板 ===== */}
        <div className="flex w-1/2 min-w-0 flex-col overflow-hidden">
          <div className="flex shrink-0 items-center justify-between border-b border-gray-800 bg-gray-900/40 px-4 py-2.5">
            <div className="flex items-center gap-2 text-sm font-medium text-gray-200">
              <span>🧪</span>
              <span>调试与预览</span>
            </div>
            <button type="button" onClick={fillExample} className="rounded border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 transition hover:bg-gray-800 hover:text-gray-200">
              填入示例
            </button>
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
            {/* 测试输入区 */}
            <div className="shrink-0">
              <label className="mb-1 block text-xs font-medium text-gray-400">
                测试输入（JSON 或纯文本）
              </label>
              <textarea
                value={testInput}
                onChange={(e) => setTestInput(e.target.value)}
                rows={6}
                placeholder='{"alert_type": "brute_force", "source_ip": "192.168.1.100", ...}'
                className="w-full resize-y rounded-md border border-gray-700 bg-gray-900 px-3 py-2 font-mono text-xs text-gray-200 placeholder:text-gray-600 focus:border-brand-500 focus:outline-none"
              />
              <div className="mt-2 flex items-center justify-between">
                <span className="text-[11px] text-gray-600">
                  {!isEdit && '新建模式：调试时将自动保存'}
                  {isEdit && dirty && '有未保存的修改，调试时将自动保存'}
                  {isEdit && !dirty && '可直接调试'}
                </span>
                <button
                  type="button"
                  onClick={handleTest}
                  disabled={testing}
                  className="rounded-md border border-brand-600 bg-brand-600/20 px-4 py-1.5 text-sm font-medium text-brand-300 transition hover:bg-brand-600/40 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {testing ? '运行中…' : '▶ 调试运行'}
                </button>
              </div>
            </div>

            {testError && (
              <div className="shrink-0 rounded-md border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-red-300">
                ❌ {testError}
              </div>
            )}

            {testing && !testResult && (
              <div className="flex shrink-0 items-center gap-2 rounded-md border border-brand-500/30 bg-brand-500/10 px-3 py-2 text-sm text-brand-300">
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" />
                  <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                </svg>
                智能体推理中，请稍候…
              </div>
            )}

            {/* 流式输出 / 结果展示 */}
            {testResult && (
              <div className="flex min-h-0 flex-1 flex-col gap-3">
                {/* 流式文本输出（chat / hermes 模式） */}
                {testResult.reply !== undefined && (
                  <div className="shrink-0 rounded-lg border border-gray-700 bg-gray-900/60 p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                        {testResult.mode === 'chat'
                          ? '对话回复'
                          : testResult.mode === 'hermes'
                          ? 'Hermes 回答'
                          : 'AI 回答'}
                      </span>
                      {testResult.streaming && (
                        <span className="flex items-center gap-1 text-[11px] text-brand-300">
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-400" />
                          生成中
                        </span>
                      )}
                    </div>
                    <div className="max-h-[400px] overflow-y-auto whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-200">
                      {testResult.reply || ''}
                      {testResult.streaming && (
                        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-brand-400 align-middle" />
                      )}
                    </div>
                  </div>
                )}

                {/* Hermes 引擎：思考过程（可折叠） */}
                {testResult.thinking && (
                  <details className="shrink-0 rounded-lg border border-gray-700 bg-gray-900/40" open>
                    <summary className="cursor-pointer px-3 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 hover:text-gray-400">
                      🧠 思考过程
                    </summary>
                    <div className="max-h-[300px] overflow-y-auto whitespace-pre-wrap break-words border-t border-gray-800 p-3 text-[12px] leading-relaxed text-gray-400">
                      {testResult.thinking}
                    </div>
                  </details>
                )}

                {/* Hermes 引擎：工具调用区（可折叠） */}
                {testResult.toolCalls && testResult.toolCalls.length > 0 && (
                  <div className="shrink-0 overflow-hidden rounded-lg border border-gray-700 bg-gray-900/40">
                    <button
                      type="button"
                      onClick={() => setShowToolCalls((s) => !s)}
                      className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400 transition hover:bg-gray-800/60"
                    >
                      <span>🔧 工具调用（{testResult.toolCalls.length} 次）</span>
                      <span className="text-gray-600">{showToolCalls ? '▼' : '▶'}</span>
                    </button>
                    {showToolCalls && (
                      <div className="max-h-[260px] overflow-y-auto border-t border-gray-800 p-2">
                        <ToolCallList toolCalls={testResult.toolCalls} />
                      </div>
                    )}
                  </div>
                )}

                {/* Hermes 引擎：子代理委派事件树（可折叠） */}
                {testResult.delegateGroups && testResult.delegateGroups.length > 0 && (
                  <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-purple-700/40 bg-purple-900/5">
                    <button
                      type="button"
                      onClick={() => setShowDelegates((s) => !s)}
                      className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wider text-purple-300 transition hover:bg-purple-900/10"
                    >
                      <span>
                        🌳 子代理委派（{testResult.delegateGroups.length} 个子代理）
                      </span>
                      <span className="text-gray-600">{showDelegates ? '▼' : '▶'}</span>
                    </button>
                    {showDelegates && (
                      <div className="max-h-[400px] overflow-y-auto border-t border-purple-800/30 p-2">
                        <DelegateEventTree
                          groups={testResult.delegateGroups}
                          onToggle={toggleDelegateGroup}
                          onToggleAll={toggleAllDelegates}
                        />
                      </div>
                    )}
                  </div>
                )}

                {/* Agent 决策模式：决策结果 */}
                {testResult.decision !== undefined && (
                  <div className="shrink-0 rounded-lg border border-gray-700 bg-gray-900/60 p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">决策结果</span>
                      {testResult.duration != null && (
                        <span className="rounded bg-gray-800 px-2 py-0.5 text-[11px] text-gray-400">
                          耗时 {(testResult.duration / 1000).toFixed(2)}s
                        </span>
                      )}
                    </div>
                    <div className="flex flex-col gap-2">
                      {testResult.decision && (
                        <div className="flex items-center gap-2">
                          <span className="rounded bg-brand-600/20 px-2 py-0.5 text-xs font-semibold text-brand-300">
                            {testResult.decision}
                          </span>
                          {testResult.target_ip && (
                            <span className="font-mono text-xs text-gray-400">→ {testResult.target_ip}</span>
                          )}
                        </div>
                      )}
                      {testResult.reason && (
                        <div className="rounded border border-gray-800 bg-gray-800/40 p-2 text-xs leading-relaxed text-gray-300">
                          {testResult.reason}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* 推理过程（可折叠） */}
                {testResult.messages && testResult.messages.length > 0 && (
                  <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-gray-700 bg-gray-900/40">
                    <button
                      type="button"
                      onClick={() => setShowMessages((s) => !s)}
                      className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400 transition hover:bg-gray-800/60"
                    >
                      <span>推理过程（{testResult.messages.length} 条消息）</span>
                      <span className="text-gray-600">{showMessages ? '▼' : '▶'}</span>
                    </button>
                    {showMessages && (
                      <div className="max-h-[300px] overflow-y-auto border-t border-gray-800 p-2">
                        {testResult.messages.map((msg, idx) => <MessageItem key={idx} msg={msg} idx={idx} />)}
                      </div>
                    )}
                  </div>
                )}

                {/* 执行日志（可折叠） */}
                {testResult.logs && testResult.logs.length > 0 && (
                  <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-gray-700 bg-gray-900/40">
                    <button
                      type="button"
                      onClick={() => setShowLogs((s) => !s)}
                      className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400 transition hover:bg-gray-800/60"
                    >
                      <span>执行日志（{testResult.logs.length} 条）</span>
                      <span className="text-gray-600">{showLogs ? '▼' : '▶'}</span>
                    </button>
                    {showLogs && (
                      <div className="max-h-[200px] overflow-y-auto border-t border-gray-800 p-2 font-mono text-[11px]">
                        {testResult.logs.map((log, idx) => (
                          <div key={idx} className="border-b border-gray-800/50 py-1 last:border-0">
                            <span className="text-gray-600">[{log.level || log.type || 'INFO'}]</span>{' '}
                            <span className="text-gray-400">{log.message || log.msg || JSON.stringify(log)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {!testResult && !testing && !testError && (
              <div className="flex flex-1 flex-col items-center justify-center text-center text-gray-600">
                <div className="mb-2 text-4xl">🤖</div>
                <div className="text-sm">输入测试数据后点击「调试运行」</div>
                <div className="mt-1 text-xs text-gray-700">智能体将使用当前配置进行推理，结果在此实时展示</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// 开场引导问题编辑器
function SuggestedQuestionsEditor({ value, onChange }) {
  const questions = Array.isArray(value) ? value : []
  return (
    <div className="flex flex-col gap-1.5">
      {questions.map((q, idx) => (
        <div key={idx} className="flex items-center gap-1.5">
          <input
            className={`${inputCls} flex-1`}
            value={q}
            placeholder={`引导问题 ${idx + 1}`}
            onChange={(e) => {
              const next = [...questions]
              next[idx] = e.target.value
              onChange(next)
            }}
          />
          <button
            type="button"
            onClick={() => onChange(questions.filter((_, i) => i !== idx))}
            className="shrink-0 rounded border border-gray-700 px-1.5 py-1 text-[11px] text-gray-500 hover:text-danger-400"
          >
            ✕
          </button>
        </div>
      ))}
      {questions.length < 6 && (
        <button
          type="button"
          onClick={() => onChange([...questions, ''])}
          className="text-[11px] text-brand-400 hover:text-brand-300"
        >
          + 添加引导问题
        </button>
      )}
    </div>
  )
}

// 推理过程消息项
function MessageItem({ msg, idx }) {
  const [expanded, setExpanded] = useState(false)
  const role = msg.role || msg.type || 'unknown'
  const content = msg.content || msg.text || ''
  const isLong = content.length > 200

  const roleColors = {
    system: 'text-purple-300 bg-purple-500/10',
    user: 'text-blue-300 bg-blue-500/10',
    assistant: 'text-green-300 bg-green-500/10',
    tool: 'text-amber-300 bg-amber-500/10',
    function: 'text-amber-300 bg-amber-500/10',
  }

  return (
    <div className="mb-2 rounded-md border border-gray-800 bg-gray-800/30">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${roleColors[role] || 'text-gray-300 bg-gray-700'}`}>
          {role}
        </span>
        {msg.name && <span className="font-mono text-[10px] text-gray-500">{msg.name}</span>}
        {isLong && (
          <button type="button" onClick={() => setExpanded((e) => !e)} className="ml-auto text-[10px] text-brand-400 hover:text-brand-300">
            {expanded ? '收起' : '展开'}
          </button>
        )}
      </div>
      <div className="px-2 pb-2 text-[11px] leading-relaxed text-gray-300">
        {isLong && !expanded ? content.slice(0, 200) + '…' : content}
      </div>
    </div>
  )
}

// ============================================================================
// Hermes 引擎专属：工具调用列表
// 渲染 tool_start / tool_end 事件为时间线
// ============================================================================
function ToolCallList({ toolCalls }) {
  if (!toolCalls || toolCalls.length === 0) return null
  return (
    <div className="flex flex-col gap-1.5">
      {toolCalls.map((tc, idx) => (
        <div
          key={tc.call_id || idx}
          className={`rounded-md border bg-gray-800/30 px-2 py-1.5 ${
            tc.status === 'running'
              ? 'border-brand-500/40'
              : 'border-gray-700'
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="text-[11px]">
              {tc.status === 'running' ? '⏳' : '✓'}
            </span>
            <span className="rounded bg-purple-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-purple-300">
              {tc.name}
            </span>
            {tc.status === 'running' && (
              <span className="flex items-center gap-1 text-[10px] text-brand-300">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-400" />
                执行中
              </span>
            )}
          </div>
          {tc.message && (
            <div className="mt-0.5 text-[10px] text-gray-500">{tc.message}</div>
          )}
          {tc.result !== null && tc.result !== undefined && (
            <ToolCallResult result={tc.result} />
          )}
        </div>
      ))}
    </div>
  )
}

// 工具调用结果展示（长结果可折叠）
function ToolCallResult({ result }) {
  const [expanded, setExpanded] = useState(false)
  const text =
    typeof result === 'string'
      ? result
      : JSON.stringify(result, null, 2)
  const isLong = text.length > 300

  return (
    <div className="mt-1 rounded border border-gray-800 bg-gray-900/50 p-1.5">
      <div className="mb-0.5 flex items-center justify-between">
        <span className="text-[10px] text-gray-600">结果</span>
        {isLong && (
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="text-[10px] text-brand-400 hover:text-brand-300"
          >
            {expanded ? '收起' : `展开（${text.length} 字符）`}
          </button>
        )}
      </div>
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-relaxed text-gray-400">
        {isLong && !expanded ? text.slice(0, 300) + '…' : text}
      </pre>
    </div>
  )
}

// ============================================================================
// Hermes 引擎专属：子代理委派事件树
// 按 subagent_id 分组，每个分组可折叠展开，展示嵌套事件流
// ============================================================================
// 子代理分组状态徽章
function DelegateStatusBadge({ status }) {
  const meta = {
    running: { label: '运行中', cls: 'bg-brand-500/15 text-brand-300' },
    completed: { label: '已完成', cls: 'bg-emerald-500/15 text-emerald-300' },
    failed: { label: '失败', cls: 'bg-danger-500/15 text-danger-300' },
  }
  const m = meta[status] || meta.running
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${m.cls}`}>
      {m.label}
    </span>
  )
}

// 单个嵌套事件渲染
function DelegateEventItem({ evt, idx }) {
  const [expanded, setExpanded] = useState(false)
  const iconMap = {
    start: '🚀',
    token: '💬',
    tool_start: '🔧',
    tool_end: '✓',
    done: '🏁',
    error: '❌',
    status: '📋',
    log: '📝',
  }
  const icon = iconMap[evt.type] || '•'

  // token 事件合并展示（避免过多 token 行）
  if (evt.type === 'token') {
    return (
      <div className="flex items-start gap-1.5 py-0.5 text-[11px]">
        <span className="text-gray-600">{icon}</span>
        <span className="text-gray-300">{evt.content}</span>
      </div>
    )
  }

  // tool_start/tool_end 展示工具名 + 结果
  if (evt.type === 'tool_start' || evt.type === 'tool_end') {
    const hasResult = evt.result !== null && evt.result !== undefined
    const resultText = hasResult
      ? typeof evt.result === 'string'
        ? evt.result
        : JSON.stringify(evt.result, null, 2)
      : ''
    const isLong = resultText.length > 200
    return (
      <div className="flex items-start gap-1.5 py-0.5 text-[11px]">
        <span className="text-gray-600">{icon}</span>
        <div className="min-w-0 flex-1">
          <span className="font-mono text-purple-300">{evt.tool_name || 'tool'}</span>
          {evt.message && <span className="ml-1 text-gray-500">{evt.message}</span>}
          {hasResult && (
            <div className="mt-0.5">
              {isLong ? (
                <>
                  <button
                    type="button"
                    onClick={() => setExpanded((e) => !e)}
                    className="text-[10px] text-brand-400 hover:text-brand-300"
                  >
                    {expanded ? '收起结果' : `展开结果（${resultText.length} 字符）`}
                  </button>
                  {expanded && (
                    <pre className="mt-0.5 max-h-32 overflow-auto whitespace-pre-wrap break-all rounded border border-gray-800 bg-gray-900/50 p-1 font-mono text-[10px] text-gray-400">
                      {resultText}
                    </pre>
                  )}
                </>
              ) : (
                <pre className="mt-0.5 whitespace-pre-wrap break-all font-mono text-[10px] text-gray-400">
                  {resultText}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    )
  }

  // done / error / start / status 通用渲染
  const text = evt.content || evt.message || ''
  const colorMap = {
    start: 'text-blue-300',
    done: 'text-emerald-300',
    error: 'text-danger-300',
    status: 'text-gray-400',
  }
  return (
    <div className="flex items-start gap-1.5 py-0.5 text-[11px]">
      <span className="text-gray-600">{icon}</span>
      <span className={colorMap[evt.type] || 'text-gray-300'}>
        {text || evt.type}
      </span>
    </div>
  )
}

// 单个子代理分组（可折叠卡片）
function DelegateGroupCard({ group, onToggle }) {
  const eventCount = group.events.length
  // 统计子代理内部工具调用数
  const toolCount = group.events.filter(
    (e) => e.type === 'tool_start' || e.type === 'tool_end'
  ).length / 2 | 0

  return (
    <div className="rounded-md border border-purple-700/40 bg-purple-900/5">
      {/* 分组头部（点击折叠/展开） */}
      <button
        type="button"
        onClick={() => onToggle(group.subagent_id)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-purple-900/10"
      >
        <span className="text-[10px] text-gray-500">
          {group.expanded ? '▼' : '▶'}
        </span>
        <span className="font-mono text-[11px] font-semibold text-purple-300">
          {group.subagent_id}
        </span>
        <span className="text-[10px] text-gray-600">
          task#{group.task_index}
        </span>
        <DelegateStatusBadge status={group.status} />
        <span className="ml-auto flex items-center gap-2 text-[10px] text-gray-600">
          {toolCount > 0 && <span>🔧 {toolCount}</span>}
          <span>📝 {eventCount}</span>
        </span>
      </button>

      {/* 分组目标 */}
      {group.goal && (
        <div className="border-t border-purple-800/30 px-3 py-1 text-[11px] text-gray-400">
          <span className="text-gray-600">目标：</span>
          {group.goal}
        </div>
      )}

      {/* 嵌套事件列表 */}
      {group.expanded && eventCount > 0 && (
        <div className="max-h-64 overflow-y-auto border-t border-purple-800/30 px-3 py-2">
          <div className="border-l border-purple-800/40 pl-2">
            {group.events.map((evt, idx) => (
              <DelegateEventItem key={idx} evt={evt} idx={idx} />
            ))}
          </div>
        </div>
      )}

      {/* 空状态 */}
      {group.expanded && eventCount === 0 && (
        <div className="border-t border-purple-800/30 px-3 py-3 text-center text-[11px] text-gray-600">
          暂无事件
        </div>
      )}
    </div>
  )
}

// 子代理委派事件树（主组件）
function DelegateEventTree({ groups, onToggle, onToggleAll }) {
  if (!groups || groups.length === 0) return null
  const running = groups.filter((g) => g.status === 'running').length
  const completed = groups.filter((g) => g.status === 'completed').length
  const failed = groups.filter((g) => g.status === 'failed').length

  return (
    <div className="flex flex-col gap-2">
      {/* 统计栏 + 全部展开/折叠 */}
      <div className="flex items-center gap-3 text-[11px] text-gray-500">
        <span>共 {groups.length} 个子代理</span>
        {running > 0 && <span className="text-brand-300">运行中 {running}</span>}
        {completed > 0 && <span className="text-emerald-300">完成 {completed}</span>}
        {failed > 0 && <span className="text-danger-300">失败 {failed}</span>}
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => onToggleAll(true)}
            className="rounded border border-gray-700 px-1.5 py-0.5 text-[10px] text-gray-400 hover:bg-gray-800"
          >
            全部展开
          </button>
          <button
            type="button"
            onClick={() => onToggleAll(false)}
            className="rounded border border-gray-700 px-1.5 py-0.5 text-[10px] text-gray-400 hover:bg-gray-800"
          >
            全部折叠
          </button>
        </div>
      </div>

      {/* 分组列表 */}
      {groups.map((g) => (
        <DelegateGroupCard key={g.subagent_id} group={g} onToggle={onToggle} />
      ))}
    </div>
  )
}

export default AgentEditor
