import { useEffect, useState, useCallback } from 'react'
import {
  getApprovals,
  getApprovalStats,
  approveExecution,
  rejectExecution,
} from '../api/approvals'
import { workflows as workflowsApi } from '../api/client'

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
  return (
    <div className="min-w-0">
      <div className="text-xs text-gray-500">{label}</div>
      <div
        className={`truncate ${mono ? 'font-mono' : ''} text-sm text-gray-200`}
        title={toText(value)}
      >
        {toText(value)}
      </div>
    </div>
  )
}

// ============ 完整上下文折叠区 ============
function ContextPanel({ ctx }) {
  const [expanded, setExpanded] = useState(false)
  if (!ctx || typeof ctx !== 'object') return null
  const entries = Object.entries(ctx)
  if (entries.length === 0) return null

  return (
    <div className="mt-3 w-full">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between rounded-md bg-gray-800/40 px-3 py-2 text-left text-xs text-gray-300 hover:bg-gray-800/70"
      >
        <span>完整上下文（{entries.length} 项）</span>
        <span>{expanded ? '收起 ▲' : '展开 ▼'}</span>
      </button>
      {expanded && (
        <div className="mt-2 max-h-96 w-full overflow-y-auto rounded-md border border-gray-800 bg-gray-950/80 p-4">
          <div className="flex flex-col gap-4">
            {entries.map(([key, val]) => (
              <div
                key={key}
                className="w-full border-b border-gray-800 pb-3 last:border-0"
              >
                <div className="mb-1 flex items-center gap-2">
                  <span className="rounded bg-brand-500/20 px-1.5 py-0.5 text-[10px] font-medium text-brand-300">
                    {key}
                  </span>
                  <span className="text-[10px] text-gray-500">
                    {Array.isArray(val)
                      ? `Array(${val.length})`
                      : val && typeof val === 'object'
                      ? 'Object'
                      : typeof val}
                  </span>
                </div>
                <pre className="w-full whitespace-pre-wrap break-words font-mono text-xs text-gray-300">
                  {toText(val)}
                </pre>
              </div>
            ))}
          </div>
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
        className="flex w-full items-center justify-between rounded-md bg-gray-800/40 px-3 py-2 text-left text-xs text-gray-300 hover:bg-gray-800/70"
      >
        <span>推理过程日志（{list.length} 条）</span>
        <span>{expanded ? '收起 ▲' : '展开 ▼'}</span>
      </button>
      {expanded && (
        <div className="mt-2 max-h-80 w-full overflow-y-auto rounded-md border border-gray-800 bg-gray-950/80 p-4">
          {list.length === 0 ? (
            <div className="text-xs text-gray-600">暂无日志</div>
          ) : (
            <div className="flex flex-col gap-2">
              {list.map((m, idx) => (
                <div
                  key={idx}
                  className="w-full border-b border-gray-800 pb-2 last:border-0"
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        m.role === 'assistant'
                          ? 'bg-brand-500/20 text-brand-300'
                          : m.role === 'tool'
                          ? 'bg-brand-500/20 text-purple-300'
                          : 'bg-gray-700 text-gray-300'
                      }`}
                    >
                      {m.role}
                    </span>
                  </div>
                  <pre className="w-full whitespace-pre-wrap break-words font-mono text-xs text-gray-300">
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
    indigo: 'from-brand-500/20 to-brand-600/5 border-brand-500/30 text-brand-300',
    orange: 'from-orange-500/20 to-orange-600/5 border-orange-500/30 text-orange-300',
    green: 'from-success-500/20 to-success-600/5 border-success-500/30 text-success-300',
    red: 'from-danger-500/20 to-danger-600/5 border-danger-500/30 text-danger-300',
    gray: 'from-gray-500/20 to-gray-600/5 border-gray-500/30 text-gray-300',
  }
  return (
    <div
      className={`flex min-w-0 flex-col gap-1 rounded-lg border bg-gradient-to-br p-4 ${colorMap[color]}`}
    >
      <div className="text-xs text-gray-400">{label}</div>
      <div className="text-2xl font-bold text-white">{value}</div>
      {sub && <div className="text-[11px] text-gray-500">{sub}</div>}
    </div>
  )
}

// ============ 工单卡片 ============
function ApprovalCard({ item, onApprove, onReject, busy }) {
  const alertData = item.alert_data || {}
  const decision = item.agent_decision || {}
  const ctx = item.context || {}
  const reviewMeta = item.review_meta || {}

  // 已处理工单展示 outcome 徽章
  const outcome =
    item.status !== 'waiting_for_approval'
      ? ctx.outcome ||
        (item.result && item.result.outcome) ||
        item.status
      : null

  return (
    <div className="w-full rounded-lg border border-gray-800 bg-gray-900/60 p-5 shadow-lg transition-colors hover:border-orange-500/40">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-800 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-danger-500/20 px-2 py-0.5 text-xs font-medium text-red-300">
            {alertData.alert_type || '未知告警'}
          </span>
          <span className="text-xs text-gray-500">
            工作流：{item.workflow_name || '-'}
          </span>
          <span className="text-xs text-gray-600">#{item.execution_id}</span>
          {outcome && (
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                outcome === 'approved'
                  ? 'bg-success-500/20 text-success-300'
                  : 'bg-gray-700 text-gray-300'
              }`}
            >
              {outcome === 'approved' ? '已同意封禁' : '已忽略'}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-500">
          创建：{fmtTime(item.created_at)}
        </span>
      </div>

      {(reviewMeta.title || reviewMeta.instructions) && (
        <div className="mt-3 w-full rounded-md border border-orange-700/40 bg-orange-900/20 p-4">
          {reviewMeta.title && (
            <div className="mb-1 text-sm font-semibold text-orange-200">
              👤 {reviewMeta.title}
            </div>
          )}
          {reviewMeta.instructions && (
            <div className="whitespace-pre-wrap text-xs leading-relaxed text-orange-100/80">
              {reviewMeta.instructions}
            </div>
          )}
        </div>
      )}

      <div className="grid w-full grid-cols-2 gap-4 py-3 sm:grid-cols-4">
        <InfoCell label="告警源 IP" value={alertData.src_ip} />
        <InfoCell label="目标 IP" value={alertData.dest_ip} />
        <InfoCell label="建议目标" value={decision.target_ip} />
        <InfoCell label="建议时长" value={decision.duration} />
      </div>

      {alertData && Object.keys(alertData).length > 0 && (
        <div className="grid w-full grid-cols-2 gap-4 pb-3 sm:grid-cols-4">
          {Object.entries(alertData)
            .filter(([k]) => !['src_ip', 'dest_ip', 'alert_type'].includes(k))
            .slice(0, 4)
            .map(([k, v]) => (
              <InfoCell key={k} label={k} value={v} />
            ))}
        </div>
      )}

      <div className="w-full rounded-md bg-gray-950/60 p-4">
        <div className="mb-1 text-xs text-gray-500">Agent 建议</div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-warning-500/20 px-2 py-0.5 text-xs text-amber-300">
            {decision.decision || '-'}
          </span>
          <span className="text-sm text-gray-300">{decision.reason || '-'}</span>
        </div>
      </div>

      <ContextPanel ctx={ctx} />
      <MessagesPanel messages={item.agent_messages} />

      {item.status === 'waiting_for_approval' && (
        <div className="mt-4 flex w-full items-center justify-end gap-4 border-t border-gray-800 pt-3">
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
  const [items, setItems] = useState([])
  const [stats, setStats] = useState(null)
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  // 查询筛选条件
  const [tab, setTab] = useState('pending') // pending | all
  const [workflowId, setWorkflowId] = useState('')
  const [keyword, setKeyword] = useState('')

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

  // 拉取工作流列表（用于筛选下拉）
  const loadWorkflows = useCallback(async () => {
    try {
      const data = await workflowsApi.list()
      setWorkflows(Array.isArray(data) ? data : [])
    } catch (err) {
      console.error('workflows load failed', err)
    }
  }, [])

  // 拉取工单列表
  const load = useCallback(async () => {
    try {
      const params = {}
      if (tab === 'all') params.status = 'all'
      if (workflowId) params.workflow_id = workflowId
      if (keyword.trim()) params.q = keyword.trim()
      params.limit = 200
      const data = await getApprovals(params)
      setItems(Array.isArray(data) ? data : [])
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [tab, workflowId, keyword])

  // 待处理工单轮询（5s）；切到「全部」时不轮询避免覆盖筛选
  useEffect(() => {
    load()
    loadStats()
    loadWorkflows()
    let timer = null
    if (tab === 'pending' && !workflowId && !keyword) {
      timer = setInterval(() => {
        load()
        loadStats()
      }, 5000)
    }
    return () => {
      if (timer) clearInterval(timer)
    }
  }, [load, loadStats, loadWorkflows, tab, workflowId, keyword])

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

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      {/* 顶部标题栏 */}
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">工作台</h1>
          {stats && (
            <span className="rounded-full bg-orange-500/20 px-2.5 py-0.5 text-xs font-medium text-orange-300">
              待处理 {stats.pending}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            load()
            loadStats()
          }}
          className="btn-secondary btn-sm"
        >
          刷新
        </button>
      </header>

      <div className="flex-1 min-w-0 overflow-y-auto p-6">
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

        {/* 查询筛选区：Tab + 工作流下拉 + 关键词输入，横向铺满 */}
        <div className="mb-4 flex w-full flex-wrap items-center gap-3 border-b border-gray-800 pb-4">
          <div className="flex shrink-0 rounded-md border border-gray-800 bg-gray-900/60 p-0.5">
            <button
              type="button"
              onClick={() => setTab('pending')}
              className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                tab === 'pending'
                  ? 'bg-brand-600 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              待处理
            </button>
            <button
              type="button"
              onClick={() => setTab('all')}
              className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                tab === 'all'
                  ? 'bg-brand-600 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              全部历史
            </button>
          </div>

          <select
            value={workflowId}
            onChange={(e) => setWorkflowId(e.target.value)}
            className="min-w-0 flex-1 rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white outline-none focus:border-brand-500"
          >
            <option value="">全部工作流</option>
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>

          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索告警类型 / IP / 工作流名..."
            className="min-w-0 flex-1 rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white outline-none placeholder:text-gray-500 focus:border-brand-500"
            onKeyDown={(e) => {
              if (e.key === 'Enter') load()
            }}
          />
          <button
            type="button"
            onClick={load}
            className="shrink-0 btn-secondary btn-sm"
          >
            查询
          </button>
        </div>

        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : items.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">✅</div>
            <div className="text-sm">
              {tab === 'pending' ? '暂无待处理工单' : '未查询到符合条件的工单'}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {items.map((item) => (
              <ApprovalCard
                key={item.execution_id}
                item={item}
                onApprove={handleApprove}
                onReject={handleReject}
                busy={busyId === item.execution_id}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default ApprovalCenter
