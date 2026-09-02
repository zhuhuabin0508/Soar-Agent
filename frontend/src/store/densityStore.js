// 数据密度全局状态：compact / standard / comfortable
//
// 影响所有 DataTable 的行高、内边距、字号
// - compact:     紧凑(行高 32px,适合大量数据快速浏览)
// - standard:    标准(行高 44px,默认)
// - comfortable: 宽松(行高 56px,适合大屏 / 触控 / 老花眼)
//
// 持久化到 localStorage,跨页面 / 跨刷新保持
// 在 DataTable 顶部用 DensitySwitcher 切换
import { create } from 'zustand'

const STORAGE_KEY = 'soar_density'
const VALID = ['compact', 'standard', 'comfortable']

function readInitial() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && VALID.includes(saved)) return saved
  } catch { /* ignore */ }
  return 'standard'
}

// 不同密度对应的 Tailwind 类
// - 行高 / 单元格垂直内边距(py) / 字号(text)
export const DENSITY_CLASS = {
  compact: {
    cell: 'py-1.5 text-xs',
    header: 'py-2 text-xs',
    rowHeight: 'h-8',
  },
  standard: {
    cell: 'py-2.5 text-sm',
    header: 'py-3 text-xs',
    rowHeight: 'h-11',
  },
  comfortable: {
    cell: 'py-4 text-sm',
    header: 'py-4 text-sm',
    rowHeight: 'h-14',
  },
}

export const useDensityStore = create((set, get) => ({
  density: readInitial(),
  setDensity: (d) => {
    if (!VALID.includes(d)) return
    try { localStorage.setItem(STORAGE_KEY, d) } catch { /* ignore */ }
    set({ density: d })
  },
  cycle: () => {
    const cur = get().density
    const next = cur === 'standard' ? 'compact' : cur === 'compact' ? 'comfortable' : 'standard'
    get().setDensity(next)
  },
}))

export const setDensity = (d) => useDensityStore.getState().setDensity(d)

export default useDensityStore
