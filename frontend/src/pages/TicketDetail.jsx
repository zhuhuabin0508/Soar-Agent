// 工单详情页：流程步骤条 + 节点处理时间线 + 当前节点操作表单
// - 上游节点字段对处理人只读展示；当前节点表单按快照字段定义动态渲染
// - 处理权限由服务端返回（can_handle：当前节点分组成员或 admin；先到先得）
// - 流转去向：按条件路由自动建议，处理人可确认调整；到达结束节点后工单完成
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  ArrowLeft, CheckCircle2, XCircle, Clock, Paperclip, X,
  SendHorizonal, Ban, UserRound, ChevronRight, Flag, Link2, Archive, ArchiveRestore,
  ShieldCheck, Database, AlertTriangle, ClipboardList,
} from 'lucide-react'
import { toast } from '../store/toastStore'
import { confirm } from '../components/ConfirmDialog'
import { Modal } from '../components/Dialog'
import { inputCls, labelCls, hintCls } from '../components/property/FormControls'
import { Button, PageContainer } from '../components/ui'
import { hasPermission } from '../utils/permissions'
import ticketApi, { attachmentUrl } from '../api/tickets'
import { evalRoutes, fieldDefMap, fieldValueText, FIELD_TYPE_LABELS } from '../utils/ticketFlow'
import { RichEditable, RichTextView, ATTACHMENT_ACCEPT, attachmentFileError } from '../components/TicketRichText'

const STATUS_META = {
  processing: { label: '进行中', cls: 'bg-blue-500/10 text-blue-500', Icon: Clock },
  completed: { label: '已完成', cls: 'bg-emerald-500/10 text-emerald-500', Icon: CheckCircle2 },
  cancelled: { label: '已取消', cls: 'bg-muted text-muted-foreground', Icon: XCircle },
}
const PRIORITY_META = {
  low: { label: '低', cls: 'bg-muted text-muted-foreground' },
  medium: { label: '中', cls: 'bg-blue-500/10 text-blue-500' },
  high: { label: '高', cls: 'bg-amber-500/10 text-amber-500' },
  critical: { label: '紧急', cls: 'bg-red-500/10 text-red-500' },
}
const ACTION_META = {
  create: { label: '发起工单', cls: 'bg-primary/10 text-primary' },
  submit: { label: '提交流转', cls: 'bg-emerald-500/10 text-emerald-500' },
  cancel: { label: '取消工单', cls: 'bg-red-500/10 text-red-500' },
}
// 流转记录 comment 的显示标题（按动作区分语义）
const ACTION_COMMENT_LABELS = { create: '发起备注', submit: '处置意见', cancel: '取消原因' }

// 字段值只读展示（KV 行）
function FieldValueView({ field, value }) {
  if (field?.type === 'file' && value) {
    return (
      <a href={attachmentUrl(value)} target="_blank" rel="noreferrer"
        className="inline-flex max-w-full items-center gap-1 truncate text-sm text-primary hover:underline">
        <Paperclip className="h-3.5 w-3.5 shrink-0" />{decodeURIComponent(String(value).split('/').pop() || '附件')}
      </a>
    )
  }
  // textarea 值含图片引用（![x](url)）时按富文本渲染
  if (field?.type === 'textarea' && typeof value === 'string' && value.includes('](')) {
    return <RichTextView text={value} />
  }
  return <span className="break-all text-sm text-foreground">{fieldValueText(field, value)}</span>
}

// 威胁情报严重程度中文
const THREAT_SEVERITY_LABELS = { high: '高', medium: '中', low: '低' }

// 自动研判单来源块：资产匹配 + 威胁情报全量字段逐项展示（空值统一显示 --）
function EnrichRow({ label, children }) {
  return (
    <div className="flex min-w-0 items-start gap-2">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 break-all">{children}</span>
    </div>
  )
}

