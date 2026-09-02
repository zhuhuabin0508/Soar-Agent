import { createContext, useContext, useState, useCallback } from 'react'

// 全局 Loading Context：提供 showLoading / hideLoading 方法
const GlobalLoadingContext = createContext(null)

// 在未包裹 Provider 时返回空操作，避免崩溃
export function useGlobalLoading() {
  const ctx = useContext(GlobalLoadingContext)
  if (!ctx) return { showLoading: () => {}, hideLoading: () => {} }
  return ctx
}

// 全屏 Loading 遮罩 Provider：长耗时操作时防止用户重复点击
export function GlobalLoadingProvider({ children }) {
  const [visible, setVisible] = useState(false)
  const [text, setText] = useState('处理中...')

  const showLoading = useCallback((t = '处理中...') => {
    setText(t)
    setVisible(true)
  }, [])

  const hideLoading = useCallback(() => {
    setVisible(false)
  }, [])

  return (
    <GlobalLoadingContext.Provider value={{ showLoading, hideLoading }}>
      {children}
      {visible && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3 rounded-lg bg-card px-8 py-6 shadow-2xl">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-primary" />
            <div className="text-sm text-muted-foreground">{text}</div>
          </div>
        </div>
      )}
    </GlobalLoadingContext.Provider>
  )
}
