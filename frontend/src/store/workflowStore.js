// Zustand 工作流状态管理
import { create } from 'zustand'
import { applyNodeChanges, applyEdgeChanges, addEdge } from 'reactflow'
import { getNodeDefinition } from '../constants/nodeCatalog'

// 新增连线的默认样式（带动画）
const defaultEdgeOptions = {
  animated: true,
  style: { stroke: '#6366f1', strokeWidth: 2 },
}

// 收藏节点本地存储 key（工作流编辑器节点库收藏夹）
const FAVORITE_NODES_KEY = 'soar_favorite_nodes_v1'

// 读取收藏节点（节点 type 数组）
function loadFavoriteNodes() {
  try {
    const raw = localStorage.getItem(FAVORITE_NODES_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

// 自动布局：横向分层排列（基于拓扑层级）
// 简化实现：BFS 分层后按层等距分布
function autoLayoutHorizontal(nodes, edges) {
  if (!nodes.length) return nodes
  // 构建邻接表（source -> [target]）
  const adj = {}
  const inDeg = {}
  nodes.forEach((n) => {
    adj[n.id] = []
    inDeg[n.id] = 0
  })
  edges.forEach((e) => {
    if (adj[e.source] && inDeg[e.target] !== undefined) {
      adj[e.source].push(e.target)
      inDeg[e.target] = (inDeg[e.target] || 0) + 1
    }
  })
  // BFS 分层（Kahn 算法）
  const layers = {} // nodeId -> layer
  let queue = nodes.filter((n) => inDeg[n.id] === 0).map((n) => n.id)
  queue.forEach((id) => (layers[id] = 0))
  let idx = 0
  while (queue.length && idx < nodes.length * 2) {
    const next = []
    queue.forEach((id) => {
      (adj[id] || []).forEach((tid) => {
        if (layers[tid] === undefined) {
          layers[tid] = (layers[id] || 0) + 1
          next.push(tid)
        }
      })
    })
    queue = next
    idx++
  }
  // 孤立节点（无连线）放在第 0 层
  nodes.forEach((n) => {
    if (layers[n.id] === undefined) layers[n.id] = 0
  })
  // 按层分组
  const byLayer = {}
  nodes.forEach((n) => {
    const l = layers[n.id]
    if (!byLayer[l]) byLayer[l] = []
    byLayer[l].push(n)
  })
  // 布局参数
  const xGap = 280, yGap = 120, xStart = 80, yStart = 80
  const result = nodes.map((n) => {
    const l = layers[n.id]
    const group = byLayer[l] || []
    const idxInGroup = group.indexOf(n)
    return {
      ...n,
      position: {
        x: xStart + l * xGap,
        y: yStart + idxInGroup * yGap,
      },
    }
  })
  return result
}

// 自动布局：纵向分层排列
function autoLayoutVertical(nodes, edges) {
  if (!nodes.length) return nodes
  const adj = {}, inDeg = {}
  nodes.forEach((n) => { adj[n.id] = []; inDeg[n.id] = 0 })
  edges.forEach((e) => {
    if (adj[e.source] && inDeg[e.target] !== undefined) {
      adj[e.source].push(e.target)
      inDeg[e.target] = (inDeg[e.target] || 0) + 1
    }
  })
  const layers = {}
  let queue = nodes.filter((n) => inDeg[n.id] === 0).map((n) => n.id)
  queue.forEach((id) => (layers[id] = 0))
  while (queue.length) {
    const next = []
    queue.forEach((id) => {
      (adj[id] || []).forEach((tid) => {
        if (layers[tid] === undefined) {
          layers[tid] = (layers[id] || 0) + 1
          next.push(tid)
        }
      })
    })
    queue = next
  }
  nodes.forEach((n) => { if (layers[n.id] === undefined) layers[n.id] = 0 })
  const byLayer = {}
  nodes.forEach((n) => {
    const l = layers[n.id]
    if (!byLayer[l]) byLayer[l] = []
    byLayer[l].push(n)
  })
  const xGap = 220, yGap = 140, xStart = 80, yStart = 80
  return nodes.map((n) => {
    const l = layers[n.id]
    const group = byLayer[l] || []
    const idxInGroup = group.indexOf(n)
    return {
      ...n,
      position: {
        x: xStart + idxInGroup * xGap,
        y: yStart + l * yGap,
      },
    }
  })
}

// 对齐网格：将节点坐标吸附到 20px 网格
function snapToGrid(nodes, grid = 20) {
  return nodes.map((n) => ({
    ...n,
    position: {
      x: Math.round((n.position?.x || 0) / grid) * grid,
      y: Math.round((n.position?.y || 0) / grid) * grid,
    },
  }))
}

// 历史快照最大深度
const MAX_HISTORY = 50

export const useWorkflowStore = create((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  // 多选节点 id 集合（框选 / Ctrl 多选）
  selectedNodeIds: [],

  // 工作流元数据：当前正在编辑的工作流名称与后端 ID
  workflowName: '',
  workflowId: null,
  // 资源级 owner 控制：后端返回的 can_edit 标志与创建者（新建时默认可编辑）
  workflowCanEdit: true,
  workflowCreatedBy: null,
  // 脏标记
  isDirty: false,

  // 试运行产生的日志与轨迹
  runLogs: [],
  runTraces: [],
  // 当前运行状态：idle / running / success / failed
  runStatus: 'idle',
  // 节点级运行状态：{ [nodeId]: 'idle' | 'running' | 'success' | 'failed' | 'skipped' }
  nodeRunStatus: {},

  // 工作流级全局变量
  variables: [],

  // 撤销/重做历史栈
  // 每个快照为 { nodes, edges } 的深拷贝
  history: [],
  historyIndex: -1,

  // 收藏节点类型列表（本地存储）
  favoriteNodes: loadFavoriteNodes(),

  // ============ 历史快照管理 ============
  // 在会改变结构的操作前调用，推入当前快照
  pushHistory: () => {
    const { nodes, edges, history, historyIndex } = get()
    const snapshot = {
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(edges)),
    }
    // 截断 redo 部分
    const newHistory = history.slice(0, historyIndex + 1)
    newHistory.push(snapshot)
    // 限制深度
    if (newHistory.length > MAX_HISTORY) newHistory.shift()
    set({ history: newHistory, historyIndex: newHistory.length - 1 })
  },

  undo: () => {
    const { history, historyIndex } = get()
    if (historyIndex <= 0) return
    const idx = historyIndex - 1
    const snapshot = history[idx]
    if (!snapshot) return
    // 防御性处理：确保 position 合法
    const nodes = (snapshot.nodes || []).map((n) => ({
      ...n,
      position: { x: n.position?.x ?? 0, y: n.position?.y ?? 0 },
    }))
    set({
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(snapshot.edges)),
      historyIndex: idx,
      isDirty: true,
    })
  },

  redo: () => {
    const { history, historyIndex } = get()
    if (historyIndex >= history.length - 1) return
    const idx = historyIndex + 1
    const snapshot = history[idx]
    if (!snapshot) return
    // 防御性处理：确保 position 合法
    const nodes = (snapshot.nodes || []).map((n) => ({
      ...n,
      position: { x: n.position?.x ?? 0, y: n.position?.y ?? 0 },
    }))
    set({
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(snapshot.edges)),
      historyIndex: idx,
      isDirty: true,
    })
  },

  canUndo: () => get().historyIndex > 0,
  canRedo: () => get().historyIndex < get().history.length - 1,

  // ============ React Flow 变更回调 ============
  onNodesChange: (changes) => {
    // 删除操作记录历史（其他变更如拖动不记录，避免历史栈爆炸）
    const hasRemove = changes.some((c) => c.type === 'remove')
    if (hasRemove) get().pushHistory()
    set({ nodes: applyNodeChanges(changes, get().nodes), isDirty: true })
  },

  onEdgesChange: (changes) => {
    const hasRemove = changes.some((c) => c.type === 'remove')
    if (hasRemove) get().pushHistory()
    set({ edges: applyEdgeChanges(changes, get().edges), isDirty: true })
  },

  onConnect: (connection) => {
    get().pushHistory()
    set({
      edges: addEdge({ ...connection, ...defaultEdgeOptions }, get().edges),
      isDirty: true,
    })
  },

  // ============ 节点 CRUD ============
  addNode: (type, position, presetData = null) => {
    const def = getNodeDefinition(type)
    if (!def) return
    const data = presetData
      ? { ...def.defaultData, ...presetData }
      : { ...def.defaultData }
    const newNode = {
      id: `node_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      type,
      position,
      data,
    }
    get().pushHistory()
    set({
      nodes: [...get().nodes, newNode],
      selectedNodeId: newNode.id,
      isDirty: true,
    })
  },

  updateNodeData: (nodeId, dataPatch) => {
    set({
      nodes: get().nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, ...dataPatch } } : n
      ),
      isDirty: true,
    })
  },

  setSelectedNode: (nodeId) => {
    set({ selectedNodeId: nodeId, selectedNodeIds: nodeId ? [nodeId] : [] })
  },

  // 多选：设置选中的节点 id 数组
  setSelectedNodes: (ids) => {
    set({ selectedNodeIds: ids || [], selectedNodeId: ids?.[0] || null })
  },

  // 切换某节点的选中状态（Ctrl+点击）
  toggleNodeSelection: (nodeId) => {
    const { selectedNodeIds } = get()
    if (selectedNodeIds.includes(nodeId)) {
      const next = selectedNodeIds.filter((id) => id !== nodeId)
      set({ selectedNodeIds: next, selectedNodeId: next[next.length - 1] || null })
    } else {
      const next = [...selectedNodeIds, nodeId]
      set({ selectedNodeIds: next, selectedNodeId: nodeId })
    }
  },

  clearAll: () => {
    get().pushHistory()
    set({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      selectedNodeIds: [],
      workflowName: '',
      workflowId: null,
      workflowCanEdit: true,
      workflowCreatedBy: null,
      runLogs: [],
      runTraces: [],
      nodeRunStatus: {},
      runStatus: 'idle',
      variables: [],
      isDirty: false,
    })
  },

  removeNode: (nodeId) => {
    const { selectedNodeId } = get()
    get().pushHistory()
    set({
      nodes: get().nodes.filter((n) => n.id !== nodeId),
      edges: get().edges.filter(
        (e) => e.source !== nodeId && e.target !== nodeId
      ),
      selectedNodeId: selectedNodeId === nodeId ? null : selectedNodeId,
      selectedNodeIds: get().selectedNodeIds.filter((id) => id !== nodeId),
      isDirty: true,
    })
  },

  // 批量删除节点
  removeNodes: (nodeIds) => {
    if (!nodeIds?.length) return
    const idSet = new Set(nodeIds)
    get().pushHistory()
    set({
      nodes: get().nodes.filter((n) => !idSet.has(n.id)),
      edges: get().edges.filter((e) => !idSet.has(e.source) && !idSet.has(e.target)),
      selectedNodeId: null,
      selectedNodeIds: [],
      isDirty: true,
    })
  },

  duplicateNode: (nodeId) => {
    const src = get().nodes.find((n) => n.id === nodeId)
    if (!src) return
    get().pushHistory()
    const newNode = {
      id: `node_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      type: src.type,
      position: { x: (src.position?.x || 0) + 40, y: (src.position?.y || 0) + 40 },
      data: JSON.parse(JSON.stringify(src.data || {})),
    }
    if (newNode.data.label) {
      newNode.data.label = `${newNode.data.label}_副本`
    }
    set({
      nodes: [...get().nodes, newNode],
      selectedNodeId: newNode.id,
      isDirty: true,
    })
  },

  getSelectedNode: () => {
    const { nodes, selectedNodeId } = get()
    return nodes.find((n) => n.id === selectedNodeId) || null
  },

  // ============ 自动布局 ============
  autoLayout: (direction = 'horizontal') => {
    const { nodes, edges } = get()
    if (!nodes.length) return
    get().pushHistory()
    const layouted =
      direction === 'vertical'
        ? autoLayoutVertical(nodes, edges)
        : autoLayoutHorizontal(nodes, edges)
    set({ nodes: layouted, isDirty: true })
  },

  alignToGrid: (grid = 20) => {
    const { nodes } = get()
    if (!nodes.length) return
    get().pushHistory()
    set({ nodes: snapToGrid(nodes, grid), isDirty: true })
  },

  // ============ 节点状态可视化 ============
  setNodeRunStatus: (nodeId, status) => {
    set({
      nodeRunStatus: { ...get().nodeRunStatus, [nodeId]: status },
    })
  },
  setAllNodeRunStatus: (statusMap) => {
    set({ nodeRunStatus: statusMap || {} })
  },
  clearNodeRunStatus: () => set({ nodeRunStatus: {} }),
  setRunStatus: (status) => set({ runStatus: status }),

  // ============ 连线标签 ============
  // 为条件分支等设置 edge 的 label（如 命中 / 未命中）
  setEdgeLabel: (edgeId, label) => {
    set({
      edges: get().edges.map((e) =>
        e.id === edgeId ? { ...e, label, labelStyle: { fontSize: 12, fill: '#fff', fontWeight: 600 }, labelBgStyle: { fill: '#6366f1' }, labelBgPadding: [6, 3] } : e
      ),
      isDirty: true,
    })
  },

  // ============ 收藏节点 ============
  toggleFavoriteNode: (nodeType) => {
    const list = get().favoriteNodes
    const next = list.includes(nodeType)
      ? list.filter((t) => t !== nodeType)
      : [...list, nodeType]
    set({ favoriteNodes: next })
    try {
      localStorage.setItem(FAVORITE_NODES_KEY, JSON.stringify(next))
    } catch {
      /* 忽略存储异常 */
    }
  },

  // ============ 序列化 ============
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
      if (e.label) edge.label = e.label
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
  markSaved: () => set({ isDirty: false }),

  loadWorkflow: (workflow) => {
    const graph = workflow?.graph_config || {}
    const rawNodes = Array.isArray(graph.nodes) ? graph.nodes : []
    const rawEdges = Array.isArray(graph.edges) ? graph.edges : []
    const variables = Array.isArray(graph.variables) ? graph.variables : []
    // 防御性处理：确保每个 node 都有合法的 position 对象
    const nodes = rawNodes.map((n) => ({
      ...n,
      position: {
        x: n.position?.x ?? (n.x ?? 0),
        y: n.position?.y ?? (n.y ?? 0),
      },
    }))
    // 构建 condition_branch 节点查找表，用于迁移旧版 sourceHandle
    const cbNodeMap = new Map()
    for (const n of nodes) {
      if (n.type === 'condition_branch') cbNodeMap.set(n.id, n.data || {})
    }
    // 迁移旧版 sourceHandle（label 文本 → 新 ID 方案）
    const edges = rawEdges.map((e) => {
      if (e.sourceHandle && cbNodeMap.has(e.source)) {
        const data = cbNodeMap.get(e.source)
        const sh = e.sourceHandle
        // 已是新方案（br_X / true / false / default）则跳过
        if (/^br_\d+$/.test(sh) || sh === 'true' || sh === 'false' || sh === 'default') {
          return { ...e }
        }
        // 旧方案：sourceHandle = case label → 转为 br_X
        if (data.mode === 'switch' && Array.isArray(data.cases)) {
          const idx = data.cases.findIndex((c) => c.label === sh)
          if (idx >= 0) return { ...e, sourceHandle: `br_${idx}` }
          if (sh === '默认' || sh === 'default') return { ...e, sourceHandle: 'default' }
        }
        // 旧方案：if_else 的 true_label / false_label
        if (sh === data.true_label || sh === '是' || sh === 'true') return { ...e, sourceHandle: 'true' }
        if (sh === data.false_label || sh === '否' || sh === 'false') return { ...e, sourceHandle: 'false' }
      }
      return { ...e }
    })
    // 加载时初始化历史快照（避免 undo 越界）
    const snapshot = {
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(edges)),
    }
    set({
      nodes,
      edges,
      variables,
      workflowName: workflow?.name || '',
      workflowId: workflow?.id ?? null,
      // 资源级 owner 控制：保留后端返回的 can_edit 与 created_by
      workflowCanEdit: typeof workflow?.can_edit === 'boolean' ? workflow.can_edit : true,
      workflowCreatedBy: workflow?.created_by ?? null,
      selectedNodeId: null,
      selectedNodeIds: [],
      runLogs: [],
      runTraces: [],
      nodeRunStatus: {},
      runStatus: 'idle',
      isDirty: false,
      history: [snapshot],
      historyIndex: 0,
    })
  },

  // ============ 工作流全局变量 CRUD ============
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
  clearRunLogs: () => set({ runLogs: [], runTraces: [], nodeRunStatus: {}, runStatus: 'idle' }),
}))
