// 解析入库监控页：概览卡片 + 策略维度统计 + 4 张趋势图 + 错误队列 + 服务日志 + 服务健康
// Tab 结构：概览 / 错误队列 / 服务日志 / 服务健康
// 图表统一使用 chartTheme（暗色主题浅色文字、柱状图圆角、悬停明细）
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import {
  Activity, CheckCircle2, XCircle, AlertTriangle, Gauge, Timer, Inbox,
  RotateCw, Trash2, FileJson, RefreshCw, Database, ServerCog, ListFilter, Play,
} from 'lucide-react'
import { toast } from '../store/toastStore'
import { confirm } from '../components/ConfirmDialog'
import { Modal } from '../components/Dialog'
import { Button, PageContainer, PageHeader, Card, DataTable, Badge, Pagination, EmptyState } from '../components/ui'
import { inputBaseCls } from '../components/property/FormControls'
import { getChartTheme } from '../utils/chartTheme'
import { hasPermission } from '../utils/permissions'
import { monitorApi } from '../api/monitor'
import banWorkflowApi from '../api/banWorkflow'
import { useAutoRefresh } from '../hooks/useAutoRefresh'

const fmtTime = (t) => (t ? String(t).replace('T', ' ').slice(0, 19) : '--')
const fmtNum = (n) => (n == null ? '--' : Number(n).toLocaleString('zh-CN'))

// 概览卡片配置（含昨日对比 + 近24小时迷你趋势线）
function OverviewCard({ icon: Icon, label, value, suffix, delta, trend, tone }) {
  const points = (trend || []).map((p) => p.total)
  const max = Math.max(...points, 1)
  // 迷你趋势线（纯 CSS 柱形，无 ECharts 开销）
  return (
    <div className="card px-5 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Icon className={`h-4 w-4 ${tone || 'text-primary'}`} /> {label}
        </div>
        {delta != null && delta !== 0 && (
          <span className={`text-[11px] tabular-nums ${delta > 0 ? 'text-destructive' : 'text-success'}`}>
            {delta > 0 ? '↑' : '↓'} {Math.abs(delta)}%
          </span>
        )}
      </div>
      <div className="mt-1.5 flex items-baseline gap-1">
        <span className="text-2xl font-semibold tabular-nums text-foreground">{value}</span>
        {suffix && <span className="text-xs text-muted-foreground">{suffix}</span>}
      </div>
      {/* 迷你趋势：近24小时逐小时柱形 */}
      <div className="mt-2 flex h-7 items-end gap-[1.5px]">
        {points.map((v, i) => (
          <div
            key={i}
            className={`flex-1 rounded-sm ${v > 0 ? 'bg-primary/60' : 'bg-border'} transition-all`}
            style={{ height: `${Math.max(3, (v / max) * 100)}%` }}
            title={`${trend[i]?.hour}:00 · ${v} 条`}
          />
        ))}
      </div>
    </div>
  )
}

