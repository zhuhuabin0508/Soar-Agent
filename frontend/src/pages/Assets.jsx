import { useEffect, useState, useCallback } from 'react'
import { assetsApi } from '../api/assets'
import { agents } from '../api/client'
import { useAuthStore } from '../store/authStore'
import { Modal } from '../components/Dialog'
import { inputCls } from '../components/property/FormControls'

// 重要性配色
const CRITICALITY_META = {
  low: { label: '低', cls: 'bg-brand-500/15 text-brand-300' },
  medium: { label: '中', cls: 'bg-yellow-500/15 text-yellow-300' },
  high: { label: '高', cls: 'bg-orange-500/15 text-orange-300' },
  critical: { label: '严重', cls: 'bg-danger-500/20 text-danger-300' },
}

// 来源标识配色
const SOURCE_META = {
  kb_ingest: { label: 'KB梳理', cls: 'bg-brand-500/15 text-brand-300' },
  agent_add: { label: '对话录入', cls: 'bg-purple-500/15 text-purple-300' },
  manual: { label: '手动添加', cls: 'bg-gray-700 text-gray-300' },
}

const CRITICALITY_OPTIONS = [
  { value: '', label: '全部重要性' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'critical', label: '严重' },
]

const SOURCE_OPTIONS = [
  { value: '', label: '全部来源' },
  { value: 'kb_ingest', label: 'KB梳理' },
  { value: 'agent_add', label: '对话录入' },
  { value: 'manual', label: '手动添加' },
]

function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// ============ 详情弹窗 ============
function DetailModal({ open, record, onClose, onEdit, onDelete, canManage, canDelete }) {
  if (!record) return null
  const critMeta = CRITICALITY_META[record.criticality] || {
    label: record.criticality, cls: 'bg-gray-700 text-gray-300',
  }
  const srcMeta = SOURCE_META[record.source] || {
    label: record.source || '-', cls: 'bg-gray-700 text-gray-300',
  }

  const fields = [
    { label: '唯一标识', value: record.identifier, mono: true },
    { label: '标识类型', value: record.identifier_type || '-' },
    { label: '资产名称', value: record.name || '-' },
    { label: '资产类型', value: record.asset_type || '-' },
    { label: '重要性', value: critMeta.label, badge: critMeta.cls },
    { label: '来源', value: srcMeta.label, badge: srcMeta.cls },
    { label: '归属部门', value: record.department || '-' },
    { label: '负责人', value: record.owner || '-' },
    { label: '物理位置', value: record.location || '-' },
    { label: 'IP 地址', value: record.ip || '-', mono: true },
    { label: '来源知识库', value: record.kb_name || (record.kb_id ? `知识库-${record.kb_id}` : '-') },
    { label: '创建时间', value: fmtTime(record.created_at) },
    { label: '更新时间', value: fmtTime(record.updated_at) },
  ]

  return (
    <Modal
      open={open}
      title={`资产详情：${record.name || record.identifier || ''}`}
      onClose={onClose}
      maxWidth="max-w-2xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">关闭</button>
          {canManage && (
            <button type="button" onClick={() => onEdit(record)} className="btn-primary btn-sm">
              编辑
            </button>
          )}
          {canDelete && (
            <button type="button" onClick={() => onDelete(record)} className="btn-danger btn-sm">
              删除
            </button>
          )}
        </>
      }
    >
      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        {fields.map((f) => (
          <div key={f.label} className="flex flex-col">
            <span className="text-xs text-gray-500">{f.label}</span>
            {f.badge ? (
              <span className={`mt-0.5 inline-flex w-fit rounded px-2 py-0.5 text-xs font-medium ${f.badge}`}>
                {f.value}
              </span>
            ) : (
              <span className={`mt-0.5 text-sm text-gray-200 ${f.mono ? 'font-mono' : ''}`}>
                {f.value}
              </span>
            )}
          </div>
        ))}
      </div>
      {record.extra_fields && Object.keys(record.extra_fields).length > 0 && (
        <div className="mt-4 border-t border-gray-800 pt-3">
          <div className="mb-2 text-xs text-gray-500">灵活字段（extra_fields）</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(record.extra_fields).map(([k, v]) => (
              <span
                key={k}
                className="inline-flex items-center gap-1 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs"
              >
                <span className="text-gray-500">{k}:</span>
                <span className="text-gray-200">{String(v)}</span>
              </span>
            ))}
          </div>
        </div>
      )}
      {record.raw_content && (
        <div className="mt-4 border-t border-gray-800 pt-3">
          <div className="mb-1 text-xs text-gray-500">原始 KB 片段（溯源）</div>
          <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-400 whitespace-pre-wrap">
            {record.raw_content}
          </pre>
        </div>
      )}
    </Modal>
  )
}