function EnrichSourceView({ s }) {
  const t = s.threat
  const geo = t?.geo_info || {}
  const geoText = [geo.country, geo.region, geo.city, geo.isp].filter(Boolean).join(' / ')
  const na = <span className="text-muted-foreground">--</span>
  const fmtTime = (v) => (v ? String(v).replace('T', ' ') : na)
  return (
    <div className="rounded-md border border-border p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="whitespace-nowrap rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">{s.label || s.role}</span>
        <span className="font-mono text-sm font-medium text-foreground">{s.ip}</span>
        {t?.is_malicious ? (
          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-500">
            <AlertTriangle className="h-3 w-3" />恶意
          </span>
        ) : t ? (
          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-500">
            <ShieldCheck className="h-3 w-3" />非恶意
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">威胁情报查询失败</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px]">
        <div className="flex min-w-0 items-start gap-2">
          <span className="shrink-0 text-muted-foreground"><Database className="inline h-3.5 w-3.5" /> 资产匹配：</span>
          {s.asset?.matched ? (
            <Link
              to={`/assets/list?keyword=${encodeURIComponent(s.asset.asset_ip || s.ip)}`}
              className="min-w-0 truncate text-primary hover:underline"
              title={`查看资产：${s.asset.asset_name || '--'}（${s.asset.asset_ip || s.ip}）`}
            >
              {s.asset.asset_name || '--'}
              <span className="ml-1 font-mono text-xs text-muted-foreground">（{s.asset.asset_ip || s.ip}）</span>
            </Link>
          ) : (
            <span className="text-muted-foreground">资产库未匹配</span>
          )}
        </div>
        <EnrichRow label="研判结论：">
          {t
            ? (t.is_malicious
              ? <span className="font-medium text-red-500">恶意</span>
              : <span className="font-medium text-emerald-500">非恶意</span>)
            : na}
        </EnrichRow>
        <EnrichRow label="置信度：">
          {t && t.confidence != null ? `${Math.round(t.confidence * 100)}%` : na}
        </EnrichRow>
        <EnrichRow label="严重程度：">
          {t?.severity ? (THREAT_SEVERITY_LABELS[t.severity] || t.severity) : na}
        </EnrichRow>
        <EnrichRow label="威胁标签：">
          {t?.tags?.length ? (
            <span className="flex flex-wrap gap-1">
              {t.tags.map((tag) => (
                <span key={tag} className="whitespace-nowrap rounded bg-red-500/10 px-1.5 py-0.5 text-xs text-red-500">{tag}</span>
              ))}
            </span>
          ) : na}
        </EnrichRow>
        <EnrichRow label="威胁类型：">
          {t?.threat_types?.length ? t.threat_types.join('、') : na}
        </EnrichRow>
        <EnrichRow label="首次发现：">{fmtTime(t?.first_seen)}</EnrichRow>
        <EnrichRow label="最近发现：">{fmtTime(t?.last_seen)}</EnrichRow>
        <EnrichRow label="地理/归属：">{geoText || na}</EnrichRow>
        <EnrichRow label="关联恶意软件：">
          {t?.related_malware?.length ? t.related_malware.join('、') : na}
        </EnrichRow>
        <EnrichRow label="情报来源：">{t?.source || na}</EnrichRow>
        <EnrichRow label="攻击模式：">
          {t?.attack_patterns?.length ? t.attack_patterns.join('；') : na}
        </EnrichRow>
      </div>
      <div className="mt-2 flex min-w-0 items-start gap-2 text-[13px]">
        <span className="shrink-0 text-muted-foreground">情报描述：</span>
        {t?.description
          ? <span className="min-w-0 break-all rounded-md bg-muted/40 px-3 py-1.5 leading-relaxed text-foreground">{t.description}</span>
          : na}
      </div>
    </div>
  )
}

// 自动研判卡片：发起时对 src_ip/dst_ip 资产匹配 + 威胁情报查询的结果，随工单流转只读展示
function EnrichmentView({ enrichment }) {
  if (!enrichment?.sources?.length) return null
  return (
    <div className="rounded-md border border-border bg-card p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-primary" />
        <span className="font-semibold text-foreground">安全上下文（自动研判）</span>
        <span className="text-xs text-muted-foreground">发起时自动匹配资产库并查询威胁情报，随工单流转只读展示</span>
        {enrichment.enriched_at && (
          <span className="ml-auto whitespace-nowrap text-xs text-muted-foreground">
            研判时间：{new Date(enrichment.enriched_at).toLocaleString('zh-CN', { hour12: false })}
          </span>
        )}
      </div>
      <div className="space-y-3">
        {enrichment.sources.map((s) => <EnrichSourceView key={`${s.role}-${s.ip}`} s={s} />)}
      </div>
      {!!enrichment.errors?.length && (
        <div className="mt-2 break-all text-xs text-amber-500">部分研判失败：{enrichment.errors.join('；')}</div>
      )}
    </div>
  )
}

export default function TicketDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const canDelete = hasPermission('ticket', 'delete')

  const [ticket, setTicket] = useState(null)
  const [loading, setLoading] = useState(true)
  const [values, setValues] = useState({})
  const [routeTo, setRouteTo] = useState('')
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [uploadingKey, setUploadingKey] = useState('')
  // 详情页 Tab：工单详情（流转历史）/ 安全上下文（自动研判）
  const [activeTab, setActiveTab] = useState('detail')

  const load = useCallback(() => {
    setLoading(true)
    ticketApi.getTicket(id)
      .then((res) => {
        setTicket(res)
        // 初始化当前节点表单
        if (res.can_handle && res.current_node) {
          const init = {}
          ;(res.current_node.fields || []).forEach((f) => {
            let v = f.default ?? ''
            if (f.type === 'switch') v = v === true || v === 'true' || v === '是'
            init[f.key] = v
          })
          setValues(init)
          const { options, suggested } = evalRoutes(res.current_node.routes, init)
          setRouteTo(suggested || (options.length === 1 ? options[0].to : '') || '')
          setComment('')
        }
      })
      .catch((e) => toast.error(e.message || '加载工单失败'))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => { load() }, [load])

  const snapshot = ticket?.flow_snapshot || {}
  const nodes = snapshot.nodes || []
  const currentNode = ticket?.current_node
  const { options: routeOptions, suggested: routeSuggested } = useMemo(
    () => evalRoutes(currentNode?.routes, values),
    [currentNode, values],
  )
  const currentFields = currentNode?.fields || []

  // 步骤条节点顺序：处理节点 + 结束
  const stepNodes = useMemo(() => {
    const tasks = nodes.filter((n) => n.type !== 'end')
    const endNode = nodes.find((n) => n.type === 'end')
    return endNode ? [...tasks, endNode] : tasks
  }, [nodes])

  const handledKeys = useMemo(
    () => new Set((ticket?.records || []).filter((r) => r.action !== 'cancel').map((r) => r.node_key)),
    [ticket],
  )

  const uploadFile = async (fkey, file) => {
    if (!file) return
    const err = attachmentFileError(file)
    if (err) return toast.error(err)
    setUploadingKey(fkey)
    try {
      const res = await ticketApi.uploadAttachment(file)
      setValues((s) => ({ ...s, [fkey]: res.url }))
      toast.success(`附件「${res.name}」已上传`)
    } catch (e) {
      toast.error(e.message || '附件上传失败')
    } finally {
      setUploadingKey('')
    }
  }

  const handleSubmit = () => {
    const missing = currentFields.filter((f) => f.required
      && (values[f.key] === undefined || values[f.key] === null || values[f.key] === ''))
    if (missing.length) return toast.error(`请填写必填字段：${missing.map((f) => f.label).join('、')}`)
    if (routeOptions.length > 1 && !routeTo) return toast.error('请选择流转去向')
    const targetKey = routeTo || routeSuggested || ''
    const target = nodes.find((n) => n.key === targetKey)
    confirm({
      title: '确认提交流转',
      message: target?.type === 'end'
        ? '提交后工单将流转至结束节点并标记为已完成，确认提交？'
        : `提交后工单将流转至「${target?.name || targetKey}」（由${ticket.group_names?.[String(target?.group_id)] || '对应分组'}处理），组内任一成员提交即代表全组。确认提交？`,
      confirmText: '提交流转',
    }).then((ok) => {
      if (!ok) return
      setSubmitting(true)
      ticketApi.advanceTicket(id, {
        field_values: values,
        route_to: targetKey,
        comment: comment.trim() || null,
      })
        .then((res) => {
          toast.success(target?.type === 'end' ? '工单已完成' : `已流转至「${target?.name}」`)
          setTicket(res)
          setValues({})
          setComment('')
        })
        .catch((e) => toast.error(e.message || '流转失败'))
        .finally(() => setSubmitting(false))
    })
  }

  const handleCancel = () => {
    if (!cancelReason.trim()) return toast.error('请填写取消原因')
    setCancelling(true)
    ticketApi.cancelTicket(id, { comment: cancelReason.trim() })
      .then((res) => { toast.success('工单已取消'); setTicket(res); setCancelOpen(false) })
      .catch((e) => toast.error(e.message || '取消失败'))
      .finally(() => setCancelling(false))
  }

  // 归档 / 取消归档（仅完结工单可归档；归档后从默认列表隐藏，可随时恢复）
  const finished = ticket?.status === 'completed' || ticket?.status === 'cancelled'
  const handleArchive = () => {
    confirm({
      title: '归档工单',
      message: `归档后工单「${ticket.ticket_no}」将从默认列表隐藏（可在工单中心「已归档」Tab 查看），处理记录完整保留，可随时取消归档。确认归档？`,
      confirmText: '确认归档',
    }).then((ok) => {
      if (!ok) return
      ticketApi.archiveTicket(id)
        .then((res) => { toast.success(`工单 ${res.ticket_no} 已归档`); setTicket(res) })
        .catch((e) => toast.error(e.message || '归档失败'))
    })
  }

  const handleUnarchive = () => {
    ticketApi.unarchiveTicket(id)
      .then((res) => { toast.success(`工单 ${res.ticket_no} 已恢复展示`); setTicket(res) })
      .catch((e) => toast.error(e.message || '取消归档失败'))
  }

  if (loading) {
    return (
      <PageContainer>
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">加载中...</div>
      </PageContainer>
    )
  }
  if (!ticket) return null

  const st = STATUS_META[ticket.status] || STATUS_META.processing
  const pr = PRIORITY_META[ticket.priority] || PRIORITY_META.medium
  // 自动研判数据存在时才显示「安全上下文」Tab（存量工单无数据则隐藏）
  const hasEnrichment = !!(ticket.enrichment_data?.sources?.length)

  return (
    <PageContainer>
      {/* 头部 */}
      <div className="mb-4 rounded-md border border-border bg-card px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <button onClick={() => navigate('/tickets')} className="mb-2 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
              <ArrowLeft className="h-4 w-4" />返回工单列表
            </button>
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-sm font-semibold text-primary">{ticket.ticket_no}</span>
              <h1 className="text-[20px] font-bold text-foreground">{ticket.title}</h1>
              <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium ${st.cls}`}>
                <st.Icon className="h-3.5 w-3.5" />{st.label}
              </span>
              <span className={`inline-flex whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium ${pr.cls}`}>{pr.label}</span>
              {ticket.archived && (
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground"
                  title="已归档：从默认列表隐藏，可在工单中心「已归档」Tab 查看">
                  <Archive className="h-3.5 w-3.5" />已归档
                </span>
              )}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px] text-muted-foreground">
              <span>流程：<Link to="/ticket-config/flows" className="text-foreground hover:text-primary">{ticket.flow_name}</Link>（快照 v{snapshot.version ?? '--'}）</span>
              <span className="flex items-center gap-1"><UserRound className="h-3.5 w-3.5" />发起人：{ticket.created_by_name || '--'}</span>
              <span className="tabular-nums">发起时间：{ticket.created_at ? new Date(ticket.created_at).toLocaleString('zh-CN', { hour12: false }) : '--'}</span>
              {ticket.related_alert_id && (
                <span className="flex items-center gap-1">
                  <Link2 className="h-3.5 w-3.5" />
                  关联告警：<Link to={`/alerts?alert_id=${ticket.related_alert_id}`} className="text-primary hover:underline">#{ticket.related_alert_id}</Link>
                </span>
              )}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {ticket.can_cancel && (
              <Button variant="danger" size="sm" onClick={() => { setCancelReason(''); setCancelOpen(true) }}>
                <Ban className="mr-1 h-3.5 w-3.5" />取消工单
              </Button>
            )}
            {canDelete && ticket.archived && (
              <Button variant="secondary" size="sm" onClick={handleUnarchive}>
                <ArchiveRestore className="mr-1 h-3.5 w-3.5" />取消归档
              </Button>
            )}
            {canDelete && !ticket.archived && finished && (
              <Button variant="secondary" size="sm" onClick={handleArchive}>
                <Archive className="mr-1 h-3.5 w-3.5" />归档
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Tab 行：工单详情（流转历史）/ 安全上下文（自动研判） */}
      <div className="mb-4 flex items-center gap-1 overflow-x-auto border-b border-border">
        <button
          className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition ${activeTab === 'detail' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
          onClick={() => setActiveTab('detail')}
        >
          <ClipboardList className="h-3.5 w-3.5" />工单详情
        </button>
        {hasEnrichment && (
          <button
            className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition ${activeTab === 'enrich' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
            onClick={() => setActiveTab('enrich')}
          >
            <ShieldCheck className="h-3.5 w-3.5" />安全上下文
          </button>
        )}
      </div>

      <div className="flex items-start gap-4">
        {/* 左侧：按 Tab 切换内容 */}
        <div className="min-w-0 flex-1 space-y-4">
          {activeTab === 'detail' && (
          <>
          {/* 流程步骤条 */}
          <div className="rounded-md border border-border bg-card p-5">
            <div className="flex flex-wrap items-center gap-1">
              {stepNodes.map((n, i) => {
                const done = handledKeys.has(n.key)
                const active = ticket.status === 'processing' && ticket.current_node_key === n.key
                const isEnd = n.type === 'end'
                const endDone = ticket.status === 'completed'
                return (
                  <div key={n.key} className="flex items-center">
                    <div className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-[13px] font-medium transition ${active ? 'border-primary bg-primary/10 text-primary' : done || (isEnd && endDone) ? 'border-emerald-500/40 bg-emerald-500/5 text-emerald-500' : 'border-border text-muted-foreground'}`}>
                      <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${active ? 'bg-primary text-white' : done || (isEnd && endDone) ? 'bg-emerald-500 text-white' : 'bg-muted text-muted-foreground'}`}>
                        {isEnd ? '✓' : done || (isEnd && endDone) ? '✓' : i + 1}
                      </span>
                      <span>{n.name || n.key}</span>
                      {!isEnd && ticket.group_names?.[String(n.group_id)] && (
                        <span className="text-[11px] font-normal text-muted-foreground">（{ticket.group_names[String(n.group_id)]}）</span>
                      )}
                    </div>
                    {i < stepNodes.length - 1 && <ChevronRight className="mx-0.5 h-4 w-4 text-muted-foreground/60" />}
                  </div>
                )
              })}
            </div>
          </div>

          {/* 流转历史：时间轴 + 各节点处置意见 */}
          <div className="rounded-md border border-border bg-card p-5">
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className="font-semibold text-foreground">流转历史</span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{(ticket.records || []).length} 条</span>
              <span className="text-xs text-muted-foreground">按处理时间正序展示，含每个节点的处理人与处置意见</span>
            </div>
            {(ticket.records || []).length > 0 ? (
              <div className="relative space-y-4 pl-7">
                <div className="absolute bottom-3 left-[11px] top-3 w-px bg-border" />
                {ticket.records.map((r) => {
                  const nodeDef = nodes.find((n) => n.key === r.node_key)
                  const defs = fieldDefMap(nodeDef?.fields)
                  const am = ACTION_META[r.action] || ACTION_META.submit
                  const routeTarget = r.route_to ? nodes.find((n) => n.key === r.route_to) : null
                  return (
                    <div key={r.id} className="relative">
                      <span className="absolute -left-7 top-6 flex h-[11px] w-[11px] items-center justify-center rounded-full border-2 border-primary bg-card" />
                      <div className="rounded-md border border-border p-4">
                        <div className="mb-3 flex flex-wrap items-center gap-2">
                          <span className="rounded bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">{r.node_key}</span>
                          <span className="font-semibold text-foreground">{r.node_name || r.node_key}</span>
                          <span className={`rounded px-2 py-0.5 text-xs font-medium ${am.cls}`}>{am.label}</span>
                          {r.group_id && ticket.group_names?.[String(r.group_id)] && (
                            <span className="text-xs text-muted-foreground">分组：{ticket.group_names[String(r.group_id)]}</span>
                          )}
                          <div className="flex-1" />
                          <span className="text-xs text-muted-foreground">{r.handler_name || '--'}</span>
                          <span className="tabular-nums text-xs text-muted-foreground">{r.created_at ? new Date(r.created_at).toLocaleString('zh-CN', { hour12: false }) : '--'}</span>
                        </div>
                        {Object.keys(r.field_values || {}).length > 0 && (
                          <div className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-md bg-muted/30 p-4">
                            {Object.entries(r.field_values).map(([k, v]) => (
                              <div key={k} className="flex items-start gap-2 text-sm">
                                <span className="shrink-0 text-muted-foreground">{defs[k]?.label || k}：</span>
                                <FieldValueView field={defs[k]} value={v} />
                              </div>
                            ))}
                          </div>
                        )}
                        {r.comment && (
                          <div className="mt-2 rounded-r-md border-l-2 border-primary/60 bg-primary/5 px-3 py-2">
                            <div className="mb-0.5 text-[11px] font-medium text-primary">
                              {ACTION_COMMENT_LABELS[r.action] || '处置意见'}
                            </div>
                            <div className="text-sm leading-relaxed text-foreground"><RichTextView text={r.comment} /></div>
                          </div>
                        )}
                        {routeTarget && (
                          <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                            <SendHorizonal className="h-3.5 w-3.5" />流转至「{routeTarget.name || routeTarget.key}」
                            {routeTarget.type !== 'end' && ticket.group_names?.[String(routeTarget.group_id)] && (
                              <span>（{ticket.group_names[String(routeTarget.group_id)]}处理）</span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-border py-8 text-center text-sm text-muted-foreground">暂无流转记录</div>
            )}
          </div>
          </>
          )}
          {activeTab === 'enrich' && (
            <EnrichmentView enrichment={ticket.enrichment_data} />
          )}
        </div>

        {/* 右侧：当前节点操作面板 */}
        <div className="w-[380px] shrink-0 space-y-4">
          {ticket.can_handle ? (
            <div className="rounded-md border border-primary/40 bg-card p-5">
              <div className="mb-1 flex items-center gap-2 font-semibold text-foreground">
                <Flag className="h-4 w-4 text-primary" />当前节点：{currentNode?.name || '--'}
              </div>
              <p className="mb-4 text-xs text-muted-foreground">
                您属于「{ticket.group_names?.[String(currentNode?.group_id)] || '当前分组'}」，组内任一成员提交即代表全组（先到先得）
              </p>
              {/* 安全上下文摘要（完整卡片见左侧详情，辅助处理人快速研判） */}
              {ticket.enrichment_data?.sources?.length > 0 && (
                <div className="mb-4 space-y-1.5 rounded-md border border-border bg-muted/30 p-3">
                  <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <ShieldCheck className="h-3.5 w-3.5 text-primary" />安全上下文（发起时自动研判）
                  </div>
                  {ticket.enrichment_data.sources.map((s) => (
                    <div key={`${s.role}-${s.ip}`} className="flex flex-wrap items-center gap-1.5 text-[13px]">
                      <span className="shrink-0 text-muted-foreground">{s.label || s.role}：</span>
                      <span className="shrink-0 font-mono text-foreground">{s.ip}</span>
                      <span className="text-muted-foreground/60">·</span>
                      {s.asset?.matched ? (
                        <Link
                          to={`/assets/list?keyword=${encodeURIComponent(s.asset.asset_ip || s.ip)}`}
                          className="shrink-0 text-primary hover:underline"
                          title={`查看资产：${s.asset.asset_name || '--'}（${s.asset.asset_ip || s.ip}）`}
                        >
                          资产「{s.asset.asset_name || '--'}」
                        </Link>
                      ) : (
                        <span className="shrink-0 text-muted-foreground">资产未匹配</span>
                      )}
                      <span className="text-muted-foreground/60">·</span>
                      {s.threat?.is_malicious ? (
                        <span className="shrink-0 font-medium text-red-500">
                          恶意（置信度 {Math.round((s.threat.confidence || 0) * 100)}%
                          {s.threat.severity ? ` · ${THREAT_SEVERITY_LABELS[s.threat.severity] || s.threat.severity}` : ''}）
                        </span>
                      ) : s.threat ? (
                        <span className="shrink-0 text-emerald-500">无威胁记录</span>
                      ) : (
                        <span className="shrink-0 text-muted-foreground">情报不可用</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
              <div className="space-y-4">
                {currentFields.map((f) => (
                  <div key={`${currentNode?.key || 'n'}-${f.key}`} className={f.type === 'textarea' ? 'col-span-2' : ''}>
                    <label className={labelCls}>
                      {f.label || f.key}
                      {f.required && <span className="text-red-500">*</span>}
                      {f.type !== 'switch' && (
                        <span className="ml-1.5 font-normal text-muted-foreground/70">（{FIELD_TYPE_LABELS[f.type] || f.type}）</span>
                      )}
                    </label>
                    {f.type === 'textarea' && (
                      <RichEditable className={inputCls} minHeight={64} placeholder={f.placeholder || ''} value={values[f.key] ?? ''}
                        onChange={(v) => setValues((s) => ({ ...s, [f.key]: v }))} />
                    )}
                    {f.type === 'select' && (
                      <select className={inputCls} value={values[f.key] ?? ''} onChange={(e) => setValues((s) => ({ ...s, [f.key]: e.target.value }))}>
                        <option value="">请选择</option>
                        {(f.options || []).map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
                      </select>
                    )}
                    {f.type === 'switch' && (
                      <div className="flex h-9 items-center gap-4">
                        {[true, false].map((b) => (
                          <label key={String(b)} className="flex cursor-pointer items-center gap-1.5">
                            <input type="radio" className="h-4 w-4 accent-primary" checked={values[f.key] === b}
                              onChange={() => setValues((s) => ({ ...s, [f.key]: b }))} />
                            <span className="text-sm text-foreground">{b ? '是' : '否'}</span>
                          </label>
                        ))}
                      </div>
                    )}
                    {f.type === 'datetime' && (
                      <input type="datetime-local" className={inputCls} value={values[f.key] ?? ''}
                        onChange={(e) => setValues((s) => ({ ...s, [f.key]: e.target.value }))} />
                    )}
                    {f.type === 'number' && (
                      <input type="number" className={inputCls} placeholder={f.placeholder || ''} value={values[f.key] ?? ''}
                        onChange={(e) => setValues((s) => ({ ...s, [f.key]: e.target.value }))} />
                    )}
                    {f.type === 'file' && (
                      <div className="flex items-center gap-2">
                        <label className="flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-input bg-background px-3 text-sm text-foreground transition hover:border-primary/50 hover:bg-muted/40">
                          <Paperclip className="h-3.5 w-3.5" />
                          {uploadingKey === f.key ? '上传中...' : '上传附件'}
                          <input type="file" className="hidden" accept={ATTACHMENT_ACCEPT}
                            onChange={(e) => { uploadFile(f.key, e.target.files?.[0]); e.target.value = '' }} />
                        </label>
                        {values[f.key] ? (
                          <div className="flex min-w-0 items-center gap-1.5">
                            <a href={attachmentUrl(values[f.key])} target="_blank" rel="noreferrer"
                              className="truncate text-sm text-primary hover:underline">{decodeURIComponent(String(values[f.key]).split('/').pop() || '附件')}</a>
                            <button onClick={() => setValues((s) => ({ ...s, [f.key]: '' }))} className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground" title="移除">
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ) : <span className="text-xs text-muted-foreground">未上传</span>}
                      </div>
                    )}
                    {['text', 'ip', 'url'].includes(f.type) && (
                      <input className={inputCls} placeholder={f.placeholder || (f.type === 'ip' ? '如：192.168.1.10' : '')} value={values[f.key] ?? ''}
                        onChange={(e) => setValues((s) => ({ ...s, [f.key]: e.target.value }))} />
                    )}
                  </div>
                ))}
                {!currentFields.length && <div className="rounded-md border border-dashed border-border py-4 text-center text-sm text-muted-foreground">本节点无需填写字段</div>}

                {routeOptions.length > 1 && (
                  <div>
                    <label className={labelCls}>流转去向<span className="text-red-500">*</span></label>
                    <div className="flex flex-wrap gap-2">
                      {routeOptions.map((r) => {
                        const isSug = routeSuggested === r.to
                        const target = nodes.find((n) => n.key === r.to)
                        return (
                          <button key={r.to} type="button" onClick={() => setRouteTo(r.to)}
                            className={`rounded-md border px-3 py-1.5 text-[13px] font-medium transition ${routeTo === r.to ? 'border-primary bg-primary/10 text-primary' : 'border-border text-foreground hover:border-primary/50'}`}>
                            {r.label || target?.name || r.to}
                            {isSug && <span className="ml-1.5 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-500">条件建议</span>}
                          </button>
                        )
                      })}
                    </div>
                    <p className={hintCls}>按已填内容自动建议流向（绿色标记），可点击调整</p>
                  </div>
                )}
                {routeOptions.length === 1 && routeOptions[0].to && (
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <SendHorizonal className="h-3.5 w-3.5" />
                    提交后流转至「{nodes.find((n) => n.key === routeOptions[0].to)?.name || routeOptions[0].to}」
                  </div>
                )}

                <div>
                  <label className={labelCls}>处理意见（选填）<span className="ml-1 font-normal text-muted-foreground/70">支持粘贴截图</span></label>
                  <RichEditable className={inputCls} minHeight={64} placeholder="填写本节点的处理说明，可直接粘贴截图" value={comment}
                    onChange={setComment} />
                </div>
                <Button variant="primary" className="w-full" loading={submitting} onClick={handleSubmit}>
                  <SendHorizonal className="mr-1 h-4 w-4" />提交流转
                </Button>
              </div>
            </div>
          ) : (
            <div className="rounded-md border border-border bg-card p-5 text-sm text-muted-foreground">
              {ticket.status === 'processing' ? (
                <div className="flex items-start gap-2">
                  <Clock className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" />
                  <span>
                    工单当前停留于「{ticket.current_node_name}」，
                    由「{ticket.current_group_name || '对应分组'}」处理；
                    您不在该分组内，本节点内容对您只读。
                  </span>
                </div>
              ) : (
                <div className="flex items-start gap-2">
                  {ticket.status === 'completed' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
                  <span>
                    {ticket.status === 'completed'
                      ? `工单已按流程完成（${ticket.closed_at ? new Date(ticket.closed_at).toLocaleString('zh-CN', { hour12: false }) : '--'}）`
                      : `工单已取消（${ticket.closed_at ? new Date(ticket.closed_at).toLocaleString('zh-CN', { hour12: false }) : '--'}）`}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* 工单信息摘要 */}
          <div className="rounded-md border border-border bg-card p-5">
            <div className="mb-3 text-sm font-semibold text-foreground">工单信息</div>
            <div className="space-y-2 text-[13px]">
              <div className="flex justify-between gap-3"><span className="text-muted-foreground">工单号</span><span className="font-mono text-foreground">{ticket.ticket_no}</span></div>
              <div className="flex justify-between gap-3"><span className="text-muted-foreground">流程模板</span><span className="text-foreground">{ticket.flow_name}</span></div>
              <div className="flex justify-between gap-3"><span className="text-muted-foreground">快照版本</span><span className="text-foreground">{snapshot.version !== undefined ? `v${snapshot.version}` : '--'}</span></div>
              <div className="flex justify-between gap-3"><span className="text-muted-foreground">发起人</span><span className="text-foreground">{ticket.created_by_name || '--'}</span></div>
              <div className="flex justify-between gap-3"><span className="text-muted-foreground">发起时间</span><span className="tabular-nums text-foreground">{ticket.created_at ? new Date(ticket.created_at).toLocaleString('zh-CN', { hour12: false }) : '--'}</span></div>
              <div className="flex justify-between gap-3"><span className="text-muted-foreground">完结时间</span><span className="tabular-nums text-foreground">{ticket.closed_at ? new Date(ticket.closed_at).toLocaleString('zh-CN', { hour12: false }) : '--'}</span></div>
              {(ticket.remind_count || 0) > 0 && (
                <div className="flex justify-between gap-3">
                  <span className="text-muted-foreground">超时提醒</span>
                  <span className="text-foreground" title={ticket.last_reminded_at ? `最近提醒：${new Date(ticket.last_reminded_at).toLocaleString('zh-CN', { hour12: false })}` : undefined}>
                    已提醒 {ticket.remind_count} 次
                  </span>
                </div>
              )}
              {ticket.related_alert_uuid && (
                <div className="flex justify-between gap-3"><span className="text-muted-foreground">关联告警 UUID</span><span className="truncate font-mono text-xs text-foreground" title={ticket.related_alert_uuid}>{ticket.related_alert_uuid}</span></div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 取消工单弹窗 */}
      <Modal
        open={cancelOpen}
        title="取消工单"
        onClose={() => setCancelOpen(false)}
        size="sm"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCancelOpen(false)}>返回</Button>
            <Button variant="danger" size="sm" loading={cancelling} onClick={handleCancel}>确认取消</Button>
          </>
        }
      >
        <div className="space-y-3 py-2">
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-500">
            取消后工单终止流转，全部处理记录保留；不可恢复。
          </div>
          <div>
            <label className={labelCls}>取消原因<span className="text-red-500">*</span></label>
            <textarea className={`${inputCls} resize-y`} rows={3} placeholder="请说明取消该工单的原因" value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)} />
          </div>
        </div>
      </Modal>
    </PageContainer>
  )
}
