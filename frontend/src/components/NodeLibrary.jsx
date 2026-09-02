import { useEffect, useMemo, useState } from 'react'
import {
  Star,
  ChevronRight,
  Search,
  PlusCircle,
  Wrench,
  // 分类图标
  Zap,
  GitBranch,
  Bot,
  Shield,
  Bell,
  Database,
  UserCheck,
  StickyNote,
  // 节点图标
  Webhook,
  Clock,
  Radio,
  Hand,
  Shuffle,
  Repeat,
  RefreshCw,
  Hourglass,
  GitMerge,
  Box,
  MessageSquare,
  ScanSearch,
  Ban,
  Megaphone,
  Globe,
  Braces,
  Variable,
  Code2,
  FileText,
  SquareStack,
  CircleStop,
} from 'lucide-react'
import { NODE_CATEGORIES, nodeCatalog } from '../constants/nodeCatalog'
import { tools as toolsApi } from '../api/client'
import { useWorkflowStore } from '../store/workflowStore'
import { inputCls } from '../components/property/FormControls'

// 图标名 → lucide 组件映射
// nodeCatalog.icon 与 NODE_CATEGORIES.icon 均存组件名字符串，统一在此映射
const ICON_MAP = {
  // 分类图标
  Zap,
  GitBranch,
  Bot,
  Shield,
  Bell,
  Database,
  UserCheck,
  StickyNote,
  Wrench,
  // 节点图标
  Webhook,
  Clock,
  Radio,
  Hand,
  Shuffle,
  Repeat,
  RefreshCw,
  Hourglass,
  GitMerge,
  Box,
  MessageSquare,
  ScanSearch,
  Ban,
  Megaphone,
  Globe,
  Braces,
  Variable,
  Code2,
  FileText,
  SquareStack,
  CircleStop,
}

// 根据 icon 字段渲染 lucide 图标，未命中时回退到 Wrench
function renderIcon(iconName, className = 'h-5 w-5') {
  const Icon = ICON_MAP[iconName] || Wrench
  return <Icon className={className} />
}

// 工具节点卡片的固定展示色（与 nodeCatalog 中 tool 节点一致）
const TOOL_COLOR = '#14b8a6'

// 收藏星标的金色（amber-400）
const FAV_COLOR = '#fbbf24'

// 分组折叠状态本地存储 key
const EXPANDED_KEY = 'soar_nodelib_expanded_v1'

// 读取折叠状态：优先 localStorage，否则取 NODE_CATEGORIES 的 expanded 默认值
function loadExpanded() {
  try {
    const raw = localStorage.getItem(EXPANDED_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object') return parsed
    }
  } catch {
    /* ignore */
  }
  const init = {}
  NODE_CATEGORIES.forEach((c) => {
    init[c.key] = c.expanded
  })
  // 自定义工具分组默认展开
  init['custom_tools'] = true
  return init
}

// 节点卡片：图标徽章 + 名称 + 描述 + 右上角收藏星标
function NodeCard({ node, isFavorite, onToggleFavorite, onDragStart }) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      title={node.description}
      className="group relative w-full cursor-grab rounded-lg border border-border bg-secondary p-3 transition hover:border-primary hover:bg-secondary active:cursor-grabbing"
    >
      <div className="flex items-center gap-2.5">
        {/* 图标徽章 */}
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md"
          style={{ background: `${node.color}22`, color: node.color }}
        >
          {renderIcon(node.icon)}
        </div>
        {/* 名称 + 描述：右侧留出星标空间 */}
        <div className="min-w-0 flex-1 pr-6">
          <div className="truncate text-sm font-semibold text-foreground">
            {node.label}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {node.description}
          </div>
        </div>
      </div>
      {/* 收藏星标：收藏时金色填充并常驻，未收藏时仅 hover 显形 */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onToggleFavorite()
        }}
        title={isFavorite ? '取消收藏' : '收藏'}
        aria-label={isFavorite ? '取消收藏' : '收藏'}
        className={`absolute right-1 top-1 rounded p-1 text-muted-foreground/50 transition hover:bg-accent hover:text-foreground ${
          isFavorite ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
        }`}
      >
        <Star
          className="h-3.5 w-3.5"
          fill={isFavorite ? FAV_COLOR : 'none'}
          color={isFavorite ? FAV_COLOR : 'currentColor'}
        />
      </button>
    </div>
  )
}

