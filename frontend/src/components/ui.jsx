// 通用 UI 组件库（令牌化版本）
// 统一按钮 / 卡片 / 页面容器 / 页面标题 / 徽章 / 数据表格 / 状态组件
// 所有组件遵循语义令牌（bg-background / text-foreground / border-border 等），
// 明暗主题切换零改动。提炼自 soar-ui-design skill。
import { isValidElement, createElement, useState } from 'react'
import { useDensityStore, DENSITY_CLASS } from '../store/densityStore'
import DensitySwitcher from './DensitySwitcher'

// ===== Button =====
// variant: primary | secondary | danger | ghost
// size: sm | md
// loading: 显示加载旋转图标并禁用
const BTN_VARIANT = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  danger: 'btn-danger',
  ghost: 'btn-ghost',
}

export function Button({
  children,
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled = false,
  className = '',
  ...props
}) {
  const variantCls = BTN_VARIANT[variant] || BTN_VARIANT.secondary
  const sizeCls = size === 'sm' ? 'btn-sm' : ''
  return (
    <button
      className={`${variantCls} ${sizeCls} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  )
}

// ===== Card =====
// 统一卡片容器：圆角令牌 + 语义边框/背景 + hover 微抬
// 可选 title / description / actions（头部区域）
// hover: 启用 card-hover 微交互（桌面端上抬 + 阴影）
export function Card({ title, description, actions, children, className = '', bodyClassName = '', hover = false }) {
  return (
    <div className={`card ${hover ? 'card-hover' : ''} ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            {title && <h3 className="truncate text-sm font-semibold text-card-foreground">{title}</h3>}
            {description && <p className="mt-0.5 truncate text-xs text-muted-foreground">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={bodyClassName || 'p-4'}>{children}</div>
    </div>
  )
}

// ===== PageContainer =====
// 统一页面外层容器：语义背景 + padding + 最小高度
export function PageContainer({ children, className = '' }) {
  return <div className={`page-container ${className}`}>{children}</div>
}

// ===== PageHeader =====
// 统一页面标题栏：标题 + 描述 + 右侧操作区
export function PageHeader({ title, description, actions, className = '' }) {
  return (
    <div className={`mb-6 flex items-start justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-foreground">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

// ===== Badge =====
// variant: primary | success | warning | danger | info | neutral
const BADGE_VARIANT = {
  primary: 'bg-primary/15 text-primary',
  success: 'bg-success/15 text-success',
  warning: 'bg-warning/15 text-warning',
  danger: 'bg-destructive/15 text-destructive',
  info: 'bg-info/15 text-info',
  neutral: 'bg-muted text-muted-foreground',
}

export function Badge({ children, variant = 'neutral', className = '' }) {
  return (
    <span className={`badge ${BADGE_VARIANT[variant] || BADGE_VARIANT.neutral} ${className}`}>
      {children}
    </span>
  )
}

// ===== StatusBadge =====
// 状态徽章：圆点 + 文字，语义色映射
// status: { color: 'success|warning|danger|info|neutral', label } 或直接传 statusKey
const STATUS_COLOR_BG = {
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-destructive',
  info: 'bg-info',
  neutral: 'bg-muted-foreground',
}

// 业务状态 → 语义色 + 中文标签 的统一映射
// 覆盖执行状态 / 资产状态 / 用户状态 / 工作流状态等所有列表页
// 用法:
//   import { statusMeta, StatusBadge } from '../components/ui'
//   const m = statusMeta(row.status)  // { color, label }
//   <StatusBadge color={m.color} label={m.label} />
export function statusMeta(status) {
  const s = String(status || '').toLowerCase()
  switch (s) {
    // 成功
    case 'success':
    case 'succeeded':
    case 'completed':
    case 'active':
    case 'enabled':
    case 'approved':
    case 'online':
      return { color: 'success', label: labelFromStatus(status) }
    // 失败/危险
    case 'failed':
    case 'error':
    case 'rejected':
    case 'disabled':
    case 'banned':
    case 'offline':
    case 'expired':
      return { color: 'danger', label: labelFromStatus(status) }
    // 进行中
    case 'running':
    case 'pending':
    case 'processing':
    case 'in_progress':
      return { color: 'info', label: labelFromStatus(status) }
    // 待审批/警告
    case 'waiting_for_approval':
    case 'waiting':
    case 'paused':
    case 'warning':
    case 'draft':
      return { color: 'warning', label: labelFromStatus(status) }
    // 中性(默认)
    default:
      return { color: 'neutral', label: labelFromStatus(status) }
  }
}

// 业务状态 → 中文标签(不区分大小写)
// 未识别的状态原样返回(便于发现遗漏)
function labelFromStatus(status) {
  if (!status) return '-'
  const s = String(status)
  const map = {
    success: '成功',
    succeeded: '成功',
    completed: '已完成',
    failed: '失败',
    error: '错误',
    rejected: '已拒绝',
    approved: '已批准',
    running: '运行中',
    pending: '处理中',
    processing: '处理中',
    in_progress: '进行中',
    waiting_for_approval: '待审批',
    waiting: '等待中',
    paused: '已暂停',
    active: '活跃',
    enabled: '已启用',
    disabled: '已禁用',
    banned: '已封禁',
    online: '在线',
    offline: '离线',
    expired: '已过期',
    draft: '草稿',
    inactive: '未激活',
  }
  return map[s.toLowerCase()] || s
}

export function StatusBadge({ color = 'neutral', label, status, className = '' }) {
  // 支持 status prop:直接传业务状态字符串,自动解析为 color + label
  if (status && !color) {
    const m = statusMeta(status)
    color = m.color
  }
  if (status && !label) {
    label = labelFromStatus(status)
  }
  const dotCls = STATUS_COLOR_BG[color] || STATUS_COLOR_BG.neutral
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${className}`}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotCls}`} />
      <span className="text-muted-foreground">{label}</span>
    </span>
  )
}

// ===== Skeleton =====
// 骨架屏占位：流光动画（见 index.css .skeleton-shimmer）
// 用法：<Skeleton className="h-4 w-24" /> 或 <Skeleton lines={3} />
export function Skeleton({ className = '', lines, ...props }) {
  if (lines && lines > 0) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className="skeleton-shimmer h-3 rounded"
            style={{ width: i === lines - 1 ? '70%' : '100%' }}
          />
        ))}
      </div>
    )
  }
  return <div className={`skeleton-shimmer rounded ${className}`} {...props} />
}

// ===== LoadingState =====
// 加载态：骨架屏模拟表格/卡片布局，替代居中 spinner
export function LoadingState({ rows = 5, cols = 4, className = '' }) {
  return (
    <div className={`flex flex-col gap-3 p-4 ${className}`}>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-4">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}

// ===== EmptyState =====
// 空态：图标 + 标题 + 描述 + 可选操作引导
// icon: ReactNode 或 lucide 图标组件（自动创建元素）
export function EmptyState({ icon, title = '暂无数据', description, action, bordered = false, className = '' }) {
  // 兼容两种传入方式：JSX 元素（isValidElement）或组件类型（函数/forwardRef）
  const iconNode = icon
    ? (isValidElement(icon) ? icon : createElement(icon))
    : (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="12" cy="6" rx="9" ry="3" />
        <path d="M3 6v6c0 1.66 4.03 3 9 3s9-1.34 9-3V6" />
        <path d="M3 12v6c0 1.66 4.03 3 9 3s9-1.34 9-3v-6" />
      </svg>
    )
  return (
    <div
      className={`flex flex-col items-center justify-center gap-3 px-6 py-12 text-center ${
        bordered ? 'rounded-lg border border-border' : ''
      } ${className}`}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        {iconNode}
      </div>
      <div>
        <div className="text-sm font-medium text-foreground">{title}</div>
        {description && <div className="mt-1 text-xs text-muted-foreground">{description}</div>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

// ===== ErrorState =====
// 错误态：图标 + 错误信息 + 重试按钮
export function ErrorState({ title = '加载失败', description, onRetry, className = '' }) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 px-6 py-12 text-center ${className}`}>
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <div>
        <div className="text-sm font-medium text-foreground">{title}</div>
        {description && <div className="mt-1 text-xs text-muted-foreground">{description}</div>}
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          重试
        </Button>
      )}
    </div>
  )
}

