// 工单流程模板编辑页：全屏左右分栏
// - 左栏：节点竖排列表（新增/上移/下移/删除/选中高亮，显示节点类型与绑定分组）
// - 右栏：选中节点编辑（基础信息 / 字段定义增删改 / 流转路由与条件编辑）
// - 顶部：模板名称/描述/发起分组 + 保存（Ctrl+S）/发布；脏状态检测 + 离开二次确认
// - 发布前服务端结构校验失败会以 toast 反馈完整错误
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  GitGraph, Plus, Trash2, ArrowUp, ArrowDown, Save, Rocket, ArrowLeft,
  Flag, ChevronRight, GripVertical, AlertTriangle, UsersRound,
} from 'lucide-react'
import { toast } from '../store/toastStore'
import InfoTip from '../components/InfoTip'
import { CcChips, CcSelectModal, ccKey } from '../components/CcPicker'
import { useUnsavedChanges } from '../hooks/useUnsavedChanges'
import { inputCls, inputBaseCls, labelCls, hintCls } from '../components/property/FormControls'
import { Button, PageContainer, CompactSelect } from '../components/ui'
import { hasPermission } from '../utils/permissions'
import ticketApi from '../api/tickets'

// 字段类型定义
const FIELD_TYPES = [
  { value: 'text', label: '单行文本' },
  { value: 'textarea', label: '富文本' },
  { value: 'number', label: '数字' },
  { value: 'datetime', label: '日期时间' },
  { value: 'select', label: '下拉选择' },
  { value: 'switch', label: '是否开关' },
  { value: 'ip', label: 'IP 地址' },
  { value: 'url', label: 'URL' },
  { value: 'file', label: '附件' },
]

// 告警一键发起时的字段映射来源（AlertEvent 列）
const ALERT_FIELD_OPTIONS = [
  { value: '', label: '不映射' },
  { value: 'alert_name', label: '告警名称' },
  { value: 'occur_timestamp', label: '发生时间' },
  { value: 'device_type', label: '告警平台（设备类型）' },
  { value: 'src_ip', label: '源 IP 地址' },
  { value: 'dst_ip', label: '目标 IP 地址' },
  { value: 'host_ip', label: '主机 IP' },
  { value: 'risk_level_name', label: '风险等级' },
  { value: 'threat_class', label: '威胁大类' },
  { value: 'threat_type', label: '威胁类型' },
  { value: 'attack_state_name', label: '攻击状态' },
  { value: 'description', label: '告警描述' },
  { value: 'recommendation', label: '处置建议' },
  { value: 'src_region_name', label: '源区域' },
  { value: 'dst_region_name', label: '目标区域' },
  { value: 'protocol', label: '协议' },
]

// 生成节点内唯一字段 key
const nextFieldKey = (fields) => {
  let i = fields.length + 1
  const keys = new Set(fields.map((f) => f.key))
  while (keys.has(`f${i}`)) i += 1
  return `f${i}`
}

// 下拉选项编辑器：本地暂存原始文本，失焦时才提交为选项数组。
// 直接受控（split → trim → filter → join 回填）会在按回车时立即清除尾部
// 空行并回写 value，光标被弹回行尾，表现为「回车无法换行」。
function FieldOptionsInput({ value, disabled, onCommit }) {
  const [text, setText] = useState((value || []).join('\n'))
  const focusedRef = useRef(false)

  // 外部选项变化时同步到本地文本（聚焦输入中不覆盖，避免打断编辑）
  useEffect(() => {
    if (!focusedRef.current) setText((value || []).join('\n'))
  }, [value])

  return (
    <textarea
      className={`${inputCls} resize-y`}
      rows={2}
      disabled={disabled}
      placeholder="每行一个选项，如：&#10;是&#10;否"
      value={text}
      onFocus={() => { focusedRef.current = true }}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        focusedRef.current = false
        const opts = text.split('\n').map((s) => s.trim()).filter(Boolean)
        setText(opts.join('\n'))
        onCommit(opts)
      }}
    />
  )
}

