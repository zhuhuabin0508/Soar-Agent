// Zustand 工作流状态管理
import { create } from 'zustand'
import { applyNodeChanges, applyEdgeChanges, addEdge } from 'reactflow'
import { getNodeDefinition } from '../constants/nodeCatalog'

// 新增连线的默认样式（带动画）
const defaultEdgeOptions = {
  animated: true,
  style: { stroke: '#6366f1', strokeWidth: 2 },
}

export const useWorkflowStore = create((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,

  // 工作流元数据：当前正在编辑的工作流名称与后端 ID
  workflowName: '',
  workflowId: null,
  // 脏标记：节点/连线/名称变更后置 true，保存或加载后置 false
  // 用于 beforeunload 离开提醒，防止用户未保存关闭页面丢失编辑
  isDirty: false,

  // 试运行产生的日志与轨迹
  runLogs: [],
  runTraces: [],

  // 工作流级全局变量：[{ name, description, default_value }]
  // 节点参数中可用 ${variables.变量名} 引用，执行时由后端 resolve_variables 替换
  variables: [],

  // 应用 React Flow 的节点变更（拖动、选中、删除等）
  onNodesChange: (changes) => {
    set({ nodes: applyNodeChanges(changes, get().nodes), isDirty: true })
  },

  // 应用 React Flow 的连线变更
  onEdgesChange: (changes) => {
    set({ edges: applyEdgeChanges(changes, get().edges), isDirty: true })
  },

  // 建立连线
  onConnect: (connection) => {
    set({
      edges: addEdge({ ...connection, ...defaultEdgeOptions }, get().edges),
      isDirty: true,
    })
  },

  // 根据类型创建新节点；可选 presetData 合并到 defaultData 之上（用于工具节点注入 tool_name 等）
  addNode: (type, position, presetData = null) => {
    const def = getNodeDefinition(type)
    if (!def) return
    const data = presetData
      ? { ...def.defaultData, ...presetData }
      : { ...def.defaultData }
    const newNode = {
      id: `node_${Date.now()}`,
      type, // 同时作为 React Flow 的渲染类型（统一映射到 CustomNode）
      position,
      data,
    }
    set({
      nodes: [...get().nodes, newNode],
      selectedNodeId: newNode.id,
      isDirty: true,
    })
  },

  // 更新节点 data（属性面板编辑用）
  updateNodeData: (nodeId, dataPatch) => {
    set({
      nodes: get().nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, ...dataPatch } } : n
      ),
      isDirty: true,
    })
  },

  // 设置当前选中节点
  setSelectedNode: (nodeId) => {
    set({ selectedNodeId: nodeId })
  },

  // 清空画布（移除所有节点与连线，同时重置工作流元数据）
  clearAll: () => {
    set({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      workflowName: '',
      workflowId: null,
      runLogs: [],
      runTraces: [],
      variables: [],
      isDirty: false,
    })
  },

  // 删除节点（同时清理相连的边）
  removeNode: (nodeId) => {
    const { selectedNodeId } = get()
    set({
      nodes: get().nodes.filter((n) => n.id !== nodeId),
      edges: get().edges.filter(
        (e) => e.source !== nodeId && e.target !== nodeId
      ),
      selectedNodeId: selectedNodeId === nodeId ? null : selectedNodeId,
      isDirty: true,
    })
  },

  // 复制节点（深拷贝 data，新 id，位置偏移 +40/+40）
  duplicateNode: (nodeId) => {
    const src = get().nodes.find((n) => n.id === nodeId)
    if (!src) return
    const newNode = {
      id: `node_${Date.now()}`,
      type: src.type,
      position: { x: (src.position?.x || 0) + 40, y: (src.position?.y || 0) + 40 },
      data: JSON.parse(JSON.stringify(src.data || {})),
    }
    // 清除副本中的 label 避免混淆（可选：保留并在末尾加"_副本"）
    if (newNode.data.label) {
      newNode.data.label = `${newNode.data.label}_副本`
    }
    set({
      nodes: [...get().nodes, newNode],
      selectedNodeId: newNode.id,
      isDirty: true,
    })
  },

  // 获取当前选中节点对象
  getSelectedNode: () => {
    const { nodes, selectedNodeId } = get()
    return nodes.find((n) => n.id === selectedNodeId) || null
  },

  // 序列化为干净 JSON（剥离 reactflow 内部字段，只保留 id/type/position/data）
  // 同时携带工作流级全局变量列表
  serialize: () => {
    const cleanNodes = get().nodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: n.position,
      data: n.data,
    }))
    const cleanEdges = get().edges.map((e) => {
      const edge = { id: e.id, source: e.source, target: e.target }
      if (e.sourceHandle) edge.sourceHandle = e.sourceHandle
      if (e.targetHandle) edge.targetHandle = e.targetHandle
      return edge
    })
    return {
      nodes: cleanNodes,
      edges: cleanEdges,
      variables: get().variables || [],
    }
  },

  // ============ 工作流元数据 ============
  setWorkflowName: (name) => set({ workflowName: name, isDirty: true }),
  setWorkflowId: (id) => set({ workflowId: id }),

  // 标记已保存（清除脏标记），保存成功后调用
  markSaved: () => set({ isDirty: false }),

  // 从后端工作流对象加载到 store（graph_config 内含 nodes/edges/variables）
  // workflow: { id, name, graph_config, ... }
  loadWorkflow: (workflow) => {
    const graph = workflow?.graph_config || {}
    const nodes = Array.isArray(graph.nodes) ? graph.nodes : []
    const edges = Array.isArray(graph.edges) ? graph.edges : []
    const variables = Array.isArray(graph.variables) ? graph.variables : []
    set({
      nodes,
      edges,
      variables,
      workflowName: workflow?.name || '',
      workflowId: workflow?.id ?? null,
      selectedNodeId: null,
      runLogs: [],
      runTraces: [],
      isDirty: false,
    })
  },

  // ============ 工作流全局变量 CRUD ============
  // 变量结构：{ name, description, default_value }
  addVariable: () => {
    const list = get().variables || []
    set({
      variables: [...list, { name: '', description: '', default_value: '' }],
      isDirty: true,
    })
  },
  updateVariable: (index, patch) => {
    const list = get().variables || []
    set({
      variables: list.map((v, i) => (i === index ? { ...v, ...patch } : v)),
      isDirty: true,
    })
  },
  removeVariable: (index) => {
    const list = get().variables || []
    set({
      variables: list.filter((_, i) => i !== index),
      isDirty: true,
    })
  },

  // ============ 试运行日志与轨迹 ============
  setRunLogs: (logs) => set({ runLogs: Array.isArray(logs) ? logs : [] }),
  setRunTraces: (traces) => set({ runTraces: Array.isArray(traces) ? traces : [] }),
  appendRunLogs: (logs) =>
    set({ runLogs: [...get().runLogs, ...(Array.isArray(logs) ? logs : [])] }),
  clearRunLogs: () => set({ runLogs: [], runTraces: [] }),
}))
