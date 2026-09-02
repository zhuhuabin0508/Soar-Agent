// 值班表页：生成 + 预览 + 查看（列表/月视图）+ 手动调班 + 导出 + 特殊日期
import { useState, useEffect, useCallback, useMemo } from 'react'
import { CalendarDays, List, Sparkles, Download, CalendarCog, CheckCircle2, AlertTriangle, ChevronLeft, ChevronRight, Sun, Moon, CalendarOff, Zap, ClipboardCheck, Trash2 } from 'lucide-react'
import { toast } from '../store/toastStore'
import { confirm } from '../components/ConfirmDialog'
import { Modal } from '../components/Dialog'
import HalfDrawer from '../components/HalfDrawer'
import { inputCls, inputBaseCls, labelCls } from '../components/property/FormControls'
import { Button, PageContainer, Badge, EmptyState, DataTable, LoadingState } from '../components/ui'
import { hasPermission } from '../utils/permissions'
import dutyApi from '../api/duty'

const STATUS_META = {
  draft: { label: '草稿', variant: 'warning' },
  published: { label: '已发布', variant: 'success' },
  expired: { label: '已过期', variant: 'neutral' },
}
const WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const MONTH_CN = ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月']

function todayStr() { return new Date().toISOString().slice(0, 10) }
function monthRange(year, month) {
  const start = `${year}-${String(month).padStart(2, '0')}-01`
  const end = new Date(year, month, 0).toISOString().slice(0, 10)
  return { start, end }
}

