import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactFlow, {
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
} from 'reactflow'
import {
  Columns3, Rows3, LayoutGrid, Undo2, Redo2, Maximize2, Maximize, Minimize2,
  Copy, Trash2, Pencil, Play, Loader2,
} from 'lucide-react'
import { useWorkflowStore } from '../store/workflowStore'
import { nodeTypes } from './nodes/nodeTypes'
import { getNodeDefinition } from '../constants/nodeCatalog'
import { workflows as workflowsApi } from '../api/client'
import { toast } from '../store/toastStore'
import { Modal } from './Dialog'

// 双击节点快捷改名弹窗
function RenameNodeModal({ open, node, onClose, onConfirm }) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')

  const def = node ? getNodeDefinition(node.type) : null

  // 弹窗打开/目标节点变化时，同步初始值为当前节点的 label / description
  useEffect(() => {
    if (open && node) {
      setName(node.data?.label || '')
      setDesc(node.data?.description || '')
    }
  }, [open, node])

  if (!open || !node) return null

  return (
    <Modal
      open={open}
      title={`编辑节点：${def?.label || node.type}`}
      onClose={onClose}
      maxWidth="max-w-md"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary btn-sm"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => onConfirm(name, desc)}
            className="btn-primary btn-sm"
          >
            确定
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            节点名称
          </label>
          <input
            className="w-full rounded-md border border-border bg-secondary px-2.5 py-1.5 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={`默认：${def?.label || ''}`}
            autoFocus
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            节点描述
          </label>
          <input
            className="w-full rounded-md border border-border bg-secondary px-2.5 py-1.5 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary"
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="可选，备注此节点的用途"
          />
        </div>
      </div>
    </Modal>
  )
}

// 浮动工具栏按钮
function ToolBtn({ title, onClick, disabled, children }) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  )
}

// 右键节点上下文菜单
function ContextMenu({ menu, onClose, onCopy, onDelete, onEdit, onRun, running }) {
  if (!menu) return null
  const { x, y, node } = menu
  // 简单的边界吸附，避免菜单溢出右下视口
  const left = Math.min(x, window.innerWidth - 180)
  const top = Math.min(y, window.innerHeight - 180)
  const def = getNodeDefinition(node?.type)
  const itemCls =
    'flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-xs text-foreground transition hover:bg-accent'
  return (
    <>
      {/* 透明遮罩：点击/右键外部关闭菜单 */}
      <div
        className="fixed inset-0 z-40"
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault()
          onClose()
        }}
      />
      <div
        className="fixed z-50 min-w-[168px] rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl"
        style={{ left, top }}
      >
        <div className="mb-1 truncate border-b border-border px-2.5 pb-1.5 pt-1 text-[11px] text-muted-foreground">
          {def?.label || node?.type}
        </div>
        <button
          type="button"
          onClick={() => onRun(node)}
          className={`${itemCls} text-success`}
        >
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          试运行到此节点
        </button>
        <button type="button" onClick={() => onEdit(node)} className={itemCls}>
          <Pencil className="h-3.5 w-3.5 text-primary" />
          编辑
        </button>
        <button type="button" onClick={() => onCopy(node)} className={itemCls}>
          <Copy className="h-3.5 w-3.5 text-primary" />
          复制
        </button>
        <button
          type="button"
          onClick={() => onDelete(node)}
          className={`${itemCls} text-destructive hover:bg-destructive/10`}
        >
          <Trash2 className="h-3.5 w-3.5" />
          删除
        </button>
      </div>
    </>
  )
}