// 堆叠柱状图：入库量趋势（成功绿/部分黄/失败红）
function VolumeChart({ data, window: win, strategies, strategyId, onStrategyChange, onWindowChange }) {
  const t = getChartTheme()
  const labels = data.map((d) => (win === '7d' ? d.label.slice(5) : d.label.slice(11)))
  const option = {
    tooltip: { ...t.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, textStyle: { color: t.textMuted, fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    grid: { top: 34, left: 44, right: 12, bottom: 24 },
    xAxis: { type: 'category', data: labels, axisLine: { lineStyle: { color: t.axisLine } }, axisLabel: { color: t.textMuted, fontSize: 10 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: t.splitLine } }, axisLabel: { color: t.textMuted, fontSize: 10 } },
    series: [
      { name: '成功', type: 'bar', stack: 'total', data: data.map((d) => d.success), barMaxWidth: 22, itemStyle: { color: '#10b981', borderRadius: [0, 0, 0, 0] } },
      { name: '部分解析', type: 'bar', stack: 'total', data: data.map((d) => d.partial), barMaxWidth: 22, itemStyle: { color: '#f59e0b' } },
      { name: '失败', type: 'bar', stack: 'total', data: data.map((d) => d.fail), barMaxWidth: 22, itemStyle: { color: '#ef4444', borderRadius: [3, 3, 0, 0] } },
    ],
  }
  return (
    <Card
      title="入库量趋势"
      description="按解析结果堆叠：成功 / 部分解析 / 失败"
      actions={(
        <div className="flex items-center gap-2">
          <select className={`${inputBaseCls} h-8 w-[170px] text-xs`} value={strategyId} onChange={(e) => onStrategyChange(Number(e.target.value))}>
            <option value={0}>全部策略</option>
            {strategies.filter((s) => s.strategy_id != null).map((s) => (
              <option key={s.strategy_id} value={s.strategy_id}>{s.strategy_name}</option>
            ))}
          </select>
          <div className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-0.5">
            {[['24h', '24小时'], ['7d', '7天']].map(([k, l]) => (
              <button key={k} className={`rounded-md px-2 py-1 text-xs transition ${win === k ? 'bg-primary text-white' : 'text-muted-foreground hover:text-foreground'}`} onClick={() => onWindowChange(k)}>{l}</button>
            ))}
          </div>
        </div>
      )}
    >
      <ReactECharts option={option} style={{ height: 260 }} notMerge />
    </Card>
  )
}

// 成功率趋势：折线图（双 Y 轴附总量）
function RateChart({ data }) {
  const t = getChartTheme()
  const labels = data.map((d) => d.label.slice(-5))
  const option = {
    tooltip: { ...t.tooltip, trigger: 'axis' },
    legend: { top: 0, textStyle: { color: t.textMuted, fontSize: 11 } },
    grid: { top: 34, left: 44, right: 44, bottom: 24 },
    xAxis: { type: 'category', data: labels, boundaryGap: false, axisLine: { lineStyle: { color: t.axisLine } }, axisLabel: { color: t.textMuted, fontSize: 10 } },
    yAxis: [
      { type: 'value', max: 100, axisLabel: { color: t.textMuted, fontSize: 10, formatter: '{value}%' }, splitLine: { lineStyle: { color: t.splitLine } } },
      { type: 'value', axisLabel: { color: t.textMuted, fontSize: 10 }, splitLine: { show: false } },
    ],
    series: [
      {
        name: '入库成功率', type: 'line', smooth: true, symbolSize: 5, data: data.map((d) => d.success_rate),
        itemStyle: { color: '#22d3ee' }, lineStyle: { width: 2 }, areaStyle: { color: 'rgba(34,211,238,0.08)' },
        connectNulls: true,
      },
      { name: '处理总量', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 4, data: data.map((d) => d.total), itemStyle: { color: '#a855f7' }, lineStyle: { width: 1.5, type: 'dashed' } },
    ],
  }
  return (
    <Card title="入库成功率趋势" description="成功率（左轴）与处理总量（右轴）">
      <ReactECharts option={option} style={{ height: 260 }} notMerge />
    </Card>
  )
}

// 风险等级分布：环形图
function RiskChart({ data }) {
  const t = getChartTheme()
  const palette = ['#ef4444', '#f97316', '#f59e0b', '#3b82f6', '#94a3b8', '#6b7280']
  const option = {
    tooltip: { ...t.tooltip, trigger: 'item', formatter: '{b}: {c} 条 ({d}%)' },
    legend: { orient: 'vertical', right: 8, top: 'center', textStyle: { color: t.textMuted, fontSize: 11 } },
    series: [{
      type: 'pie', radius: ['48%', '72%'], center: ['38%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: t.pieBorderColor, borderWidth: 2, borderRadius: 4 },
      label: { show: false },
      data: (data || []).map((d, i) => ({ name: d.name, value: d.count, itemStyle: { color: palette[i % palette.length] } })),
    }],
  }
  return (
    <Card title="风险等级分布" description="今日入库告警按风险等级">
      {(data || []).length === 0 ? (
        <div className="flex h-[260px] items-center justify-center"><EmptyState icon={Inbox} title="今日暂无告警" /></div>
      ) : (
        <ReactECharts option={option} style={{ height: 260 }} notMerge />
      )}
    </Card>
  )
}

// 告警类型 TOP10：横向条形图
function TopThreatChart({ data }) {
  const t = getChartTheme()
  const sorted = [...(data || [])].reverse()
  const option = {
    tooltip: { ...t.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { top: 8, left: 130, right: 40, bottom: 24 },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: t.splitLine } }, axisLabel: { color: t.textMuted, fontSize: 10 } },
    yAxis: {
      type: 'category', data: sorted.map((d) => d.name),
      axisLine: { lineStyle: { color: t.axisLine } },
      axisLabel: { color: t.textMuted, fontSize: 11, width: 120, overflow: 'truncate' },
    },
    series: [{
      type: 'bar', data: sorted.map((d) => d.count), barMaxWidth: 16,
      itemStyle: { color: '#6054f1', borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', color: t.textMuted, fontSize: 10 },
    }],
  }
  return (
    <Card title="告警类型 TOP10" description="按威胁大类 + 威胁类型聚合（今日）">
      {sorted.length === 0 ? (
        <div className="flex h-[260px] items-center justify-center"><EmptyState icon={Inbox} title="今日暂无告警" /></div>
      ) : (
        <ReactECharts option={option} style={{ height: 260 }} notMerge />
      )}
    </Card>
  )
}

// ===== 错误队列 Tab =====
function ErrorQueueTab() {
  const canEdit = hasPermission('monitor', 'edit')
  const navigate = useNavigate()
  const [list, setList] = useState({ total: 0, items: [] })
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [errorType, setErrorType] = useState('')
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState([])
  const [retrying, setRetrying] = useState(null)
  const [rawView, setRawView] = useState(null) // { id, raw_data }
  const [rawLoading, setRawLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    monitorApi.errors({ error_type: errorType, keyword, page, page_size: 20 })
      .then((res) => setList({ total: res.total || 0, items: res.items || [] }))
      .catch((e) => toast.error(e.message || '错误队列加载失败'))
      .finally(() => setLoading(false))
  }, [errorType, keyword, page])

  useEffect(() => { load() }, [load])

  const handleRetry = (row) => {
    setRetrying(row.id)
    monitorApi.retryError(row.id)
      .then((res) => {
        if (res.ok) {
          toast.success(`重新解析成功（${res.status === 'partial' ? '部分解析' : '完全成功'}），已移出错误队列`)
        } else {
          toast.warning(`重试仍失败：${res.error || '未知原因'}${res.need_manual ? '（已转人工处理）' : ''}`)
        }
        load()
      })
      .catch((e) => toast.error(e.message || '重试失败'))
      .finally(() => setRetrying(null))
  }

  const handleBatchRetry = () => {
    if (selected.length === 0) return
    setRetrying(-1)
    monitorApi.retryBatch(selected)
      .then((res) => {
        toast.success(`批量重试完成：成功 ${res.ok} 条，失败 ${res.fail} 条`)
        setSelected([])
        load()
      })
      .catch((e) => toast.error(e.message || '批量重试失败'))
      .finally(() => setRetrying(null))
  }

  const handleDelete = (row) => {
    confirm({
      title: '删除错误记录',
      message: `确认删除错误记录 #${row.id}？删除后该条原始数据将不再支持重试。`,
      variant: 'danger',
      confirmText: '删除',
    }).then((ok) => {
      if (!ok) return
      monitorApi.removeError(row.id)
        .then(() => { toast.success('已删除'); load() })
        .catch((e) => toast.error(e.message || '删除失败'))
    })
  }

  const viewRaw = (row) => {
    setRawLoading(true)
    setRawView({ id: row.id })
    monitorApi.errorRaw(row.id)
      .then((res) => setRawView(res))
      .catch((e) => toast.error(e.message || '加载失败'))
      .finally(() => setRawLoading(false))
  }

  const formatRaw = (raw) => {
    if (!raw) return ''
    try { return JSON.stringify(JSON.parse(raw), null, 2) } catch { return raw }
  }

  const columns = [
    { key: 'id', header: '错误ID', width: '80px', render: (r) => <span className="tabular-nums">#{r.id}</span> },
    { key: 'uuid', header: 'UUID', width: '180px', render: (r) => <span className="truncate font-mono text-xs text-muted-foreground" title={r.uuid}>{r.uuid || '--'}</span> },
    { key: 'strategy_name', header: '策略', width: '170px', render: (r) => <span className="truncate" title={r.strategy_name}>{r.strategy_name || '--'}</span> },
    { key: 'created_at', header: '失败时间', width: '150px', render: (r) => <span className="font-mono text-xs text-muted-foreground">{fmtTime(r.created_at)}</span> },
    { key: 'error_type_label', header: '错误类型', width: '110px', render: (r) => <Badge variant="danger">{r.error_type_label}</Badge> },
    { key: 'error_msg', header: '失败原因', width: '200px', render: (r) => <span className="block max-w-[200px] truncate text-xs text-muted-foreground" title={r.error_msg}>{r.error_msg || '--'}</span> },
    {
      key: 'retry_count', header: '重试次数', width: '110px', numeric: true,
      render: (r) => r.retry_count >= 3
        ? <span className="font-medium text-destructive" title="重试超过 3 次，需人工处理">{r.retry_count} 次 · 需人工处理</span>
        : <span className="tabular-nums text-muted-foreground">{r.retry_count} 次</span>,
    },
    { key: 'raw_summary', header: '原始数据摘要', render: (r) => <span className="block max-w-[220px] truncate font-mono text-xs text-muted-foreground" title={r.raw_summary}>{r.raw_summary || '--'}</span> },
    {
      key: 'actions', header: '操作', width: '130px',
      render: (r) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          {canEdit && (
            <button className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary" title="重新解析" disabled={retrying === r.id} onClick={() => handleRetry(r)}>
              <RotateCw className={`h-4 w-4 ${retrying === r.id ? 'animate-spin' : ''}`} />
            </button>
          )}
          <button className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary" title="查看 JSON" onClick={() => viewRaw(r)}>
            <FileJson className="h-4 w-4" />
          </button>
          {canEdit && (
            <button className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-destructive" title="删除" onClick={() => handleDelete(r)}>
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <select className={`${inputBaseCls} h-[34px] w-[170px]`} value={errorType} onChange={(e) => { setErrorType(e.target.value); setPage(1) }}>
            <option value="">全部错误类型</option>
            <option value="json_parse_failed">JSON解析失败</option>
            <option value="no_strategy_matched">无匹配策略</option>
            <option value="field_validation_failed">字段校验失败</option>
            <option value="db_write_failed">数据库写入失败</option>
          </select>
          <input
            className={`${inputBaseCls} h-[34px] w-[220px]`}
            placeholder="失败原因 / UUID 关键词"
            value={keyword}
            onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
          />
          <Button size="sm" variant="ghost" onClick={load}><RefreshCw className="h-3.5 w-3.5" /> 刷新</Button>
          {canEdit && selected.length > 0 && (
            <Button size="sm" variant="primary" loading={retrying === -1} onClick={handleBatchRetry}>
              <Play className="h-3.5 w-3.5" /> 批量重试（{selected.length}）
            </Button>
          )}
        </div>
      </Card>

      <Card className="p-0" bodyClassName="p-0">
        <DataTable
          columns={columns}
          data={list.items}
          loading={loading}
          rowKey="id"
          selectable={canEdit}
          selectedKeys={selected}
          onSelectChange={setSelected}
          emptyText="错误队列为空"
          emptyDescription="没有待处理的解析失败记录"
          emptyIcon={Inbox}
        />
        <div className="px-4">
          <Pagination page={page} pageSize={20} total={list.total} onPageChange={setPage} pageSizeOptions={[20]} />
        </div>
      </Card>

      {/* 原始数据 JSON 弹窗 */}
      <Modal open={!!rawView} title={`原始数据 #${rawView?.id ?? ''}`} onClose={() => setRawView(null)} size="lg">
        {rawLoading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">加载中…</div>
        ) : (
          <pre className="max-h-[60vh] overflow-auto rounded-lg border border-border bg-muted/40 p-4 font-mono text-xs leading-relaxed text-foreground">
            {formatRaw(rawView?.raw_data)}
          </pre>
        )}
      </Modal>
    </div>
  )
}

// ===== 服务日志 Tab =====
function LogsTab() {
  const [items, setItems] = useState([])
  const [level, setLevel] = useState('')
  const [keyword, setKeyword] = useState('')
  const latestIdRef = useRef(0)
  const levelRef = useRef('')
  const keywordRef = useRef('')
  levelRef.current = level
  keywordRef.current = keyword

  // 拉取：初次全量（过滤条件变化时重置），自动刷新时增量
  const fetchLogs = useCallback((reset = false) => {
    monitorApi.logs({
      level: levelRef.current, keyword: keywordRef.current,
      afterId: reset ? 0 : latestIdRef.current, limit: reset ? 200 : 50,
    }).then((res) => {
      const newItems = res.items || []
      if (newItems.length) latestIdRef.current = newItems[newItems.length - 1].id
      setItems((prev) => (reset ? newItems : [...prev, ...newItems].slice(-500)))
    }).catch(() => { /* 静默 */ })
  }, [])

  useEffect(() => { fetchLogs(true) }, [fetchLogs, level, keyword])
  const { enabled: auto, toggle } = useAutoRefresh(() => fetchLogs(false), { interval: 5000 })

  const levelColor = (l) => {
    if (l === 'ERROR') return 'text-destructive font-semibold'
    if (l === 'WARNING') return 'text-warning'
    return 'text-muted-foreground'
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <select className={`${inputBaseCls} h-[34px] w-[130px]`} value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">全部级别</option>
            <option value="ERROR">ERROR</option>
            <option value="WARNING">WARNING</option>
            <option value="INFO">INFO</option>
            <option value="DEBUG">DEBUG</option>
          </select>
          <input
            className={`${inputBaseCls} h-[34px] w-[220px]`}
            placeholder="日志内容关键词"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Button size="sm" variant="ghost" onClick={() => fetchLogs(true)}>
            <RefreshCw className="h-3.5 w-3.5" /> 刷新
          </Button>
          <button
            className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition ${
              auto ? 'border-primary/60 text-primary' : 'border-border text-muted-foreground hover:text-foreground'
            }`}
            onClick={toggle}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${auto ? 'animate-pulse bg-primary' : 'bg-muted-foreground/40'}`} />
            自动刷新 {auto ? '开' : '关'}
          </button>
          <span className="text-xs text-muted-foreground">每 5 秒增量拉取 · 共 {items.length} 条</span>
        </div>
      </Card>

      <Card className="p-0" bodyClassName="p-0">
        {items.length === 0 ? (
          <EmptyState icon={Inbox} title="暂无日志" description="调整筛选条件或开启自动刷新等待新日志" />
        ) : (
          <div className="max-h-[560px] overflow-y-auto">
            {items.map((it) => (
              <div key={it.id} className="flex items-start gap-3 border-b border-border/50 px-4 py-2 hover:bg-accent/30">
                <span className="w-[140px] shrink-0 font-mono text-xs text-muted-foreground">{it.ts}</span>
                <span className={`w-[64px] shrink-0 text-xs ${levelColor(it.level)}`}>{it.level}</span>
                <span className="w-[150px] shrink-0 truncate font-mono text-xs text-muted-foreground" title={it.module}>{it.module}</span>
                <span className="min-w-0 flex-1 break-all text-xs text-foreground">{it.message}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

// ===== 服务健康 Tab =====
function HealthTab() {
  const [health, setHealth] = useState(null)
  const [overview, setOverview] = useState(null)

  const load = useCallback(() => {
    Promise.all([monitorApi.health(), monitorApi.overview()])
      .then(([h, o]) => { setHealth(h); setOverview(o) })
      .catch((e) => toast.error(e.message || '健康状态加载失败'))
  }, [])

  useEffect(() => { load() }, [load])
  const { enabled: auto, toggle } = useAutoRefresh(load, { interval: 10000 })

  const fmtUptime = (s) => {
    if (s == null) return '--'
    if (s < 60) return `${s} 秒`
    if (s < 3600) return `${Math.floor(s / 60)} 分钟`
    return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分`
  }

  const items = [
    {
      icon: ServerCog, title: '解析服务',
      ok: health?.service?.status === 'running',
      rows: [
        ['状态', health?.service?.status === 'running' ? '运行中' : '已停止'],
        ['启动时间', fmtTime(health?.service?.started_at)],
        ['已运行', fmtUptime(health?.service?.uptime_seconds)],
      ],
    },
    {
      icon: Database, title: '数据库连接',
      ok: health?.database?.status === 'connected',
      rows: [
        ['状态', health?.database?.status === 'connected' ? '连接正常' : `异常：${health?.database?.error || '未知错误'}`],
        ['当前连接数', `${health?.database?.connections ?? '--'} 个`],
      ],
    },
    {
      icon: ListFilter, title: '待处理积压',
      ok: (health?.backlog ?? 0) === 0,
      rows: [
        ['错误队列待处理', `${health?.backlog ?? 0} 条`],
        ['今日无匹配策略', `${overview?.no_match_today ?? 0} 条`],
      ],
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button size="sm" variant="ghost" onClick={load}><RefreshCw className="h-3.5 w-3.5" /> 刷新</Button>
        <button
          className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition ${
            auto ? 'border-primary/60 text-primary' : 'border-border text-muted-foreground hover:text-foreground'
          }`}
          onClick={toggle}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${auto ? 'animate-pulse bg-primary' : 'bg-muted-foreground/40'}`} />
          自动刷新 {auto ? '开' : '关'}
        </button>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {items.map(({ icon: Icon, title, ok, rows }) => (
          <Card key={title}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Icon className="h-4 w-4 text-primary" /> {title}
              </div>
              <span className={`flex items-center gap-1.5 text-xs ${ok ? 'text-success' : 'text-destructive'}`}>
                <span className={`h-2 w-2 rounded-full ${ok ? 'animate-pulse bg-success' : 'bg-destructive'}`} />
                {ok ? '正常' : '异常'}
              </span>
            </div>
            <div className="mt-4 space-y-2.5">
              {rows.map(([k, v]) => (
                <div key={k} className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="tabular-nums text-foreground">{v}</span>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}

// ===== 封禁工作流统计卡片（概览 Tab） =====
function WorkflowStatsRow({ navigate }) {
  const [stats, setStats] = useState(null)

  const load = useCallback(() => {
    banWorkflowApi.stats().then(setStats).catch(() => { /* 静默：无权限/无数据不打扰监控页 */ })
  }, [])

  useEffect(() => { load() }, [load])
  const { enabled: auto, toggle } = useAutoRefresh(load, { interval: 30000 })

  const items = [
    { icon: Zap, label: '今日触发实例', value: fmtNum(stats?.today_instances), tone: 'text-primary' },
    { icon: ShieldBan, label: '今日自动封禁', value: fmtNum(stats?.today_auto_bans), tone: 'text-destructive' },
    { icon: Clock4, label: '待审批工单', value: fmtNum(stats?.pending_approvals), tone: (stats?.pending_approvals ?? 0) > 0 ? 'text-warning' : '' },
    { icon: CheckCircle2, label: '审批通过率', value: stats?.approval_rate == null ? '--' : `${stats.approval_rate}%`, tone: 'text-success' },
    { icon: Timer, label: '平均研判耗时', value: stats?.avg_agent_ms == null ? '--' : `${(stats.avg_agent_ms / 1000).toFixed(1)}s`, tone: '' },
  ]

  return (
    <Card
      title="封禁工作流"
      description="告警入库自动触发 IP 风险研判与封禁：点击卡片查看实例明细"
      actions={(
        <div className="flex items-center gap-2">
          {stats?.circuit?.paused && <Badge variant="danger">熔断暂停中</Badge>}
          <button
            className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition ${auto ? 'border-primary/60 text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}
            onClick={toggle}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${auto ? 'animate-pulse bg-primary' : 'bg-muted-foreground/40'}`} />
            自动刷新 {auto ? '开' : '关'}
          </button>
          <Button size="sm" variant="ghost" onClick={() => navigate('/ban-workflow/instances')}>
            实例管理
          </Button>
        </div>
      )}
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {items.map(({ icon: Icon, label, value, tone }) => (
          <button
            key={label}
            className="flex items-center gap-3 rounded-lg border border-border bg-muted/20 px-4 py-3 text-left transition hover:border-primary/40"
            onClick={() => navigate('/ban-workflow/instances')}
          >
            <Icon className={`h-4.5 w-4.5 shrink-0 ${tone || 'text-primary'}`} size={18} />
            <div className="min-w-0">
              <div className="truncate text-xs text-muted-foreground">{label}</div>
              <div className={`mt-0.5 text-lg font-semibold tabular-nums ${tone || 'text-foreground'}`}>{value}</div>
            </div>
          </button>
        ))}
      </div>
    </Card>
  )
}

// ===== 主页面 =====
export default function IngestionMonitor() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'overview'

  const [overview, setOverview] = useState(null)
  const [strategyStats, setStrategyStats] = useState([])
  const [trendData, setTrendData] = useState([])
  const [trendWindow, setTrendWindow] = useState('24h')
  const [strategyId, setStrategyId] = useState(0)
  const [riskData, setRiskData] = useState([])
  const [topThreats, setTopThreats] = useState([])
  const [loading, setLoading] = useState(false)

  const loadOverview = useCallback(() => {
    Promise.all([
      monitorApi.overview(),
      monitorApi.strategyStats(),
      monitorApi.trend(trendWindow, strategyId),
      monitorApi.riskDistribution(),
      monitorApi.topThreats(10),
    ]).then(([ov, ss, tr, risk, top]) => {
      setOverview(ov)
      setStrategyStats(ss.items || [])
      setTrendData(tr.series || [])
      setRiskData(risk.items || [])
      setTopThreats(top.items || [])
    }).catch((e) => toast.error(e.message || '监控数据加载失败'))
  }, [trendWindow, strategyId])

  useEffect(() => { loadOverview() }, [loadOverview])

  const setTab = (t) => setSearchParams({ tab: t }, { replace: true })

  // 概览卡片（带昨日对比 + 24h 迷你趋势线）
  const today = overview?.today
  const yesterday = overview?.yesterday
  const trend = overview?.trend_24h || []
  const pctDelta = (cur, prev) => {
    if (prev == null || prev === 0) return cur ? null : 0
    return Math.round((cur - prev) * 1000 / prev) / 10
  }
  const cards = [
    { icon: Activity, label: '今日接收总数', value: fmtNum(today?.total), delta: pctDelta(today?.total, yesterday?.total), trend },
    { icon: CheckCircle2, label: '入库成功数', value: fmtNum(today?.success), tone: 'text-success', delta: pctDelta(today?.success, yesterday?.success), trend },
    { icon: XCircle, label: '解析失败数', value: fmtNum(today?.fail), tone: 'text-destructive', delta: pctDelta(today?.fail, yesterday?.fail), trend },
    { icon: AlertTriangle, label: '部分解析数', value: fmtNum(today?.partial), tone: 'text-warning', delta: pctDelta(today?.partial, yesterday?.partial), trend },
    { icon: Gauge, label: '入库成功率', value: today?.success_rate == null ? '--' : today.success_rate, suffix: '%', delta: today?.success_rate != null && yesterday?.success_rate != null ? Math.round((today.success_rate - yesterday.success_rate) * 10) / 10 : null, trend },
    { icon: Timer, label: '平均解析耗时', value: today?.avg_parse_ms == null ? '--' : today.avg_parse_ms, suffix: 'ms', delta: pctDelta(today?.avg_parse_ms, yesterday?.avg_parse_ms), trend },
  ]

  // 策略维度统计表（点击行跳转告警列表按设备类型过滤）
  const strategyColumns = [
    { key: 'strategy_name', header: '策略名称', width: '260px', render: (r) => <span className="max-w-[240px] truncate font-medium" title={r.strategy_name}>{r.strategy_name}</span> },
    { key: 'device_type', header: '设备类型', width: '130px', render: (r) => <span className="text-muted-foreground">{r.device_type || '--'}</span> },
    { key: 'today_total', header: '今日解析量', width: '110px', numeric: true, render: (r) => <span className="tabular-nums">{r.today_total ?? 0}</span> },
    { key: 'success', header: '成功', width: '80px', numeric: true, render: (r) => <span className="tabular-nums text-success">{r.success ?? 0}</span> },
    { key: 'partial', header: '部分', width: '80px', numeric: true, render: (r) => <span className="tabular-nums text-warning">{r.partial ?? 0}</span> },
    { key: 'fail', header: '失败', width: '80px', numeric: true, render: (r) => <span className={`tabular-nums ${(r.fail ?? 0) > 0 ? 'text-destructive' : ''}`}>{r.fail ?? 0}</span> },
    {
      key: 'success_rate', header: '成功率', width: '90px', numeric: true,
      render: (r) => (r.success_rate == null ? <span className="text-muted-foreground">--</span> : <span className="tabular-nums">{r.success_rate}%</span>),
    },
    {
      key: 'avg_parse_ms', header: '平均耗时', width: '90px', numeric: true,
      render: (r) => (r.avg_parse_ms == null ? <span className="text-muted-foreground">--</span> : <span className="tabular-nums">{r.avg_parse_ms}ms</span>),
    },
    {
      key: 'no_match', header: '无匹配告警数', width: '110px', numeric: true,
      render: (r) => <span className={`tabular-nums ${r.strategy_id == null && (r.no_match ?? 0) > 0 ? 'text-destructive' : 'text-muted-foreground'}`}>{r.no_match ?? '--'}</span>,
    },
  ]

  const TABS = [
    { key: 'overview', label: '概览' },
    { key: 'errors', label: '错误队列' },
    { key: 'logs', label: '服务日志' },
    { key: 'health', label: '服务健康' },
  ]

  return (
    <PageContainer>
      <PageHeader
        title="解析入库监控"
        description="按策略/设备维度统计解析入库：趋势、错误队列、服务日志与健康状态"
        actions={<Button size="sm" variant="ghost" onClick={loadOverview}><RefreshCw className="h-3.5 w-3.5" /> 刷新</Button>}
      />

      {/* Tab 栏 */}
      <div className="mb-4 flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-1">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            className={`rounded-md px-4 py-1.5 text-sm transition ${tab === key ? 'bg-primary text-white shadow' : 'text-muted-foreground hover:text-foreground'}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="space-y-4">
          {/* 概览卡片（6 张） */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {cards.map((c) => <OverviewCard key={c.label} {...c} />)}
          </div>

          {/* 策略维度统计表 */}
          <Card title="策略维度统计" description="点击行查看该策略的告警明细（跳转告警列表）" className="p-0" bodyClassName="p-0">
            <DataTable
              columns={strategyColumns}
              data={strategyStats}
              rowKey={(r) => (r.strategy_id == null ? 'none' : r.strategy_id)}
              onRowClick={(r) => {
                if (r.device_type) navigate(`/alerts?device_type=${encodeURIComponent(r.device_type)}`)
                else if (r.strategy_id == null) navigate('/alerts')
              }}
              emptyText="暂无策略统计"
              emptyDescription="接入设备产生解析量后此处显示按策略聚合的统计"
              emptyIcon={Inbox}
            />
          </Card>

          {/* 趋势图（4 张） */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <VolumeChart
              data={trendData}
              window={trendWindow}
              strategies={strategyStats}
              strategyId={strategyId}
              onStrategyChange={setStrategyId}
              onWindowChange={setTrendWindow}
            />
            <RateChart data={trendData} />
            <RiskChart data={riskData} />
            <TopThreatChart data={topThreats} />
          </div>
        </div>
      )}

      {tab === 'errors' && <ErrorQueueTab />}
      {tab === 'logs' && <LogsTab />}
      {tab === 'health' && <HealthTab />}
    </PageContainer>
  )
}
