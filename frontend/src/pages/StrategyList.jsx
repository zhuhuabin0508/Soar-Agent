// 解析模板列表页：统计卡片 + 模板表格（启停开关 / 编辑 / 测试 / 删除）
// 「今日解析量」为 0 时给出原因提示（暂无条目引用 / 模板已停用 / 今日暂无日志到达）
// 「今日失败数」可点击打开错误抽屉，按模板过滤查看失败样本原文
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, FlaskConical, Pencil, Trash2, ShieldAlert, Activity, Layers, Inbox, FileJson, Download, Upload, X } from 'lucide-react'
import { toast } from '../store/toastStore'
import { confirm } from '../components/ConfirmDialog'
import { Modal, Drawer } from '../components/Dialog'
import { inputBaseCls } from '../components/property/FormControls'
import { Button, PageContainer, PageHeader, Card, DataTable, Badge, EmptyState, Sparkline } from '../components/ui'
import { hasPermission } from '../utils/permissions'
import strategyApi from '../api/strategy'

// 统计卡片（紧凑布局，数值 tabular-nums；clickable 点击下钻筛选列表；spark 24h 迷你趋势线）
function StatCard({ icon: Icon, label, value, sub, onClick, clickable, title, active, spark }) {
  return (
    <div
      className={`card flex items-center gap-3 px-5 py-4 ${clickable ? `cursor-pointer transition hover:border-primary/40 hover:shadow-md ${active ? 'border-primary/40 ring-1 ring-primary/20' : ''}` : ''}`}
      onClick={clickable ? onClick : undefined}
      role={clickable ? 'button' : undefined}
      title={clickable ? (title || '点击查看') : undefined}
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-[18px] w-[18px]" />
      </div>
      <div className="min-w-0">
        <div className="truncate text-xs text-muted-foreground">{label}</div>
        <div className="mt-0.5 flex items-baseline gap-1.5">
          <span className="text-xl font-semibold tabular-nums text-foreground">{value}</span>
          {sub && <span className="text-[11px] text-muted-foreground">{sub}</span>}
        </div>
      </div>
      {spark && <Sparkline data={spark} className="ml-auto text-primary/60" />}
    </div>
  )
}

// 启停开关（仅点击开关本身生效）
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

const fmtTime = (t) => (t ? String(t).replace('T', ' ').slice(0, 19) : '-')

