// 数据源条目页：三层信息架构第二层（来源 IP 接入实例）
// 列表首列：来源 IP 或自定义名称；列含设备类型/绑定模板/所属接收器/今日接收与解析成功/三态状态/最近活跃。
// 点击行进入详情页（基本信息 / 解析模板 / 日志预览三 Tab）。支持 ?receiver= 按接收器筛选（接收器页跳转）。
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronRight, Inbox, ListTree, RefreshCw, Search } from 'lucide-react'
import { toast } from '../../store/toastStore'
import { inputCls } from '../../components/property/FormControls'
import { Drawer, Modal } from '../../components/Dialog'
import { devices as devicesApi } from '../../api/client'
import { Button, PageContainer, PageHeader, DataTable, Pagination, Badge, EmptyState } from '../../components/ui'
import {
  SOURCE_TYPE_META, PROTOCOL_TAG_CLS, ENTRY_STATUS_META, DEVICE_TYPE_LABELS,
} from './receiverMeta'

const PAGE_SIZE = 20
const fmtCount = (n) => (n ?? 0).toLocaleString()
const fmtTime = (t) => (t ? new Date(t).toLocaleString() : '—')

// 状态色图例圆点（规范：已接入=绿 / 待配置=橙 / 解析异常=红 / 已停用=灰）
const ENTRY_DOT_CLS = {
  pending: 'bg-warning',
  active: 'bg-success',
  parse_error: 'bg-destructive',
  disabled: 'bg-muted-foreground',
}

// 绑定模板来源徽标
const BOUND_SOURCE_LABELS = {
  entry: { label: '条目', cls: 'bg-primary/15 text-primary', title: '条目级固定模板（优先级最高）' },
  receiver: { label: '接收器', cls: 'bg-secondary text-muted-foreground', title: '跟随所属接收器的默认模板' },
  auto: { label: '自动', cls: 'bg-cyan-500/15 text-cyan-400', title: '由系统按元数据/特征自动匹配模板' },
}

