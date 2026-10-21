// 接收器管理页：三层信息架构第一层（监听端点）
// 列表：方式/地址/状态/今日接收失败/发现条目数；点击行打开配置抽屉；
// 同一监听地址+端口（同协议）禁止重复创建；发现条目数可点击跳转数据源条目页并按接收器筛选。
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity, AlertTriangle, Inbox, ListTree, Plus, RefreshCw,
  Radio, SlidersHorizontal, Trash2, X, Zap,
} from 'lucide-react'
import { confirm } from '../../components/ConfirmDialog'
import { toast } from '../../store/toastStore'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'
import { inputCls } from '../../components/property/FormControls'
import { devices as devicesApi } from '../../api/client'
import { strategyApi } from '../../api/strategy'
import { Section, Switch } from '../devices/Badges'
import { Button, PageContainer, PageHeader, DataTable } from '../../components/ui'
import {
  LISTEN_PROTOCOLS, SOURCE_TYPE_META, PROTOCOL_TAG_CLS, RECEIVER_STATUS_META,
  parseAdapterConfig, getCfg, setCfgValue, receiverAccessInfo, receiverEndpoint, receiverToBody,
} from './receiverMeta'

// ============ 适配器参数动态表单段（SOURCE_TYPE_META.fields 驱动） ============
function AdapterConfigSection({ meta, cfg, onChange }) {
  const fields = (meta.fields || []).filter((f) => !f.showIf || f.showIf(cfg))
  const setCfg = (key, value) => onChange(setCfgValue(cfg, key, value))
  return (
    <Section title={`${meta.label}参数`} hint={meta.hint}>
      <div className="grid grid-cols-2 gap-3">
        {fields.map((f) => {
          const raw = getCfg(cfg, f.key)
          const display = f.type === 'json' && raw != null && typeof raw === 'object' ? JSON.stringify(raw) : raw ?? ''
          return (
            <label key={f.key} className={f.full ? 'col-span-2' : ''}>
              <div className="mb-1 text-xs font-medium text-muted-foreground">{f.label}{f.required ? ' *' : ''}</div>
              {f.type === 'bool' ? (
                <div className="flex h-[38px] items-center gap-2">
                  <Switch checked={f.defaultTrue ? raw !== false : !!raw} onChange={(v) => setCfg(f.key, v)} />
                  <span className="text-xs text-muted-foreground">{f.hint || (raw ? '已启用' : '未启用')}</span>
                </div>
              ) : f.type === 'select' ? (
                <select className={inputCls} value={String(raw ?? '')} onChange={(e) => setCfg(f.key, e.target.value)}>
                  <option value="">{f.placeholder || '默认'}</option>
                  {(f.options || []).map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                </select>
              ) : f.type === 'textarea' ? (
                <textarea className={inputCls} rows={2} value={display} placeholder={f.placeholder} onChange={(e) => setCfg(f.key, e.target.value)} />
              ) : f.type === 'json' ? (
                <input
                  className={inputCls} value={display} placeholder={f.placeholder}
                  onChange={(e) => {
                    const text = e.target.value
                    let val = text
                    if (text.trim()) { try { val = JSON.parse(text) } catch { val = text } }
                    setCfg(f.key, val)
                  }}
                />
              ) : (
                <input
                  type={f.type === 'number' ? 'number' : 'text'} className={inputCls} value={display} placeholder={f.placeholder}
                  onChange={(e) => setCfg(f.key, f.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)}
                />
              )}
              {f.hint && f.type !== 'bool' && <div className="mt-1 text-[10px] leading-tight text-muted-foreground/70">{f.hint}</div>}
            </label>
          )
        })}
      </div>
    </Section>
  )
}

// ============ 接收器配置抽屉（点击行打开：接收器设置 + 处理配置） ============
// 合并原「接收器设置」「处理配置」双弹窗：抽屉内两个 Section 一次保存（全量 PUT）。
function ReceiverConfigDrawer({ open, initial, receivers, devices, strategies, onClose, onSaved }) {
  const isCreate = !initial?.id
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  // 未保存修改提醒：抽屉打开期间跟踪表单改动；关闭/保存后复位
  const [dirty, setDirty] = useState(false)
  const bypassGuard = useUnsavedChanges(open && dirty, { onSave: () => handleSubmit() })

  const buildForm = (src) => ({
    name: src?.name || '',
    protocol: src?.protocol || 'syslog',
    enabled: src?.enabled !== false,
    syslog_port: src?.syslog_port ?? 514,
    syslog_proto: src?.syslog_proto || 'udp',
    syslog_bind: src?.syslog_bind || '0.0.0.0',
    kafka_bootstrap: src?.kafka_bootstrap || '',
    kafka_topic: src?.kafka_topic || '',
    kafka_group: src?.kafka_group || 'soar-ingest',
    kafka_security: src?.kafka_security || '',
    adapter_config: parseAdapterConfig(src?.adapter_config),
    description: src?.description || '',
    // 处理配置
    device_id: src?.device_id ? String(src.device_id) : '',
    format: src?.format || 'json',
    strategy_id: src?.strategy_id ? String(src.strategy_id) : '',
    notify_interval_minutes: src?.notify_interval_minutes ?? 0,
  })

  useEffect(() => {
    if (open) { setForm(buildForm(initial)); setDirty(false) }
  }, [open, initial]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k, v) => { setForm((p) => ({ ...p, [k]: v })); setDirty(true) }
  const meta = SOURCE_TYPE_META[form?.protocol] || {}
  const isFlat = !!meta.flat
  const isListen = LISTEN_PROTOCOLS.has(form?.protocol)

  // 同一监听地址+端口禁止重复创建（与后端 _check_port_conflict 一致：仅比对启用中的接收器）
  const checkEndpointDup = () => {
    const probe = {
      protocol: form.protocol,
      syslog_port: form.syslog_port,
      syslog_bind: form.syslog_bind,
      adapter_config: form.adapter_config,
    }
    const ep = receiverEndpoint(probe)
    if (!ep) return null
    const dup = receivers.find((r) => {
      if (r.id === initial?.id || !r.enabled) return false
      if (r.protocol !== form.protocol) return false
      return receiverEndpoint(r) === ep
    })
    return dup ? { ep, dup } : null
  }

  const handleSubmit = async () => {
    if (!form.name.trim()) { toast.warning('请填写接收器名称'); return }
    if (form.protocol === 'syslog' && !form.syslog_port) { toast.warning('Syslog 需配置监听端口'); return }
    if (form.protocol === 'kafka' && (!form.kafka_bootstrap || !form.kafka_topic)) {
      toast.warning('Kafka 需配置 bootstrap 与 topic'); return
    }
    if (!isFlat) {
      for (const f of meta.fields || []) {
        if (f.required && !String(getCfg(form.adapter_config, f.key) ?? '').trim()) {
          toast.warning(`请填写${f.label}`); return
        }
      }
      for (const f of (meta.fields || []).filter((x) => x.type === 'json')) {
        const v = getCfg(form.adapter_config, f.key)
        if (typeof v === 'string' && v.trim()) { toast.warning(`「${f.label}」需为合法 JSON`); return }
      }
    }
    if (!isListen && !form.device_id) { toast.warning('拉取型接收器必须绑定默认归属设备'); return }
    // 同名 + 同归属设备去重（后端 (device_id, name) 唯一）
    const ownerKey = isListen ? null : Number(form.device_id)
    if (receivers.some((r) => r.id !== initial?.id && r.name.trim() === form.name.trim() && (r.device_id ?? null) === ownerKey)) {
      toast.warning(`已存在同名接收器「${form.name.trim()}」，请换一个名称`); return
    }
    // 同地址+端口重复（同协议）
    const dupHit = checkEndpointDup()
    if (dupHit) {
      toast.warning(`监听地址 ${dupHit.ep} 已被接收器「${dupHit.dup.name}」占用，同一地址+端口不可重复创建`)
      return
    }
    const patch = {
      name: form.name.trim(),
      protocol: form.protocol,
      enabled: !!form.enabled,
      syslog_port: form.syslog_port,
      syslog_proto: form.syslog_proto,
      syslog_bind: form.syslog_bind,
      kafka_bootstrap: form.kafka_bootstrap,
      kafka_topic: form.kafka_topic,
      kafka_group: form.kafka_group,
      kafka_security: form.kafka_security,
      adapter_config: { ...(form.adapter_config || {}) },
      description: form.description,
      device_id: form.device_id ? Number(form.device_id) : null,
      format: form.format,
      strategy_id: form.strategy_id ? Number(form.strategy_id) : null,
      notify_interval_minutes: Math.max(0, Number(form.notify_interval_minutes) || 0),
    }
    const body = isCreate ? patch : { ...receiverToBody(initial), ...patch }
    setSaving(true)
    try {
      if (isCreate) {
        await devicesApi.logReceivers.create(body)
        toast.success('接收器已创建')
      } else {
        await devicesApi.logReceivers.update(initial.id, body)
        toast.success('接收器配置已保存')
      }
      onSaved()
      setDirty(false)
      bypassGuard() // 保存成功放行，关闭抽屉不再拦截
      onClose()
    } catch (err) {
      toast.error(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 关闭前脏检查：有未保存修改时二次确认，避免误触关闭丢改动
  const requestClose = () => {
    if (!dirty) { onClose(); return }
    confirm({
      title: '放弃未保存的修改',
      message: `接收器「${form?.name || '新建'}」的配置有未保存的修改，关闭后将丢失这些更改。`,
      variant: 'danger',
      confirmText: '放弃修改并关闭',
    }).then((ok) => {
      if (!ok) return
      setDirty(false)
      bypassGuard()
      onClose()
    })
  }

  if (!open || !form) return null

  return (
    <div className="fixed inset-0 z-[100] flex justify-end">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={requestClose} />
      <div className="relative flex h-full w-full flex-col border-l border-border bg-card shadow-2xl sm:max-w-[680px]">
        {/* 抽屉头部 */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">{isCreate ? '添加接收器' : `接收器配置 · ${initial?.name}`}</span>
            {!isCreate && (
              <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${PROTOCOL_TAG_CLS[form.protocol] || 'bg-secondary text-muted-foreground'}`}>
                {SOURCE_TYPE_META[form.protocol]?.label || form.protocol}
              </span>
            )}
          </div>
          <button
            type="button" onClick={requestClose}
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-foreground"
            title="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 抽屉内容 */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="flex flex-col gap-3">
            <Section title="接收器设置" hint="监听端点：日志到达后按来源 IP 自动生成数据源条目">
              <div className="grid grid-cols-2 gap-3">
                <label>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">接收器名称 *</div>
                  <input className={inputCls} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="如 syslog-514" />
                </label>
                <label>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">接收方式 *</div>
                  <select className={inputCls} value={form.protocol} onChange={(e) => set('protocol', e.target.value)} disabled={!isCreate}>
                    {Object.entries(SOURCE_TYPE_META).map(([v, m]) => (<option key={v} value={v}>{m.label}</option>))}
                  </select>
                </label>
              </div>
              <label className="mt-3 block">
                <div className="mb-1 text-xs font-medium text-muted-foreground">描述</div>
                <input className={inputCls} value={form.description} onChange={(e) => set('description', e.target.value)} placeholder="可选" />
              </label>
              <label className="mt-3 flex items-center gap-2">
                <Switch checked={!!form.enabled} onChange={(v) => set('enabled', v)} />
                <span className="text-sm text-muted-foreground">启用该接收器</span>
              </label>

              {form.protocol === 'syslog' && (
                <div className="mt-3">
                  <div className="mb-2 text-xs font-semibold text-foreground">Syslog 监听</div>
                  <div className="grid grid-cols-3 gap-3">
                    <label>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">监听端口 *</div>
                      <input type="number" min={1} max={65535} className={inputCls} value={form.syslog_port} onChange={(e) => set('syslog_port', Number(e.target.value))} />
                    </label>
                    <label>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">传输协议</div>
                      <select className={inputCls} value={form.syslog_proto} onChange={(e) => set('syslog_proto', e.target.value)}>
                        <option value="udp">UDP</option>
                        <option value="tcp">TCP</option>
                      </select>
                    </label>
                    <label>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">监听地址</div>
                      <input className={inputCls} value={form.syslog_bind} onChange={(e) => set('syslog_bind', e.target.value)} placeholder="0.0.0.0" />
                      <div className="mt-1 text-[10px] leading-tight text-muted-foreground/70">0.0.0.0 监听所有接口；填本机不存在的地址会启动失败</div>
                    </label>
                  </div>
                  {/* 条目自动发现（监听型专属，存 adapter_config） */}
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    <div className="flex items-center gap-2">
                      <Switch
                        checked={getCfg(form.adapter_config, 'entry_discovery') !== false}
                        onChange={(v) => set('adapter_config', setCfgValue(form.adapter_config, 'entry_discovery', v))}
                      />
                      <div className="text-xs text-muted-foreground">
                        条目自动发现
                        <div className="text-[10px] text-muted-foreground/70">按来源 IP 自动生成数据源条目，未配置的条目跟随接收器默认模板</div>
                      </div>
                    </div>
                    <label>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">条目数量上限</div>
                      <input
                        type="number" min={1} className={inputCls}
                        value={getCfg(form.adapter_config, 'entry_max_count') ?? ''}
                        placeholder="1000"
                        onChange={(e) => set('adapter_config', setCfgValue(form.adapter_config, 'entry_max_count', e.target.value === '' ? '' : Number(e.target.value)))}
                      />
                      <div className="mt-1 text-[10px] text-muted-foreground/70">超过上限后新来源不再建条目，走接收器默认配置</div>
                    </label>
                  </div>
                </div>
              )}

              {form.protocol === 'kafka' && (
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <label>
                    <div className="mb-1 text-xs font-medium text-muted-foreground">Bootstrap Servers *</div>
                    <input className={inputCls} value={form.kafka_bootstrap} onChange={(e) => set('kafka_bootstrap', e.target.value)} placeholder="host:9092,host2:9092" />
                  </label>
                  <label>
                    <div className="mb-1 text-xs font-medium text-muted-foreground">Topic *</div>
                    <input className={inputCls} value={form.kafka_topic} onChange={(e) => set('kafka_topic', e.target.value)} placeholder="topic1,topic2" />
                  </label>
                  <label>
                    <div className="mb-1 text-xs font-medium text-muted-foreground">消费组</div>
                    <input className={inputCls} value={form.kafka_group} onChange={(e) => set('kafka_group', e.target.value)} />
                  </label>
                  <label>
                    <div className="mb-1 text-xs font-medium text-muted-foreground">安全配置(JSON)</div>
                    <input className={inputCls} value={form.kafka_security} onChange={(e) => set('kafka_security', e.target.value)} placeholder='{"security_protocol":"SSL"}' />
                  </label>
                </div>
              )}
            </Section>

            {!isFlat && <AdapterConfigSection meta={meta} cfg={form.adapter_config} onChange={(c) => set('adapter_config', c)} />}

            <Section title="处理配置" hint="日志进入解析管道后的默认处理规则（可被数据源条目逐条覆盖）">
              <div className="grid grid-cols-2 gap-3">
                <label>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">默认归属设备{isListen ? '' : ' *'}</div>
                  <select className={inputCls} value={form.device_id} onChange={(e) => set('device_id', e.target.value)}>
                    <option value="">{isListen ? '按数据源条目自动归属（推荐）' : '请选择设备'}</option>
                    {(devices || []).map((d) => (<option key={d.id} value={d.id}>{d.name}</option>))}
                  </select>
                  <div className="mt-1 text-[10px] text-muted-foreground/70">
                    {isListen ? '仅当数据源条目未绑定设备时使用此默认归属' : '拉取型必须绑定设备，接收日志与告警均计入该设备'}
                  </div>
                </label>
                <label>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">内容格式</div>
                  <select className={inputCls} value={form.format} onChange={(e) => set('format', e.target.value)}>
                    <option value="json">JSON</option>
                    <option value="raw">原始文本</option>
                  </select>
                </label>
              </div>
              <label className="mt-3 block">
                <div className="mb-1 text-xs font-medium text-muted-foreground">解析模板</div>
                <select className={inputCls} value={form.strategy_id} onChange={(e) => set('strategy_id', e.target.value)}>
                  <option value="">自动匹配（推荐）</option>
                  {(strategies || []).map((s) => (
                    <option key={s.id} value={s.id}>{s.strategy_name}{s.device_type ? `（${s.device_type}）` : ''}</option>
                  ))}
                </select>
                <div className="mt-1 text-xs text-muted-foreground">
                  {form.strategy_id
                    ? '固定使用该模板解析，失败即记为失败，不会自动切换其他模板。'
                    : '不选择则由系统按路由规则自动匹配解析模板（元数据 → 特征匹配 → 候选回退）。'}
                </div>
              </label>
              <label className="mt-3 block">
                <div className="mb-1 text-xs font-medium text-muted-foreground">异常通知间隔（分钟）</div>
                <input type="number" min={0} className={inputCls} value={form.notify_interval_minutes}
                  onChange={(e) => set('notify_interval_minutes', Math.max(0, Number(e.target.value) || 0))} />
                <div className="mt-1 text-xs text-muted-foreground">
                  {Number(form.notify_interval_minutes) > 0
                    ? `接收器异常（断流/失败率过高/停止/积压）持续时，每 ${Number(form.notify_interval_minutes)} 分钟重复提醒一次。`
                    : '仅首次异常时提醒一次，恢复前不重复。'}
                </div>
              </label>
            </Section>

            {isCreate && (
              <div className="rounded-md bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
                保存后设备日志到达即按来源 IP 自动生成数据源条目；条目归属设备与解析模板可在「数据源条目」页逐条配置。
              </div>
            )}
          </div>
        </div>

        {/* 抽屉底部 */}
        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border px-5 py-3">
          <button type="button" onClick={requestClose} className="btn-secondary btn-sm">取消</button>
          <button type="button" onClick={handleSubmit} disabled={saving} className="btn-primary btn-sm">
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ============ 接收器管理页 ============
export default function ReceiverList() {
  const navigate = useNavigate()
  const [receivers, setReceivers] = useState([])
  const [summary, setSummary] = useState(null)
  const [devices, setDevices] = useState([])
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)

  // 配置抽屉：editing=null 表示新建
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [recRes, sumRes] = await Promise.all([
        devicesApi.logReceivers.list(),
        devicesApi.logReceivers.summary(),
      ])
      setReceivers(Array.isArray(recRes) ? recRes : recRes?.items || [])
      setSummary(sumRes)
    } catch (err) {
      toast.error(err.message || '加载接收器失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // 设备与解析模板列表（抽屉下拉）
  useEffect(() => {
    let cancelled = false
    devicesApi.list().then((res) => { if (!cancelled) setDevices(Array.isArray(res) ? res : res?.items || []) }).catch(() => {})
    strategyApi.list().then((res) => { if (!cancelled) setStrategies(Array.isArray(res) ? res : res?.items || []) }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const handleDelete = async (rec) => {
    const ok = await confirm({
      title: '删除接收器',
      message: `确定删除接收器「${rec.name}」？删除后将停止监听，并级联清理其 ${rec.entries_count ?? 0} 个数据源条目与接收明细。`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    try {
      await devicesApi.logReceivers.remove(rec.id)
      toast.success('接收器已删除')
      load()
    } catch (err) {
      toast.error(err.message || '删除失败')
    }
  }

  const handleReload = async (rec) => {
    try {
      await devicesApi.logReceivers.reload(rec.id)
      toast.success('已重新应用配置')
      load()
    } catch (err) {
      toast.error(err.message || '操作失败')
    }
  }

  const strategyName = useCallback((id) => {
    const s = strategies.find((x) => String(x.id) === String(id))
    return s ? s.strategy_name : `#${id}`
  }, [strategies])

  const s = summary || {}

  // 统计卡片下钻筛选：''=全部 running=运行中 abnormal=异常 today_active=今日有接收 today_failed=今日有失败
  const [cardFilter, setCardFilter] = useState('')
  const CARD_FILTER_LABELS = { running: '运行中', abnormal: '异常', today_active: '今日有接收', today_failed: '今日有失败' }
  const isRunning = (r) => !!r.enabled && ['listening', 'running'].includes(r.status)
  const isAbnormal = (r) => !!r.enabled && ['start_failed', 'failed', 'stopped'].includes(r.status)
  const filteredReceivers = useMemo(() => {
    if (cardFilter === 'running') return receivers.filter(isRunning)
    if (cardFilter === 'abnormal') return receivers.filter(isAbnormal)
    if (cardFilter === 'today_active') return receivers.filter((r) => (r.today_total ?? 0) > 0)
    if (cardFilter === 'today_failed') return receivers.filter((r) => (r.today_fail ?? 0) > 0)
    return receivers
  }, [receivers, cardFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  const statCards = [
    { label: '接收器', value: s.receiver_count ?? 0, icon: Radio, cls: '', filter: '', tip: '查看全部接收器' },
    { label: '运行中', value: s.running_count ?? 0, icon: Activity, cls: 'text-success', filter: 'running', tip: '筛选运行中的接收器' },
    { label: '异常', value: s.abnormal_count ?? 0, icon: AlertTriangle, cls: s.abnormal_count ? 'text-destructive' : 'text-muted-foreground', filter: 'abnormal', tip: '筛选异常的接收器' },
    { label: '今日接收', value: s.today_total ?? 0, icon: Inbox, cls: '', filter: 'today_active', tip: '筛选今日有日志到达的接收器' },
    { label: '今日失败', value: s.today_fail ?? 0, icon: Zap, cls: s.today_fail ? 'text-destructive' : 'text-muted-foreground', filter: 'today_failed', tip: '筛选今日有解析失败的接收器' },
  ]

  const fmtCount = (n) => (n ?? 0).toLocaleString()

  const columns = [
    {
      key: 'name', header: '接收器', width: '220px',
      render: (r) => (
        <div className="min-w-0">
          <div className="truncate font-medium" title={r.name}>{r.name}</div>
          {r.strategy_id ? (
            <div className="text-[11px] text-primary" title={`固定模板：${strategyName(r.strategy_id)}`}>
              固定模板：{strategyName(r.strategy_id)}
            </div>
          ) : (
            <div className="text-[11px] text-muted-foreground/60">模板自动匹配</div>
          )}
        </div>
      ),
    },
    {
      key: 'protocol', header: '方式', width: '120px',
      render: (r) => (
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${PROTOCOL_TAG_CLS[r.protocol] || 'bg-secondary text-muted-foreground'}`} title={r.protocol}>
          {SOURCE_TYPE_META[r.protocol]?.label || r.protocol}
        </span>
      ),
    },
    {
      key: 'endpoint', header: '监听地址 / 接入信息', width: '240px',
      render: (r) => <span className="font-mono text-xs text-muted-foreground" title={receiverAccessInfo(r)}>{receiverAccessInfo(r)}</span>,
    },
    {
      key: 'status', header: '状态', width: '130px',
      render: (r) => {
        const st = RECEIVER_STATUS_META[r.status] || { label: r.status, cls: 'bg-secondary text-muted-foreground' }
        return (
          <div>
            <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${st.cls}`}>
              {r.alive && <span className="h-1.5 w-1.5 rounded-full bg-success" />}
              {st.label}
            </span>
            {r.status === 'start_failed' && r.last_error && (
              <div className="mt-0.5 max-w-[200px] truncate font-mono text-[10px] text-destructive" title={r.last_error}>
                {r.last_error}
              </div>
            )}
          </div>
        )
      },
    },
    {
      key: 'today', header: '今日接收 / 失败', width: '130px', numeric: true,
      render: (r) => (
        <span>
          <span className={`tabular-nums ${(r.today_total ?? 0) > 0 ? '' : 'text-muted-foreground/50'}`}>{fmtCount(r.today_total)}</span>
          <span className="mx-1 text-muted-foreground/40">/</span>
          <span className={`tabular-nums ${r.today_fail ? 'text-destructive' : 'text-muted-foreground/50'}`} title="今日接收失败数">
            {fmtCount(r.today_fail)}
          </span>
        </span>
      ),
    },
    {
      key: 'entries', header: '发现条目', width: '110px', numeric: true,
      render: (r) => {
        if (!LISTEN_PROTOCOLS.has(r.protocol)) {
          return <span className="text-muted-foreground/40" title="拉取型无来源条目">--</span>
        }
        const n = r.entries_count ?? 0
        return (
          <button
            type="button"
            className="rounded-full px-1.5 text-[11px] font-medium tabular-nums transition hover:underline"
            onClick={(e) => { e.stopPropagation(); navigate(`/source-entries?receiver=${r.id}`) }}
            title={`查看 ${r.name} 的数据源条目`}
          >
            <span className={n ? 'bg-primary/15 px-1.5 py-0.5 text-primary' : 'px-1.5 py-0.5 text-muted-foreground/50'}>{fmtCount(n)}</span>
          </button>
        )
      },
    },
    {
      key: 'last_received_at', header: '最近接收', width: '150px',
      render: (r) => (
        <span className="text-xs text-muted-foreground">
          {r.last_received_at ? new Date(r.last_received_at).toLocaleString() : '—'}
        </span>
      ),
    },
    {
      key: 'actions', header: '操作', width: '110px',
      render: (r) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            type="button" onClick={() => handleReload(r)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary"
            title="应用配置 / 重启"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            type="button" onClick={() => handleDelete(r)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive"
            title="删除"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ),
    },
  ]

  return (
    <PageContainer>
      <PageHeader
        title="接收器"
        description="管理日志监听端点：接收器只负责监听，日志到达后按来源 IP 自动生成数据源条目，由条目绑定设备与解析模板"
        actions={(
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={load} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> 刷新
            </Button>
            <Button variant="primary" onClick={() => { setEditing(null); setDrawerOpen(true) }}>
              <Plus className="h-4 w-4" /> 添加接收器
            </Button>
          </div>
        )}
      />

      {/* 概览统计卡片（点击下钻筛选列表） */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {statCards.map((c) => {
          const active = !!c.filter && cardFilter === c.filter
          return (
            <div
              key={c.label}
              role="button"
              tabIndex={0}
              title={`${c.tip}（点击查看）`}
              onClick={() => setCardFilter((v) => (v === c.filter ? '' : c.filter))}
              className={`card cursor-pointer px-5 py-4 transition hover:border-primary/40 hover:shadow-md ${active ? 'border-primary/40 ring-1 ring-primary/20' : ''}`}
            >
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <c.icon className="h-3.5 w-3.5" />
                {c.label}
              </div>
              <div className={`mt-1 text-2xl font-semibold tabular-nums ${c.cls}`}>{fmtCount(c.value)}</div>
            </div>
          )
        })}
      </div>

      {/* 接收器列表 */}
      <div className="card">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="flex items-center gap-2">
            <ListTree className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium">接收器列表</span>
            <span className="text-xs text-muted-foreground">
              8 类日志源接入：推送（Syslog / SNMP Trap / NetFlow）、拉取（REST API / 数据库）、本机（文件跟踪 / 镜像抓包）与 Kafka 消费
            </span>
          </div>
          {cardFilter ? (
            <button
              type="button"
              onClick={() => setCardFilter('')}
              title="清除筛选，显示全部接收器"
              className="flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs text-primary transition hover:bg-primary/20"
            >
              筛选：{CARD_FILTER_LABELS[cardFilter]} · {filteredReceivers.length}/{receivers.length}
              <X className="h-3 w-3" />
            </button>
          ) : (
            <span className="text-xs text-muted-foreground">点击行打开配置抽屉</span>
          )}
        </div>
        <DataTable
          columns={columns}
          data={filteredReceivers}
          loading={loading}
          rowKey="id"
          onRowClick={(r) => { setEditing(r); setDrawerOpen(true) }}
          emptyIcon={Radio}
          emptyText="暂无接收器"
          emptyDescription="点击「添加接收器」配置监听端点，设备日志到达后自动生成数据源条目"
          emptyAction={(
            <Button variant="primary" onClick={() => { setEditing(null); setDrawerOpen(true) }}>
              <Plus className="h-4 w-4" /> 添加接收器
            </Button>
          )}
        />
      </div>

      {/* 接收器配置抽屉 */}
      <ReceiverConfigDrawer
        open={drawerOpen}
        initial={editing}
        receivers={receivers}
        devices={devices}
        strategies={strategies}
        onClose={() => { setDrawerOpen(false); setEditing(null) }}
        onSaved={load}
      />
    </PageContainer>
  )
}
