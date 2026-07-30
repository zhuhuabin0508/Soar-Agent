import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getExecutionDetail } from '../api/executions'

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 计算时长（秒）
function duration(started, finished) {
  if (!started || !finished) return '-'
  try {
    const ms = new Date(finished).getTime() - new Date(started).getTime()
    if (ms < 0) return '-'
    if (ms < 1000) return `${ms} ms`
    return `${(ms / 1000).toFixed(2)} 秒`
  } catch {
    return '-'
  }
}

// 状态对应圆点颜色
function dotColor(status) {
  switch ((status || '').toLowerCase()) {
    case 'success':
      return 'bg-success-400 ring-success-400/40'
    case 'failed':
    case 'error':
      return 'bg-danger-400 ring-danger-400/40'
    case 'waiting':
    case 'waiting_for_approval':
      return 'bg-warning-400 ring-warning-400/40'
    case 'running':
      return 'bg-brand-400 ring-brand-400/40'
    default:
      return 'bg-gray-400 ring-gray-400/40'
  }
}

function statusBadgeClass(status) {
  switch ((status || '').toLowerCase()) {
    case 'success':
      return 'bg-success-500/20 text-success-300'
    case 'failed':
    case 'error':
      return 'bg-danger-500/20 text-red-300'
    case 'waiting':
    case 'waiting_for_approval':
      return 'bg-warning-500/20 text-amber-300'
    case 'running':
      return 'bg-brand-500/20 text-brand-300'
    default:
      return 'bg-gray-700 text-gray-300'
  }
}

// 日志级别对应彩色标签样式
function logLevelBadgeClass(level) {
  switch ((level || '').toLowerCase()) {
    case 'info':
      return 'bg-brand-500/20 text-brand-300'
    case 'warning':
    case 'warn':
      return 'bg-warning-500/20 text-amber-300'
    case 'error':
      return 'bg-danger-500/20 text-red-300'
    case 'debug':
      return 'bg-gray-700 text-gray-300'
    default:
      return 'bg-gray-700 text-gray-300'
  }
}

