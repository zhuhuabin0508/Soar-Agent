// 批量操作工具栏：列表底部浮动条，显示选中数量 + 批量操作按钮
// 配合 DataTable 的 selectable / selectedKeys / onSelectChange 使用。
//
// 用法：
//   <BatchActions
//     selectedCount={selectedKeys.length}
//     onClear={() => setSelectedKeys([])}
//     actions={[{ key:'delete', label:'批量删除', icon:Trash2, variant:'danger', onClick:handleBatchDelete }]}
//   />
import { X } from 'lucide-react'
import { Button } from './ui'

export function BatchActions({ selectedCount = 0, actions = [], onClear, className = '' }) {
  if (selectedCount === 0) return null
  return (
    <div
      className={`pointer-events-auto fixed bottom-6 left-1/2 z-dropdown flex -translate-x-1/2 items-center gap-4 rounded-lg border border-border bg-card px-4 py-2.5 shadow-2xl ${className}`}
    >
      <div className="flex items-center gap-2 text-sm">
        <span className="flex h-6 min-w-[24px] items-center justify-center rounded-full bg-primary/15 px-2 text-xs font-medium text-primary tabular-nums">
          {selectedCount}
        </span>
        <span className="text-muted-foreground">已选择</span>
        {onClear && (
          <button
            type="button"
            onClick={onClear}
            className="flex items-center gap-1 text-xs text-muted-foreground transition hover:text-foreground"
          >
            <X className="h-3 w-3" />
            清空
          </button>
        )}
      </div>
      <div className="h-5 w-px bg-border" />
      <div className="flex items-center gap-2">
        {actions.map((a) => (
          <Button
            key={a.key}
            size="sm"
            variant={a.variant || 'secondary'}
            loading={!!a.loading}
            disabled={a.disabled}
            onClick={a.onClick}
          >
            {a.icon && <a.icon className="h-3.5 w-3.5" />}
            {a.label}
          </Button>
        ))}
      </div>
    </div>
  )
}

export default BatchActions
