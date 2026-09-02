// 批量选择 hook：管理选中 rowKey 集合，配合 DataTable 的 selectable 模式
//
// 用法：
//   const { selectedKeys, setSelectedKeys, clear, isSelected, count } = useSelection()
//   <DataTable selectable selectedKeys={selectedKeys} onSelectChange={setSelectedKeys} rowKey="id" />
//   <BatchActions selectedCount={count} onClear={clear} actions={[...]} />
import { useState, useCallback, useMemo } from 'react'

export function useSelection(initial = []) {
  const [selectedKeys, setSelectedKeys] = useState(initial)

  const clear = useCallback(() => setSelectedKeys([]), [])

  const isSelected = useCallback((key) => selectedKeys.includes(key), [selectedKeys])

  const count = selectedKeys.length

  // 批量替换：用于全选整个数据集（不限于当前页）
  const selectAll = useCallback((keys) => setSelectedKeys(keys), [])

  const toggle = useCallback((key, checked) => {
    setSelectedKeys((prev) =>
      checked ? [...new Set([...prev, key])] : prev.filter((k) => k !== key)
    )
  }, [])

  const memo = useMemo(() => ({ selectedKeys, count, clear, isSelected, selectAll, toggle, setSelectedKeys }), [selectedKeys, count, clear, isSelected, selectAll, toggle])

  return memo
}

export default useSelection
