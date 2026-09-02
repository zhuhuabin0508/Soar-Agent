// 全局 Toast 容器：固定在右上角，渲染 toast 队列。
// 在 App.jsx 中挂载一次即可，任意位置调用 toast.success() 等均会在此显示。
//
// 动画：进场从右滑入 + 淡入；退场淡出（leaving 标记触发）。
// 支持 onClick：点击弹窗主体或「查看」按钮触发回调并关闭。
import { useEffect } from 'react'
import { CheckCircle2, XCircle, AlertTriangle, Info, X, ExternalLink } from 'lucide-react'
import { useToastStore } from '../store/toastStore'

const VARIANT_STYLE = {
  success: {
    bar: 'bg-success',
    icon: <CheckCircle2 className="h-5 w-5 text-success" />,
  },
  error: {
    bar: 'bg-destructive',
    icon: <XCircle className="h-5 w-5 text-destructive" />,
  },
  warning: {
    bar: 'bg-warning',
    icon: <AlertTriangle className="h-5 w-5 text-warning" />,
  },
  info: {
    bar: 'bg-info',
    icon: <Info className="h-5 w-5 text-info" />,
  },
}

function ToastItem({ item }) {
  const { dismiss, remove } = useToastStore.getState()
  const style = VARIANT_STYLE[item.variant] || VARIANT_STYLE.info

  // leaving 标记后等待动画再移除
  useEffect(() => {
    if (item.leaving) {
      const t = setTimeout(() => remove(item.id), 200)
      return () => clearTimeout(t)
    }
  }, [item.leaving, item.id, remove])

  const handleClick = () => {
    if (item.onClick) {
      item.onClick()
      dismiss(item.id)
    }
  }

  return (
    <div
      className={`pointer-events-auto flex w-80 items-start gap-3 overflow-hidden rounded-lg border border-border bg-card shadow-xl transition-all duration-200 ${
        item.leaving ? 'translate-x-4 opacity-0' : 'translate-x-0 opacity-100'
      } ${item.onClick ? 'cursor-pointer hover:border-primary/50' : ''}`}
      role="alert"
      onClick={item.onClick ? handleClick : undefined}
    >
      {/* 左侧语义色条 */}
      <div className={`h-full w-1 shrink-0 self-stretch ${style.bar}`} />
      <div className="flex min-w-0 flex-1 items-start gap-2.5 p-3">
        <span className="mt-0.5 shrink-0">{style.icon}</span>
        <div className="min-w-0 flex-1">
          {item.title && (
            <div className="text-sm font-semibold text-foreground">
              {item.title}
            </div>
          )}
          <div
            className={`text-sm text-foreground/90 break-words ${
              item.title ? 'mt-0.5' : ''
            }`}
          >
            {item.message}
          </div>
          {item.onClick && item.actionLabel && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                handleClick()
              }}
              className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80"
            >
              <ExternalLink className="h-3 w-3" />
              {item.actionLabel}
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            dismiss(item.id)
          }}
          className="shrink-0 rounded p-0.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          aria-label="关闭"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}

export default function ToastContainer() {
  const items = useToastStore((s) => s.items)
  if (items.length === 0) return null
  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[100] flex flex-col gap-2">
      {items.map((item) => (
        <ToastItem key={item.id} item={item} />
      ))}
    </div>
  )
}
