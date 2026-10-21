// 工单 SLA 目标配置页：按优先级（紧急/高危/中危/低危）设定响应时限与解决时限
// - 响应时限 = 工单发起 → 首次节点提交；解决时限 = 工单创建 → 完成关闭
// - 留空 = 该优先级对应维度不设目标（不参与大屏 SLA 统计）
// - 配置实时作用于监控大屏 SLA 时效分析与超时预警口径
import { useEffect, useState } from 'react'
import { TimerReset, RotateCcw } from 'lucide-react'
import { toast } from '../store/toastStore'
import { inputCls, labelCls } from '../components/property/FormControls'
import { Button, PageContainer } from '../components/ui'
import { hasPermission } from '../utils/permissions'
import ticketApi from '../api/tickets'

const PRIORITIES = [
  ['critical', '紧急'],
  ['high', '高危'],
  ['medium', '中危'],
  ['low', '低危'],
]

// 分钟数 → 可读时长（60 分钟以上显示小时）
const fmtMinutes = (m) => {
  if (m === null || m === undefined) return '不限'
  if (m < 60) return `${m} 分钟`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r ? `${h} 小时 ${r} 分` : `${h} 小时`
}

export default function TicketSlaConfig() {
  const canEdit = hasPermission('ticket_config', 'edit')
  const [config, setConfig] = useState(null)
  const [defaults, setDefaults] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    ticketApi.getSlaConfig()
      .then((res) => {
        setConfig(res.config || {})
        setDefaults(res.defaults || {})
      })
      .catch((e) => toast.error(e.message || '加载 SLA 配置失败'))
      .finally(() => setLoading(false))
  }, [])

  const setDim = (p, dim, v) => {
    // 输入留空即不限（null）；仅接受正整数
    const val = v === '' ? null : (Number(v) >= 1 ? Math.floor(Number(v)) : '')
    setConfig((c) => ({ ...c, [p]: { ...(c[p] || {}), [dim]: val } }))
  }

  const handleSave = () => {
    // 本地预校验：空字符串视为非法输入（应清空为不限）
    for (const [p] of PRIORITIES) {
      for (const dim of ['response', 'resolve']) {
        const v = config?.[p]?.[dim]
        if (v === '' || v === undefined) {
          return toast.error('时限需为正整数，或清空表示不限')
        }
      }
    }
    setSaving(true)
    ticketApi.updateSlaConfig(config)
      .then((res) => {
        setConfig(res.config)
        toast.success('SLA 目标配置已保存')
      })
      .catch((e) => toast.error(e.message || '保存失败'))
      .finally(() => setSaving(false))
  }

  return (
    <PageContainer>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[22px] font-bold text-foreground">SLA 目标配置</h1>
          <p className="mt-2 text-[13px] text-muted-foreground">
            按工单优先级设定响应时限与解决时限：响应 = 工单发起 → 首次节点提交；解决 = 工单创建 → 完成关闭。
            超出目标即计为 SLA 超时，作用于监控大屏的 SLA 时效分析与超时预警；留空表示该维度不设目标（不参与统计）。
          </p>
        </div>
        {canEdit && config && (
          <div className="flex shrink-0 gap-2">
            <Button variant="outline" size="sm" onClick={() => setConfig(structuredClone(defaults))}>
              <RotateCcw className="mr-1 h-3.5 w-3.5" />恢复默认
            </Button>
            <Button variant="primary" size="sm" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存配置'}
            </Button>
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">加载中...</div>
      ) : !config ? (
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">暂无配置数据</div>
      ) : (
        <div className="rounded-md border border-border bg-card">
          {/* 表头 */}
          <div className="grid grid-cols-[180px_1fr_1fr_200px] items-center gap-4 border-b border-border px-6 py-3 text-[13px] font-medium text-muted-foreground">
            <div>优先级</div>
            <div>响应时限（分钟）</div>
            <div>解决时限（分钟）</div>
            <div className="text-right">默认值参考</div>
          </div>
          {PRIORITIES.map(([key, label]) => {
            const d = defaults?.[key] || {}
            return (
              <div key={key} className="grid grid-cols-[180px_1fr_1fr_200px] items-center gap-4 border-b border-border px-6 py-4 last:border-b-0">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${key === 'critical' ? 'bg-red-500' : key === 'high' ? 'bg-orange-500' : key === 'medium' ? 'bg-blue-500' : 'bg-slate-400'}`} />
                  <span className="font-medium text-foreground">{label}</span>
                </div>
                <div>
                  <label className={`${labelCls} mb-1.5`}>工单发起 → 首次提交</label>
                  <input
                    type="number" min="1" disabled={!canEdit}
                    className={inputCls} placeholder="留空 = 不限"
                    value={config[key]?.response ?? ''}
                    onChange={(e) => setDim(key, 'response', e.target.value)}
                  />
                </div>
                <div>
                  <label className={`${labelCls} mb-1.5`}>工单创建 → 完成关闭</label>
                  <input
                    type="number" min="1" disabled={!canEdit}
                    className={inputCls} placeholder="留空 = 不限"
                    value={config[key]?.resolve ?? ''}
                    onChange={(e) => setDim(key, 'resolve', e.target.value)}
                  />
                </div>
                <div className="text-right text-[13px] text-muted-foreground">
                  响应 {fmtMinutes(d.response ?? null)} / 解决 {fmtMinutes(d.resolve ?? null)}
                </div>
              </div>
            )
          })}
          <div className="flex items-start gap-2 px-6 py-4 text-[13px] text-muted-foreground">
            <TimerReset className="mt-0.5 h-4 w-4 shrink-0" />
            <p>
              口径说明：进行中工单按当前时间实时判断是否超出目标；已取消工单仅统计响应超时（取消不计解决）；
              流程模板中节点级的「超时提醒」仍用于通知中心提醒处理分组，与大屏 SLA 统计口径相互独立。
            </p>
          </div>
        </div>
      )}
    </PageContainer>
  )
}
