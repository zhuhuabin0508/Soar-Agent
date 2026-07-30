import { useEffect, useState, useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import { getDashboardStats } from '../api/dashboard'

// KPI 卡片
function KpiCard({ label, value, suffix, accent }) {
  return (
    <div className="min-w-0 flex-1 rounded-xl border border-gray-800 bg-gradient-to-br from-gray-900 to-gray-900/40 p-5 shadow-lg">
      <div className="text-xs text-gray-400">{label}</div>
      <div className="mt-2 flex items-baseline gap-1">
        <span
          className={`bg-clip-text text-3xl font-bold text-transparent ${accent || 'bg-gradient-to-r from-brand-300 to-brand-500'}`}
        >
          {value}
        </span>
        {suffix && <span className="text-sm text-gray-400">{suffix}</span>}
      </div>
    </div>
  )
}

// 运营大屏页：深色科技风
function Dashboard() {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  // 每 30 秒轮询
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await getDashboardStats()
        if (!alive) return
        setStats(data)
        setError('')
      } catch (err) {
        if (!alive) return
        setError(err.message || '加载失败')
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    const timer = setInterval(load, 30000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  const kpi = stats?.kpi || {}
  const trend7d = stats?.trend_7d || []
  const alertCategories = stats?.alert_categories || []
  const topIps = stats?.top_malicious_ips || []

  // 折线图配置：近 7 天自动化处置 vs 人工介入趋势
  const trendOption = useMemo(() => {
    return {
      backgroundColor: 'transparent',
      color: ['#22d3ee', '#f59e0b'],
      tooltip: { trigger: 'axis' },
      legend: {
        data: ['自动化处置', '人工介入'],
        textStyle: { color: '#9ca3af' },
        top: 0,
      },
      grid: { left: 40, right: 24, top: 40, bottom: 32, containLabel: true },
      xAxis: {
        type: 'category',
        data: trend7d.map((d) => d.date),
        axisLine: { lineStyle: { color: '#4b5563' } },
        axisLabel: { color: '#9ca3af' },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#1f2937' } },
        axisLabel: { color: '#9ca3af' },
      },
      series: [
        {
          name: '自动化处置',
          type: 'line',
          smooth: true,
          areaStyle: { opacity: 0.2 },
          data: trend7d.map((d) => d.auto_count),
        },
        {
          name: '人工介入',
          type: 'line',
          smooth: true,
          areaStyle: { opacity: 0.2 },
          data: trend7d.map((d) => d.manual_count),
        },
      ],
    }
  }, [trend7d])

  // 环形图配置：安全告警分类占比
  const categoryOption = useMemo(() => {
    return {
      backgroundColor: 'transparent',
      color: ['#22d3ee', '#3b82f6', '#a855f7', '#ec4899', '#f59e0b', '#10b981', '#ef4444', '#6366f1'],
      tooltip: { trigger: 'item' },
      legend: {
        type: 'scroll',
        orient: 'vertical',
        right: 8,
        top: 'center',
        textStyle: { color: '#9ca3af' },
      },
      series: [
        {
          name: '告警分类',
          type: 'pie',
          radius: ['42%', '68%'],
          center: ['40%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: '#0b1020', borderWidth: 2 },
          label: { color: '#d1d5db' },
          data: alertCategories.map((c) => ({ name: c.name, value: c.value })),
        },
      ],
    }
  }, [alertCategories])

  // 柱状图配置：Top 10 恶意攻击源 IP
  const topIpOption = useMemo(() => {
    const top10 = topIps.slice(0, 10)
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 40, right: 24, top: 20, bottom: 32, containLabel: true },
      xAxis: {
        type: 'category',
        data: top10.map((d) => d.ip),
        axisLine: { lineStyle: { color: '#4b5563' } },
        axisLabel: { color: '#9ca3af', rotate: 20 },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#1f2937' } },
        axisLabel: { color: '#9ca3af' },
      },
      series: [
        {
          name: '攻击次数',
          type: 'bar',
          barWidth: '50%',
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: '#22d3ee' },
                { offset: 1, color: '#3b82f6' },
              ],
            },
          },
          data: top10.map((d) => d.count),
        },
      ],
    }
  }, [topIps])

  const successRate =
    kpi.auto_block_success_rate != null
      ? `${Math.round(kpi.auto_block_success_rate * 100)}`
      : '-'

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      {/* 顶部标题栏 */}
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">运营大屏</h1>
          <span className="text-xs text-gray-500">每 30 秒自动刷新</span>
        </div>
        <div className="text-xs text-gray-500">
          {new Date().toLocaleString('zh-CN', { hour12: false })}
        </div>
      </header>

      {/* 内容滚动区 */}
      <div className="flex-1 min-w-0 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : (
          <div className="flex w-full flex-col gap-4">
            {/* KPI 卡片：等宽填满横向宽度 */}
            <div className="flex w-full flex-col gap-4 sm:flex-row">
              <KpiCard label="今日接警总数" value={kpi.today_alerts ?? '-'} />
              <KpiCard label="全自动化封禁成功率" value={successRate} suffix="%" />
              <KpiCard
                label="系统平均响应时间"
                value={kpi.mttr_seconds ?? '-'}
                suffix="秒"
                accent="bg-gradient-to-r from-success-300 to-brand-500"
              />
              <KpiCard
                label="待人工处理工单数"
                value={kpi.pending_approvals ?? '-'}
                accent="bg-gradient-to-r from-amber-300 to-pink-500"
              />
            </div>

            {/* 中间：左折线 + 右环形，各占 1/2 */}
            <div className="grid w-full grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="w-full rounded-xl border border-gray-800 bg-gradient-to-br from-gray-900/80 to-gray-950 p-4">
                <div className="mb-2 text-sm font-medium text-gray-300">
                  近 7 天自动化处置 vs 人工介入趋势
                </div>
                <ReactECharts option={trendOption} style={{ height: 320, width: '100%' }} />
              </div>
              <div className="w-full rounded-xl border border-gray-800 bg-gradient-to-br from-gray-900/80 to-gray-950 p-4">
                <div className="mb-2 text-sm font-medium text-gray-300">安全告警分类占比</div>
                <ReactECharts option={categoryOption} style={{ height: 320, width: '100%' }} />
              </div>
            </div>

            {/* 底部：Top 10 恶意攻击源 IP 柱状图 */}
            <div className="w-full rounded-xl border border-gray-800 bg-gradient-to-br from-gray-900/80 to-gray-950 p-4">
              <div className="mb-2 text-sm font-medium text-gray-300">Top 10 恶意攻击源 IP</div>
              <ReactECharts option={topIpOption} style={{ height: 360, width: '100%' }} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default Dashboard