// ===== DataTable =====
// 统一数据表格：语义令牌 + 骨架加载 + 空态 + 粘性表头 + 批量选择
// columns: [{ key, header, render?, className?, width?, numeric? }]
// data: 行数据数组
// loading / emptyText / emptyDescription / emptyIcon / emptyAction（带图标+引导按钮的空态）
// onRowClick / stickyHeader
// selectable: 开启行选择列；selectedKeys: 当前选中 rowKey 集合；onSelectChange: (keys)=>void
// 复选框点击区域：整列单元格可点击（用 label 包装），点整行不触发选择
export function DataTable({
  columns = [],
  data = [],
  loading = false,
  emptyText = '暂无数据',
  emptyDescription,
  emptyIcon,
  emptyAction,
  onRowClick,
  rowKey = 'id',
  stickyHeader = false,
  selectable = false,
  selectedKeys = [],
  onSelectChange,
  rowClassName,
  draggable = false,
  onReorder,
  maxHeight,
  className = '',
}) {
  // 数据密度:全局 store,所有 DataTable 共享
  const density = useDensityStore((s) => s.density)
  const dCls = DENSITY_CLASS[density] || DENSITY_CLASS.standard
  // 拖拽排序状态：dragIndex=被拖起的行下标，dragOverIndex=悬停目标行下标
  const [dragIndex, setDragIndex] = useState(null)
  const [dragOverIndex, setDragOverIndex] = useState(null)
  // 选择状态计算
  const selectedSet = new Set(selectedKeys)
  const pageKeys = data.map((row) => row[rowKey])
  const allSelected = selectable && data.length > 0 && pageKeys.every((k) => selectedSet.has(k))
  const someSelected = selectable && !allSelected && pageKeys.some((k) => selectedSet.has(k))

  const toggleAll = (checked) => {
    if (!onSelectChange) return
    if (checked) {
      // 合并：保留已选 + 当前页全部
      onSelectChange([...new Set([...selectedKeys, ...pageKeys])])
    } else {
      // 取消当前页全部
      const pageSet = new Set(pageKeys)
      onSelectChange(selectedKeys.filter((k) => !pageSet.has(k)))
    }
  }

  const toggleRow = (key, checked) => {
    if (!onSelectChange) return
    onSelectChange(checked ? [...selectedKeys, key] : selectedKeys.filter((k) => k !== key))
  }

  // 行点击：仅触发 onRowClick 回调；选中只能通过勾选框操作
  const handleRowClick = (row) => {
    if (onRowClick) {
      onRowClick(row)
    }
  }

  const colSpan = columns.length + (selectable ? 1 : 0)

  return (
    <div
      className={`table-wrap overflow-x-auto ${maxHeight ? 'overflow-y-auto' : ''} ${className}`}
      style={maxHeight ? { maxHeight: typeof maxHeight === 'number' ? `${maxHeight}px` : maxHeight } : undefined}
    >
      {/* table-fixed：列宽按 width 分配，超长内容配合单元格 overflow 截断，
          避免长描述把表格撑出横向滚动条 */}
      <table className="w-full table-fixed border-collapse">
        <thead>
          <tr
            className={`border-b border-border text-left ${dCls.header} text-muted-foreground ${
              stickyHeader ? 'sticky top-0 z-base' : ''
            }`}
            style={{ background: 'var(--table-header)' }}
          >
            {selectable && (
              <th key="__select" className={`px-3 ${dCls.header}`} style={{ width: '44px' }}>
                <label className="flex h-7 w-7 cursor-pointer items-center justify-center rounded hover:bg-accent">
                  <input
                    type="checkbox"
                    className="h-4 w-4 cursor-pointer rounded border-border accent-primary"
                    checked={allSelected}
                    ref={(el) => {
                      if (el) el.indeterminate = someSelected
                    }}
                    onChange={(e) => toggleAll(e.target.checked)}
                    aria-label="全选当前页"
                  />
                </label>
              </th>
            )}
            {columns.map((col) => (
              <th
                key={col.key}
                className={`whitespace-nowrap px-4 ${dCls.header} font-semibold ${col.numeric ? 'text-right tabular-nums' : ''} ${col.className || ''}`}
                style={col.width ? { width: col.width } : undefined}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={colSpan} className="px-4 py-0">
                <LoadingState rows={6} cols={columns.length} />
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={colSpan} className="px-4 py-0">
                <EmptyState
                  icon={emptyIcon}
                  title={emptyText}
                  description={emptyDescription}
                  action={emptyAction}
                />
              </td>
            </tr>
          ) : (
            data.map((row, i) => {
              const key = row[rowKey] ?? i
              const checked = selectable && selectedSet.has(row[rowKey])
              const clickable = !!onRowClick
              const extraRowCls = rowClassName ? rowClassName(row) : ''
              const isDragging = draggable && dragIndex === i
              const isDragOver = draggable && dragOverIndex === i && dragIndex !== null && dragIndex !== i
              return (
                <tr
                  key={key}
                  draggable={draggable}
                  onDragStart={(e) => {
                    if (!draggable) return
                    setDragIndex(i)
                    e.dataTransfer.effectAllowed = 'move'
                    try { e.dataTransfer.setData('text/plain', String(i)) } catch (_) {}
                  }}
                  onDragOver={(e) => {
                    if (!draggable || dragIndex === null) return
                    e.preventDefault()
                    e.dataTransfer.dropEffect = 'move'
                    if (dragOverIndex !== i) setDragOverIndex(i)
                  }}
                  onDragLeave={() => draggable && dragOverIndex === i && setDragOverIndex(null)}
                  onDrop={(e) => {
                    if (!draggable || dragIndex === null) return
                    e.preventDefault()
                    if (dragIndex !== i && onReorder) onReorder(dragIndex, i)
                    setDragIndex(null)
                    setDragOverIndex(null)
                  }}
                  onDragEnd={() => { setDragIndex(null); setDragOverIndex(null) }}
                  onClick={() => handleRowClick(row)}
                  className={`table-row-hover border-b border-border/60 ${clickable ? 'cursor-pointer' : ''} ${draggable ? 'cursor-grab active:cursor-grabbing' : ''} ${checked ? 'bg-primary/5' : ''} ${isDragging ? 'opacity-40' : ''} ${isDragOver ? 'ring-2 ring-inset ring-primary/50 bg-primary/5' : ''} ${extraRowCls}`}
                >
                  {selectable && (
                    <td key="__select" className={`px-3 ${dCls.cell}`} style={{ width: '44px' }} onClick={(e) => e.stopPropagation()}>
                      <label className="flex h-7 w-7 cursor-pointer items-center justify-center rounded hover:bg-accent">
                        <input
                          type="checkbox"
                          className="h-4 w-4 cursor-pointer rounded border-border accent-primary"
                          checked={checked}
                          onChange={(e) => toggleRow(row[rowKey], e.target.checked)}
                          aria-label="选择该行"
                        />
                      </label>
                    </td>
                  )}
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`overflow-hidden text-ellipsis whitespace-nowrap px-4 ${dCls.cell} text-foreground ${col.numeric ? 'text-right tabular-nums' : ''} ${col.className || ''}`}
                    >
                      {col.render ? col.render(row) : row[col.key]}
                    </td>
                  ))}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}

// ===== Pagination =====
// 统一分页控件：条数区间 + 每页大小选择 + 跳页 + 上下页
// onPageChange(page) / onPageSizeChange(size)（可选）
// showPageSize：是否显示每页大小选择器；showJumper：是否显示跳页输入框
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [20, 50, 100],
  showPageSize = true,
  showJumper = true,
  showDensity = true,
  className = '',
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  if (total === 0) return null
  const safePage = Math.min(Math.max(1, page), totalPages)
  const start = (safePage - 1) * pageSize + 1
  const end = Math.min(safePage * pageSize, total)
  // 密度切换器:全局共享,影响所有 DataTable 行高
  return (
    <div className={`flex flex-wrap items-center justify-between gap-3 px-1 py-3 text-xs text-muted-foreground ${className}`}>
      <div className="flex items-center gap-3">
        <span className="tabular-nums">
          共 {total} 条，第 {start}-{end} 条
        </span>
        {showPageSize && onPageSizeChange && (
          <label className="flex items-center gap-1.5">
            <span>每页</span>
            <select
              className="rounded border border-border bg-background px-1.5 py-0.5 text-xs text-foreground outline-none focus:border-primary"
              value={pageSize}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
            >
              {pageSizeOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt} 条
                </option>
              ))}
            </select>
          </label>
        )}
        {showDensity && <DensitySwitcher />}
      </div>
      <div className="flex items-center gap-2">
        {showJumper && totalPages > 1 && (
          <label className="flex items-center gap-1.5">
            <span>跳至</span>
            <input
              type="number"
              min={1}
              max={totalPages}
              className="w-14 rounded border border-border bg-background px-1.5 py-0.5 text-xs text-foreground outline-none tabular-nums focus:border-primary"
              defaultValue={safePage}
              key={safePage}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const p = Number(e.target.value)
                  if (Number.isFinite(p) && p >= 1 && p <= totalPages && p !== safePage) {
                    onPageChange(p)
                  }
                }
              }}
            />
            <span>页</span>
          </label>
        )}
        <Button size="sm" variant="ghost" disabled={safePage <= 1} onClick={() => onPageChange(safePage - 1)}>
          上一页
        </Button>
        <span className="tabular-nums">{safePage} / {totalPages}</span>
        <Button size="sm" variant="ghost" disabled={safePage >= totalPages} onClick={() => onPageChange(safePage + 1)}>
          下一页
        </Button>
      </div>
    </div>
  )
}

export default { Button, Card, PageContainer, PageHeader, Badge, StatusBadge, Skeleton, LoadingState, EmptyState, ErrorState, DataTable, Pagination }
