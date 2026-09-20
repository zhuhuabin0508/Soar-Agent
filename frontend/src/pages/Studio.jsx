import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Bot,
  FolderKanban,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Target,
  Trash2,
} from 'lucide-react'
import { agents as agentsApi, workflows as workflowsApi, isAgentPublished } from '../api/client'
import { confirm } from '../components/ConfirmDialog'
import { toast } from '../store/toastStore'
import { hasPermission, canEditResource } from '../utils/permissions'

const TABS = [
  { id: 'all', label: '全部' },
  { id: 'agent', label: '智能体' },
  { id: 'workflow', label: '工作流' },
]

function fmtTime(t) {
  if (!t) return ''
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(t)
  }
}

function Studio() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((t) => t.id === params.get('tab')) ? params.get('tab') : 'all'
  const [agents, setAgents] = useState([])
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [menuId, setMenuId] = useState(null)
  const canCreateAgent = hasPermission('agent', 'edit')
  const canCreateWorkflow = hasPermission('workflow_list', 'edit') || hasPermission('workflow_editor', 'edit')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [a, w] = await Promise.all([
        hasPermission('agent', 'view') ? agentsApi.list() : Promise.resolve([]),
        hasPermission('workflow_list', 'view') ? workflowsApi.list() : Promise.resolve([]),
      ])
      setAgents(Array.isArray(a) ? a : [])
      setWorkflows(Array.isArray(w) ? w : [])
    } catch (err) {
      toast.error(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const items = useMemo(() => {
    const kw = q.trim().toLowerCase()
    const agentItems = agents.map((row) => ({
      key: `agent-${row.id}`,
      kind: 'agent',
      id: row.id,
      name: row.name || `智能体 ${row.id}`,
      description: row.description || '',
      updated_at: row.updated_at || row.created_at,
      avatar: row.avatar,
      engine: row.engine,
      published: isAgentPublished(row),
      raw: row,
    }))
    const wfItems = workflows.map((row) => ({
      key: `workflow-${row.id}`,
      kind: 'workflow',
      id: row.id,
      name: row.name || `工作流 ${row.id}`,
      description: row.description || '',
      updated_at: row.updated_at || row.created_at,
      status: row.status,
      trigger_type: row.trigger_type,
      raw: row,
    }))
    let list = tab === 'agent' ? agentItems : tab === 'workflow' ? wfItems : [...agentItems, ...wfItems]
    if (kw) {
      list = list.filter(
        (it) =>
          it.name.toLowerCase().includes(kw) ||
          (it.description || '').toLowerCase().includes(kw)
      )
    }
    list.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    return list
  }, [agents, workflows, q, tab])

  const openItem = (it) => {
    if (it.kind === 'agent') navigate(`/agents/${it.id}/edit`)
    else navigate(`/editor?id=${it.id}`)
  }

  const chatAgent = (it) => {
    try {
      localStorage.setItem('soar_chat_selected_agent', String(it.id))
    } catch {
    }
    navigate('/chat')
  }

  const handleDelete = async (it) => {
    setMenuId(null)
    const ok = await confirm({
      message: `确定删除${it.kind === 'agent' ? '智能体' : '工作流'}「${it.name}」吗？`,
      variant: 'danger',
      confirmText: '确定删除',
    })
    if (!ok) return
    try {
      if (it.kind === 'agent') await agentsApi.remove(it.id)
      else await workflowsApi.remove(it.id)
      await load()
    } catch (err) {
      toast.error(err.message || '删除失败')
    }
  }

  const createAgent = () => navigate('/agents/new')

  const createWorkflow = () => {
    navigate('/workflows/new')
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border px-8 py-5">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">工作室</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            智能体与工作流作为应用统一管理；工具、技能、知识库在应用内挂载
          </p>
        </div>
        <div className="flex items-center gap-2">
          {hasPermission('skill', 'view') && (
            <button
              type="button"
              onClick={() => navigate('/skills')}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              <Target className="h-4 w-4" />
              技能库
            </button>
          )}
          {(canCreateAgent || canCreateWorkflow) && (
            <div className="relative">
              <details className="group">
                <summary className="flex h-9 cursor-pointer list-none items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground">
                  <Plus className="h-4 w-4" />
                  创建
                </summary>
                <div className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-md border border-border bg-card py-1">
                  {canCreateAgent && (
                    <button
                      type="button"
                      onClick={createAgent}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-secondary"
                    >
                      <Bot className="h-4 w-4 text-primary" />
                      智能体
                    </button>
                  )}
                  {canCreateWorkflow && (
                    <button
                      type="button"
                      onClick={createWorkflow}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-secondary"
                    >
                      <FolderKanban className="h-4 w-4 text-cyan-500" />
                      工作流
                    </button>
                  )}
                </div>
              </details>
            </div>
          )}
        </div>
      </header>

      <div className="flex shrink-0 items-center gap-6 border-b border-border px-8">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setParams(t.id === 'all' ? {} : { tab: t.id })}
            className={`relative py-3 text-sm transition ${
              tab === t.id ? 'font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {t.label}
            {tab === t.id && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 bg-primary" />
            )}
          </button>
        ))}
        <div className="relative ml-auto mb-2 mt-2 w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索应用"
            className="h-8 w-full rounded-md border border-border bg-secondary pl-8 pr-2 text-xs text-foreground placeholder:text-muted-foreground/60 focus:border-primary focus:outline-none"
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto px-8 py-6">
        {loading ? (
          <p className="py-16 text-center text-sm text-muted-foreground">加载中…</p>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <Sparkles className="mb-3 h-8 w-8 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">
              {q ? '没有匹配的应用' : '还没有应用。创建一个智能体，或编排一条工作流。'}
            </p>
            {!q && (
              <div className="mt-4 flex gap-2">
                {canCreateAgent && (
                  <button type="button" onClick={createAgent} className="btn-primary btn-sm">
                    创建智能体
                  </button>
                )}
                {canCreateWorkflow && (
                  <button type="button" onClick={createWorkflow} className="btn-secondary btn-sm">
                    创建工作流
                  </button>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {items.map((it) => {
              const editable = canEditResource(it.raw)
              return (
                <div
                  key={it.key}
                  className="group relative flex cursor-pointer flex-col rounded-xl border border-border bg-card p-4 transition hover:border-primary/40"
                  onClick={() => openItem(it)}
                >
                  <div className="mb-3 flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-3">
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg ${
                          it.kind === 'agent' ? 'bg-primary/15 text-primary' : 'bg-cyan-500/15 text-cyan-500'
                        }`}
                      >
                        {it.avatar ? (
                          <img src={it.avatar} alt="" className="h-full w-full object-cover" />
                        ) : it.kind === 'agent' ? (
                          <Bot className="h-5 w-5" />
                        ) : (
                          <FolderKanban className="h-5 w-5" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold">{it.name}</div>
                        <div className="mt-0.5 text-[11px] text-muted-foreground">
                          {it.kind === 'agent' ? '智能体' : '工作流'}
                          {it.kind === 'agent' && it.engine ? ` · ${it.engine}` : ''}
                          {it.kind === 'agent' && !it.published ? ' · 草稿' : ''}
                          {it.kind === 'workflow' && it.status ? ` · ${it.status}` : ''}
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="rounded p-1 text-muted-foreground opacity-0 hover:bg-secondary hover:text-foreground group-hover:opacity-100"
                      onClick={(e) => {
                        e.stopPropagation()
                        setMenuId(menuId === it.key ? null : it.key)
                      }}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </button>
                  </div>
                  <p className="line-clamp-2 min-h-[2.5rem] text-xs text-muted-foreground">
                    {it.description || '暂无描述'}
                  </p>
                  <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground/80">
                    <span>{fmtTime(it.updated_at)}</span>
                    {it.kind === 'agent' && it.published && (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-secondary hover:text-foreground"
                        onClick={(e) => {
                          e.stopPropagation()
                          chatAgent(it)
                        }}
                      >
                        <MessageSquare className="h-3 w-3" />
                        对话
                      </button>
                    )}
                  </div>
                  {menuId === it.key && (
                    <div
                      className="absolute right-3 top-12 z-10 w-36 overflow-hidden rounded-md border border-border bg-card py-1"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-secondary"
                        onClick={() => {
                          setMenuId(null)
                          openItem(it)
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        编辑
                      </button>
                      {it.kind === 'agent' && editable && !it.published && (
                        <button
                          type="button"
                          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-secondary"
                          onClick={async () => {
                            setMenuId(null)
                            try {
                              await agentsApi.publish(it.id)
                              toast.success('已发布，可在对话中使用')
                              await load()
                            } catch (err) {
                              toast.error(err.message || '发布失败')
                            }
                          }}
                        >
                          <Sparkles className="h-3.5 w-3.5" />
                          发布
                        </button>
                      )}
                      {editable && (
                        <button
                          type="button"
                          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-destructive hover:bg-secondary"
                          onClick={() => handleDelete(it)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          删除
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default Studio
