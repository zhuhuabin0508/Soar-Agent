import { useState, useEffect, useCallback, useRef } from 'react'

// 定期将数据自动保存到 localStorage，刷新或崩溃后可恢复草稿
export function useAutoSave(key, data, intervalMs = 30000) {
  const [draft, setDraft] = useState(() => {
    try {
      const saved = localStorage.getItem(key)
      return saved ? JSON.parse(saved) : null
    } catch {
      return null
    }
  })
  const lastSavedRef = useRef('')

  useEffect(() => {
    const timer = setInterval(() => {
      try {
        const serialized = JSON.stringify(data)
        if (serialized !== lastSavedRef.current && serialized !== '{}') {
          localStorage.setItem(key, serialized)
          lastSavedRef.current = serialized
        }
      } catch {
        // localStorage 满或不可序列化，静默失败
      }
    }, intervalMs)
    return () => clearInterval(timer)
  }, [key, data, intervalMs])

  const clearDraft = useCallback(() => {
    try {
      localStorage.removeItem(key)
      setDraft(null)
      lastSavedRef.current = ''
    } catch {
      // ignore
    }
  }, [key])

  return { draft, clearDraft }
}