// 画布内部组件：需要位于 ReactFlowProvider 内部以使用 useReactFlow
function FlowCanvasInner() {
  const { screenToFlowPosition, fitView } = useReactFlow()

  const nodes = useWorkflowStore((s) => s.nodes)
  const edges = useWorkflowStore((s) => s.edges)
  const nodeRunStatus = useWorkflowStore((s) => s.nodeRunStatus)
  const selectedNodeIds = useWorkflowStore((s) => s.selectedNodeIds)
  const onNodesChange = useWorkflowStore((s) => s.onNodesChange)
  const onEdgesChange = useWorkflowStore((s) => s.onEdgesChange)
  const onConnect = useWorkflowStore((s) => s.onConnect)
  const addNode = useWorkflowStore((s) => s.addNode)
  const setSelectedNode = useWorkflowStore((s) => s.setSelectedNode)
  const setSelectedNodes = useWorkflowStore((s) => s.setSelectedNodes)
  const updateNodeData = useWorkflowStore((s) => s.updateNodeData)
  // 多选 / 批量删除
  const removeNodes = useWorkflowStore((s) => s.removeNodes)
  const removeNode = useWorkflowStore((s) => s.removeNode)
  const duplicateNode = useWorkflowStore((s) => s.duplicateNode)
  // 撤销 / 重做 / 自动布局
  const undo = useWorkflowStore((s) => s.undo)
  const redo = useWorkflowStore((s) => s.redo)
  const history = useWorkflowStore((s) => s.history)
  const historyIndex = useWorkflowStore((s) => s.historyIndex)
  const autoLayout = useWorkflowStore((s) => s.autoLayout)
  const alignToGrid = useWorkflowStore((s) => s.alignToGrid)
  // 节点运行状态
  const setNodeRunStatus = useWorkflowStore((s) => s.setNodeRunStatus)

  const canUndo = historyIndex > 0
  const canRedo = historyIndex < history.length - 1

  // 双击改名弹窗状态
  const [renameTarget, setRenameTarget] = useState(null)
  // 右键菜单状态：{ x, y, node } | null
  const [ctxMenu, setCtxMenu] = useState(null)
  // 右键「试运行」中的节点 id
  const [runTargetId, setRunTargetId] = useState(null)
  // 全屏状态
  const wrapRef = useRef(null)
  const [isFullscreen, setIsFullscreen] = useState(false)

  // ============ 派生：节点附加状态 className / zIndex ============
  const displayNodes = useMemo(() => {
    return nodes.map((n) => {
      const status = nodeRunStatus[n.id]
      const extraClass = status === 'running' ? 'node-running' : ''
      const className = [n.className, extraClass].filter(Boolean).join(' ') || undefined
      // group 节点作为背景容器置底，其它节点抬升一档以便覆盖在分组之上
      const zIndex = n.type === 'group' ? 0 : n.zIndex ?? 10
      if (className || zIndex !== n.zIndex) {
        return { ...n, className, zIndex }
      }
      return n
    })
  }, [nodes, nodeRunStatus])

  // ============ 派生：条件分支输出连线自动加标签 ============
  // 从 condition_branch 节点出来的边，根据 sourceHandle 解析实际分支标签
  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const displayEdges = useMemo(() => {
    return edges.map((e) => {
      const src = nodeMap.get(e.source)
      if (src?.type === 'condition_branch' && e.sourceHandle) {
        // 从 sourceHandle ID 解析实际显示标签
        let branchLabel = e.label
        if (!branchLabel) {
          if (e.sourceHandle === 'default') {
            branchLabel = '默认'
          } else if (e.sourceHandle === 'true') {
            branchLabel = src.data?.true_label || '是'
          } else if (e.sourceHandle === 'false') {
            branchLabel = src.data?.false_label || '否'
          } else if (e.sourceHandle.startsWith('br_')) {
            const idx = parseInt(e.sourceHandle.slice(3), 10)
            const cases = src.data?.cases || []
            branchLabel = cases[idx]?.label || `分支${idx + 1}`
          } else {
            branchLabel = e.sourceHandle
          }
        }
        return {
          ...e,
          label: branchLabel,
          labelStyle: { fontSize: 11, fill: '#fff', fontWeight: 600 },
          labelBgStyle: { fill: '#6366f1' },
          labelBgPadding: [6, 3],
          labelBgBorderRadius: 4,
        }
      }
      return e
    })
  }, [edges, nodeMap])

  // 选中的连线 id（用 ref 暂存，避免额外渲染；快捷键删除时读取）
  const selectedEdgeIdsRef = useRef([])

  // ============ 选中变化：同步多选集合到 store ============
  const onSelectionChange = useCallback(
    ({ nodes: selNodes, edges: selEdges }) => {
      setSelectedNodes(selNodes.map((n) => n.id))
      selectedEdgeIdsRef.current = (selEdges || []).map((e) => e.id)
    },
    [setSelectedNodes]
  )

  // 拖拽悬停：允许 drop
  const onDragOver = useCallback((e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  // 放下：读取节点类型，计算落点坐标并创建节点
  // 对 tool 类型，额外读取工具名并注入到节点 data
  const onDrop = useCallback(
    (e) => {
      e.preventDefault()
      const type = e.dataTransfer.getData('application/reactflow')
      if (!type) return
      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })
      if (type === 'tool') {
        const toolName = e.dataTransfer.getData('application/reactflow-tool-name')
        addNode(type, position, toolName ? { tool_name: toolName } : null)
      } else {
        addNode(type, position)
      }
    },
    [screenToFlowPosition, addNode]
  )

  // 双击节点：打开快捷改名弹窗
  const onNodeDoubleClick = useCallback((_, node) => {
    setSelectedNode(node.id)
    setRenameTarget(node)
  }, [setSelectedNode])

  // 确认改名
  const handleRenameConfirm = (name, desc) => {
    if (renameTarget) {
      updateNodeData(renameTarget.id, { label: name, description: desc })
    }
    setRenameTarget(null)
  }

  // 右键节点：弹出上下文菜单
  const onNodeContextMenu = useCallback(
    (e, node) => {
      e.preventDefault()
      setSelectedNode(node.id)
      setCtxMenu({ x: e.clientX, y: e.clientY, node })
    },
    [setSelectedNode]
  )

  // ============ 右键菜单动作 ============
  const handleCtxCopy = (node) => duplicateNode(node.id)
  const handleCtxDelete = (node) => removeNode(node.id)
  const handleCtxEdit = (node) => setSelectedNode(node.id)

  // 试运行到此节点：调用后端单节点测试，并联动节点状态可视化
  const handleCtxRun = async (node) => {
    if (!node) return
    setRunTargetId(node.id)
    setNodeRunStatus(node.id, 'running')
    try {
      await workflowsApi.testNode(
        { id: node.id, type: node.type, data: node.data },
        node.data?.test_input || {}
      )
      setNodeRunStatus(node.id, 'success')
      toast.success(`节点「${node.data?.label || node.type}」试运行完成`)
    } catch (err) {
      setNodeRunStatus(node.id, 'failed')
      toast.error(`节点试运行失败：${err.message || err}`)
    } finally {
      setRunTargetId(null)
    }
  }

  // ============ 全屏切换 ============
  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen?.()
    } else if (wrapRef.current?.requestFullscreen) {
      wrapRef.current.requestFullscreen().catch(() => {})
    }
  }, [])

  // 监听全屏状态变化（含 Esc 退出），进入全屏后自适应视图
  useEffect(() => {
    const onChange = () => {
      const fs = !!document.fullscreenElement
      setIsFullscreen(fs)
      if (fs) {
        // 进入全屏后稍候自适应，避免尺寸未就绪
        setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 120)
      }
    }
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [fitView])

  // ============ 画布级快捷键：Ctrl+Z 撤销 / Ctrl+Y 重做 / Delete 删除选中 ============
  // 使用捕获阶段 + stopImmediatePropagation，确保优先于 WorkflowEditor 的单选删除监听
  // 注意：ReactFlow 内置 deleteKeyCode 已置为 null，统一由本处与 WorkflowEditor 接管，
  // 避免双重删除导致历史快照重复。
  useEffect(() => {
    const handler = (e) => {
      const tag = (e.target?.tagName || '').toLowerCase()
      const inForm =
        tag === 'input' ||
        tag === 'textarea' ||
        tag === 'select' ||
        e.target?.isContentEditable
      // Ctrl/Cmd+Z 撤销（不含 Shift）
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === 'z' || e.key === 'Z')) {
        if (inForm) return
        e.preventDefault()
        undo()
        e.stopImmediatePropagation()
        return
      }
      // Ctrl/Cmd+Y 或 Ctrl/Cmd+Shift+Z 重做
      if (
        (e.ctrlKey || e.metaKey) &&
        (e.key === 'y' || e.key === 'Y' ||
          ((e.key === 'z' || e.key === 'Z') && e.shiftKey))
      ) {
        if (inForm) return
        e.preventDefault()
        redo()
        e.stopImmediatePropagation()
        return
      }
      // Delete/Backspace：多选节点批量删除 / 连线删除
      // 单个节点删除仍交由 WorkflowEditor 处理（保留既有逻辑）
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (inForm) return
        if (selectedNodeIds.length > 1) {
          e.preventDefault()
          removeNodes(selectedNodeIds)
          e.stopImmediatePropagation()
        } else if (selectedNodeIds.length === 0 && selectedEdgeIdsRef.current.length > 0) {
          e.preventDefault()
          onEdgesChange(
            selectedEdgeIdsRef.current.map((id) => ({ type: 'remove', id }))
          )
          e.stopImmediatePropagation()
        }
      }
    }
    window.addEventListener('keydown', handler, { capture: true })
    return () => window.removeEventListener('keydown', handler, { capture: true })
  }, [undo, redo, selectedNodeIds, removeNodes, onEdgesChange])

  return (
    <div ref={wrapRef} className="relative h-full w-full bg-background">
      <ReactFlow
        nodes={displayNodes}
        edges={displayEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeDoubleClick={onNodeDoubleClick}
        onNodeContextMenu={onNodeContextMenu}
        onSelectionChange={onSelectionChange}
        fitView
        // 框选多选：左键拖拽框选，Shift/Ctrl/Cmd+点击追加多选
        selectionOnDrag
        panOnDrag={[1]}
        multiSelectionKeyCode={['Shift', 'Control', 'Meta']}
        deleteKeyCode={null}
        proOptions={{ hideAttribution: true }}
        className="h-full w-full bg-background"
      >
        <Background color="#374151" gap={16} />
        <Controls showInteractive={false} className="!shadow-lg" />
        <MiniMap
          pannable
          zoomable
          className="!bg-secondary"
          maskColor="rgba(17,24,39,0.7)"
          nodeColor={(n) => getNodeDefinition(n.type)?.color || '#6366f1'}
        />
      </ReactFlow>

      {/* 右上角浮动工具按钮组：布局 / 撤销重做 / 适配 / 全屏 */}
      <div className="absolute right-3 top-3 z-20 flex items-center gap-0.5 rounded-md border border-border bg-card/95 p-1 shadow-lg backdrop-blur">
        <ToolBtn title="横向布局" onClick={() => autoLayout('horizontal')}>
          <Columns3 className="h-4 w-4" />
        </ToolBtn>
        <ToolBtn title="纵向布局" onClick={() => autoLayout('vertical')}>
          <Rows3 className="h-4 w-4" />
        </ToolBtn>
        <ToolBtn title="对齐网格 (20px)" onClick={() => alignToGrid(20)}>
          <LayoutGrid className="h-4 w-4" />
        </ToolBtn>
        <div className="mx-0.5 h-5 w-px bg-border" />
        <ToolBtn title="撤销 (Ctrl+Z)" onClick={undo} disabled={!canUndo}>
          <Undo2 className="h-4 w-4" />
        </ToolBtn>
        <ToolBtn title="重做 (Ctrl+Y)" onClick={redo} disabled={!canRedo}>
          <Redo2 className="h-4 w-4" />
        </ToolBtn>
        <div className="mx-0.5 h-5 w-px bg-border" />
        <ToolBtn title="适配画布" onClick={() => fitView({ padding: 0.2, duration: 300 })}>
          <Maximize2 className="h-4 w-4" />
        </ToolBtn>
        <ToolBtn title={isFullscreen ? '退出全屏' : '全屏编辑'} onClick={toggleFullscreen}>
          {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
        </ToolBtn>
      </div>

      {/* 右键节点上下文菜单 */}
      <ContextMenu
        menu={ctxMenu}
        onClose={() => setCtxMenu(null)}
        onCopy={handleCtxCopy}
        onDelete={handleCtxDelete}
        onEdit={handleCtxEdit}
        onRun={handleCtxRun}
        running={!!runTargetId && ctxMenu?.node?.id === runTargetId}
      />

      {/* 双击节点快捷改名弹窗 */}
      <RenameNodeModal
        open={!!renameTarget}
        node={renameTarget}
        onClose={() => setRenameTarget(null)}
        onConfirm={handleRenameConfirm}
      />
    </div>
  )
}

// 用 ReactFlowProvider 包裹，以便内部使用 useReactFlow 获取 screenToFlowPosition
function FlowCanvas() {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner />
    </ReactFlowProvider>
  )
}

export default FlowCanvas
