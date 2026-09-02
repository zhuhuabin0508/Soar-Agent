// 告警列表页：统计卡片 + 筛选区 + 后端分页表格 + 详情抽屉
// 筛选/排序/分页全部走后端；默认时间范围为最近 24 小时（基于 occur_timestamp）
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  BellRing, Flame, AlertOctagon, MonitorSmartphone, Download, RotateCw, ChevronDown,
  Check, Search, Inbox,
} from 'lucide-react'
import { toast } from '../store/toastStore'
import { Button, PageContainer, PageHeader, Card, DataTable, Badge, Pagination, EmptyState } from '../components/ui'
import { inputBaseCls } from '../components/property/FormControls'
import { hasPermission } from '../utils/permissions'
import { alertApi } from '../api/alert'
import strategyApi from '../api/strategy'
import AlertDetailDrawer from './AlertDetailDrawer'

// ===== 标准模型枚举（下拉选项中文标签）=====
const RISK_LEVELS = [
  { v: 0, label: '严重' }, { v: 1, label: '高危' }, { v: 2, label: '中危' },
  { v: 3, label: '低危' }, { v: 4, label: '信息' }, { v: 5, label: '未知' },
]
const ATTACK_STATES = [{ v: 0, label: '尝试' }, { v: 1, label: '失败' }, { v: 2, label: '成功' }, { v: 3, label: '失利' }]
const DEAL_STATUSES = [
  { v: 0, label: '未处置' }, { v: 10, label: '生成事件' }, { v: 20, label: '已完成' }, { v: 30, label: '已加白' },
  { v: 40, label: '已驳回' }, { v: 50, label: '已忽略' }, { v: 60, label: '已遏制' }, { v: 70, label: '处置中' }, { v: 80, label: '误报' },
]
const STAGES = [
  { v: 0, label: '默认' }, { v: 10, label: '存在风险' }, { v: 20, label: '扫描探测' }, { v: 30, label: '遭受攻击' },
  { v: 40, label: '主机异常' }, { v: 50, label: '内网扩散' }, { v: 60, label: 'C&C通信' }, { v: 70, label: '黑产牟利' }, { v: 80, label: '窃取数据' },
]
const DIRECTIONS = [{ v: 0, label: '无' }, { v: 1, label: '内到外' }, { v: 2, label: '外到内' }, { v: 3, label: '内对内' }]
const PARSE_STATUSES = [{ v: 'success', label: '成功' }, { v: 'partial', label: '部分解析' }, { v: 'fail', label: '失败' }]

// 风险等级徽章颜色：严重红/高危橙/中危黄/低危蓝/信息灰/未知灰
function RiskBadge({ level, name }) {
  const variant = { 0: 'danger', 1: 'danger', 2: 'warning', 3: 'info', 4: 'neutral', 5: 'neutral' }[level] || 'neutral'
  return <Badge variant={variant}>{name || '未知'}</Badge>
}

