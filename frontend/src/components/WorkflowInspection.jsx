import { useEffect, useState, useMemo, useCallback } from 'react'
import ReactECharts from 'echarts-for-react'
import { getExecutions, getExecutionDetail } from '../api/executions'

// 格式化时间
function fmtTime(t) {
  if (!t) return ''
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(t)
  }
}

// 取本地日期 YYYY-MM-DD（按本地时区分组，避免时区错位）
function toDate(t) {
  if (!t) return ''
  try {
    const d = new Date(t)
    if (Number.isNaN(d.getTime())) return ''
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  } catch {
    return ''
  }
}

// 计算单次执行耗时（秒）：finished_at - created_at，缺 finished_at 视为 0
function durationSeconds(exec) {
  if (!exec || !exec.created_at || !exec.finished_at) return 0
  const start = new Date(exec.created_at).getTime()
  const end = new Date(exec.finished_at).getTime()
  if (Number.isNaN(start) || Number.isNaN(end)) return 0
  return Math.max(0, (end - start) / 1000)
}

// 执行状态标签颜色：success=绿 / failed=红 / running=蓝 / waiting=黄
function execStatusClass(status) {
  switch ((status || '').toLowerCase()) {
    case 'success':
      return 'bg-success-500/20 text-success-300'
    case 'failed':
    case 'error':
      return 'bg-danger-500/20 text-danger-300'
    case 'running':
      return 'bg-brand-500/20 text-brand-300'
    case 'waiting':
    case 'waiting_for_approval':
      return 'bg-warning-500/20 text-warning-300'
    default:
      return 'bg-gray-700 text-gray-300'
  }
}

// 轨迹节点状态颜色
function traceStatusClass(status) {
  switch ((status || '').toLowerCase()) {
    case 'success':
      return 'bg-success-500/20 text-success-300'
    case 'failed':
    case 'error':
      return 'bg-danger-500/20 text-danger-300'
    case 'running':
      return 'bg-brand-500/20 text-brand-300'
    case 'waiting':
    case 'waiting_for_approval':
      return 'bg-warning-500/20 text-warning-300'
    default:
      return 'bg-gray-700 text-gray-300'
  }
}

// 日志 level 标签颜色
function logLevelClass(level) {
  switch ((level || '').toLowerCase()) {
    case 'error':
      return 'bg-danger-500/20 text-danger-300'
    case 'warn':
    case 'warning':
      return 'bg-warning-500/20 text-warning-300'
    case 'info':
      return 'bg-brand-500/20 text-brand-300'
    default:
      return 'bg-gray-700 text-gray-300'
  }
}

// 紧凑统计卡片（适配窄面板）
function StatCard({ label, value, suffix, accent }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-2.5">
      <div className="text-[10px] text-gray-400">{label}</div>
      <div className="mt-1 flex items-baseline gap-0.5">
        <span className={`text-lg font-bold ${accent || 'text-gray-100'}`}>{value}</span>
        {suffix && <span className="text-[10px] text-gray-500">{suffix}</span>}
      </div>
    </div>
  )
}

// 监测 Tab：4 个统计卡片 + 按天趋势折线图
function MonitorTab({ executions }) {
  // 本地计算统计指标
  const stats = useMemo(() => {
    const total = executions.length
    let success = 0
    let failed = 0
    let durSum = 0
    let durCount = 0
    const byDayMap = {} // date -> { date, total, success, failed }
    for (const ex of executions) {
      const st = (ex.status || '').toLowerCase()
      if (st === 'success') success++
      if (st === 'failed' || st === 'error') failed++
      const dur = durationSeconds(ex)
      if (dur > 0) {
        durSum += dur
        durCount++
      }
      const date = toDate(ex.created_at)
      if (date) {
        if (!byDayMap[date]) byDayMap[date] = { date, total: 0, success: 0, failed: 0 }
        byDayMap[date].total++
        if (st === 'success') byDayMap[date].success++
        if (st === 'failed' || st === 'error') byDayMap[date].failed++
      }
    }
    const successRate = total > 0 ? Math.round((success / total) * 100) : 0
    const avgDuration = durCount > 0 ? Math.round((durSum / durCount) * 10) / 10 : 0
    // 按日期升序排列
    const byDay = Object.values(byDayMap).sort((a, b) => (a.date < b.date ? -1 : 1))
    return { total, success, failed, successRate, avgDuration, byDay }
  }, [executions])

  // 按天趋势折线图配置：总数 / 成功 / 失败
  const trendOption = useMemo(() => {
    const dates = stats.byDay.map((d) => d.date)
    const totals = stats.byDay.map((d) => d.total)
    const successes = stats.byDay.map((d) => d.success)
    const faileds = stats.byDay.map((d) => d.failed)
    return {
      backgroundColor: 'transparent',
      textStyle: { color: '#9ca3af' },
      tooltip: { trigger: 'axis' },
      legend: { data: ['总数', '成功', '失败'], textStyle: { color: '#9ca3af' }, top: 0 },
      grid: { left: 30, right: 15, top: 35, bottom: 25 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { color: '#9ca3af', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#9ca3af', fontSize: 10 },
      },
      series: [
        { name: '总数', type: 'line', data: totals, smooth: true, itemStyle: { color: '#22d3ee' } },
        { name: '成功', type: 'line', data: successes, smooth: true, itemStyle: { color: '#22c55e' } },
        { name: '失败', type: 'line', data: faileds, smooth: true, itemStyle: { color: '#ef4444' } },
      ],
    }
  }, [stats])

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* 4 个统计卡片，2x2 网格 */}
      <div className="grid grid-cols-2 gap-2">
        <StatCard label="总执行数" value={stats.total} />
        <StatCard label="成功率" value={stats.successRate} suffix="%" accent="text-success-300" />
        <StatCard label="平均耗时" value={stats.avgDuration} suffix="秒" accent="text-brand-300" />
        <StatCard label="失败数" value={stats.failed} accent="text-danger-300" />
      </div>

      {/* 按天趋势折线图 */}
      <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-2">
        <div className="mb-1 text-[11px] font-medium text-gray-300">按天执行趋势</div>
        {stats.byDay.length === 0 ? (
          <div className="py-6 text-center text-[11px] text-gray-600">暂无数据</div>
        ) : (
          <ReactECharts option={trendOption} style={{ height: 180, width: '100%' }} />
        )}
      </div>
    </div>
  )
}

