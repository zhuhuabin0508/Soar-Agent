// 全局键盘快捷键 Hook
//
// 提供以下快捷键:
// - `/`          聚焦页面上的搜索框(任何带 [data-hotkey="search"] 的元素)
// - `Ctrl/Cmd+Enter`  触发当前页面的主提交按钮(带 [data-hotkey="submit"] 的元素)
// - `Esc`        关闭顶层模态/抽屉(由 Modal/Drawer 自身处理,这里仅做兜底)
// - `g d` 双键    跳转到 Dashboard
// - `g a` 双键    跳转到 Agents
// - `g w` 双键    跳转到 Workflows
//
// 用法(在 App.jsx 根挂载一次):
//   import { useHotkeys } from './hooks/useHotkeys'
//   function App() {
//     useHotkeys()
//     return <RouterProvider ... />
//   }
//
// 搜索框标记(各列表页的 FilterBar 自动有 data-hotkey="search"):
//   <input data-hotkey="search" ... />
//
// 提交按钮标记(各编辑页主表单):
//   <button data-hotkey="submit" ... />
//
// 设计要点:
// - 仅在 input/textarea 不聚焦时响应 `/`(避免输入冲突)
// - Ctrl/Cmd+Enter 在表单内也响应(原生提交)
// - 双键 `g x`:按下 g 后 800ms 内按 x 才触发,超时重置
// - 监听 keydown,useEffect 挂载一次
import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'

const IGNORE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

function isTyping() {
  const el = document.activeElement
  if (!el) return false
  return IGNORE_TAGS.has(el.tagName) || el.isContentEditable
}

export function useHotkeys() {
  const navigate = useNavigate()
  const lastGRef = useRef(0)  // 上次按 g 的时间戳

  useEffect(() => {
    const handler = (e) => {
      // —— `/` 聚焦搜索 ——
      if (e.key === '/' && !isTyping() && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const el = document.querySelector('[data-hotkey="search"]')
        if (el) {
          e.preventDefault()
          el.focus()
          if (el.select) el.select()
        }
        return
      }

      // —— Ctrl/Cmd+Enter 触发主提交 ——
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        const el = document.querySelector('[data-hotkey="submit"]')
        if (el && !el.disabled) {
          e.preventDefault()
          el.click()
        }
        return
      }

      // —— 双键 `g x` 跳转 ——
      if (e.key === 'g' && !isTyping() && !e.ctrlKey && !e.metaKey) {
        lastGRef.current = Date.now()
        return
      }
      if (lastGRef.current > 0 && Date.now() - lastGRef.current < 800) {
        if (e.key === 'd' && !isTyping()) {
          e.preventDefault()
          navigate('/dashboard')
          lastGRef.current = 0
        } else if (e.key === 'a' && !isTyping()) {
          e.preventDefault()
          navigate('/agents')
          lastGRef.current = 0
        } else if (e.key === 'w' && !isTyping()) {
          e.preventDefault()
          navigate('/workflows')
          lastGRef.current = 0
        } else if (e.key === 't' && !isTyping()) {
          e.preventDefault()
          navigate('/tools')
          lastGRef.current = 0
        } else if (e.key === 'e' && !isTyping()) {
          e.preventDefault()
          navigate('/executions')
          lastGRef.current = 0
        } else {
          // 其他键取消 g 状态
          lastGRef.current = 0
        }
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [navigate])
}

export default useHotkeys
