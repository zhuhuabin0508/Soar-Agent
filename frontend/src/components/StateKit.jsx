// 通用状态组件：LoadingSpinner / EmptyState / ErrorBanner
// 用于统一各页面的加载中、空数据、错误提示体验

// 加载中骨架屏：支持指定行数与高度
export function LoadingSpinner({ text = '加载中...', rows = 3, className = '' }) {
  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <svg
          className="h-4 w-4 animate-spin text-brand-400"
          viewBox="0 0 24 24"
          fill="none"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 0 1 4 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
        <span>{text}</span>
      </div>
      {/* 骨架行 */}
      {rows > 0 &&
        Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-12 animate-pulse rounded-md bg-gray-800/50"
            style={{ animationDelay: `${i * 0.1}s` }}
          />
        ))}
    </div>
  )
}

// 空状态：图标 + 标题 + 描述 + 可选操作按钮
export function EmptyState({
  icon = '📭',
  title = '暂无数据',
  description = '',
  action,
  className = '',
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-3 py-16 text-center ${className}`}
    >
      <div className="text-5xl opacity-60">{icon}</div>
      <div className="text-sm font-medium text-gray-400">{title}</div>
      {description && (
        <div className="max-w-md text-xs text-gray-500">{description}</div>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

// 错误提示横幅：红色背景 + 错误信息 + 可选重试按钮
export function ErrorBanner({
  message = '操作失败',
  onRetry,
  className = '',
}) {
  return (
    <div
      className={`flex items-center gap-3 rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2.5 text-sm text-red-300 ${className}`}
    >
      <svg
        className="h-4 w-4 shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <span className="flex-1">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded border border-red-700/60 px-2 py-0.5 text-xs text-red-300 transition hover:bg-red-900/40"
        >
          重试
        </button>
      )}
    </div>
  )
}

export default { LoadingSpinner, EmptyState, ErrorBanner }