// 工具节点卡片：固定 Wrench 图标 + 工具名 + 描述
function ToolCard({ tool, onDragStart }) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      title={tool.description || tool.name}
      className="group w-full cursor-grab rounded-lg border border-border bg-secondary p-3 transition hover:border-teal-500 hover:bg-secondary active:cursor-grabbing"
    >
      <div className="flex items-center gap-2.5">
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md"
          style={{ background: `${TOOL_COLOR}22`, color: TOOL_COLOR }}
        >
          <Wrench className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-foreground">
            {tool.name || `工具 ${tool.id}`}
            {tool.enabled === false && (
              <span className="ml-1 text-[10px] text-muted-foreground/70">
                （已禁用）
              </span>
            )}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {tool.description || '自定义工具'}
          </div>
        </div>
      </div>
    </div>
  )
}

// 分组标题行：图标 + 分组名 + 节点数量 + 展开箭头（展开时旋转 90°）
function CategoryHeader({ icon, label, count, isOpen, onToggle }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition hover:bg-accent"
    >
      {renderIcon(icon, 'h-4 w-4 shrink-0 text-muted-foreground')}
      <span className="flex-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="text-[11px] tabular-nums text-muted-foreground/60">
        {count}
      </span>
      <ChevronRight
        className={`h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform duration-200 ${
          isOpen ? 'rotate-90' : ''
        }`}
      />
    </button>
  )
}