export default function TicketFlowEdit() {
  const { id } = useParams()
  const isNew = !id
  const navigate = useNavigate()
  const canEdit = hasPermission('ticket_config', 'edit')

  const [loading, setLoading] = useState(!isNew)
  const [flowId, setFlowId] = useState(id ? Number(id) : null)
  const [meta, setMeta] = useState({ name: '', description: '' })
  const [startGroups, setStartGroups] = useState([])
  const [startPickerOpen, setStartPickerOpen] = useState(false)
  const [ccTargets, setCcTargets] = useState([]) // 模板级固定抄送 [{type, id, name}]
  const [ccPickerOpen, setCcPickerOpen] = useState(false)
  const [nodes, setNodes] = useState([])
  const [selectedKey, setSelectedKey] = useState('')
  // 发布校验失败时定位到问题节点（红框高亮，数秒后自动消除）
  const [invalidKeys, setInvalidKeys] = useState([])
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [initial, setInitial] = useState('')
  const [groups, setGroups] = useState([])

  useEffect(() => {
    ticketApi.listGroups().then((res) => setGroups(res.items || [])).catch(() => {})
  }, [])

  // 发起分组 chips 数据：复用 CcChips 展示（分组徽标 + 超量折叠 +N）
  const startGroupTargets = startGroups
    .map((gid) => groups.find((g) => g.id === gid))
    .filter(Boolean)
    .map((g) => ({ type: 'group', id: g.id, name: g.name }))

  const serialize = useCallback(
    (m, sg, cc, ns) => JSON.stringify({ name: (m.name || '').trim(), description: (m.description || '').trim(), start_groups: sg, cc_targets: cc, nodes: ns }),
    [],
  )

  // 加载 / 初始化
  useEffect(() => {
    if (isNew) {
      const defaultNodes = [
        { key: 'n1', name: '发起节点', type: 'task', group_id: '', fields: [], routes: [{ to: 'n2', label: '', when: null }] },
        { key: 'n2', name: '处理节点', type: 'task', group_id: '', fields: [], routes: [{ to: 'end', label: '', when: null }] },
        { key: 'end', name: '结束', type: 'end', fields: [], routes: [] },
      ]
      setMeta({ name: '', description: '' })
      setStartGroups([])
      setCcTargets([])
      setNodes(defaultNodes)
      setSelectedKey('n1')
      setInitial(serialize({ name: '', description: '' }, [], [], defaultNodes))
      return
    }
    setLoading(true)
    ticketApi.getFlow(id)
      .then((f) => {
        const nj = f.nodes || {}
        const ns = nj.nodes || []
        const m = { name: f.name, description: f.description || '' }
        const sg = nj.start_groups || []
        const cc = nj.cc_targets || []
        setMeta(m)
        setStartGroups(sg)
        setCcTargets(cc)
        setNodes(ns)
        setSelectedKey(ns[0]?.key || '')
        setInitial(serialize(m, sg, cc, ns))
      })
      .catch((e) => { toast.error(e.message || '加载流程模板失败'); navigate('/ticket-config/flows') })
      .finally(() => setLoading(false))
  }, [id, isNew, navigate, serialize])

  const dirty = useMemo(
    () => serialize(meta, startGroups, ccTargets, nodes) !== initial,
    [serialize, meta, startGroups, ccTargets, nodes, initial],
  )

  const payload = useCallback(() => ({
    name: meta.name.trim(),
    description: meta.description.trim(),
    nodes: { start_groups: startGroups, cc_targets: ccTargets, nodes },
  }), [meta, startGroups, ccTargets, nodes])

  const markClean = useCallback(() => {
    setInitial(serialize(meta, startGroups, ccTargets, nodes))
  }, [serialize, meta, startGroups, ccTargets, nodes])

  const handleSave = useCallback(async () => {
    if (!meta.name.trim()) { toast.error('请输入模板名称'); return }
    setSaving(true)
    try {
      if (isNew) {
        const f = await ticketApi.createFlow(payload())
        setFlowId(f.id)
        toast.success('模板已创建（草稿）')
        markClean()
        bypassGuard()
        navigate(`/ticket-config/flows/${f.id}/edit`, { replace: true })
      } else {
        await ticketApi.updateFlow(flowId, payload())
        toast.success('模板已保存（草稿），发布后才能发起工单')
        markClean()
      }
    } catch (e) {
      toast.error(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta, isNew, payload, flowId, markClean, navigate, serialize, startGroups, ccTargets, nodes])

  const bypassGuard = useUnsavedChanges(dirty, { onSave: handleSave })

  const handlePublish = async () => {
    if (!meta.name.trim()) { toast.error('请输入模板名称'); return }
    if (isNew) { toast.error('请先保存模板再发布'); return }
    setPublishing(true)
    try {
      await ticketApi.updateFlow(flowId, payload())
      const f = await ticketApi.publishFlow(flowId)
      markClean()
      toast.success(`发布成功（v${f.version}），现在可以在工单中心发起该流程的工单`)
    } catch (e) {
      // 服务端校验文案形如「第 2 个节点（xx）：未绑定处理分组」，据此高亮定位问题节点
      const msg = e.message || '发布失败，请检查流程结构'
      const idxs = []
      for (const m of msg.matchAll(/第 (\d+) 个节点/g)) {
        const i = Number(m[1]) - 1
        if (nodes[i]) idxs.push(i)
      }
      if (idxs.length) {
        setInvalidKeys(idxs.map((i) => nodes[i].key))
        setSelectedKey(nodes[idxs[0]].key)
        document.querySelector(`[data-nodekey="${nodes[idxs[0]].key}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        setTimeout(() => setInvalidKeys([]), 8000)
      }
      toast.error(msg)
    } finally {
      setPublishing(false)
    }
  }

  // ===== 节点操作 =====
  const taskNodes = nodes.filter((n) => n.type !== 'end')

  const addNode = () => {
    let i = nodes.length + 1
    const keys = new Set(nodes.map((n) => n.key))
    while (keys.has(`n${i}`)) i += 1
    const key = `n${i}`
    const endIdx = nodes.findIndex((n) => n.type === 'end')
    const node = { key, name: `处理节点${i}`, type: 'task', group_id: '', fields: [], routes: [{ to: 'end', label: '', when: null }] }
    const next = [...nodes]
    if (endIdx >= 0) next.splice(endIdx, 0, node)
    else next.push(node)
    setNodes(next)
    setSelectedKey(key)
  }

  const removeNode = (key) => {
    if (nodes.filter((n) => n.type !== 'end').length <= 1) { toast.error('至少保留一个处理节点'); return }
    if (key === 'end') { toast.error('结束节点不可删除'); return }
    const next = nodes
      .filter((n) => n.key !== key)
      .map((n) => ({ ...n, routes: (n.routes || []).filter((r) => r.to !== key) }))
    setNodes(next)
    if (selectedKey === key) setSelectedKey(next.find((n) => n.type !== 'end')?.key || '')
    toast.info('已删除节点，请检查其他节点指向该节点的路由')
  }

  const moveNode = (key, dir) => {
    const idx = nodes.findIndex((n) => n.key === key)
    const target = idx + dir
    if (idx < 0 || target < 0 || target >= nodes.length) return
    if (nodes[idx].type === 'end' || nodes[target].type === 'end') return
    const next = [...nodes]
    ;[next[idx], next[target]] = [next[target], next[idx]]
    setNodes(next)
  }

  const patchNode = (key, patch) => {
    setNodes((ns) => ns.map((n) => (n.key === key ? { ...n, ...patch } : n)))
  }

  const selected = nodes.find((n) => n.key === selectedKey)

  // ===== 字段操作 =====
  const addField = () => {
    if (!selected) return
    const fields = selected.fields || []
    patchNode(selected.key, { fields: [...fields, { key: nextFieldKey(fields), label: '', type: 'text', required: false, options: [], placeholder: '', default: '', alert_field_mapping: '', auto_enrich: true, auto_agent: false }] })
  }

  const patchField = (fkey, patch) => {
    if (!selected) return
    patchNode(selected.key, { fields: (selected.fields || []).map((f) => (f.key === fkey ? { ...f, ...patch } : f)) })
  }

  const removeField = (fkey) => {
    if (!selected) return
    patchNode(selected.key, { fields: (selected.fields || []).filter((f) => f.key !== fkey) })
  }

  // ===== 路由操作 =====
  const addRoute = () => {
    if (!selected) return
    const routes = selected.routes || []
    patchNode(selected.key, { routes: [...routes, { to: 'end', label: '', when: null }] })
  }

  const patchRoute = (idx, patch) => {
    if (!selected) return
    patchNode(selected.key, { routes: (selected.routes || []).map((r, i) => (i === idx ? { ...r, ...patch } : r)) })
  }

  const removeRoute = (idx) => {
    if (!selected) return
    patchNode(selected.key, { routes: (selected.routes || []).filter((_, i) => i !== idx) })
  }

  // 默认路由唯一：勾选新的默认时，旧默认转为条件路由
  const setRouteDefault = (idx, isDefault) => {
    if (!selected) return
    const routes = (selected.routes || []).map((r, i) => {
      if (i === idx) return { ...r, when: isDefault ? null : (r.when || { field: selected.fields?.[0]?.key || '', op: 'eq', value: '' }) }
      if (isDefault && r.when === null) {
        return { ...r, when: { field: selected.fields?.[0]?.key || '', op: 'eq', value: '' } }
      }
      return r
    })
    patchNode(selected.key, { routes })
  }

  const groupName = (gid) => groups.find((g) => g.id === gid)?.name

  if (loading) {
    return (
      <PageContainer>
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">加载中...</div>
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      {/* 顶部两行：行1 基础信息 + 操作；行2 发起分组 / 抄送 配置条（chips 超量折叠，防多选刷屏换行） */}
      <div className="mb-4 rounded-md border border-border bg-card">
        <div className="flex flex-wrap items-center gap-3 px-6 py-4">
          <button onClick={() => navigate('/ticket-config/flows')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />返回
          </button>
          <div className="h-6 w-px bg-border" />
          <input
            className={`${inputBaseCls} h-9 w-56 font-semibold`}
            placeholder="流程模板名称"
            value={meta.name}
            disabled={!canEdit}
            onChange={(e) => setMeta({ ...meta, name: e.target.value })}
          />
          <input
            className={`${inputBaseCls} h-9 min-w-40 flex-1`}
            placeholder="模板描述（选填）"
            value={meta.description}
            disabled={!canEdit}
            onChange={(e) => setMeta({ ...meta, description: e.target.value })}
          />
          <div className="flex shrink-0 items-center gap-2">
            {dirty && (
              <span className="flex items-center gap-1 text-xs text-amber-500">
                <AlertTriangle className="h-3.5 w-3.5" />未保存
              </span>
            )}
            <Button variant="secondary" size="sm" onClick={handlePublish} disabled={!canEdit || publishing || isNew}>
              <Rocket className="mr-1 h-3.5 w-3.5" />{publishing ? '发布中' : '保存并发布'}
            </Button>
            <Button variant="primary" size="sm" onClick={handleSave} disabled={!canEdit || saving}>
              <Save className="mr-1 h-3.5 w-3.5" />{saving ? '保存中' : '保存'}
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-8 gap-y-2 border-t border-border px-6 py-3">
          {/* 发起分组：授权勾选分组（谁能开单）；与节点「处理分组」（谁干活）区分 */}
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-1.5">
            <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-muted-foreground">
              <Flag className="h-3.5 w-3.5" />发起分组
              <InfoTip text="授权勾选分组内的成员可在工单中心使用本流程发起工单（管理员始终可发起）。未勾选任何分组时仅管理员可发起。各环节由谁处理请在下方节点的「处理分组」中配置，与这里无关。" />
            </span>
            <CcChips
              targets={startGroupTargets}
              max={6}
              emptyText="未勾选时，仅管理员可发起"
              onRemove={canEdit ? (t) => setStartGroups((s) => s.filter((x) => x !== t.id)) : undefined}
            />
            {canEdit && (
              <button
                type="button"
                onClick={() => setStartPickerOpen(true)}
                className="flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1 text-xs font-medium text-muted-foreground transition hover:border-primary/60 hover:text-primary"
              >
                <Plus className="h-3 w-3" />选择分组
              </button>
            )}
          </div>
          {/* 模板级固定抄送：该模板发起的所有工单自动抄送给这些对象（人员/分组）；工单中可手动追加或移除 */}
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-1.5">
            <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-muted-foreground">
              <UsersRound className="h-3.5 w-3.5" />抄送
              <InfoTip text="配置该模板发起工单时的固定抄送对象（人员或分组，组内全员均收到抄送）。发起时自动生效，发起人、当前处理人、管理员也可在工单详情中手动追加或移除抄送对象。" />
            </span>
            <CcChips
              targets={ccTargets}
              max={6}
              emptyText="未配置，发起的工单不固定抄送"
              onRemove={canEdit ? (t) => setCcTargets((s) => s.filter((x) => ccKey(x) !== ccKey(t))) : undefined}
            />
            {canEdit && (
              <button
                type="button"
                onClick={() => setCcPickerOpen(true)}
                className="flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1 text-xs font-medium text-muted-foreground transition hover:border-primary/60 hover:text-primary"
              >
                <Plus className="h-3 w-3" />添加抄送
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-start gap-4">
        {/* 左栏：节点列表 */}
        <div className="w-72 shrink-0 rounded-md border border-border bg-card p-3">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-xs font-semibold text-foreground">流程节点（{nodes.length}）</span>
            {canEdit && (
              <button onClick={addNode} className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10">
                <Plus className="h-3.5 w-3.5" />新增节点
              </button>
            )}
          </div>
          <div className="space-y-1">
            {nodes.map((n, idx) => {
              const active = n.key === selectedKey
              const invalid = invalidKeys.includes(n.key)
              return (
                <div key={n.key} data-nodekey={n.key} className="relative">
                  <button
                    onClick={() => setSelectedKey(n.key)}
                    title={invalid ? '该节点存在校验问题，详见发布错误提示' : undefined}
                    className={`flex w-full items-center gap-2.5 rounded-md border px-3 py-2.5 text-left transition ${invalid ? 'border-destructive bg-destructive/5' : active ? 'border-primary bg-primary/5' : 'border-transparent hover:bg-muted'}`}
                  >
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${n.type === 'end' ? 'bg-muted text-muted-foreground' : 'bg-primary/15 text-primary'}`}>
                      {n.type === 'end' ? '✓' : idx + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-foreground">{n.name || n.key}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {n.type === 'end' ? '结束节点' : `${groupName(n.group_id) || '未绑定分组'} · ${(n.fields || []).length} 字段`}
                      </span>
                    </span>
                    {active && <ChevronRight className="h-4 w-4 shrink-0 text-primary" />}
                  </button>
                  {canEdit && n.type !== 'end' && (
                    <div className="absolute right-1.5 top-1.5 flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100 hover:opacity-100" style={{ opacity: active ? 1 : undefined }}>
                      <button onClick={() => moveNode(n.key, -1)} disabled={idx === 0} className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30" title="上移">
                        <ArrowUp className="h-3 w-3" />
                      </button>
                      <button onClick={() => moveNode(n.key, 1)} disabled={nodes[idx + 1]?.type === 'end'} className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30" title="下移">
                        <ArrowDown className="h-3 w-3" />
                      </button>
                      <button onClick={() => removeNode(n.key)} className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" title="删除节点">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* 右栏：节点编辑 */}
        <div className="min-w-0 flex-1 rounded-md border border-border bg-card">
          {!selected ? (
            <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">请选择左侧节点进行编辑</div>
          ) : (
            <div className="p-6">
              {/* 基础信息 */}
              <div className="mb-6">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <GripVertical className="h-4 w-4 text-muted-foreground" />节点基础信息
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className={labelCls}>节点名称<span className="text-red-500">*</span></label>
                    <input className={inputCls} value={selected.name || ''} disabled={!canEdit || selected.type === 'end'}
                      onChange={(e) => patchNode(selected.key, { name: e.target.value })} />
                  </div>
                  <div>
                    <label className={labelCls}>节点标识（key）</label>
                    <input className={`${inputCls} font-mono`} value={selected.key} disabled
                      title="节点标识在流程内唯一且不可修改（已发起工单的快照依赖该标识）" />
                  </div>
                  <div>
                    <label className={labelCls}>处理分组<span className="text-red-500">*</span></label>
                    <CompactSelect size="lg" block disabled={!canEdit || selected.type === 'end'}
                      value={selected.group_id || ''}
                      onChange={(e) => patchNode(selected.key, { group_id: e.target.value ? Number(e.target.value) : '' })}>
                      <option value="">请选择分组</option>
                      {groups.filter((g) => g.enabled).map((g) => (
                        <option key={g.id} value={g.id}>{g.name}（{g.member_count || 0} 人）</option>
                      ))}
                    </CompactSelect>
                    {selected.type === 'end' && <p className={hintCls}>结束节点无需绑定分组</p>}
                  </div>
                </div>
                {selected.type !== 'end' && (
                  <div className="mt-4 grid grid-cols-3 gap-4">
                    <div>
                      <label className={labelCls}>超时提醒（分钟）</label>
                      <input type="number" min="1" className={inputCls} disabled={!canEdit}
                        placeholder="留空 = 不提醒"
                        value={selected.timeout_minutes ?? ''}
                        onChange={(e) => {
                          const v = e.target.value
                          patchNode(selected.key, { timeout_minutes: v === '' ? null : (Number(v) >= 1 ? Math.floor(Number(v)) : '') })
                        }} />
                      <p className={hintCls}>工单停留本节点超过该时长后，通过通知中心提醒处理分组</p>
                    </div>
                    <div>
                      <label className={labelCls}>重复提醒间隔（分钟）</label>
                      <input type="number" min="0" className={inputCls} disabled={!canEdit}
                        placeholder="留空或 0 = 仅提醒一次"
                        value={selected.remind_interval_minutes ?? ''}
                        onChange={(e) => {
                          const v = e.target.value
                          patchNode(selected.key, { remind_interval_minutes: v === '' ? null : (Number(v) >= 0 ? Math.floor(Number(v)) : '') })
                        }} />
                      <p className={hintCls}>超时未处理时按该间隔重复提醒，直到工单流转离开本节点</p>
                    </div>
                  </div>
                )}
              </div>

              {selected.type !== 'end' && (
                <>
                  {/* 字段定义 */}
                  <div className="mb-6">
                    <div className="mb-3 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                        <GripVertical className="h-4 w-4 text-muted-foreground" />节点字段（{(selected.fields || []).length}）
                      </div>
                      {canEdit && (
                        <Button size="sm" variant="secondary" onClick={addField}>
                          <Plus className="mr-1 h-3.5 w-3.5" />添加字段
                        </Button>
                      )}
                    </div>
                    {!(selected.fields || []).length ? (
                      <div className="rounded-md border border-dashed border-border py-6 text-center text-sm text-muted-foreground">
                        暂无字段，点击「添加字段」自定义该节点需填写的内容
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {(selected.fields || []).map((f) => (
                          <div key={f.key} className="rounded-md border border-border p-4">
                            <div className="grid grid-cols-4 gap-3">
                              <div>
                                <label className={labelCls}>显示名<span className="text-red-500">*</span></label>
                                <input className={inputCls} placeholder="如：源IP地址" disabled={!canEdit}
                                  value={f.label || ''} onChange={(e) => patchField(f.key, { label: e.target.value })} />
                              </div>
                              <div>
                                <label className={labelCls}>标识（key）</label>
                                <input className={`${inputCls} font-mono`} disabled={!canEdit}
                                  value={f.key} onChange={(e) => patchField(f.key, { key: e.target.value.trim() })} />
                              </div>
                              <div>
                                <label className={labelCls}>类型</label>
                                <CompactSelect size="lg" block disabled={!canEdit} value={f.type || 'text'}
                                  onChange={(e) => patchField(f.key, { type: e.target.value })}>
                                  {FIELD_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                                </CompactSelect>
                              </div>
                              <div className="flex items-end justify-between gap-2">
                                <label className="flex cursor-pointer items-center gap-2 pb-2">
                                  <input type="checkbox" className="h-4 w-4 accent-primary" disabled={!canEdit}
                                    checked={!!f.required} onChange={(e) => patchField(f.key, { required: e.target.checked })} />
                                  <span className="text-sm text-foreground">必填</span>
                                </label>
                                {canEdit && (
                                  <button onClick={() => removeField(f.key)}
                                    className="mb-1 flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-destructive hover:bg-destructive/10">
                                    <Trash2 className="h-3.5 w-3.5" />删除
                                  </button>
                                )}
                              </div>
                            </div>
                            <div className="mt-3 grid grid-cols-4 gap-3">
                              {f.type === 'select' && (
                                <div className="col-span-2">
                                  <label className={labelCls}>下拉选项（每行一个）</label>
                                  <FieldOptionsInput
                                    value={f.options || []}
                                    disabled={!canEdit}
                                    onCommit={(opts) => patchField(f.key, { options: opts })}
                                  />
                                </div>
                              )}
                              {f.type === 'switch' && (
                                <div>
                                  <label className={labelCls}>取值方式</label>
                                  <input className={inputCls} value="是 / 否" disabled />
                                </div>
                              )}
                              {f.type === 'ip' && (
                                <>
                                  <div>
                                    <label className={labelCls}>自动研判</label>
                                    <label className="flex cursor-pointer items-center gap-2 py-[7px]"
                                      title="发起工单时自动对该 IP 执行资产匹配与威胁情报查询；仅标识（key）或告警字段映射为 src_ip / dst_ip 的字段生效，默认开启">
                                      <input type="checkbox" className="h-4 w-4 accent-primary" disabled={!canEdit}
                                        checked={f.auto_enrich !== false}
                                        onChange={(e) => patchField(f.key, { auto_enrich: e.target.checked })} />
                                      <span className="text-sm text-foreground">资产匹配 + 威胁情报</span>
                                    </label>
                                  </div>
                                  <div>
                                    <label className={labelCls}>智能体研判</label>
                                    <label className="flex cursor-pointer items-center gap-2 py-[7px]"
                                      title="发起工单时调用「IP风险智能研判与封禁决策」智能体研判该 IP，安全上下文仅展示风险等级、处置建议与决策依据；仅标识（key）或告警字段映射为 src_ip / dst_ip 的字段生效，默认关闭，需配置 BAN_ANALYST_AGENT_ID">
                                      <input type="checkbox" className="h-4 w-4 accent-primary" disabled={!canEdit}
                                        checked={f.auto_agent === true}
                                        onChange={(e) => patchField(f.key, { auto_agent: e.target.checked })} />
                                      <span className="text-sm text-foreground">IP 风险智能研判</span>
                                    </label>
                                  </div>
                                </>
                              )}
                              <div>
                                <label className={labelCls}>占位提示</label>
                                <input className={inputCls} disabled={!canEdit} placeholder="选填"
                                  value={f.placeholder || ''} onChange={(e) => patchField(f.key, { placeholder: e.target.value })} />
                              </div>
                              {f.type !== 'select' && f.type !== 'switch' && f.type !== 'file' && (
                                <div>
                                  <label className={labelCls}>默认值</label>
                                  <input className={inputCls} disabled={!canEdit}
                                    value={f.default || ''} onChange={(e) => patchField(f.key, { default: e.target.value })} />
                                </div>
                              )}
                              <div>
                                <label className={labelCls}>告警字段映射</label>
                                <CompactSelect size="lg" block disabled={!canEdit} value={f.alert_field_mapping || ''}
                                  onChange={(e) => patchField(f.key, { alert_field_mapping: e.target.value })}
                                  title="告警一键发起工单时，自动预填该告警字段">
                                  {ALERT_FIELD_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                                </CompactSelect>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* 流转路由 */}
                  <div>
                    <div className="mb-3 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                        <GripVertical className="h-4 w-4 text-muted-foreground" />流转路由（{(selected.routes || []).length}）
                      </div>
                      {canEdit && (
                        <Button size="sm" variant="secondary" onClick={addRoute}>
                          <Plus className="mr-1 h-3.5 w-3.5" />添加路由
                        </Button>
                      )}
                    </div>
                    {!(selected.routes || []).length ? (
                      <div className="rounded-md border border-dashed border-border py-6 text-center text-sm text-muted-foreground">
                        至少配置一条流转路由，否则该节点无法流转
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {(selected.routes || []).map((r, idx) => {
                          const isDefault = r.when === null || r.when === undefined
                          const toNode = nodes.find((n) => n.key === r.to)
                          return (
                            <div key={idx} className="rounded-md border border-border p-4">
                              <div className="flex items-center gap-3">
                                <span className="shrink-0 rounded bg-muted px-2 py-1 text-xs font-medium text-foreground">路由 {idx + 1}</span>
                                <div className="w-48">
                                  <CompactSelect size="lg" block disabled={!canEdit} value={r.to || ''} onChange={(e) => patchRoute(idx, { to: e.target.value })}>
                                    <option value="">选择去向节点</option>
                                    {nodes.map((n) => <option key={n.key} value={n.key}>{n.name || n.key}{n.type === 'end' ? '（结束）' : ''}</option>)}
                                  </CompactSelect>
                                </div>
                                <div className="w-48">
                                  <input className={inputCls} disabled={!canEdit} placeholder="路由名称（如：需应急）"
                                    value={r.label || ''} onChange={(e) => patchRoute(idx, { label: e.target.value })} />
                                </div>
                                <label className="flex shrink-0 cursor-pointer items-center gap-2">
                                  <input type="checkbox" className="h-4 w-4 accent-primary" disabled={!canEdit}
                                    checked={isDefault} onChange={(e) => setRouteDefault(idx, e.target.checked)} />
                                  <span className="text-sm text-foreground">无条件（默认路由）</span>
                                </label>
                                <div className="flex-1" />
                                {toNode && toNode.type !== 'end' && (
                                  <span className="shrink-0 text-xs text-muted-foreground">→ 「{toNode.name}」由「{groupName(toNode.group_id) || '未绑定分组'}」处理</span>
                                )}
                                {canEdit && (
                                  <button onClick={() => removeRoute(idx)}
                                    className="flex shrink-0 items-center gap-1 rounded px-2 py-1 text-xs font-medium text-destructive hover:bg-destructive/10">
                                    <Trash2 className="h-3.5 w-3.5" />删除
                                  </button>
                                )}
                              </div>
                              {!isDefault && (
                                <div className="mt-3 flex items-end gap-3 rounded-md bg-muted p-3">
                                  <div className="w-56">
                                    <label className={labelCls}>判断字段</label>
                                    <CompactSelect size="lg" block disabled={!canEdit} value={r.when?.field || ''}
                                      onChange={(e) => patchRoute(idx, { when: { ...r.when, field: e.target.value } })}>
                                      <option value="">选择本节点字段</option>
                                      {(selected.fields || []).map((f) => (
                                        <option key={f.key} value={f.key}>{f.label || f.key}（{f.key}）</option>
                                      ))}
                                    </CompactSelect>
                                  </div>
                                  <div className="w-36">
                                    <label className={labelCls}>操作符</label>
                                    <CompactSelect size="lg" block disabled={!canEdit} value={r.when?.op || 'eq'}
                                      onChange={(e) => patchRoute(idx, { when: { ...r.when, op: e.target.value } })}>
                                      <option value="eq">等于</option>
                                      <option value="ne">不等于</option>
                                    </CompactSelect>
                                  </div>
                                  <div className="w-48">
                                    <label className={labelCls}>判断值</label>
                                    {(() => {
                                      const cf = (selected.fields || []).find((x) => x.key === r.when?.field)
                                      if (cf && (cf.type === 'select' || cf.type === 'switch')) {
                                        const opts = cf.type === 'switch' ? ['是', '否'] : (cf.options || [])
                                        return (
                                          <CompactSelect size="lg" block disabled={!canEdit} value={r.when?.value ?? ''}
                                            onChange={(e) => patchRoute(idx, { when: { ...r.when, value: e.target.value } })}>
                                            <option value="">请选择</option>
                                            {opts.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
                                          </CompactSelect>
                                        )
                                      }
                                      return (
                                        <input className={inputCls} disabled={!canEdit} placeholder="填写的字段值等于该值时走此路由"
                                          value={r.when?.value ?? ''} onChange={(e) => patchRoute(idx, { when: { ...r.when, value: e.target.value } })} />
                                      )
                                    })()}
                                  </div>
                                  <p className={`${hintCls} flex-1 pb-2`}>
                                    条件路由按从上到下顺序匹配；提交时命中即建议走此路由，处理人可确认调整
                                  </p>
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
      {/* 模板固定抄送选择弹窗：已配置的对象在弹窗中置灰不重复选 */}
      <CcSelectModal
        open={ccPickerOpen}
        onClose={() => setCcPickerOpen(false)}
        title="配置模板固定抄送"
        excludeKeys={ccTargets.map(ccKey)}
        onConfirm={(targets) => setCcTargets((s) => [...s, ...targets.filter((t) => !s.some((x) => ccKey(x) === ccKey(t)))])}
      />
      {/* 发起分组选择弹窗（仅分组）：已授权分组置灰不重复选 */}
      <CcSelectModal
        open={startPickerOpen}
        onClose={() => setStartPickerOpen(false)}
        title="选择发起分组"
        groupsOnly
        excludeKeys={startGroups.map((gid) => `group:${gid}`)}
        onConfirm={(targets) => setStartGroups((s) => {
          const ids = new Set(s)
          targets.forEach((t) => ids.add(t.id))
          return [...ids]
        })}
      />
    </PageContainer>
  )
}