// 日志 Tab：执行记录表格 + 行展开详情（轨迹与日志）
function LogsTab({ executions, loading }) {
  // 当前展开的执行 id（null 表示全部折叠）
  const [expandedId, setExpandedId] = useState(null)
  // 详情缓存：id -> { execution, traces, logs }
  const [detailCache, setDetailCache] = useState({})
  // 加载中的 id 集合
  const [loadingIds, setLoadingIds] = useState({})
  // 详情错误：id -> 错误信息
  const [detailErr, setDetailErr] = useState({})

  // 切换展开/折叠，展开时按需拉取详情并缓存
  const toggle = useCallback(
    async (id) => {
      if (expandedId === id) {
        setExpandedId(null)
        return
      }
      setExpandedId(id)
      // 已缓存则直接复用
      if (detailCache[id]) return
      setLoadingIds((m) => ({ ...m, [id]: true }))
      setDetailErr((m) => ({ ...m, [id]: '' }))
      try {
        const data = await getExecutionDetail(id)
        setDetailCache((m) => ({
          ...m,
          [id]: {
            execution: data?.execution || {},
            traces: Array.isArray(data?.traces) ? data.traces : [],
            logs: Array.isArray(data?.logs) ? data.logs : [],
          },
        }))
      } catch (err) {
        setDetailErr((m) => ({ ...m, [id]: err.message || '加载详情失败' }))
      } finally {
        setLoadingIds((m) => ({ ...m, [id]: false }))
      }
    },
    [expandedId, detailCache]
  )

  if (executions.length === 0) {
    return (
      <div className="py-8 text-center text-[11px] text-gray-600">
        {loading ? '加载中…' : '暂无执行记录'}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-3">
      {executions.map((ex) => {
        const expanded = expandedId === ex.id
        const detail = detailCache[ex.id]
        const isLoading = loadingIds[ex.id]
        const err = detailErr[ex.id]
        return (
          <div key={ex.id} className="rounded-md border border-gray-800 bg-gray-900/40">
            {/* 行：点击展开/折叠，展示 ID/状态/触发类型/创建时间/耗时 */}
            <button
              type="button"
              onClick={() => toggle(ex.id)}
              className="flex w-full flex-col gap-1 px-2.5 py-2 text-left hover:bg-gray-800/40"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`shrink-0 text-[10px] text-gray-500 transition-transform ${
                    expanded ? 'rotate-90' : ''
                  }`}
                >
                  ▶
                </span>
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${execStatusClass(
                    ex.status
                  )}`}
                >
                  {ex.status || '-'}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-gray-300">
                  #{ex.id}
                </span>
                <span className="shrink-0 text-[10px] text-gray-400">
                  {durationSeconds(ex).toFixed(1)}s
                </span>
              </div>
              {/* 第二行：触发类型 + 创建时间 */}
              <div className="flex items-center gap-2 pl-4 text-[10px] text-gray-500">
                <span>触发：{ex.trigger_type || '-'}</span>
                <span className="text-gray-600">·</span>
                <span className="truncate">{fmtTime(ex.created_at)}</span>
              </div>
            </button>

            {/* 展开内容：节点轨迹 + 日志 */}
            {expanded && (
              <div className="border-t border-gray-800 p-2.5">
                {isLoading && (
                  <div className="py-3 text-center text-[11px] text-gray-500">加载详情…</div>
                )}
                {err && (
                  <div className="rounded border border-danger-700/40 bg-danger-900/20 p-2 text-[11px] text-danger-300">
                    {err}
                  </div>
                )}
                {detail && (
                  <>
                    {/* 节点轨迹列表 */}
                    <div className="mb-2">
                      <div className="mb-1 text-[11px] font-medium text-gray-300">
                        节点轨迹（{detail.traces.length}）
                      </div>
                      {detail.traces.length === 0 ? (
                        <div className="text-[11px] text-gray-600">暂无轨迹</div>
                      ) : (
                        <div className="flex flex-col gap-1">
                          {detail.traces.map((tr, idx) => {
                            const tdur =
                              tr.started_at && tr.finished_at
                                ? Math.max(
                                    0,
                                    (new Date(tr.finished_at).getTime() -
                                      new Date(tr.started_at).getTime()) /
                                      1000
                                  )
                                : 0
                            return (
                              <div
                                key={idx}
                                className="flex items-center gap-1.5 rounded bg-gray-950/40 px-1.5 py-1 text-[10px]"
                              >
                                <span
                                  className={`shrink-0 rounded px-1 py-0.5 ${traceStatusClass(
                                    tr.status
                                  )}`}
                                >
                                  {tr.status || '-'}
                                </span>
                                <span className="min-w-0 flex-1 truncate font-mono text-gray-300">
                                  {tr.node_id}
                                </span>
                                {tr.node_type && (
                                  <span className="shrink-0 rounded bg-gray-700 px-1 py-0.5 text-gray-300">
                                    {tr.node_type}
                                  </span>
                                )}
                                <span className="shrink-0 text-gray-500">
                                  {tdur.toFixed(1)}s
                                </span>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>

                    {/* 日志列表 */}
                    <div>
                      <div className="mb-1 text-[11px] font-medium text-gray-300">
                        日志（{detail.logs.length}）
                      </div>
                      {detail.logs.length === 0 ? (
                        <div className="text-[11px] text-gray-600">暂无日志</div>
                      ) : (
                        <div className="flex max-h-48 flex-col gap-0.5 overflow-y-auto">
                          {detail.logs.map((log, idx) => (
                            <div
                              key={idx}
                              className="flex items-start gap-1.5 font-mono text-[10px]"
                            >
                              <span
                                className={`shrink-0 rounded px-1 py-0.5 ${logLevelClass(
                                  log.level
                                )}`}
                              >
                                {(log.level || 'info').toUpperCase()}
                              </span>
                              {log.node_id && (
                                <span className="shrink-0 text-brand-300">[{log.node_id}]</span>
                              )}
                              <span className="min-w-0 flex-1 break-words text-gray-300">
                                {log.message}
                              </span>
                              {log.timestamp && (
                                <span className="shrink-0 text-gray-600">
                                  {fmtTime(log.timestamp)}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// 工作流监测组件：在工作流编辑器右侧面板展示当前工作流的监测数据与执行日志
// initialTab: 'monitor' | 'logs'，由父组件控制初始 Tab
function WorkflowInspection({ workflowId, initialTab = 'monitor' }) {
  // tab：监测 monitor | 日志 logs
  const [tab, setTab] = useState(initialTab)
  // 执行记录列表
  const [executions, setExecutions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 拉取该工作流的执行记录列表
  const load = useCallback(async () => {
    if (!workflowId) {
      setExecutions([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await getExecutions(50, 0, workflowId)
      setExecutions(Array.isArray(data) ? data : [])
    } catch (err) {
      setError(err.message || '加载执行记录失败')
      setExecutions([])
    } finally {
      setLoading(false)
    }
  }, [workflowId])

  useEffect(() => {
    load()
  }, [load])

  // workflowId 为空时提示先保存工作流
  if (!workflowId) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-center text-sm text-gray-500">请先保存工作流</p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部标题 + 刷新按钮 */}
      <div className="shrink-0 border-b border-gray-800 px-3 py-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-300">监测</h2>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="rounded-md border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:border-brand-700 hover:text-brand-300 disabled:opacity-50"
          >
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>
        {/* Tab 切换 */}
        <div className="mt-2 flex items-center gap-1 rounded-md bg-gray-800/60 p-0.5 text-[11px]">
          <button
            type="button"
            onClick={() => setTab('monitor')}
            className={`flex-1 rounded px-2 py-1 ${
              tab === 'monitor' ? 'bg-brand-600 text-white' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            监测
          </button>
          <button
            type="button"
            onClick={() => setTab('logs')}
            className={`flex-1 rounded px-2 py-1 ${
              tab === 'logs' ? 'bg-brand-600 text-white' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            日志
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="shrink-0 border-b border-danger-700/40 bg-danger-900/20 px-3 py-1.5 text-[11px] text-danger-300">
          {error}
        </div>
      )}

      {/* 内容区 */}
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        {tab === 'monitor' ? (
          <MonitorTab executions={executions} />
        ) : (
          <LogsTab executions={executions} loading={loading} />
        )}
      </div>
    </div>
  )
}

export default WorkflowInspection
