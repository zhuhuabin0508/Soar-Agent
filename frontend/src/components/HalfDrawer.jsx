import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

/**
 * 通用半屏抽屉组件：右侧滑入，宽度 50%（max-w-3xl）。
 *
 * Props:
 *   - open: boolean        是否打开
 *   - onClose: () => void  关闭回调
 *   - title: string        抽屉标题
 *   - children: ReactNode  抽屉内容
 *   - loading: boolean     内容加载中（可选）
 *   - footer: ReactNode    底部固定操作区（可选，固定在抽屉底部不随内容滚动）
 */
function HalfDrawer({ open, onClose, title, children, loading, footer }) {
  // ESC 键关闭
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  // 打开时禁止背景滚动
  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  if (!open) return null

  // 通过 Portal 渲染到 body，避免祖先元素存在 transform/backdrop-filter 等
  // 导致 position:fixed 失效（抽屉只显示下半部分）的问题。
  return createPortal(
    <div className="fixed inset-0 z-[100] flex justify-end">
      {/* 遮罩层 */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* 抽屉主体 */}
      <div className="relative flex h-full w-1/2 min-w-[480px] max-w-3xl flex-col border-l border-border bg-card shadow-2xl animate-[slideIn_0.2s_ease-out]">
        <style>{`
          @keyframes slideIn {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
          }
        `}</style>

        {/* 标题栏 */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-base font-semibold text-foreground">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 内容滚动区 */}
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground/70">
              加载中...
            </div>
          ) : (
            children
          )}
        </div>

        {/* 底部固定操作区（可选） */}
        {footer && (
          <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border bg-card/60 px-6 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

export default HalfDrawer
