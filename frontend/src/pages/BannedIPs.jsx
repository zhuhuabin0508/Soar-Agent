import { useEffect, useState, useCallback, useRef } from 'react'
import { bannedIpsApi } from '../api/bannedIps'
import { useAuthStore } from '../store/authStore'
import { Modal } from '../components/Dialog'
import { inputCls } from '../components/property/FormControls'

// 封禁等级中文映射 + 配色
const LEVEL_META = {
  low: { label: '低', cls: 'bg-brand-500/15 text-brand-300' },
  medium: { label: '中', cls: 'bg-yellow-500/15 text-yellow-300' },
  high: { label: '高', cls: 'bg-orange-500/15 text-orange-300' },
  serious: { label: '严重', cls: 'bg-danger-500/20 text-danger-300' },
}

// 封禁状态中文映射 + 配色
const STATUS_META = {
  active: { label: '封禁中', cls: 'bg-danger-500/20 text-danger-300' },
  expired: { label: '已过期', cls: 'bg-gray-700 text-gray-400' },
  unblocked: { label: '已解封', cls: 'bg-success-500/20 text-success-300' },
}

// 来源标识中文映射 + 配色
const SOURCE_META = {
  manual: { label: '手动添加', cls: 'bg-brand-500/15 text-brand-300' },
  agent: { label: '智能体添加', cls: 'bg-purple-500/15 text-purple-300' },
}

// 封禁等级选项（供新增表单使用）
const LEVEL_OPTIONS = [
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'serious', label: '严重' },
]

const STATUS_FILTERS = [
  { value: '', label: '全部状态' },
  { value: 'active', label: '封禁中' },
  { value: 'expired', label: '已过期' },
  { value: 'unblocked', label: '已解封' },
]

function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 秒数 → 友好时长描述（0 表示永久封禁）
function humanizeDuration(sec) {
  if (sec == null) return '-'
  const s = Number(sec)
  if (!Number.isFinite(s)) return '-'
  if (s <= 0) return '永久'
  if (s >= 86400) return `${Math.floor(s / 86400)} 天`
  if (s >= 3600) return `${Math.floor(s / 3600)} 小时`
  if (s >= 60) return `${Math.floor(s / 60)} 分钟`
  return `${s} 秒`
}

// 过期时间格式化：9999 年视为永久封禁
function fmtExpiry(t) {
  if (!t) return '-'
  if (String(t).startsWith('9999')) return '永久'
  return fmtTime(t)
}

