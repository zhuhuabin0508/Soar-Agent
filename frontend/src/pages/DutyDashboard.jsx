// 值班监控大屏：全屏暗色主题，实时展示当前班次、异常提醒、近7天排班与月度排班
import { useState, useEffect, useRef, useCallback } from 'react'
import { Maximize2, Minimize2, RefreshCw, AlertTriangle, CalendarDays, Sun, Moon, Phone, Clock, Users, ChevronLeft, ChevronRight, LayoutDashboard, Cpu, Package } from 'lucide-react'
import dutyApi from '../api/duty'

const WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const MONTH_CN = ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月']

// 主题色
const C = {
  day: '#3B82F6',
  night: '#8B5CF6',
  pending: '#EF4444',
  leave: '#F59E0B',
  adjust: '#EAB308',
  normal: '#10B981',
}

// 判断周末（周六/周日）
function isWeekendDay(dateStr) {
  const d = new Date(dateStr + 'T00:00:00')
  const w = d.getDay()
  return w === 0 || w === 6
}

// 节假日/周末背景色
function dayBgStyle(day) {
  if (!day) return {}
  if (day.is_holiday) return { background: 'rgba(139,92,246,0.12)', borderColor: 'rgba(139,92,246,0.35)' }
  if (isWeekendDay(day.duty_date)) return { background: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.25)' }
  return {}
}

// 日期数字颜色
function dateColor(day) {
  if (!day) return '#94A3B8'
  if (day.is_holiday) return '#A78BFA'
  if (isWeekendDay(day.duty_date)) return '#FBBF24'
  return '#E2E8F0'
}

function fmtMember(m) {
  if (!m) return '--'
  return m.name || '--'
}

function memberPhone(m) {
  if (!m) return null
  return m.phone || m.contact || null
}