// 左侧节点库面板：搜索 + 收藏 + 分类折叠 + 自定义工具 + 注册入口
function NodeLibrary() {
  const favoriteNodes = useWorkflowStore((s) => s.favoriteNodes)
  const toggleFavoriteNode = useWorkflowStore((s) => s.toggleFavoriteNode)

  // 搜索关键词（同时过滤静态节点与工具节点）
  const [keyword, setKeyword] = useState('')
  // 分组折叠状态
  const [expanded, setExpanded] = useState(loadExpanded)

  // 动态拉取后端工具列表
  const [toolList, setToolList] = useState([])
  const [loadingTools, setLoadingTools] = useState(true)
  const [toolErr, setToolErr] = useState('')

  // 静态节点拖拽：dataTransfer 仅设节点 type
  const onDragStart = (e, type) => {
    e.dataTransfer.setData('application/reactflow', type)
    e.dataTransfer.effectAllowed = 'move'
  }

  // 工具节点拖拽：额外携带工具名，供 FlowCanvas 注入到节点 data
  const onToolDragStart = (e, toolName) => {
    e.dataTransfer.setData('application/reactflow', 'tool')
    e.dataTransfer.setData('application/reactflow-tool-name', toolName)
    e.dataTransfer.effectAllowed = 'move'
  }

  // 拉取后端已注册工具
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const data = await toolsApi.list()
        if (!alive) return
        setToolList(Array.isArray(data) ? data : [])
        setToolErr('')
      } catch (err) {
        setToolErr(err.message || '加载工具失败')
        setToolList([])
      } finally {
        if (alive) setLoadingTools(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  // 切换分组折叠，并持久化到 localStorage
  const toggleExpanded = (key) => {
    setExpanded((prev) => {
      const next = { ...prev, [key]: !prev[key] }
      try {
        localStorage.setItem(EXPANDED_KEY, JSON.stringify(next))
      } catch {
        /* ignore */
      }
      return next
    })
  }

  // 按关键词过滤静态节点（匹配 label / type / description）
  const filteredNodes = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return nodeCatalog
    return nodeCatalog.filter(
      (n) =>
        n.label.toLowerCase().includes(kw) ||
        n.type.toLowerCase().includes(kw) ||
        (n.description || '').toLowerCase().includes(kw)
    )
  }, [keyword])

  // 按关键词过滤工具节点（匹配 name / description）
  const filteredTools = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return toolList
    return toolList.filter(
      (t) =>
        (t.name || '').toLowerCase().includes(kw) ||
        (t.description || '').toLowerCase().includes(kw)
    )
  }, [keyword, toolList])

  // 将过滤后的静态节点按 category 分组
  const groupedNodes = useMemo(() => {
    const groups = {}
    NODE_CATEGORIES.forEach((c) => {
      groups[c.key] = []
    })
    filteredNodes.forEach((n) => {
      const cat = n.category || 'other'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(n)
    })
    return groups
  }, [filteredNodes])

  // 收藏节点定义列表（按 favoriteNodes 顺序查找 nodeCatalog）
  const favoriteNodeDefs = useMemo(
    () =>
      favoriteNodes
        .map((type) => nodeCatalog.find((n) => n.type === type))
        .filter(Boolean),
    [favoriteNodes]
  )

  const hasKeyword = keyword.trim().length > 0

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          节点库
        </h2>
        <span className="text-[11px] text-muted-foreground/70">拖拽到画布</span>
      </div>

      {/* 搜索框：过滤节点与工具 */}
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
        <input
          className={`${inputCls} pl-8`}
          placeholder="搜索节点 / 工具…"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      {/* 收藏区：仅有收藏且未在搜索时显示 */}
      {!hasKeyword && favoriteNodeDefs.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5 px-1">
            <Star className="h-3.5 w-3.5" fill={FAV_COLOR} color={FAV_COLOR} />
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              收藏
            </span>
            <span className="text-[11px] tabular-nums text-muted-foreground/60">
              {favoriteNodeDefs.length}
            </span>
          </div>
          {favoriteNodeDefs.map((n) => (
            <NodeCard
              key={`fav-${n.type}`}
              node={n}
              isFavorite
              onToggleFavorite={() => toggleFavoriteNode(n.type)}
              onDragStart={(e) => onDragStart(e, n.type)}
            />
          ))}
        </section>
      )}

      {hasKeyword ? (
        /* 搜索结果：忽略分组折叠，平铺显示匹配的节点与工具 */
        <div className="flex flex-col gap-2">
          {filteredNodes.length === 0 && filteredTools.length === 0 ? (
            <p className="px-1 text-[11px] text-muted-foreground/60">无匹配的节点</p>
          ) : (
            <>
              {filteredNodes.map((n) => (
                <NodeCard
                  key={n.type}
                  node={n}
                  isFavorite={favoriteNodes.includes(n.type)}
                  onToggleFavorite={() => toggleFavoriteNode(n.type)}
                  onDragStart={(e) => onDragStart(e, n.type)}
                />
              ))}
              {filteredTools.map((t) => (
                <ToolCard
                  key={t.id ?? t.name}
                  tool={t}
                  onDragStart={(e) => onToolDragStart(e, t.name)}
                />
              ))}
            </>
          )}
        </div>
      ) : (
        /* 分类折叠展示 */
        <>
          {NODE_CATEGORIES.map((cat) => {
            const nodes = groupedNodes[cat.key] || []
            // 空分组不渲染，减少视觉噪音
            if (nodes.length === 0) return null
            const isOpen = !!expanded[cat.key]
            return (
              <section key={cat.key} className="flex flex-col gap-1.5">
                <CategoryHeader
                  icon={cat.icon}
                  label={cat.label}
                  count={nodes.length}
                  isOpen={isOpen}
                  onToggle={() => toggleExpanded(cat.key)}
                />
                {isOpen &&
                  nodes.map((n) => (
                    <NodeCard
                      key={n.type}
                      node={n}
                      isFavorite={favoriteNodes.includes(n.type)}
                      onToggleFavorite={() => toggleFavoriteNode(n.type)}
                      onDragStart={(e) => onDragStart(e, n.type)}
                    />
                  ))}
              </section>
            )
          })}

          {/* 自定义工具分组（动态拉取已注册工具） */}
          <section className="mt-1 flex flex-col gap-1.5 border-t border-border pt-2">
            <CategoryHeader
              icon="Wrench"
              label="自定义工具"
              count={toolList.length}
              isOpen={!!expanded['custom_tools']}
              onToggle={() => toggleExpanded('custom_tools')}
            />
            {expanded['custom_tools'] && (
              <div className="flex flex-col gap-2">
                {loadingTools ? (
                  <div className="rounded-md border border-border bg-muted p-3 text-center text-[11px] text-muted-foreground/70">
                    加载中…
                  </div>
                ) : toolErr ? (
                  <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-center text-[11px] text-destructive">
                    {toolErr}
                  </div>
                ) : toolList.length === 0 ? (
                  <div className="rounded-md border border-border bg-muted p-3 text-center text-[11px] text-muted-foreground/60">
                    暂无已注册工具
                  </div>
                ) : (
                  toolList.map((t) => (
                    <ToolCard
                      key={t.id ?? t.name}
                      tool={t}
                      onDragStart={(e) => onToolDragStart(e, t.name)}
                    />
                  ))
                )}
              </div>
            )}
          </section>
        </>
      )}

      {/* 注册自定义节点入口 */}
      <div className="mt-1 border-t border-border pt-3">
        <button
          type="button"
          onClick={() => {
            window.location.href = '/tools'
          }}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-secondary px-3 py-2.5 text-sm font-medium text-foreground transition hover:border-primary hover:bg-accent hover:text-primary"
        >
          <PlusCircle className="h-4 w-4" />
          注册自定义节点
        </button>
        <p className="mt-1.5 text-center text-[11px] leading-relaxed text-muted-foreground/70">
          扩展节点能力，前往工具管理
        </p>
      </div>
    </div>
  )
}

export default NodeLibrary
