// 统一列表筛选栏：搜索 + 自定义字段筛选 + 右侧操作区
// 配合 DataTable + Pagination + BatchActions 构成第三批「数据管理」列表基线。
//
// 用法：
//   <FilterBar
//     search={{ value, onChange, placeholder }}
//     filters={[{ key, label, value, onChange, options:[{value,label}] }]}
//     actions={<Button>新建</Button>}
//   />
import { Search, X } from 'lucide-react'
import { inputCls } from './property/FormControls'

export function FilterBar({ search, filters = [], actions, className = '' }) {
  const hasSearch = !!search
  const hasFilters = filters.length > 0
  return (
    <div className={`mb-4 flex flex-wrap items-center gap-3 ${className}`}>
      {hasSearch && (
        <div className="relative min-w-[200px] flex-1" style={{ maxWidth: '320px' }}>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            className={`${inputCls} pl-8 pr-8`}
            placeholder={search.placeholder || '搜索...'}
            value={search.value}
            onChange={(e) => search.onChange(e.target.value)}
            data-hotkey="search"
          />
          {search.value && (
            <button
              type="button"
              onClick={() => search.onChange('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground transition hover:text-foreground"
              aria-label="清除搜索"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}
      {hasFilters &&
        filters.map((f) => (
          <label key={f.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {f.label && <span className="whitespace-nowrap">{f.label}</span>}
            <select
              className="rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground outline-none focus:border-primary"
              value={f.value}
              onChange={(e) => f.onChange(e.target.value)}
            >
              {f.options.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        ))}
      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export default FilterBar
