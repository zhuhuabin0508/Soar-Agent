// 资产发现：左侧同级来源（综合运管平台 + 1.1~1.4），右侧为当前来源的表与清单
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  CheckCircle2, FileSpreadsheet, Loader2, RefreshCw, Search, Server, Network, Globe, Cpu,
  Upload, X, ShieldOff, Shield, Monitor,
} from 'lucide-react'
import { govCloudApi } from '../api/govcloud'
import { toast } from '../store/toastStore'
import {
  PageContainer, PageHeader, Button, Badge, EmptyState, Pagination, LoadingState,
} from '../components/ui'
import { Modal } from '../components/Dialog'
import { inputCls } from '../components/property/FormControls'
import { hasPermission } from '../utils/permissions'

const TYPE_ICONS = {
  cloud_host: Server,
  bare_metal: Cpu,
  e_government_network: Network,
  elastic_ip: Globe,
}

const SOURCE_ICONS = {
  itsm_ops: Globe,
  intranet_mapping: Network,
  qingteng_host: Server,
  jiaotu_yunsuo: Shield,
  tianqing_endpoint: Monitor,
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

const HIDE_COLS = new Set(['extra_excel', 'batch_id'])

function cellText(v) {
  if (v === '' || v == null) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function sourceTitle(group) {
  if (!group) return ''
  return group.index ? `${group.index} ${group.label}` : group.label
}

function ImportDialog({ open, tableName, sourceName, importing, importPhase, onClose, onConfirm }) {
  const [mode, setMode] = useState('full')
  const [file, setFile] = useState(null)
  const pickRef = useRef(null)

  useEffect(() => {
    if (open) {
      setMode('full')
      setFile(null)
    }
  }, [open])

  if (!open) return null
  return (
    <Modal
      open={open}
      title={`导入「${tableName}」`}
      onClose={importing ? undefined : onClose}
      size="md"
      footer={
        <>
          <Button variant="secondary" size="sm" disabled={importing} onClick={onClose}>取消</Button>
          <Button
            variant="primary"
            size="sm"
            disabled={importing || !file}
            onClick={() => onConfirm(file, mode)}
          >
            {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {importing ? importPhase || '导入中' : (mode === 'full' ? '开始全量导入' : '开始增量导入')}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-xs text-muted-foreground">
        来源：{sourceName}。请先选择插入方式，再选择爬虫产出的 .xlsx。
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <button
          type="button"
          disabled={importing}
          onClick={() => setMode('full')}
          className={`rounded-lg border p-3 text-left ${
            mode === 'full' ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted/50'
          }`}
        >
          <div className="text-sm font-medium text-foreground">全量导入</div>
          <div className="mt-1 text-xs text-muted-foreground">
            按 CMDB ID 新增或更新文件中的记录，并删除本次文件里没有的旧记录，与全量爬取对齐。
          </div>
        </button>
        <button
          type="button"
          disabled={importing}
          onClick={() => setMode('incremental')}
          className={`rounded-lg border p-3 text-left ${
            mode === 'incremental' ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted/50'
          }`}
        >
          <div className="text-sm font-medium text-foreground">增量导入</div>
          <div className="mt-1 text-xs text-muted-foreground">
            只新增或更新文件中的记录，不删除库内已有数据。适合补录、周中追加。
          </div>
        </button>
      </div>
      <div className="mt-4">
        <input
          ref={pickRef}
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <Button variant="secondary" size="sm" disabled={importing} onClick={() => pickRef.current?.click()}>
          <FileSpreadsheet className="h-4 w-4" />
          {file ? file.name : '选择 Excel 文件'}
        </Button>
      </div>
    </Modal>
  )
}

export default function GovCloudAssets() {
  const canView = hasPermission('asset_discovery', 'view')
  const canEdit = hasPermission('asset_discovery', 'edit')
  const [importOpen, setImportOpen] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const [fieldLabels, setFieldLabels] = useState({})
  const [groups, setGroups] = useState([])
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [loading, setLoading] = useState(true)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [cons, setCons] = useState(null)
  const [importing, setImporting] = useState(false)
  const [importPhase, setImportPhase] = useState('')
  const [detail, setDetail] = useState(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [listColumns, setListColumns] = useState([])

  const currentGroup = useMemo(() => {
    const fromUrl = searchParams.get('source')
    if (fromUrl) return groups.find((g) => g.code === fromUrl) || groups[0]
    return groups[0]
  }, [groups, searchParams])

  const tables = currentGroup?.tables || []
  const active = searchParams.get('table') || tables[0]?.code || ''
  const currentTable = tables.find((t) => t.code === active) || tables[0]
  const sourceEnabled = Boolean(currentGroup?.enabled && tables.length)

  const displayColumns = useMemo(() => {
    const ordered = []
    const seen = new Set()
    const fromMeta = listColumns.length ? listColumns : (currentTable?.excel_columns || [])
    fromMeta.forEach((c) => {
      if (!c?.key || HIDE_COLS.has(c.key) || seen.has(c.key)) return
      seen.add(c.key)
      ordered.push({ key: c.key, label: c.label || fieldLabels[c.key] || c.key })
    })
    items.forEach((row) => {
      Object.keys(row || {}).forEach((k) => {
        if (HIDE_COLS.has(k) || seen.has(k)) return
        seen.add(k)
        ordered.push({ key: k, label: fieldLabels[k] || k })
      })
    })
    return ordered
  }, [listColumns, currentTable?.excel_columns, items, fieldLabels])

  useEffect(() => {
    if (!canView) return
    Promise.all([govCloudApi.meta(), govCloudApi.summary()])
      .then(([m, s]) => {
        setFieldLabels(m.field_labels || {})
        setGroups(s.groups?.length ? s.groups : (m.groups || []))
      })
      .catch((e) => toast.error(e.message || '加载元数据失败'))
  }, [canView])

  const load = useCallback(async () => {
    if (!canView || !sourceEnabled || !currentTable?.code) {
      setLoading(false)
      setItems([])
      setTotal(0)
      setCons(null)
      setListColumns([])
      return
    }
    setLoading(true)
    try {
      const type = currentTable.code
      const [list, c, sum] = await Promise.all([
        govCloudApi.list({ resource_type: type, keyword, page, page_size: pageSize }),
        govCloudApi.consistency(type),
        govCloudApi.summary(),
      ])
      setItems(list.items || [])
      setTotal(list.total || 0)
      setListColumns(list.columns || currentTable.excel_columns || [])
      setCons(c)
      if (sum.groups) setGroups(sum.groups)
    } catch (e) {
      toast.error(e.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [canView, sourceEnabled, currentTable?.code, keyword, page, pageSize])

  useEffect(() => { if (canView) load() }, [load, canView])

  function selectSource(code) {
    const next = groups.find((g) => g.code === code)
    const firstTable = next?.tables?.[0]?.code
    const params = { source: code }
    if (firstTable) params.table = firstTable
    setSearchParams(params)
    setPage(1)
    setKeyword('')
  }

  function selectTable(code) {
    const params = { table: code }
    if (currentGroup?.code) params.source = currentGroup.code
    setSearchParams(params)
    setPage(1)
    setKeyword('')
  }

  async function handleImport(file, mode) {
    if (!file || !currentTable?.code) return
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      toast.error('请上传爬虫产出的 .xlsx 文件')
      return
    }
    const tableName = currentTable.excel_name || currentTable.label
    const isFull = mode !== 'incremental'
    setImporting(true)
    setImportPhase('上传中…')
    try {
      const result = await govCloudApi.importExcel(file, currentTable.code, ({ phase, percent }) => {
        if (phase === 'uploading') setImportPhase(`上传中 ${percent || 0}%`)
        if (phase === 'processing') setImportPhase('服务端处理中，请稍候…')
      }, isFull ? 'full' : 'incremental')
      if (isFull) {
        if (result.consistent) {
          toast.success(`${tableName} 全量已对齐：Excel ${result.excel_rows} 行 / 库内 ${result.live_count} 条`)
        } else {
          toast.error(result.note || '全量导入完成但一致性校验未通过')
        }
      } else {
        toast.success(`${tableName} 增量完成：新增 ${result.inserted} / 更新 ${result.updated} / 库内 ${result.live_count} 条`)
      }
      setImportOpen(false)
      setPage(1)
      await load()
    } catch (e) {
      toast.error(e.message || '导入失败')
    } finally {
      setImporting(false)
      setImportPhase('')
    }
  }

  async function openDetail(id) {
    try {
      const rec = await govCloudApi.get(currentTable.code, id)
      setDetail(rec)
      setDetailOpen(true)
    } catch (e) {
      toast.error(e.message || '加载详情失败')
    }
  }

  if (!canView) {
    return (
      <PageContainer>
        <PageHeader title="资产发现" description="按发现来源归类展示资产。" />
        <EmptyState
          icon={ShieldOff}
          title="没有访问权限"
          description="请联系管理员在「角色管理」中授予「资产发现」查看权限。"
        />
      </PageContainer>
    )
  }

  return (
    <PageContainer className="flex min-h-0 flex-col">
      <PageHeader
        title="资产发现"
        description="发现来源同级展示。当前已接入综合运管平台；1.1～1.4 后续接入。"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={load} disabled={loading || importing || !sourceEnabled}>
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </Button>
            {canEdit && sourceEnabled && (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={importing || !currentTable}
                  onClick={() => setImportOpen(true)}
                >
                  {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                  {importing ? importPhase || '导入中' : `导入${currentTable?.excel_name || ' Excel'}`}
                </Button>
            )}
          </div>
        }
      />

      <div className="flex min-h-0 flex-1 gap-4">
        <aside className="w-[240px] shrink-0">
          <div className="mb-2 px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            发现来源
          </div>
          <div className="space-y-1">
            {groups.map((g) => {
                  const Icon = SOURCE_ICONS[g.code] || Globe
              const on = g.code === currentGroup?.code
              const count = (g.tables || []).reduce((n, t) => n + (t.total || 0), 0)
              return (
                <button
                  key={g.code}
                  type="button"
                  onClick={() => selectSource(g.code)}
                  className={`flex w-full items-start gap-2 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                    on
                      ? 'border-primary bg-primary/10'
                      : 'border-transparent hover:bg-muted/60'
                  }`}
                >
                  <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${on ? 'text-primary' : 'text-muted-foreground'}`} />
                  <span className="min-w-0 flex-1">
                    <span className={`block text-sm font-medium leading-snug ${on ? 'text-primary' : 'text-foreground'}`}>
                      {sourceTitle(g)}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-muted-foreground">
                      {g.enabled ? `${count} 条` : '即将接入'}
                    </span>
                  </span>
                  {!g.enabled && (
                    <Badge variant="neutral" className="shrink-0">待接入</Badge>
                  )}
                </button>
              )
            })}
          </div>
        </aside>

        <section className="min-w-0 flex-1">
          <div className="mb-3">
            <h2 className="text-base font-semibold text-foreground">{sourceTitle(currentGroup)}</h2>
            {currentGroup?.description && (
              <p className="mt-0.5 text-xs text-muted-foreground">{currentGroup.description}</p>
            )}
          </div>

          {!sourceEnabled ? (
            <EmptyState
              icon={SOURCE_ICONS[currentGroup?.code] || Globe}
              title={`${sourceTitle(currentGroup) || '该来源'}尚未接入`}
              description="与综合运管平台资产发现同级，数据接入后将在此展示清单与导入。"
              bordered
            />
          ) : (
            <>
              <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {tables.map((t) => {
                  const Icon = TYPE_ICONS[t.code] || FileSpreadsheet
                  const on = t.code === currentTable?.code
                  return (
                    <button
                      key={t.code}
                      type="button"
                      onClick={() => selectTable(t.code)}
                      className={`rounded-lg border p-3 text-left transition-colors ${
                        on ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted/60'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2">
                          <FileSpreadsheet className={`h-4 w-4 shrink-0 ${on ? 'text-primary' : 'text-emerald-500'}`} />
                          <span className={`truncate text-sm font-medium ${on ? 'text-primary' : 'text-foreground'}`}>
                            {t.excel_name || t.label}
                          </span>
                        </div>
                        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      </div>
                      <div className="mt-2 flex items-center justify-between gap-2">
                        <span className="text-lg font-semibold tabular-nums">{t.total ?? 0}</span>
                        <Badge variant={t.consistent ? 'success' : 'danger'}>
                          {t.consistent ? '已对齐' : '未对齐'}
                        </Badge>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">.xlsx · 全量爬取</div>
                    </button>
                  )
                })}
              </div>

              {cons && (
                <div className={`mb-4 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${
                  cons.consistent
                    ? 'border-success/30 bg-success/10 text-foreground'
                    : 'border-destructive/30 bg-destructive/10 text-foreground'
                }`}>
                  {cons.consistent
                    ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                    : <X className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
                  <div>
                    <div className="font-medium">
                      {currentTable?.excel_name || currentTable?.label}：{cons.message}
                    </div>
                    {cons.last_batch && (
                      <div className="mt-1 text-xs text-muted-foreground">
                        最近导入 {cons.last_batch.filename} · Excel {cons.excel_rows} 行 ·
                        唯一 ID {cons.unique_source_ids} · 库内 {cons.live_count} ·
                        {fmtTime(cons.last_batch.created_at)}
                        {cons.last_batch.note ? ` · ${cons.last_batch.note}` : ''}
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="mb-3 flex items-center gap-2">
                <div className="relative max-w-md flex-1">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    className={`${inputCls} pl-8`}
                    placeholder={`搜索「${currentTable?.excel_name || '当前表'}」名称 / IP / 部门 / CMDB ID`}
                    value={keyword}
                    onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
                  />
                </div>
              </div>

              {loading ? (
                <LoadingState />
              ) : items.length === 0 ? (
                <EmptyState
                  icon={FileSpreadsheet}
                  title={`${currentTable?.excel_name || '当前表'}暂无数据`}
                  description={canEdit ? '请导入对应全量爬取 Excel（Sheet「原始数据」）' : '等待管理员导入全量爬取结果'}
                  bordered
                />
              ) : (
                <div className="max-h-[62vh] overflow-auto rounded-lg border border-border">
                  <table className="w-max min-w-full text-left text-sm">
                    <thead className="sticky top-0 z-10 bg-muted text-xs text-muted-foreground">
                      <tr>
                        {displayColumns.map((col) => (
                          <th key={col.key} className="whitespace-nowrap px-3 py-2 font-medium">
                            {col.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((row) => (
                        <tr
                          key={row.id}
                          className="cursor-pointer border-t border-border hover:bg-muted/40"
                          onClick={() => openDetail(row.id)}
                        >
                          {displayColumns.map((col) => (
                            <td
                              key={col.key}
                              className="max-w-[280px] truncate whitespace-nowrap px-3 py-2"
                              title={cellText(row[col.key])}
                            >
                              {cellText(row[col.key])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {total > pageSize && (
                <div className="mt-4">
                  <Pagination page={page} pageSize={pageSize} total={total} onPageChange={setPage} showPageSize={false} />
                </div>
              )}
            </>
          )}
        </section>
      </div>

      <ImportDialog
        open={importOpen}
        tableName={currentTable?.excel_name || currentTable?.label || '当前表'}
        sourceName={sourceTitle(currentGroup)}
        importing={importing}
        importPhase={importPhase}
        onClose={() => { if (!importing) setImportOpen(false) }}
        onConfirm={handleImport}
      />
      <Modal
        open={detailOpen}
        title={detail?.instance_name || detail?.inst_name || detail?.name || '资产详情'}
        onClose={() => setDetailOpen(false)}
        size="lg"
      >
        {detail && (
          <dl className="grid max-h-[70vh] grid-cols-1 gap-x-6 gap-y-3 overflow-auto sm:grid-cols-2">
            {Object.entries(detail)
              .filter(([k]) => !HIDE_COLS.has(k))
              .map(([k, v]) => (
              <div key={k} className="min-w-0">
                <dt className="text-xs text-muted-foreground">{fieldLabels[k] || k}</dt>
                <dd className="break-all text-sm text-foreground">{cellText(v)}</dd>
              </div>
            ))}
          </dl>
        )}
      </Modal>
    </PageContainer>
  )
}
