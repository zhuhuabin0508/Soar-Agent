// 工单中心：工单列表（待我处理/我发起/我处理过/全部）+ 发起工单弹窗
// - 发起弹窗：选择已发布流程 → 按首节点字段定义动态渲染表单 → 提交后跳转详情
// - 告警一键发起：从告警列表跳转携带 state.alertPrefill，自动选中流程并按映射预填字段
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  TicketCheck, Plus, Search, Paperclip, X, Eye, Rocket, ChevronRight, Archive, ArchiveRestore, Monitor, Trash2,
  RefreshCw, AlertTriangle,
} from 'lucide-react'
import { toast } from '../store/toastStore'
import { confirm } from '../components/ConfirmDialog'
import { Modal } from '../components/Dialog'
import { inputCls, inputBaseCls, labelCls, hintCls } from '../components/property/FormControls'
import { Button, PageContainer, DataTable, Pagination, CompactSelect, DatePicker } from '../components/ui'
import { hasPermission } from '../utils/permissions'
import ticketApi, { attachmentUrl } from '../api/tickets'
import { evalRoutes, FIELD_TYPE_LABELS } from '../utils/ticketFlow'
import { RichEditable, ATTACHMENT_ACCEPT, ATTACHMENT_EXTS, attachmentFileError } from '../components/TicketRichText'
import { CcChips, CcSelectModal, ccKey } from '../components/CcPicker'

const STATUS_META = {
  processing: { label: '进行中', cls: 'bg-blue-500/10 text-blue-500' },
  completed: { label: '已完成', cls: 'bg-emerald-500/10 text-emerald-500' },
  cancelled: { label: '已取消', cls: 'bg-muted text-muted-foreground' },
}
const PRIORITY_META = {
  low: { label: '低', cls: 'bg-muted text-muted-foreground' },
  medium: { label: '中', cls: 'bg-blue-500/10 text-blue-500' },
  high: { label: '高', cls: 'bg-amber-500/10 text-amber-500' },
  critical: { label: '紧急', cls: 'bg-red-500/10 text-red-500' },
}
const VIEWS = [
  { key: 'my_pending', label: '待我处理' },
  { key: 'created', label: '我发起' },
  { key: 'handled', label: '我处理过' },
  { key: 'cc', label: '抄送我的' },
  { key: 'all', label: '全部' },
  { key: 'archived', label: '已归档' },
]
// 状态指标条 chips：与工单状态枚举同色系，点击联动状态筛选
const STATUS_CHIPS = [
  { key: 'processing', label: '进行中', dot: 'bg-blue-500', active: 'bg-blue-500/15 text-blue-500 ring-blue-500/40', pulse: true },
  { key: 'completed', label: '已完成', dot: 'bg-emerald-500', active: 'bg-emerald-500/15 text-emerald-500 ring-emerald-500/40' },
  { key: 'cancelled', label: '已取消', dot: 'bg-zinc-500', active: 'bg-zinc-500/15 text-zinc-400 ring-zinc-500/40' },
]