export default function StrategyList() {
  const navigate = useNavigate()
  const canEdit = hasPermission('strategy', 'edit')
  const canDelete = hasPermission('strategy', 'delete')

  const [list, setList] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [togglingId, setTogglingId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  // 错误队列抽屉（按类型过滤）
  const [errorDrawer, setErrorDrawer] = useState(null) // { error_type }
  const [errors, setErrors] = useState([])
  const [errorsTotal, setErrorsTotal] = useState(0)
  const [errorsPage, setErrorsPage] = useState(1)
  const [errorsLoading, setErrorsLoading] = useState(false)
  // 失败样本原文查看
  const [sampleView, setSampleView] = useState(null)

  // 失败样本下钻抽屉（成功率 / 今日失败数列点击：原因四分类 + 按原因筛选）
  const [drill, setDrill] = useState(null) // { strategyId, name }
  const [drillData, setDrillData] = useState(null)
  const [drillReason, setDrillReason] = useState('')
  const [drillPage, setDrillPage] = useState(1)
  const [drillLoading, setDrillLoading] = useState(false)

  // 模板导入弹窗：选择 .json 文件 → 解析预览 → 确认导入（冲突自动重命名）
  const [importOpen, setImportOpen] = useState(false)
  const [importParsed, setImportParsed] = useState(null) // { payload, names, count }
  const [importing, setImporting] = useState(false)
  const fileInputRef = useRef(null)

  // 统计卡片下钻筛选：''=全部 enabled=启用 today_active=今日有解析量
  const [cardFilter, setCardFilter] = useState('')
  const CARD_FILTER_LABELS = { enabled: '启用模板', today_active: '今日有解析量' }
  const filteredList = useMemo(() => {
    if (cardFilter === 'enabled') return list.filter((r) => r.status === 'enabled')
    if (cardFilter === 'today_active') return list.filter((r) => (r.today_total ?? 0) > 0)
    return list
  }, [list, cardFilter])

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([strategyApi.list(), strategyApi.stats()])
      .then(([items, s]) => { setList(items || []); setStats(s || {}) })
      .catch((e) => toast.error(e.message || '加载失败'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const loadErrors = useCallback((errorType, page = 1, strategyId = 0) => {
    setErrorsLoading(true)
    strategyApi.errors({ error_type: errorType, strategy_id: strategyId, page, page_size: 15 })
      .then((res) => { setErrors(res.items || []); setErrorsTotal(res.total || 0); setErrorsPage(page) })
      .catch((e) => toast.error(e.message || '错误队列加载失败'))
      .finally(() => setErrorsLoading(false))
  }, [])

  const openErrorDrawer = (errorType, strategyId = 0, title = '') => {
    setErrorDrawer({ error_type: errorType, strategy_id: strategyId, title })
    loadErrors(errorType, 1, strategyId)
  }

  // 失败样本下钻：原因四分类统计 + 按原因筛选 + 分页
  const loadDrill = useCallback((sid, reason, page) => {
    setDrillLoading(true)
    strategyApi.failureSamples(sid, { reason, page, page_size: 15 })
      .then((res) => { setDrillData(res); setDrillPage(page) })
      .catch((e) => toast.error(e.message || '失败样本加载失败'))
      .finally(() => setDrillLoading(false))
  }, [])

  const openDrill = (row) => {
    setDrill({ strategyId: row.id, name: row.strategy_name })
    setDrillReason('')
    setDrillData(null)
    loadDrill(row.id, '', 1)
  }

  const applyDrillReason = (reason) => {
    const next = reason === drillReason ? '' : reason
    setDrillReason(next)
    if (drill) loadDrill(drill.strategyId, next, 1)
  }

  const handleToggle = (row, next) => {
    setTogglingId(row.id)
    strategyApi.toggleStatus(row.id, next ? 'enabled' : 'disabled')
      .then(() => {
        toast.success(next ? `已启用「${row.strategy_name}」` : `已停用「${row.strategy_name}」`)
        load()
      })
      .catch((e) => toast.error(e.message || '操作失败'))
      .finally(() => setTogglingId(null))
  }

  const handleDelete = (row) => {
    confirm({
      title: '删除解析模板',
      message: `确认删除模板「${row.strategy_name}」？删除后引用它的数据源条目与接收器将回退为自动匹配，该设备类型的告警将无法解析（进入错误队列）。若已有关联告警记录将禁止删除。`,
      variant: 'danger',
      confirmText: '删除',
    }).then((ok) => {
      if (!ok) return
      setDeletingId(row.id)
      strategyApi.remove(row.id)
        .then(() => { toast.success('模板已删除'); load() })
        .catch((e) => toast.error(e.message || '删除失败'))
        .finally(() => setDeletingId(null))
    })
  }

  // 导出模板为 JSON 文件下载
  const handleExport = (row) => {
    const token = localStorage.getItem('soar_token')
    fetch(strategyApi.exportUrl(row.id), { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (!r.ok) return r.json().then((j) => { throw new Error(j.detail || '导出失败') })
        return r.blob()
      })
      .then((blob) => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `${row.strategy_name}.json`
        a.click()
        URL.revokeObjectURL(a.href)
        toast.success(`已导出「${row.strategy_name}」`)
      })
      .catch((e) => toast.error(e.message || '导出失败'))
  }

  // 导入：选择 .json 文件后解析预览（单对象或数组）
  const handleImportFile = (file) => {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result || ''))
        const items = Array.isArray(parsed) ? parsed : [parsed]
        const names = items.map((it) => it?.strategy_name || '(未命名)')
        setImportParsed({
          payload: Array.isArray(parsed) ? { configs: parsed } : { config: parsed },
          names,
          count: items.length,
        })
      } catch (e) {
        toast.error('文件不是合法的 JSON')
        setImportParsed(null)
      }
    }
    reader.onerror = () => toast.error('文件读取失败')
    reader.readAsText(file)
  }

  const handleImportSubmit = () => {
    if (!importParsed) return
    setImporting(true)
    strategyApi.import(importParsed.payload)
      .then((res) => {
        const renamed = (res.items || []).filter((it) => it.renamed_from).length
        toast.success(`成功导入 ${res.imported} 个模板${renamed ? `，其中 ${renamed} 个因名称冲突已自动重命名` : ''}`)
        setImportOpen(false)
        setImportParsed(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
        load()
      })
      .catch((e) => toast.error(e.message || '导入失败'))
      .finally(() => setImporting(false))
  }

  const columns = [
    {
      key: 'strategy_name',
      header: '模板名称',
      width: '230px',
      render: (r) => (
        <button
          className="flex items-center gap-2 text-left transition hover:text-primary"
          onClick={() => navigate(`/strategies/${r.id}/edit`)}
          title={r.has_draft ? `${r.strategy_name}（存在未发布草稿）` : r.strategy_name}
        >
          <FileJson className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="max-w-[150px] truncate font-medium">{r.strategy_name}</span>
          {r.has_draft && <Badge variant="warning" className="shrink-0">草稿</Badge>}
        </button>
      ),
    },
    { key: 'device_type', header: '设备类型', width: '120px', render: (r) => <span className="truncate text-muted-foreground">{r.device_type || '-'}</span> },
    {
      key: 'version', header: '版本', width: '70px',
      render: (r) => (
        <span className="tabular-nums" title={`配置版本 ${r.version || '-'}；发布号 v${r.published_version_no ?? '-'}`}>
          v{r.published_version_no ?? '-'}
        </span>
      ),
    },
    {
      key: 'status', header: '状态', width: '100px',
      render: (r) => (
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <StatusToggle
            checked={r.status === 'enabled'}
            disabled={!canEdit || togglingId === r.id}
            onChange={(next) => handleToggle(r, next)}
          />
          <span className={`text-xs ${r.status === 'enabled' ? 'text-success' : 'text-muted-foreground'}`}>
            {r.status === 'enabled' ? '启用' : '停用'}
          </span>
        </div>
      ),
    },
    {
      // 引用条目数：条目级绑定为主，另注明被多少接收器设为默认模板
      key: 'entry_count', header: '引用条目数', width: '120px', numeric: true,
      render: (r) => (
        <div className="min-w-0">
          <span className={`tabular-nums ${(r.entry_count ?? 0) > 0 ? '' : 'text-muted-foreground/50'}`}>{(r.entry_count ?? 0).toLocaleString()}</span>
          {(r.receiver_count ?? 0) > 0 && (
            <div className="text-[10px] leading-tight text-muted-foreground/70" title={`另有 ${r.receiver_count} 个接收器将其设为默认模板`}>
              另 {r.receiver_count} 接收器默认
            </div>
          )}
        </div>
      ),
    },
    {
      // 今日解析量为 0 时给出原因提示：无引用 / 已停用 / 今日无日志到达
      key: 'today_total', header: '今日解析量', width: '130px', numeric: true,
      render: (r) => {
        const n = r.today_total ?? 0
        if (n > 0) return <span className="tabular-nums">{n.toLocaleString()}</span>
        const reason = (r.entry_count ?? 0) === 0 && (r.receiver_count ?? 0) === 0
          ? '暂无条目引用'
          : r.status !== 'enabled'
            ? '模板已停用'
            : '今日暂无日志到达'
        return (
          <div>
            <span className="tabular-nums text-muted-foreground/50">0</span>
            <div className="text-[10px] leading-tight text-muted-foreground/70" title={reason}>{reason}</div>
          </div>
        )
      },
    },
    {
      // 今日失败数 > 0 时可点击下钻：失败样本 + 原因四分类统计
      key: 'today_fail', header: '今日失败数', width: '100px', numeric: true,
      render: (r) => {
        const n = r.today_fail ?? 0
        if (n > 0) {
          return (
            <button
              type="button"
              className="tabular-nums text-destructive transition hover:underline"
              title={`查看「${r.strategy_name}」的失败样本与原因分类`}
              onClick={(e) => { e.stopPropagation(); openDrill(r) }}
            >
              {n.toLocaleString()}
            </button>
          )
        }
        return <span className="tabular-nums text-muted-foreground/50">0</span>
      },
    },
    {
      // 成功率可点击：下钻查看失败样本 + 失败原因分类（无匹配模板/字段缺失/校验不通过/格式异常）
      key: 'today_success_rate', header: '成功率', width: '85px', numeric: true,
      render: (r) => (r.today_success_rate == null
        ? <span className="text-muted-foreground">-</span>
        : (
          <button
            type="button"
            className="transition hover:underline"
            title={`查看「${r.strategy_name}」的失败样本与原因分类`}
            onClick={(e) => { e.stopPropagation(); openDrill(r) }}
          >
            <Badge variant={r.today_success_rate >= 95 ? 'success' : r.today_success_rate >= 80 ? 'warning' : 'danger'}>{r.today_success_rate}%</Badge>
          </button>
        )),
    },
    { key: 'updated_at', header: '更新时间', width: '150px', render: (r) => <span className="tabular-nums text-muted-foreground">{fmtTime(r.updated_at)}</span> },
    {
      key: 'actions', header: '操作', width: '190px',
      render: (r) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary"
            title="测试解析"
            onClick={() => navigate(`/strategies/${r.id}/edit?tab=test`)}
          >
            <FlaskConical className="h-4 w-4" />
          </button>
          <button
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary"
            title="导出为 JSON 文件"
            onClick={() => handleExport(r)}
          >
            <Download className="h-4 w-4" />
          </button>
          {canEdit && (
            <button
              className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary"
              title="编辑"
              onClick={() => navigate(`/strategies/${r.id}/edit`)}
            >
              <Pencil className="h-4 w-4" />
            </button>
          )}
          {canDelete && (
            <button
              className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-destructive"
              title="删除"
              disabled={deletingId === r.id}
              onClick={() => handleDelete(r)}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <PageContainer>
      <PageHeader
        title="解析模板"
        description="管理解析模板：路由匹配、字段映射、枚举翻译与校验规则，由数据源条目或接收器引用后生效，配置即接入无需改代码"
        actions={canEdit && (
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => { setImportOpen(true); setImportParsed(null) }}>
              <Upload className="h-4 w-4" /> 导入模板
            </Button>
            <Button variant="primary" onClick={() => navigate('/strategies/new')}>
              <Plus className="h-4 w-4" /> 新建模板
            </Button>
          </div>
        )}
      />

      {/* 顶部统计卡片（可点击下钻：筛选列表 / 打开错误队列） */}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon={Layers}
          label="启用模板数"
          value={stats?.enabled_count ?? 0}
          sub={`/ 共 ${stats?.strategy_count ?? 0} 个`}
          clickable
          active={cardFilter === 'enabled'}
          title="筛选启用中的模板（点击查看）"
          onClick={() => setCardFilter((v) => (v === 'enabled' ? '' : 'enabled'))}
        />
        <StatCard icon={Activity} label="接入设备类型数" value={stats?.device_type_count ?? 0} />
        <StatCard
          icon={FileJson}
          label="今日总解析量"
          value={stats?.today_total ?? 0}
          spark={stats?.trend_24h}
          clickable
          active={cardFilter === 'today_active'}
          title="筛选今日有解析量的模板（点击查看）"
          onClick={() => setCardFilter((v) => (v === 'today_active' ? '' : 'today_active'))}
        />
        <StatCard
          icon={ShieldAlert}
          label="今日无匹配模板告警"
          value={stats?.today_no_match ?? 0}
          clickable
          title="查看无匹配模板的错误队列（点击查看）"
          onClick={() => openErrorDrawer('no_strategy_matched')}
        />
      </div>

      {/* 模板表格 */}
      <Card className="p-0" bodyClassName="p-0">
        {cardFilter && (
          <div className="flex items-center justify-end border-b border-border px-4 py-2">
            <button
              type="button"
              onClick={() => setCardFilter('')}
              title="清除筛选，显示全部模板"
              className="flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs text-primary transition hover:bg-primary/20"
            >
              筛选：{CARD_FILTER_LABELS[cardFilter]} · {filteredList.length}/{list.length}
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
        <DataTable
          columns={columns}
          data={filteredList}
          loading={loading}
          rowKey="id"
          emptyText="暂无解析模板"
          emptyDescription="新建模板后，数据源条目或接收器即可引用，设备日志按模板解析入库"
          emptyIcon={FileJson}
          emptyAction={canEdit && (
            <Button variant="primary" size="sm" onClick={() => navigate('/strategies/new')}>
              <Plus className="h-4 w-4" /> 新建模板
            </Button>
          )}
        />
      </Card>

      {/* 模板导入弹窗：选择 JSON 文件 → 结构预览 → 确认导入（后端校验 + 冲突自动重命名） */}
      <Modal
        open={importOpen}
        title="导入解析模板"
        onClose={() => { if (!importing) setImportOpen(false) }}
        size="md"
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button size="sm" variant="secondary" disabled={importing} onClick={() => setImportOpen(false)}>取消</Button>
            <Button size="sm" variant="primary" disabled={!importParsed || importing} onClick={handleImportSubmit}>
              {importing ? '导入中…' : importParsed ? `导入 ${importParsed.count} 个模板` : '导入'}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-4 py-8 text-center transition hover:border-primary/50 hover:bg-primary/5">
            <Upload className="h-8 w-8 text-muted-foreground" />
            <span className="text-sm text-foreground">点击选择 .json 文件</span>
            <span className="text-xs text-muted-foreground">支持单模板对象或模板数组，结构与「导出为 JSON」的文件一致</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              disabled={importing}
              onChange={(e) => handleImportFile(e.target.files?.[0])}
            />
          </label>
          {importParsed && (
            <div className="rounded-lg border border-border bg-card/60 px-4 py-3">
              <div className="text-xs text-muted-foreground">
                已识别 <span className="font-medium text-foreground">{importParsed.count}</span> 个模板：
              </div>
              <ul className="mt-1.5 flex max-h-40 flex-col gap-1 overflow-auto text-sm">
                {importParsed.names.map((n, i) => (
                  <li key={i} className="flex items-center gap-2 truncate">
                    <FileJson className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate text-foreground">{n}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-2 text-xs text-muted-foreground/70">与现有模板同名时将自动重命名（追加「(导入N)」后缀）；结构非法将整体拒绝。</div>
            </div>
          )}
        </div>
      </Modal>

      {/* 错误队列抽屉（Modal 实现，按错误类型 / 模板过滤） */}
      <Modal
        open={!!errorDrawer}
        title={errorDrawer?.title ? `失败样本 · ${errorDrawer.title}` : '解析错误队列'}
        onClose={() => setErrorDrawer(null)}
        size="xl"
        footer={
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              共 {errorsTotal} 条 · {errorDrawer?.title ? `模板「${errorDrawer.title}」的解析失败样本` : '仅展示解析失败/无匹配的原始数据'}
            </span>
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={errorsPage <= 1 || errorsLoading} onClick={() => loadErrors(errorDrawer?.error_type, errorsPage - 1, errorDrawer?.strategy_id)}>上一页</Button>
              <Button size="sm" disabled={errorsPage * 15 >= errorsTotal || errorsLoading} onClick={() => loadErrors(errorDrawer?.error_type, errorsPage + 1, errorDrawer?.strategy_id)}>下一页</Button>
            </div>
          </div>
        }
      >
        {errorsLoading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">加载中…</div>
        ) : errors.length === 0 ? (
          <EmptyState icon={Inbox} title="暂无错误记录" description="当前过滤条件下没有解析失败的告警" />
        ) : (
          <DataTable
            rowKey="id"
            data={errors}
            columns={[
              { key: 'uuid', header: 'UUID', width: '170px', render: (r) => <span className="truncate text-muted-foreground">{r.uuid || '-'}</span> },
              { key: 'error_type', header: '错误类型', width: '150px', render: (r) => <Badge variant="danger">{r.error_type}</Badge> },
              { key: 'error_msg', header: '错误信息', render: (r) => <span className="block max-w-[340px] truncate" title={r.error_msg}>{r.error_msg}</span> },
              { key: 'status', header: '状态', width: '85px', render: (r) => <Badge variant={r.status === 'resolved' ? 'success' : 'warning'}>{r.status}</Badge> },
              { key: 'created_at', header: '时间', width: '150px', render: (r) => <span className="tabular-nums text-muted-foreground">{fmtTime(r.created_at)}</span> },
              {
                key: 'sample', header: '样本', width: '70px',
                render: (r) => (
                  <button
                    type="button"
                    className="rounded px-1.5 py-0.5 text-[11px] text-primary transition hover:bg-primary/10"
                    title="查看失败样本原文"
                    onClick={(e) => { e.stopPropagation(); setSampleView(r) }}
                  >
                    查看
                  </button>
                ),
              },
            ]}
          />
        )}
      </Modal>

      {/* 失败样本下钻抽屉（成功率 / 今日失败数列点击）：原因四分类 + 按原因筛选 */}
      <Drawer
        open={!!drill}
        title={drill ? `失败样本下钻 · ${drill.name}` : ''}
        onClose={() => setDrill(null)}
        width="w-[760px]"
        footer={drillData && (
          <div className="flex w-full items-center justify-between">
            <span className="text-xs text-muted-foreground">
              共 {drillData.total} 条{drillReason ? ` · 已按「${drillData.reason_labels?.[drillReason] || drillReason}」筛选` : ' · 点击上方原因标签可筛选'}
            </span>
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={drillPage <= 1 || drillLoading} onClick={() => loadDrill(drill.strategyId, drillReason, drillPage - 1)}>上一页</Button>
              <Button size="sm" disabled={drillPage * 15 >= drillData.total || drillLoading} onClick={() => loadDrill(drill.strategyId, drillReason, drillPage + 1)}>下一页</Button>
            </div>
          </div>
        )}
      >
        {drillLoading && !drillData ? (
          <div className="py-10 text-center text-sm text-muted-foreground">加载中…</div>
        ) : !drillData ? (
          <EmptyState icon={Inbox} title="暂无失败样本" description="该模板没有解析失败的原始日志留存" />
        ) : (
          <div className="space-y-4">
            {/* 原因分类统计（点击筛选，再点取消） */}
            <div className="flex flex-wrap items-center gap-2">
              {Object.entries(drillData.stats || {}).map(([k, n]) => {
                const active = drillReason === k
                return (
                  <button
                    key={k}
                    type="button"
                    className={`rounded-full border px-3 py-1.5 text-xs transition ${
                      active ? 'border-primary bg-primary/10 font-medium text-primary' : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'
                    }`}
                    title="点击按此原因筛选"
                    onClick={() => applyDrillReason(k)}
                  >
                    {drillData.reason_labels?.[k] || k}
                    <span className={`ml-1.5 tabular-nums ${n > 0 ? (k === 'no_template' || k === 'other' ? 'text-destructive' : 'text-warning') : 'text-muted-foreground/50'}`}>
                      {n.toLocaleString()}
                    </span>
                  </button>
                )
              })}
            </div>

            {/* 样本列表 */}
            {(drillData.items || []).length === 0 ? (
              <EmptyState icon={Inbox} title="当前筛选条件下没有失败样本" description="更换原因分类或清除筛选查看全部" />
            ) : (
              <div className="overflow-hidden rounded-lg border border-border">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-border bg-muted/50 text-left text-muted-foreground">
                      <th className="px-2 py-2 font-semibold">失败原因</th>
                      <th className="px-2 py-2 font-semibold">错误类型</th>
                      <th className="px-2 py-2 font-semibold">错误信息</th>
                      <th className="px-2 py-2 font-semibold">时间</th>
                      <th className="px-2 py-2 font-semibold">原文</th>
                    </tr>
                  </thead>
                  <tbody>
                    {drillData.items.map((it) => (
                      <tr key={it.id} className="border-b border-border/40 transition last:border-0 hover:bg-accent/30">
                        <td className="px-2 py-2"><Badge variant="danger">{it.reason_label}</Badge></td>
                        <td className="px-2 py-2 font-mono text-muted-foreground">{it.error_type || '-'}</td>
                        <td className="max-w-[260px] truncate px-2 py-2 text-muted-foreground" title={it.error_msg}>{it.error_msg || '-'}</td>
                        <td className="px-2 py-2 tabular-nums text-muted-foreground">{fmtTime(it.created_at)}</td>
                        <td className="px-2 py-2">
                          <button
                            type="button"
                            className="rounded px-1.5 py-0.5 text-[11px] text-primary transition hover:bg-primary/10"
                            title="查看失败样本原始日志"
                            onClick={() => setSampleView({ error_type: it.error_type, error_msg: it.reason_label ? `${it.reason_label} · ${it.error_msg || ''}` : it.error_msg, raw_data: it.raw_data })}
                          >
                            查看
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* 失败样本原文查看 */}
      <Modal
        open={!!sampleView}
        title="失败样本原文"
        onClose={() => setSampleView(null)}
        size="lg"
      >
        <div className="space-y-3">
          <div className="flex items-start gap-2 text-xs text-muted-foreground">
            <Badge variant="danger">{sampleView?.error_type}</Badge>
            <span className="min-w-0 flex-1 break-all">{sampleView?.error_msg}</span>
          </div>
          <pre className="max-h-[420px] overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed break-all whitespace-pre-wrap">
            {sampleView?.raw_data || '（无原始数据）'}
          </pre>
        </div>
      </Modal>
    </PageContainer>
  )
}
