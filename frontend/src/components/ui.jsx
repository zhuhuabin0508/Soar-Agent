// 通用 UI 组件库
// 统一按钮 / 卡片 / 页面容器 / 页面标题 / 徽章 / 数据表格
// 所有组件遵循设计令牌（brand/success/warning/danger 色板 + zIndex 层级）

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
// 统一卡片容器：圆角 + 边框 + 暗色背景
// 可选 title / description / actions（头部区域）
export function Card({ title, description, actions, children, className = '', bodyClassName = '' }) {
  return (
    <div className={`card ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-gray-800 px-4 py-3">
          <div className="min-w-0">
            {title && <h3 className="truncate text-sm font-semibold text-gray-100">{title}</h3>}
            {description && <p className="mt-0.5 truncate text-xs text-gray-500">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={bodyClassName || 'p-4'}>{children}</div>
    </div>
  )
}

// ===== PageContainer =====
// 统一页面外层容器：暗色背景 + padding + 最小高度
export function PageContainer({ children, className = '' }) {
  return <div className={`page-container ${className}`}>{children}</div>
}

// ===== PageHeader =====
// 统一页面标题栏：标题 + 描述 + 右侧操作区
export function PageHeader({ title, description, actions, className = '' }) {
  return (
    <div className={`mb-6 flex items-start justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-gray-100">{title}</h1>
        {description && <p className="mt-1 text-sm text-gray-400">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

// ===== Badge =====
// variant: brand | success | warning | danger | gray
const BADGE_VARIANT = {
  brand: 'bg-brand-500/15 text-brand-300',
  success: 'bg-success-500/15 text-success-300',
  warning: 'bg-warning-500/15 text-warning-300',
  danger: 'bg-danger-500/15 text-danger-300',
  gray: 'bg-gray-700/50 text-gray-300',
}

export function Badge({ children, variant = 'gray', className = '' }) {
  return (
    <span className={`badge ${BADGE_VARIANT[variant] || BADGE_VARIANT.gray} ${className}`}>
      {children}
    </span>
  )
}

// ===== DataTable =====
// 统一数据表格：overflow-x-auto + hover 高亮 + 空态/加载态
// columns: [{ key, header, render?, className?, width? }]
// data: 行数据数组
// loading / emptyText / onRowClick
export function DataTable({
  columns = [],
  data = [],
  loading = false,
  emptyText = '暂无数据',
  onRowClick,
  rowKey = 'id',
  className = '',
}) {
  return (
    <div className={`table-wrap ${className}`}>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-900/80 text-left text-xs text-gray-400">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`whitespace-nowrap px-4 py-2.5 font-medium ${col.className || ''}`}
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
              <td colSpan={columns.length} className="px-4 py-8 text-center text-gray-500">
                <span className="inline-flex items-center gap-2">
                  <svg className="h-4 w-4 animate-spin text-brand-400" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  加载中...
                </span>
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center text-gray-500">
                {emptyText}
              </td>
            </tr>
          ) : (
            data.map((row, i) => (
              <tr
                key={row[rowKey] ?? i}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={`table-row-hover border-b border-gray-800/60 ${onRowClick ? 'cursor-pointer' : ''}`}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`px-4 py-2.5 text-gray-300 ${col.className || ''}`}
                  >
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

// ===== Pagination =====
// 统一分页控件
export function Pagination({ page, pageSize, total, onPageChange, className = '' }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  if (total === 0) return null
  return (
    <div className={`flex items-center justify-between gap-3 px-1 py-3 text-xs text-gray-400 ${className}`}>
      <span>
        共 {total} 条，第 {page}/{totalPages} 页
      </span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          上一页
        </Button>
        <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
          下一页
        </Button>
      </div>
    </div>
  )
}

export default { Button, Card, PageContainer, PageHeader, Badge, DataTable, Pagination }
