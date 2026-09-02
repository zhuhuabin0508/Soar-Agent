import { useEffect, useState, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  CheckCircle2,
  ClipboardList,
  Ban,
  ScrollText,
  User,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Search,
  X,
  Copy,
  Download,
  AlertCircle,
  Clock,
  Rocket,
  Flag,
  Brain,
  Trash2,
  Activity,
} from 'lucide-react'
import {
  getApprovals,
  getApprovalStats,
  approveExecution,
  rejectExecution,
  deleteExecution,
} from '../api/approvals'
import { workflows as workflowsApi } from '../api/client'
import banWorkflowApi from '../api/banWorkflow'
import BanApprovals from './ban/BanApprovals'
import BanWorkbench from './ban/BanWorkbench'
import BanWorkflowInstances from './ban/BanWorkflowInstances'
import { inputBaseCls } from '../components/property/FormControls'
import { isAdmin } from '../utils/permissions'
import { confirm } from '../components/ConfirmDialog'

// ============ 工具函数 ============
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

function fmtDuration(seconds) {
  if (!seconds || seconds <= 0) return '-'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h${Math.floor((seconds % 3600) / 60)}m`
}

function toText(v) {
  if (v == null) return '-'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

// ============ 信息单元 ============
function InfoCell({ label, value, mono = true }) {
  const text = toText(value)
  const isEmpty = text === '-' || text === '' || text == null
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground/70">{label}</div>
      <div
        className={`truncate ${mono ? 'font-mono' : ''} text-sm ${isEmpty ? 'text-muted-foreground/40' : 'text-foreground'}`}
        title={text}
      >
        {isEmpty ? '无' : text}
      </div>
    </div>
  )
}

// JSON 语法高亮（轻量级，返回 HTML 字符串）
function highlightJson(obj) {
  let json
  try { json = JSON.stringify(obj, null, 2) } catch { return '' }
  return json
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, (match) => {
      let cls = 'text-amber-300' // number
      if (/^"/.test(match)) {
        if (/:$/.test(match)) cls = 'text-sky-300' // key
        else cls = 'text-emerald-300' // string
      } else if (/true|false/.test(match)) cls = 'text-purple-300'
      else if (/null/.test(match)) cls = 'text-muted-foreground/60'
      return `<span class="${cls}">${match}</span>`
    })
}

// ============ 完整上下文折叠区（JSON 高亮 + 复制/下载） ============
function ContextPanel({ ctx }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)
  if (!ctx || typeof ctx !== 'object') return null
  const entries = Object.entries(ctx)
  if (entries.length === 0) return null

  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(ctx, null, 2)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(ctx, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `context_${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mt-3 w-full">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between rounded-md bg-muted px-3 py-2 text-left text-xs text-muted-foreground hover:bg-muted"
      >
        <span>完整上下文（{entries.length} 项）</span>
        <span className="inline-flex items-center gap-1">{expanded ? '收起' : '展开'} {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}</span>
      </button>
      {expanded && (
        <div className="mt-2 w-full overflow-hidden rounded-md border border-border bg-background/80">
          <div className="flex items-center justify-between border-b border-border bg-muted/50 px-3 py-1.5">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">JSON</span>
            <div className="flex items-center gap-1">
              <button type="button" onClick={handleCopy} className="flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:bg-secondary hover:text-foreground">
                {copied ? <CheckCircle2 className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                {copied ? '已复制' : '复制'}
              </button>
              <button type="button" onClick={handleDownload} className="flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:bg-secondary hover:text-foreground">
                <Download className="h-3 w-3" /> 下载
              </button>
            </div>
          </div>
          <pre
            className="max-h-96 w-full overflow-y-auto p-4 font-mono text-xs leading-relaxed"
            dangerouslySetInnerHTML={{ __html: highlightJson(ctx) }}
          />
        </div>
      )}
    </div>
  )
}

// ============ 推理过程日志 ============
function MessagesPanel({ messages }) {
  const [expanded, setExpanded] = useState(false)
  const list = Array.isArray(messages) ? messages : []
  return (
    <div className="mt-3 w-full">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between rounded-md bg-muted px-3 py-2 text-left text-xs text-muted-foreground hover:bg-muted"
      >
        <span>推理过程日志（{list.length} 条）</span>
        <span className="inline-flex items-center gap-1">{expanded ? '收起' : '展开'} {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}</span>
      </button>
      {expanded && (
        <div className="mt-2 max-h-80 w-full overflow-y-auto rounded-md border border-border bg-background/80 p-4">
          {list.length === 0 ? (
            <div className="text-xs text-muted-foreground/60">暂无日志</div>
          ) : (
            <div className="flex flex-col gap-2">
              {list.map((m, idx) => (
                <div
                  key={idx}
                  className="w-full border-b border-border pb-2 last:border-0"
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        m.role === 'assistant'
                          ? 'bg-primary/20 text-primary'
                          : m.role === 'tool'
                          ? 'bg-primary/20 text-primary'
                          : 'bg-secondary text-muted-foreground'
                      }`}
                    >
                      {m.role}
                    </span>
                  </div>
                  <pre className="w-full whitespace-pre-wrap break-words font-mono text-xs text-muted-foreground">
                    {typeof m.content === 'string'
                      ? m.content
                      : JSON.stringify(m.content, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ============ 统计看板卡片 ============
function StatCard({ label, value, sub, color = 'indigo' }) {
  const colorMap = {
    indigo: 'from-primary/20 to-primary/5 border-primary/30 text-primary',
    orange: 'from-orange-500/20 to-orange-600/5 border-orange-500/30 text-warning',
    green: 'from-success-500/20 to-success-600/5 border-success/30 text-success',
    red: 'from-danger-500/20 to-danger-600/5 border-destructive/30 text-destructive',
    gray: 'from-gray-500/20 to-gray-600/5 border-border/30 text-muted-foreground',
  }
  return (
    <div
      className={`flex min-w-0 flex-col gap-1 rounded-lg border bg-gradient-to-br p-4 ${colorMap[color]}`}
    >
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-bold text-foreground">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground/70">{sub}</div>}
    </div>
  )
}

// ============ 迷你时间线 ============
function MiniTimeline({ item }) {
  const alertData = item.alert_data || {}
  const decision = item.agent_decision || {}
  const ctx = item.context || {}
  const outcome = item.status !== 'waiting_for_approval'
    ? (ctx.outcome || (item.result && item.result.outcome) || item.status)
    : null

  const nodes = [
    { label: '告警触发', time: item.created_at, done: true, icon: <AlertCircle className="h-3 w-3" /> },
    { label: 'Agent 研判', time: item.agent_decided_at || item.updated_at, done: !!(decision.decision), icon: <Brain className="h-3 w-3" /> },
    { label: '人工审批', time: item.reviewed_at, done: outcome != null, icon: <User className="h-3 w-3" /> },
    {
      label: outcome === 'approved' ? '已封禁' : outcome === 'rejected' ? '已忽略' : '待处理',
      time: item.finished_at || item.updated_at,
      done: outcome != null,
      icon: outcome === 'approved' ? <Ban className="h-3 w-3" /> : outcome === 'rejected' ? <X className="h-3 w-3" /> : <Clock className="h-3 w-3" />,
    },
  ]
  return (
    <div className="flex items-center gap-1 overflow-x-auto py-2">
      {nodes.map((n, idx) => (
        <div key={idx} className="flex items-center gap-1">
          <div className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${
            n.done ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border bg-secondary text-muted-foreground/50'
          }`}>
            {n.icon}
            <span>{n.label}</span>
            {n.done && n.time && <span className="text-muted-foreground/50">· {fmtTime(n.time).split(' ')[1] || ''}</span>}
          </div>
          {idx < nodes.length - 1 && <span className="text-muted-foreground/30">→</span>}
        </div>
      ))}
    </div>
  )
}

// ============ 工单卡片 ============
function ApprovalCard({ item, onApprove, onReject, onDelete, busy }) {
  const alertData = item.alert_data || {}
  const decision = item.agent_decision || {}
  const ctx = item.context || {}
  const reviewMeta = item.review_meta || {}
  const isPending = item.status === 'waiting_for_approval'
  const isRejected = item.status === 'rejected' || ctx.outcome === 'rejected'

  // 已处理工单展示 outcome 徽章
  const outcome = !isPending ? (ctx.outcome || (item.result && item.result.outcome) || item.status) : null

  // 关键字段摘要
  const summaryItems = [
    { label: '告警类型', value: alertData.alert_type },
    { label: '源 IP', value: alertData.src_ip },
    { label: '目标 IP', value: alertData.dest_ip },
    { label: '告警次数', value: alertData.count },
  ].filter((s) => s.value != null && s.value !== '')

  return (
    <div className={`w-full rounded-lg border bg-card/60 p-5 shadow-lg transition-colors hover:border-orange-500/40 ${isRejected ? 'border-border/50 opacity-75' : 'border-border'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-destructive/20 px-2 py-0.5 text-xs font-medium text-destructive">
            {alertData.alert_type || '未知告警'}
          </span>
          <span className="text-xs text-muted-foreground/70">
            工作流：{item.workflow_name || '-'}
          </span>
          <span className="text-xs text-muted-foreground/60">#{item.execution_id}</span>
          {outcome && (
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                outcome === 'approved'
                  ? 'bg-success/20 text-success'
                  : 'bg-secondary text-muted-foreground'
              }`}
            >
              {outcome === 'approved' ? '已同意封禁' : '已忽略'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {onDelete && (
            <button
              type="button"
              onClick={() => onDelete(item)}
              className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground/70 transition hover:bg-accent hover:text-destructive"
              title="删除该工单（仅管理员）"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
          <span className="text-xs text-muted-foreground/70">
            创建：{fmtTime(item.created_at)}
          </span>
        </div>
      </div>

      {/* 迷你时间线 */}
      <MiniTimeline item={item} />

      {/* 关键字段摘要卡片 */}
      {summaryItems.length > 0 && (
        <div className="mt-2 grid w-full grid-cols-2 gap-2 rounded-md border border-border bg-background/40 p-2 sm:grid-cols-4">
          {summaryItems.map((s) => (
            <div key={s.label} className="min-w-0">
              <div className="text-[10px] text-muted-foreground/60">{s.label}</div>
              <div className="truncate font-mono text-xs text-foreground" title={toText(s.value)}>{toText(s.value)}</div>
            </div>
          ))}
        </div>
      )}

      {(reviewMeta.title || reviewMeta.instructions) && (
        <div className="mt-3 w-full rounded-md border border-warning/40 bg-warning/20 p-4">
          {reviewMeta.title && (
            <div className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-warning">
              <User className="h-4 w-4" />
              {reviewMeta.title}
            </div>
          )}
          {reviewMeta.instructions && (
            <div className="whitespace-pre-wrap text-xs leading-relaxed text-warning/80">
              {reviewMeta.instructions}
            </div>
          )}
        </div>
      )}

      {/* 告警详情：已忽略工单隐藏建议字段 */}
      <div className="grid w-full grid-cols-2 gap-4 py-3 sm:grid-cols-4">
        <InfoCell label="告警源 IP" value={alertData.src_ip} />
        <InfoCell label="目标 IP" value={alertData.dest_ip} />
        {!isRejected && <InfoCell label="建议目标" value={decision.target_ip} />}
        {!isRejected && <InfoCell label="建议时长" value={decision.duration} />}
      </div>

      {alertData && Object.keys(alertData).length > 0 && (
        <div className="grid w-full grid-cols-2 gap-4 pb-3 sm:grid-cols-4">
          {Object.entries(alertData)
            .filter(([k]) => !['src_ip', 'dest_ip', 'alert_type', 'count'].includes(k))
            .slice(0, 4)
            .map(([k, v]) => (
              <InfoCell key={k} label={k} value={v} />
            ))}
        </div>
      )}

      {/* Agent 建议：已忽略时显示「无需建议」 */}
      <div className="w-full rounded-md bg-background/60 p-4">
        <div className="mb-1 text-xs text-muted-foreground/70">Agent 建议</div>
        {isRejected ? (
          <div className="text-sm text-muted-foreground/50">该工单已被忽略，无需 Agent 建议</div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-warning/20 px-2 py-0.5 text-xs text-warning">
              {decision.decision || '无'}
            </span>
            <span className="text-sm text-muted-foreground">{decision.reason || '无'}</span>
          </div>
        )}
      </div>

      <ContextPanel ctx={ctx} />
      <MessagesPanel messages={item.agent_messages} />

      {isPending && (
        <div className="mt-4 flex w-full items-center justify-end gap-4 border-t border-border pt-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => onReject(item.execution_id)}
            className="btn-secondary"
          >
            忽略
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onApprove(item.execution_id)}
            className="btn-danger"
          >
            同意封禁
          </button>
        </div>
      )}
    </div>
  )
}

// ============ 工作台主组件 ============
function ApprovalCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
  // 支持 URL ?tab=banned / all 直达；默认为统一审批中心
  const initialTab = searchParams.get('tab') === 'banned' ? 'banned'
    : searchParams.get('tab') === 'all' ? 'all' : 'approval'

  const [items, setItems] = useState([])
  const [stats, setStats] = useState(null)
  // 封禁工作流统计：待审批工单数 + 生效中封禁数
  const [banStats, setBanStats] = useState({ pendingApprovals: 0, activeBans: 0 })
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  // 查询筛选条件：pending | all | banned
  const [tab, setTab] = useState(initialTab)
  // 全部历史 Tab 内子视图：instances（封禁实例）/ approvals（审批历史）
  const [historyTab, setHistoryTab] = useState('instances')
  const [workflowId, setWorkflowId] = useState(searchParams.get('workflow_id') || '')
  const [keyword, setKeyword] = useState(searchParams.get('q') || '')
  const [quickFilter, setQuickFilter] = useState(searchParams.get('filter') || '') // 严重/境外/今日/近7天

  // 切换 Tab 时同步 URL
  const switchTab = useCallback((newTab) => {
    setTab(newTab)
    setQuickFilter('')
    const params = {}
    if (newTab === 'banned') params.tab = 'banned'
    else if (newTab === 'all') params.tab = 'all'
    setSearchParams(params, { replace: true })
  }, [setSearchParams])

  // 拉取统计数据
  const loadStats = useCallback(async () => {
    try {
      const data = await getApprovalStats()
      setStats(data)
    } catch (err) {
      // 静默失败，不打断主流程
      console.error('stats load failed', err)
    }
  }, [])

  // 拉取封禁工作流统计（待审批工单 + 生效中封禁）
  const loadBanStats = useCallback(async () => {
    try {
      const [st, active] = await Promise.all([
        banWorkflowApi.stats(),
        banWorkflowApi.bannedIps({ status: 'active', page: 1, page_size: 1 }),
      ])
      setBanStats({
        pendingApprovals: st?.pending_approvals ?? 0,
        activeBans: active?.total ?? 0,
      })
    } catch (err) {
      // 静默失败，不打断主流程
      console.error('ban stats load failed', err)
    }
  }, [])

  // 拉取工作流列表（用于筛选下拉）
  const loadWorkflows = useCallback(async () => {
    try {
      const data = await workflowsApi.list()
      setWorkflows(Array.isArray(data) ? data : [])
    } catch (err) {
      console.error('workflows load failed', err)
    }
  }, [])

  // 拉取历史工单列表（全部历史 Tab 用）
  const load = useCallback(async () => {
    try {
      const params = {}
      if (tab === 'all') params.status = 'all'
      if (workflowId) params.workflow_id = workflowId
      // 合并关键词和快捷筛选
      const qParts = [keyword.trim(), quickFilter].filter(Boolean)
      if (qParts.length) params.q = qParts.join(' ')
      params.limit = 200
      const data = await getApprovals(params)
      setItems(Array.isArray(data) ? data : [])
      setError('')
      setLastUpdated(new Date())
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [tab, workflowId, keyword, quickFilter])

  // 手动刷新（审批中心/已封禁IP Tab 由嵌入组件自带刷新，这里刷新统计即可）
  const handleRefresh = useCallback(() => {
    loadBanStats()
    loadStats()
    if (tab === 'all') {
      load()
    }
  }, [tab, load, loadStats, loadBanStats])

  // 初始化加载：全历史 Tab 拉列表；统计始终拉取
  useEffect(() => {
    if (tab === 'all') {
      load()
    }
    loadStats()
    loadWorkflows()
    loadBanStats()
  }, [load, loadStats, loadWorkflows, loadBanStats, tab])

  const handleApprove = async (id) => {
    setBusyId(id)
    try {
      await approveExecution(id)
      setItems((prev) => prev.filter((it) => it.execution_id !== id))
      loadStats()
    } catch (err) {
      setError(err.message || '审批失败')
    } finally {
      setBusyId(null)
    }
  }

  const handleReject = async (id) => {
    setBusyId(id)
    try {
      await rejectExecution(id)
      setItems((prev) => prev.filter((it) => it.execution_id !== id))
      loadStats()
    } catch (err) {
      setError(err.message || '拒绝失败')
    } finally {
      setBusyId(null)
    }
  }

  // 删除历史工单（仅 admin）
  const handleDelete = async (item) => {
    const ok = await confirm({
      title: `删除工单 #${item.execution_id}`,
      message: '删除后该执行记录从工作台移除，操作仅限管理员。确定删除？',
      danger: true,
    })
    if (!ok) return
    try {
      await deleteExecution(item.execution_id)
      setItems((prev) => prev.filter((it) => it.execution_id !== item.execution_id))
      loadStats()
    } catch (err) {
      setError(err.message || '删除失败')
    }
  }

  // 快捷筛选 chips（全部历史 Tab）
  const currentQuickFilters = [
    { value: 'success', label: '成功' },
    { value: 'failed', label: '失败' },
    { value: '今日', label: '今日' },
    { value: '近7天', label: '近 7 天' },
  ]

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      {/* 顶部标题栏：页面名 + 全局快捷入口 + 刷新+最后更新时间 */}
      <header className="flex items-center justify-between border-b border-border bg-card/60 px-6 py-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">工作台</h1>
          {/* 全局快捷入口（点击跳转对应 Tab） */}
          <button
            type="button"
            onClick={() => switchTab('approval')}
            className="rounded-full bg-warning/20 px-2.5 py-0.5 text-xs font-medium text-warning transition hover:bg-warning/30"
            title="点击查看待审批工单"
          >
            待处理 {(stats?.pending ?? 0) + banStats.pendingApprovals}
          </button>
          <button
            type="button"
            onClick={() => switchTab('banned')}
            className="rounded-full bg-destructive/20 px-2.5 py-0.5 text-xs font-medium text-destructive transition hover:bg-destructive/30"
            title="点击查看已封禁 IP"
          >
            封禁中 {banStats.activeBans}
          </button>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-[11px] text-muted-foreground/50">
              最后更新：{lastUpdated.toLocaleTimeString('zh-CN', { hour12: false })}
            </span>
          )}
          <button
            type="button"
            onClick={handleRefresh}
            className="flex items-center gap-1.5 btn-secondary btn-sm"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
        </div>
      </header>

      <div className="flex-1 min-w-0 overflow-y-auto p-6">
        {/* Tab 导航栏：增强激活状态对比 */}
        <div className="mb-4 flex w-full items-center gap-3 border-b border-border pb-4">
          <div className="flex shrink-0 rounded-md border border-border bg-card/60 p-0.5">
            <button
              type="button"
              onClick={() => switchTab('approval')}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                tab === 'approval'
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
              }`}
            >
              <ClipboardList className="h-4 w-4" />
              审批中心
              {(stats?.pending ?? 0) + banStats.pendingApprovals > 0 && tab !== 'approval' && (
                <span className="ml-1 rounded-full bg-warning/30 px-1.5 text-[10px]">{(stats?.pending ?? 0) + banStats.pendingApprovals}</span>
              )}
            </button>
            <button
              type="button"
              onClick={() => switchTab('banned')}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                tab === 'banned'
                  ? 'bg-destructive text-destructive-foreground shadow-sm'
                  : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
              }`}
            >
              <Ban className="h-4 w-4" />
              已封禁 IP
              {banStats.activeBans > 0 && tab !== 'banned' && (
                <span className="ml-1 rounded-full bg-destructive/30 px-1.5 text-[10px]">{banStats.activeBans}</span>
              )}
            </button>
            <button
              type="button"
              onClick={() => switchTab('all')}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                tab === 'all'
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
              }`}
            >
              <ScrollText className="h-4 w-4" />
              全部历史
            </button>
          </div>
        </div>

        {/* ====== 审批中心 Tab：统一审批（封禁工单 + 工作流人工审批） ====== */}
        {tab === 'approval' ? (
          <BanApprovals embedded />
        ) : tab === 'banned' ? (
          /* ====== 已封禁 IP Tab：嵌入封禁工作台（新封禁工作流数据） ====== */
          <BanWorkbench embedded />
        ) : (
          <>
            {/* ====== 全部历史 Tab：统一历史（封禁实例 + 审批历史） ====== */}
            <div className="mb-4 flex items-center gap-2">
              <div className="flex items-center gap-1 rounded-md border border-border bg-card/60 p-0.5">
                <button
                  type="button"
                  onClick={() => setHistoryTab('instances')}
                  className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                    historyTab === 'instances'
                      ? 'bg-primary text-primary-foreground shadow-sm'
                      : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                  }`}
                >
                  <Activity className="h-4 w-4" />
                  封禁实例
                </button>
                <button
                  type="button"
                  onClick={() => setHistoryTab('approvals')}
                  className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                    historyTab === 'approvals'
                      ? 'bg-primary text-primary-foreground shadow-sm'
                      : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                  }`}
                >
                  <ScrollText className="h-4 w-4" />
                  审批历史
                </button>
              </div>
            </div>

            {historyTab === 'instances' ? (
              <BanWorkflowInstances embedded />
            ) : (
            <>
            {/* 统计看板：4 张数字卡片横向铺满 */}
            {stats && (
              <div className="grid w-full grid-cols-2 gap-4 pb-6 lg:grid-cols-4">
                <StatCard
                  label="待处理工单"
                  value={stats.pending ?? 0}
                  sub={`今日新增 ${stats.today_new ?? 0}`}
                  color="orange"
                />
                <StatCard
                  label="同意封禁"
                  value={stats.approved ?? 0}
                  sub="累计"
                  color="red"
                />
                <StatCard
                  label="已忽略"
                  value={stats.rejected ?? 0}
                  sub="累计"
                  color="gray"
                />
                <StatCard
                  label="平均处理时长"
                  value={fmtDuration(stats.avg_handle_seconds)}
                  sub="已结束工单"
                  color="indigo"
                />
              </div>
            )}

            {/* 快捷筛选 chips */}
            <div className="mb-3 flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground/60">快捷筛选：</span>
              {currentQuickFilters.map((f) => (
                <button
                  key={f.value}
                  type="button"
                  onClick={() => setQuickFilter((prev) => (prev === f.value ? '' : f.value))}
                  className={`rounded-full border px-2.5 py-0.5 text-[11px] transition ${
                    quickFilter === f.value
                      ? 'border-primary bg-primary/15 text-primary'
                      : 'border-border bg-secondary text-muted-foreground hover:border-primary/50 hover:text-foreground'
                  }`}
                >
                  {f.label}
                </button>
              ))}
              {quickFilter && (
                <button
                  type="button"
                  onClick={() => setQuickFilter('')}
                  className="flex items-center gap-0.5 text-[11px] text-muted-foreground/50 hover:text-foreground"
                >
                  <X className="h-3 w-3" /> 清除
                </button>
              )}
            </div>

            {/* 查询筛选区：工作流下拉 + 关键词输入（实时搜索） */}
            <div className="mb-4 flex w-full flex-wrap items-center gap-3">
              <select
                value={workflowId}
                onChange={(e) => setWorkflowId(e.target.value)}
                className={`${inputBaseCls} min-w-0 flex-1`}
              >
                <option value="">全部工作流</option>
                {workflows.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>

              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
                <input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="搜索告警类型 / IP / 工作流名..."
                  className={`${inputBaseCls} w-full pl-8`}
                />
              </div>
            </div>

            {error && (
              <div className="mb-4 w-full rounded-md border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm text-destructive">
                {error}
              </div>
            )}

            {loading ? (
              <div className="flex h-40 items-center justify-center text-sm text-muted-foreground/70">
                加载中...
              </div>
            ) : items.length === 0 ? (
              /* 空状态优化：更明确的文案 + 快捷操作 */
              <div className="flex h-60 flex-col items-center justify-center gap-3 text-muted-foreground/70">
                <CheckCircle2 className="h-14 w-14 opacity-40" />
                <div className="text-sm font-medium">未查询到符合条件的工单</div>
                {tab === 'all' && (
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => switchTab('approval')}
                      className="rounded-md border border-border px-2.5 py-1 text-[11px] text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                    >
                      前往审批中心
                    </button>
                    <button
                      type="button"
                      onClick={() => switchTab('banned')}
                      className="rounded-md border border-border px-2.5 py-1 text-[11px] text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                    >
                      查看已封禁 IP
                    </button>
                    <button
                      type="button"
                      onClick={handleRefresh}
                      className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[11px] text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                    >
                      <RefreshCw className="h-3 w-3" /> 刷新
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {items.map((item) => (
                  <ApprovalCard
                    key={item.execution_id}
                    item={item}
                    onApprove={handleApprove}
                    onReject={handleReject}
                    onDelete={isAdmin() ? handleDelete : undefined}
                    busy={busyId === item.execution_id}
                  />
                ))}
              </div>
            )}
            </>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default ApprovalCenter
