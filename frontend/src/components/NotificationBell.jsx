import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Megaphone, AlertTriangle, XCircle, ExternalLink } from 'lucide-react'
import { notificationsApi } from '../api/notifications'
import { toast } from '../store/toastStore'
import { fmtAbs } from '../utils/absTime'
import { guardNavPermission } from '../utils/permissions'

// 类型图标映射（带语义色容器：公告 info / 系统告警 warning / 执行失败 destructive）
const TYPE_ICON = {
  announcement: <Megaphone className="h-3.5 w-3.5" />,
  system_alert: <AlertTriangle className="h-3.5 w-3.5" />,
  execution_failed: <XCircle className="h-3.5 w-3.5" />,
}

// 类型 → 图标底色容器（浅色圆角底 + 语义色图标）
const TYPE_ICON_CLS = {
  announcement: 'bg-info/15 text-info',
  system_alert: 'bg-warning/15 text-warning',
  execution_failed: 'bg-destructive/15 text-destructive',
}

function getTypeIcon(type) {
  return TYPE_ICON[type] || <Bell className="h-3.5 w-3.5" />
}

function getTypeIconCls(type) {
  return TYPE_ICON_CLS[type] || 'bg-primary/15 text-primary'
}

// 根据通知关联资源生成跳转链接
function buildNotificationLink(n) {
  if (!n) return null
  if (n.related_type && n.related_id) {
    const map = {
      workflow: `/workflows?focus=${n.related_id}`,
      execution: `/executions?focus=${n.related_id}`,
      agent: `/agents/${n.related_id}/monitor`,
      tool: `/tools?focus=${n.related_id}`,
      knowledge_base: `/knowledge-bases?focus=${n.related_id}`,
      user: `/users?focus=${n.related_id}`,
    }
    if (map[n.related_type]) return map[n.related_type]
  }
  const typeMap = {
    announcement: null,
    system_alert: '/system/monitor',
    execution_failed: '/executions',
  }
  return typeMap[n.type] || null
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
// 轮询期间检测到新通知时，通过全局 Toast 弹窗提醒（可点击跳转）。
function NotificationBell() {
  const navigate = useNavigate()
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [recent, setRecent] = useState([])
  const [loadingRecent, setLoadingRecent] = useState(false)
  const [actioning, setActioning] = useState(false)
  const containerRef = useRef(null)
  // 已见过的通知 ID 集合：用于检测"新"通知（仅对未读通知弹窗）
  const seenIdsRef = useRef(new Set())
  // 上一次未读数：用于判断是否需要拉取最近通知做对比
  const prevUnreadRef = useRef(0)
  // 是否完成首次拉取（首次不弹窗，仅记录基线）
  const firstLoadRef = useRef(true)

  // 检测新通知并弹窗提醒
  const checkNewAndToast = useCallback(
    async (newUnread) => {
      // 未读数没有增长，跳过拉取最近通知
      if (newUnread <= prevUnreadRef.current) return
      try {
        const res = await notificationsApi.list(5, 0)
        const list = Array.isArray(res)
          ? res
          : res?.items || res?.notifications || []
        // 首次拉取：仅记录基线，不弹窗
        if (firstLoadRef.current) {
          list.forEach((n) => seenIdsRef.current.add(n.id))
          firstLoadRef.current = false
          return
        }
        // 后续轮询：对未见过的未读通知弹窗
        for (const n of list) {
          if (seenIdsRef.current.has(n.id)) continue
          seenIdsRef.current.add(n.id)
          if (n.is_read) continue
          // 弹窗提醒：点击跳转到关联资源或通知中心
          const link = buildNotificationLink(n)
          toast.warning(n.title || '收到新通知', {
            title: '新通知',
            duration: 6000,
            actionLabel: link ? '查看' : '查看通知',
            onClick: () => {
              navigate(link || '/notifications')
            },
          })
        }
      } catch {
        // 静默失败
      }
    },
    [navigate],
  )

  // 获取未读计数
  const loadUnread = useCallback(async () => {
    try {
      const res = await notificationsApi.unreadCount()
      // 后端返回 { unread_count: N }，兼容旧版 { count: N } 与裸数字
      const count = res?.unread_count ?? res?.count ?? (typeof res === 'number' ? res : 0)
      setUnread(count || 0)
      // 未读数增长时，拉取最近通知并弹窗提醒
      if (count > prevUnreadRef.current) {
        await checkNewAndToast(count)
      }
      prevUnreadRef.current = count || 0
    } catch {
      // 静默失败：铃铛不应因轮询错误打断用户
    }
  }, [checkNewAndToast])

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

  // 点击通知项：标记已读 + 跳转到关联资源或通知中心
  const handleClickNotification = async (n) => {
    if (!n.is_read) {
      // 静默标记已读
      notificationsApi.markRead(n.id).catch(() => {})
      setRecent((list) =>
        list.map((it) => (it.id === n.id ? { ...it, is_read: true } : it))
      )
      setUnread((u) => Math.max(0, u - 1))
    }
    const link = buildNotificationLink(n)
    setOpen(false)
    if (link) {
      navigate(link)
    } else {
      // 没有关联资源，跳转到通知中心查看完整内容（无权限时 toast 拦截）
      if (!guardNavPermission('notification', 'view', '通知中心')) return
      navigate('/notifications')
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
      {/* 铃铛按钮：悬停微抬 + 铃铛摆动反馈 */}
      <button
        type="button"
        onClick={handleToggle}
        className={`group relative flex h-9 w-9 items-center justify-center rounded-full bg-secondary text-foreground transition-all duration-200 hover:bg-accent hover:ring-1 hover:ring-primary/40 ${
          open ? 'bg-accent ring-1 ring-primary/40' : ''
        }`}
        aria-label="通知"
      >
        <Bell
          className={`h-5 w-5 transition-transform duration-300 ${
            unread > 0 ? 'dot-pulse' : 'group-hover:rotate-12'
          }`}
        />
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold tabular-nums text-destructive-foreground shadow ring-2 ring-background">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {/* 下拉面板 */}
      {open && (
        <div className="drawer-enter absolute right-0 z-dropdown mt-2 w-80 overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-2xl">
          {/* 头部 */}
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <span className="text-sm font-semibold text-foreground">通知</span>
            <span className="text-xs tabular-nums text-muted-foreground">{unread} 条未读</span>
          </div>

          {/* 通知列表 */}
          <div className="max-h-[400px] min-h-0 overflow-y-auto">
            {loadingRecent ? (
              <div className="flex flex-col gap-2.5 px-4 py-4">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex items-center gap-2.5">
                    <div className="skeleton-shimmer h-7 w-7 shrink-0 rounded-full" />
                    <div className="flex-1 space-y-1.5">
                      <div className="skeleton-shimmer h-3.5 w-3/4 rounded" />
                      <div className="skeleton-shimmer h-2.5 w-1/3 rounded" />
                    </div>
                  </div>
                ))}
              </div>
            ) : recent.length === 0 ? (
              <div className="flex h-24 flex-col items-center justify-center gap-1.5 text-muted-foreground">
                <Bell className="h-7 w-7 opacity-60" />
                <div className="text-xs">暂无通知</div>
              </div>
            ) : (
              recent.map((n) => {
                const link = buildNotificationLink(n)
                return (
                <button
                  type="button"
                  key={n.id}
                  onClick={() => handleClickNotification(n)}
                  className={`flex w-full items-start gap-2.5 border-l-2 px-4 py-2.5 text-left transition-colors hover:bg-accent ${
                    n.is_read
                      ? 'border-transparent'
                      : 'border-l-primary bg-primary/10'
                  }`}
                  title={link ? `点击查看关联资源` : '点击查看通知详情'}
                >
                  <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${getTypeIconCls(n.type)}`}>
                    {getTypeIcon(n.type)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1 truncate text-sm font-medium text-foreground">
                        {n.title || '(无标题)'}
                        {link && <ExternalLink className="h-3 w-3 shrink-0 text-primary/70" />}
                      </div>
                      {!n.is_read && (
                        <span className="dot-pulse h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                      )}
                    </div>
                    <div className="mt-0.5 whitespace-nowrap text-[11px] tabular-nums text-muted-foreground" title={fmtAbs(n.created_at)}>
                      {fmtRelative(n.created_at)}
                    </div>
                  </div>
                </button>
                )
              })
            )}
          </div>

          {/* 底部操作 */}
          <div className="flex items-center justify-between border-t border-border px-3 py-2">
            <button
              type="button"
              onClick={() => {
                if (!guardNavPermission('notification', 'view', '通知中心')) return
                setOpen(false)
                navigate('/notifications')
              }}
              className="rounded px-1 text-xs font-medium text-primary transition-colors hover:text-primary/80"
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