export default function DutyDashboard({ onSwitchTab }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [now, setNow] = useState(new Date())
  const [fullscreen, setFullscreen] = useState(false)
  const [monthData, setMonthData] = useState({ days: [] })
  const [monthCursor, setMonthCursor] = useState(() => {
    const d = new Date()
    return { year: d.getFullYear(), month: d.getMonth() + 1 }
  })
  const containerRef = useRef(null)

  // 加载大屏数据
  const loadData = useCallback(async () => {
    try {
      const res = await dutyApi.dashboard()
      setData(res)
    } catch (e) {
      console.error('加载值班大屏数据失败:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  // 加载月度排班
  const loadMonth = useCallback(async (year, month) => {
    try {
      const res = await dutyApi.monthSchedule(year, month)
      setMonthData(res || { days: [] })
    } catch (e) {
      console.error('加载月度排班失败:', e)
    }
  }, [])

  // 初始加载 + 60s 自动刷新
  useEffect(() => {
    loadData()
    const timer = setInterval(loadData, 60000)
    return () => clearInterval(timer)
  }, [loadData])

  // 时钟 1s 刷新
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  // 月度排班加载
  useEffect(() => {
    loadMonth(monthCursor.year, monthCursor.month)
  }, [monthCursor, loadMonth])

  // 全屏切换
  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen?.()
      setFullscreen(true)
    } else {
      document.exitFullscreen?.()
      setFullscreen(false)
    }
  }, [])

  useEffect(() => {
    const onFsChange = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFsChange)
    const onEsc = (e) => { if (e.key === 'Escape' && fullscreen) document.exitFullscreen?.() }
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('fullscreenchange', onFsChange)
      document.removeEventListener('keydown', onEsc)
    }
  }, [fullscreen])

  // 倒计时到班次结束
  const countdown = (() => {
    if (!data) return '--'
    const h = now.getHours()
    const m = now.getMinutes()
    const s = now.getSeconds()
    if (data.current_shift === 'DAY') {
      // 白班结束 18:00
      const endH = 18
      let dh = endH - 1 - h
      let dm = 59 - m
      let ds = 60 - s
      if (ds === 60) { ds = 0; dm++ }
      if (dm === 60) { dm = 0; dh++ }
      if (dh < 0) return '已结束'
      return `${String(dh).padStart(2, '0')}:${String(dm).padStart(2, '0')}:${String(ds).padStart(2, '0')}`
    } else {
      // 晚班结束 次日09:00
      let dh = 8 - h
      let dm = 59 - m
      let ds = 60 - s
      if (ds === 60) { ds = 0; dm++ }
      if (dm === 60) { dm = 0; dh++ }
      if (dh < 0) dh += 24
      return `${String(dh).padStart(2, '0')}:${String(dm).padStart(2, '0')}:${String(ds).padStart(2, '0')}`
    }
  })()

  const shiftTitle = data?.current_shift === 'DAY' ? '白班' : '晚班'
  const shiftColor = data?.current_shift === 'DAY' ? C.day : C.night
  const curMember = data?.current_member
  const backupMember = data?.backup_member
  const todayRec = data?.today_record
  const upcoming7 = data?.upcoming_7days || []
  const anomalies = data?.anomalies || {}

  // 月历网格
  const monthGrid = (() => {
    const days = monthData.days || []
    if (days.length === 0) return []
    const first = new Date(monthCursor.year, monthCursor.month - 1, 1)
    // 周一为第一天：偏移
    let offset = first.getDay() - 1
    if (offset < 0) offset = 6
    const cells = new Array(offset).fill(null)
    days.forEach((d) => cells.push(d))
    while (cells.length % 7 !== 0) cells.push(null)
    const weeks = []
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7))
    return weeks
  })()

  const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
  const weekdayStr = WEEKDAY_CN[(now.getDay() + 6) % 7]

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-[200] flex flex-col"
      style={{ background: 'linear-gradient(135deg, #0B1120 0%, #1E293B 100%)', color: '#E2E8F0' }}
    >
      {/* ===== 顶部栏 96px ===== */}
      <header className="flex h-24 shrink-0 items-center justify-between px-8" style={{ borderBottom: '1px solid rgba(148,163,184,0.12)' }}>
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl" style={{ background: 'rgba(59,130,246,0.15)' }}>
            <CalendarDays className="h-6 w-6" style={{ color: shiftColor }} />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-wide text-white">值班监控大屏</h1>
            <p className="text-sm text-slate-400">{dateStr} {weekdayStr}</p>
          </div>
          {/* 大屏切换 */}
          {onSwitchTab && (
            <div className="ml-4 flex items-center gap-1 rounded-lg p-0.5" style={{ background: 'rgba(148,163,184,0.08)' }}>
              <button
                type="button"
                onClick={() => onSwitchTab('operations')}
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-white"
                title="运营大屏"
              >
                <LayoutDashboard className="h-3.5 w-3.5" />
                运营
              </button>
              <button
                type="button"
                onClick={() => onSwitchTab('ai_usage')}
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-white"
                title="AI 用量大屏"
              >
                <Cpu className="h-3.5 w-3.5" />
                AI用量
              </button>
              <button
                type="button"
                onClick={() => onSwitchTab('materials')}
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-white"
                title="材料管理大屏"
              >
                <Package className="h-3.5 w-3.5" />
                材料
              </button>
              <button
                type="button"
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-white"
                style={{ background: 'rgba(59,130,246,0.25)' }}
                title="值班大屏（当前）"
              >
                <CalendarDays className="h-3.5 w-3.5" />
                值班
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center gap-6">
          {/* 实时时钟 */}
          <div className="text-right">
            <div className="text-3xl font-bold tabular-nums text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>{timeStr}</div>
          </div>

          {/* 班次状态 */}
          <div className="flex items-center gap-2 rounded-lg px-4 py-2" style={{ background: `${shiftColor}22`, border: `1px solid ${shiftColor}55` }}>
            {data?.current_shift === 'DAY' ? <Sun className="h-5 w-5" style={{ color: shiftColor }} /> : <Moon className="h-5 w-5" style={{ color: shiftColor }} />}
            <span className="text-lg font-semibold" style={{ color: shiftColor }}>{shiftTitle}</span>
          </div>

          {/* 全屏切换 */}
          <button onClick={toggleFullscreen} className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 transition hover:text-white" style={{ background: 'rgba(148,163,184,0.08)' }} title={fullscreen ? '退出全屏' : '全屏'}>
            {fullscreen ? <Minimize2 className="h-5 w-5" /> : <Maximize2 className="h-5 w-5" />}
          </button>

          {/* 手动刷新 */}
          <button onClick={loadData} className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 transition hover:text-white" style={{ background: 'rgba(148,163,184,0.08)' }} title="刷新">
            <RefreshCw className={`h-5 w-5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </header>

      {/* ===== 主区域 ===== */}
      <div className="flex flex-1 min-h-0">
        {/* 左侧 30%：上 2/3 当前值班卡片 + 下 1/3 异常提醒 */}
        <div className="flex w-[30%] shrink-0 flex-col px-6 py-4" style={{ borderRight: '1px solid rgba(148,163,184,0.12)' }}>
          {/* 上 2/3：当前值班 */}
          <div className="flex flex-1 flex-col items-center justify-center">
            {/* 呼吸灯 */}
            <div className="relative mb-3">
              <div className="absolute inset-0 animate-ping rounded-full" style={{ background: `${shiftColor}33`, animationDuration: '2s' }} />
              <div className="relative flex h-14 w-14 items-center justify-center rounded-full" style={{ background: `${shiftColor}22`, border: `2px solid ${shiftColor}` }}>
                {data?.current_shift === 'DAY' ? <Sun className="h-7 w-7" style={{ color: shiftColor }} /> : <Moon className="h-7 w-7" style={{ color: shiftColor }} />}
              </div>
            </div>

            {/* 班次标题 */}
            <div className="mb-1.5 text-xs text-slate-400">当前班次</div>
            <div className="mb-4" style={{ fontSize: 48, fontWeight: 700, color: shiftColor, lineHeight: 1 }}>{shiftTitle}</div>

            {/* 值班人姓名 */}
            {curMember ? (
              <>
                <div className="mb-1.5 text-xs text-slate-400">值班人员</div>
                <div className="mb-3 text-center" style={{ fontSize: 60, fontWeight: 700, color: '#F8FAFC', lineHeight: 1.1 }}>{curMember.name}</div>
                {curMember.duty_category === 'PERMANENT_DAY' && (
                  <div className="mb-3 rounded px-3 py-0.5 text-xs" style={{ background: 'rgba(16,185,129,0.12)', color: C.normal }}>长期白班</div>
                )}
                {memberPhone(curMember) && (
                  <div className="mb-4 flex items-center gap-2" style={{ fontSize: 28, fontWeight: 500, color: '#CBD5E1' }}>
                    <Phone className="h-5 w-5 text-slate-500" />
                    {memberPhone(curMember)}
                  </div>
                )}
              </>
            ) : (
              <div className="mb-4 text-xl text-slate-500">暂未排班</div>
            )}

            {/* 倒计时 */}
            <div className="mb-1.5 text-xs text-slate-400">距离下班</div>
            <div className="tabular-nums mb-3" style={{ fontSize: 28, fontWeight: 700, color: '#F1F5F9', fontVariantNumeric: 'tabular-nums' }}>{countdown}</div>

            {/* 备班 */}
            {backupMember && (
              <div className="rounded-lg px-3 py-2" style={{ background: 'rgba(148,163,184,0.06)', border: '1px solid rgba(148,163,184,0.15)' }}>
                <div className="mb-0.5 text-[10px] text-slate-400">备班人员</div>
                <div className="flex items-center gap-2">
                  <Users className="h-3.5 w-3.5 text-slate-400" />
                  <span className="text-base font-semibold text-slate-200">{backupMember.name}</span>
                </div>
              </div>
            )}
          </div>

          {/* 下 1/3：异常提醒 */}
          <div className="shrink-0 rounded-lg p-3" style={{ background: 'rgba(148,163,184,0.05)', border: '1px solid rgba(148,163,184,0.12)', maxHeight: '33%' }}>
            <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-200">
              <AlertTriangle className="h-3.5 w-3.5" style={{ color: data?.has_anomaly ? C.pending : C.normal }} />
              异常提醒
            </h2>
            <div className="space-y-1 overflow-y-auto" style={{ maxHeight: 'calc(33vh - 80px)' }}>
              {/* 待分配 */}
              {(anomalies.pending || []).length > 0 && (
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="font-medium" style={{ color: C.pending }}>待分配</span>
                  <span className="text-slate-400">{anomalies.pending.length} 项</span>
                </div>
              )}
              {/* 请假 */}
              {(anomalies.leaves || []).length > 0 && (
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="font-medium" style={{ color: C.leave }}>请假</span>
                  <span className="text-slate-400">{anomalies.leaves.map(l => l.member_name).join('、')}</span>
                </div>
              )}
              {/* 调班记录详情 */}
              {(anomalies.adjustments || []).length > 0 && (
                <div>
                  <div className="mb-0.5 text-[11px] font-medium" style={{ color: C.adjust }}>调班记录 ({anomalies.adjustments.length})</div>
                  {anomalies.adjustments.slice(0, 6).map((a, i) => (
                    <div key={i} className="flex items-center gap-1 text-[11px] text-slate-400">
                      <span className="whitespace-nowrap">{a.duty_date?.slice(5)}</span>
                      <span className="truncate">{a.original_member_name}</span>
                      <span style={{ color: C.adjust }}>→</span>
                      <span className="truncate">{a.new_member_name}</span>
                      <span className="whitespace-nowrap" style={{ color: a.shift === '白班' ? C.day : C.night }}>{a.shift}</span>
                    </div>
                  ))}
                </div>
              )}
              {/* 交班 */}
              {anomalies.upcoming_handover && (
                <div className="flex items-center gap-2 text-[11px]">
                  <Clock className="h-3 w-3 text-slate-400" />
                  <span className="text-slate-400">交班 {anomalies.upcoming_handover.time} → {anomalies.upcoming_handover.next_shift === 'DAY' ? '白班' : '晚班'}</span>
                </div>
              )}
              {/* 无异常 */}
              {!data?.has_anomaly && (anomalies.pending || []).length === 0 && (anomalies.leaves || []).length === 0 && (
                <div className="flex items-center gap-2 text-[11px]" style={{ color: C.normal }}>
                  <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: C.normal }} /> 一切正常
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 右侧 70%：7天排班 + 月历 */}
        <div className="flex-1 min-w-0 overflow-y-auto p-6 space-y-5">

          {/* ===== 近7天排班 ===== */}
          <section>
            <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-slate-200">
              <CalendarDays className="h-4 w-4" style={{ color: shiftColor }} />
              近 7 天排班
            </h2>
            <div className="grid grid-cols-7 gap-2">
              {upcoming7.map((d, i) => {
                const bg = dayBgStyle(d)
                const isWk = d ? isWeekendDay(d.duty_date) : false
                return (
                  <div
                    key={i}
                    className="rounded-lg p-2.5"
                    style={{
                      background: bg.background || 'rgba(148,163,184,0.05)',
                      border: `1px solid ${bg.borderColor || 'rgba(148,163,184,0.1)'}`,
                      ...(d?.is_today ? { boxShadow: `0 0 0 2px ${shiftColor}44` } : {}),
                    }}
                    title={d?.holiday_name || ''}
                  >
                    {/* 日期行 */}
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-sm font-semibold" style={{ color: dateColor(d) }}>
                        {d ? Number(d.duty_date.slice(8)) : '--'}
                      </span>
                      <span className="text-[10px]" style={{ color: dateColor(d) }}>
                        {d?.weekday || ''}
                      </span>
                    </div>

                    {/* 节假/休息标记 */}
                    {d?.is_holiday && (
                      <div className="mb-1.5 text-[10px] font-medium" style={{ color: '#A78BFA' }}>
                        {d.holiday_name || '休'}
                      </div>
                    )}
                    {!d?.is_holiday && isWk && (
                      <div className="mb-1.5 text-[10px] font-medium" style={{ color: '#FBBF24' }}>周末</div>
                    )}

                    {/* 白班 */}
                    <div className="mb-1 flex items-center gap-1.5 rounded px-1.5 py-1" style={{ background: 'rgba(59,130,246,0.10)' }}>
                      <Sun className="h-3 w-3 shrink-0" style={{ color: C.day }} />
                      <span className="truncate text-xs text-slate-300">{fmtMember(d?.day_member)}</span>
                    </div>

                    {/* 晚班 */}
                    <div className="flex items-center gap-1.5 rounded px-1.5 py-1" style={{ background: 'rgba(139,92,246,0.10)' }}>
                      <Moon className="h-3 w-3 shrink-0" style={{ color: C.night }} />
                      <span className="truncate text-xs text-slate-300">{fmtMember(d?.night_member)}</span>
                    </div>

                    {/* 需调整标记 */}
                    {(d?.day_needs_adjust || d?.night_needs_adjust) && (
                      <div className="mt-1 flex items-center gap-1 text-[10px]" style={{ color: C.adjust }}>
                        <AlertTriangle className="h-2.5 w-2.5" /> 需调整
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </section>

          {/* ===== 月度排班日历 ===== */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-base font-semibold text-slate-200">
                <CalendarDays className="h-4 w-4 text-slate-400" />
                {monthCursor.year} 年 {MONTH_CN[monthCursor.month - 1]} 排班
              </h2>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setMonthCursor((p) => {
                    let y = p.year, m = p.month - 1
                    if (m < 1) { m = 12; y-- }
                    return { year: y, month: m }
                  })}
                  className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:text-white"
                  style={{ background: 'rgba(148,163,184,0.08)' }}
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setMonthCursor(() => { const d = new Date(); return { year: d.getFullYear(), month: d.getMonth() + 1 } })}
                  className="rounded px-2 py-1 text-xs text-slate-400 hover:text-white"
                  style={{ background: 'rgba(148,163,184,0.08)' }}
                >
                  本月
                </button>
                <button
                  onClick={() => setMonthCursor((p) => {
                    let y = p.year, m = p.month + 1
                    if (m > 12) { m = 1; y++ }
                    return { year: y, month: m }
                  })}
                  className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:text-white"
                  style={{ background: 'rgba(148,163,184,0.08)' }}
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="overflow-hidden rounded-lg" style={{ border: '1px solid rgba(148,163,184,0.12)' }}>
              <table className="w-full border-collapse">
                <thead>
                  <tr style={{ background: 'rgba(148,163,184,0.06)' }}>
                    {WEEKDAY_CN.map((w, i) => (
                      <th key={w} className="px-1.5 py-2 text-center text-xs font-semibold" style={{ color: i >= 5 ? '#FBBF24' : '#94A3B8' }}>{w}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {monthGrid.map((week, wi) => (
                    <tr key={wi}>
                      {week.map((d, di) => {
                        const bg = dayBgStyle(d)
                        const isWk = d ? isWeekendDay(d.duty_date) : false
                        return (
                          <td
                            key={di}
                            className="align-top p-1.5"
                            style={{
                              height: 64,
                              minWidth: 70,
                              background: bg.background || 'transparent',
                              borderTop: '1px solid rgba(148,163,184,0.08)',
                              borderLeft: di > 0 ? '1px solid rgba(148,163,184,0.08)' : 'none',
                              ...(d?.is_today ? { boxShadow: 'inset 0 0 0 2px rgba(59,130,246,0.4)' } : {}),
                            }}
                            title={d?.holiday_name || ''}
                          >
                            {d && (
                              <div className="flex h-full flex-col gap-0.5">
                                <div className="flex items-center justify-between">
                                  <span className="text-xs font-bold" style={{ color: dateColor(d) }}>
                                    {Number(d.duty_date.slice(8))}
                                  </span>
                                  <span className="text-[9px]" style={{ color: d.is_holiday ? '#A78BFA' : isWk ? '#FBBF24' : '#64748B' }}>
                                    {d.is_holiday ? '休' : isWk ? '休' : '班'}
                                  </span>
                                </div>
                                {d.holiday_name && (
                                  <div className="truncate text-[9px]" style={{ color: '#A78BFA' }} title={d.holiday_name}>{d.holiday_name}</div>
                                )}
                                <div className="flex items-center gap-0.5 text-[10px]">
                                  <Sun className="h-2.5 w-2.5 shrink-0" style={{ color: C.day }} />
                                  <span className="truncate text-slate-400">{fmtMember(d.day_member)}</span>
                                </div>
                                <div className="flex items-center gap-0.5 text-[10px]">
                                  <Moon className="h-2.5 w-2.5 shrink-0" style={{ color: C.night }} />
                                  <span className="truncate text-slate-400">{fmtMember(d.night_member)}</span>
                                </div>
                              </div>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* 图例 */}
            <div className="mt-2 flex items-center gap-4 text-[11px] text-slate-500">
              <span className="flex items-center gap-1">
                <span className="inline-block h-3 w-3 rounded" style={{ background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.35)' }} /> 节假日
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block h-3 w-3 rounded" style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)' }} /> 周末
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block h-3 w-3 rounded" style={{ background: 'rgba(148,163,184,0.05)', border: '1px solid rgba(148,163,184,0.10)' }} /> 工作日
              </span>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
