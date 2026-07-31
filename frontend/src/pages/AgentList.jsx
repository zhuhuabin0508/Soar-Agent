import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { agents as agentsApi } from '../api/client'
import { Modal } from '../components/Dialog'
import { inputCls } from '../components/property/FormControls'

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 智能体列表：列出 GET /agents，支持新建/编辑跳转、测试、删除
function AgentList() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 测试相关状态
  const [testOpen, setTestOpen] = useState(false)
  const [testAgent, setTestAgent] = useState(null)
  const [testInput, setTestInput] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [resultErr, setResultErr] = useState('')
  const [resultOpen, setResultOpen] = useState(false)

  // 列表搜索关键字
  const [search, setSearch] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await agentsApi.list()
      setRows(Array.isArray(data) ? data : [])
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

  const handleDelete = async (id, name) => {
    if (!window.confirm(`确定删除智能体「${name || id}」吗？`)) return
    try {
      await agentsApi.remove(id)
      setRows((prev) => prev.filter((r) => r.id !== id))
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  // 打开测试弹窗
  const openTest = (agent) => {
    setTestAgent(agent)
    setTestInput('')
    setTestOpen(true)
  }

  // 执行测试：POST /agents/{id}/test body={input}
  const handleTest = async () => {
    if (!testAgent) return
    setRunning(true)
    setResultErr('')
    try {
      const res = await agentsApi.test(testAgent.id, testInput)
      setResult(res)
      setResultOpen(true)
      setTestOpen(false)
    } catch (err) {
      setResultErr(err.message || String(err))
      setResultOpen(true)
      setTestOpen(false)
    } finally {
      setRunning(false)
    }
  }

  // 按名称过滤列表
  const filteredRows = search
    ? rows.filter((r) => (r.name || '').toLowerCase().includes(search.toLowerCase()))
    : rows

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-100">智能体</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={load}
            className="btn-secondary btn-sm"
          >
            刷新
          </button>
          <button
            type="button"
            onClick={() => navigate('/agent-tutorial')}
            className="btn-secondary btn-sm"
            title="查看智能体配置教程"
          >
            📖 使用教程
          </button>
          <button
            type="button"
            onClick={() => navigate('/agents/new')}
            className="btn-primary btn-sm"
          >
            + 新建智能体
          </button>
        </div>
      </header>

      <div className="flex items-center gap-3 px-6 py-3">
        <input
          className="max-w-sm flex-1 rounded-md border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          placeholder="搜索智能体名称..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-xs text-gray-500">共 {filteredRows.length} / {rows.length} 个</span>
      </div>

      <div className="min-w-0 flex-1 overflow-y-auto p-6">
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
            <div className="text-4xl">🤖</div>
            <div className="text-sm">暂无智能体</div>
          </div>
        ) : (
          <div className="w-full overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full table-fixed border-collapse text-sm">
              <thead className="bg-gray-900 text-gray-400">
                <tr>
                  <th className="w-20 px-4 py-3 text-left font-medium">ID</th>
                  <th className="px-4 py-3 text-left font-medium">名称</th>
                  <th className="w-40 px-4 py-3 text-left font-medium">模型配置</th>
                  <th className="w-32 px-4 py-3 text-left font-medium">迭代上限</th>
                  <th className="w-52 px-4 py-3 text-left font-medium">更新时间</th>
                  <th className="w-72 px-4 py-3 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((r, idx) => (
                  <tr
                    key={r.id}
                    className={`border-t border-gray-800 transition-colors hover:bg-brand-500/5 ${
                      idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-brand-300">#{r.id}</td>
                    <td className="truncate px-4 py-3 text-gray-200">{r.name || '-'}</td>
                    <td className="truncate px-4 py-3 text-gray-300">
                      {r.model_config_id ?? '-'}
                    </td>
                    <td className="px-4 py-3 text-gray-300">{r.max_iterations ?? '-'}</td>
                    <td className="px-4 py-3 text-gray-400">{fmtTime(r.updated_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => navigate(`/agents/${r.id}/edit`)}
                          className="btn-secondary btn-sm"
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          onClick={() => navigate(`/agents/${r.id}/monitor`)}
                          className="btn-secondary btn-sm"
                        >
                          监控
                        </button>
                        <button
                          type="button"
                          disabled={running && testAgent?.id === r.id}
                          onClick={() => openTest(r)}
                          className="btn-secondary btn-sm"
                        >
                          测试
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(r.id, r.name)}
                          className="btn-danger btn-sm"
                        >
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 测试输入弹窗 */}
      <Modal
        open={testOpen}
        title={`测试智能体${testAgent ? `：${testAgent.name || ''}` : ''}`}
        onClose={() => setTestOpen(false)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setTestOpen(false)}
              className="btn-secondary"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleTest}
              disabled={running}
              className="btn-primary"
            >
              {running ? '运行中…' : '开始测试'}
            </button>
          </>
        }
      >
        <label className="mb-1 block text-xs text-gray-400">输入文本（input）</label>
        <textarea
          className={`${inputCls} resize-y`}
          rows={5}
          value={testInput}
          onChange={(e) => setTestInput(e.target.value)}
          placeholder="请输入待测试的告警/事件描述…"
        />
      </Modal>

      {/* 测试结果弹窗 */}
      <Modal
        open={resultOpen}
        title="智能体测试结果"
        onClose={() => setResultOpen(false)}
        maxWidth="max-w-3xl"
        footer={
          <button
            type="button"
            onClick={() => setResultOpen(false)}
            className="btn-primary"
          >
            关闭
          </button>
        }
      >
        {resultErr ? (
          <div className="rounded-md border border-danger-500/40 bg-danger-500/10 p-4 text-sm text-danger-300">
            {resultErr}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid w-full grid-cols-2 gap-4">
              <div className="rounded-md border border-gray-800 bg-gray-900/60 p-4">
                <div className="text-xs text-gray-500">decision</div>
                <div className="mt-1 font-mono text-sm text-brand-300">
                  {result?.decision ?? '-'}
                </div>
              </div>
              <div className="rounded-md border border-gray-800 bg-gray-900/60 p-4">
                <div className="text-xs text-gray-500">target_ip</div>
                <div className="mt-1 font-mono text-sm text-gray-200">
                  {result?.target_ip ?? '-'}
                </div>
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">reason</div>
              <div className="mt-1 rounded-md bg-gray-950 p-4 text-sm text-gray-200 ring-1 ring-gray-800">
                {result?.reason || '-'}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">duration</div>
              <div className="mt-1 font-mono text-sm text-gray-300">{result?.duration ?? '-'}</div>
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">
                推理过程 messages（{(result?.messages || []).length} 条）
              </div>
              <div className="max-h-72 w-full overflow-auto rounded-md bg-gray-950 p-4 ring-1 ring-gray-800">
                {(result?.messages || []).length === 0 ? (
                  <div className="text-xs text-gray-600">暂无消息</div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {result.messages.map((m, idx) => (
                      <div key={idx} className="border-b border-gray-800 pb-2 last:border-0">
                        <div className="mb-1 flex items-center gap-2">
                          <span className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] text-gray-300">
                            {m.role || '-'}
                          </span>
                        </div>
                        <pre className="whitespace-pre-wrap break-words font-mono text-xs text-gray-300">
                          {typeof m.content === 'string' ? m.content : JSON.stringify(m.content, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">
                日志（{(result?.logs || []).length} 条）
              </div>
              <div className="max-h-48 w-full overflow-auto rounded-md bg-gray-950 p-4 ring-1 ring-gray-800">
                {(result?.logs || []).length === 0 ? (
                  <div className="text-xs text-gray-600">暂无日志</div>
                ) : (
                  <div className="flex flex-col gap-1">
                    {result.logs.map((log, idx) => (
                      <div key={idx} className="font-mono text-xs">
                        <span className="mr-2 text-gray-400">[{(log.level || 'info').toUpperCase()}]</span>
                        <span className="text-gray-300">{log.message}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

export default AgentList
