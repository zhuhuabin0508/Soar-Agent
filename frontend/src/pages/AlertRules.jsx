﻿﻿﻿﻿﻿// 告警规则列表页（XDR 风格重构）：左侧分组树面板（预置分组 + 计数 + 管理）+
// 严格模式提示条（可折叠，本地持久化）+ 统计卡片（可下钻）+ 导入导出 +
// 空状态模板快速开始（预填全屏编辑页，不直接创建）+ 规则表格
// （分组/类型文案/统计摘要/聚合标签/草稿徽标/拖拽排序/启停二次确认/
//   命中数下钻/疑似失效标记/复制/批量操作）
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity, AlertTriangle, BellOff, Check, ChevronDown, Copy, Download, FolderPlus, GripVertical,
  Layers, ListFilter, Pencil, Plus, ShieldCheck, Trash2, Upload, X,
} from 'lucide-react'

import { alertRuleApi, alertRuleGroupApi } from '../api/alert'
import { confirm } from '../components/ConfirmDialog'
import { inputBaseCls } from '../components/property/FormControls'
import { Badge, Button, DataTable, PageContainer, PageHeader } from '../components/ui'
import { toast } from '../store/toastStore'
import { hasPermission } from '../utils/permissions'
import AlertRuleHitsDrawer from './AlertRuleHitsDrawer'
import {
  ACTION_META, condSummary, absTime, aggregationSummary, fmtTime, relTime, ruleTypeLabel,
  statsSummary,
} from './alertRuleMeta'

// 统计卡片（紧凑布局；clickable 点击下钻）
function StatCard({ icon: Icon, label, value, sub, onClick, clickable, title, active, tone }) {
  return (
    <div
      className={`card flex items-center gap-3 px-5 py-4 ${clickable ? `cursor-pointer transition hover:border-primary/40 hover:shadow-md ${active ? 'border-primary/40 ring-1 ring-primary/20' : ''}` : ''}`}
      onClick={clickable ? onClick : undefined}
      role={clickable ? 'button' : undefined}
      title={clickable ? (title || '点击查看') : undefined}
    >
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
        tone === 'danger' ? 'bg-destructive/10 text-destructive' : 'bg-primary/10 text-primary'
      }}`}>
        <Icon size={18} />
      </div>
      <div className="min-w-0">
        <div className="truncate text-xs text-muted-foreground">{label}</div>
        <div className="mt-0.5 flex items-baseline gap-1.5">
          <span className={`text-xl font-semibold tabular-nums ${tone === 'danger' ? 'text-destructive' : 'text-foreground'}`}>{value}</span>
          {sub && <span className="text-[11px] text-muted-foreground">{sub}</span>}
        </div>
      </div>
    </div>
  )
}

// 启停开关（仅点击开关本身生效；停用需二次确认）
function StatusToggle({ checked, disabled, onChange }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => { e.stopPropagation(); if (!disabled) onChange(!checked) }}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
        checked ? 'bg-primary' : 'bg-muted-foreground/30'
      } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:opacity-80'}`}
      title={checked ? '点击停用' : '点击启用'}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-[18px]' : 'translate-x-0.5'
        }`}
      />
    </button>
  )
}

// 今日零点（与告警列表快捷「今日」同一格式）
const todayStart = () => {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T00:00:00`
}

