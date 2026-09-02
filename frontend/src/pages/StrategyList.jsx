// 解析策略列表页：统计卡片 + 策略表格（启停开关 / 编辑 / 测试 / 删除）
// 点击「今日无匹配策略」卡片打开错误队列抽屉（按 no_strategy_matched 过滤）
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, FlaskConical, Pencil, Trash2, ShieldAlert, Activity, Layers, Inbox, FileJson } from 'lucide-react'
import { toast } from '../store/toastStore'
import { confirm } from '../components/ConfirmDialog'
import { Modal } from '../components/Dialog'
import { inputBaseCls } from '../components/property/FormControls'
import { Button, PageContainer, PageHeader, Card, DataTable, Badge, EmptyState } from '../components/ui'
import { hasPermission } from '../utils/permissions'
import strategyApi from '../api/strategy'

// 统计卡片（紧凑布局，数值 tabular-nums）
function StatCard({ icon: Icon, label, value, sub, onClick, clickable }) {
  return (
    <div
      className={`card flex items-center gap-3 px-5 py-4 ${clickable ? 'cursor-pointer transition hover:border-primary/40 hover:shadow-md' : ''}`}
      onClick={clickable ? onClick : undefined}
      role={clickable ? 'button' : undefined}
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-4.5 w-4.5" size={18} />
      </div>
      <div className="min-w-0">
        <div className="truncate text-xs text-muted-foreground">{label}</div>
        <div className="mt-0.5 flex items-baseline gap-1.5">
          <span className="text-xl font-semibold tabular-nums text-foreground">{value}</span>
          {sub && <span className="text-[11px] text-muted-foreground">{sub}</span>}
        </div>
      </div>
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

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([strategyApi.list(), strategyApi.stats()])
      .then(([items, s]) => { setList(items || []); setStats(s || {}) })
      .catch((e) => toast.error(e.message || '加载失败'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const loadErrors = useCallback((errorType, page = 1) => {
    setErrorsLoading(true)
    strategyApi.errors({ error_type: errorType, page, page_size: 15 })
      .then((res) => { setErrors(res.items || []); setErrorsTotal(res.total || 0); setErrorsPage(page) })
      .catch((e) => toast.error(e.message || '错误队列加载失败'))
      .finally(() => setErrorsLoading(false))
  }, [])

  const openErrorDrawer = (errorType) => {
    setErrorDrawer({ error_type: errorType })
    loadErrors(errorType, 1)
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
      title: '删除解析策略',
      message: `确认删除策略「${row.strategy_name}」？删除后该设备类型的告警将无法解析（进入错误队列）。若已有关联告警记录将禁止删除。`,
      variant: 'danger',
      confirmText: '删除',
    }).then((ok) => {
      if (!ok) return
      setDeletingId(row.id)
      strategyApi.remove(row.id)
        .then(() => { toast.success('策略已删除'); load() })
        .catch((e) => toast.error(e.message || '删除失败'))
        .finally(() => setDeletingId(null))
    })
  }

  const columns = [
    {
      key: 'strategy_name',
      header: '策略名称',
      width: '260px',
      render: (r) => (
        <button
          className="flex items-center gap-2 text-left transition hover:text-primary"
          onClick={() => navigate(`/strategies/${r.id}/edit`)}
          title={r.strategy_name}
        >
          <FileJson className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="max-w-[220px] truncate font-medium">{r.strategy_name}</span>
        </button>
      ),
    },
    { key: 'device_type', header: '设备类型', width: '140px', render: (r) => <span className="truncate text-muted-foreground">{r.device_type || '-'}</span> },
    { key: 'version', header: '版本', width: '80px', render: (r) => <span className="tabular-nums">v{r.version || '-'}</span> },
    {
      key: 'status', header: '状态', width: '110px',
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
    { key: 'today_total', header: '今日解析量', width: '110px', numeric: true, render: (r) => <span className="tabular-nums">{r.today_total ?? 0}</span> },
    {
      key: 'today_fail', header: '今日失败数', width: '110px', numeric: true,
      render: (r) => (
        <span className={`tabular-nums ${(r.today_fail ?? 0) > 0 ? 'text-destructive' : ''}`}>{r.today_fail ?? 0}</span>
      ),
    },
    {
      key: 'today_success_rate', header: '成功率', width: '90px', numeric: true,
      render: (r) => (r.today_success_rate == null
        ? <span className="text-muted-foreground">-</span>
        : <Badge variant={r.today_success_rate >= 95 ? 'success' : r.today_success_rate >= 80 ? 'warning' : 'danger'}>{r.today_success_rate}%</Badge>),
    },
    { key: 'updated_at', header: '更新时间', width: '160px', render: (r) => <span className="tabular-nums text-muted-foreground">{fmtTime(r.updated_at)}</span> },
    {
      key: 'actions', header: '操作', width: '150px',
      render: (r) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary"
            title="测试解析"
            onClick={() => navigate(`/strategies/${r.id}/edit?tab=test`)}
          >
            <FlaskConical className="h-4 w-4" />
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
        title="解析策略"
        description="管理告警解析策略：路由匹配、字段映射、枚举翻译与校验规则，配置即接入无需改代码"
        actions={canEdit && (
          <Button variant="primary" onClick={() => navigate('/strategies/new')}>
            <Plus className="h-4 w-4" /> 新建策略
          </Button>
        )}
      />

      {/* 顶部统计卡片 */}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icon={Layers} label="启用策略数" value={stats?.enabled_count ?? 0} sub={`/ 共 ${stats?.strategy_count ?? 0} 个`} />
        <StatCard icon={Activity} label="接入设备类型数" value={stats?.device_type_count ?? 0} />
        <StatCard icon={FileJson} label="今日总解析量" value={stats?.today_total ?? 0} />
        <StatCard
          icon={ShieldAlert}
          label="今日无匹配策略告警"
          value={stats?.today_no_match ?? 0}
          clickable
          onClick={() => openErrorDrawer('no_strategy_matched')}
        />
      </div>

      {/* 策略表格 */}
      <Card className="p-0" bodyClassName="p-0">
        <DataTable
          columns={columns}
          data={list}
          loading={loading}
          rowKey="id"
          emptyText="暂无解析策略"
          emptyDescription="新建策略后，设备推送的告警即可按策略解析入库"
          emptyIcon={FileJson}
          emptyAction={canEdit && (
            <Button variant="primary" size="sm" onClick={() => navigate('/strategies/new')}>
              <Plus className="h-4 w-4" /> 新建策略
            </Button>
          )}
        />
      </Card>

      {/* 错误队列抽屉（Modal 实现，按错误类型过滤） */}
      <Modal
        open={!!errorDrawer}
        title="解析错误队列"
        onClose={() => setErrorDrawer(null)}
        size="xl"
        footer={
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">共 {errorsTotal} 条 · 仅展示解析失败/无匹配的原始数据</span>
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={errorsPage <= 1 || errorsLoading} onClick={() => loadErrors(errorDrawer?.error_type, errorsPage - 1)}>上一页</Button>
              <Button size="sm" disabled={errorsPage * 15 >= errorsTotal || errorsLoading} onClick={() => loadErrors(errorDrawer?.error_type, errorsPage + 1)}>下一页</Button>
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
              { key: 'uuid', header: 'UUID', width: '200px', render: (r) => <span className="truncate text-muted-foreground">{r.uuid || '-'}</span> },
              { key: 'error_type', header: '错误类型', width: '160px', render: (r) => <Badge variant="danger">{r.error_type}</Badge> },
              { key: 'error_msg', header: '错误信息', render: (r) => <span className="block max-w-[400px] truncate" title={r.error_msg}>{r.error_msg}</span> },
              { key: 'status', header: '状态', width: '90px', render: (r) => <Badge variant={r.status === 'resolved' ? 'success' : 'warning'}>{r.status}</Badge> },
              { key: 'created_at', header: '时间', width: '160px', render: (r) => <span className="tabular-nums text-muted-foreground">{fmtTime(r.created_at)}</span> },
            ]}
          />
        )}
      </Modal>
    </PageContainer>
  )
}
