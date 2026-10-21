// 工单流程模板列表页：模板 CRUD + 发布 + 启停
// - 发布前必须通过服务端结构校验（节点/字段/路由/分组绑定）
// - 已发布的模板被编辑后自动回到草稿态，需重新发布才能发起工单
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { GitGraph, Plus, Pencil, Trash2, Rocket, FileJson, Power } from 'lucide-react'
import { toast } from '../store/toastStore'
import { confirm } from '../components/ConfirmDialog'
import { Button, PageContainer, DataTable, Pagination, EmptyState } from '../components/ui'
import { hasPermission } from '../utils/permissions'
import ticketApi from '../api/tickets'

export default function TicketFlowList() {
  const canEdit = hasPermission('ticket_config', 'edit')
  const navigate = useNavigate()

  const [list, setList] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [publishingId, setPublishingId] = useState(null)
  const [togglingId, setTogglingId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    ticketApi.listFlows()
      .then((res) => { setList(res.items || []); setTotal(res.items?.length || 0) })
      .catch((e) => toast.error(e.message || '加载流程模板失败'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const openNew = () => navigate('/ticket-config/flows/new')

  const openEdit = (row) => navigate(`/ticket-config/flows/${row.id}/edit`)

  const handlePublish = (row) => {
    confirm({
      title: '发布流程模板',
      message: `确认发布「${row.name}」？发布后将校验流程结构（节点/字段/路由/分组绑定），校验通过后即可发起工单；已发起的工单不受影响。`,
      confirmText: '发布',
    }).then((ok) => {
      if (!ok) return
      setPublishingId(row.id)
      ticketApi.publishFlow(row.id)
        .then(() => { toast.success(`模板已发布（v${(row.version || 0) + 1}）`); load() })
        .catch((e) => toast.error(e.message || '发布失败，请检查流程结构'))
        .finally(() => setPublishingId(null))
    })
  }

  const handleToggle = (row) => {
    setTogglingId(row.id)
    ticketApi.updateFlow(row.id, { enabled: !row.enabled })
      .then(() => { toast.success(row.enabled ? '已停用' : '已启用'); load() })
      .catch((e) => toast.error(e.message || '操作失败'))
      .finally(() => setTogglingId(null))
  }

  const handleDelete = (row) => {
    confirm({
      title: '删除流程模板',
      message: `确认删除「${row.name}」？已被工单引用的模板无法删除。不可恢复。`,
      variant: 'danger',
      confirmText: '删除',
    }).then((ok) => {
      if (!ok) return
      setDeletingId(row.id)
      ticketApi.deleteFlow(row.id)
        .then(() => { toast.success('模板已删除'); load() })
        .catch((e) => toast.error(e.message || '删除失败'))
        .finally(() => setDeletingId(null))
    })
  }

  const columns = [
    {
      key: 'name', header: '模板名称',
      render: (r) => (
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <FileJson className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium text-foreground">{r.name}</span>
              {r.is_draft
                ? <span className="shrink-0 rounded bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-500">草稿</span>
                : <span className="shrink-0 rounded bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-500">已发布 v{r.version}</span>}
            </div>
            {r.description && <div className="mt-0.5 truncate text-xs text-muted-foreground">{r.description}</div>}
          </div>
        </div>
      ),
    },
    {
      key: 'node_count', header: '节点数', width: '90px', align: 'right',
      render: (r) => <span className="tabular-nums">{r.node_count ?? '--'}</span>,
    },
    {
      key: 'ticket_count', header: '工单数', width: '90px', align: 'right',
      render: (r) => <span className="tabular-nums">{r.ticket_count ?? 0}</span>,
    },
    {
      key: 'enabled', header: '状态', width: '90px',
      render: (r) => (
        <span className={`inline-flex whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium ${r.enabled ? 'bg-emerald-500/10 text-emerald-500' : 'bg-muted text-muted-foreground'}`}>
          {r.enabled ? '启用' : '停用'}
        </span>
      ),
    },
    {
      key: 'updated_at', header: '更新时间', width: '160px',
      render: (r) => <span className="tabular-nums text-muted-foreground">{r.updated_at ? new Date(r.updated_at).toLocaleString('zh-CN', { hour12: false }) : '--'}</span>,
    },
    {
      key: 'actions', header: '操作', width: '230px',
      render: (r) => {
        if (!canEdit) return <span className="text-xs text-muted-foreground">--</span>
        return (
          <div className="flex items-center gap-1.5 whitespace-nowrap">
            <button onClick={() => openEdit(r)} className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-foreground hover:bg-muted" title="编辑流程">
              <Pencil className="h-3.5 w-3.5" />编辑
            </button>
            {!r.is_draft && (
              <button onClick={() => handleToggle(r)} disabled={togglingId === r.id}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                title={r.enabled ? '停用（停用后不能发起工单）' : '启用'}>
                <Power className="h-3.5 w-3.5" />{r.enabled ? '停用' : '启用'}
              </button>
            )}
            {!r.is_draft && (
              <button onClick={() => handlePublish(r)} disabled={publishingId === r.id}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10 disabled:opacity-50" title="重新发布">
                <Rocket className="h-3.5 w-3.5" />{publishingId === r.id ? '发布中' : '发布'}
              </button>
            )}
            {r.is_draft && (
              <button onClick={() => handlePublish(r)} disabled={publishingId === r.id}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10 disabled:opacity-50" title="发布后才能发起工单">
                <Rocket className="h-3.5 w-3.5" />{publishingId === r.id ? '发布中' : '发布'}
              </button>
            )}
            <button onClick={() => handleDelete(r)} disabled={deletingId === r.id}
              className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50" title="删除模板">
              <Trash2 className="h-3.5 w-3.5" />{deletingId === r.id ? '删除中' : '删除'}
            </button>
          </div>
        )
      },
    },
  ]

  return (
    <PageContainer>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[22px] font-bold text-foreground">流程模板</h1>
          <p className="mt-2 text-[13px] text-muted-foreground">自定义工单流转程序：节点绑定处理分组、节点字段自定义、流转路由支持条件判断；模板发布后即可发起工单</p>
        </div>
        {canEdit && (
          <Button variant="primary" size="sm" onClick={openNew}>
            <Plus className="mr-1 h-3.5 w-3.5" />新建模板
          </Button>
        )}
      </div>

      <DataTable
        columns={columns}
        data={list.slice((page - 1) * size, page * size)}
        loading={loading}
        rowKey="id"
        rowClassName={() => 'h-14'}
        emptyText="暂无流程模板"
        emptyIcon={GitGraph}
        emptyDescription="创建并发布流程模板后，即可在工单中心发起工单"
        emptyAction={canEdit && (
          <Button variant="primary" size="sm" onClick={openNew}>
            <Plus className="mr-1 h-3.5 w-3.5" />新建模板
          </Button>
        )}
      />
      <Pagination page={page} pageSize={size} total={total} onPageChange={setPage} onPageSizeChange={(s) => { setSize(s); setPage(1) }} />
    </PageContainer>
  )
}