// ============ 详情弹窗：展示已封禁 IP 的所有信息 ============
function DetailModal({ open, record, onClose, onUnban, onHardDelete, canUnban, unbanning, deleting }) {
  if (!record) return null
  const levelMeta = LEVEL_META[record.ban_level] || {
    label: record.ban_level,
    cls: 'bg-gray-700 text-gray-300',
  }
  const statusMeta = STATUS_META[record.status] || {
    label: record.status,
    cls: 'bg-gray-700 text-gray-300',
  }

  const fields = [
    { label: 'IP 地址', value: record.ip, mono: true },
    { label: '封禁等级', value: levelMeta.label, badge: levelMeta.cls },
    { label: '当前状态', value: statusMeta.label, badge: statusMeta.cls },
    { label: '来源', value: (SOURCE_META[record.source] || { label: record.source || '-' }).label, badge: (SOURCE_META[record.source] || {}).cls },
    { label: '封禁时长', value: humanizeDuration(record.ban_duration) },
    { label: '过期时间', value: fmtExpiry(record.expired_at) },
    { label: '违规次数', value: record.violation_count ?? 0 },
    { label: '归属地区', value: record.region || '-' },
    { label: '封禁时间', value: fmtTime(record.created_at) },
    { label: '更新时间', value: fmtTime(record.updated_at) },
  ]

  return (
    <Modal
      open={open}
      title={`已封禁 IP 详情：${record.ip || ''}`}
      onClose={onClose}
      maxWidth="max-w-2xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            关闭
          </button>
          {canUnban && record.status === 'active' && (
            <button
              type="button"
              onClick={() => onUnban(record)}
              disabled={unbanning || deleting}
              className="btn-danger"
            >
              {unbanning ? '解封中…' : '手动解封'}
            </button>
          )}
          {canUnban && (
            <button
              type="button"
              onClick={() => onHardDelete(record)}
              disabled={unbanning || deleting}
              className="btn-danger"
            >
              {deleting ? '删除中…' : '硬删除记录'}
            </button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {/* 基本信息网格：填满弹窗宽度 */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-3">
          {fields.map((f) => (
            <div key={f.label} className="min-w-0">
              <div className="mb-1 text-xs font-medium text-gray-500">
                {f.label}
              </div>
              {f.badge ? (
                <span
                  className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${f.badge}`}
                >
                  {f.value}
                </span>
              ) : (
                <div
                  className={`truncate text-sm text-gray-200 ${
                    f.mono ? 'font-mono' : ''
                  }`}
                  title={String(f.value)}
                >
                  {f.value}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* 封禁原因：整行展示 */}
        <div className="min-w-0">
          <div className="mb-1 text-xs font-medium text-gray-500">封禁原因</div>
          <div className="w-full rounded-md border border-gray-800 bg-gray-950/60 p-3 text-sm text-gray-300">
            {record.reason || '（未填写）'}
          </div>
        </div>
      </div>
    </Modal>
  )
}

// ============ 主页面 ============
function BannedIPs() {
  const user = useAuthStore((s) => s.user)
  const canUnban = user?.role === 'admin'

  const [records, setRecords] = useState([])
  const [stats, setStats] = useState({ total: 0, active: 0, expired: 0, unblocked: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 过滤条件
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  // 详情弹窗
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRecord, setDetailRecord] = useState(null)
  const [unbanning, setUnbanning] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // 导入导出
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const fileInputRef = useRef(null)

  // 新增封禁弹窗
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createForm, setCreateForm] = useState({
    ip: '',
    ban_level: 'medium',
    ban_duration: 3600,
    region: '',
    reason: '',
  })

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [list, st] = await Promise.all([
        bannedIpsApi.list({ search, status: statusFilter }),
        bannedIpsApi.stats(),
      ])
      setRecords(Array.isArray(list) ? list : [])
      setStats(st || { total: 0, active: 0, expired: 0, unblocked: 0 })
      setError('')
    } catch (err) {
      setError(err.message || '加载已封禁 IP 失败')
    } finally {
      setLoading(false)
    }
  }, [search, statusFilter])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const handleUnban = async (record) => {
    if (!record) return
    if (!window.confirm(`确定手动解封 IP「${record.ip}」吗？解封后将无法恢复封禁状态。`))
      return
    setUnbanning(true)
    try {
      await bannedIpsApi.unban(record.id)
      setDetailOpen(false)
      setDetailRecord(null)
      await loadAll()
    } catch (err) {
      window.alert(`解封失败：${err.message || err}`)
    } finally {
      setUnbanning(false)
    }
  }

  // 硬删除：从数据库物理删除记录（不可恢复）
  // 二次确认要求用户输入完整 IP 地址匹配，防止误操作
  const handleHardDelete = async (record) => {
    if (!record) return
    const input = window.prompt(
      `⚠️ 硬删除将彻底从数据库删除 IP「${record.ip}」的记录，不可恢复！\n` +
      `如确认删除，请输入该 IP 地址以继续：`
    )
    if (input === null) return
    if (input.trim() !== record.ip) {
      window.alert('输入的 IP 地址不匹配，已取消删除。')
      return
    }
    setDeleting(true)
    try {
      await bannedIpsApi.hardDelete(record.id)
      setDetailOpen(false)
      setDetailRecord(null)
      await loadAll()
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    } finally {
      setDeleting(false)
    }
  }

  // 手动新增封禁 IP
  const handleCreate = async () => {
    if (!createForm.ip.trim()) {
      window.alert('请填写 IP 地址')
      return
    }
    setCreating(true)
    try {
      await bannedIpsApi.create({
        ip: createForm.ip.trim(),
        ban_level: createForm.ban_level,
        ban_duration: Number(createForm.ban_duration) || 0,
        region: createForm.region.trim(),
        reason: createForm.reason.trim(),
      })
      setCreateOpen(false)
      setCreateForm({ ip: '', ban_level: 'medium', ban_duration: 3600, region: '', reason: '' })
      await loadAll()
    } catch (err) {
      window.alert(`新增失败：${err.message || err}`)
    } finally {
      setCreating(false)
    }
  }

  // 导出 CSV
  const handleExport = async () => {
    setExporting(true)
    try {
      await bannedIpsApi.exportCsv()
    } catch (err) {
      window.alert(`导出失败：${err.message || err}`)
    } finally {
      setExporting(false)
    }
  }

  // 导入 CSV：点击按钮触发隐藏文件选择
  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  // 导入 CSV：处理选中的文件
  const handleImportFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = '' // 重置，允许重复选择同一文件
    if (!file) return
    setImporting(true)
    try {
      const result = await bannedIpsApi.importCsv(file)
      setImportResult(result)
      await loadAll()
    } catch (err) {
      window.alert(`导入失败：${err.message || err}`)
    } finally {
      setImporting(false)
    }
  }

  const statCards = [
    { key: 'total', label: '总计', value: stats.total, icon: '📋', cls: 'text-gray-200' },
    { key: 'active', label: '封禁中', value: stats.active, icon: '🔴', cls: 'text-danger-300' },
    { key: 'expired', label: '已过期', value: stats.expired, icon: '⏰', cls: 'text-gray-400' },
    { key: 'unblocked', label: '已解封', value: stats.unblocked, icon: '✅', cls: 'text-success-300' },
  ]

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-100">已封禁 IP</h1>
          <span className="text-xs text-gray-500">
            共 {records.length} 条 / 总计 {stats.total} 条
          </span>
        </div>
        <div className="flex items-center gap-2">
          {canUnban && (
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="btn-primary btn-sm"
            >
              + 新增封禁
            </button>
          )}
          <button
            type="button"
            onClick={handleExport}
            disabled={exporting}
            className="btn-secondary btn-sm"
          >
            {exporting ? '导出中...' : '导出 CSV'}
          </button>
          {canUnban && (
            <button
              type="button"
              onClick={handleImportClick}
              disabled={importing}
              className="btn-secondary btn-sm"
            >
              {importing ? '导入中...' : '导入 CSV'}
            </button>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={handleImportFile}
          />
          <button type="button" onClick={loadAll} className="btn-secondary btn-sm">
            刷新
          </button>
        </div>
      </header>

      {/* 统计卡片：4 列填满宽度 */}
      <div className="grid grid-cols-2 gap-3 px-6 pt-4 md:grid-cols-4">
        {statCards.map((c) => (
          <div
            key={c.key}
            className="w-full rounded-lg border border-gray-800 bg-gray-900/40 px-4 py-3"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">{c.label}</span>
              <span className="text-base">{c.icon}</span>
            </div>
            <div className={`mt-1 text-2xl font-semibold ${c.cls}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* 过滤栏：搜索 + 状态筛选，填满宽度 */}
      <div className="flex flex-wrap items-center gap-3 px-6 py-3">
        <input
          className="min-w-[200px] flex-1 rounded-md border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          placeholder="搜索 IP 地址..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className={inputCls}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      {/* 列表区 */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : records.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">🛡️</div>
            <div className="text-sm">
              {search || statusFilter ? '没有匹配的封禁记录' : '暂无已封禁 IP 记录'}
            </div>
          </div>
        ) : (
          <div className="w-full overflow-x-auto rounded-md border border-gray-800">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-gray-900 text-gray-400">
                <tr>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">IP 地址</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">等级</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">状态</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">来源</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">封禁时长</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">过期时间</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">违规</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">地区</th>
                  <th className="px-3 py-2 text-left font-medium">原因</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r, idx) => {
                  const levelMeta = LEVEL_META[r.ban_level] || {
                    label: r.ban_level,
                    cls: 'bg-gray-700 text-gray-300',
                  }
                  const statusMeta = STATUS_META[r.status] || {
                    label: r.status,
                    cls: 'bg-gray-700 text-gray-300',
                  }
                  return (
                    <tr
                      key={r.id}
                      className={`border-t border-gray-800 ${idx % 2 === 0 ? 'bg-gray-900/30' : ''}`}
                    >
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-brand-300">
                        {r.ip}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${levelMeta.cls}`}
                        >
                          {levelMeta.label}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${statusMeta.cls}`}
                        >
                          {statusMeta.label}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${(SOURCE_META[r.source] || { cls: 'bg-gray-700 text-gray-300' }).cls}`}
                        >
                          {(SOURCE_META[r.source] || { label: r.source || '-' }).label}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-gray-300">
                        {humanizeDuration(r.ban_duration)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-gray-400">
                        {fmtExpiry(r.expired_at)}
                      </td>
                      <td className="px-3 py-2 text-gray-300">{r.violation_count ?? 0}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-gray-400">
                        {r.region || '-'}
                      </td>
                      <td
                        className="max-w-[260px] truncate px-3 py-2 text-gray-400"
                        title={r.reason || ''}
                      >
                        {r.reason || '-'}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <div className="flex gap-1.5">
                          <button
                            type="button"
                            onClick={() => {
                              setDetailRecord(r)
                              setDetailOpen(true)
                            }}
                            className="btn-secondary btn-sm"
                          >
                            详情
                          </button>
                          {canUnban && r.status === 'active' && (
                            <button
                              type="button"
                              onClick={() => handleUnban(r)}
                              disabled={deleting}
                              className="btn-danger btn-sm"
                            >
                              解封
                            </button>
                          )}
                          {canUnban && (
                            <button
                              type="button"
                              onClick={() => handleHardDelete(r)}
                              disabled={unbanning}
                              className="btn-danger btn-sm"
                              title="硬删除：从数据库彻底删除记录（不可恢复）"
                            >
                              删除
                            </button>
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
      </div>

      {/* 详情弹窗 */}
      <DetailModal
        open={detailOpen}
        record={detailRecord}
        onClose={() => {
          setDetailOpen(false)
          setDetailRecord(null)
        }}
        onUnban={handleUnban}
        onHardDelete={handleHardDelete}
        canUnban={canUnban}
        unbanning={unbanning}
        deleting={deleting}
      />

      {/* 导入结果弹窗 */}
      <Modal
        open={!!importResult}
        title="CSV 导入结果"
        onClose={() => setImportResult(null)}
        maxWidth="max-w-md"
        footer={
          <button
            type="button"
            onClick={() => setImportResult(null)}
            className="btn-primary btn-sm"
          >
            确定
          </button>
        }
      >
        {importResult && (
          <div className="flex flex-col gap-3 text-sm">
            <div className="rounded-md border border-success-500/30 bg-success-500/10 p-3 text-success-300">
              ✅ 导入成功 {importResult.imported || 0} 条
            </div>
            {importResult.skipped > 0 && (
              <div className="text-gray-400">⏭️ 跳过已存在 {importResult.skipped} 条</div>
            )}
            {importResult.errors?.length > 0 && (
              <div className="rounded-md border border-warning-500/30 bg-warning-500/10 p-3">
                <div className="mb-1 text-warning-300">⚠️ 错误 {importResult.errors.length} 条：</div>
                <ul className="max-h-32 overflow-y-auto text-xs text-gray-400">
                  {importResult.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* 新增封禁弹窗 */}
      <Modal
        open={createOpen}
        title="手动新增封禁 IP"
        onClose={() => setCreateOpen(false)}
        maxWidth="max-w-lg"
        footer={
          <>
            <button type="button" onClick={() => setCreateOpen(false)} className="btn-secondary">
              取消
            </button>
            <button
              type="button"
              onClick={handleCreate}
              disabled={creating}
              className="btn-primary"
            >
              {creating ? '提交中…' : '确认封禁'}
            </button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {/* IP 地址 + 封禁等级 */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">IP 地址 *</label>
              <input
                className={inputCls}
                placeholder="如 1.2.3.4"
                value={createForm.ip}
                onChange={(e) => setCreateForm({ ...createForm, ip: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">封禁等级</label>
              <select
                className={inputCls}
                value={createForm.ban_level}
                onChange={(e) => setCreateForm({ ...createForm, ban_level: e.target.value })}
              >
                {LEVEL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* 封禁时长 + 归属地区 */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">
                封禁时长（秒，0=永久）
              </label>
              <input
                type="number"
                className={inputCls}
                placeholder="3600"
                value={createForm.ban_duration}
                onChange={(e) => setCreateForm({ ...createForm, ban_duration: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">归属地区</label>
              <input
                className={inputCls}
                placeholder="如 中国 北京"
                value={createForm.region}
                onChange={(e) => setCreateForm({ ...createForm, region: e.target.value })}
              />
            </div>
          </div>

          {/* 封禁原因 */}
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500">封禁原因</label>
            <textarea
              className={`${inputCls} min-h-[72px] resize-y`}
              placeholder="说明封禁原因..."
              value={createForm.reason}
              onChange={(e) => setCreateForm({ ...createForm, reason: e.target.value })}
            />
          </div>

          <div className="rounded-md border border-brand-500/30 bg-brand-500/10 px-3 py-2 text-xs text-brand-300">
            ℹ️ 手动新增的记录将标记为「手动添加」来源，与智能体自动封禁的记录区分。
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default BannedIPs
