import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { workflows as workflowsApi } from '../api/client'
import { JsonInputDialog, Modal } from '../components/Dialog'

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 工作流管理列表：列出 GET /workflows，支持新建、编辑（跳转 /editor?id=）、试运行、删除
function WorkflowList() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 全部试运行相关
  const [testOpen, setTestOpen] = useState(false)
  const [testWf, setTestWf] = useState(null)
  const [running, setRunning] = useState(false)
  const [runResult, setRunResult] = useState(null)
  const [runErr, setRunErr] = useState('')
  const [resultOpen, setResultOpen] = useState(false)

  // webhook 密钥查看/重置
  const [secretOpen, setSecretOpen] = useState(false)
  const [secretWf, setSecretWf] = useState(null)
  const [secretValue, setSecretValue] = useState('')
  const [secretLoading, setSecretLoading] = useState(false)
  const [resetting, setResetting] = useState(false)

  // 列表搜索关键字
  const [search, setSearch] = useState('')

  // 拉取列表
  const load = useCallback(async () => {
    try {
      const data = await workflowsApi.list()
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

  // 删除工作流
  const handleDelete = async (id, name) => {
    if (!window.confirm(`确定删除工作流「${name || id}」吗？此操作不可撤销。`)) return
    try {
      await workflowsApi.remove(id)
      setRows((prev) => prev.filter((r) => r.id !== id))
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  // 跳转到编辑器加载该工作流
  const handleEdit = (id) => {
    navigate(`/editor?id=${id}`)
  }

  // 复制工作流：拉取详情后以「原名称_副本」创建新工作流
  const [copying, setCopying] = useState(false)
  const handleCopy = async (wf) => {
    if (copying) return
    if (!window.confirm(`确定复制工作流「${wf.name || wf.id}」吗？将创建一个副本。`)) return
    setCopying(true)
    try {
      const detail = await workflowsApi.get(wf.id)
      const body = {
        name: `${detail.name || '未命名'}_副本`,
        graph_config: detail.graph_config || { nodes: [], edges: [] },
      }
      await workflowsApi.create(body)
      await load()
      window.alert('工作流已复制')
    } catch (err) {
      window.alert(`复制失败：${err.message || err}`)
    } finally {
      setCopying(false)
    }
  }

  // 导出工作流为 JSON 文件
  const handleExport = async (wf) => {
    try {
      const detail = await workflowsApi.get(wf.id)
      const exportData = {
        _type: 'soar_workflow_export',
        _version: '1.0',
        name: detail.name || '未命名工作流',
        exported_at: new Date().toISOString(),
        graph_config: detail.graph_config || { nodes: [], edges: [] },
      }
      const json = JSON.stringify(exportData, null, 2)
      const blob = new Blob([json], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const safeName = (detail.name || 'workflow').replace(/[^\w\u4e00-\u9fa5-]/g, '_')
      a.href = url
      a.download = `${safeName}_${Date.now()}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      window.alert(`导出失败：${err.message || err}`)
    }
  }

  // 试运行
  const handleTestRun = async (payload) => {
    setTestOpen(false)
    if (!testWf) return
    setRunning(true)
    setRunErr('')
    try {
      const res = await workflowsApi.testRun(testWf.id, payload)
      setRunResult(res)
      setResultOpen(true)
    } catch (err) {
      setRunErr(err.message || String(err))
      setResultOpen(true)
    } finally {
      setRunning(false)
    }
  }

  // 查看 webhook 密钥（列表不返回，需调详情接口）
  const handleViewSecret = async (wf) => {
    setSecretWf(wf)
    setSecretOpen(true)
    setSecretValue('')
    setSecretLoading(true)
    try {
      const detail = await workflowsApi.get(wf.id)
      setSecretValue(detail.webhook_secret || '(未配置)')
    } catch (err) {
      setSecretValue(`获取失败：${err.message || err}`)
    } finally {
      setSecretLoading(false)
    }
  }

  // 重置 webhook 密钥
  const handleResetSecret = async () => {
    if (!secretWf) return
    if (!window.confirm(`确定重置工作流「${secretWf.name || secretWf.id}」的 Webhook 密钥吗？旧密钥将立即失效。`)) return
    setResetting(true)
    try {
      const res = await workflowsApi.resetSecret(secretWf.id)
      setSecretValue(res.webhook_secret || '(未返回)')
    } catch (err) {
      window.alert(`重置失败：${err.message || err}`)
    } finally {
      setResetting(false)
    }
  }

  // 复制密钥到剪贴板
  const handleCopySecret = async () => {
    if (!secretValue || secretValue.startsWith('(')) return
    try {
      await navigator.clipboard.writeText(secretValue)
      window.alert('密钥已复制到剪贴板')
    } catch {
      window.alert('复制失败，请手动选择复制')
    }
  }

  // 按名称过滤列表
  const filteredRows = search
    ? rows.filter((r) => (r.name || '').toLowerCase().includes(search.toLowerCase()))
    : rows

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      {/* 顶部标题栏 */}
      <header className="flex items-center justify-between gap-4 border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-100">工作流管理</h1>
          <span className="text-xs text-gray-500">共 {rows.length} 个</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={load}
            className="btn-secondary btn-sm"
          >
            刷新
          </button>
          <button
            type="button"
            onClick={() => navigate('/editor')}
            className="btn-primary btn-sm"
          >
            + 新建工作流
          </button>
        </div>
      </header>

      <div className="px-6 pb-3">
        <input
          className="w-full max-w-sm rounded-md border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          placeholder="搜索工作流名称..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* 内容滚动区 */}
      <div className="flex-1 overflow-y-auto p-6">
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
            <div className="text-4xl">📁</div>
            <div className="text-sm">暂无工作流，点击右上角「新建工作流」创建</div>
          </div>
        ) : (
          <div className="w-full overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full min-w-[900px] table-fixed border-collapse text-sm">
              <thead className="bg-gray-900 text-gray-400">
                <tr>
                  <th className="w-20 px-4 py-3 text-left font-medium">ID</th>
                  <th className="px-4 py-3 text-left font-medium">名称</th>
                  <th className="w-56 px-4 py-3 text-left font-medium">创建时间</th>
                  <th className="w-56 px-4 py-3 text-left font-medium">更新时间</th>
                  <th className="w-20 px-4 py-3 text-left font-medium">启用</th>
                  <th className="w-[420px] px-4 py-3 text-left font-medium">操作</th>
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
                    <td className="truncate px-4 py-3 font-mono text-brand-300">#{r.id}</td>
                    <td className="truncate px-4 py-3 text-gray-200">{r.name || '-'}</td>
                    <td className="px-4 py-3 text-gray-400">{fmtTime(r.created_at)}</td>
                    <td className="px-4 py-3 text-gray-400">{fmtTime(r.updated_at)}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-[10px] ${
                          r.enabled
                            ? 'bg-success-500/15 text-success-300'
                            : 'bg-gray-700 text-gray-400'
                        }`}
                      >
                        {r.enabled ? '启用' : '禁用'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => handleEdit(r.id)}
                          className="btn-secondary btn-sm"
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          disabled={copying}
                          onClick={() => handleCopy(r)}
                          className="btn-secondary btn-sm"
                        >
                          复制
                        </button>
                        <button
                          type="button"
                          onClick={() => handleExport(r)}
                          className="btn-secondary btn-sm"
                        >
                          导出
                        </button>
                        <button
                          type="button"
                          disabled={running && testWf?.id === r.id}
                          onClick={() => {
                            setTestWf(r)
                            setTestOpen(true)
                          }}
                          className="btn-secondary btn-sm"
                        >
                          试运行
                        </button>
                        <button
                          type="button"
                          onClick={() => handleViewSecret(r)}
                          className="btn-secondary btn-sm"
                        >
                          密钥
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

      {/* 全部试运行输入弹窗 */}
      <JsonInputDialog
        open={testOpen}
        title={`试运行工作流「${testWf?.name || ''}」 · 输入示例 payload（JSON）`}
        onClose={() => setTestOpen(false)}
        onSubmit={handleTestRun}
        submitText="开始运行"
      />

      {/* 试运行结果弹窗 */}
      <Modal
        open={resultOpen}
        title={`试运行结果${testWf ? `：${testWf.name || ''}` : ''}`}
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
        {runErr ? (
          <div className="rounded-md border border-danger-500/40 bg-danger-500/10 p-4 text-sm text-danger-300">
            {runErr}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="text-sm text-gray-300">
              状态：<span className="font-mono text-brand-300">{runResult?.status || '-'}</span>
              {runResult?.execution_id != null && (
                <span className="ml-3 text-xs text-gray-500">execution_id: {runResult.execution_id}</span>
              )}
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">
                节点轨迹（{(runResult?.traces || []).length} 个）
              </div>
              <div className="max-h-72 w-full overflow-auto rounded-md bg-gray-950 p-3 ring-1 ring-gray-800">
                {(runResult?.traces || []).length === 0 ? (
                  <div className="text-xs text-gray-600">暂无轨迹</div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {runResult.traces.map((tr, idx) => (
                      <div key={idx} className="rounded-md border border-gray-800 bg-gray-900/60 p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-gray-200">
                            {tr.node_label || tr.node_type || `节点 ${tr.node_id}`}
                          </span>
                          <span className="rounded bg-gray-700 px-2 py-0.5 text-[10px] text-gray-300">
                            {tr.status || '-'}
                          </span>
                        </div>
                        <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-gray-300">
                          {typeof tr.output === 'string' ? tr.output : JSON.stringify(tr.output, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">
                日志（{(runResult?.logs || []).length} 条）
              </div>
              <div className="max-h-64 w-full overflow-auto rounded-md bg-gray-950 p-3 ring-1 ring-gray-800">
                {(runResult?.logs || []).length === 0 ? (
                  <div className="text-xs text-gray-600">暂无日志</div>
                ) : (
                  <div className="flex flex-col gap-1">
                    {runResult.logs.map((log, idx) => (
                      <div key={idx} className="font-mono text-xs">
                        <span className="mr-2 text-gray-400">[{(log.level || 'info').toUpperCase()}]</span>
                        {log.node_id && (
                          <span className="mr-2 text-brand-300">[{log.node_id}]</span>
                        )}
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

      {/* Webhook 密钥查看/重置弹窗 */}
      <Modal
        open={secretOpen}
        title={`Webhook 密钥${secretWf ? `：${secretWf.name || ''}` : ''}`}
        onClose={() => setSecretOpen(false)}
        maxWidth="max-w-xl"
        footer={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopySecret}
              disabled={secretLoading || !secretValue || secretValue.startsWith('(')}
              className="btn-secondary btn-sm"
            >
              复制密钥
            </button>
            <button
              type="button"
              onClick={handleResetSecret}
              disabled={resetting || secretLoading}
              className="btn-secondary btn-sm"
            >
              {resetting ? '重置中...' : '重置密钥'}
            </button>
            <button
              type="button"
              onClick={() => setSecretOpen(false)}
              className="btn-primary btn-sm"
            >
              关闭
            </button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="rounded-md border border-gray-800 bg-gray-950 p-4">
            <div className="mb-1 text-xs text-gray-500">调用 webhook 时需在请求头携带：</div>
            <div className="font-mono text-[11px] text-brand-300">
              X-Webhook-Secret: &lt;下方密钥&gt;
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs text-gray-500">Webhook 密钥</div>
            {secretLoading ? (
              <div className="text-sm text-gray-500">加载中...</div>
            ) : (
              <div className="max-h-32 overflow-auto rounded-md bg-gray-950 p-3 ring-1 ring-gray-800">
                <code className="break-all font-mono text-xs text-warning-300">
                  {secretValue || '-'}
                </code>
              </div>
            )}
          </div>
          <div className="rounded-md border border-warning-500/30 bg-warning-500/5 px-3 py-2 text-[11px] text-warning-400/80">
            ⚠️ 密钥仅在工作流启用且请求头匹配时允许触发。重置后旧密钥立即失效，需同步更新调用方配置。
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default WorkflowList
