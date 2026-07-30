import { Fragment, useEffect, useState, useCallback } from 'react'
import { systemMonitorApi } from '../api/systemMonitor'

// ============ 工具函数 ============
// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 运行时长格式化：x天 x小时 x分钟
function fmtUptime(seconds) {
  if (seconds == null || seconds < 0) return '-'
  const s = Math.floor(Number(seconds) || 0)
  const days = Math.floor(s / 86400)
  const hours = Math.floor((s % 86400) / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  return `${days}天 ${hours}小时 ${minutes}分钟`
}

// 进度条颜色：<60% 绿色，60-80% 黄色，>80% 红色
function progressColor(percent) {
  if (percent > 80) return 'bg-danger-500'
  if (percent >= 60) return 'bg-warning-500'
  return 'bg-success-500'
}

// detail 格式化为 JSON 字符串
function fmtDetail(detail) {
  if (detail == null || detail === '') return ''
  if (typeof detail === 'string') {
    try {
      return JSON.stringify(JSON.parse(detail), null, 2)
    } catch {
      return detail
    }
  }
  try {
    return JSON.stringify(detail, null, 2)
  } catch {
    return String(detail)
  }
}

// ============ 通用小组件 ============
// 进度条
function ProgressBar({ percent }) {
  const safe = Math.min(100, Math.max(0, Number(percent) || 0))
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-gray-800">
      <div
        className={`h-full rounded-full transition-all ${progressColor(safe)}`}
        style={{ width: `${safe}%` }}
      />
    </div>
  )
}

// 服务状态标签：healthy=绿/unhealthy=红/unknown=灰
function ServiceStatusBadge({ status }) {
  const map = {
    healthy: 'bg-success-500/20 text-success-300',
    unhealthy: 'bg-danger-500/20 text-danger-300',
    unknown: 'bg-gray-500/20 text-gray-400',
  }
  const cls = map[status] || map.unknown
  return (
    <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {status || 'unknown'}
    </span>
  )
}

// 整体状态徽章：healthy=绿 / degraded=红
function OverallBadge({ overall }) {
  if (overall === 'healthy') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-success-500/20 px-3 py-1 text-sm font-medium text-success-300">
        <span className="h-2 w-2 rounded-full bg-success-400" />
        系统正常
      </span>
    )
  }
  if (overall === 'degraded') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-danger-500/20 px-3 py-1 text-sm font-medium text-danger-300">
        <span className="h-2 w-2 rounded-full bg-danger-400" />
        系统异常
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-500/20 px-3 py-1 text-sm font-medium text-gray-400">
      <span className="h-2 w-2 rounded-full bg-gray-400" />
      未知
    </span>
  )
}

// 操作类型彩色标签
function ActionBadge({ action }) {
  const map = {
    login: 'bg-brand-500/20 text-brand-300',
    logout: 'bg-gray-500/20 text-gray-300',
    create: 'bg-success-500/20 text-success-300',
    update: 'bg-warning-500/20 text-warning-300',
    delete: 'bg-danger-500/20 text-danger-300',
    execute: 'bg-brand-500/20 text-brand-300',
  }
  const cls = map[action] || 'bg-gray-700 text-gray-300'
  return (
    <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {action || '-'}
    </span>
  )
}

// 结果标签：success=绿 / failed=红
function ResultBadge({ result }) {
  const isSuccess = result === 'success' || result === 'ok' || result === true
  const isFailed = result === 'failed' || result === 'fail' || result === 'error'
  if (isSuccess) {
    return (
      <span className="rounded bg-success-500/20 px-2 py-0.5 text-[11px] font-medium text-success-300">
        success
      </span>
    )
  }
  if (isFailed) {
    return (
      <span className="rounded bg-danger-500/20 px-2 py-0.5 text-[11px] font-medium text-danger-300">
        {result || 'failed'}
      </span>
    )
  }
  return (
    <span className="rounded bg-gray-500/20 px-2 py-0.5 text-[11px] font-medium text-gray-400">
      {result || '-'}
    </span>
  )
}