// ============ 新增/编辑弹窗 ============
function AssetFormModal({ open, form, setForm, agentsList, onSubmit, onClose, submitting, isEdit }) {
  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }))

  return (
    <Modal
      open={open}
      title={isEdit ? '编辑资产' : '手动新增资产'}
      onClose={onClose}
      maxWidth="max-w-2xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">取消</button>
          <button type="button" onClick={onSubmit} disabled={submitting} className="btn-primary">
            {submitting ? '保存中...' : '保存'}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">归属智能体 *</label>
          <select
            className={inputCls}
            value={form.agent_id || ''}
            onChange={(e) => set('agent_id', Number(e.target.value))}
            disabled={isEdit}
          >
            <option value="">选择智能体...</option>
            {agentsList.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">唯一标识 *</label>
          <input
            className={inputCls}
            value={form.identifier || ''}
            onChange={(e) => set('identifier', e.target.value)}
            placeholder="IP/主机名/工号/资产编号"
            disabled={isEdit}
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">标识类型</label>
          <select className={inputCls} value={form.identifier_type || 'custom'}
            onChange={(e) => set('identifier_type', e.target.value)}>
            <option value="ip">IP</option>
            <option value="hostname">主机名</option>
            <option value="asset_name">资产名</option>
            <option value="employee_id">工号</option>
            <option value="mac">MAC</option>
            <option value="custom">自定义</option>
          </select>
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">资产名称</label>
          <input className={inputCls} value={form.name || ''}
            onChange={(e) => set('name', e.target.value)} placeholder="展示用名称" />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">资产类型</label>
          <input className={inputCls} value={form.asset_type || ''}
            onChange={(e) => set('asset_type', e.target.value)} placeholder="服务器/工作站/网络设备..." />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">重要性</label>
          <select className={inputCls} value={form.criticality || 'medium'}
            onChange={(e) => set('criticality', e.target.value)}>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="critical">严重</option>
          </select>
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">归属部门</label>
          <input className={inputCls} value={form.department || ''}
            onChange={(e) => set('department', e.target.value)} />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">负责人</label>
          <input className={inputCls} value={form.owner || ''}
            onChange={(e) => set('owner', e.target.value)} />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">物理位置</label>
          <input className={inputCls} value={form.location || ''}
            onChange={(e) => set('location', e.target.value)} />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs text-gray-500">IP 地址</label>
          <input className={inputCls} value={form.ip || ''}
            onChange={(e) => set('ip', e.target.value)} />
        </div>
        <div className="col-span-2 flex flex-col">
          <label className="mb-1 text-xs text-gray-500">灵活字段（JSON，可选）</label>
          <textarea
            className={`${inputCls} h-20 font-mono`}
            value={form.extra_fields_text || ''}
            onChange={(e) => set('extra_fields_text', e.target.value)}
            placeholder='{"序列号": "SN001", "购入日期": "2024-01-01"}'
          />
        </div>
      </div>
    </Modal>
  )
}

