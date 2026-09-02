// 筛选条件持久化 Hook：把搜索关键字 / 字段筛选值存到 localStorage
// 下次进入同一页面时自动恢复,避免反复重新筛选。
//
// 用法:
//   const [filters, setFilters, resetFilters] = usePersistedFilters(
//     'llm_config_filters',   // storage key 唯一标识(建议用页面名)
//     { search: '', provider: '', status: '' },  // 初始值
//   )
//   // search 改变时:setFilters({ ...filters, search: v })
//   // 重置按钮:resetFilters()
//
// 设计:
// - 初始化时从 localStorage 读,反序列化为对象;失败则用 initialValues
// - setFilters 同时更新 state 和 localStorage(防抖不必要,filter 变化频率低)
// - 存储空间限制:单 key 上限 5KB,超时静默放弃写入(避免报错)
// - 选项兼容:存对象 stringify,读 parse 后再合并 initialValues(保证新增字段有默认值)
import { useState, useCallback, useEffect } from 'react'

const PREFIX = 'soar_filters_'  // 统一前缀,便于后续清理或迁移
const MAX_SIZE = 5120            // 5KB 上限

// 读取持久化的筛选
function readFilters(key, initialValues) {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (!raw) return initialValues
    const parsed = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return initialValues
    // 合并:用 initialValues 作为基线,保证新增字段有默认值
    return { ...initialValues, ...parsed }
  } catch {
    return initialValues
  }
}

// 写入:超 size 上限放弃写入(避免 QUOTA_EXCEEDED 报错)
function writeFilters(key, value) {
  try {
    const s = JSON.stringify(value)
    if (s.length > MAX_SIZE) return
    localStorage.setItem(PREFIX + key, s)
  } catch {
    // localStorage 不可用或配额超限,静默
  }
}

export function usePersistedFilters(key, initialValues = {}) {
  const [filters, setFiltersState] = useState(() => readFilters(key, initialValues))

  // 更新:合并 patch 或替换整个值
  const setFilters = useCallback((patch) => {
    setFiltersState((prev) => {
      const next = typeof patch === 'function'
        ? patch(prev)
        : { ...prev, ...patch }
      writeFilters(key, next)
      return next
    })
  }, [key])

  // 重置:回到 initialValues 并清除 localStorage
  const resetFilters = useCallback(() => {
    writeFilters(key, initialValues)
    setFiltersState(initialValues)
  }, [key, initialValues])

  // initialValues 变化时合并新字段(保持已持久化的值)
  useEffect(() => {
    setFiltersState((prev) => ({ ...initialValues, ...prev }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initialValues)])

  return [filters, setFilters, resetFilters]
}

export default usePersistedFilters
