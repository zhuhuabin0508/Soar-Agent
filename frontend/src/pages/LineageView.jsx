// 数据血缘视图：用 reactflow 拓扑图展示 设备 → 接收器 → 条目 → 模板 的数据血缘
// 节点按类型分列布局，显示健康状态徽章（healthy/disabled/warning/offline）
import { useEffect, useState, useCallback } from 'react'
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow'
import 'reactflow/dist/style.css'
import { Server, Radio, ListTree, FileJson, Loader2, RefreshCw } from 'lucide-react'
import { PageContainer, PageHeader, Button, EmptyState } from '../components/ui'
import { request } from '../api/client'
import { toast } from '../store/toastStore'

// 节点类型 → 图标 + 颜色
const TYPE_META = {
  device: { icon: Server, color: '#3b82f6', label: '设备' },
  receiver: { icon: Radio, color: '#8b5cf6', label: '接收器' },
  entry: { icon: ListTree, color: '#06b6d4', label: '数据源条目' },
  strategy: { icon: FileJson, color: '#10b981', label: '解析模板' },
}

// 健康状态 → 徽章颜色
const HEALTH_STYLE = {
  healthy: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  disabled: 'bg-gray-500/15 text-gray-500',
  warning: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  offline: 'bg-red-500/15 text-red-600 dark:text-red-400',
}
const HEALTH_LABEL = { healthy: '正常', disabled: '已停用', warning: '有失败', offline: '离线' }

// 自定义节点
function LineageNode({ data }) {
  const { label, nodeType, health, meta } = data
  const tm = TYPE_META[nodeType] || TYPE_META.device
  const Icon = tm.icon
  return (
    <div className="flex w-[200px] flex-col rounded-lg border border-border bg-background p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-md" style={{ backgroundColor: `${tm.color}22` }}>
          <Icon className="h-4 w-4" style={{ color: tm.color }} />
        </div>
        <div className="flex-1 truncate text-sm font-medium text-foreground" title={label}>{label}</div>
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">{tm.label}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${HEALTH_STYLE[health] || HEALTH_STYLE.disabled}`}>
          {HEALTH_LABEL[health] || health}
        </span>
      </div>
      {meta && (
        <div className="mt-1.5 space-y-0.5 border-t border-border pt-1.5 text-[10px] text-muted-foreground">
          {meta.type && <div>类型：{meta.type}</div>}
          {meta.ip && <div className="truncate" title={meta.ip}>IP：{meta.ip}</div>}
          {meta.protocol && <div>协议：{meta.protocol}{meta.port ? `:${meta.port}` : ''}</div>}
          {meta.version && <div>版本：v{meta.version}</div>}
          {typeof meta.alert_count === 'number' && meta.alert_count > 0 && (
            <div>今日告警：{meta.alert_count}</div>
          )}
          {typeof meta.fail_count === 'number' && meta.fail_count > 0 && (
            <div className="text-amber-600 dark:text-amber-400">今日失败：{meta.fail_count}</div>
          )}
        </div>
      )}
    </div>
  )
}

const nodeTypes = { lineage: LineageNode }

// 分层布局：按 type 分列，y 递增
const COLUMN_X = { device: 0, receiver: 320, entry: 640, strategy: 960 }

function layoutNodes(nodes) {
  const counters = { device: 0, receiver: 0, entry: 0, strategy: 0 }
  return nodes.map((n) => {
    const col = COLUMN_X[n.type] !== undefined ? n.type : 'device'
    const y = counters[col] * 130
    counters[col] += 1
    return {
      id: n.id,
      type: 'lineage',
      position: { x: COLUMN_X[col], y },
      data: { label: n.label, nodeType: n.type, health: n.health, meta: n.meta },
      draggable: true,
    }
  })
}

const edgeStyle = {
  stroke: '#94a3b8', strokeWidth: 1.5, strokeDasharray: '0',
}
const arrowHeadType = 'arrowclosed'

export default function LineageView() {
  const [data, setData] = useState({ nodes: [], edges: [] })
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await request('/ingest/lineage')
      setData(res)
    } catch (e) {
      toast.error(e.message || '血缘数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const rfNodes = layoutNodes(data.nodes || [])
  const rfEdges = (data.edges || []).map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label,
    type: 'smoothstep',
    style: edgeStyle,
    arrowHeadType,
  }))

  const counts = (data.nodes || []).reduce((acc, n) => {
    acc[n.type] = (acc[n.type] || 0) + 1
    return acc
  }, {})

  return (
    <div>
      <PageHeader
        title="数据血缘视图"
        description="设备 → 接收器 → 数据源条目 → 解析模板 的拓扑血缘与健康状态"
        actions={
          <Button variant="ghost" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1 h-4 w-4" />}
            刷新
          </Button>
        }
      />
      <PageContainer>
        {/* 统计条 */}
        <div className="mb-3 flex items-center gap-4 text-xs text-muted-foreground">
          <span>设备 {counts.device || 0}</span>
          <span>接收器 {counts.receiver || 0}</span>
          <span>数据源条目 {counts.entry || 0}</span>
          <span>解析模板 {counts.strategy || 0}</span>
          <span>连线 {rfEdges.length}</span>
          <span className="ml-auto flex items-center gap-3">
            {Object.entries(HEALTH_LABEL).map(([k, v]) => (
              <span key={k} className="flex items-center gap-1">
                <span className={`inline-block h-2 w-2 rounded-full ${HEALTH_STYLE[k]}`} />
                {v}
              </span>
            ))}
          </span>
        </div>

        {/* 拓扑图 */}
        <div className="h-[calc(100vh-220px)] min-h-[480px] rounded-lg border border-border bg-background">
          {loading ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : rfNodes.length === 0 ? (
            <EmptyState icon={Server} title="暂无血缘数据" description="请先通过设备列表的「新建设备」完成设备接入，并创建接收器" />
          ) : (
            <ReactFlow
              nodes={rfNodes}
              edges={rfEdges}
              nodeTypes={nodeTypes}
              fitView
              fitViewPadding={0.15}
              minZoom={0.2}
              maxZoom={1.5}
              nodesConnectable={false}
              edgesFocusable={false}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#cbd5e1" gap={16} size={1} />
              <Controls showInteractive={false} />
              <MiniMap
                nodeColor={(n) => (TYPE_META[n.data?.nodeType]?.color) || '#94a3b8'}
                maskColor="rgba(241,245,249,0.7)"
              />
            </ReactFlow>
          )}
        </div>
      </PageContainer>
    </div>
  )
}
