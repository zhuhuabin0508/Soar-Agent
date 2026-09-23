// 日志接收渠道表单弹窗与日志接收 Tab
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, Inbox, Plus, Radio, RefreshCw, Settings, X } from 'lucide-react'
import { Modal } from '../../components/Dialog'
import { confirm } from '../../components/ConfirmDialog'
import { toast } from '../../store/toastStore'
import { inputCls } from '../../components/property/FormControls'
import { devices as devicesApi } from '../../api/client'
import { Section, Switch } from './Badges'

// ============ 日志接收渠道表单弹窗 ============
// 对方设备主动推送日志时，配置 syslog / kafka 接收方式
export function LogReceiverFormModal({ open, initial, devices: devList, onClose, onSubmit, saving }) {
  const [form, setForm] = useState(() => buildInitialReceiverForm(initial))

  function buildInitialReceiverForm(src) {
    return {
      device_id: src?.device_id || '',
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
      format: src?.format || 'json',
      notify_interval_minutes: src?.notify_interval_minutes ?? 0,
      description: src?.description || '',
    }
  }

  useEffect(() => {
    if (open) setForm(buildInitialReceiverForm(initial))
  }, [open, initial])

  const set = (k) => (v) => setForm((p) => ({ ...p, [k]: v }))

  const handleSubmit = async () => {
    if (!form.device_id) {
      toast.warning('请选择所属设备')
      return
    }
    if (!form.name.trim()) {
      toast.warning('请填写渠道名称')
      return
    }
    if (form.protocol === 'syslog' && !form.syslog_port) {
      toast.warning('syslog 需配置监听端口')
      return
    }
    if (form.protocol === 'kafka' && (!form.kafka_bootstrap || !form.kafka_topic)) {
      toast.warning('kafka 需配置 bootstrap 与 topic')
      return
    }
    const ok = await onSubmit({ ...form, device_id: Number(form.device_id), protocol: form.protocol })
    if (ok) onClose()
  }

  return (
    <Modal open={open} title={initial?.id ? '编辑接收渠道' : '添加接收渠道'} onClose={onClose} size="lg"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary btn-sm">取消</button>
          <button type="button" onClick={handleSubmit} disabled={saving} className="btn-primary btn-sm">
            {saving ? '保存中…' : '保存'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Section title="基本信息">
          <div className="grid grid-cols-2 gap-3">
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">所属设备 *</div>
              <select className={inputCls} value={form.device_id} onChange={(e) => set('device_id')(e.target.value)}>
                <option value="">请选择设备</option>
                {(devList || []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}{d.api_url ? '' : '（仅接收日志）'}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">渠道名称 *</div>
              <input className={inputCls} value={form.name} onChange={(e) => set('name')(e.target.value)} placeholder="如 syslog-514 / kafka-soc" />
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">接收方式 *</div>
              <select className={inputCls} value={form.protocol} onChange={(e) => set('protocol')(e.target.value)}>
                <option value="syslog">Syslog</option>
                <option value="kafka">Kafka</option>
              </select>
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-muted-foreground">内容格式</div>
              <select className={inputCls} value={form.format} onChange={(e) => set('format')(e.target.value)}>
                <option value="json">JSON</option>
                <option value="raw">原始文本</option>
              </select>
            </label>
          </div>
          <label className="mt-3 block">
            <div className="mb-1 text-xs font-medium text-muted-foreground">异常通知间隔（分钟）</div>
            <input type="number" min={0} className={inputCls} value={form.notify_interval_minutes}
              onChange={(e) => set('notify_interval_minutes')(Math.max(0, Number(e.target.value) || 0))} />
            <div className="mt-1 text-xs text-muted-foreground">
              {Number(form.notify_interval_minutes) > 0
                ? `接收渠道异常（断流/失败率过高/停止/积压）持续时，每 ${Number(form.notify_interval_minutes)} 分钟重复提醒一次。`
                : '仅首次异常时提醒一次，恢复前不重复。'}
            </div>
          </label>
          <label className="mt-3 block">
            <div className="mb-1 text-xs font-medium text-muted-foreground">描述</div>
            <input className={inputCls} value={form.description} onChange={(e) => set('description')(e.target.value)} placeholder="可选" />
          </label>
          <label className="mt-3 flex items-center gap-2">
            <Switch checked={!!form.enabled} onChange={(v) => set('enabled')(v)} />
            <span className="text-sm text-muted-foreground">启用该接收渠道</span>
          </label>
        </Section>

        {form.protocol === 'syslog' && (
          <Section title="Syslog 监听设置" hint="设备 UDP/TCP 推送日志到此端口">
            <div className="grid grid-cols-3 gap-3">
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">监听端口 *</div>
                <input type="number" min={1} max={65535} className={inputCls} value={form.syslog_port} onChange={(e) => set('syslog_port')(Number(e.target.value))} />
              </label>
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">传输协议</div>
                <select className={inputCls} value={form.syslog_proto} onChange={(e) => set('syslog_proto')(e.target.value)}>
                  <option value="udp">UDP</option>
                  <option value="tcp">TCP</option>
                </select>
              </label>
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">监听地址</div>
                <input
                  className={inputCls}
                  value={form.syslog_bind}
                  onChange={(e) => set('syslog_bind')(e.target.value)}
                  placeholder="0.0.0.0 或本机网卡 IP"
                />
                <div className="mt-1 text-[10px] text-muted-foreground/70">
                  填 0.0.0.0 监听所有接口，或填本机实际 IP；填本机不存在的地址会启动失败（Errno 99）
                </div>
              </label>
            </div>
          </Section>
        )}

        {form.protocol === 'kafka' && (
          <Section title="Kafka 消费设置" hint="从未需安装 aiokafka，未安装时渠道会标记为启动失败">
            <div className="grid grid-cols-2 gap-3">
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">Bootstrap Servers *</div>
                <input className={inputCls} value={form.kafka_bootstrap} onChange={(e) => set('kafka_bootstrap')(e.target.value)} placeholder="host:9092,host2:9092" />
              </label>
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">Topic *</div>
                <input className={inputCls} value={form.kafka_topic} onChange={(e) => set('kafka_topic')(e.target.value)} placeholder="topic1,topic2" />
              </label>
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">消费组</div>
                <input className={inputCls} value={form.kafka_group} onChange={(e) => set('kafka_group')(e.target.value)} />
              </label>
              <label>
                <div className="mb-1 text-xs font-medium text-muted-foreground">安全配置(JSON)</div>
                <input className={inputCls} value={form.kafka_security} onChange={(e) => set('kafka_security')(e.target.value)} placeholder='{"security_protocol":"SSL"}' />
              </label>
            </div>
          </Section>
        )}
      </div>
    </Modal>
  )
}

// ============ 日志接收 Tab（被动接入监控） ============
export function LogReceiversTab({ devices }) {
  const [receivers, setReceivers] = useState([])
  const [summary, setSummary] = useState(null)
  const [metrics, setMetrics] = useState([])
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState(null)

  const [logFilters, setLogFilters] = useState({ receiverId: '', parseStatus: '' })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [recRes, sumRes, metRes, logRes] = await Promise.all([
        devicesApi.logReceivers.list(),
        devicesApi.logReceivers.summary(),
        devicesApi.logReceivers.metrics({ hours: 24 }),
        devicesApi.logReceivers.receiveLogs({ page: 1, page_size: 50 }),
      ])
      setReceivers(Array.isArray(recRes) ? recRes : recRes?.items || [])
      setSummary(sumRes)
      setMetrics(Array.isArray(metRes) ? metRes : [])
      setLogs(logRes?.items || [])
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSubmit = async (body) => {
    try {
      if (editing?.id) {
        await devicesApi.logReceivers.update(editing.id, body)
      } else {
        await devicesApi.logReceivers.create(body)
      }
      setFormOpen(false)
      setEditing(null)
      load()
      return true
    } catch (err) {
      toast.error(err.message || '保存失败')
      return false
    }
  }

  const handleDelete = async (rec) => {
    const ok = await confirm(`确定删除接收渠道「${rec.name}」？删除后将停止对应监听。`)
    if (!ok) return
    try {
      await devicesApi.logReceivers.remove(rec.id)
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

  const s = summary || {}
  const statCards = [
    { label: '接收渠道', value: s.receiver_count ?? 0, cls: '' },
    { label: '运行中', value: s.running_count ?? 0, cls: 'text-success' },
    { label: '异常', value: s.abnormal_count ?? 0, cls: s.abnormal_count ? 'text-destructive' : '' },
    { label: '今日接收', value: s.today_total ?? 0, cls: '' },
    { label: '今日失败', value: s.today_fail ?? 0, cls: s.today_fail ? 'text-destructive' : '' },
  ]

  const statusMeta = {
    running: { label: '运行中', cls: 'bg-success/15 text-success' },
    stopped: { label: '已停止', cls: 'bg-secondary text-muted-foreground' },
    start_failed: { label: '启动失败', cls: 'bg-destructive/15 text-destructive' },
    unconfigured: { label: '未配置', cls: 'bg-secondary text-muted-foreground' },
  }
  const parseMeta = {
    received: { label: '已接收', cls: 'bg-secondary text-muted-foreground' },
    success: { label: '解析成功', cls: 'bg-success/15 text-success' },
    partial: { label: '部分解析', cls: 'bg-warning/15 text-warning' },
    fail: { label: '解析失败', cls: 'bg-destructive/15 text-destructive' },
  }

  const filteredLogs = useMemo(() => {
    return logs.filter((l) =>
      (!logFilters.receiverId || String(l.receiver_id) === String(logFilters.receiverId)) &&
      (!logFilters.parseStatus || l.parse_status === logFilters.parseStatus)
    )
  }, [logs, logFilters])

  return (
    <div className="flex flex-col gap-4">
      {/* 概览卡片 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {statCards.map((c) => (
          <div key={c.label} className="rounded-lg border border-border bg-card/60 p-4">
            <div className="text-xs text-muted-foreground">{c.label}</div>
            <div className={`mt-1 text-2xl font-semibold ${c.cls}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {error && (
        <div className="w-full rounded-md border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* 渠道列表面板 */}
      <div className="rounded-lg border border-border bg-card/60">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium">接收渠道</span>
            <span className="text-xs text-muted-foreground">
              对方设备主动推送日志时在此配置 syslog / kafka 接收方式
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={load} disabled={loading} className="btn-secondary btn-sm">
              {loading ? '刷新中…' : '刷新'}
            </button>
            <button
              type="button"
              onClick={() => { setEditing(null); setFormOpen(true) }}
              className="btn-primary btn-sm"
            >
              <Plus className="mr-1 h-3.5 w-3.5" /> 添加渠道
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-4 py-2">名称 / 设备</th>
                <th className="px-4 py-2">方式</th>
                <th className="px-4 py-2">接入信息</th>
                <th className="px-4 py-2">状态</th>
                <th className="px-4 py-2">接收 / 失败</th>
                <th className="px-4 py-2">最近接收</th>
                <th className="px-4 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {receivers.length === 0 && !loading && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground/70">暂无接收渠道，点击「添加渠道」配置</td></tr>
              )}
              {receivers.map((r) => {
                const st = statusMeta[r.status] || { label: r.status, cls: 'bg-secondary text-muted-foreground' }
                const cfg = r.protocol === 'syslog'
                  ? `${r.syslog_bind || '0.0.0.0'}:${r.syslog_port} (${r.syslog_proto})`
                  : `${r.kafka_topic} ← ${r.kafka_bootstrap}`
                return (
                  <tr key={r.id} className="border-b border-border/60 last:border-0 hover:bg-card/40">
                    <td className="px-4 py-2.5">
                      <div className="font-medium">{r.name}</div>
                      <div className="text-xs text-muted-foreground/70">{r.device_name}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${r.protocol === 'syslog' ? 'bg-primary/15 text-primary' : 'bg-purple-500/15 text-purple-400'}`}>
                        {r.protocol.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">{cfg}</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${st.cls}`}>
                        {r.alive && <span className="h-1.5 w-1.5 rounded-full bg-success" />}
                        {st.label}
                      </span>
                      {r.status === 'start_failed' && r.last_error && (
                        <div
                          className="mt-1 max-w-[260px] break-words font-mono text-[10px] leading-tight text-destructive"
                          title={r.last_error}
                        >
                          {r.last_error}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="text-xs">{r.received_count ?? 0}</span>
                      <span className={`ml-2 text-xs ${r.error_count ? 'text-destructive' : 'text-muted-foreground'}`}>
                        {r.error_count ?? 0}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">
                      {r.last_received_at ? new Date(r.last_received_at).toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        <button type="button" onClick={() => handleReload(r)} className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground" title="应用配置/重启">
                          <RefreshCw className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" onClick={() => { setEditing(r); setFormOpen(true) }} className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground" title="编辑">
                          <Settings className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" onClick={() => handleDelete(r)} className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" title="删除">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 接收指标（按渠道按小时） */}
      <div className="rounded-lg border border-border bg-card/60">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Activity className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">接收指标（最近 24 小时）</span>
        </div>
        {metrics.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground/70">暂无接收指标数据</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2">渠道</th>
                  <th className="px-4 py-2">时段</th>
                  <th className="px-4 py-2">接收</th>
                  <th className="px-4 py-2">成功</th>
                  <th className="px-4 py-2">部分</th>
                  <th className="px-4 py-2">失败</th>
                </tr>
              </thead>
              <tbody>
                {metrics.slice(0, 50).map((m, i) => (
                  <tr key={`${m.receiver_id}-${m.stat_hour}`} className="border-b border-border/60 last:border-0 hover:bg-card/40">
                    <td className="px-4 py-2 text-xs">{m.receiver_name}</td>
                    <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{m.stat_hour}</td>
                    <td className="px-4 py-2 text-xs">{m.total_count ?? 0}</td>
                    <td className="px-4 py-2 text-xs text-success">{m.success_count ?? 0}</td>
                    <td className="px-4 py-2 text-xs text-warning">{m.partial_count ?? 0}</td>
                    <td className="px-4 py-2 text-xs text-destructive">{m.fail_count ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 接收日志明细 */}
      <div className="rounded-lg border border-border bg-card/60">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Inbox className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium">接收日志明细</span>
          </div>
          <div className="flex items-center gap-2">
            <select className={`${inputCls} w-auto py-1 text-xs`} value={logFilters.receiverId} onChange={(e) => setLogFilters((p) => ({ ...p, receiverId: e.target.value }))}>
              <option value="">全部渠道</option>
              {receivers.map((r) => (<option key={r.id} value={r.id}>{r.name}</option>))}
            </select>
            <select className={`${inputCls} w-auto py-1 text-xs`} value={logFilters.parseStatus} onChange={(e) => setLogFilters((p) => ({ ...p, parseStatus: e.target.value }))}>
              <option value="">全部状态</option>
              <option value="success">解析成功</option>
              <option value="partial">部分解析</option>
              <option value="fail">解析失败</option>
              <option value="received">仅接收</option>
            </select>
          </div>
        </div>
        {filteredLogs.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground/70">暂无接收日志</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2">时间</th>
                  <th className="px-4 py-2">设备 / 渠道</th>
                  <th className="px-4 py-2">来源 IP</th>
                  <th className="px-4 py-2">解析状态</th>
                  <th className="px-4 py-2">内容</th>
                  <th className="px-4 py-2">告警</th>
                </tr>
              </thead>
              <tbody>
                {filteredLogs.map((l) => {
                  const pm = parseMeta[l.parse_status] || { label: l.parse_status, cls: 'bg-secondary text-muted-foreground' }
                  return (
                    <tr key={l.id} className="border-b border-border/60 last:border-0 hover:bg-card/40">
                      <td className="px-4 py-2 text-xs text-muted-foreground">{new Date(l.received_at).toLocaleString()}</td>
                      <td className="px-4 py-2 text-xs">{l.device_name}</td>
                      <td className="px-4 py-2 text-xs">{l.source_ip || '—'}</td>
                      <td className="px-4 py-2">
                        <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${pm.cls}`}>{pm.label}</span>
                      </td>
                      <td className="max-w-[220px] truncate px-4 py-2 text-xs text-muted-foreground" title={l.raw_data}>
                        {l.raw_data}
                      </td>
                      <td className="px-4 py-2 text-xs">
                        {l.alert_id ? <span className="text-primary">#{l.alert_id}</span> : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 表单弹窗 */}
      <LogReceiverFormModal
        open={formOpen}
        initial={editing}
        devices={devices}
        onClose={() => { setFormOpen(false); setEditing(null) }}
        onSubmit={handleSubmit}
      />
    </div>
  )
}
