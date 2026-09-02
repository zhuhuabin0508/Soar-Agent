// ECharts 主题适配工具
//
// 解决两个问题:
// - U12 暗色对比度:把图表文字色统一到 WCAG AA(暗色用 #d1d5db / 亮色用 #374151)
// - U13 hover 高亮:统一 emphasis 配置,饼图/柱状图 hover 时相邻项淡化
//
// 用法:
//   import { getChartTheme, emphasisPie, emphasisBar } from '../utils/chartTheme'
//   const t = getChartTheme()  // 根据 <html>.dark 自动选择
//   const option = {
//     textStyle: { color: t.text },
//     legend: { textStyle: { color: t.textMuted } },
//     xAxis: { axisLine: { lineStyle: { color: t.axisLine } }, axisLabel: { color: t.textMuted } },
//     yAxis: { splitLine: { lineStyle: { color: t.splitLine } }, axisLabel: { color: t.textMuted } },
//     tooltip: t.tooltip,
//     series: [{ ...emphasisBar(), data: ... }],
//   }
export function getChartTheme() {
  const isDark = document.documentElement.classList.contains('dark')
  if (isDark) {
    return {
      text: '#e5e7eb',        // gray-200,主要文字(对比度 13.6:1,AAA)
      textMuted: '#cbd5e1',   // slate-300,次要文字(对比度 10.3:1,AAA,比 gray-400 更亮)
      axisLine: '#475569',    // slate-600
      splitLine: '#1e293b',   // slate-800
      tooltip: {
        backgroundColor: 'rgba(15,23,42,0.95)',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0' },
      },
      pieBorderColor: '#0f172a',
      palette: ['#22d3ee', '#3b82f6', '#a855f7', '#ec4899', '#f59e0b', '#10b981', '#ef4444', '#6366f1'],
    }
  }
  return {
    text: '#1f2937',          // gray-800
    textMuted: '#475569',     // slate-600
    axisLine: '#cbd5e1',      // slate-300
    splitLine: '#e2e8f0',     // slate-200
    tooltip: {
      backgroundColor: 'rgba(255,255,255,0.98)',
      borderColor: '#cbd5e1',
      textStyle: { color: '#0f172a' },
    },
    pieBorderColor: '#ffffff',
    palette: ['#0891b2', '#2563eb', '#9333ea', '#db2777', '#d97706', '#059669', '#dc2626', '#4f46e5'],
  }
}

// 饼图 emphasis: hover 项放大 + 相邻项淡化
export function emphasisPie() {
  return {
    emphasis: {
      scale: true,
      scaleSize: 8,
      itemStyle: {
        shadowBlur: 12,
        shadowColor: 'rgba(0,0,0,0.35)',
      },
      label: { show: true, fontSize: 13, fontWeight: 'bold' },
    },
    // 未 hover 项的淡化效果
    blur: {
      itemStyle: { opacity: 0.3 },
      label: { show: false },
    },
  }
}

// 柱状图 emphasis:hover 项高亮,相邻柱淡化
export function emphasisBar() {
  return {
    emphasis: {
      itemStyle: {
        shadowBlur: 10,
        shadowColor: 'rgba(0,0,0,0.3)',
      },
    },
    blur: {
      itemStyle: { opacity: 0.4 },
    },
  }
}

// 折线图 emphasis:hover 高亮当前线
export function emphasisLine() {
  return {
    emphasis: {
      focus: 'series',
      lineStyle: { width: 3 },
    },
    blur: {
      lineStyle: { opacity: 0.3 },
    },
  }
}