// JSON 查看器：等宽字体，可滚动，填满宽度，可折叠/展开
function JsonViewer({ label, data }) {
  const [open, setOpen] = useState(true)
  const isEmpty =
    data == null || (typeof data === 'object' && Object.keys(data).length === 0)
  return (
    <div className="min-w-0 flex-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mb-1 flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300"
      >
        <span className="inline-block w-3 text-gray-400">{open ? '▼' : '▶'}</span>
        <span>{label}</span>
      </button>
      {open && (
        <pre className="w-full max-h-64 overflow-auto rounded-md bg-gray-950 p-4 font-mono text-xs text-gray-300 ring-1 ring-gray-800">
          {isEmpty ? '(空)' : JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}

// 日志区域：支持级别筛选、彩色标签、时间戳
function LogsSection({ logs }) {
  const [filter, setFilter] = useState('all')
  const levels = ['all', 'info', 'warning', 'error']
  const filtered =
    filter === 'all'
      ? logs
      : logs.filter((l) => (l.level || '').toLowerCase() === filter)

  return (
    <div className="mt-6 w-full">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium text-gray-300">
          日志（{logs.length} 条{filter !== 'all' ? `，筛选后 ${filtered.length} 条` : ''}）
        </div>
        <div className="flex items-center gap-1">
          {levels.map((lv) => (
            <button
              key={lv}
              type="button"
              onClick={() => setFilter(lv)}
              className={`rounded px-2 py-1 text-xs ${
                filter === lv
                  ? 'bg-gray-700 text-gray-100'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {lv === 'all' ? '全部' : lv}
            </button>
          ))}
        </div>
      </div>
      {filtered.length === 0 ? (
        <div className="flex h-24 items-center justify-center text-sm text-gray-500">
          暂无日志
        </div>
      ) : (
        <div className="max-h-96 overflow-y-auto rounded-lg border border-gray-800 bg-gray-900/60">
          {filtered.map((log, idx) => (
            <div
              key={idx}
              className="flex items-start gap-4 border-b border-gray-800/60 px-4 py-2 text-xs last:border-b-0"
            >
              <span className="shrink-0 text-gray-500">{fmtTime(log.timestamp)}</span>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase ${logLevelBadgeClass(log.level)}`}
              >
                {log.level || '-'}
              </span>
              {log.node_id && (
                <span className="shrink-0 rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400">
                  {log.node_id}
                </span>
              )}
              <span className="min-w-0 flex-1 break-words text-gray-300">{log.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// 执行追溯详情页：垂直时间轴
function ExecutionDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const res = await getExecutionDetail(id)
        if (!alive) return
        setData(res)
        setError('')
      } catch (err) {
        if (!alive) return
        setError(err.message || '加载失败')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [id])

  const execution = data?.execution || {}
  const traces = data?.traces || []
  const logs = data?.logs || []

  // 导出整个执行详情为 JSON 文件下载
  const handleExport = () => {
    if (!data) return
    try {
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `execution-${id}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      setError('导出失败：' + (e?.message || e))
    }
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      {/* 顶部标题栏 */}
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => navigate('/executions')}
            className="btn-secondary btn-sm"
          >
            ← 返回列表
          </button>
          <h1 className="text-xl font-semibold">执行追溯 #{id}</h1>
        </div>
        <button
          type="button"
          onClick={handleExport}
          disabled={!data}
          className="btn-secondary btn-sm"
        >
          导出 JSON
        </button>
      </header>

      {/* 内容滚动区 */}
      <div className="flex-1 min-w-0 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : !data ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            未找到数据
          </div>
        ) : (
          <>
            {/* 执行概要 */}
            <div className="mb-6 w-full rounded-lg border border-gray-800 bg-gray-900/60 p-5">
              <div className="grid w-full grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
                <InfoCell label="执行 ID" value={`#${execution.id}`} />
                <InfoCell label="工作流 ID" value={execution.workflow_id} />
                <div className="min-w-0">
                  <div className="text-xs text-gray-500">状态</div>
                  <span className={`mt-1 inline-block rounded px-2 py-0.5 text-xs font-medium ${statusBadgeClass(execution.status)}`}>
                    {execution.status || '-'}
                  </span>
                </div>
                <InfoCell label="触发类型" value={execution.trigger_type || '-'} />
                <InfoCell label="创建时间" value={fmtTime(execution.created_at)} />
                <InfoCell label="完成时间" value={fmtTime(execution.finished_at)} />
                <InfoCell label="总耗时" value={duration(execution.created_at, execution.finished_at)} />
              </div>
            </div>

            {/* 垂直时间轴 */}
            <div className="w-full">
              <div className="mb-3 text-sm font-medium text-gray-300">
                执行轨迹（{traces.length} 个节点）
              </div>
              {traces.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-gray-500">
                  暂无轨迹数据
                </div>
              ) : (
                <div className="relative w-full">
                  {/* 时间轴左侧轴线 */}
                  <div className="absolute bottom-0 left-[11px] top-2 w-px bg-gray-700" />
                  <div className="flex flex-col gap-5">
                    {traces.map((tr) => (
                      <div key={tr.id} className="relative flex w-full gap-5">
                        {/* 圆点 */}
                        <div
                          className={`relative z-dropdown mt-1 h-5 w-5 shrink-0 rounded-full ring-4 ${dotColor(tr.status)}`}
                        />
                        {/* 右侧详情卡片：填满剩余宽度 */}
                        <div className="min-w-0 flex-1 rounded-lg border border-gray-800 bg-gray-900/60 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-800 pb-2">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-gray-200">
                                {tr.node_label || tr.node_type || `节点 ${tr.node_id}`}
                              </span>
                              <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400">
                                {tr.node_type}
                              </span>
                            </div>
                            <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusBadgeClass(tr.status)}`}>
                              {tr.status || '-'}
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 py-2 text-xs text-gray-400">
                            <span>开始：{fmtTime(tr.started_at)}</span>
                            <span>结束：{fmtTime(tr.finished_at)}</span>
                            <span className="inline-flex items-center gap-1">
                              耗时：
                              <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-300">
                                {duration(tr.started_at, tr.finished_at)}
                              </span>
                            </span>
                          </div>
                          <div className="flex w-full flex-col gap-4 pt-2 sm:flex-row">
                            <JsonViewer label="输入" data={tr.input} />
                            <JsonViewer label="输出" data={tr.output} />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* 日志区 */}
            <LogsSection logs={logs} />
          </>
        )}
      </div>
    </div>
  )
}

// 信息单元
function InfoCell({ label, value }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="truncate text-sm text-gray-200" title={String(value)}>
        {value == null ? '-' : String(value)}
      </div>
    </div>
  )
}

export default ExecutionDetail