// ============ 主页面 ============
function Assets() {
  const user = useAuthStore((s) => s.user)
  const canManage = user?.role === 'admin' || user?.role === 'analyst'
  const canDelete = user?.role === 'admin'

  const [records, setRecords] = useState([])
  const [stats, setStats] = useState({ total: 0, by_source: {}, by_criticality: {}, by_type: {} })
  const [agentsList, setAgentsList] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 分页
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)

  // 过滤条件
  const [keyword, setKeyword] = useState('')
  const [agentFilter, setAgentFilter] = useState('')
  const [criticalityFilter, setCriticalityFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')

  // 详情弹窗
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRecord, setDetailRecord] = useState(null)

  // 新增/编辑弹窗
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState({})
  const [isEdit, setIsEdit] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // 扫描
  const [scanning, setScanning] = useState(false)
  const [exporting, setExporting] = useState(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const params = {
        page,
        page_size: pageSize,
        keyword,
        criticality: criticalityFilter,
        source: sourceFilter,
      }
      if (agentFilter) params.agent_id = agentFilter
      const [listData, st] = await Promise.all([
        assetsApi.list(params),
        assetsApi.stats(agentFilter || undefined),
      ])
      setRecords(listData?.items || [])
      setTotal(listData?.total || 0)
      setTotalPages(listData?.pages || 0)
      setStats(st || { total: 0, by_source: {}, by_criticality: {}, by_type: {} })
      setError('')
    } catch (err) {
      setError(err.message || '加载资产失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, agentFilter, criticalityFilter, sourceFilter])

  // 加载智能体列表（用于筛选和表单下拉）
  useEffect(() => {
    agents.list().then((data) => {
      setAgentsList(Array.isArray(data) ? data : [])
    }).catch(() => {})
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  // 过滤条件变化时回到第一页
  useEffect(() => {
    setPage(1)
  }, [keyword, agentFilter, criticalityFilter, sourceFilter])

  const handleDetail = (record) => {
    setDetailRecord(record)
    setDetailOpen(true)
  }

  const handleCreate = () => {
    setIsEdit(false)
    setForm({
      agent_id: agentFilter ? Number(agentFilter) : '',
      identifier: '',
      identifier_type: 'custom',
      name: '',
      asset_type: '',
      department: '',
      owner: '',
      location: '',
      ip: '',
      criticality: 'medium',
      extra_fields_text: '',
    })
    setFormOpen(true)
  }

  const handleEdit = (record) => {
    setDetailOpen(false)
    setIsEdit(true)
    setForm({
      id: record.id,
      agent_id: record.agent_id,
      identifier: record.identifier,
      identifier_type: record.identifier_type || 'custom',
      name: record.name || '',
      asset_type: record.asset_type || '',
      department: record.department || '',
      owner: record.owner || '',
      location: record.location || '',
      ip: record.ip || '',
      criticality: record.criticality || 'medium',
      extra_fields_text: record.extra_fields
        ? JSON.stringify(record.extra_fields, null, 2)
        : '',
    })
    setFormOpen(true)
  }

  const handleSubmit = async () => {
    if (!form.agent_id) {
      window.alert('请选择归属智能体')
      return
    }
    if (!form.identifier?.trim()) {
      window.alert('请填写唯一标识')
      return
    }
    let extraFields = null
    if (form.extra_fields_text?.trim()) {
      try {
        extraFields = JSON.parse(form.extra_fields_text)
      } catch {
        window.alert('灵活字段不是有效的 JSON 格式')
        return
      }
    }
    setSubmitting(true)
    try {
      const body = {
        identifier: form.identifier.trim(),
        identifier_type: form.identifier_type,
        name: form.name?.trim() || '',
        asset_type: form.asset_type?.trim() || '',
        department: form.department?.trim() || '',
        owner: form.owner?.trim() || '',
        location: form.location?.trim() || '',
        ip: form.ip?.trim() || '',
        criticality: form.criticality,
        extra_fields: extraFields,
      }
      if (isEdit) {
        await assetsApi.update(form.id, body)
      } else {
        body.agent_id = form.agent_id
        await assetsApi.create(body)
      }
      setFormOpen(false)
      await loadAll()
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (record) => {
    if (!record) return
    if (!window.confirm(`确定删除资产「${record.name || record.identifier}」吗？此操作不可恢复。`))
      return
    try {
      await assetsApi.remove(record.id)
      setDetailOpen(false)
      await loadAll()
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  const handleScan = async () => {
    setScanning(true)
    try {
      const result = await assetsApi.scan()
      window.alert(`扫描任务已提交（任务ID: ${result.task_id}）\n将在后台异步扫描所有资产管理智能体的新知识库。`)
    } catch (err) {
      window.alert(`触发扫描失败：${err.message || err}`)
    } finally {
      setScanning(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      await assetsApi.exportCsv(agentFilter || undefined)
    } catch (err) {
      window.alert(`导出失败：${err.message || err}`)
    } finally {
      setExporting(false)
    }
  }

  // 统计卡片
  const statCards = [
    { key: 'total', label: '资产总数', value: stats.total || 0, icon: '📋', cls: 'text-brand-300' },
    { key: 'kb_ingest', label: 'KB梳理', value: (stats.by_source || {}).kb_ingest || 0, icon: '📚', cls: 'text-brand-300' },
    { key: 'agent_add', label: '对话录入', value: (stats.by_source || {}).agent_add || 0, icon: '🤖', cls: 'text-purple-300' },
    { key: 'critical', label: '严重资产', value: (stats.by_criticality || {}).critical || 0, icon: '🔴', cls: 'text-danger-300' },
  ]

  return (
    <div className="flex h-full flex-col">
      {/* 页头 */}
      <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-100">资产管理</h1>
          <span className="text-xs text-gray-500">
            共 {total} 条 / 第 {page}/{totalPages || 1} 页
          </span>
        </div>
        <div className="flex items-center gap-2">
          {canManage && (
            <button type="button" onClick={handleScan} disabled={scanning} className="btn-secondary btn-sm">
              {scanning ? '提交中...' : '🔍 扫描新KB'}
            </button>
          )}
          {canManage && (
            <button type="button" onClick={handleCreate} className="btn-primary btn-sm">
              + 新增资产
            </button>
          )}
          <button type="button" onClick={handleExport} disabled={exporting} className="btn-secondary btn-sm">
            {exporting ? '导出中...' : '导出 CSV'}
          </button>
          <button type="button" onClick={loadAll} className="btn-secondary btn-sm">
            刷新
          </button>
        </div>
      </header>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-3 px-6 pt-4 md:grid-cols-4">
        {statCards.map((c) => (
          <div key={c.key} className="w-full rounded-lg border border-gray-800 bg-gray-900/40 px-4 py-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">{c.label}</span>
              <span className="text-base">{c.icon}</span>
            </div>
            <div className={`mt-1 text-2xl font-semibold ${c.cls}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* 过滤栏 */}
      <div className="flex flex-wrap items-center gap-3 px-6 py-3">
        <input
          className="min-w-[200px] flex-1 rounded-md border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          placeholder="搜索标识/名称/IP/负责人..."
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <select className={inputCls} value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}>
          <option value="">全部智能体</option>
          {agentsList.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <select className={inputCls} value={criticalityFilter}
          onChange={(e) => setCriticalityFilter(e.target.value)}>
          {CRITICALITY_OPTIONS.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
        <select className={inputCls} value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}>
          {SOURCE_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
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
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">加载中...</div>
        ) : records.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">📋</div>
            <div className="text-sm">
              {keyword || agentFilter || criticalityFilter || sourceFilter
                ? '没有匹配的资产记录' : '暂无资产记录，可点击「扫描新KB」或「新增资产」'}
            </div>
          </div>
        ) : (
          <div className="w-full overflow-x-auto rounded-md border border-gray-800">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-gray-900 text-gray-400">
                <tr>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">标识</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">名称</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">类型</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">部门</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">负责人</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">IP</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">重要性</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">来源</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => {
                  const critMeta = CRITICALITY_META[r.criticality] || { label: r.criticality, cls: 'bg-gray-700 text-gray-300' }
                  const srcMeta = SOURCE_META[r.source] || { label: r.source || '-', cls: 'bg-gray-700 text-gray-300' }
                  return (
                    <tr key={r.id} className="border-t border-gray-800 hover:bg-gray-900/50">
                      <td className="px-3 py-2 font-mono text-gray-200">{r.identifier}</td>
                      <td className="px-3 py-2 text-gray-200">{r.name || '-'}</td>
                      <td className="px-3 py-2 text-gray-400">{r.asset_type || '-'}</td>
                      <td className="px-3 py-2 text-gray-400">{r.department || '-'}</td>
                      <td className="px-3 py-2 text-gray-400">{r.owner || '-'}</td>
                      <td className="px-3 py-2 font-mono text-gray-400">{r.ip || '-'}</td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${critMeta.cls}`}>
                          {critMeta.label}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${srcMeta.cls}`}>
                          {srcMeta.label}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <button type="button" onClick={() => handleDetail(r)}
                          className="text-xs text-brand-400 hover:underline">
                          详情
                        </button>
                        {canManage && (
                          <button type="button" onClick={() => handleEdit(r)}
                            className="ml-2 text-xs text-gray-400 hover:underline">
                            编辑
                          </button>
                        )}
                        {canDelete && (
                          <button type="button" onClick={() => handleDelete(r)}
                            className="ml-2 text-xs text-danger-400 hover:underline">
                            删除
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-center gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="btn-secondary btn-sm"
            >
              上一页
            </button>
            <span className="text-sm text-gray-400">
              {page} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="btn-secondary btn-sm"
            >
              下一页
            </button>
          </div>
        )}
      </div>

      {/* 详情弹窗 */}
      <DetailModal
        open={detailOpen}
        record={detailRecord}
        onClose={() => setDetailOpen(false)}
        onEdit={handleEdit}
        onDelete={handleDelete}
        canManage={canManage}
        canDelete={canDelete}
      />

      {/* 新增/编辑弹窗 */}
      <AssetFormModal
        open={formOpen}
        form={form}
        setForm={setForm}
        agentsList={agentsList}
        onSubmit={handleSubmit}
        onClose={() => setFormOpen(false)}
        submitting={submitting}
        isEdit={isEdit}
      />
    </div>
  )
}

export default Assets
