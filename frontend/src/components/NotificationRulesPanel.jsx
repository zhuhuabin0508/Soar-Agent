/**
 * 通知规则配置面板。
 * 在通知中心页的「通知规则」Tab 中渲染，用于配置：
 *   哪些事件类型（feedback / model_alert / system_update / ...）需要通知，
 *   以及通知给谁（指定用户 + 指定角色）。
 *
 * 功能：
 * - 规则列表：展示名称 / 事件类型 / 目标用户数 / 目标角色 / 启停开关 / 编辑 / 删除
 * - 新建 / 编辑规则弹窗：名称、事件类型（下拉）、目标用户（多选）、目标角色（多选）、说明、启用
 * - 事件类型清单来自后端 /notification-rules/event-types
 * - 用户清单来自 /users，角色清单来自 /roles
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bell, Plus, Pencil, Trash2, Power, Users, Tag, X, Loader2, ShieldCheck,
} from 'lucide-react'
import { notificationRulesApi } from '../api/notifications'
import { usersApi } from '../api/users'
import { rolesApi } from '../api/roles'
import { toast } from '../store/toastStore'
import { confirm } from './ConfirmDialog'

const EMPTY_FORM = {
  name: '',
  description: '',
  event_type: 'feedback',
  target_user_ids: [],
  target_roles: [],
  enabled: true,
}

function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(t)
  }
}

export default function NotificationRulesPanel() {
  const [rules, setRules] = useState([])
  const [eventTypes, setEventTypes] = useState([])
  const [users, setUsers] = useState([])
  const [roles, setRoles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // 弹窗：null | { mode: 'create' | 'edit', data: rule }
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [togglingId, setTogglingId] = useState(null)

  // 加载规则列表 + 事件类型 + 用户 + 角色
  const loadAll = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [rulesRes, etRes, usersRes, rolesRes] = await Promise.all([
        notificationRulesApi.list(),
        notificationRulesApi.eventTypes(),
        usersApi.list(),
        rolesApi.list(),
      ])
      setRules(Array.isArray(rulesRes) ? rulesRes : (rulesRes?.items || []))
      setEventTypes(etRes?.event_types || [])
      setUsers(Array.isArray(usersRes) ? usersRes : (usersRes?.items || []))
      setRoles(Array.isArray(rolesRes) ? rolesRes : (rolesRes?.items || []))
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  // 事件类型 label 映射
  const eventTypeLabel = useMemo(() => {
    const m = { '*': '全部事件' }
    eventTypes.forEach((et) => { m[et.value] = et.label })
    return (type) => m[type] || type
  }, [eventTypes])

  // 动态角色选项：从后端加载的所有角色（含自定义角色）
  const roleOptions = useMemo(() => {
    return roles.map((r) => ({
      value: r.name,
      label: r.description ? `${r.name}（${r.description}）` : r.name,
    }))
  }, [roles])

  // 角色名 → label 映射（用于规则列表展示）
  const roleLabelMap = useMemo(() => {
    const m = new Map()
    roles.forEach((r) => {
      m.set(r.name, r.description ? `${r.name}（${r.description}）` : r.name)
    })
    return m
  }, [roles])

  // 用户 ID → 用户名映射
  const userNameMap = useMemo(() => {
    const m = new Map()
    users.forEach((u) => m.set(u.id, u.username || `用户#${u.id}`))
    return m
  }, [users])

  // 用户角色名映射：优先用 role_id 关联角色名，fallback 到 u.role
  const userRoleMap = useMemo(() => {
    const m = new Map()
    const roleById = new Map()
    roles.forEach((r) => roleById.set(r.id, r.name))
    users.forEach((u) => {
      // 优先用 role_id 关联的角色名
      if (u.role_id && roleById.has(u.role_id)) {
        m.set(u.id, roleById.get(u.role_id))
      } else if (u.role) {
        m.set(u.id, u.role)
      }
    })
    return m
  }, [users, roles])

  const handleOpenCreate = () => {
    setForm(EMPTY_FORM)
    setModal({ mode: 'create' })
  }

  const handleOpenEdit = (rule) => {
    setForm({
      name: rule.name || '',
      description: rule.description || '',
      event_type: rule.event_type || 'feedback',
      target_user_ids: rule.target_user_ids || [],
      target_roles: rule.target_roles || [],
      enabled: rule.enabled !== false,
    })
    setModal({ mode: 'edit', id: rule.id })
  }

  const handleCloseModal = () => {
    setModal(null)
    setForm(EMPTY_FORM)
  }

  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.warning('请填写规则名称')
      return
    }
    if (!form.event_type) {
      toast.warning('请选择事件类型')
      return
    }
    if (form.target_user_ids.length === 0 && form.target_roles.length === 0) {
      toast.warning('请至少选择一个目标用户或角色')
      return
    }
    setSaving(true)
    try {
      const body = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        event_type: form.event_type,
        target_user_ids: form.target_user_ids,
        target_roles: form.target_roles,
        enabled: form.enabled,
      }
      if (modal.mode === 'create') {
        await notificationRulesApi.create(body)
        toast.success('通知规则已创建')
      } else {
        await notificationRulesApi.update(modal.id, body)
        toast.success('通知规则已更新')
      }
      handleCloseModal()
      await loadAll()
    } catch (err) {
      toast.error('保存失败：' + (err.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  const handleToggle = async (rule) => {
    setTogglingId(rule.id)
    try {
      await notificationRulesApi.toggle(rule.id)
      setRules((list) =>
        list.map((r) => (r.id === rule.id ? { ...r, enabled: !r.enabled } : r))
      )
      toast.success(rule.enabled ? '规则已停用' : '规则已启用')
    } catch (err) {
      toast.error('切换失败：' + (err.message || '未知错误'))
    } finally {
      setTogglingId(null)
    }
  }

  const handleDelete = async (rule) => {
    const ok = await confirm({
      title: '删除通知规则',
      message: `确定删除规则「${rule.name}」吗？此操作不可撤销。`,
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await notificationRulesApi.remove(rule.id)
      setRules((list) => list.filter((r) => r.id !== rule.id))
      toast.success('规则已删除')
    } catch (err) {
      toast.error('删除失败：' + (err.message || '未知错误'))
    }
  }

  // 多选用户切换
  const toggleUserId = (uid) => {
    setForm((f) => {
      const set = new Set(f.target_user_ids)
      if (set.has(uid)) set.delete(uid)
      else set.add(uid)
      return { ...f, target_user_ids: [...set] }
    })
  }
  // 多选角色切换
  const toggleRole = (role) => {
    setForm((f) => {
      const set = new Set(f.target_roles)
      if (set.has(role)) set.delete(role)
      else set.add(role)
      return { ...f, target_roles: [...set] }
    })
  }

  const inputCls =
    'w-full rounded-md border border-border bg-secondary px-3 py-2 text-sm text-foreground outline-none focus:border-primary'
  const labelCls = 'mb-1.5 block text-xs font-medium text-muted-foreground'

  return (
    <div className="space-y-4">
      {/* 说明条 */}
      <div className="rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 text-xs text-muted-foreground">
        <ShieldCheck className="mr-1.5 inline h-3.5 w-3.5 text-primary" />
        配置「<b className="text-foreground">哪些事件</b>需要通知」以及「<b className="text-foreground">通知给谁</b>」。
        事件发生时，系统按匹配的启用规则将通知投递给目标用户（指定用户 + 指定角色）。
        <b className="text-foreground">无匹配规则时回退为全员广播</b>，保证不丢通知。
      </div>

      {/* 操作栏 */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground/70">共 {rules.length} 条规则</span>
        <button type="button" onClick={handleOpenCreate} className="btn-primary btn-sm">
          <Plus className="h-3.5 w-3.5" />
          新建规则
        </button>
      </div>

      {/* 列表 */}
      {loading ? (
        <div className="flex h-32 items-center justify-center text-sm text-muted-foreground/70">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中...
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {error}
        </div>
      ) : rules.length === 0 ? (
        <div className="flex h-48 flex-col items-center justify-center gap-2 text-muted-foreground/70">
          <Bell className="h-10 w-10" />
          <div className="text-sm">暂无通知规则</div>
          <div className="text-xs">未配置规则时，所有通知将回退为全员广播</div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {rules.map((rule) => (
            <div
              key={rule.id}
              className={`rounded-lg border p-4 transition-colors ${
                rule.enabled
                  ? 'border-border bg-card'
                  : 'border-border bg-secondary/40 opacity-70'
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-foreground">{rule.name}</span>
                    <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                      {eventTypeLabel(rule.event_type)}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        rule.enabled
                          ? 'bg-success/15 text-success'
                          : 'bg-muted text-muted-foreground'
                      }`}
                    >
                      {rule.enabled ? '启用' : '停用'}
                    </span>
                  </div>
                  {rule.description && (
                    <div className="mt-1 text-xs text-muted-foreground/80">{rule.description}</div>
                  )}
                  {/* 目标用户 */}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Users className="h-3 w-3 text-muted-foreground" />
                    <span className="text-[11px] text-muted-foreground">目标用户：</span>
                    {rule.target_roles && rule.target_roles.length > 0 ? (
                      rule.target_roles.map((r) => (
                        <span key={r} className="inline-flex items-center gap-0.5 rounded bg-warning/15 px-1.5 py-0.5 text-[10px] text-warning">
                          <Tag className="h-2.5 w-2.5" />
                          {roleLabelMap.get(r) || r}
                        </span>
                      ))
                    ) : null}
                    {rule.target_user_ids && rule.target_user_ids.length > 0 ? (
                      rule.target_user_ids.map((uid) => (
                        <span key={uid} className="rounded bg-info/15 px-1.5 py-0.5 text-[10px] text-info">
                          {userNameMap.get(uid) || `用户#${uid}`}
                        </span>
                      ))
                    ) : null}
                    {(!rule.target_roles || rule.target_roles.length === 0) &&
                      (!rule.target_user_ids || rule.target_user_ids.length === 0) && (
                        <span className="text-[11px] text-muted-foreground/60">（无目标，回退广播）</span>
                      )}
                  </div>
                  <div className="mt-1.5 text-[11px] text-muted-foreground/60">
                    创建于 {fmtTime(rule.created_at)} · 由 {rule.created_by || '系统'} 创建
                  </div>
                </div>
                {/* 操作 */}
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => handleToggle(rule)}
                    disabled={togglingId === rule.id}
                    title={rule.enabled ? '停用规则' : '启用规则'}
                    className={`rounded-md p-1.5 transition hover:bg-secondary ${
                      rule.enabled ? 'text-success' : 'text-muted-foreground'
                    }`}
                  >
                    <Power className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleOpenEdit(rule)}
                    title="编辑规则"
                    className="rounded-md p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-primary"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(rule)}
                    title="删除规则"
                    className="rounded-md p-1.5 text-muted-foreground transition hover:bg-destructive/15 hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 新建/编辑弹窗 */}
      {modal && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60"
          onClick={handleCloseModal}
        >
          <div
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border bg-card shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 弹窗头部 */}
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <h3 className="text-sm font-semibold text-foreground">
                {modal.mode === 'create' ? '新建通知规则' : '编辑通知规则'}
              </h3>
              <button
                type="button"
                onClick={handleCloseModal}
                className="rounded p-1 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {/* 表单 */}
            <div className="space-y-4 p-5">
              <div>
                <label className={labelCls}>规则名称 *</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="如：反馈提交通知运维组"
                  className={inputCls}
                  maxLength={100}
                />
              </div>
              <div>
                <label className={labelCls}>事件类型 *</label>
                <select
                  value={form.event_type}
                  onChange={(e) => setForm((f) => ({ ...f, event_type: e.target.value }))}
                  className={inputCls}
                >
                  {eventTypes.length > 0 ? (
                    eventTypes.map((et) => (
                      <option key={et.value} value={et.value}>
                        {et.label}（{et.value}）— {et.desc}
                      </option>
                    ))
                  ) : (
                    <option value={form.event_type}>{form.event_type}</option>
                  )}
                </select>
                <div className="mt-1 text-[11px] text-muted-foreground/70">
                  选择「*」匹配所有事件类型
                </div>
              </div>
              <div>
                <label className={labelCls}>说明（可选）</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="规则用途说明"
                  className={inputCls}
                  rows={2}
                />
              </div>
              {/* 目标角色（动态从后端加载，含自定义角色） */}
              <div>
                <label className={labelCls}>目标角色</label>
                {roleOptions.length === 0 ? (
                  <div className="text-xs text-muted-foreground/70">暂无可用角色</div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {roleOptions.map((r) => {
                      const active = form.target_roles.includes(r.value)
                      return (
                        <button
                          type="button"
                          key={r.value}
                          onClick={() => toggleRole(r.value)}
                          className={`rounded-md border px-2.5 py-1 text-xs transition ${
                            active
                              ? 'border-warning bg-warning/15 text-warning'
                              : 'border-border bg-secondary text-muted-foreground hover:border-warning/50'
                          }`}
                          title={r.label}
                        >
                          {r.label}
                        </button>
                      )
                    })}
                  </div>
                )}
                <div className="mt-1 text-[11px] text-muted-foreground/70">
                  选中角色的所有启用用户都会收到通知
                </div>
              </div>
              {/* 目标用户 */}
              <div>
                <label className={labelCls}>目标用户（指定）</label>
                {users.length === 0 ? (
                  <div className="text-xs text-muted-foreground/70">暂无可用用户</div>
                ) : (
                  <div className="max-h-40 overflow-y-auto rounded-md border border-border bg-secondary/50 p-2">
                    <div className="flex flex-wrap gap-1.5">
                      {users.map((u) => {
                        const active = form.target_user_ids.includes(u.id)
                        const roleLabel = userRoleMap.get(u.id)
                        return (
                          <button
                            type="button"
                            key={u.id}
                            onClick={() => toggleUserId(u.id)}
                            className={`rounded border px-2 py-0.5 text-xs transition ${
                              active
                                ? 'border-info bg-info/15 text-info'
                                : 'border-border bg-secondary text-muted-foreground hover:border-info/50'
                            }`}
                            title={roleLabel ? `角色：${roleLabel}` : undefined}
                          >
                            {u.username}
                            {roleLabel ? ` (${roleLabel})` : ''}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
              {/* 启用开关 */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, enabled: !f.enabled }))}
                  className={`inline-flex h-5 w-9 items-center rounded-full p-0.5 transition ${
                    form.enabled ? 'bg-success' : 'bg-muted-foreground/30'
                  }`}
                >
                  <span
                    className={`h-4 w-4 rounded-full bg-white transition ${
                      form.enabled ? 'translate-x-4' : ''
                    }`}
                  />
                </button>
                <span className="text-xs text-muted-foreground">
                  {form.enabled ? '启用此规则' : '停用此规则'}
                </span>
              </div>
            </div>
            {/* 弹窗底部 */}
            <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
              <button type="button" onClick={handleCloseModal} className="btn-secondary btn-sm">
                取消
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="btn-primary btn-sm"
              >
                {saving ? '保存中...' : modal.mode === 'create' ? '创建' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
