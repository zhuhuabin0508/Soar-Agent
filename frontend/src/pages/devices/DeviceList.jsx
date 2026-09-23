// 设备卡片、动作表格、设备列表行
import { ChevronDown, ChevronRight, History, Plus, RefreshCw, TestTube, Wifi } from 'lucide-react'
import {
  DEVICE_TYPE_LABELS,
  fmtRelative,
  fmtTime,
  parseTags,
  successRate,
  truncate,
} from './constants'
import {
  CategoryBadge,
  DeviceTypeIcon,
  MethodBadge,
  RiskBadge,
  StatusBadge,
  Switch,
} from './Badges'

// ============ 设备卡片组件 ============
export function DeviceCard({
  device,
  expanded,
  onToggleExpand,
  onEdit,
  onDelete,
  onTest,
  testing,
  actions,
  loadingActions,
  onEditAction,
  onDeleteAction,
  onTestAction,
  onToggleAction,
  onNewAction,
  onActionHistory,
  togglingActionId,
  checked,
  onToggleCheck,
}) {
  const api_url = device.api_url || ''
  const tags = parseTags(device.tags)

  return (
    <div
      className={`w-full overflow-hidden rounded-lg border transition ${
        expanded
          ? 'border-primary bg-primary/5'
          : 'border-border bg-card/40 hover:border-primary/50'
      }`}
    >
      {/* 设备行 */}
      <div
        className="flex cursor-pointer items-center gap-3 p-4"
        onClick={() => onToggleExpand(device)}
      >
        {typeof checked === 'boolean' && (
          <input
            type="checkbox"
            className="h-4 w-4 shrink-0 accent-primary"
            checked={checked}
            onClick={(e) => e.stopPropagation()}
            onChange={() => onToggleCheck?.(device)}
            title="勾选以导出"
          />
        )}
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary">
          <DeviceTypeIcon type={device.type} className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground">{device.name}</span>
            <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
              #{device.id}
            </span>
            <span className="whitespace-nowrap rounded bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary">
              {DEVICE_TYPE_LABELS[device.type] || device.type}
            </span>
            {device.vendor && (
              <span className="whitespace-nowrap text-[11px] text-muted-foreground/70">
                {device.vendor}
              </span>
            )}
            <StatusBadge status={device.status || (device.enabled ? 'unconfigured' : 'disabled')} />
            {tags.map((t) => (
              <span
                key={t}
                className="whitespace-nowrap rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {t}
              </span>
            ))}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/70">
            {device.ip_address && (
              <>
                <span className="truncate" title={`IP: ${device.ip_address}`}>
                  {device.ip_address}
                </span>
                <span>·</span>
              </>
            )}
            <span
              className="truncate"
              title={api_url || '未配置 API 地址'}
              style={{ maxWidth: 360 }}
            >
              {api_url ? (
                truncate(api_url, 30)
              ) : (
                <span className="text-destructive">未配置</span>
              )}
            </span>
            <span>·</span>
            <span>动作 {device.action_count ?? '-'}</span>
            <span>·</span>
            <span>今日 {device.today_call_count ?? 0} 次</span>
            {device.last_heartbeat && (
              <>
                <span>·</span>
                <span title={fmtTime(device.last_heartbeat)}>
                  心跳 {fmtRelative(device.last_heartbeat)}
                </span>
              </>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={() => onTest(device)}
            disabled={testing}
            className="btn-secondary btn-sm"
            title="测试连接"
          >
            {testing ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />}
          </button>
          <button type="button" onClick={() => onEdit(device)} className="btn-secondary btn-sm">
            编辑
          </button>
          <button type="button" onClick={() => onDelete(device)} className="btn-danger btn-sm">
            删除
          </button>
          <button
            type="button"
            onClick={() => onToggleExpand(device)}
            className="btn-secondary btn-sm"
            title={expanded ? '收起' : '展开'}
          >
            {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      {/* 动作列表（展开时显示） */}
      {expanded && (
        <div className="border-t border-border bg-background/40 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              设备动作（{loadingActions ? '...' : actions.length} 个）
            </h3>
            <button type="button" onClick={() => onNewAction()} className="btn-primary btn-sm">
              <Plus className="mr-1 h-3 w-3" /> 新建动作
            </button>
          </div>
          <ActionTable
            actions={actions}
            loading={loadingActions}
            onEdit={onEditAction}
            onDelete={onDeleteAction}
            onTest={onTestAction}
            onToggle={onToggleAction}
            onHistory={onActionHistory}
            togglingActionId={togglingActionId}
          />
        </div>
      )}
    </div>
  )
}

// ============ 动作表格 ============
export function ActionTable({
  actions,
  loading,
  onEdit,
  onDelete,
  onTest,
  onToggle,
  onHistory,
  togglingActionId,
}) {
  if (loading) {
    return <div className="py-6 text-center text-xs text-muted-foreground/70">加载中...</div>
  }
  if (actions.length === 0) {
    return <div className="py-6 text-center text-xs text-muted-foreground/60">暂无动作，请新建</div>
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[1100px] table-fixed border-collapse text-sm">
        <thead className="bg-card text-muted-foreground">
          <tr>
            <th className="w-16 px-3 py-2 text-left font-medium">ID</th>
            <th className="w-40 px-3 py-2 text-left font-medium">动作名称</th>
            <th className="w-20 px-3 py-2 text-left font-medium">分类</th>
            <th className="w-16 px-3 py-2 text-left font-medium">方法</th>
            <th className="px-3 py-2 text-left font-medium">API 路径</th>
            <th className="w-16 px-3 py-2 text-left font-medium">版本</th>
            <th className="w-28 px-3 py-2 text-left font-medium">最后调用</th>
            <th className="w-16 px-3 py-2 text-right font-medium">24h调用</th>
            <th className="w-16 px-3 py-2 text-right font-medium">成功率</th>
            <th className="w-16 px-3 py-2 text-right font-medium">平均响应</th>
            <th className="w-16 px-3 py-2 text-center font-medium">风险</th>
            <th className="w-16 px-3 py-2 text-center font-medium">启用</th>
            <th className="w-44 px-3 py-2 text-left font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((a, idx) => {
            const rate = successRate(a)
            return (
              <tr
                key={a.id}
                className={`border-t border-border hover:bg-primary/5 ${idx % 2 === 0 ? 'bg-card/30' : ''}`}
              >
                <td className="px-3 py-2 font-mono text-primary">#{a.id}</td>
                <td className="truncate px-3 py-2 text-foreground" title={a.name}>
                  {a.name}
                </td>
                <td className="px-3 py-2">
                  <CategoryBadge category={a.category} />
                </td>
                <td className="px-3 py-2">
                  <MethodBadge method={a.http_method} />
                </td>
                <td className="truncate px-3 py-2 font-mono text-muted-foreground" title={a.api_path}>
                  {a.api_path || '-'}
                </td>
                <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
                  v{a.version || 1}
                </td>
                <td className="px-3 py-2 text-[11px] text-muted-foreground" title={fmtTime(a.last_call_at)}>
                  {fmtRelative(a.last_call_at)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-[11px] text-foreground">
                  {a.call_count_24h ?? 0}
                </td>
                <td className="px-3 py-2 text-right">
                  {rate == null ? (
                    <span className="text-[11px] text-muted-foreground/60">-</span>
                  ) : (
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        rate >= 0.9
                          ? 'bg-success/20 text-success'
                          : rate >= 0.5
                          ? 'bg-warning/20 text-warning'
                          : 'bg-destructive/20 text-destructive'
                      }`}
                    >
                      {(rate * 100).toFixed(0)}%
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-mono text-[11px] text-muted-foreground">
                  {a.avg_latency_ms != null ? `${a.avg_latency_ms}ms` : '-'}
                </td>
                <td className="px-3 py-2 text-center">
                  <RiskBadge level={a.risk_level} />
                </td>
                <td className="px-3 py-2 text-center">
                  <Switch
                    checked={!!a.enabled}
                    onChange={() => onToggle(a)}
                    disabled={togglingActionId === a.id}
                    size="sm"
                  />
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    <button
                      type="button"
                      onClick={() => onTest(a)}
                      className="btn-secondary btn-sm"
                      title="测试动作"
                    >
                      <TestTube className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onHistory(a)}
                      className="btn-secondary btn-sm"
                      title="执行历史"
                    >
                      <History className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onEdit(a)}
                      className="btn-secondary btn-sm"
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(a)}
                      className="btn-danger btn-sm"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ============ 设备列表行（用于分栏视图和列表视图） ============
export function DeviceRow({
  device,
  selected,
  onClick,
  onTest,
  testing,
  checked,
  onToggleCheck,
}) {
  return (
    <div
      onClick={onClick}
      className={`flex cursor-pointer items-center gap-3 border-b border-border px-2 py-2.5 transition ${
        selected ? 'bg-primary/10' : 'hover:bg-accent'
      }`}
    >
      {typeof checked === 'boolean' && (
        <input
          type="checkbox"
          className="h-3.5 w-3.5 shrink-0 accent-primary"
          checked={checked}
          onClick={(e) => e.stopPropagation()}
          onChange={() => onToggleCheck?.(device)}
          title="勾选以导出"
        />
      )}
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-primary/15 text-primary">
        <DeviceTypeIcon type={device.type} className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">{device.name}</span>
          <StatusBadge status={device.status || (device.enabled ? 'unconfigured' : 'disabled')} />
        </div>
        <div className="truncate text-[11px] text-muted-foreground/70">
          {device.api_url ? truncate(device.api_url, 30) : '未配置'}
        </div>
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onTest(device)
        }}
        disabled={testing}
        className="text-muted-foreground hover:text-primary disabled:opacity-40"
        title="测试连接"
      >
        {testing ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}
