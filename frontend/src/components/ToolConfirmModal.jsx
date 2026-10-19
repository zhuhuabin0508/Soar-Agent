import { AlertTriangle, Loader2, X } from 'lucide-react'

export default function ToolConfirmModal({
  open,
  toolName,
  dangerLevel,
  ticketId,
  args,
  busy,
  onConfirm,
  onReject,
  onClose,
}) {
  if (!open) return null

  let argsText = ''
  try {
    argsText = args && Object.keys(args || {}).length
      ? JSON.stringify(args, null, 2)
      : ''
  } catch {
    argsText = String(args || '')
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 p-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-card shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
            <div>
              <div className="text-sm font-semibold text-foreground">高危操作确认</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                请确认是否执行，操作人将记入审计日志
              </div>
            </div>
          </div>
          <button
            type="button"
            className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
            onClick={onClose}
            disabled={busy}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-4 py-3 text-sm">
          <div>
            <div className="text-xs text-muted-foreground">工具</div>
            <div className="font-mono text-foreground">{toolName || '-'}</div>
          </div>
          <div className="flex gap-4">
            <div>
              <div className="text-xs text-muted-foreground">危险等级</div>
              <div className="font-medium text-amber-600">{dangerLevel || 'high'}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">工单</div>
              <div className="font-mono">#{ticketId}</div>
            </div>
          </div>
          {argsText ? (
            <div>
              <div className="text-xs text-muted-foreground">参数</div>
              <pre className="mt-1 max-h-40 overflow-auto rounded-md border border-border bg-secondary/40 p-2 font-mono text-[11px] leading-relaxed">
                {argsText}
              </pre>
            </div>
          ) : null}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <button
            type="button"
            disabled={busy}
            onClick={onReject}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-secondary disabled:opacity-50"
          >
            拒绝
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            确认执行
          </button>
        </div>
      </div>
    </div>
  )
}
