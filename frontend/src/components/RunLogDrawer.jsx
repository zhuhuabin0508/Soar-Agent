import { useState } from 'react'
import { useWorkflowStore } from '../store/workflowStore'

// 格式化时间
function fmtTime(t) {
  if (!t) return ''
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(t)
  }
}

// 日志 level 颜色：info 灰 / warn 黄 / error 红
function logLevelClass(level) {
  switch ((level || '').toLowerCase()) {
    case 'error':
      return 'bg-danger-500/20 text-danger-300'
    case 'warn':
    case 'warning':
      return 'bg-warning-500/20 text-warning-300'
    default:
      return 'bg-gray-700 text-gray-300'
  }
}

function logLevelTextClass(level) {
  switch ((level || '').toLowerCase()) {
    case 'error':
      return 'text-danger-400'
    case 'warn':
    case 'warning':
      return 'text-warning-300'
    default:
      return 'text-gray-300'
  }
}

// 状态标签颜色
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

// 可折叠的运行日志抽屉：展示试运行/单节点试运行返回的 logs 与 traces
function RunLogDrawer() {
  const runLogs = useWorkflowStore((s) => s.runLogs)
  const runTraces = useWorkflowStore((s) => s.runTraces)
  const clearRunLogs = useWorkflowStore((s) => s.clearRunLogs)

  // collapsed 折叠 / expanded 展开（默认折叠）
  const [collapsed, setCollapsed] = useState(true)
  // tab：logs | traces
  const [tab, setTab] = useState('logs')

  const total = runLogs.length + runTraces.length

  return (
    <div className="shrink-0 border-t border-gray-800 bg-gray-900">
      {/* 顶栏：折叠按钮 + 标题 + 清空 + Tab */}
      <div className="flex items-center justify-between px-3 py-2">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-300 hover:text-white"
        >
          <span className={`transition-transform ${collapsed ? '' : 'rotate-90'}`}>
            ▶
          </span>
          <span>运行日志</span>
          <span className="rounded-full bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">
            {total}
          </span>
        </button>
        <div className="flex items-center gap-2">
          {!collapsed && (
            <>
              <div className="flex items-center gap-1 rounded-md bg-gray-800 p-0.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => setTab('logs')}
                  className={`rounded px-2 py-0.5 ${
                    tab === 'logs' ? 'bg-brand-600 text-white' : 'text-gray-400 hover:text-gray-200'
                  }`}
                >
                  日志 {runLogs.length}
                </button>
                <button
                  type="button"
                  onClick={() => setTab('traces')}
                  className={`rounded px-2 py-0.5 ${
                    tab === 'traces' ? 'bg-brand-600 text-white' : 'text-gray-400 hover:text-gray-200'
                  }`}
                >
                  轨迹 {runTraces.length}
                </button>
              </div>
              <button
                type="button"
                onClick={() => clearRunLogs()}
                className="rounded-md border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:border-danger-700 hover:text-danger-400"
              >
                清空
              </button>
            </>
          )}
        </div>
      </div>

      {/* 展开内容 */}
      {!collapsed && (
        <div className="min-h-0 max-h-64 overflow-y-auto border-t border-gray-800 p-3">
          {tab === 'logs' ? (
            runLogs.length === 0 ? (
              <div className="py-6 text-center text-xs text-gray-600">
                暂无日志，可在工具栏点击「全部试运行」或在属性面板点击「试运行此节点」
              </div>
            ) : (
              <div className="flex flex-col gap-1">
                {runLogs.map((log, idx) => (
                  <div key={idx} className="flex items-start gap-2 font-mono text-xs">
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${logLevelClass(log.level)}`}
                    >
                      {(log.level || 'info').toUpperCase()}
                    </span>
                    {log.node_id && (
                      <span className="shrink-0 text-brand-300">[{log.node_id}]</span>
                    )}
                    <span className={`min-w-0 flex-1 break-words ${logLevelTextClass(log.level)}`}>
                      {log.message}
                    </span>
                    {log.timestamp && (
                      <span className="shrink-0 text-gray-600">{fmtTime(log.timestamp)}</span>
                    )}
                  </div>
                ))}
              </div>
            )
          ) : runTraces.length === 0 ? (
            <div className="py-6 text-center text-xs text-gray-600">
              暂无轨迹数据
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {runTraces.map((tr, idx) => (
                <div
                  key={idx}
                  className="rounded-md border border-gray-800 bg-gray-800/40 p-2 text-xs"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-gray-200">
                        {tr.node_label || tr.node_type || `节点 ${tr.node_id}`}
                      </span>
                      {tr.node_type && (
                        <span className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] text-gray-300">
                          {tr.node_type}
                        </span>
                      )}
                      {tr.node_id && (
                        <span className="font-mono text-[10px] text-brand-300">[{tr.node_id}]</span>
                      )}
                    </div>
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-medium ${traceStatusClass(tr.status)}`}
                    >
                      {tr.status || '-'}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-gray-500">
                    {tr.started_at && <span>开始：{fmtTime(tr.started_at)}</span>}
                    {tr.finished_at && <span>结束：{fmtTime(tr.finished_at)}</span>}
                  </div>
                  {(tr.input || tr.output) && (
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      {tr.input != null && (
                        <div>
                          <div className="mb-0.5 text-[10px] text-gray-500">Input</div>
                          <pre className="max-h-32 overflow-auto rounded bg-gray-950 p-2 font-mono text-[11px] text-gray-300 ring-1 ring-gray-800">
                            {typeof tr.input === 'string' ? tr.input : JSON.stringify(tr.input, null, 2)}
                          </pre>
                        </div>
                      )}
                      {tr.output != null && (
                        <div>
                          <div className="mb-0.5 text-[10px] text-gray-500">Output</div>
                          <pre className="max-h-32 overflow-auto rounded bg-gray-950 p-2 font-mono text-[11px] text-gray-300 ring-1 ring-gray-800">
                            {typeof tr.output === 'string' ? tr.output : JSON.stringify(tr.output, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default RunLogDrawer