// ============ Tab 1：服务健康 ============
function HealthTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await systemMonitorApi.health()
      setData(res)
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 自动刷新：每 30 秒拉取一次
  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(() => {
      load()
    }, 30000)
    return () => clearInterval(timer)
  }, [autoRefresh, load])

  const services = data?.services || []

  return (
    <div className="flex flex-col gap-4">
      {/* 顶部：整体状态 + 最后检查时间 + 自动刷新 + 刷新按钮 */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-gray-800 bg-gray-900/60 p-4">
        <div className="flex flex-wrap items-center gap-4">
          {data ? <OverallBadge overall={data.overall} /> : null}
          <span className="text-xs text-gray-500">
            最后检查：{data?.checked_at ? fmtTime(data.checked_at) : '-'}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-gray-400">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="h-3.5 w-3.5 accent-brand-500"
            />
            每 30 秒自动刷新
          </label>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="btn-secondary btn-sm"
          >
            {loading ? '刷新中...' : '刷新'}
          </button>
        </div>
      </div>

      {error && (
        <div className="w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="flex h-40 items-center justify-center text-sm text-gray-500">
          加载中...
        </div>
      ) : services.length === 0 ? (
        <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
          <div className="text-4xl">📡</div>
          <div className="text-sm">暂无服务数据</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {services.map((svc) => (
            <div
              key={svc.name}
              className="rounded-lg border border-gray-800 bg-gray-900/60 p-4 shadow-lg transition-colors hover:border-brand-500/40"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-sm font-semibold text-gray-100">
                  {svc.name}
                </div>
                <ServiceStatusBadge status={svc.status} />
              </div>
              <div className="mt-2 flex items-center gap-4 text-xs text-gray-400">
                <span>
                  延迟：
                  {svc.latency_ms != null ? `${svc.latency_ms} ms` : '-'}
                </span>
              </div>
              {svc.detail && (
                <div className="mt-2 break-words text-xs leading-relaxed text-gray-500">
                  {svc.detail}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ============ Tab 2：性能指标 ============
function PerformanceTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await systemMonitorApi.performance()
      setData(res)
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const cpuPercent = data?.cpu_percent ?? 0
  const mem = data?.memory || {}
  const disk = data?.disk || {}
  const uptime = data?.uptime_seconds

  return (
    <div className="flex flex-col gap-4">
      {/* 顶部：刷新按钮 */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">
          实时性能指标（CPU / 内存 / 磁盘 / 运行时长）
        </span>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="btn-secondary btn-sm"
        >
          {loading ? '刷新中...' : '刷新'}
        </button>
      </div>

      {error && (
        <div className="w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="flex h-40 items-center justify-center text-sm text-gray-500">
          加载中...
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* CPU 使用率 */}
          <div className="rounded-xl border border-gray-800 bg-gradient-to-br from-gray-900 to-gray-900/40 p-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-xl">
                  🧠
                </div>
                <div className="text-sm text-gray-400">CPU 使用率</div>
              </div>
              <div className="text-right">
                <span className="text-2xl font-bold text-gray-100">
                  {Math.round(cpuPercent)}
                </span>
                <span className="ml-1 text-sm text-gray-400">%</span>
              </div>
            </div>
            <div className="mt-4">
              <ProgressBar percent={cpuPercent} />
              <div className="mt-2 text-xs text-gray-500">
                核心数：{data?.cpu_count ?? '-'}
              </div>
            </div>
          </div>

          {/* 内存使用率 */}
          <div className="rounded-xl border border-gray-800 bg-gradient-to-br from-gray-900 to-gray-900/40 p-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-xl">
                  💾
                </div>
                <div className="text-sm text-gray-400">内存使用率</div>
              </div>
              <div className="text-right">
                <span className="text-2xl font-bold text-gray-100">
                  {Math.round(mem.percent ?? 0)}
                </span>
                <span className="ml-1 text-sm text-gray-400">%</span>
              </div>
            </div>
            <div className="mt-4">
              <ProgressBar percent={mem.percent ?? 0} />
              <div className="mt-2 text-xs text-gray-500">
                {mem.used_gb ?? '-'} GB / {mem.total_gb ?? '-'} GB
              </div>
            </div>
          </div>

          {/* 磁盘使用率 */}
          <div className="rounded-xl border border-gray-800 bg-gradient-to-br from-gray-900 to-gray-900/40 p-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-warning-500/10 text-xl">
                  💿
                </div>
                <div className="text-sm text-gray-400">磁盘使用率</div>
              </div>
              <div className="text-right">
                <span className="text-2xl font-bold text-gray-100">
                  {Math.round(disk.percent ?? 0)}
                </span>
                <span className="ml-1 text-sm text-gray-400">%</span>
              </div>
            </div>
            <div className="mt-4">
              <ProgressBar percent={disk.percent ?? 0} />
              <div className="mt-2 text-xs text-gray-500">
                {disk.used_gb ?? '-'} GB / {disk.total_gb ?? '-'} GB
              </div>
            </div>
          </div>

          {/* 运行时长 */}
          <div className="rounded-xl border border-gray-800 bg-gradient-to-br from-gray-900 to-gray-900/40 p-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-success-500/10 text-xl">
                  ⏱️
                </div>
                <div className="text-sm text-gray-400">运行时长</div>
              </div>
            </div>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="text-xl font-bold text-gray-100">
                {fmtUptime(uptime)}
              </span>
            </div>
            <div className="mt-2 text-xs text-gray-500">系统自启动以来持续运行</div>
          </div>
        </div>
      )}
    </div>
  )
}

// ============ Tab 3：审计日志 ============
const PAGE_SIZE = 50
const ACTION_OPTIONS = ['login', 'logout', 'create', 'update', 'delete', 'execute']
const RESOURCE_OPTIONS = ['workflow', 'tool', 'agent', 'user', 'role', 'auth']

function AuditLogsTab() {
  const [logs, setLogs] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState(null)

  // 筛选条件（已提交查询的）
  const [filters, setFilters] = useState({ action: '', resource_type: '', username: '' })
  // 输入框临时值
  const [input, setInput] = useState({ action: '', resource_type: '', username: '' })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = { limit: PAGE_SIZE, offset }
      if (filters.action) params.action = filters.action
      if (filters.resource_type) params.resource_type = filters.resource_type
      if (filters.username.trim()) params.username = filters.username.trim()
      const res = await systemMonitorApi.auditLogs(params)
      setLogs(res?.logs || [])
      setTotal(res?.total ?? 0)
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [offset, filters])

  useEffect(() => {
    load()
  }, [load])

  const handleQuery = () => {
    setOffset(0)
    setFilters({ ...input })
    setExpandedId(null)
  }

  const handleReset = () => {
    setInput({ action: '', resource_type: '', username: '' })
    setOffset(0)
    setFilters({ action: '', resource_type: '', username: '' })
    setExpandedId(null)
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const canPrev = offset > 0
  const canNext = offset + PAGE_SIZE < total

  const handlePrev = () => {
    if (canPrev) {
      setOffset(Math.max(0, offset - PAGE_SIZE))
      setExpandedId(null)
    }
  }
  const handleNext = () => {
    if (canNext) {
      setOffset(offset + PAGE_SIZE)
      setExpandedId(null)
    }
  }

  const selectCls =
    'rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white outline-none focus:border-brand-500'
  const inputCls =
    'min-w-0 flex-1 rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white outline-none placeholder:text-gray-500 focus:border-brand-500'

  return (
    <div className="flex flex-col gap-4">
      {/* 顶部筛选栏 */}
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-gray-800 bg-gray-900/60 p-4">
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-400">操作类型</span>
          <select
            value={input.action}
            onChange={(e) => setInput((p) => ({ ...p, action: e.target.value }))}
            className={selectCls}
          >
            <option value="">全部</option>
            {ACTION_OPTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-400">资源类型</span>
          <select
            value={input.resource_type}
            onChange={(e) =>
              setInput((p) => ({ ...p, resource_type: e.target.value }))
            }
            className={selectCls}
          >
            <option value="">全部</option>
            {RESOURCE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        <input
          value={input.username}
          onChange={(e) => setInput((p) => ({ ...p, username: e.target.value }))}
          placeholder="搜索用户名..."
          className={inputCls}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleQuery()
          }}
        />
        <button
          type="button"
          onClick={handleQuery}
          className="shrink-0 btn-primary btn-sm"
        >
          查询
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="shrink-0 btn-secondary btn-sm"
        >
          重置
        </button>
      </div>

      {error && (
        <div className="w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
          {error}
        </div>
      )}

      {/* 日志表格 */}
      {loading ? (
        <div className="flex h-40 items-center justify-center text-sm text-gray-500">
          加载中...
        </div>
      ) : logs.length === 0 ? (
        <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
          <div className="text-4xl">📋</div>
          <div className="text-sm">未查询到符合条件的日志</div>
        </div>
      ) : (
        <div className="w-full overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full min-w-[960px] table-fixed border-collapse text-sm">
            <thead className="bg-gray-900 text-gray-400">
              <tr>
                <th className="w-40 px-4 py-3 text-left font-medium">时间</th>
                <th className="w-28 px-4 py-3 text-left font-medium">用户名</th>
                <th className="w-24 px-4 py-3 text-left font-medium">操作类型</th>
                <th className="w-24 px-4 py-3 text-left font-medium">资源类型</th>
                <th className="w-20 px-4 py-3 text-left font-medium">资源 ID</th>
                <th className="w-24 px-4 py-3 text-left font-medium">结果</th>
                <th className="px-4 py-3 text-left font-medium">IP 地址</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log, idx) => {
                const expanded = expandedId === log.id
                const detail = fmtDetail(log.detail)
                return (
                  <Fragment key={log.id}>
                    <tr
                      onClick={() => setExpandedId(expanded ? null : log.id)}
                      className={`cursor-pointer border-t border-gray-800 transition-colors hover:bg-brand-500/5 ${
                        idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
                      }`}
                    >
                      <td className="px-4 py-3 text-gray-300">
                        {fmtTime(log.created_at)}
                      </td>
                      <td className="truncate px-4 py-3 text-gray-200">
                        {log.username || '-'}
                      </td>
                      <td className="px-4 py-3">
                        <ActionBadge action={log.action} />
                      </td>
                      <td className="px-4 py-3 text-gray-300">
                        {log.resource_type || '-'}
                      </td>
                      <td className="truncate px-4 py-3 font-mono text-xs text-brand-300">
                        {log.resource_id ?? '-'}
                      </td>
                      <td className="px-4 py-3">
                        <ResultBadge result={log.result} />
                      </td>
                      <td className="truncate px-4 py-3 font-mono text-xs text-gray-400">
                        {log.ip_address || '-'}
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="border-t border-gray-800 bg-gray-950/60">
                        <td colSpan={7} className="px-4 py-3">
                          <div className="mb-1 text-xs text-gray-500">
                            详情（点击行收起）
                          </div>
                          {detail ? (
                            <pre className="max-h-72 w-full overflow-auto whitespace-pre-wrap break-words rounded-md border border-gray-800 bg-gray-950/80 p-4 font-mono text-xs text-gray-300">
                              {detail}
                            </pre>
                          ) : (
                            <div className="text-xs text-gray-600">暂无详情</div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 分页 */}
      {!loading && logs.length > 0 && (
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span>
            共 {total} 条，第 {currentPage} / {totalPages} 页
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handlePrev}
              disabled={!canPrev}
              className="btn-secondary btn-sm"
            >
              上一页
            </button>
            <button
              type="button"
              onClick={handleNext}
              disabled={!canNext}
              className="btn-secondary btn-sm"
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ============ Tab 4：服务日志（通过 Docker 容器查看各服务运行日志） ============
// 容器状态徽章：running=绿 / exited=红 / 其它=灰
function ContainerStatusBadge({ status, running }) {
  if (running) {
    return (
      <span className="rounded bg-success-500/20 px-2 py-0.5 text-[11px] font-medium text-success-300">
        running
      </span>
    )
  }
  if (status === 'exited' || status === 'dead') {
    return (
      <span className="rounded bg-danger-500/20 px-2 py-0.5 text-[11px] font-medium text-danger-300">
        {status || 'unknown'}
      </span>
    )
  }
  return (
    <span className="rounded bg-gray-500/20 px-2 py-0.5 text-[11px] font-medium text-gray-400">
      {status || 'unknown'}
    </span>
  )
}

function ServiceLogsTab() {
  const [services, setServices] = useState([])
  const [error, setError] = useState('')
  const [loadingList, setLoadingList] = useState(true)
  const [selected, setSelected] = useState(null) // 当前选中的容器名
  const [logs, setLogs] = useState([])
  const [logsError, setLogsError] = useState('')
  const [loadingLogs, setLoadingLogs] = useState(false)
  const [tail, setTail] = useState(200) // 取最近 N 行

  // 加载服务列表
  const loadServices = useCallback(async () => {
    setLoadingList(true)
    try {
      const res = await systemMonitorApi.listServices()
      setServices(res?.services || [])
      setError(res?.error || '')
      // 默认选中第一个容器
      if (!selected && (res?.services || []).length > 0) {
        setSelected(res.services[0].name)
      }
    } catch (err) {
      setError(err.message || '加载失败')
      setServices([])
    } finally {
      setLoadingList(false)
    }
  }, [selected])

  // 加载选中容器的日志
  const loadLogs = useCallback(async () => {
    if (!selected) return
    setLoadingLogs(true)
    setLogsError('')
    try {
      const res = await systemMonitorApi.getServiceLogs(selected, tail)
      setLogs(res?.logs || [])
      // 容器可能在拉取日志时已删除，做一次列表同步
      if (res?.status) {
        setServices((prev) =>
          prev.map((s) => (s.name === selected ? { ...s, status: res.status, running: res.status === 'running' } : s))
        )
      }
    } catch (err) {
      setLogsError(err.message || '获取日志失败')
      setLogs([])
    } finally {
      setLoadingLogs(false)
    }
  }, [selected, tail])

  // 初次加载服务列表
  useEffect(() => {
    loadServices()
  }, [loadServices])

  // 选中容器或 tail 变化时拉取日志
  useEffect(() => {
    if (selected) loadLogs()
  }, [selected, tail, loadLogs])

  const handleSelect = (name) => {
    if (name === selected) return
    setSelected(name)
  }

  const selectCls =
    'rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white outline-none focus:border-brand-500'

  return (
    <div className="flex flex-col gap-4">
      {/* 顶部工具栏：刷新服务列表 + tail 行数选择 */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-gray-800 bg-gray-900/60 p-4">
        <span className="text-xs text-gray-500">
          通过 Docker 容器获取 SOAR 平台各服务的运行日志（仅可查看 soar- 前缀的服务）
        </span>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-400">
            最近
            <select
              value={tail}
              onChange={(e) => setTail(Number(e.target.value))}
              className={selectCls}
            >
              <option value={100}>100</option>
              <option value={200}>200</option>
              <option value={500}>500</option>
              <option value={1000}>1000</option>
              <option value={2000}>2000</option>
            </select>
            行
          </label>
          <button
            type="button"
            onClick={loadServices}
            disabled={loadingList}
            className="btn-secondary btn-sm"
          >
            {loadingList ? '刷新中...' : '刷新服务'}
          </button>
        </div>
      </div>

      {error && (
        <div className="w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        {/* 左侧：容器列表 */}
        <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-2">
          <div className="px-2 py-2 text-xs font-medium text-gray-400">
            服务容器（{services.length}）
          </div>
          {loadingList && services.length === 0 ? (
            <div className="flex h-32 items-center justify-center text-xs text-gray-500">
              加载中...
            </div>
          ) : services.length === 0 ? (
            <div className="flex h-32 flex-col items-center justify-center gap-1 text-gray-500">
              <div className="text-2xl">📦</div>
              <div className="text-xs">暂无容器数据</div>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              {services.map((svc) => {
                const active = svc.name === selected
                return (
                  <button
                    key={svc.name}
                    type="button"
                    onClick={() => handleSelect(svc.name)}
                    className={`flex items-center justify-between gap-2 rounded-md px-3 py-2 text-left transition ${
                      active
                        ? 'bg-brand-500/15 text-white ring-1 ring-brand-500/40'
                        : 'text-gray-300 hover:bg-gray-800/60'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{svc.name}</div>
                      <div className="mt-0.5 truncate text-[11px] text-gray-500">
                        {svc.image || '-'}
                      </div>
                    </div>
                    <ContainerStatusBadge status={svc.status} running={svc.running} />
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* 右侧：日志内容 */}
        <div className="flex min-h-[400px] flex-col rounded-lg border border-gray-800 bg-gray-950/60">
          {/* 日志头部 */}
          <div className="flex items-center justify-between border-b border-gray-800 px-4 py-2">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-gray-100">
                {selected || '未选择服务'}
              </span>
              {selected && (
                <span className="text-[11px] text-gray-500">
                  最近 {tail} 行
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={loadLogs}
                disabled={!selected || loadingLogs}
                className="btn-secondary btn-sm"
              >
                {loadingLogs ? '拉取中...' : '刷新日志'}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!logs.length) return
                  const blob = new Blob([logs.join('\n')], { type: 'text/plain;charset=utf-8' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = `${selected}-${Date.now()}.log`
                  a.click()
                  URL.revokeObjectURL(url)
                }}
                disabled={!logs.length}
                className="btn-secondary btn-sm"
              >
                下载
              </button>
            </div>
          </div>

          {/* 日志正文 */}
          <div className="flex-1 overflow-auto p-3">
            {logsError ? (
              <div className="rounded-md border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-xs text-danger-300">
                {logsError}
              </div>
            ) : loadingLogs && logs.length === 0 ? (
              <div className="flex h-32 items-center justify-center text-xs text-gray-500">
                拉取日志中...
              </div>
            ) : !selected ? (
              <div className="flex h-32 items-center justify-center text-xs text-gray-500">
                请在左侧选择一个服务容器
              </div>
            ) : logs.length === 0 ? (
              <div className="flex h-32 flex-col items-center justify-center gap-1 text-gray-500">
                <div className="text-2xl">📄</div>
                <div className="text-xs">暂无日志输出</div>
              </div>
            ) : (
              <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-gray-300">
                {logs.map((ln, idx) => (
                  <div key={idx} className="border-b border-gray-900/50 px-1 py-0.5 hover:bg-gray-900/40">
                    {ln}
                  </div>
                ))}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ============ 主组件 ============
function SystemMonitor() {
  const [activeTab, setActiveTab] = useState('health') // health | performance | audit | logs

  const tabs = [
    { key: 'health', label: '服务健康' },
    { key: 'performance', label: '性能指标' },
    { key: 'audit', label: '审计日志' },
    { key: 'logs', label: '服务日志' },
  ]

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      {/* 顶部标题栏 */}
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-100">系统监控</h1>
          <span className="text-xs text-gray-500">
            服务健康 / 性能指标 / 审计日志 / 服务日志
          </span>
        </div>
      </header>

      {/* Tab 切换 */}
      <div className="flex items-center gap-1 border-b border-gray-800 bg-gray-900/30 px-6">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveTab(t.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
              activeTab === t.key
                ? 'border-brand-500 text-white'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 内容滚动区 */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === 'health' && <HealthTab />}
        {activeTab === 'performance' && <PerformanceTab />}
        {activeTab === 'audit' && <AuditLogsTab />}
        {activeTab === 'logs' && <ServiceLogsTab />}
      </div>
    </div>
  )
}

export default SystemMonitor
