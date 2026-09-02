// 定时自动刷新 hook：支持普通全量刷新与带游标的增量刷新
//
// 用法：
//   全量：  const { enabled, toggle } = useAutoRefresh(load, { interval: 5000 })
//   增量：  useAutoRefresh(() => pull(afterIdRef.current), { interval: 5000 }) —— 回调内部自行维护游标
//
// 页面不可见（document.hidden）时暂停轮询，回来立即补一次。
import { useEffect, useRef, useState, useCallback } from 'react'

export function useAutoRefresh(fetcher, { interval = 5000, enabled = false } = {}) {
  const [on, setOn] = useState(enabled)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const timerRef = useRef(null)

  const run = useCallback(async () => {
    try {
      await fetcherRef.current()
    } catch { /* 刷新失败静默，下一轮重试 */ }
  }, [])

  useEffect(() => {
    if (!on) return undefined
    // 立即执行一次，再按间隔轮询
    run()
    timerRef.current = setInterval(() => {
      if (document.hidden) return // 页面不可见时跳过本轮
      run()
    }, interval)
    const onVisible = () => {
      if (!document.hidden) run() // 回到页面立即补一次
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [on, interval, run])

  const toggle = useCallback(() => setOn((v) => !v), [])

  return { enabled: on, setEnabled: setOn, toggle, refresh: run }
}

export default useAutoRefresh