export default function SourceEntryList() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [receivers, setReceivers] = useState([])
  const [items, setItems] = useState([])
  const [statusCounts, setStatusCounts] = useState({ pending: 0, active: 0, parse_error: 0, disabled: 0 })
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  // 筛选：接收器（URL ?receiver= 预置）、状态、搜索
  const [receiverId, setReceiverId] = useState(() => searchParams.get('receiver') || '')
  const [status, setStatus] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await devicesApi.logReceivers.entriesGlobal({
        page, page_size: PAGE_SIZE,
        receiver_id: receiverId || undefined,
        status: status || undefined,
        search: search || undefined,
      })
      setItems(res?.items || [])
      setTotal(res?.total || 0)
      setStatusCounts(res?.status_counts || statusCounts)
    } catch (err) {
      toast.error(err.message || '加载数据源条目失败')
    } finally {
      setLoading(false)
    }
  }, [page, receiverId, status, search]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load() }, [load])

  // 接收器下拉（筛选用）
  useEffect(() => {
    devicesApi.logReceivers.list()
      .then((res) => setReceivers(Array.isArray(res) ? res : res?.items || []))
      .catch(() => {})
  }, [])

  // 搜索防抖
  useEffect(() => {
    const t = setTimeout(() => { setPage(1); setSearch(searchInput.trim()) }, 300)
    return () => clearTimeout(t)
  }, [searchInput])

  const applyFilter = (setter) => (v) => { setter(v); setPage(1) }

  // 失败样本原文查看
  const [sampleView, setSampleView] = useState(null)

  // 失败样本下钻抽屉（今日接收/解析成功列点击：原因四分类 + 按原因筛选）
  const [drill, setDrill] = useState(null) // { entryId, name }
  const [drillData, setDrillData] = useState(null)
  const [drillReason, setDrillReason] = useState('')
  const [drillPage, setDrillPage] = useState(1)
  const [drillLoading, setDrillLoading] = useState(false)

  // 失败样本下钻：该来源条目起失败明细 + 原因分类统计（分页，可按原因筛选）
  const loadDrill = useCallback((entryId, reason, page) => {
    setDrillLoading(true)
    devicesApi.logReceivers.entryFailureSamples(entryId, { reason, page, page_size: 15 })
      .then((res) => { setDrillData(res); setDrillPage(page) })
      .catch((e) => toast.error(e.message || '失败样本加载失败'))
      .finally(() => setDrillLoading(false))
  }, [])

  const openDrill = (row) => {
    setDrill({ entryId: row.id, name: row.name !== row.source_ip ? row.name : row.source_ip })
    setDrillReason('')
    setDrillData(null)
    loadDrill(row.id, '', 1)
  }

  const applyDrillReason = (reason) => {
    const next = reason === drillReason ? '' : reason
    setDrillReason(next)
    if (drill) loadDrill(drill.entryId, next, 1)
  }

  const cards = [
    { key: 'all', label: '条目总数', value: total, cls: '', icon: ListTree, tip: '全部数据源条目（含停用）' },
    { key: 'active', label: '已接入', value: statusCounts.active ?? 0, cls: 'text-success', icon: Inbox, tip: '今日解析无失败且已完成配置的条目数' },
    { key: 'pending', label: '待配置', value: statusCounts.pending ?? 0, cls: 'text-warning', icon: Search, tip: '自动发现后尚未绑定设备/模板的条目数' },
    { key: 'parse_error', label: '解析异常', value: statusCounts.parse_error ?? 0, cls: statusCounts.parse_error ? 'text-destructive' : 'text-muted-foreground', icon: RefreshCw, tip: '今日解析失败数（fail/unknown）> 0 的条目数，即使另有成功也计入' },
  ]

  const columns = [
    {
      key: 'name', header: '来源 IP / 名称', width: '210px',
      render: (r) => (
        <div className="min-w-0">
          <div className="truncate font-mono text-xs font-semibold">
            {r.name !== r.source_ip ? r.name : r.source_ip}
          </div>
          <div className="truncate text-[11px] text-muted-foreground/70" title={r.source_ip}>
            {r.name !== r.source_ip ? r.source_ip : (r.auto_created ? '自动发现' : '手工创建')}
          </div>
        </div>
      ),
    },
    {
      key: 'device_type', header: '设备类型', width: '110px',
      render: (r) => (r.device_type
        ? <span className="text-xs">{DEVICE_TYPE_LABELS[r.device_type] || r.device_type}</span>
        : <span className="text-xs text-muted-foreground/40" title="未绑定设备">--</span>),
    },
    {
      key: 'strategy', header: '绑定模板', width: '180px',
      render: (r) => {
        const src = BOUND_SOURCE_LABELS[r.bound_strategy_source] || BOUND_SOURCE_LABELS.auto
        return (
          <div className="flex min-w-0 items-center gap-1.5">
            {r.bound_strategy_name ? (
              <>
                <span className="truncate text-xs" title={`${src.title} · ${r.bound_strategy_name}`}>{r.bound_strategy_name}</span>
                <span className={`shrink-0 rounded px-1 py-0.5 text-[10px] font-medium ${src.cls}`} title={src.title}>{src.label}</span>
              </>
            ) : (
              <span className="rounded px-1 py-0.5 text-[10px] font-medium text-cyan-400" title="由系统按元数据/特征自动匹配模板">自动匹配</span>
            )}
          </div>
        )
      },
    },
    {
      key: 'receiver', header: '所属接收器', width: '170px',
      render: (r) => (
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-xs" title={r.receiver_name}>{r.receiver_name}</span>
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${PROTOCOL_TAG_CLS[r.receiver_protocol] || 'bg-secondary text-muted-foreground'}`}>
            {SOURCE_TYPE_META[r.receiver_protocol]?.label || r.receiver_protocol}
          </span>
        </div>
      ),
    },
    {
      key: 'today', header: '今日接收 / 解析成功', width: '150px', numeric: true,
      render: (r) => (
        <button
          type="button"
          disabled={!r.today_received}
          onClick={(e) => { e.stopPropagation(); openDrill(r) }}
          title={r.today_received
            ? '点击查看该条目的失败样本与原因分类'
            : '今日暂无接收，无失败样本'}
          className={`rounded px-1 py-0.5 -mx-1 tabular-nums transition ${
            r.today_received
              ? 'cursor-pointer hover:bg-primary/10 hover:text-primary'
              : 'cursor-default'}`}
        >
          <span className={r.today_received ? '' : 'text-muted-foreground/50'}>{fmtCount(r.today_received)}</span>
          <span className="mx-1 text-muted-foreground/40">/</span>
          <span className={r.today_received && !r.today_parsed ? 'text-destructive' : r.today_parsed ? '' : 'text-muted-foreground/50'}>
            {fmtCount(r.today_parsed)}
          </span>
        </button>
      ),
    },
    {
      key: 'status', header: '状态', width: '100px',
      render: (r) => {
        const st = ENTRY_STATUS_META[r.status] || { label: r.status, cls: 'bg-secondary text-muted-foreground' }
        return <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${st.cls}`} title={st.desc}>{st.label}</span>
      },
    },
    {
      key: 'last_received_at', header: '最近活跃', width: '150px',
      render: (r) => <span className="text-xs text-muted-foreground">{fmtTime(r.last_received_at)}</span>,
    },
    {
      key: 'go', header: '', width: '50px',
      render: () => <ChevronRight className="h-4 w-4 text-muted-foreground/50" />,
    },
  ]

  return (
    <PageContainer>
      <PageHeader
        title="数据源条目"
        description="接收器按来源 IP 自动发现的接入实例：点击条目配置归属设备、解析模板与流水线覆盖，查看原始日志与解析结果对照"
        actions={(
          <Button variant="secondary" onClick={load} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> 刷新
          </Button>
        )}
      />

      {/* 状态统计卡片（可点击筛选） */}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {cards.map((c) => (
          <div
            key={c.key}
            role="button"
            tabIndex={0}
            title={`${c.tip}（点击按此状态筛选）`}
            onClick={() => applyFilter(setStatus)(c.key === 'all' ? '' : c.key)}
            className={`card cursor-pointer px-5 py-4 transition hover:border-primary/40 hover:shadow-md ${status === (c.key === 'all' ? '' : c.key) ? 'border-primary/40 ring-1 ring-primary/20' : ''}`}
          >
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <c.icon className="h-3.5 w-3.5" />
              {c.label}
            </div>
            <div className={`mt-1 text-2xl font-semibold tabular-nums ${c.cls}`}>{fmtCount(c.value)}</div>
          </div>
        ))}
      </div>

      {/* 筛选栏 + 列表 */}
      <div className="card">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3">
          <input
            className={`${inputCls} max-w-xs`}
            placeholder="搜索来源 IP / 名称"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <select className={`${inputCls} w-auto`} value={receiverId} onChange={(e) => applyFilter(setReceiverId)(e.target.value)}>
            <option value="">全部接收器</option>
            {receivers.map((r) => (<option key={r.id} value={r.id}>{r.name}</option>))}
          </select>
          <select className={`${inputCls} w-auto`} value={status} onChange={(e) => applyFilter(setStatus)(e.target.value)}>
            <option value="">全部状态</option>
            {Object.entries(ENTRY_STATUS_META).map(([v, m]) => (<option key={v} value={v}>{m.label}</option>))}
          </select>
          <div className="ml-auto flex items-center gap-3">
            {/* 状态色图例（与状态徽标同色系） */}
            {Object.entries(ENTRY_STATUS_META).map(([v, m]) => (
              <span key={v} className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" title={m.desc}>
                <span className={`h-2 w-2 shrink-0 rounded-full ${ENTRY_DOT_CLS[v] || 'bg-muted-foreground'}`} />
                {m.label}
              </span>
            ))}
            <span className="border-l border-border pl-3 text-xs text-muted-foreground">点击行进入条目详情</span>
          </div>
        </div>
        <DataTable
          columns={columns}
          data={items}
          loading={loading}
          rowKey="id"
          onRowClick={(r) => navigate(`/source-entries/${r.id}`)}
          emptyIcon={ListTree}
          emptyText="暂无数据源条目"
          emptyDescription={receiverId
            ? '该接收器启用后，设备日志到达即按来源 IP 自动生成条目'
            : '请先在「接收器」页配置监听端点；设备日志到达后按来源 IP 自动生成条目'}
        />
        <div className="border-t border-border px-5 py-3">
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={setPage}
          />
        </div>
      </div>

      {/* 失败样本下钻抽屉（今日接收/解析成功列点击）：原因四分类 + 按原因筛选 */}
      <Drawer
        open={!!drill}
        title={drill ? `失败样本下钻 · ${drill.name}` : ''}
        onClose={() => setDrill(null)}
        width="w-[760px]"
        footer={drillData && (
          <div className="flex w-full items-center justify-between">
            <span className="text-xs text-muted-foreground">
              共 {drillData.total} 条{drillReason ? ` · 已按「${drillData.reason_labels?.[drillReason] || drillReason}」筛选` : ' · 点击上方原因标签可筛选'}
            </span>
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={drillPage <= 1 || drillLoading} onClick={() => loadDrill(drill.entryId, drillReason, drillPage - 1)}>上一页</Button>
              <Button size="sm" disabled={drillPage * 15 >= drillData.total || drillLoading} onClick={() => loadDrill(drill.entryId, drillReason, drillPage + 1)}>下一页</Button>
            </div>
          </div>
        )}
      >
        {drillLoading && !drillData ? (
          <div className="py-10 text-center text-sm text-muted-foreground">加载中…</div>
        ) : !drillData ? (
          <EmptyState icon={Inbox} title="暂无失败样本" description="该来源条目没有解析失败的原始日志留存" />
        ) : (
          <div className="space-y-4">
            {/* 原因分类统计（点击筛选，再点取消） */}
            <div className="flex flex-wrap items-center gap-2">
              {Object.entries(drillData.stats || {}).map(([k, n]) => {
                const active = drillReason === k
                return (
                  <button
                    key={k}
                    type="button"
                    className={`rounded-full border px-3 py-1.5 text-xs transition ${
                      active ? 'border-primary bg-primary/10 font-medium text-primary' : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'
                    }`}
                    title="点击按此原因筛选"
                    onClick={() => applyDrillReason(k)}
                  >
                    {drillData.reason_labels?.[k] || k}
                    <span className={`ml-1.5 tabular-nums ${n > 0 ? (k === 'no_template' || k === 'other' ? 'text-destructive' : 'text-warning') : 'text-muted-foreground/50'}`}>
                      {n.toLocaleString()}
                    </span>
                  </button>
                )
              })}
            </div>

            {/* 样本列表 */}
            {(drillData.items || []).length === 0 ? (
              <EmptyState icon={Inbox} title="当前筛选条件下没有失败样本" description="更换原因分类或清除筛选查看全部" />
            ) : (
              <div className="overflow-hidden rounded-lg border border-border">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-border bg-muted/50 text-left text-muted-foreground">
                      <th className="px-2 py-2 font-semibold">失败原因</th>
                      <th className="px-2 py-2 font-semibold">解析状态</th>
                      <th className="px-2 py-2 font-semibold">错误信息</th>
                      <th className="px-2 py-2 font-semibold">接收时间</th>
                      <th className="px-2 py-2 font-semibold">原文</th>
                    </tr>
                  </thead>
                  <tbody>
                    {drillData.items.map((it) => (
                      <tr key={it.id} className="border-b border-border/40 transition last:border-0 hover:bg-accent/30">
                        <td className="px-2 py-2"><Badge variant="danger">{it.reason_label}</Badge></td>
                        <td className="px-2 py-2 font-mono text-muted-foreground">{it.parse_status || '-'}</td>
                        <td className="max-w-[240px] truncate px-2 py-2 text-muted-foreground" title={it.error_msg}>{it.error_msg || '-'}</td>
                        <td className="px-2 py-2 tabular-nums text-muted-foreground">{fmtTime(it.received_at)}</td>
                        <td className="px-2 py-2">
                          <button
                            type="button"
                            className="rounded px-1.5 py-0.5 text-[11px] text-primary transition hover:bg-primary/10"
                            title="查看失败样本原始日志"
                            onClick={() => setSampleView({ reason_label: it.reason_label, error_msg: it.error_msg, raw_data: it.raw_data })}
                          >
                            查看
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* 失败样本原文查看 */}
      <Modal
        open={!!sampleView}
        title="失败样本原文"
        onClose={() => setSampleView(null)}
        size="lg"
      >
        <div className="space-y-3">
          <div className="flex items-start gap-2 text-xs text-muted-foreground">
            <Badge variant="danger">{sampleView?.reason_label}</Badge>
            <span className="min-w-0 flex-1 break-all">{sampleView?.error_msg}</span>
          </div>
          <pre className="max-h-[420px] overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed break-all whitespace-pre-wrap">
            {sampleView?.raw_data || '（无原始数据）'}
          </pre>
        </div>
      </Modal>
    </PageContainer>
  )
}
