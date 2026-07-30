import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getExecutions } from '../api/executions'
import { workflows as workflowsApi } from '../api/client'

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 状态标签颜色
function statusClass(status) {
  switch ((status || '').toLowerCase()) {
    case 'success':
      return 'bg-success-500/20 text-success-300'
    case 'failed':
    case 'error':
      return 'bg-danger-500/20 text-danger-300'
    case 'running':
      return 'bg-brand-500/20 text-brand-300'
    case 'waiting_for_approval':
    case 'waiting':
      return 'bg-warning-500/20 text-warning-300'
    default:
      return 'bg-gray-700 text-gray-300'
  }
}

// 触发类型标签
function triggerLabel(t) {
  switch ((t || '').toLowerCase()) {
    case 'webhook':
      return 'Webhook'
    case 'test_run':
      return '流程测试'
    case 'manual':
      return '手动'
    case 'agent_test':
      return '智能体测试'
    default:
      return t || '-'
  }
}

const PAGE_SIZE = 50
const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'running', label: '运行中' },
  { value: 'waiting_for_approval', label: '待审批' },
]

// 执行列表页
function ExecutionList() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  // 工作流列表（用于筛选下拉）
  const [workflows, setWorkflows] = useState([])
  // 已提交的筛选条件
  const [filters, setFilters] = useState({ workflowId: '', status: '' })
  // 输入框临时值
  const [input, setInput] = useState({ workflowId: '', status: '' })

  // 加载工作流列表（仅一次）
  useEffect(() => {
    ;(async () => {
      try {
        const data = await workflowsApi.list()
        setWorkflows(Array.isArray(data) ? data : [])
      } catch {
        // 工作流列表加载失败不阻断主流程，下拉仍可用“全部”
        setWorkflows([])
      }
    })()
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getExecutions(
        PAGE_SIZE,
        offset,
        filters.workflowId || null,
        filters.status || null
      )
      const arr = Array.isArray(data) ? data : []
      setRows(arr)
      // 后端 list 接口未返回 total，用当前页条数估算（满页则可能有下一页）
      setTotal(arr.length)
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
      setRows([])
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
  }

  const handleReset = () => {
    setInput({ workflowId: '', status: '' })
    setOffset(0)
    setFilters({ workflowId: '', status: '' })
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const canPrev = offset > 0
  const canNext = rows.length === PAGE_SIZE

  const selectCls =
    'rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white outline-none focus:border-brand-500'

  // 工作流名映射：workflow_id -> name
  const wfNameMap = {}
  workflows.forEach((w) => {
    wfNameMap[w.id] = w.name
  })

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      {/* 顶部标题栏 */}
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <h1 className="text-xl font-semibold text-gray-100">执行追溯</h1>
        <span className="text-xs text-gray-500">共 {rows.length} 条记录</span>
      </header>

      {/* 内容滚动区 */}
      <div className="min-w-0 flex-1 overflow-y-auto p-6">
        {/* 筛选栏 */}
        <div className="mb-4 flex flex-wrap items-center gap-4 rounded-lg border border-gray-800 bg-gray-900/60 p-4">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-400">工作流</span>
            <select
              value={input.workflowId}
              onChange={(e) => setInput((p) => ({ ...p, workflowId: e.target.value }))}
              className={selectCls}
            >
              <option value="">全部</option>
              {workflows.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-400">状态</span>
            <select
              value={input.status}
              onChange={(e) => setInput((p) => ({ ...p, status: e.target.value }))}
              className={selectCls}
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <button type="button" onClick={handleQuery} className="btn-primary btn-sm">
            查询
          </button>
          <button type="button" onClick={handleReset} className="btn-secondary btn-sm">
            重置
          </button>
        </div>

        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : rows.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">📜</div>
            <div className="text-sm">暂无执行记录</div>
          </div>
        ) : (
          <div className="w-full overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full min-w-[900px] table-fixed border-collapse text-sm">
              <thead className="bg-gray-900 text-gray-400">
                <tr>
                  <th className="w-20 px-4 py-3 text-left font-medium">ID</th>
                  <th className="w-40 px-4 py-3 text-left font-medium">工作流</th>
                  <th className="w-28 px-4 py-3 text-left font-medium">触发类型</th>
                  <th className="w-32 px-4 py-3 text-left font-medium">状态</th>
                  <th className="px-4 py-3 text-left font-medium">创建时间</th>
                  <th className="px-4 py-3 text-left font-medium">完成时间</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, idx) => (
                  <tr
                    key={r.id}
                    onClick={() => navigate(`/executions/${r.id}`)}
                    className={`cursor-pointer border-t border-gray-800 transition-colors hover:bg-brand-500/10 ${
                      idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-brand-300">#{r.id}</td>
                    <td className="truncate px-4 py-3 text-gray-300" title={r.workflow_id ? wfNameMap[r.workflow_id] || `#${r.workflow_id}` : '智能体测试'}>
                      {r.workflow_id
                        ? wfNameMap[r.workflow_id] || `工作流 #${r.workflow_id}`
                        : <span className="text-gray-500">—（智能体测试）</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[11px] text-gray-300">
                        {triggerLabel(r.trigger_type)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusClass(r.status)}`}>
                        {r.status || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-400">{fmtTime(r.created_at)}</td>
                    <td className="px-4 py-3 text-gray-400">{fmtTime(r.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* 分页 */}
        {!loading && rows.length > 0 && (
          <div className="mt-4 flex items-center justify-between text-xs text-gray-400">
            <span>第 {currentPage} 页</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => canPrev && setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={!canPrev}
                className="btn-secondary btn-sm"
              >
                上一页
              </button>
              <button
                type="button"
                onClick={() => canNext && setOffset(offset + PAGE_SIZE)}
                disabled={!canNext}
                className="btn-secondary btn-sm"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default ExecutionList