// 多选下拉（复选框 + 已选计数）
function MultiSelect({ placeholder, options, values, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const toggle = (v) => {
    onChange(values.includes(v) ? values.filter((x) => x !== v) : [...values, v])
  }
  const label = values.length
    ? `${placeholder} ${values.length}`
    : placeholder

  return (
    <div className="relative" ref={ref}>
      <button
        className={`${inputBaseCls} flex h-[34px] w-full items-center justify-between gap-1 text-left ${values.length ? 'border-primary/60 text-foreground' : ''}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="truncate">{label}</span>
        <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute top-[38px] left-0 z-dropdown max-h-64 w-44 overflow-y-auto rounded-lg border border-border bg-popover p-1 shadow-lg">
          {options.map((o) => (
            <button
              key={o.v}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground transition hover:bg-accent"
              onClick={() => toggle(o.v)}
            >
              <span className={`flex h-4 w-4 items-center justify-center rounded border ${values.includes(o.v) ? 'border-primary bg-primary text-white' : 'border-border'}`}>
                {values.includes(o.v) && <Check className="h-3 w-3" />}
              </span>
              <span className="truncate">{o.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// 统计卡片（含涨跌对比）
function StatCard({ icon: Icon, label, value, delta, onClick, clickable, valueClass }) {
  return (
    <div
      className={`card flex items-center gap-3 px-5 py-4 ${clickable ? 'cursor-pointer transition hover:border-primary/40 hover:shadow-md' : ''}`}
      onClick={clickable ? onClick : undefined}
      role={clickable ? 'button' : undefined}
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-4.5 w-4.5" size={18} />
      </div>
      <div className="min-w-0">
        <div className="truncate text-xs text-muted-foreground">{label}</div>
        <div className="mt-0.5 flex items-baseline gap-1.5">
          <span className={`text-xl font-semibold tabular-nums ${valueClass || 'text-foreground'}`}>{value}</span>
          {delta != null && delta !== 0 && (
            <span className={`text-[11px] tabular-nums ${delta > 0 ? 'text-destructive' : 'text-success'}`}>
              {delta > 0 ? '↑' : '↓'} {Math.abs(delta)}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

const fmtTime = (t) => (t ? String(t).replace('T', ' ').slice(0, 19) : '--')
const fmtNum = (n) => (n == null ? '--' : Number(n).toLocaleString('zh-CN'))

// IP 数组 JSON → 首个 + "+N"（悬停全部）
function IpCell({ raw }) {
  let list = []
  if (Array.isArray(raw)) list = raw
  else if (typeof raw === 'string' && raw.startsWith('[')) {
    try { list = JSON.parse(raw) } catch { list = [raw] }
  } else if (raw) list = [raw]
  if (list.length === 0) return <span className="text-muted-foreground">--</span>
  return (
    <span className="font-mono text-[13px]" title={list.join(', ')}>
      {list[0]}{list.length > 1 && <span className="ml-0.5 text-primary">+{list.length - 1}</span>}
    </span>
  )
}

export default function AlertList() {
  const navigate = useNavigate()
  const canExport = hasPermission('alert', 'export')

  // ===== 筛选状态（全部传后端）=====
  const now = useMemo(() => new Date(), [])
  const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19)
  const [filters, setFilters] = useState({
    start_time: iso(new Date(now.getTime() - 24 * 3600 * 1000)),
    end_time: '',
    risk_levels: [], attack_states: [], deal_statuses: [], stages: [], directions: [],
    keyword: '', parse_status: '', device_type: '',
    sort: 'occur_timestamp', order: 'desc',
  })
  const [quickRange, setQuickRange] = useState('24h')
  // 支持 URL 参数预置过滤（监控页策略统计跳转：device_type / parse_status）
  const [searchParams] = useSearchParams()
  const urlDeviceType = searchParams.get('device_type') || ''
  const urlParseStatus = searchParams.get('parse_status') || ''
  const urlKeyword = searchParams.get('keyword') || ''
  useEffect(() => {
    if (urlDeviceType || urlParseStatus || urlKeyword) {
      setFilters((f) => ({ ...f, device_type: urlDeviceType, parse_status: urlParseStatus, keyword: urlKeyword || f.keyword }))
    }
  }, [urlDeviceType, urlParseStatus, urlKeyword])

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [list, setList] = useState({ total: 0, items: [] })
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [selected, setSelected] = useState([])
  const [deviceTypes, setDeviceTypes] = useState([]) // 已启用策略的设备类型
  const [drawerId, setDrawerId] = useState(null)

  const setF = (patch) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
  }

  const setQuick = (key) => {
    setQuickRange(key)
    const nowD = new Date()
    let st = null
    if (key === '1h') st = new Date(nowD.getTime() - 3600 * 1000)
    else if (key === '24h') st = new Date(nowD.getTime() - 24 * 3600 * 1000)
    else if (key === 'today') st = new Date(nowD.getFullYear(), nowD.getMonth(), nowD.getDate())
    else if (key === '7d') st = new Date(nowD.getTime() - 7 * 24 * 3600 * 1000)
    if (st) setF({ start_time: iso(st), end_time: '' })
  }

  const load = useCallback(() => {
    setLoading(true)
    alertApi.list(page, pageSize, filters)
      .then((res) => setList({ total: res.total || 0, items: res.items || [] }))
      .catch((e) => toast.error(e.message || '告警加载失败'))
      .finally(() => setLoading(false))
  }, [page, pageSize, filters])

  const loadStats = useCallback(() => {
    alertApi.stats()
      .then(setStats)
      .catch(() => { /* 卡片失败不打扰列表 */ })
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    loadStats()
    strategyApi.list().then((items) => {
      setDeviceTypes([...new Set((items || []).filter((s) => s.status === 'enabled').map((s) => s.device_type).filter(Boolean))])
    }).catch(() => {})
  }, [loadStats])

  // 时间范围变化时重置到第 1 页
  useEffect(() => { setPage(1) }, [filters.start_time, filters.end_time])

  const handleSort = (key) => {
    if (key !== 'occur_timestamp' && key !== 'risk_level' && key !== 'severity') return
    if (filters.sort === key) {
      setF({ order: filters.order === 'desc' ? 'asc' : 'desc' })
    } else {
      setF({ sort: key, order: 'desc' })
    }
  }

  const handleExport = () => {
    setExporting(true)
    alertApi.export(filters)
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `告警列表_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}_${Date.now().toString().slice(-6)}.csv`
        a.click()
        URL.revokeObjectURL(url)
        toast.success(`已导出 ${list.total} 条告警记录`)
      })
      .catch((e) => toast.error(e.message || '导出失败'))
      .finally(() => setExporting(false))
  }

  const resetFilters = () => {
    setFilters({
      start_time: iso(new Date(Date.now() - 24 * 3600 * 1000)), end_time: '',
      risk_levels: [], attack_states: [], deal_statuses: [], stages: [], directions: [],
      keyword: '', parse_status: '', device_type: '',
      sort: 'occur_timestamp', order: 'desc',
    })
    setQuickRange('24h')
    setPage(1)
  }

  const SortHeader = ({ label, sortKey, align }) => {
    const active = filters.sort === sortKey
    return (
      <button
        className={`flex items-center gap-1 font-semibold transition hover:text-primary ${align === 'right' ? 'flex-row-reverse ml-auto' : ''} ${active ? 'text-primary' : ''}`}
        onClick={() => handleSort(sortKey)}
      >
        {label}
        <ChevronDown className={`h-3 w-3 transition ${active && filters.order === 'asc' ? 'rotate-180' : ''} ${active ? 'opacity-100' : 'opacity-30'}`} />
      </button>
    )
  }

  const columns = [
    {
      key: 'alert_name', header: '告警名称', width: '220px',
      render: (r) => (
        <button
          className="max-w-[200px] truncate text-left font-medium text-foreground transition hover:text-primary"
          title={r.alert_name}
          onClick={() => setDrawerId(r.id)}
        >
          {r.alert_name || '--'}
        </button>
      ),
    },
    {
      key: 'risk_level', header: '风险等级', width: '90px',
      render: (r) => <RiskBadge level={r.risk_level} name={r.risk_level_name} />,
    },
    { key: 'device_type', header: '设备类型', width: '110px', render: (r) => <span className="truncate text-muted-foreground">{r.device_type || '--'}</span> },
    { key: 'attack_state', header: '攻击状态', width: '90px', render: (r) => <span className="truncate">{r.attack_state_name || '--'}</span> },
    {
      key: 'ip', header: '源IP → 目的IP', width: '230px',
      render: (r) => (
        <span className="flex items-center gap-1.5">
          <IpCell raw={r.src_ip} />
          <span className="text-muted-foreground/60">→</span>
          <IpCell raw={r.dst_ip} />
        </span>
      ),
    },
    { key: 'direction', header: '方向', width: '80px', render: (r) => <span className="truncate text-muted-foreground">{r.direction_name || '--'}</span> },
    {
      key: 'protocol', header: '协议', width: '80px',
      render: (r) => <span className="font-mono text-[13px] uppercase">{r.protocol || '--'}</span>,
    },
    { key: 'stage', header: '告警阶段', width: '100px', render: (r) => <span className="truncate">{r.stage_name || '--'}</span> },
    {
      key: 'occur_timestamp', header: '发生时间', width: '160px',
      render: (r) => <span className="font-mono text-[13px] text-muted-foreground">{fmtTime(r.occur_timestamp)}</span>,
    },
    {
      key: 'deal_status', header: '处置状态', width: '90px',
      render: (r) => <Badge variant={r.deal_status === 0 ? 'warning' : r.deal_status === 20 ? 'success' : 'neutral'}>{r.deal_status_name || '未知'}</Badge>,
    },
    {
      key: 'parse_status', header: '解析状态', width: '90px',
      render: (r) => (
        <span className={`text-xs font-medium ${r.parse_status === 'success' ? 'text-success' : r.parse_status === 'partial' ? 'text-warning' : 'text-destructive'}`}>
          {r.parse_status === 'success' ? '成功' : r.parse_status === 'partial' ? '部分解析' : '失败'}
        </span>
      ),
    },
    {
      key: 'actions', header: '操作', width: '100px',
      render: (r) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary"
            title="详情"
            onClick={() => setDrawerId(r.id)}
          >
            <Search className="h-4 w-4" />
          </button>
          {canExport && (
            <button
              className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary"
              title="导出当前筛选"
              onClick={handleExport}
            >
              <Download className="h-4 w-4" />
            </button>
          )}
        </div>
      ),
    },
  ]

  const hasActiveFilters = filters.risk_levels.length || filters.attack_states.length || filters.deal_statuses.length
    || filters.stages.length || filters.directions.length || filters.keyword || filters.parse_status || filters.device_type
    || filters.end_time

  return (
    <PageContainer>
      <PageHeader
        title="告警列表"
        description="基于标准告警模型的统一告警视图：多设备混合展示、筛选排序分页全部服务端执行"
        actions={canExport && (
          <Button variant="primary" loading={exporting} onClick={handleExport}>
            <Download className="h-4 w-4" /> 导出 CSV
          </Button>
        )}
      />

      {/* 统计卡片 */}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icon={BellRing} label="今日告警总数" value={fmtNum(stats?.today_total)} delta={stats?.delta} />
        <StatCard icon={Flame} label="今日高危及以上" value={fmtNum(stats?.today_high)} valueClass="text-warning" />
        <StatCard
          icon={AlertOctagon}
          label="解析失败数"
          value={fmtNum(stats?.today_fail)}
          valueClass={(stats?.today_fail ?? 0) > 0 ? 'text-destructive' : 'text-foreground'}
          clickable
          onClick={() => navigate('/ingest-monitor?tab=errors')}
        />
        <StatCard icon={MonitorSmartphone} label="接入设备类型数" value={fmtNum(stats?.device_type_count)} />
      </div>

      {/* 筛选区（卡片容器，单行横排） */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-2.5">
          {/* 时间范围快捷 */}
          <div className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-1">
            {[['1h', '1小时'], ['24h', '24小时'], ['today', '今天'], ['7d', '7天']].map(([key, label]) => (
              <button
                key={key}
                className={`rounded-md px-2.5 py-1 text-xs transition ${quickRange === key ? 'bg-primary text-white' : 'text-muted-foreground hover:text-foreground'}`}
                onClick={() => setQuick(key)}
              >
                {label}
              </button>
            ))}
          </div>
          <input
            type="datetime-local"
            className={`${inputBaseCls} h-[34px] w-[190px] font-mono text-xs`}
            value={filters.start_time}
            onChange={(e) => { setQuickRange(''); setF({ start_time: e.target.value }) }}
            title="开始时间（基于发生时间）"
          />
          <span className="text-xs text-muted-foreground">至</span>
          <input
            type="datetime-local"
            className={`${inputBaseCls} h-[34px] w-[190px] font-mono text-xs`}
            value={filters.end_time}
            onChange={(e) => { setQuickRange(''); setF({ end_time: e.target.value }) }}
            title="结束时间"
          />

          <MultiSelect placeholder="风险等级" options={RISK_LEVELS} values={filters.risk_levels} onChange={(v) => setF({ risk_levels: v })} />
          <MultiSelect placeholder="攻击状态" options={ATTACK_STATES} values={filters.attack_states} onChange={(v) => setF({ attack_states: v })} />
          <MultiSelect placeholder="处置状态" options={DEAL_STATUSES} values={filters.deal_statuses} onChange={(v) => setF({ deal_statuses: v })} />
          <MultiSelect placeholder="告警阶段" options={STAGES} values={filters.stages} onChange={(v) => setF({ stages: v })} />
          <MultiSelect placeholder="访问方向" options={DIRECTIONS} values={filters.directions} onChange={(v) => setF({ directions: v })} />

          <select className={`${inputBaseCls} h-[34px] w-[120px]`} value={filters.parse_status} onChange={(e) => setF({ parse_status: e.target.value })}>
            <option value="">解析状态</option>
            {PARSE_STATUSES.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
          </select>
          <select className={`${inputBaseCls} h-[34px] w-[150px]`} value={filters.device_type} onChange={(e) => setF({ device_type: e.target.value })}>
            <option value="">全部设备类型</option>
            {deviceTypes.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>

          <input
            className={`${inputBaseCls} h-[34px] w-[200px]`}
            placeholder="源IP / 目的IP / 告警名称"
            value={filters.keyword}
            onChange={(e) => setF({ keyword: e.target.value })}
            onKeyDown={(e) => { if (e.key === 'Enter') load() }}
          />

          <Button size="sm" variant="ghost" onClick={() => load()}>
            <RotateCw className="h-3.5 w-3.5" /> 刷新
          </Button>
          {hasActiveFilters ? (
            <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={resetFilters}>清除筛选</Button>
          ) : null}
        </div>
      </Card>

      {/* 告警表格（后端分页） */}
      <Card className="p-0" bodyClassName="p-0">
        <DataTable
          columns={columns}
          data={list.items}
          loading={loading}
          rowKey="id"
          selectable={false}
          selectedKeys={selected}
          onSelectChange={setSelected}
          emptyText="暂无告警"
          emptyDescription="当前时间范围内没有匹配的告警记录"
          emptyIcon={Inbox}
        />
        <div className="px-4">
          <Pagination
            page={page}
            pageSize={pageSize}
            total={list.total}
            onPageChange={setPage}
            onPageSizeChange={(s) => { setPageSize(s); setPage(1) }}
            pageSizeOptions={[20, 50, 100]}
          />
        </div>
      </Card>

      {/* 详情抽屉（60% 宽，Tab） */}
      <AlertDetailDrawer
        open={drawerId != null}
        alertId={drawerId}
        onClose={() => setDrawerId(null)}
      />
    </PageContainer>
  )
}
