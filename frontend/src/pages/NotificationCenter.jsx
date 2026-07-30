import { useCallback, useEffect, useState } from 'react'
import { notificationsApi } from '../api/notifications'

// 类型图标映射
const TYPE_ICON = {
  announcement: '📢',
  system_alert: '⚠️',
  execution_failed: '❌',
}

const TYPE_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'announcement', label: '📢 公告' },
  { value: 'system_alert', label: '⚠️ 系统告警' },
  { value: 'execution_failed', label: '❌ 执行失败' },
]

const READ_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'unread', label: '未读' },
  { value: 'read', label: '已读' },
]

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

// 绝对时间（hover 提示用）
function fmtAbsolute(t) {
  if (!t) return ''
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
}

const PAGE_SIZE = 20

function NotificationCenter() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // 筛选条件
  const [typeFilter, setTypeFilter] = useState('')
  const [readFilter, setReadFilter] = useState('')
  // 操作进行中：null | 'all' | <id>
  const [actionId, setActionId] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await notificationsApi.list(PAGE_SIZE, offset)
      const list = Array.isArray(res)
        ? res
        : res?.items || res?.notifications || []
      setItems(list)
      setTotal(res?.total ?? list.length)
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [offset])

  useEffect(() => {
    load()
  }, [load])

  // 客户端筛选（API 仅支持 limit/offset）
  const filtered = items.filter((n) => {
    if (typeFilter && n.type !== typeFilter) return false
    if (readFilter === 'unread' && n.is_read) return false
    if (readFilter === 'read' && !n.is_read) return false
    return true
  })

  const handleMarkRead = async (id) => {
    if (actionId !== null) return
    setActionId(id)
    try {
      await notificationsApi.markRead(id)
      setItems((list) =>
        list.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      )
    } catch (err) {
      setError(err.message || '标记已读失败')
    } finally {
      setActionId(null)
    }
  }

  const handleMarkAllRead = async () => {
    if (actionId !== null) return
    setActionId('all')
    try {
      await notificationsApi.markAllRead()
      setItems((list) => list.map((n) => ({ ...n, is_read: true })))
    } catch (err) {
      setError(err.message || '全部标记已读失败')
    } finally {
      setActionId(null)
    }
  }

  const handleDelete = async (id) => {
    if (actionId !== null) return
    setActionId(id)
    try {
      await notificationsApi.remove(id)
      setItems((list) => list.filter((n) => n.id !== id))
      setTotal((t) => Math.max(0, t - 1))
    } catch (err) {
      setError(err.message || '删除失败')
    } finally {
      setActionId(null)
    }
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const canPrev = offset > 0
  const canNext = offset + PAGE_SIZE < total

  const handlePrev = () => {
    if (canPrev) setOffset(Math.max(0, offset - PAGE_SIZE))
  }
  const handleNext = () => {
    if (canNext) setOffset(offset + PAGE_SIZE)
  }

  const hasUnread = items.some((n) => !n.is_read)

  const selectCls =
    'rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white outline-none focus:border-brand-500'

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      {/* 顶部标题栏 */}
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-100">通知中心</h1>
          <span className="text-xs text-gray-500">查看与管理站内通知</span>
        </div>
        <button
          type="button"
          onClick={handleMarkAllRead}
          disabled={!hasUnread || actionId !== null}
          className="btn-secondary btn-sm"
        >
          {actionId === 'all' ? '处理中...' : '全部标记已读'}
        </button>
      </header>

      {/* 筛选区 */}
      <div className="flex flex-wrap items-center gap-4 border-b border-gray-800 bg-gray-900/30 px-6 py-3">
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-400">类型</span>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className={selectCls}
          >
            {TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-400">状态</span>
          <select
            value={readFilter}
            onChange={(e) => setReadFilter(e.target.value)}
            className={selectCls}
          >
            {READ_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">🔔</div>
            <div className="text-sm">
              {items.length === 0
                ? '暂无通知'
                : '未匹配到符合筛选条件的通知'}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {filtered.map((n) => (
              <div
                key={n.id}
                className={`rounded-lg border border-gray-800 p-4 transition-colors hover:bg-gray-800/60 ${
                  n.is_read ? '' : 'border-l-2 border-l-brand-500'
                }`}
              >
                <div className="flex items-start gap-4">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gray-800 text-base">
                    {getTypeIcon(n.type)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-gray-100">
                        {n.title || '(无标题)'}
                      </span>
                      {!n.is_read && (
                        <span className="rounded bg-brand-500/20 px-1.5 py-0.5 text-[10px] font-medium text-brand-300">
                          未读
                        </span>
                      )}
                      {n.type && (
                        <span className="rounded bg-gray-700/60 px-1.5 py-0.5 text-[10px] text-gray-400">
                          {n.type}
                        </span>
                      )}
                    </div>
                    {n.content && (
                      <div className="mt-1 break-words text-xs leading-relaxed text-gray-400">
                        {n.content}
                      </div>
                    )}
                    <div
                      className="mt-2 text-[11px] text-gray-500"
                      title={fmtAbsolute(n.created_at)}
                    >
                      {fmtRelative(n.created_at)}
                    </div>
                  </div>
                  {/* 操作 */}
                  <div className="flex shrink-0 items-center gap-2">
                    {!n.is_read && (
                      <button
                        type="button"
                        onClick={() => handleMarkRead(n.id)}
                        disabled={actionId !== null}
                        className="btn-secondary btn-sm"
                      >
                        {actionId === n.id ? '处理中' : '标记已读'}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDelete(n.id)}
                      disabled={actionId !== null}
                      className="btn-danger btn-sm"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 分页 */}
        {!loading && filtered.length > 0 && (
          <div className="mt-4 flex items-center justify-between text-xs text-gray-400">
            <span>
              共 {total} 条，第 {currentPage} / {totalPages} 页
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handlePrev}
                disabled={!canPrev}
                className="btn-secondary btn-sm"
              >
                上一页
              </button>
              <button
                type="button"
                onClick={handleNext}
                disabled={!canNext}
                className="btn-secondary btn-sm"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default NotificationCenter