export default function DutySchedule() {
  const canEdit = hasPermission('duty', 'edit')
  const canDelete = hasPermission('duty', 'delete')

  // 视图模式与日期范围
  const today = new Date()
  const [view, setView] = useState('list') // list | month
  const [range, setRange] = useState(monthRange(today.getFullYear(), today.getMonth() + 1))

  const [list, setList] = useState([])
  const [monthData, setMonthData] = useState({ days: [] })
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState(null)
  const [members, setMembers] = useState([])

  // 筛选
  const [filterGroup, setFilterGroup] = useState('')
  const [filterMember, setFilterMember] = useState(0)
  const [showPhone, setShowPhone] = useState(true) // 显示电话
  const [onlyPending, setOnlyPending] = useState(false) // 只看待分配/需调整

  // 生成弹窗
  const [genOpen, setGenOpen] = useState(false)
  const [genForm, setGenForm] = useState({
    start_date: todayStr(),
    end_date: todayStr(),
    conflict_strategy: 'overwrite',
    auto_publish: false,
  })
  const [genResult, setGenResult] = useState(null)
  const [generating, setGenerating] = useState(false)

  // 调班抽屉
  const [adjustTarget, setAdjustTarget] = useState(null) // { record, shift }
  const [adjustMemberId, setAdjustMemberId] = useState('')
  const [adjustReason, setAdjustReason] = useState('')
  const [adjusting, setAdjusting] = useState(false)

  // 特殊日期抽屉
  const [specialOpen, setSpecialOpen] = useState(false)
  const [specialList, setSpecialList] = useState([])
  const [specialForm, setSpecialForm] = useState({ date: todayStr(), day_type: 'holiday', note: '' })
  const [specialLoading, setSpecialLoading] = useState(false)

  const loadMembers = useCallback(() => {
    dutyApi.allMembers('').then(setMembers).catch(() => {})
  }, [])

  const loadList = useCallback(() => {
    setLoading(true)
    dutyApi.listSchedule({ start_date: range.start, end_date: range.end, group_name: filterGroup, member_id: filterMember })
      .then((res) => setList(res.items || []))
      .catch((e) => toast.error(e.message || '加载失败'))
      .finally(() => setLoading(false))
  }, [range, filterGroup, filterMember])

  const loadMonth = useCallback(() => {
    const [y, m] = range.start.split('-').map(Number)
    setLoading(true)
    dutyApi.monthSchedule(y, m)
      .then((res) => setMonthData(res))
      .catch((e) => toast.error(e.message || '加载失败'))
      .finally(() => setLoading(false))
  }, [range.start])

  const loadStats = useCallback(() => {
    dutyApi.scheduleStats({ start_date: range.start, end_date: range.end })
      .then(setStats)
      .catch(() => {})
  }, [range.start, range.end])

  useEffect(() => { loadMembers() }, [loadMembers])
  useEffect(() => { view === 'list' ? loadList() : loadMonth() }, [view, loadList, loadMonth])
  useEffect(() => { loadStats() }, [loadStats])

  // 今日值班（从已加载数据提取）
  const todayStr2 = todayStr()
  const todayDuty = useMemo(() => {
    if (view === 'list') {
      return list.find((r) => r.duty_date === todayStr2) || null
    }
    return (monthData.days || []).find((d) => d.duty_date === todayStr2) || null
  }, [view, list, monthData, todayStr2])

  // 生成
  const openGenerate = () => { setGenResult(null); setGenOpen(true) }
  const handleGenerate = () => {
    if (genForm.end_date < genForm.start_date) return toast.error('结束日期不能早于起始日期')
    setGenerating(true)
    setGenResult(null)
    dutyApi.generate(genForm)
      .then((res) => {
        setGenResult(res)
        toast.success(`已生成 ${res.count} 条值班记录`)
        // 刷新视图
        setRange({ start: genForm.start_date, end: genForm.end_date })
      })
      .catch((e) => toast.error(e.message || '生成失败'))
      .finally(() => setGenerating(false))
  }
  const handleConfirm = () => {
    confirm({ title: '确认发布值班表', message: `将 ${genForm.start_date} 至 ${genForm.end_date} 范围内的草稿记录发布为已发布？`, variant: 'info', confirmText: '发布' })
      .then((ok) => {
        if (!ok) return
        dutyApi.confirm(genForm.start_date, genForm.end_date)
          .then((res) => { toast.success(`已发布 ${res.published} 条`); setGenOpen(false); setRange({ start: genForm.start_date, end: genForm.end_date }) })
          .catch((e) => toast.error(e.message || '发布失败'))
      })
  }
  // 发布当前日期范围内的草稿记录（独立入口，不依赖生成弹窗）
  const handlePublishRange = () => {
    confirm({ title: '确认发布值班表', message: `将 ${range.start} 至 ${range.end} 范围内的草稿记录发布为已发布？发布后该范围内的记录将锁定，手动调班不再触发自动接排。`, variant: 'info', confirmText: '发布' })
      .then((ok) => {
        if (!ok) return
        dutyApi.confirm(range.start, range.end)
          .then((res) => { toast.success(`已发布 ${res.published} 条`); view === 'list' ? loadList() : loadMonth(); loadStats() })
          .catch((e) => toast.error(e.message || '发布失败'))
      })
  }
  // 删除单条值班记录（admin）
  const [deletingRecordId, setDeletingRecordId] = useState(null)
  const handleDeleteRecord = (row) => {
    confirm({
      title: '删除值班记录',
      message: `确认删除 ${row.duty_date}（${row.weekday}）的值班记录？该日白班/晚班安排及关联调班日志将一并清除，不可恢复。如需整段重排请用「生成值班表」覆盖。`,
      variant: 'danger',
      confirmText: '删除',
    }).then((ok) => {
      if (!ok) return
      setDeletingRecordId(row.id)
      dutyApi.deleteRecord(row.id)
        .then(() => { toast.success('值班记录已删除'); view === 'list' ? loadList() : loadMonth(); loadStats() })
        .catch((e) => toast.error(e.message || '删除失败'))
        .finally(() => setDeletingRecordId(null))
    })
  }

  // 调班
  const openAdjust = (record, shift) => {
    if (!canEdit) return
    if (record.status === 'expired') return toast.warning('已过期记录不可调整')
    setAdjustTarget({ record, shift })
    const cur = shift === 'DAY' ? record.day_member : record.night_member
    setAdjustMemberId(cur ? String(cur.id) : '')
    setAdjustReason('')
  }
  const handleAdjust = () => {
    setAdjusting(true)
    dutyApi.adjust(adjustTarget.record.id, {
      shift: adjustTarget.shift,
      new_member_id: adjustMemberId ? Number(adjustMemberId) : null,
      reason: adjustReason,
    })
      .then((res) => {
        if (res?.auto_reordered > 0) {
          const label = res?.reordered_shift === 'NIGHT' ? '晚班' : '非工作日白班'
          toast.success(`调班成功，已按新顺序自动接排后续 ${res.auto_reordered} 个${label}`)
        } else if (res?.rotation_anchored) {
          toast.success('调班成功，已重锚定轮换顺序')
        } else {
          toast.success('调班成功')
        }
        setAdjustTarget(null); view === 'list' ? loadList() : loadMonth(); loadStats()
      })
      .catch((e) => toast.error(e.message || '调班失败'))
      .finally(() => setAdjusting(false))
  }

  // 导出
  const handleExport = () => {
    dutyApi.exportSchedule(range.start, range.end).catch((e) => toast.error(e.message || '导出失败'))
  }

  // 特殊日期
  const openSpecial = () => {
    setSpecialOpen(true)
    loadSpecial()
  }
  const loadSpecial = () => {
    setSpecialLoading(true)
    dutyApi.specialDates().then((res) => setSpecialList(res.items || [])).catch(() => {}).finally(() => setSpecialLoading(false))
  }
  const handleAddSpecial = () => {
    if (!specialForm.date) return toast.error('请选择日期')
    const items = [...specialList, { date: specialForm.date, day_type: specialForm.day_type, note: specialForm.note }]
    dutyApi.setSpecialDates(items)
      .then(() => { toast.success('已保存'); loadSpecial() })
      .catch((e) => toast.error(e.message || '保存失败'))
  }
  const handleDeleteSpecial = (d) => {
    dutyApi.deleteSpecialDate(d).then(() => { toast.success('已删除'); loadSpecial() }).catch((e) => toast.error(e.message || '删除失败'))
  }

  // 只看待分配/需调整：客户端二次过滤
  const filteredList = useMemo(() => {
    if (!onlyPending) return list
    return list.filter((r) => r.day_needs_adjust || r.night_needs_adjust || !r.day_member || !r.night_member)
  }, [list, onlyPending])

  // ===== 列表视图 =====
  const listColumns = useMemo(() => ([
    { key: 'duty_date', header: '日期', width: '110px', render: (r) => <span className="text-sm font-medium tabular-nums whitespace-nowrap">{r.duty_date}</span> },
    { key: 'weekday', header: '星期', width: '70px', render: (r) => <span className="text-sm text-muted-foreground whitespace-nowrap">{r.weekday || '--'}</span> },
    {
      key: 'day_type', header: '日期类型', width: '96px',
      render: (r) => r.is_holiday
        ? <span className="inline-flex items-center rounded bg-purple-500/15 px-2 py-0.5 text-xs text-purple-300 whitespace-nowrap">{r.holiday_name ? `非工作日` : '非工作日'}</span>
        : <span className="text-xs text-muted-foreground whitespace-nowrap">工作日</span>,
    },
    {
      key: 'day', header: '白班', width: '170px',
      render: (r) => <ShiftCell shift="DAY" member={r.day_member} needsAdjust={r.day_needs_adjust} showPhone={showPhone} onClick={() => openAdjust(r, 'DAY')} canEdit={canEdit} />,
    },
    {
      key: 'night', header: '晚班', width: '170px',
      render: (r) => <ShiftCell shift="NIGHT" member={r.night_member} needsAdjust={r.night_needs_adjust} showPhone={showPhone} onClick={() => openAdjust(r, 'NIGHT')} canEdit={canEdit} />,
    },
    {
      key: 'status', header: '状态', width: '84px',
      render: (r) => {
        const m = STATUS_META[r.status] || { label: r.status || '--' }
        const cls = r.status === 'published' ? 'bg-emerald-500/10 text-emerald-500' : r.status === 'draft' ? 'bg-amber-500/10 text-amber-500' : 'bg-gray-500/10 text-gray-400'
        return <span className={`inline-flex items-center rounded px-2.5 py-1 text-xs font-medium whitespace-nowrap ${cls}`}>{m.label}</span>
      },
    },
    ...(canDelete ? [{
      key: 'actions', header: '操作', width: '80px',
      render: (r) => (
        <button onClick={() => handleDeleteRecord(r)} disabled={deletingRecordId === r.id}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50 whitespace-nowrap" title="删除该日值班记录">
          <Trash2 className="h-3.5 w-3.5" />{deletingRecordId === r.id ? '删除中' : '删除'}
        </button>
      ),
    }] : []),
  ]), [canEdit, canDelete, showPhone, deletingRecordId])

  // ===== 月视图网格 =====
  const calendarGrid = useMemo(() => {
    const days = monthData.days || []
    if (days.length === 0) return []
    const byDate = {}
    days.forEach((d) => { byDate[d.duty_date] = d })
    const first = new Date(days[0].duty_date)
    const leadDays = (first.getDay() + 6) % 7 // 周一为首列
    const cells = []
    for (let i = 0; i < leadDays; i++) cells.push(null)
    days.forEach((d) => cells.push(d))
    while (cells.length % 7 !== 0) cells.push(null)
    // 分周
    const weeks = []
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7))
    return weeks
  }, [monthData])

  const shiftMonth = (delta) => {
    const [y, m] = range.start.split('-').map(Number)
    let ny = y, nm = m + delta
    if (nm < 1) { nm = 12; ny -= 1 }
    if (nm > 12) { nm = 1; ny += 1 }
    setRange(monthRange(ny, nm))
  }

  return (
    <PageContainer className="flex flex-col">
      {/* 标题区 */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[22px] font-bold text-foreground whitespace-nowrap">值班表</h1>
          <p className="mt-2 text-[13px] text-muted-foreground">按规则自动生成白班/晚班排班，支持手动调班、列表/月视图查看与导出</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={openSpecial}><CalendarCog className="mr-1 h-3.5 w-3.5" />特殊日期</Button>
          <Button variant="ghost" size="sm" onClick={handleExport}><Download className="mr-1 h-3.5 w-3.5" />导出</Button>
          {canEdit && stats && stats.draft > 0 && <Button variant="secondary" size="sm" onClick={handlePublishRange}><CheckCircle2 className="mr-1 h-3.5 w-3.5" />发布草稿<span className="ml-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-500">{stats.draft}</span></Button>}
          {canEdit && <Button variant="primary" size="sm" onClick={openGenerate}><Sparkles className="mr-1 h-3.5 w-3.5" />生成值班表</Button>}
        </div>
      </div>

      {/* 今日值班条：横向三列，白底卡片，左色块区分白班/晚班 */}
      {todayDuty && (
        <div className="mb-4 flex items-center gap-3 rounded-md border border-border bg-card px-3" style={{ minHeight: '64px', maxHeight: '72px' }}>
          <span className="flex shrink-0 items-center gap-1.5 text-sm font-semibold text-foreground whitespace-nowrap"><CalendarDays className="h-4 w-4 text-muted-foreground" />今日值班</span>
          <div className="h-8 w-px bg-border" />
          <div className="flex flex-1 items-center gap-2 overflow-hidden">
            <div className="flex min-w-0 flex-1 items-center gap-2 rounded border-l-4 border-l-blue-500 bg-blue-500/5 px-2.5 py-1">
              <Sun className="h-4 w-4 shrink-0 text-blue-500" />
              <div className="min-w-0">
                <div className="truncate text-[16px] font-medium leading-tight text-foreground">{todayDuty.day_member?.name || '--'}</div>
                <div className="truncate text-[13px] leading-tight text-muted-foreground">{todayDuty.day_member?.phone || ''}</div>
              </div>
            </div>
            <div className="flex min-w-0 flex-1 items-center gap-2 rounded border-l-4 border-l-purple-500 bg-purple-500/5 px-2.5 py-1">
              <Moon className="h-4 w-4 shrink-0 text-purple-500" />
              <div className="min-w-0">
                <div className="truncate text-[16px] font-medium leading-tight text-foreground">{todayDuty.night_member?.name || '--'}</div>
                <div className="truncate text-[13px] leading-tight text-muted-foreground">{todayDuty.night_member?.phone || ''}</div>
              </div>
            </div>
          </div>
          {(todayDuty.day_needs_adjust || todayDuty.night_needs_adjust) && (
            <span className="flex shrink-0 items-center gap-1 text-xs text-amber-500 whitespace-nowrap"><AlertTriangle className="h-3.5 w-3.5" />需调整</span>
          )}
        </div>
      )}

      {/* 统计面板：5 卡片等分，左图标+右数字/标签 */}
      {stats && (
        <div className="mb-4 flex gap-4">
          {[
            { icon: CalendarDays, label: '总天数', value: stats.total, color: 'text-muted-foreground', valueColor: 'text-foreground' },
            { icon: Sun, label: '白班已排', value: stats.day_assigned, sub: `/ 待${stats.day_pending}`, color: 'text-blue-500', valueColor: 'text-blue-500' },
            { icon: Moon, label: '晚班已排', value: stats.night_assigned, sub: `/ 待${stats.night_pending}`, color: 'text-purple-500', valueColor: 'text-purple-500' },
            { icon: CalendarOff, label: '需调整', value: stats.needs_adjust, color: stats.needs_adjust ? 'text-amber-500' : 'text-muted-foreground', valueColor: stats.needs_adjust ? 'text-amber-500' : 'text-foreground' },
            { icon: ClipboardCheck, label: '已发布/草稿', value: stats.published, sub: ` / ${stats.draft}`, color: 'text-emerald-500', valueColor: 'text-foreground' },
          ].map((c) => (
            <div key={c.label} className="flex flex-1 items-center gap-3 rounded-md border border-border bg-card px-4" style={{ height: '80px' }}>
              <c.icon className={`h-6 w-6 shrink-0 ${c.color}`} />
              <div className="min-w-0">
                <div className="flex items-baseline gap-1">
                  <span className={`text-[24px] font-bold tabular-nums leading-none ${c.valueColor}`}>{c.value}</span>
                  {c.sub && <span className="text-[12px] text-muted-foreground whitespace-nowrap">{c.sub}</span>}
                </div>
                <div className="mt-1 text-[13px] text-muted-foreground whitespace-nowrap">{c.label}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 控制行：视图切换 + 筛选（列表）/ 月份导航（月视图），合并为一行避免垂直堆叠 */}
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-md border border-border bg-card px-4 py-2.5">
        <div className="flex shrink-0 items-center rounded-md border border-border p-0.5">
          <button onClick={() => setView('list')} className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs whitespace-nowrap ${view === 'list' ? 'bg-blue-500/10 text-blue-500' : 'text-muted-foreground'}`}><List className="h-3.5 w-3.5" />列表</button>
          <button onClick={() => setView('month')} className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs whitespace-nowrap ${view === 'month' ? 'bg-blue-500/10 text-blue-500' : 'text-muted-foreground'}`}><CalendarDays className="h-3.5 w-3.5" />月视图</button>
        </div>
        {view === 'month' ? (
          <div className="flex items-center gap-2">
            <button onClick={() => shiftMonth(-1)} className="rounded p-1 hover:bg-accent"><ChevronLeft className="h-4 w-4" /></button>
            <span className="text-sm font-medium tabular-nums whitespace-nowrap">{range.start.slice(0, 4)}年 {MONTH_CN[Number(range.start.slice(5, 7)) - 1]}</span>
            <button onClick={() => shiftMonth(1)} className="rounded p-1 hover:bg-accent"><ChevronRight className="h-4 w-4" /></button>
          </div>
        ) : (
          <>
            <div className="h-6 w-px shrink-0 bg-border" />
            <label className="text-xs text-muted-foreground whitespace-nowrap">日期</label>
            <input type="date" className={`${inputBaseCls} h-9 w-[140px]`} value={range.start} onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))} />
            <span className="text-muted-foreground">~</span>
            <input type="date" className={`${inputBaseCls} h-9 w-[140px]`} value={range.end} onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))} />
            <input className={`${inputBaseCls} h-9 w-32`} placeholder="组别" value={filterGroup} onChange={(e) => setFilterGroup(e.target.value)} />
            <select className={`${inputBaseCls} h-9 w-32`} value={filterMember} onChange={(e) => setFilterMember(Number(e.target.value))}>
              <option value={0}>全部人员</option>
              {members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            <label className="flex items-center gap-1 text-xs text-muted-foreground whitespace-nowrap cursor-pointer">
              <input type="checkbox" className="h-4 w-4 rounded border-border accent-blue-500" checked={onlyPending} onChange={(e) => setOnlyPending(e.target.checked)} />只看待分配
            </label>
            <label className="flex items-center gap-1 text-xs text-muted-foreground whitespace-nowrap cursor-pointer">
              <input type="checkbox" className="h-4 w-4 rounded border-border accent-blue-500" checked={showPhone} onChange={(e) => setShowPhone(e.target.checked)} />显示电话
            </label>
            <div className="flex-1" />
            <Button size="sm" variant="secondary" className="h-9 whitespace-nowrap" onClick={loadList}>查询</Button>
          </>
        )}
      </div>

      {/* 内容区：占满剩余高度 */}
      <div className="flex-1 min-h-0">
        {view === 'list' ? (
          <DataTable
            columns={listColumns}
            data={filteredList}
            loading={loading}
            rowKey="duty_date"
            rowClassName={(r) => `h-12 ${r.is_holiday ? 'bg-purple-500/5' : ''}`}
            emptyText="暂无值班记录"
            emptyIcon={CalendarDays}
            emptyDescription="点击右上角「生成值班表」自动排班"
            emptyAction={canEdit && (
              <Button variant="primary" size="sm" onClick={openGenerate}>
                <Sparkles className="mr-1 h-3.5 w-3.5" />生成值班表
              </Button>
            )}
          />
        ) : (
          <div className="h-full overflow-auto rounded-md border border-border">
            {loading ? (
              <LoadingState rows={6} cols={7} className="py-6" />
            ) : calendarGrid.length === 0 ? (
              <div className="flex h-full min-h-[300px] items-center justify-center">
                <EmptyState
                  icon={CalendarDays}
                  title="暂无值班记录"
                  description="点击右上角「生成值班表」自动排班"
                  action={canEdit && (
                    <Button variant="primary" size="sm" onClick={openGenerate}>
                      <Sparkles className="mr-1 h-3.5 w-3.5" />生成值班表
                    </Button>
                  )}
                />
              </div>
            ) : (
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-border bg-muted/40">
                    {WEEKDAY_CN.map((w, i) => (
                      <th key={w} className={`px-2 py-2 text-center text-sm font-bold whitespace-nowrap ${i >= 5 ? 'text-amber-500/80' : 'text-muted-foreground'}`}>{w}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {calendarGrid.map((week, wi) => (
                    <tr key={wi}>
                      {week.map((d, di) => {
                        const isWeekend = di >= 5
                        const dateNum = d ? Number(d.duty_date.slice(8, 10)) : ''
                        return (
                          <td key={di}
                            onClick={d ? () => openAdjust(d, 'DAY') : undefined}
                            className={`align-top p-1.5 border border-border/50 ${d && d.is_today ? 'bg-blue-500/5 ring-2 ring-inset ring-blue-500/40' : ''} ${d && d.is_holiday ? 'bg-purple-500/5' : ''} ${d ? 'cursor-pointer hover:bg-accent/40' : ''}`}
                            style={{ minWidth: '100px', height: '108px', width: '14.28%' }}
                          >
                            {d && (
                              <div className="flex h-full flex-col gap-1">
                                <div className="flex items-center justify-between">
                                  <span className={`text-sm font-semibold ${isWeekend ? 'text-amber-500' : 'text-foreground'}`}>{dateNum}</span>
                                  <span className="text-[10px] text-muted-foreground whitespace-nowrap">{d.is_holiday ? '休' : '班'}</span>
                                </div>
                                <ShiftMini member={d.day_member} shift="白班" needsAdjust={d.day_needs_adjust} onClick={(e) => { e?.stopPropagation?.(); openAdjust(d, 'DAY') }} canEdit={canEdit} />
                                <ShiftMini member={d.night_member} shift="晚班" needsAdjust={d.night_needs_adjust} onClick={(e) => { e?.stopPropagation?.(); openAdjust(d, 'NIGHT') }} canEdit={canEdit} />
                              </div>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* 生成值班表弹窗 */}
      <Modal
        open={genOpen}
        title="生成值班表"
        onClose={() => setGenOpen(false)}
        size="lg"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setGenOpen(false)}>关闭</Button>
            {genResult && !genForm.auto_publish && (
              <Button variant="primary" size="sm" onClick={handleConfirm}><CheckCircle2 className="mr-1 h-3.5 w-3.5" />确认发布</Button>
            )}
            {canEdit && (
              <Button variant="primary" size="sm" loading={generating} onClick={handleGenerate}><Sparkles className="mr-1 h-3.5 w-3.5" />生成</Button>
            )}
          </>
        }
      >
        <div className="space-y-4 py-2">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>起始日期</label>
              <input type="date" className={inputCls} value={genForm.start_date} onChange={(e) => setGenForm({ ...genForm, start_date: e.target.value })} />
            </div>
            <div>
              <label className={labelCls}>结束日期</label>
              <input type="date" className={inputCls} value={genForm.end_date} onChange={(e) => setGenForm({ ...genForm, end_date: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>冲突处理</label>
              <select className={inputCls} value={genForm.conflict_strategy} onChange={(e) => setGenForm({ ...genForm, conflict_strategy: e.target.value })}>
                <option value="overwrite">覆盖重排（已有记录重新生成）</option>
                <option value="fill">仅填充空缺日期（保留已有记录）</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>生成后状态</label>
              <select className={inputCls} value={genForm.auto_publish ? '1' : '0'} onChange={(e) => setGenForm({ ...genForm, auto_publish: e.target.value === '1' })}>
                <option value="0">草稿（生成后可预览再发布）</option>
                <option value="1">直接发布</option>
              </select>
            </div>
          </div>
          <div className="rounded-md border border-border bg-muted/30 p-3 text-[11px] leading-relaxed text-muted-foreground">
            <p>排班规则：工作日白班由「长期白班」主值班人固定值守，晚班按「晚班」类别轮换；非工作日白班按「白班」类别轮换，晚班连续轮换。</p>
            <p className="mt-1">轮换游标持久化，保证连续性；请假人员自动跳过；某类别无人则该班次留空并告警。</p>
          </div>

          {genResult && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <CheckCircle2 className="h-4 w-4 text-success" />
                <span>已生成 {genResult.count} 条记录，批次号 {genResult.batch}</span>
              </div>
              {genResult.warnings && genResult.warnings.length > 0 && (
                <div className="rounded-md border border-warning/30 bg-warning/10 p-2">
                  {genResult.warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs text-warning">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span>{w}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="max-h-64 overflow-y-auto rounded-md border border-border">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/40 text-muted-foreground">
                    <tr><th className="px-2 py-1 text-left">日期</th><th className="px-2 py-1 text-left">白班</th><th className="px-2 py-1 text-left">晚班</th><th className="px-2 py-1 text-left">状态</th></tr>
                  </thead>
                  <tbody>
                    {genResult.records.map((r, i) => (
                      <tr key={i} className="border-t border-border/50">
                        <td className="px-2 py-1">{r.duty_date} {r.weekday}</td>
                        <td className="px-2 py-1">{r.day_member ? r.day_member.name : <span className="text-destructive">待分配</span>}</td>
                        <td className="px-2 py-1">{r.night_member ? r.night_member.name : <span className="text-destructive">待分配</span>}</td>
                        <td className="px-2 py-1"><Badge variant={(STATUS_META[r.status] || {}).variant}>{(STATUS_META[r.status] || {}).label}</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </Modal>

      {/* 手动调班抽屉 */}
      <HalfDrawer
        open={!!adjustTarget}
        onClose={() => setAdjustTarget(null)}
        title="手动调班"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setAdjustTarget(null)}>取消</Button>
            <Button variant="primary" size="sm" loading={adjusting} onClick={handleAdjust}>保存调班</Button>
          </div>
        }
      >
        {adjustTarget && (
          <div className="space-y-4">
            <div className="rounded-md border border-border bg-muted/30 p-3 text-sm">
              <div>日期：<span className="font-medium">{adjustTarget.record.duty_date} {adjustTarget.record.weekday}</span></div>
              <div>班次：<span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${adjustTarget.shift === 'DAY' ? 'bg-blue-500/10 text-blue-500' : 'bg-purple-500/10 text-purple-500'}`}>{adjustTarget.shift === 'DAY' ? '白班' : '晚班'}</span></div>
              <div className="mt-1">原值班人：{adjustTarget.shift === 'DAY' ? (adjustTarget.record.day_member?.name || '待分配') : (adjustTarget.record.night_member?.name || '待分配')}</div>
              {(adjustTarget.shift === 'DAY' ? adjustTarget.record.day_needs_adjust : adjustTarget.record.night_needs_adjust) && (
                <div className="mt-1 flex items-center gap-1 text-xs text-amber-500"><AlertTriangle className="h-3.5 w-3.5" />该值班人已请假，建议替换</div>
              )}
            </div>
            <div>
              <div className="flex items-center justify-between">
                <label className={labelCls}>替换为</label>
                <button
                  onClick={() => {
                    // 一键替换：挑选同类别中第一个非当前人员
                    const cur = adjustTarget.shift === 'DAY' ? adjustTarget.record.day_member : adjustTarget.record.night_member
                    const cat = adjustTarget.shift === 'DAY' ? 'DAY' : 'NIGHT'
                    const candidates = members.filter((m) => m.duty_category === cat && (!cur || m.id !== cur.id))
                    if (candidates.length === 0) return toast.warning('没有可替换的同类别人员')
                    setAdjustMemberId(String(candidates[0].id))
                  }}
                  className="flex items-center gap-1 text-xs text-primary hover:underline"
                  title="自动挑选同类别下一个可用人员"
                >
                  <Zap className="h-3.5 w-3.5" />一键替换
                </button>
              </div>
              <select className={inputCls} value={adjustMemberId} onChange={(e) => setAdjustMemberId(e.target.value)}>
                <option value="">（待分配）</option>
                {members.map((m) => <option key={m.id} value={m.id}>{m.name}（{m.group_name || '未分组'}）-{m.phone}</option>)}
              </select>
              <p className="mt-1 text-[11px] text-muted-foreground/70">调整周末/节假日白班或晚班会重锚定对应轮换顺序，并自动按新顺序接排后续草稿排班（白班仅非工作日，晚班为所有日期）；已发布/已过期记录不受影响。</p>
            </div>
            <div>
              <label className={labelCls}>调整原因</label>
              <textarea className={`${inputCls} resize-y`} rows={3} placeholder="请假 / 调换 / 其他" value={adjustReason} onChange={(e) => setAdjustReason(e.target.value)} />
            </div>
          </div>
        )}
      </HalfDrawer>

      {/* 特殊日期抽屉 */}
      <HalfDrawer
        open={specialOpen}
        onClose={() => setSpecialOpen(false)}
        title="特殊日期管理"
        footer={<div className="flex justify-end"><Button variant="secondary" size="sm" onClick={() => setSpecialOpen(false)}>关闭</Button></div>}
      >
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">手动标记某日为非工作日（holiday）或工作日/调休上班（workday），覆盖内置节假日表。用于内置数据缺失或临时调休。</p>
          <div className="rounded-md border border-border p-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={labelCls}>日期</label>
                <input type="date" className={inputCls} value={specialForm.date} onChange={(e) => setSpecialForm({ ...specialForm, date: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>类型</label>
                <select className={inputCls} value={specialForm.day_type} onChange={(e) => setSpecialForm({ ...specialForm, day_type: e.target.value })}>
                  <option value="holiday">非工作日（放假）</option>
                  <option value="workday">工作日（调休上班）</option>
                </select>
              </div>
            </div>
            <Button className="mt-2" variant="primary" size="sm" onClick={handleAddSpecial}>添加</Button>
          </div>
          <div>
            <div className="mb-2 text-xs font-medium text-muted-foreground">已标记的特殊日期</div>
            {specialLoading ? (
              <div className="text-sm text-muted-foreground">加载中...</div>
            ) : specialList.length === 0 ? (
              <EmptyState title="暂无特殊日期" />
            ) : (
              <div className="max-h-64 space-y-1 overflow-y-auto">
                {specialList.map((s) => (
                  <div key={s.date} className="flex items-center justify-between rounded border border-border/60 px-3 py-1.5 text-sm">
                    <span className="tabular-nums">{s.date}</span>
                    <Badge variant={s.day_type === 'holiday' ? 'info' : 'success'}>{s.day_type === 'holiday' ? '非工作日' : '工作日'}</Badge>
                    <button onClick={() => handleDeleteSpecial(s.date)} className="text-xs text-destructive hover:underline">删除</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </HalfDrawer>
    </PageContainer>
  )
}

// 班次单元（列表视图）：左侧4px色条 + 姓名14px + 电话12px分行，请假角标
function ShiftCell({ member, shift, needsAdjust, showPhone, onClick, canEdit }) {
  const stripeCls = shift === 'DAY' ? 'border-l-4 border-l-blue-500' : 'border-l-4 border-l-purple-500'
  if (!member) {
    return (
      <button onClick={onClick} disabled={!canEdit}
        className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left ${stripeCls} ${canEdit ? 'cursor-pointer border border-dashed border-amber-500/40 text-amber-500 hover:bg-amber-500/5' : 'text-amber-500'}`}
        title={`${shift === 'DAY' ? '白班' : '晚班'}：待分配`}
      >
        <span className="text-sm">--</span>
      </button>
    )
  }
  return (
    <button onClick={onClick} disabled={!canEdit}
      className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left ${stripeCls} ${needsAdjust ? 'bg-amber-500/5' : ''} ${canEdit ? 'cursor-pointer hover:bg-accent/40' : 'cursor-default'}`}
      title={`${shift === 'DAY' ? '白班' : '晚班'}：${member.name} ${member.phone}${needsAdjust ? '（该人员请假，需替换）' : ''}`}>
      <span className="flex flex-col min-w-0">
        <span className="flex items-center gap-1">
          <span className="truncate text-sm font-medium text-foreground">{member.name}</span>
          {needsAdjust && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" title="请假，需替换" />}
        </span>
        {showPhone && <span className="truncate text-xs text-muted-foreground">{member.phone}</span>}
      </span>
    </button>
  )
}

// 班次迷你单元（月视图）：蓝/紫小点 + 姓名13px，未分配显示"--"
function ShiftMini({ member, shift, needsAdjust, onClick, canEdit }) {
  const dotCls = needsAdjust ? 'bg-amber-500' : (shift === '白班' ? 'bg-blue-500' : 'bg-purple-500')
  return (
    <button onClick={onClick} disabled={!canEdit}
      className={`flex items-center gap-1 truncate rounded px-0.5 py-0.5 text-left ${canEdit ? 'cursor-pointer hover:bg-accent/50' : 'cursor-default'}`}
      title={member ? `${shift}：${member.name} ${member.phone}${needsAdjust ? '（请假，需替换）' : ''}` : `${shift}：--`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotCls}`} />
      <span className={`truncate ${member ? (needsAdjust ? 'text-amber-500' : 'text-foreground') : 'text-muted-foreground/50'}`} style={{ fontSize: '13px' }}>
        {member ? member.name : '--'}
      </span>
    </button>
  )
}