export default function TicketCenter() {
  const canEdit = hasPermission('ticket', 'edit')
  const canDelete = hasPermission('ticket', 'delete')
  const canMonitor = hasPermission('ticket_monitor', 'view')
  const navigate = useNavigate()
  const location = useLocation()

  const [view, setView] = useState('my_pending')
  const [list, setList] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [keyword, setKeyword] = useState('')
  const [searchKw, setSearchKw] = useState('')
  const [deletingId, setDeletingId] = useState(null)

  // 发起弹窗
  const [createOpen, setCreateOpen] = useState(false)
  const [flows, setFlows] = useState([])
  const [flowId, setFlowId] = useState('')
  const [title, setTitle] = useState('')
  const [ticketPriority, setTicketPriority] = useState('medium')
  const [values, setValues] = useState({})
  const [routeTo, setRouteTo] = useState('')
  const [comment, setComment] = useState('')
  const [creating, setCreating] = useState(false)
  const [uploadingKey, setUploadingKey] = useState('')
  const [alertPrefill, setAlertPrefill] = useState(null)
  // 发起时追加抄送（模板固定抄送之外手动加）
  const [extraCc, setExtraCc] = useState([])
  const [ccPickerOpen, setCcPickerOpen] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    // 已归档 Tab = view:all + archived:only；其余视图默认排除归档
    ticketApi.listTickets({
      view: view === 'archived' ? 'all' : view,
      archived: view === 'archived' ? 'only' : 'exclude',
      status, priority, q: searchKw, page, size,
    })
      .then((res) => { setList(res.items || []); setTotal(res.total || 0) })
      .catch((e) => toast.error(e.message || '加载工单列表失败'))
      .finally(() => setLoading(false))
  }, [view, status, priority, searchKw, page, size])

  useEffect(() => { load() }, [load])

  // 告警一键发起：携带 state.alertPrefill 自动打开发起弹窗并预填
  useEffect(() => {
    if (location.state?.alertPrefill) {
      const prefill = location.state.alertPrefill
      setAlertPrefill(prefill)
      setTitle(prefill.title || '')
      // 清理 state，避免刷新重复触发
      navigate(location.pathname, { replace: true, state: null })
      ticketApi.flowOptions().then((res) => {
        const opts = (res.items || []).filter((f) => f.can_initiate)
        setFlows(opts)
        if (opts.length === 1) selectFlow(opts[0], prefill)
        setCreateOpen(true)
      }).catch((e) => toast.error(e.message || '加载流程失败'))
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const openCreate = () => {
    setAlertPrefill(null)
    setTitle('')
    setTicketPriority('medium')
    setFlowId('')
    setValues({})
    setRouteTo('')
    setComment('')
    setExtraCc([])
    ticketApi.flowOptions()
      .then((res) => {
        const opts = (res.items || []).filter((f) => f.can_initiate)
        setFlows(opts)
        if (!opts.length) toast.warning('暂无可发起的流程（需先在工单配置中发布流程并将您加入发起分组）')
        setCreateOpen(true)
      })
      .catch((e) => toast.error(e.message || '加载流程失败'))
  }

  // 选择流程：初始化首节点字段值（告警预填按映射）
  const selectFlow = (f, prefill = null) => {
    setFlowId(f.id)
    const init = {}
    ;(f.first_node?.fields || []).forEach((fd) => {
      let v = fd.default ?? ''
      if (prefill && fd.alert_field_mapping) {
        const mapped = prefill.alert?.[fd.alert_field_mapping]
        if (mapped !== undefined && mapped !== null && mapped !== '') v = String(mapped)
      }
      if (fd.type === 'switch') v = v === true || v === 'true' || v === '是'
      init[fd.key] = v
    })
    setValues(init)
    const { options, suggested } = evalRoutes(f.first_node?.routes, init)
    setRouteTo(suggested || (options.length === 1 ? options[0].to : '') || '')
  }

  const currentFlow = flows.find((f) => f.id === Number(flowId))
  const currentFields = currentFlow?.first_node?.fields || []
  const { options: routeOptions, suggested: routeSuggested } = useMemo(
    () => evalRoutes(currentFlow?.first_node?.routes, values),
    [currentFlow, values],
  )

  // 必填校验：缺失字段红框高亮（输入后自动清除），提交时滚动定位到第一个缺失项
  const [missingKeys, setMissingKeys] = useState([])
  const setFieldValue = (key, v) => {
    setValues((s) => ({ ...s, [key]: v }))
    if (missingKeys.includes(key)) setMissingKeys((ks) => ks.filter((k) => k !== key))
  }
  // inputCls 自带 border-input，红框需 !important 覆盖（Tailwind 同特异性按生成顺序，destructive 会被 input 吃掉）
  const fieldCls = (f) => (missingKeys.includes(f.key) ? `${inputCls} !border-destructive ring-1 !ring-destructive` : inputCls)

  const uploadFile = async (fkey, file) => {
    if (!file) return
    const err = attachmentFileError(file)
    if (err) return toast.error(err)
    setUploadingKey(fkey)
    try {
      const res = await ticketApi.uploadAttachment(file)
      setValues((s) => ({ ...s, [fkey]: res.url }))
      setMissingKeys((ks) => ks.filter((k) => k !== fkey))
      toast.success(`附件「${res.name}」已上传`)
    } catch (e) {
      if (e && (e.name === 'TimeoutError' || e.name === 'AbortError')) {
        toast.error('附件上传超时，请重试；请确认文件可正常读取且在 10MB 内')
      } else {
        toast.error(e.message || '附件上传失败')
      }
    } finally {
      setUploadingKey('')
    }
  }

  const handleCreate = () => {
    if (!flowId) return toast.error('请选择流程模板')
    if (!title.trim()) {
      setMissingKeys(['__title'])
      toast.error('请输入工单标题')
      document.querySelector('[data-fkey="__title"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return
    }
    const missing = currentFields.filter((f) => f.required
      && (values[f.key] === undefined || values[f.key] === null || values[f.key] === ''))
    if (missing.length) {
      setMissingKeys(missing.map((f) => f.key))
      toast.error(`请填写必填字段：${missing.map((f) => f.label).join('、')}`)
      document.querySelector(`[data-fkey="${missing[0].key}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return
    }
    if (routeOptions.length > 1 && !routeTo) return toast.error('请选择流转去向')
    setCreating(true)
    ticketApi.createTicket({
      flow_id: Number(flowId),
      title: title.trim(),
      priority: ticketPriority,
      field_values: values,
      route_to: routeTo || (routeSuggested || ''),
      comment: comment.trim() || null,
      related_alert_id: alertPrefill?.alert?.id || null,
      related_alert_uuid: alertPrefill?.alert?.uuid || null,
      cc_targets: extraCc,
    })
      .then((res) => {
        toast.success(`工单已发起：${res.ticket_no}`)
        setCreateOpen(false)
        setMissingKeys([])
        setExtraCc([])
        navigate(`/tickets/${res.id}`)
      })
      .catch((e) => toast.error(e.message || '发起失败'))
      .finally(() => setCreating(false))
  }

  const handleArchive = (r) => {
    confirm({
      title: '归档工单',
      message: `归档后工单「${r.ticket_no}」将从默认列表隐藏（可在「已归档」Tab 查看），处理记录完整保留，可随时取消归档。确认归档？`,
      confirmText: '确认归档',
    }).then((ok) => {
      if (!ok) return
      ticketApi.archiveTicket(r.id)
        .then(() => { toast.success(`工单 ${r.ticket_no} 已归档`); load() })
        .catch((e) => toast.error(e.message || '归档失败'))
    })
  }

  const handleUnarchive = (r) => {
    ticketApi.unarchiveTicket(r.id)
      .then(() => { toast.success(`工单 ${r.ticket_no} 已恢复展示`); load() })
      .catch((e) => toast.error(e.message || '取消归档失败'))
  }

  // 彻底删除工单记录（物理删除，含节点记录与抄送行；仅 ticket:delete 如 admin 可见）
  const handleDelete = (r) => {
    confirm({
      title: '删除工单',
      message: `确认彻底删除工单「${r.ticket_no}（${r.title}）」？节点处理记录与抄送关系将一并删除，操作不可恢复。`,
      variant: 'danger',
      confirmText: '删除',
    }).then((ok) => {
      if (!ok) return
      setDeletingId(r.id)
      ticketApi.deleteTicket(r.id)
        .then(() => { toast.success(`工单 ${r.ticket_no} 已删除`); load() })
        .catch((e) => toast.error(e.message || '删除失败'))
        .finally(() => setDeletingId(null))
    })
  }

  const fmtTime = (v) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '--')

  // 状态指标条统计：从当前列表派生（不新增请求）
  const listStats = useMemo(() => {
    const s = { processing: 0, completed: 0, cancelled: 0, critical: 0 }
    list.forEach((r) => {
      if (s[r.status] !== undefined) s[r.status] += 1
      if (r.priority === 'critical') s.critical += 1
    })
    return s
  }, [list])

  // 是否存在生效的筛选条件（用于区分空态文案与「清除筛选」引导）
  const hasActiveFilters = !!(status || priority || searchKw)
  const clearFilters = () => { setStatus(''); setPriority(''); setSearchKw(''); setKeyword(''); setPage(1) }

  const columns = [
    {
      key: 'ticket_no', header: '工单号', width: '150px',
      render: (r) => <span className="font-mono text-[13px] font-medium text-primary" title={r.ticket_no}>{r.ticket_no}</span>,
    },
    {
      key: 'title', header: '标题',
      render: (r) => (
        <div className="min-w-0">
          <div className="truncate font-medium text-foreground" title={r.title}>{r.title}</div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground" title={r.flow_name}>{r.flow_name}</div>
        </div>
      ),
    },
    {
      key: 'current_node', header: '当前节点', width: '140px',
      render: (r) => r.status === 'processing'
        ? <span title={`${r.current_node_name || '--'}${r.current_group_name ? `（${r.current_group_name}）` : ''}`}>{r.current_node_name || '--'}<span className="ml-1 text-xs text-muted-foreground">{r.current_group_name ? `（${r.current_group_name}）` : ''}</span></span>
        : <span className="text-xs text-muted-foreground">--</span>,
    },
    {
      key: 'priority', header: '优先级', width: '90px',
      render: (r) => {
        const m = PRIORITY_META[r.priority] || { label: r.priority || '--', cls: 'bg-muted text-muted-foreground' }
        return <span className={`inline-flex whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium ${m.cls}`}>{m.label}</span>
      },
    },
    {
      key: 'status', header: '状态', width: '110px',
      render: (r) => {
        const m = STATUS_META[r.status] || { label: r.status || '--', cls: 'bg-muted text-muted-foreground' }
        return (
          <span className="flex items-center gap-1.5">
            <span className={`inline-flex whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium ${m.cls}`}>{m.label}</span>
            {r.archived && (
              <span className="inline-flex whitespace-nowrap rounded bg-muted px-1.5 py-1 text-xs text-muted-foreground" title="已归档：从默认列表隐藏，可在已归档 Tab 查看">
                <Archive className="mr-0.5 h-3 w-3" />已归档
              </span>
            )}
          </span>
        )
      },
    },
    { key: 'created_by_name', header: '发起人', width: '110px', render: (r) => <span title={r.created_by_name || '--'}>{r.created_by_name || '--'}</span> },
    {
      key: 'created_at', header: '发起时间', width: '150px',
      render: (r) => <span className="tabular-nums text-muted-foreground" title={fmtTime(r.created_at)}>{fmtTime(r.created_at)}</span>,
    },
    {
      key: 'actions', header: '操作', width: '270px',
      render: (r) => (
        <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
          <button onClick={(e) => { e.stopPropagation(); navigate(`/tickets/${r.id}`) }}
            className="btn-secondary btn-sm" title="查看工单详情">
            <Eye className="h-3 w-3" />详情
          </button>
          {canDelete && r.archived && (
            <button onClick={(e) => { e.stopPropagation(); handleUnarchive(r) }}
              className="btn-secondary btn-sm" title="取消归档，恢复在默认列表展示">
              <ArchiveRestore className="h-3 w-3" />恢复
            </button>
          )}
          {canDelete && !r.archived && (r.status === 'completed' || r.status === 'cancelled') && (
            <button onClick={(e) => { e.stopPropagation(); handleArchive(r) }}
              className="btn-secondary btn-sm" title="归档后从默认列表隐藏，处理记录保留">
              <Archive className="h-3 w-3" />归档
            </button>
          )}
          {canDelete && (
            <button onClick={(e) => { e.stopPropagation(); handleDelete(r) }} disabled={deletingId === r.id}
              className="btn-danger btn-sm" title="彻底删除工单记录（不可恢复）">
              <Trash2 className="h-3 w-3" />{deletingId === r.id ? '删除中' : '删除'}
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <PageContainer>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">工单中心</h1>
            {!loading && (
              <span className="text-sm font-medium tabular-nums text-foreground">
                共 {total.toLocaleString()} 个工单
              </span>
            )}
          </div>
          <p className="mt-2 text-[13px] text-muted-foreground">安全运营工单流转：节点到达分组后组内全员可见，任一成员提交即代表全组（先到先得）</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canMonitor && (
            <Button variant="secondary" size="sm" onClick={() => window.open('/ticket-monitor', '_blank')}>
              <Monitor className="mr-1 h-3.5 w-3.5" />监控大屏
            </Button>
          )}
          <button type="button" onClick={load} className="btn-secondary btn-sm" title="刷新工单列表">
            <RefreshCw className={`mr-1 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新
          </button>
          {canEdit && (
            <Button variant="primary" size="sm" onClick={openCreate}>
              <Plus className="mr-1 h-3.5 w-3.5" />发起工单
            </Button>
          )}
        </div>
      </div>

      {/* 视图 Tab（下划线式） */}
      <nav className="flex flex-wrap items-center border-b border-border">
        {VIEWS.map((v) => (
          <button key={v.key} type="button"
            onClick={() => { setView(v.key); setPage(1) }}
            className={`-mb-px border-b-2 px-4 py-3 text-sm font-medium transition ${
              view === v.key
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}>
            {v.label}
          </button>
        ))}
      </nav>

      {/* 筛选行 */}
      <div className="mb-4 mt-4 flex flex-wrap items-center gap-3 rounded-md border border-border bg-card px-4 py-2.5">
        <CompactSelect size="lg" block className="w-28" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="">全部状态</option>
          <option value="processing">进行中</option>
          <option value="completed">已完成</option>
          <option value="cancelled">已取消</option>
        </CompactSelect>
        <CompactSelect size="lg" block className="w-28" value={priority} onChange={(e) => { setPriority(e.target.value); setPage(1) }}>
          <option value="">全部优先级</option>
          <option value="low">低</option>
          <option value="medium">中</option>
          <option value="high">高</option>
          <option value="critical">紧急</option>
        </CompactSelect>
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            className={`${inputBaseCls} h-9 w-full pl-9`}
            placeholder="搜索工单号 / 标题"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { setSearchKw(keyword.trim()); setPage(1) } }}
          />
        </div>
        <Button variant="primary" size="sm" className="h-9 whitespace-nowrap" onClick={() => { setSearchKw(keyword.trim()); setPage(1) }}>查询</Button>
      </div>

      {/* 状态指标条：点击 chip 快捷筛选状态，右侧汇总工单总数与紧急工单 */}
      {!loading && list.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {STATUS_CHIPS.map((chip) => {
            const active = status === chip.key
            const count = listStats[chip.key] || 0
            return (
              <button key={chip.key} type="button"
                onClick={() => { setStatus(active ? '' : chip.key); setPage(1) }}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition ${
                  active
                    ? `border-transparent ring-1 ${chip.active}`
                    : 'border-border bg-secondary text-muted-foreground hover:border-primary/40 hover:text-foreground'
                } ${count === 0 && !active ? 'text-muted-foreground' : ''}`}
                title={active ? '点击取消该筛选' : `点击筛选「${chip.label}」的工单`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${chip.dot} ${chip.pulse && count > 0 ? 'animate-pulse' : ''}`} />
                {chip.label}
                <span className="tabular-nums">{count}</span>
              </button>
            )
          })}
          <div className="ml-auto flex items-center gap-4 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5" title="当前筛选条件下的工单总数">
              <TicketCheck className="h-3.5 w-3.5 text-primary/80" />
              工单总数
              <span className={`font-semibold tabular-nums ${total > 0 ? 'text-foreground' : 'text-muted-foreground'}`}>
                {total > 0 ? total.toLocaleString() : '--'}
              </span>
            </span>
            <span className="inline-flex items-center gap-1.5" title="当前页紧急优先级的工单数量">
              <AlertTriangle className="h-3.5 w-3.5 text-primary/80" />
              紧急
              <span className={`font-semibold tabular-nums ${listStats.critical > 0 ? 'text-foreground' : 'text-muted-foreground'}`}>
                {listStats.critical > 0 ? listStats.critical.toLocaleString() : '--'}
              </span>
            </span>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-border">
        <DataTable
          className="table-stagger"
          columns={columns}
          data={list}
          loading={loading}
          rowKey="id"
          onRowClick={(r) => navigate(`/tickets/${r.id}`)}
          rowClassName={() => 'h-12 cursor-pointer'}
          emptyIcon={TicketCheck}
          emptyText={hasActiveFilters ? '未找到匹配的工单' : '暂无工单'}
          emptyDescription={
            hasActiveFilters
              ? '调整关键词或清除筛选条件后再试'
              : view === 'my_pending'
                ? '当前没有指派到您所在分组的待处理工单'
                : view === 'archived'
                  ? '暂无已归档的工单（完结工单可在操作列发起归档）'
                  : '暂无符合条件的工单'
          }
          emptyAction={
            hasActiveFilters
              ? (
                <button type="button" onClick={clearFilters} className="btn-secondary btn-sm">
                  清除筛选
                </button>
              )
              : canEdit && (
                <button type="button" onClick={openCreate} className="btn-primary btn-sm">
                  <Plus className="mr-1 h-3.5 w-3.5" />发起工单
                </button>
              )
          }
        />
      </div>
      <Pagination page={page} pageSize={size} total={total} onPageChange={setPage} onPageSizeChange={(s) => { setSize(s); setPage(1) }} />

      {/* 发起工单弹窗 */}
      <Modal
        open={createOpen}
        title="发起工单"
        onClose={() => setCreateOpen(false)}
        size="lg"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button variant="primary" size="sm" loading={creating} onClick={handleCreate}>
              <Rocket className="mr-1 h-3.5 w-3.5" />发起并流转
            </Button>
          </>
        }
      >
        <div className="space-y-4 py-2">
          {alertPrefill && (
            <div className="flex items-start gap-1.5 rounded-md border border-primary/30 bg-primary/5 p-2.5 text-xs text-foreground">
              <Paperclip className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <span>已关联告警「{alertPrefill.alert?.alert_name || '--'}」，已按字段映射自动预填，可继续修改后提交</span>
            </div>
          )}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className={labelCls}>流程模板<span className="text-red-500">*</span></label>
              <CompactSelect size="lg" block value={flowId}
                onChange={(e) => {
                  const f = flows.find((x) => x.id === Number(e.target.value))
                  if (f) selectFlow(f)
                }}>
                <option value="">请选择流程</option>
                {flows.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </CompactSelect>
            </div>
            <div>
              <label className={labelCls}>工单标题<span className="text-red-500">*</span></label>
              <input data-fkey="__title" className={missingKeys.includes('__title') ? `${inputCls} !border-destructive ring-1 !ring-destructive` : inputCls}
                placeholder="简要概括本次工单" value={title}
                onChange={(e) => {
                  setTitle(e.target.value)
                  if (missingKeys.includes('__title')) setMissingKeys((ks) => ks.filter((k) => k !== '__title'))
                }} />
            </div>
            <div>
              <label className={labelCls}>优先级</label>
              <CompactSelect size="lg" block value={ticketPriority} onChange={(e) => setTicketPriority(e.target.value)}>
                <option value="low">低</option>
                <option value="medium">中</option>
                <option value="high">高</option>
                <option value="critical">紧急</option>
              </CompactSelect>
            </div>
          </div>

          {/* 首节点字段 */}
          {currentFlow && (
            <div className="rounded-md border border-border">
              <div className="flex items-center gap-2 border-b border-border bg-muted px-4 py-2 text-[13px] font-medium text-foreground">
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                {currentFlow.first_node?.name || '发起节点'} · 填写字段
              </div>
              <div className="grid grid-cols-2 gap-4 p-4">
                {currentFields.map((f) => (
                  <div key={`${currentFlow?.id || 'f'}-${f.key}`} data-fkey={f.key} className={f.type === 'textarea' ? 'col-span-2' : ''}>
                    <label className={labelCls}>
                      {f.label || f.key}
                      {f.required && <span className="text-red-500">*</span>}
                      {!['switch', 'file'].includes(f.type) && (
                        <span className="ml-1.5 font-normal text-muted-foreground">（{FIELD_TYPE_LABELS[f.type] || f.type}）</span>
                      )}
                    </label>
                    {f.type === 'textarea' && (
                      <RichEditable className={fieldCls(f)} minHeight={64} placeholder={f.placeholder || ''} value={values[f.key] ?? ''}
                        onChange={(v) => setFieldValue(f.key, v)} />
                    )}
                    {f.type === 'select' && (
                      <CompactSelect size="lg" block value={values[f.key] ?? ''} onChange={(e) => setFieldValue(f.key, e.target.value)}>
                        <option value="">请选择</option>
                        {(f.options || []).map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
                      </CompactSelect>
                    )}
                    {f.type === 'switch' && (
                      <div className="flex h-9 items-center gap-4">
                        {[true, false].map((b) => (
                          <label key={String(b)} className="flex cursor-pointer items-center gap-1.5">
                            <input type="radio" className="h-4 w-4 accent-primary" checked={values[f.key] === b}
                              onChange={() => setFieldValue(f.key, b)} />
                            <span className="text-sm text-foreground">{b ? '是' : '否'}</span>
                          </label>
                        ))}
                      </div>
                    )}
                    {f.type === 'datetime' && (
                      <DatePicker type="datetime" block value={values[f.key] ?? ''}
                        placeholder={f.label || f.key} title={f.label || f.key}
                        onChange={(e) => setFieldValue(f.key, e.target.value)} />
                    )}
                    {f.type === 'number' && (
                      <input type="number" className={fieldCls(f)} placeholder={f.placeholder || ''} value={values[f.key] ?? ''}
                        onChange={(e) => setFieldValue(f.key, e.target.value)} />
                    )}
                    {f.type === 'file' && (
                      <div className="flex flex-wrap items-center gap-2">
                        <label className={`flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border px-3 text-sm text-foreground transition hover:bg-muted ${uploadingKey === f.key ? 'pointer-events-none opacity-60' : ''} ${missingKeys.includes(f.key) ? 'border-destructive bg-destructive/5' : 'border-input bg-background hover:border-primary/50'}`}>
                          <Paperclip className="h-3.5 w-3.5" />
                          {uploadingKey === f.key ? '上传中...' : '上传附件'}
                          <input type="file" className="hidden" accept={ATTACHMENT_ACCEPT}
                            onChange={(e) => { uploadFile(f.key, e.target.files?.[0]); e.target.value = '' }} />
                        </label>
                        {values[f.key]
                          ? (
                            <div className="flex min-w-0 items-center gap-1.5">
                              <a href={attachmentUrl(values[f.key])} target="_blank" rel="noreferrer"
                                className="truncate text-sm text-primary hover:underline">{decodeURIComponent(values[f.key].split('/').pop() || '附件')}</a>
                              <button onClick={() => setFieldValue(f.key, '')} className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground" title="移除">
                                <X className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          )
                          : <span className="text-xs text-muted-foreground">未上传，支持：{ATTACHMENT_EXTS.join(' / ')}（10MB 内）</span>}
                      </div>
                    )}
                    {['text', 'ip', 'url'].includes(f.type) && (
                      <input className={fieldCls(f)} placeholder={f.placeholder || (f.type === 'ip' ? '如：192.168.1.10' : '')} value={values[f.key] ?? ''}
                        onChange={(e) => setFieldValue(f.key, e.target.value)} />
                    )}
                    {f.type === 'switch' && !f.required && <p className={hintCls}>开关型字段提交 是/否</p>}
                  </div>
                ))}
                {!currentFields.length && <div className="col-span-2 py-2 text-center text-sm text-muted-foreground">该节点无需填写字段</div>}
              </div>
            </div>
          )}

          {/* 流转去向 */}
          {currentFlow && routeOptions.length > 1 && (
            <div>
              <label className={labelCls}>流转去向<span className="text-red-500">*</span></label>
              <div className="flex flex-wrap items-center gap-2">
                {routeOptions.map((r) => {
                  const isSug = routeSuggested === r.to
                  return (
                    <button key={r.to} type="button"
                      onClick={() => setRouteTo(r.to)}
                      className={`rounded-md border px-3 py-1.5 text-[13px] font-medium transition ${routeTo === r.to ? 'border-primary bg-primary/10 text-primary' : 'border-border text-foreground hover:border-primary/50'}`}>
                      {r.label || r.to}
                      {isSug && <span className="ml-1.5 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-500">条件建议</span>}
                    </button>
                  )
                })}
              </div>
              <p className={hintCls}>已按当前填写内容自动建议流向（绿色标记），可点击调整；仅一条路由时自动流转</p>
            </div>
          )}

          {/* 抄送：模板固定抄送自动生效（只读展示）+ 可手动追加 */}
          {currentFlow && (
            <div>
              <label className={labelCls}>
                抄送<span className="ml-1 font-normal text-muted-foreground">发起后自动通知抄送对象，工单完结时再次通知结果</span>
              </label>
              <div className="flex flex-wrap items-center gap-1">
                {currentFlow.cc_targets?.length
                  ? <CcChips targets={currentFlow.cc_targets.map((t) => ({ ...t, source: 'template' }))} showSource max={6} />
                  : <span className="text-xs text-muted-foreground">本流程未配置固定抄送</span>}
                {extraCc.length > 0 && (
                  <CcChips targets={extraCc} max={6} onRemove={(t) => setExtraCc((s) => s.filter((x) => ccKey(x) !== ccKey(t)))} />
                )}
                <button
                  type="button"
                  onClick={() => setCcPickerOpen(true)}
                  className="flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1 text-xs font-medium text-muted-foreground transition hover:border-primary/60 hover:text-primary"
                >
                  <Plus className="h-3 w-3" />追加抄送
                </button>
              </div>
            </div>
          )}

          <div>
            <label className={labelCls}>发起备注（选填）<span className="ml-1 font-normal text-muted-foreground">支持粘贴截图</span></label>
            <RichEditable className={inputCls} minHeight={64} placeholder="补充说明本次工单背景，可直接粘贴截图" value={comment}
              onChange={setComment} />
          </div>
        </div>
      </Modal>

      {/* 追加抄送选择弹窗：模板固定抄送与已追加对象置灰不重复选 */}
      <CcSelectModal
        open={ccPickerOpen}
        onClose={() => setCcPickerOpen(false)}
        title="追加抄送对象"
        excludeKeys={[
          ...(currentFlow?.cc_targets || []).map(ccKey),
          ...extraCc.map(ccKey),
        ]}
        onConfirm={(targets) => setExtraCc((s) => [...s, ...targets.filter((t) => !s.some((x) => ccKey(x) === ccKey(t)))])}
      />
    </PageContainer>
  )
}
