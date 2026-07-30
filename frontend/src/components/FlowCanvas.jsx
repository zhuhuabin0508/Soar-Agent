import { useCallback, useEffect, useState } from 'react'
import ReactFlow, {
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
} from 'reactflow'
import { useWorkflowStore } from '../store/workflowStore'
import { nodeTypes } from './nodes/nodeTypes'
import { getNodeDefinition } from '../constants/nodeCatalog'
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
          <label className="mb-1 block text-xs font-medium text-gray-400">
            节点名称
          </label>
          <input
            className="w-full rounded-md border border-gray-700 bg-gray-800 px-2.5 py-1.5 text-sm text-white outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={`默认：${def?.label || ''}`}
            autoFocus
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-400">
            节点描述
          </label>
          <input
            className="w-full rounded-md border border-gray-700 bg-gray-800 px-2.5 py-1.5 text-sm text-white outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="可选，备注此节点的用途"
          />
        </div>
      </div>
    </Modal>
  )
}

// 画布内部组件：需要位于 ReactFlowProvider 内部以使用 useReactFlow
function FlowCanvasInner() {
  const { screenToFlowPosition } = useReactFlow()

  const nodes = useWorkflowStore((s) => s.nodes)
  const edges = useWorkflowStore((s) => s.edges)
  const onNodesChange = useWorkflowStore((s) => s.onNodesChange)
  const onEdgesChange = useWorkflowStore((s) => s.onEdgesChange)
  const onConnect = useWorkflowStore((s) => s.onConnect)
  const addNode = useWorkflowStore((s) => s.addNode)
  const setSelectedNode = useWorkflowStore((s) => s.setSelectedNode)
  const updateNodeData = useWorkflowStore((s) => s.updateNodeData)

  // 双击改名弹窗状态
  const [renameTarget, setRenameTarget] = useState(null)

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
      updateNodeData(renameTarget.id, {
        label: name,
        description: desc,
      })
    }
    setRenameTarget(null)
  }

  return (
    <>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={(_, node) => setSelectedNode(node.id)}
        onNodeDoubleClick={onNodeDoubleClick}
        onPaneClick={() => setSelectedNode(null)}
        fitView
        proOptions={{ hideAttribution: true }}
        className="h-full w-full bg-gray-950"
      >
        <Background color="#374151" gap={16} />
        <Controls
          showInteractive={false}
          className="!shadow-lg"
        />
        <MiniMap
          pannable
          zoomable
          className="!bg-gray-800"
          maskColor="rgba(17,24,39,0.7)"
          nodeColor={() => '#6366f1'}
        />
      </ReactFlow>

      {/* 双击节点快捷改名弹窗 */}
      <RenameNodeModal
        open={!!renameTarget}
        node={renameTarget}
        onClose={() => setRenameTarget(null)}
        onConfirm={handleRenameConfirm}
      />
    </>
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
