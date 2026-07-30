import { useEffect, useState, useCallback } from 'react'
import request from '../api/client'

// 格式化时间
function fmtTime(t) {
  if (!t) return ''
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(t)
  }
}

// 从 graph_config 中提取节点数与连线数，兼容多种结构
function graphSummary(graphConfig) {
  if (!graphConfig || typeof graphConfig !== 'object') return { nodes: 0, edges: 0 }
  // 节点：nodes 数组优先，其次 node array
  const nodes =
    Array.isArray(graphConfig.nodes) ? graphConfig.nodes :
    Array.isArray(graphConfig.node) ? graphConfig.node : []
  // 连线：edges / connections / links
  const edges =
    Array.isArray(graphConfig.edges) ? graphConfig.edges :
    Array.isArray(graphConfig.connections) ? graphConfig.connections :
    Array.isArray(graphConfig.links) ? graphConfig.links : []
  return { nodes: nodes.length, edges: edges.length }
}

// 工作流版本历史面板：在工作流编辑器右侧面板展示版本记录
function WorkflowVersionHistory({ workflowId }) {
  const [versions, setVersions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // 当前展开详情的版本 id（null 表示全部折叠）
  const [expandedId, setExpandedId] = useState(null)
  // 详情缓存：id -> version 详情（含 snapshot）
  const [detailCache, setDetailCache] = useState({})
  const [loadingIds, setLoadingIds] = useState({})
  const [detailErr, setDetailErr] = useState({})
  // 操作中的版本 id 集合（创建/回滚）
  const [actingIds, setActingIds] = useState({})
  // 临时成功提示
  const [toast, setToast] = useState('')

  // 临时提示：3 秒后自动消失
  const showToast = useCallback((msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }, [])

  // 拉取版本列表
  const load = useCallback(async () => {
    if (!workflowId) {
      setVersions([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await request(`/workflows/${workflowId}/versions`)
      const list = Array.isArray(data) ? data : (data?.items || data?.versions || [])
      // 按 version_number 降序
      const sorted = [...list].sort((a, b) => {
        const va = Number(a?.version_number) || 0
        const vb = Number(b?.version_number) || 0
        return vb - va
      })
      setVersions(sorted)
    } catch (err) {
      setError(err.message || '加载版本列表失败')
      setVersions([])
    } finally {
      setLoading(false)
    }
  }, [workflowId])

  useEffect(() => {
    load()
  }, [load])

  // 创建版本：prompt 输入变更说明后调用 POST；用户取消（返回 null）则中止
  const handleCreate = useCallback(async () => {
    const note = window.prompt('请输入版本变更说明', '')
    if (note === null) return
    setActingIds((m) => ({ ...m, __create: true }))
    try {
      await request(`/workflows/${workflowId}/versions`, {
        method: 'POST',
        body: { change_note: note },
      })
      showToast('版本创建成功')
      await load()
    } catch (err) {
      setError(err.message || '创建版本失败')
    } finally {
      setActingIds((m) => ({ ...m, __create: false }))
    }
  }, [workflowId, load, showToast])

  // 展开详情：按需拉取版本详情并缓存
  const toggleDetail = useCallback(
    async (versionId) => {
      if (expandedId === versionId) {
        setExpandedId(null)
        return
      }
      setExpandedId(versionId)
      if (detailCache[versionId]) return
      setLoadingIds((m) => ({ ...m, [versionId]: true }))
      setDetailErr((m) => ({ ...m, [versionId]: '' }))
      try {
        const data = await request(`/workflows/${workflowId}/versions/${versionId}`)
        setDetailCache((m) => ({ ...m, [versionId]: data || {} }))
      } catch (err) {
        setDetailErr((m) => ({ ...m, [versionId]: err.message || '加载详情失败' }))
      } finally {
        setLoadingIds((m) => ({ ...m, [versionId]: false }))
      }
    },
    [expandedId, detailCache, workflowId]
  )

  // 回滚到指定版本：confirm 确认后调用 rollback
  const handleRollback = useCallback(
    async (versionId, versionNumber) => {
      const ok = window.confirm(
        `确定要回滚到版本 v${versionNumber} 吗？当前工作流配置将被覆盖。`
      )
      if (!ok) return
      setActingIds((m) => ({ ...m, [versionId]: true }))
      try {
        await request(`/workflows/${workflowId}/versions/${versionId}/rollback`, {
          method: 'POST',
        })
        showToast('已回滚到该版本')
        await load()
      } catch (err) {
        setError(err.message || '回滚失败')
      } finally {
        setActingIds((m) => ({ ...m, [versionId]: false }))
      }
    },
    [workflowId, load, showToast]
  )

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
      {/* 顶部标题 + 创建版本按钮 */}
      <div className="shrink-0 border-b border-gray-800 px-3 py-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-300">
            版本历史
          </h2>
          <button
            type="button"
            onClick={handleCreate}
            disabled={!!actingIds.__create}
            className="btn-primary btn-sm"
          >
            {actingIds.__create ? '创建中…' : '创建版本'}
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="shrink-0 border-b border-red-700/40 bg-red-900/20 px-3 py-1.5 text-[11px] text-red-300">
          {error}
        </div>
      )}

      {/* 成功提示 toast */}
      {toast && (
        <div className="shrink-0 border-b border-success-700/40 bg-success-900/20 px-3 py-1.5 text-[11px] text-success-300">
          {toast}
        </div>
      )}

      {/* 内容区：可滚动 */}
      <div className="min-w-0 flex-1 overflow-y-auto">
        {loading ? (
          <div className="py-8 text-center text-[11px] text-gray-500">加载中…</div>
        ) : versions.length === 0 ? (
          <div className="py-8 text-center text-[11px] text-gray-600">
            暂无版本记录，点击上方按钮创建第一个版本
          </div>
        ) : (
          <div className="flex flex-col gap-2 p-3">
            {versions.map((v) => {
              const vid = v.id
              const expanded = expandedId === vid
              const detail = detailCache[vid]
              const isLoadingDetail = loadingIds[vid]
              const detailError = detailErr[vid]
              const isActing = actingIds[vid]
              // 详情快照：优先用详情接口返回的 snapshot，其次列表项自带的 snapshot
              const snapshot = detail?.snapshot || v.snapshot || {}
              const summary = graphSummary(snapshot.graph_config)
              return (
                <div
                  key={vid}
                  className="rounded-md border border-gray-800 bg-gray-900/40 hover:bg-gray-800/60"
                >
                  {/* 版本摘要行 */}
                  <div className="flex flex-col gap-1 px-2.5 py-2">
                    <div className="flex items-center gap-2">
                      <span className="shrink-0 rounded bg-brand-500/20 px-1.5 py-0.5 text-[10px] font-medium text-brand-300">
                        v{v.version_number}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[11px] text-gray-300">
                        {v.change_note || '（无变更说明）'}
                      </span>
                    </div>
                    {/* 第二行：创建时间 + 创建者 */}
                    <div className="flex items-center gap-2 pl-0.5 text-[10px] text-gray-500">
                      <span>{fmtTime(v.created_at) || '-'}</span>
                      <span className="text-gray-600">·</span>
                      <span className="truncate">{v.created_by || '未知'}</span>
                    </div>
                    {/* 操作按钮 */}
                    <div className="mt-1 flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => toggleDetail(vid)}
                        className="rounded border border-gray-700 px-2 py-0.5 text-[10px] text-gray-300 hover:border-brand-600 hover:text-brand-300"
                      >
                        {expanded ? '收起' : '查看详情'}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleRollback(vid, v.version_number)}
                        disabled={!!isActing}
                        className="rounded border border-orange-700/50 px-2 py-0.5 text-[10px] text-orange-300 hover:border-red-600 hover:text-red-300 disabled:opacity-50"
                      >
                        {isActing ? '回滚中…' : '回滚到此版本'}
                      </button>
                    </div>
                  </div>

                  {/* 展开内容：snapshot 摘要 */}
                  {expanded && (
                    <div className="border-t border-gray-800 p-2.5">
                      {isLoadingDetail && (
                        <div className="py-3 text-center text-[11px] text-gray-500">
                          加载详情…
                        </div>
                      )}
                      {detailError && (
                        <div className="rounded border border-red-700/40 bg-red-900/20 p-2 text-[11px] text-red-300">
                          {detailError}
                        </div>
                      )}
                      {detail && (
                        <div className="flex flex-col gap-1.5 text-[11px]">
                          <div className="flex items-center gap-1.5">
                            <span className="text-gray-500">名称：</span>
                            <span className="min-w-0 flex-1 truncate text-gray-200">
                              {snapshot.name || '（未命名）'}
                            </span>
                          </div>
                          <div className="flex items-center gap-3">
                            <div className="flex items-center gap-1.5">
                              <span className="text-gray-500">节点数：</span>
                              <span className="font-mono text-brand-300">{summary.nodes}</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <span className="text-gray-500">连线数：</span>
                              <span className="font-mono text-brand-300">{summary.edges}</span>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default WorkflowVersionHistory
