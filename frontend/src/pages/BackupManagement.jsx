import { useEffect, useState, useCallback } from 'react'
import { backupApi } from '../api/backup'

// ============ 工具函数 ============
// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 格式化文件大小：字节 → KB/MB/GB
function fmtSize(bytes) {
  if (bytes == null) return '-'
  const n = Number(bytes)
  if (!isFinite(n) || n < 0) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(2)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

// ============ 通用小组件 ============
// 状态标签：completed=绿 / failed=红 / running=黄 / 其它=灰
function StatusBadge({ status }) {
  const map = {
    completed: 'bg-success-500/20 text-success-300',
    failed: 'bg-danger-500/20 text-danger-300',
    running: 'bg-warning-500/20 text-warning-300',
  }
  const cls = map[status] || 'bg-gray-500/20 text-gray-400'
  return (
    <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {status || 'unknown'}
    </span>
  )
}

// 类型标签：manual=蓝 / scheduled=紫 / 其它=灰
function TypeBadge({ type }) {
  const map = {
    manual: { cls: 'bg-brand-500/20 text-brand-300', label: '手动备份' },
    scheduled: { cls: 'bg-purple-500/20 text-purple-300', label: '定时备份' },
  }
  const item = map[type] || { cls: 'bg-gray-500/20 text-gray-400', label: type || '-' }
  return (
    <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${item.cls}`}>
      {item.label}
    </span>
  )
}

// ============ 主组件 ============
const PAGE_SIZE = 20

function BackupManagement() {
  const [backups, setBackups] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // 创建备份中
  const [creating, setCreating] = useState(false)
  // 行内操作中（按 id 记录，防止重复点击）
  const [actioning, setActioning] = useState({})
  // 操作提示消息
  const [toast, setToast] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await backupApi.list(PAGE_SIZE, offset)
      setBackups(res?.backups || [])
      setTotal(res?.total ?? 0)
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

  // 短暂提示
  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 2500)
  }

  // 创建手动备份
  const handleCreate = async () => {
    setCreating(true)
    try {
      await backupApi.create('manual')
      showToast('备份创建成功')
      // 创建后回到第一页并刷新
      setOffset(0)
      await load()
    } catch (err) {
      setError(err.message || '创建备份失败')
    } finally {
      setCreating(false)
    }
  }

  // 下载备份
  const handleDownload = async (id) => {
    setActioning((p) => ({ ...p, [id]: 'download' }))
    try {
      await backupApi.download(id)
      showToast('下载已开始')
    } catch (err) {
      window.alert(err.message || '下载失败')
    } finally {
      setActioning((p) => {
        const n = { ...p }
        delete n[id]
        return n
      })
    }
  }

  // 从备份恢复（二次确认）
  const handleRestore = async (id) => {
    const ok = window.confirm(
      '警告：恢复操作将覆盖当前数据库，且不可撤销。\n确定要从该备份恢复吗？'
    )
    if (!ok) return
    setActioning((p) => ({ ...p, [id]: 'restore' }))
    try {
      await backupApi.restore(id)
      showToast('恢复完成')
      await load()
    } catch (err) {
      window.alert(err.message || '恢复失败')
    } finally {
      setActioning((p) => {
        const n = { ...p }
        delete n[id]
        return n
      })
    }
  }

  // 删除备份（二次确认）
  const handleDelete = async (id) => {
    const ok = window.confirm('确定要删除该备份吗？此操作不可撤销。')
    if (!ok) return
    setActioning((p) => ({ ...p, [id]: 'delete' }))
    try {
      await backupApi.remove(id)
      showToast('删除成功')
      // 删除后若当前页空了且不在第一页，回退一页
      if (backups.length === 1 && offset > 0) {
        setOffset(Math.max(0, offset - PAGE_SIZE))
      } else {
        await load()
      }
    } catch (err) {
      window.alert(err.message || '删除失败')
    } finally {
      setActioning((p) => {
        const n = { ...p }
        delete n[id]
        return n
      })
    }
  }

  // 分页
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

  // 小图标按钮
  const iconBtnCls =
    'inline-flex h-7 w-7 items-center justify-center rounded-md border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50'

  return (
    <div className="min-h-full bg-gray-950 p-6 text-gray-100">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        {/* 顶部标题栏 */}
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-semibold text-gray-100">数据备份与恢复</h1>
            <span className="text-xs text-gray-500">手动备份 / 下载 / 恢复 / 删除</span>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating}
            className="btn-primary"
          >
            {creating ? '备份中...' : '创建备份'}
          </button>
        </header>

        {/* 错误提示 */}
        {error && (
          <div className="w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
            {error}
          </div>
        )}

        {/* 短暂提示 */}
        {toast && (
          <div className="w-full rounded-md border border-success-500/40 bg-success-500/10 px-4 py-2 text-sm text-success-300">
            {toast}
          </div>
        )}

        {/* 备份记录表格 */}
        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : backups.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 rounded-lg border border-gray-800 bg-gray-900 text-gray-500">
            <div className="text-4xl">🗄️</div>
            <div className="text-sm">暂无备份记录，点击右上角“创建备份”开始第一次备份</div>
          </div>
        ) : (
          <div className="w-full overflow-x-auto rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full min-w-[860px] table-fixed border-collapse text-sm">
              <thead className="bg-gray-900 text-gray-400">
                <tr>
                  <th className="w-44 px-4 py-3 text-left font-medium">备份时间</th>
                  <th className="w-24 px-4 py-3 text-left font-medium">类型</th>
                  <th className="w-28 px-4 py-3 text-left font-medium">文件大小</th>
                  <th className="w-24 px-4 py-3 text-left font-medium">状态</th>
                  <th className="w-28 px-4 py-3 text-left font-medium">创建者</th>
                  <th className="w-36 px-4 py-3 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {backups.map((b, idx) => {
                  const act = actioning[b.id]
                  return (
                    <tr
                      key={b.id}
                      className={`border-t border-gray-800 transition-colors hover:bg-brand-500/5 ${
                        idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
                      }`}
                    >
                      <td className="px-4 py-3 text-gray-300">{fmtTime(b.created_at)}</td>
                      <td className="px-4 py-3">
                        <TypeBadge type={b.backup_type} />
                      </td>
                      <td className="px-4 py-3 text-gray-300">{fmtSize(b.file_size)}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={b.status} />
                      </td>
                      <td className="truncate px-4 py-3 text-gray-300">
                        {b.created_by || '-'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            title="下载"
                            onClick={() => handleDownload(b.id)}
                            disabled={b.status !== 'completed' || !!act}
                            className={iconBtnCls}
                          >
                            ⬇
                          </button>
                          <button
                            type="button"
                            title="恢复"
                            onClick={() => handleRestore(b.id)}
                            disabled={b.status !== 'completed' || !!act}
                            className={iconBtnCls}
                          >
                            ↺
                          </button>
                          <button
                            type="button"
                            title="删除"
                            onClick={() => handleDelete(b.id)}
                            disabled={!!act}
                            className={`${iconBtnCls} hover:border-danger-500/60 hover:bg-danger-500/10 hover:text-danger-300`}
                          >
                            ✕
                          </button>
                          {act && (
                            <span className="ml-1 text-[11px] text-gray-500">
                              {act === 'download'
                                ? '下载中'
                                : act === 'restore'
                                ? '恢复中'
                                : '删除中'}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* 分页 */}
        {!loading && backups.length > 0 && (
          <div className="flex items-center justify-between text-xs text-gray-400">
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

export default BackupManagement
