// 前端分页 hook：管理 page/pageSize，并切片出当前页数据
// 适用于数据量不大、不需要后端分页的列表页（工具/技能/用户/角色/LLM 配置等）。
//
// 用法：
//   const { page, pageSize, paged, total, totalPages, setPage, setPageSize, reset } = usePagination(rows, { pageSize: 20 })
//   // 筛选后记得 reset() 回到第 1 页
import { useState, useMemo, useCallback, useEffect } from 'react'

export function usePagination(rows = [], opts = {}) {
  const initialPageSize = opts.pageSize || 20
  const maxPageSize = opts.maxPageSize || 200
  const [page, setPage] = useState(1)
  const [pageSize, setPageSizeState] = useState(initialPageSize)

  const total = rows.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  // 越界保护：数据删减导致当前页超出范围时，自动回退到最后一页
  const safePage = Math.min(Math.max(1, page), totalPages)
  const start = (safePage - 1) * pageSize
  const paged = useMemo(() => rows.slice(start, start + pageSize), [rows, start, pageSize])

  // 当前页超出范围时自动校正（例如删除最后一条后）
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const setPageSize = useCallback((size) => {
    setPageSizeState(Math.min(Math.max(1, size), maxPageSize))
    setPage(1)
  }, [maxPageSize])

  const reset = useCallback(() => setPage(1), [])

  return { page: safePage, pageSize, paged, total, totalPages, setPage, setPageSize, reset }
}

export default usePagination