export default function AlertRules() {
  const navigate = useNavigate()
  const canEdit = hasPermission('alert', 'handle')

  const [list, setList] = useState([])
  const [groups, setGroups] = useState([])
  const [stats, setStats] = useState(null)
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(false)
  const [togglingId, setTogglingId] = useState(null)

  // 筛选：搜索 / 分组 / 类型 / 状态（含草稿）/ 统计卡下钻（stale=24h 无命中）
  const [search, setSearch] = useState('')
  const [groupFilter, setGroupFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [cardFilter, setCardFilter] = useState('')
  const [selectedKeys, setSelectedKeys] = useState([])

  // 分组管理：管理模式 + 新建输入 + 行内重命名
  const [groupManage, setGroupManage] = useState(false)
  const [groupCreating, setGroupCreating] = useState(false)
  const [groupNewName, setGroupNewName] = useState('')
  const [groupRenamingId, setGroupRenamingId] = useState(null)
  const [groupRenameValue, setGroupRenameValue] = useState('')
  const [groupBusy, setGroupBusy] = useState(false)

  // 导入
  const fileRef = useRef(null)
  const [importing, setImporting] = useState(false)

  // 命中抽屉过滤条件
  const [hitsFilter, setHitsFilter] = useState(null)

  // 严格模式提示条折叠状态（本地持久化；默认收起，仅用户展开过才保持展开）
  const [bannerOpen, setBannerOpen] = useState(
    () => localStorage.getItem('alert-rules-banner') === 'open',
  )
  const toggleBanner = () => {
    setBannerOpen((v) => {
      localStorage.setItem('alert-rules-banner', v ? 'collapsed' : 'open')
      return !v
    })
  }

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([alertRuleApi.list(), alertRuleApi.stats(), alertRuleGroupApi.list()])
      .then(([res, s, gs]) => {
        setList(res.items || [])
        setStats(s || {})
        setGroups(gs.items || [])
      })
      .catch((e) => toast.error(e.message || '加载失败'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // 空状态模板卡片（后端配置，便于扩展）
  useEffect(() => {
    if (!loading && list.length === 0 && templates.length === 0) {
      alertRuleApi.templates()
        .then((res) => setTemplates(res.items || []))
        .catch(() => { /* 模板加载失败不阻塞页面 */ })
    }
  }, [loading, list.length, templates.length])

  const filtering = !!search || !!groupFilter || !!actionFilter || !!statusFilter || !!cardFilter
  const filteredList = useMemo(() => {
    let rows = list
    if (search) rows = rows.filter((r) => r.name.toLowerCase().includes(search.toLowerCase()))
    if (groupFilter === '__draft__') rows = rows.filter((r) => r.draft)
    else if (groupFilter) rows = rows.filter((r) => (r.group || '其他') === groupFilter)
    if (actionFilter) rows = rows.filter((r) => r.action === actionFilter)
    if (statusFilter === 'draft') rows = rows.filter((r) => r.draft)
    else if (statusFilter) rows = rows.filter((r) => (statusFilter === 'enabled' ? r.enabled : !r.enabled))
    if (cardFilter === 'stale') rows = rows.filter((r) => r.enabled && !r.draft && !r.has_hit_24h)
    return rows
  }, [list, search, groupFilter, actionFilter, statusFilter, cardFilter])

  // ===== 编辑跳转（全屏页；模板/复制经 state.initial 预填）=====
  const goCreate = (initial = null) => navigate('/alert-rules/new', initial ? { state: { initial } } : undefined)
  const goEdit = (row) => navigate(`/alert-rules/${row.id}/edit`)

  // ===== 启停（停用二次确认：说明停用后不再命中）=====
  const doToggle = (row, next) => {
    setTogglingId(row.id)
    alertRuleApi.toggle(row.id)
      .then(() => {
        toast.success(next ? `已启用「${row.name}」` : `已停用「${row.name}」，该规则不再命中`)
        load()
      })
      .catch((e) => toast.error(e.message || '操作失败'))
      .finally(() => setTogglingId(null))
  }
  const handleToggle = (row, next) => {
    if (next) { doToggle(row, next); return }
    confirm({
      title: '停用规则',
      message: `确认停用「${row.name}」？停用后该规则不再命中；严格模式下，仅命中该规则的日志将不再产生告警（仅保留接收明细）。`,
      variant: 'warning',
      confirmText: '停用',
    }).then((ok) => { if (ok) doToggle(row, next) })
  }

  // ===== 删除（确认文案含规则名 + 今日命中数）=====
  const handleDelete = (row) => {
    const todayHits = row.today_hits || 0
    confirm({
      title: '删除规则',
      message: `确认删除规则「${row.name}」？${todayHits > 0 ? `该规则今日已命中 ${todayHits} 次，` : ''}删除后立即失效且不可恢复。`,
      variant: 'danger',
      confirmText: '删除',
    }).then((ok) => {
      if (!ok) return
      alertRuleApi.remove(row.id)
        .then(() => { toast.success('规则已删除'); load() })
        .catch((e) => toast.error(e.message || '删除失败'))
    })
  }

  // ===== 拖拽排序（乐观更新，失败回滚）=====
  const handleReorder = (fromIdx, toIdx) => {
    if (fromIdx === toIdx) return
    const prev = [...list]
    const next = [...list]
    const [moved] = next.splice(fromIdx, 1)
    next.splice(toIdx, 0, moved)
    setList(next)
    alertRuleApi.reorder(next.map((r) => r.id))
      .then(() => {
        toast.success('排序已保存')
        load()
      })
      .catch((e) => {
        setList(prev) // 回滚
        toast.error(e.message || '排序保存失败，已回滚')
      })
  }

  // ===== 批量操作 =====
  const runBatch = (op) => {
    const fn = () => alertRuleApi.batch(selectedKeys, op)
      .then((res) => {
        toast.success(`已批量${op === 'enable' ? '启用' : op === 'disable' ? '停用' : '删除'} ${res.affected} 条规则`)
        setSelectedKeys([])
        load()
      })
      .catch((e) => toast.error(e.message || '批量操作失败'))
    if (op === 'delete') {
      confirm({
        title: '批量删除规则',
        message: `确认删除选中的 ${selectedKeys.length} 条规则？删除后立即失效且不可恢复。`,
        variant: 'danger',
        confirmText: '删除',
      }).then((ok) => { if (ok) fn() })
    } else fn()
  }

  // ===== 导出（JSON 全量，含草稿）=====
  const handleExport = () => {
    alertRuleApi.export()
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `alert-rules-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.json`
        a.click()
        URL.revokeObjectURL(url)
        toast.success('规则已导出')
      })
      .catch((e) => toast.error(e.message || '导出失败'))
  }

  // ===== 导入（重名跳过；导入规则均为草稿态需自行发布）=====
  const handleImportFile = (e) => {
    const file = e.target.files?.[0]
    e.target.value = '' // 允许重复选择同一文件
    if (!file) return
    setImporting(true)
    const reader = new FileReader()
    reader.onload = () => {
      let rules = []
      try {
        const data = JSON.parse(reader.result)
        rules = Array.isArray(data) ? data : (data.items || data.rules || [])
      } catch {
        toast.error('文件不是合法 JSON')
        setImporting(false)
        return
      }
      if (!Array.isArray(rules) || !rules.length) {
        toast.error('文件中没有可导入的规则')
        setImporting(false)
        return
      }
      alertRuleApi.import(rules)
        .then((res) => {
          const parts = [`导入 ${res.imported} 条`]
          if (res.skipped?.length) parts.push(`跳过 ${res.skipped.length} 条（重名）`)
          if (res.errors?.length) parts.push(`失败 ${res.errors.length} 条`)
          if (res.imported > 0) toast.success(`${parts.join('，')}；导入规则为草稿态，测试通过后发布`)
          else toast.warning(parts.join('，'))
          if (res.errors?.length) console.warn('[alert-rules] 导入失败明细：', res.errors)
          load()
        })
        .catch((err) => toast.error(err.message || '导入失败'))
        .finally(() => setImporting(false))
    }
    reader.readAsText(file)
  }

  // ===== 分组管理 =====
  const createGroup = () => {
    const name = groupNewName.trim()
    if (!name) { toast.error('分组名称不能为空'); return }
    setGroupBusy(true)
    alertRuleGroupApi.create(name)
      .then(() => { toast.success(`分组「${name}」已创建`); setGroupCreating(false); setGroupNewName(''); load() })
      .catch((e) => toast.error(e.message || '创建失败'))
      .finally(() => setGroupBusy(false))
  }
  const renameGroup = (g) => {
    const name = groupRenameValue.trim()
    if (!name || name === g.name) { setGroupRenamingId(null); return }
    setGroupBusy(true)
    alertRuleGroupApi.rename(g.id, name)
      .then(() => {
        toast.success(`分组已重命名为「${name}」`)
        if (groupFilter === g.name) setGroupFilter(name)
        setGroupRenamingId(null)
        load()
      })
      .catch((e) => toast.error(e.message || '重命名失败'))
      .finally(() => setGroupBusy(false))
  }
  const removeGroup = (g) => {
    confirm({
      title: '删除分组',
      message: `确认删除分组「${g.name}」？该分组下的 ${g.count} 条规则将移入「其他」，规则本身不会被删除。`,
      variant: 'warning',
      confirmText: '删除分组',
    }).then((ok) => {
      if (!ok) return
      alertRuleGroupApi.remove(g.id)
        .then(() => {
          toast.success('分组已删除，规则已移入「其他」')
          if (groupFilter === g.name) setGroupFilter('')
          load()
        })
        .catch((e) => toast.error(e.message || '删除失败'))
    })
  }

  // ===== 统计卡下钻 =====
  const clearFilters = () => { setSearch(''); setGroupFilter(''); setActionFilter(''); setStatusFilter(''); setCardFilter('') }
  const goTodayAlerts = () => navigate(`/alerts?start_time=${todayStart()}`)

  const columns = useMemo(() => {
    const cols = []
    if (canEdit && !filtering) {
      cols.push({
        key: '__drag', header: '', width: '36px',
        render: () => (
          <span className="flex cursor-grab items-center text-muted-foreground/50 hover:text-foreground" title="拖拽调整优先级（越小越先匹配）">
            <GripVertical className="h-4 w-4" />
          </span>
        ),
      })
    }
    cols.push(
      {
        key: 'name', header: '规则名称', width: '17%',
        render: (r) => (
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <button
                className="max-w-full truncate text-left text-[13px] font-medium text-foreground transition hover:text-primary"
                title={r.description || r.name}
                onClick={(e) => { e.stopPropagation(); goEdit(r) }}
              >
                {r.name}
              </button>
              {r.draft ? (
                <Badge variant="warning" className="shrink-0" >草稿</Badge>
              ) : !r.enabled ? (
                <Badge variant="neutral" className="shrink-0">已停用</Badge>
              ) : null}
            </div>
            {r.enabled && !r.draft && !r.has_hit_24h && (
              <span
                className="mt-1 inline-flex items-center gap-1 text-[11px] text-warning"
                title="该规则启用中但近 24 小时零命中。可能原因：条件过严 / 数据源断流 / 被更高优先级规则抢先命中"
              >
                <AlertTriangle className="h-3 w-3" />疑似失效
              </span>
            )}
          </div>
        ),
      },
      {
        key: 'group', header: '分组', width: '92px',
        render: (r) => (
          <span className="inline-flex max-w-full items-center rounded border border-border/70 bg-muted/40 px-1.5 py-0.5 text-[11.5px] text-muted-foreground" title={`分组：${r.group || '其他'}`}>
            <span className="truncate">{r.group || '其他'}</span>
          </span>
        ),
      },
      {
        key: 'type', header: '类型', width: '118px',
        render: (r) => (
          <div className="flex flex-wrap items-center gap-1">
            <span className={r.type === 'stats' ? 'text-[12px] font-medium text-primary' : 'text-[12px] text-foreground'}>
              {ruleTypeLabel(r)}
            </span>
            {r.type !== 'stats' && r.action !== 'alert' && (
              <Badge variant={ACTION_META[r.action]?.variant || 'neutral'}>{ACTION_META[r.action]?.label || r.action}</Badge>
            )}
          </div>
        ),
      },
      {
        key: 'conditions', header: '匹配条件 / 统计配置', width: '26%',
        render: (r) => {
          if (r.type === 'stats') {
            const summary = statsSummary(r)
            return (
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                <span
                  className="inline-flex max-w-full items-center gap-1 rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-[11.5px] text-primary"
                  title={`统计配置：${summary}；筛选条件：${condSummary(r) || '（无）'}`}
                >
                  <span className="truncate">{summary || '--'}</span>
                </span>
                {r.alert_aggregation?.keys?.length > 0 && (
                  <span
                    className="inline-flex shrink-0 items-center gap-1 rounded border border-border/70 bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                    title={`告警聚合：${aggregationSummary(r.alert_aggregation)}`}
                  >
                    <Layers className="h-3 w-3" />聚合
                  </span>
                )}
              </div>
            )
          }
          const summary = condSummary(r)
          return (
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="block max-w-[300px] truncate text-[12.5px] text-muted-foreground" title={summary}>
                {summary || '--'}
              </span>
              {r.alert_aggregation?.keys?.length > 0 && (
                <span
                  className="inline-flex shrink-0 items-center gap-1 rounded border border-border/70 bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                  title={`告警聚合：${aggregationSummary(r.alert_aggregation)}`}
                >
                  <Layers className="h-3 w-3" />聚合
                </span>
              )}
            </div>
          )
        },
      },
      { key: 'priority', header: '优先级', width: '72px', numeric: true, render: (r) => <span className="font-mono text-[12.5px]">{r.priority}</span> },
      {
        key: 'enabled', header: '状态', width: '72px',
        render: (r) => (
          <StatusToggle
            checked={r.enabled}
            disabled={!canEdit || togglingId === r.id}
            onChange={(next) => handleToggle(r, next)}
          />
        ),
      },
      {
        key: 'today_hits', header: '今日命中', width: '84px', numeric: true,
        render: (r) => (
          <button
            className={`font-mono text-[12.5px] tabular-nums transition hover:text-primary ${r.today_hits > 0 ? 'text-foreground' : 'text-muted-foreground/60'}`}
            title="点击查看今日命中日志"
            onClick={(e) => { e.stopPropagation(); setHitsFilter({ ruleId: r.id, ruleName: r.name, today: true }) }}
          >
            {r.today_hits || 0}
          </button>
        ),
      },
      {
        key: 'hit_count', header: '累计命中', width: '84px', numeric: true,
        render: (r) => (
          <button
            className={`font-mono text-[12.5px] tabular-nums transition hover:text-primary ${r.hit_count > 0 ? 'text-foreground' : 'text-muted-foreground/60'}`}
            title="点击查看近 7 天命中日志"
            onClick={(e) => { e.stopPropagation(); setHitsFilter({ ruleId: r.id, ruleName: r.name }) }}
          >
            {r.hit_count || 0}
          </button>
        ),
      },
      {
        key: 'last_hit_at', header: '最近触发', width: '104px',
        render: (r) => (
          <span className="text-[12.5px] text-muted-foreground" title={absTime(r.last_hit_at)}>
            {relTime(r.last_hit_at)}
          </span>
        ),
      },
      {
        key: 'updated_at', header: '更新时间', width: '142px',
        render: (r) => (
          <div className="text-[12px] leading-tight">
            <div className="text-muted-foreground">{fmtTime(r.updated_at)}</div>
            {r.updated_by && <div className="mt-0.5 text-[11px] text-muted-foreground/70">{r.updated_by}</div>}
          </div>
        ),
      },
    )
    if (canEdit) {
      cols.push({
        key: '__ops', header: '操作', width: '112px',
        render: (r) => (
          <div className="flex items-center gap-1">
            <button className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-foreground" title={r.draft ? '编辑草稿（测试通过后发布）' : '编辑'}
              onClick={(e) => { e.stopPropagation(); goEdit(r) }}>
              <Pencil className="h-4 w-4" />
            </button>
            <button className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-foreground" title="复制为新规则"
              onClick={(e) => { e.stopPropagation(); goCreate({ ...r, id: undefined, name: `${r.name}（副本）`, draft: true }) }}>
              <Copy className="h-4 w-4" />
            </button>
            <button className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-destructive" title="删除"
              onClick={(e) => { e.stopPropagation(); handleDelete(r) }}>
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ),
      })
    }
    return cols
  }, [canEdit, filtering, togglingId, list]) // eslint-disable-line react-hooks/exhaustive-deps

  const s = stats || {}
  const totalRules = groups.reduce((acc, g) => acc + (g.count || 0), 0)
  const draftCount = list.filter((r) => r.draft).length

  return (
    <PageContainer>
      <PageHeader
        title="告警规则"
        description="解析成功的日志命中规则后才产生告警（严格模式）；按优先级从小到大匹配，首条命中即停"
        actions={canEdit && list.length > 0 ? (
          <div className="flex items-center gap-2">
            <input ref={fileRef} type="file" accept=".json,application/json" className="hidden" onChange={handleImportFile} />
            <Button variant="secondary" onClick={() => fileRef.current?.click()} disabled={importing}>
              <Upload className="mr-1.5 h-4 w-4" />{importing ? '导入中…' : '导入'}
            </Button>
            <Button variant="secondary" onClick={handleExport}>
              <Download className="mr-1.5 h-4 w-4" />导出
            </Button>
            <Button onClick={() => goCreate()}>
              <Plus className="mr-1.5 h-4 w-4" />新建规则
            </Button>
          </div>
        ) : undefined}
      />

      <div className="flex items-start gap-4">
        {/* ===== 左侧分组树面板 ===== */}
        <aside className="card hidden w-56 shrink-0 p-3 lg:block">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-[12.5px] font-semibold text-foreground">规则分组</span>
            {canEdit && (
              <button
                className={`flex h-6 items-center gap-1 rounded px-1.5 text-[11.5px] transition ${groupManage ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground'}`}
                title={groupManage ? '退出分组管理' : '管理分组（新建 / 重命名 / 删除）'}
                onClick={() => { setGroupManage((v) => !v); setGroupCreating(false); setGroupRenamingId(null) }}
              >
                {groupManage ? <X className="h-3 w-3" /> : null}{groupManage ? '完成' : '管理'}
              </button>
            )}
          </div>
          <div className="space-y-0.5">
            {/* 全部 */}
            <button
              className={`flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-[12.5px] transition ${!groupFilter ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground'}`}
              onClick={() => setGroupFilter('')}
            >
              <span>全部规则</span>
              <span className="font-mono text-[11.5px] tabular-nums opacity-80">{totalRules}</span>
            </button>
            {/* 草稿 */}
            <button
              className={`flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-[12.5px] transition ${groupFilter === '__draft__' ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground'}`}
              onClick={() => setGroupFilter(groupFilter === '__draft__' ? '' : '__draft__')}
              title="未发布的草稿规则（不参与线上匹配）"
            >
              <span className="flex items-center gap-1.5">草稿箱{draftCount > 0 && <Badge variant="warning">{draftCount}</Badge>}</span>
              <span className="font-mono text-[11.5px] tabular-nums opacity-80">{draftCount}</span>
            </button>
            <div className="my-1.5 border-t border-border/60" />
            {/* 各分组 */}
            {groups.map((g) => {
              const active = groupFilter === g.name
              if (groupRenamingId === g.id) {
                return (
                  <div key={g.id} className="flex items-center gap-1 px-1 py-1">
                    <input
                      autoFocus className={`${inputBaseCls} h-7 min-w-0 flex-1 px-2 text-[12px]`}
                      value={groupRenameValue} maxLength={64}
                      onChange={(e) => setGroupRenameValue(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') renameGroup(g); if (e.key === 'Escape') setGroupRenamingId(null) }}
                    />
                    <button className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-success transition hover:bg-accent" title="确认重命名"
                      onClick={() => renameGroup(g)}>
                      <Check className="h-3.5 w-3.5" />
                    </button>
                    <button className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition hover:bg-accent" title="取消"
                      onClick={() => setGroupRenamingId(null)}>
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )
              }
              return (
                <div key={g.id} className="flex items-center gap-0.5">
                  <button
                    className={`flex min-w-0 flex-1 items-center justify-between rounded-md px-2.5 py-1.5 text-[12.5px] transition ${active ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground'}`}
                    onClick={() => setGroupFilter(active ? '' : g.name)}
                    title={g.name === '其他' ? '默认分组（不可删除）' : undefined}
                  >
                    <span className="max-w-[110px] truncate">{g.name}</span>
                    <span className="font-mono text-[11.5px] tabular-nums opacity-80">{g.count}</span>
                  </button>
                  {groupManage && (
                    <button className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-foreground"
                      title="重命名分组"
                      onClick={() => { setGroupRenamingId(g.id); setGroupRenameValue(g.name) }}>
                      <Pencil className="h-3 w-3" />
                    </button>
                  )}
                  {groupManage && g.name !== '其他' && (
                    <button className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition hover:bg-accent hover:text-destructive"
                      title="删除分组（规则移入「其他」）"
                      onClick={() => removeGroup(g)}>
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                </div>
              )
            })}
            {/* 新建分组 */}
            {canEdit && (groupManage || groupCreating) && (
              groupCreating ? (
                <div className="flex items-center gap-1 px-1 py-1">
                  <input
                    autoFocus className={`${inputBaseCls} h-7 min-w-0 flex-1 px-2 text-[12px]`}
                    value={groupNewName} maxLength={64} placeholder="分组名称"
                    onChange={(e) => setGroupNewName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') createGroup(); if (e.key === 'Escape') setGroupCreating(false) }}
                  />
                  <button className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-success transition hover:bg-accent" title="确认创建"
                    onClick={createGroup}>
                    <Check className="h-3.5 w-3.5" />
                  </button>
                  <button className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition hover:bg-accent" title="取消"
                    onClick={() => { setGroupCreating(false); setGroupNewName('') }}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <button
                  className="flex w-full items-center gap-1.5 rounded-md border border-dashed border-border px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:border-primary/50 hover:text-primary"
                  onClick={() => setGroupCreating(true)}
                >
                  <FolderPlus className="h-3.5 w-3.5" />新建分组
                </button>
              )
            )}
          </div>
        </aside>

        {/* ===== 右侧主列 ===== */}
        <div className="min-w-0 flex-1 space-y-4">
          {/* 严格模式提示条（可折叠，状态本地持久化） */}
          <div className="rounded-lg border border-warning/30 bg-warning/5">
            <div className="flex items-center gap-2.5 px-4 py-2.5 text-[12.5px]">
              <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
              <span className="min-w-0 flex-1">
                <span className="font-medium text-warning">严格模式：</span>
                <span className="text-muted-foreground">未命中规则的日志不会产生告警，仅保留接收明细</span>
                <button className="ml-2 text-primary hover:underline" onClick={toggleBanner}>
                  了解模式区别
                </button>
              </span>
              <button
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition hover:bg-accent"
                title={bannerOpen ? '收起' : '展开'}
                onClick={toggleBanner}
              >
                <ChevronDown className={`h-4 w-4 transition-transform ${bannerOpen ? 'rotate-180' : ''}`} />
              </button>
            </div>
            {bannerOpen && (
              <div className="grid grid-cols-1 gap-3 border-t border-warning/20 px-4 py-3 text-[12px] leading-relaxed md:grid-cols-2">
                <div className="rounded-md border border-border/60 bg-background/60 p-3">
                  <div className="mb-1 font-medium text-foreground">严格模式（当前）</div>
                  <div className="text-muted-foreground">
                    解析成功的日志必须命中至少一条启用中的「产生告警 / 调整等级」规则才写入告警列表。
                    例：只配置了「高危及以上」规则时，低危日志仅保留接收明细，不产生告警。
                  </div>
                </div>
                <div className="rounded-md border border-border/60 bg-background/60 p-3">
                  <div className="mb-1 font-medium text-foreground">宽松模式</div>
                  <div className="text-muted-foreground">
                    解析成功的日志默认全部产生告警，规则仅用于抑制或调整。
                    例：刚接入设备想先看全量告警，可使用「全部告警（宽松兜底）」模板达到类似效果。
                  </div>
                  <div className="mt-1.5 text-[11px] text-muted-foreground/70">当前平台仅支持严格模式。</div>
                </div>
              </div>
            )}
          </div>

          {/* 空状态：模板快速开始 */}
          {!loading && list.length === 0 ? (
            <div className="flex flex-col items-center py-8">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <ShieldCheck className="h-7 w-7" />
              </div>
              <h3 className="mt-4 text-base font-semibold">还没有告警规则</h3>
              <p className="mt-1.5 max-w-md text-center text-[13px] text-muted-foreground">
                严格模式下，解析成功的日志需要命中规则才会产生告警。从下方模板快速开始，或从空白创建。
              </p>
              <div className="mt-6 grid w-full max-w-4xl grid-cols-1 gap-4 px-6 md:grid-cols-2 xl:grid-cols-3">
                {templates.map((t) => (
                  <div
                    key={t.key}
                    className="group relative flex flex-col rounded-xl border border-border/60 bg-card p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md"
                  >
                    {t.recommended && (
                      <span className="absolute -top-2 right-3 rounded-full bg-primary px-2 py-0.5 text-[10.5px] font-medium text-primary-foreground">
                        推荐
                      </span>
                    )}
                    <div className="text-[13.5px] font-semibold">{t.name}</div>
                    <div className="mt-1.5 text-[12px] leading-relaxed text-muted-foreground">{t.description}</div>
                    <div className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground/70">{t.hit_note}</div>
                    <Button
                      className="mt-3 w-full"
                      variant={t.recommended ? 'primary' : 'secondary'}
                      onClick={() => goCreate(t.payload)}
                    >
                      使用此模板
                    </Button>
                  </div>
                ))}
              </div>
              {canEdit && (
                <button
                  className="mt-5 text-[13px] text-primary transition hover:underline"
                  onClick={() => goCreate()}
                >
                  + 从空白创建
                </button>
              )}
            </div>
          ) : (
            <>
              {/* 统计卡片（可点击下钻） */}
              <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
                <StatCard icon={ListFilter} label="规则总数" value={s.total ?? '--'} sub={s.enabled != null ? `启用 ${s.enabled} 条` : ''}
                  clickable title="点击查看全部规则" active={!filtering}
                  onClick={clearFilters} />
                <StatCard icon={Activity} label="今日告警生成数" value={s.today_alerts ?? '--'}
                  clickable title="跳转告警列表（今日已产生）" onClick={goTodayAlerts} />
                <StatCard icon={BellOff} label="今日抑制数" value={s.today_suppressed ?? '--'}
                  clickable title="查看抑制命中记录"
                  onClick={() => setHitsFilter({ action: 'suppress', today: true, ruleName: '抑制类规则' })} />
                <StatCard icon={AlertTriangle} label="24h 无命中启用规则" value={s.stale_count ?? '--'}
                  clickable tone={s.stale_count > 0 ? 'danger' : undefined}
                  title="启用但近 24 小时零命中的规则（可能条件过严或数据源断流）"
                  active={cardFilter === 'stale'}
                  onClick={() => setCardFilter(cardFilter === 'stale' ? '' : 'stale')} />
              </div>

              {/* 筛选工具行 + 批量操作 */}
              <div className="card flex flex-wrap items-center gap-2.5 px-4 py-3">
                <input
                  className={`${inputBaseCls} h-9 w-52`} placeholder="搜索规则名称"
                  value={search} onChange={(e) => setSearch(e.target.value)} />
                <select className={`${inputBaseCls} h-9 w-36`} value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
                  <option value="">全部类型</option>
                  {Object.entries(ACTION_META).map(([v, m]) => <option key={v} value={v}>{m.label}</option>)}
                </select>
                <select className={`${inputBaseCls} h-9 w-32`} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  <option value="">全部状态</option>
                  <option value="enabled">启用中</option>
                  <option value="disabled">已停用</option>
                  <option value="draft">草稿</option>
                </select>
                {groupFilter && (
                  <button className="flex h-9 items-center gap-1.5 rounded-md border border-primary/50 bg-primary/5 px-3 text-[12px] text-primary transition hover:bg-primary/10"
                    onClick={() => setGroupFilter('')}>
                    {groupFilter === '__draft__' ? '草稿箱' : groupFilter} <span className="text-[13px] leading-none">×</span>
                  </button>
                )}
                {cardFilter === 'stale' && (
                  <button className="flex h-9 items-center gap-1.5 rounded-md border border-warning/50 bg-warning/10 px-3 text-[12px] text-warning transition hover:bg-warning/20"
                    onClick={() => setCardFilter('')}>
                    疑似失效筛选 <span className="text-[13px] leading-none">×</span>
                  </button>
                )}
                {canEdit && selectedKeys.length > 0 && (
                  <div className="ml-auto flex items-center gap-2">
                    <span className="text-[12px] text-muted-foreground">已选 {selectedKeys.length} 条</span>
                    <Button variant="secondary" size="sm" onClick={() => runBatch('enable')}>批量启用</Button>
                    <Button variant="secondary" size="sm" onClick={() => runBatch('disable')}>批量停用</Button>
                    <Button variant="danger" size="sm" onClick={() => runBatch('delete')}>批量删除</Button>
                  </div>
                )}
              </div>

              {/* 规则表格 */}
              <div className="card p-0">
                <DataTable
                  columns={columns}
                  data={filteredList}
                  rowKey="id"
                  loading={loading}
                  emptyText={filtering ? '没有符合条件的规则' : '暂无告警规则'}
                  emptyDescription={filtering ? '调整筛选条件后重试' : '点击右上角「新建规则」或使用模板快速开始'}
                  draggable={canEdit && !filtering}
                  onReorder={handleReorder}
                  selectable={canEdit}
                  selectedKeys={selectedKeys}
                  onSelectChange={setSelectedKeys}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {/* 命中记录抽屉 */}
      <AlertRuleHitsDrawer open={!!hitsFilter} filter={hitsFilter} onClose={() => setHitsFilter(null)} />
    </PageContainer>
  )
}
