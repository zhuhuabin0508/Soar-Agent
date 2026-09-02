// 页面切换动画：路由切换时触发 fade-in 过渡
//
// 用法(在 AppShell 里包裹 Outlet):
//   import PageTransition from './PageTransition'
//   <PageTransition><Outlet /></PageTransition>
//
// 实现:
// - 监听 useLocation().pathname 变化,作为 key 触发重新挂载
// - 子树挂载时执行 fade-in 动画(200ms,尊重 prefers-reduced-motion)
// - 不影响内部 state(因为只在 pathname 变化时重挂载,query/hash 变化不重挂载)
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

export default function PageTransition({ children, className = '' }) {
  const location = useLocation()
  // 用 pathname 作为 key,切换页面时重新挂载子树触发动画
  // 不用 location.key 是因为同页 query 变化也会变 key,过频重挂载
  const key = location.pathname
  const [visible, setVisible] = useState(false)
  const timerRef = useRef(null)

  // key 变化时执行动画:先设为 hidden,下一帧设为 visible 触发 transition
  useEffect(() => {
    setVisible(false)
    if (timerRef.current) cancelAnimationFrame(timerRef.current)
    timerRef.current = requestAnimationFrame(() => {
      timerRef.current = requestAnimationFrame(() => setVisible(true))
    })
    return () => {
      if (timerRef.current) cancelAnimationFrame(timerRef.current)
    }
  }, [key])

  return (
    <div
      key={key}
      // min-h-0 + h-full：在 flex column 父容器中约束高度，防止被子内容撑开
      // 破坏高度链导致内部 overflow-y-auto 失效（对话页滚动不到底部的根因）
      className={`page-transition min-h-0 h-full ${className}`}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(4px)',
        transition: 'opacity 200ms ease-out, transform 200ms ease-out',
      }}
    >
      {children}
    </div>
  )
}
