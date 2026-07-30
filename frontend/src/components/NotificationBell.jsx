import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { notificationsApi } from '../api/notifications'

// 类型图标映射
const TYPE_ICON = {
  announcement: '📢',
  system_alert: '⚠️',
  execution_failed: '❌',
}

function getTypeIcon(type) {
  return TYPE_ICON[type] || '🔔'
}

// 相对时间格式化：刚刚 / X分钟前 / X小时前 / X天前
function fmtRelative(t) {
  if (!t) return '-'
  let ts
  try {
    ts = new Date(t).getTime()
  } catch {
    return t
  }
  if (isNaN(ts)) return t
  const diff = Date.now() - ts
  if (diff < 0) return '刚刚'
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return '刚刚'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  return `${days}天前`
}

// 通知铃铛：固定在右上角，展示未读数量徽章 + 下拉面板（最近 5 条）
function NotificationBell() {
  const navigate = useNavigate()
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [recent, setRecent] = useState([])
  const [loadingRecent, setLoadingRecent] = useState(false)
  const [actioning, setActioning] = useState(false)
  const containerRef = useRef(null)

  // 获取未读计数
  const loadUnread = useCallback(async () => {
    try {
      const res = await notificationsApi.unreadCount()
      const count = res?.count ?? (typeof res === 'number' ? res : 0)
      setUnread(count || 0)
    } catch {
      // 静默失败：铃铛不应因轮询错误打断用户
    }
  }, [])

  // 初始化 + 每 30 秒自动刷新未读计数
  useEffect(() => {
    loadUnread()
    const timer = setInterval(loadUnread, 30000)
    return () => clearInterval(timer)
  }, [loadUnread])

  // 下拉面板外点击关闭
  useEffect(() => {
    if (!open) return
    function handleMouseDown(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [open])

  // 拉取最近 5 条通知
  const loadRecent = useCallback(async () => {
    setLoadingRecent(true)
    try {
      const res = await notificationsApi.list(5, 0)
      const list = Array.isArray(res)
        ? res
        : res?.items || res?.notifications || []
      setRecent(list)
    } catch {
      setRecent([])
    } finally {
      setLoadingRecent(false)
    }
  }, [])

  const handleToggle = () => {
    const next = !open
    setOpen(next)
    if (next) loadRecent()
  }

  // 标记单条已读
  const handleMarkRead = async (id) => {
    try {
      await notificationsApi.markRead(id)
      setRecent((list) =>
        list.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      )
      setUnread((u) => Math.max(0, u - 1))
    } catch {
      // 静默失败
    }
  }

  // 全部标记已读
  const handleMarkAllRead = async () => {
    if (actioning) return
    setActioning(true)
    try {
      await notificationsApi.markAllRead()
      setRecent((list) => list.map((n) => ({ ...n, is_read: true })))
      setUnread(0)
    } catch {
      // 静默失败
    } finally {
      setActioning(false)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      {/* 铃铛按钮 */}
      <button
        type="button"
        onClick={handleToggle}
        className="relative flex h-9 w-9 items-center justify-center rounded-full bg-gray-800 text-gray-200 transition-colors hover:bg-gray-700"
        aria-label="通知"
      >
        <span className="text-base leading-none">🔔</span>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-brand-500 px-1 text-[10px] font-semibold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {/* 下拉面板 */}
      {open && (
        <div className="absolute right-0 z-dropdown mt-2 w-80 overflow-hidden rounded-lg border border-gray-700 bg-gray-800 shadow-xl">
          {/* 头部 */}
          <div className="flex items-center justify-between border-b border-gray-700 px-4 py-2.5">
            <span className="text-sm font-semibold text-gray-100">通知</span>
            <span className="text-xs text-gray-500">{unread} 条未读</span>
          </div>

          {/* 通知列表 */}
          <div className="max-h-[400px] min-h-0 overflow-y-auto">
            {loadingRecent ? (
              <div className="flex h-24 items-center justify-center text-xs text-gray-500">
                加载中...
              </div>
            ) : recent.length === 0 ? (
              <div className="flex h-24 flex-col items-center justify-center gap-1 text-gray-500">
                <div className="text-2xl">🔔</div>
                <div className="text-xs">暂无通知</div>
              </div>
            ) : (
              recent.map((n) => (
                <button
                  type="button"
                  key={n.id}
                  onClick={() => {
                    if (!n.is_read) handleMarkRead(n.id)
                  }}
                  className={`flex w-full items-start gap-2 border-l-2 px-4 py-2.5 text-left transition-colors hover:bg-gray-700/40 ${
                    n.is_read
                      ? 'border-transparent'
                      : 'border-l-brand-500 bg-brand-500/10'
                  }`}
                >
                  <span className="mt-0.5 text-base leading-none">
                    {getTypeIcon(n.type)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm text-gray-100">
                        {n.title || '(无标题)'}
                      </div>
                      {!n.is_read && (
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
                      )}
                    </div>
                    <div className="mt-0.5 text-[11px] text-gray-500">
                      {fmtRelative(n.created_at)}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>

          {/* 底部操作 */}
          <div className="flex items-center justify-between border-t border-gray-700 px-3 py-2">
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                navigate('/notifications')
              }}
              className="text-xs text-brand-300 hover:text-brand-200"
            >
              查看全部
            </button>
            <button
              type="button"
              onClick={handleMarkAllRead}
              disabled={unread === 0 || actioning}
              className="btn-secondary btn-sm"
            >
              {actioning ? '处理中...' : '全部标记已读'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default NotificationBell
