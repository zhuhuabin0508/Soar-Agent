import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import Toolbar from '../components/Toolbar'
import NodeLibrary from '../components/NodeLibrary'
import VariablePanel from '../components/VariablePanel'
import FlowCanvas from '../components/FlowCanvas'
import PropertyPanel from '../components/PropertyPanel'
import WorkflowInspection from '../components/WorkflowInspection'
import WorkflowVersionHistory from '../components/WorkflowVersionHistory'
import RunLogDrawer from '../components/RunLogDrawer'
import { useWorkflowStore } from '../store/workflowStore'
import { useUnsavedChanges } from '../hooks/useUnsavedChanges'
import { useAutoSave } from '../hooks/useAutoSave'
import { workflows as workflowsApi } from '../api/client'

// 工作流编排页：原三栏布局（顶部工具栏 + 左节点库 + 中画布 + 右属性面板）+ 底部日志抽屉
// 支持 URL ?id=xxx 加载已存在的工作流
// 快捷键：Ctrl/Cmd+S 保存、Delete/Backspace 删除选中节点
function WorkflowEditor() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const loadWorkflow = useWorkflowStore((s) => s.loadWorkflow)
  const clearAll = useWorkflowStore((s) => s.clearAll)
  const workflowId = useWorkflowStore((s) => s.workflowId)
  const isDirty = useWorkflowStore((s) => s.isDirty)
  const nodes = useWorkflowStore((s) => s.nodes)
  const edges = useWorkflowStore((s) => s.edges)
  const workflowName = useWorkflowStore((s) => s.workflowName)
  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId)
  const removeNode = useWorkflowStore((s) => s.removeNode)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // 左侧面板 Tab：节点库 / 全局变量
  const [leftTab, setLeftTab] = useState('library')
  // 右侧面板 Tab：属性 / 监测 / 日志
  const [rightTab, setRightTab] = useState('property')

  // 未保存提示 + 自动保存草稿
  useUnsavedChanges(isDirty)
  const { draft, clearDraft } = useAutoSave(
    `soar_workflow_draft_${workflowId || 'new'}`,
    { nodes, edges, name: workflowName },
    30000
  )

  const idParam = searchParams.get('id')

  // 检测到 ?id= 时从后端拉取工作流并灌入 store
  useEffect(() => {
    let alive = true
    if (!idParam) {
      // 进入空白编辑器：清空 store
      clearAll()
      return () => {
        alive = false
      }
    }
    // 如果 store 里已经是该 id，不重复加载
    if (workflowId && String(workflowId) === String(idParam)) {
      return () => {
        alive = false
      }
    }
    setLoading(true)
    setError('')
    ;(async () => {
      try {
        const wf = await workflowsApi.get(idParam)
        if (!alive) return
        loadWorkflow(wf)
      } catch (err) {
        if (!alive) return
        setError(err.message || '加载工作流失败')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idParam])

  // 清理 URL 上的 id 参数后跳到空白编辑器
  const handleClearParam = () => {
    setSearchParams({})
    clearAll()
    navigate('/editor')
  }

  // 快捷键：Ctrl/Cmd+S 触发保存按钮点击；Delete/Backspace 删除选中节点
  // 注意：当焦点在 input/textarea/select 中时不拦截 Delete，避免影响文本编辑
  useEffect(() => {
    const handler = (e) => {
      // Ctrl+S / Cmd+S：触发保存
      if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault()
        const saveBtn = document.querySelector(
          'header button.btn-primary'
        )
        if (saveBtn) saveBtn.click()
        return
      }
      // Delete / Backspace：删除选中节点（仅当焦点不在表单控件中时）
      if (
        (e.key === 'Delete' || e.key === 'Backspace') &&
        selectedNodeId
      ) {
        const tag = (e.target?.tagName || '').toLowerCase()
        if (
          tag === 'input' ||
          tag === 'textarea' ||
          tag === 'select' ||
          e.target?.isContentEditable
        ) {
          return // 不拦截表单内的删除
        }
        e.preventDefault()
        removeNode(selectedNodeId)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectedNodeId, removeNode])

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-900 text-gray-100">
      {/* 顶部工具栏 */}
      <Toolbar />

      {/* 主体三栏：左节点库/变量面板 / 中画布 / 右属性面板 */}
      <div className="flex min-h-0 flex-1">
        <aside className="w-[260px] shrink-0 border-r border-gray-800 bg-gray-900">
          {/* Tab 切换栏 */}
          <div className="flex shrink-0 border-b border-gray-800">
            <button
              type="button"
              onClick={() => setLeftTab('library')}
              className={`flex-1 px-3 py-2 text-xs font-medium transition ${
                leftTab === 'library'
                  ? 'border-b-2 border-brand-500 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              🧩 节点库
            </button>
            <button
              type="button"
              onClick={() => setLeftTab('variables')}
              className={`flex-1 px-3 py-2 text-xs font-medium transition ${
                leftTab === 'variables'
                  ? 'border-b-2 border-brand-500 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              🔣 变量
            </button>
          </div>
          {/* Tab 内容 */}
          <div className="overflow-y-auto" style={{ maxHeight: 'calc(100vh - 120px)' }}>
            {leftTab === 'library' ? <NodeLibrary /> : <VariablePanel />}
          </div>
        </aside>
        <main className="relative min-w-0 flex-1 bg-gray-950">
          {loading && (
            <div className="absolute inset-0 z-dropdown flex items-center justify-center bg-gray-950/70 text-sm text-gray-300">
              加载工作流中...
            </div>
          )}
          {error && (
            <div className="absolute left-1/2 top-3 z-dropdown -translate-x-1/2 rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-red-300">
              {error}
              <button
                type="button"
                onClick={handleClearParam}
                className="ml-3 rounded border border-red-700 px-2 py-0.5 text-xs hover:bg-red-900/40"
              >
                清空并新建
              </button>
            </div>
          )}
          <FlowCanvas />
        </main>
        <aside className="flex w-[360px] shrink-0 flex-col border-l border-gray-800 bg-gray-900">
          {/* 右侧面板 Tab 切换栏 */}
          <div className="flex shrink-0 border-b border-gray-800">
            <button
              type="button"
              onClick={() => setRightTab('property')}
              className={`flex-1 px-3 py-2 text-xs font-medium transition ${
                rightTab === 'property'
                  ? 'border-b-2 border-brand-500 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              ⚙ 属性
            </button>
            <button
              type="button"
              onClick={() => setRightTab('monitor')}
              className={`flex-1 px-3 py-2 text-xs font-medium transition ${
                rightTab === 'monitor'
                  ? 'border-b-2 border-brand-500 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              📈 监测
            </button>
            <button
              type="button"
              onClick={() => setRightTab('versions')}
              className={`flex-1 px-3 py-2 text-xs font-medium transition ${
                rightTab === 'versions'
                  ? 'border-b-2 border-brand-500 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              📦 版本
            </button>
          </div>
          {/* Tab 内容 */}
          <div className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden">
            {rightTab === 'property' && <PropertyPanel />}
            {rightTab === 'monitor' && (
              <WorkflowInspection workflowId={workflowId} />
            )}
            {rightTab === 'versions' && (
              <WorkflowVersionHistory workflowId={workflowId} />
            )}
          </div>
        </aside>
      </div>

      {/* 底部运行日志抽屉 */}
      <RunLogDrawer />
    </div>
  )
}

export default WorkflowEditor
