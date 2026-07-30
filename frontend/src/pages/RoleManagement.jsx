import { useEffect, useState, useCallback } from 'react'
import { rolesApi } from '../api/roles'
import { hasPermission } from '../utils/permissions'
import { Drawer } from '../components/Dialog'
import { Section, TextInput, CheckRow } from '../components/property/FormControls'

// 角色管理页面：CRUD + 权限矩阵编辑器
function RoleManagement() {
  const [rows, setRows] = useState([])
  const [moduleDef, setModuleDef] = useState({
    modules: {},
    module_labels: {},
    action_labels: {},
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 编辑相关
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    name: '',
    description: '',
    permissions: {},
  })
  const [saving, setSaving] = useState(false)

  const canView = hasPermission('role', 'view')
  const canEdit = hasPermission('role', 'edit')
  const canDelete = hasPermission('role', 'delete')

  const load = useCallback(async () => {
    if (!canView) {
      setError('您没有查看角色列表的权限')
      setLoading(false)
      return
    }
    try {
      const [roleData, modData] = await Promise.all([
        rolesApi.list(),
        rolesApi.modules(),
      ])
      setRows(Array.isArray(roleData) ? roleData : [])
      setModuleDef(
        modData || { modules: {}, module_labels: {}, action_labels: {} }
      )
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [canView])

  useEffect(() => {
    load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    // 初始化权限矩阵：所有模块动作默认为空
    const initPerms = {}
    Object.keys(moduleDef.modules || {}).forEach((m) => {
      initPerms[m] = []
    })
    setForm({
      name: '',
      description: '',
      permissions: initPerms,
    })
    setEditOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    setForm({
      name: row.name || '',
      description: row.description || '',
      permissions: { ...(row.permissions || {}) },
    })
    setEditOpen(true)
  }

  // 切换某个模块的某个动作
  const togglePermission = (moduleName, action) => {
    setForm((prev) => {
      const currentActions = prev.permissions[moduleName] || []
      const nextActions = currentActions.includes(action)
        ? currentActions.filter((a) => a !== action)
        : [...currentActions, action]
      return {
        ...prev,
        permissions: { ...prev.permissions, [moduleName]: nextActions },
      }
    })
  }

  // 一键全选/清空某模块
  const setModuleAll = (moduleName, actions, selectAll) => {
    setForm((prev) => ({
      ...prev,
      permissions: {
        ...prev.permissions,
        [moduleName]: selectAll ? [...actions] : [],
      },
    }))
  }

  const handleSave = async () => {
    if (!form.name.trim()) {
      window.alert('请填写角色名')
      return
    }
    setSaving(true)
    try {
      const body = {
        name: form.name.trim(),
        description: form.description || null,
        permissions: form.permissions,
      }
      if (editing) {
        await rolesApi.update(editing.id, body)
      } else {
        await rolesApi.create(body)
      }
      setEditOpen(false)
      await load()
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (row) => {
    if (!window.confirm(`确定删除角色「${row.name}」吗？`)) return
    try {
      await rolesApi.remove(row.id)
      await load()
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  const moduleEntries = Object.entries(moduleDef.modules || {})
  const moduleLabels = moduleDef.module_labels || {}
  const actionLabels = moduleDef.action_labels || {}

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between gap-4 border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-100">角色管理</h1>
          <span className="text-xs text-gray-500">共 {rows.length} 个角色</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={load}
            className="btn-secondary btn-sm"
          >
            刷新
          </button>
          {canEdit && (
            <button
              type="button"
              onClick={openCreate}
              className="btn-primary btn-sm"
            >
              + 新建角色
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {rows.map((r) => {
              const permCount = Object.values(r.permissions || {}).reduce(
                (sum, arr) => sum + (Array.isArray(arr) ? arr.length : 0),
                0
              )
              return (
                <div
                  key={r.id}
                  className="rounded-lg border border-gray-800 bg-gray-900/40 p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 truncate text-base font-semibold text-gray-100">
                          {r.name}
                        </span>
                        {r.is_system && (
                          <span className="rounded bg-warning-500/20 px-2 py-0.5 text-[11px] font-medium text-warning-300">
                            系统内置
                          </span>
                        )}
                        <span className="text-xs text-gray-500">
                          {permCount} 项权限
                        </span>
                      </div>
                      {r.description && (
                        <div className="mt-1 truncate text-sm text-gray-400">
                          {r.description}
                        </div>
                      )}
                      {/* 权限矩阵概览 */}
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {moduleEntries.map(([modName, actions]) => {
                          const userActions = r.permissions?.[modName] || []
                          if (userActions.length === 0) return null
                          return (
                            <span
                              key={modName}
                              className="rounded border border-gray-700 bg-gray-800 px-2 py-0.5 text-[11px] text-gray-300"
                            >
                              {moduleLabels[modName] || modName}:{' '}
                              <span className="text-brand-300">
                                {userActions
                                  .map((a) => actionLabels[a] || a)
                                  .join(' / ')}
                              </span>
                            </span>
                          )
                        })}
                        {permCount === 0 && (
                          <span className="text-[11px] text-gray-600">
                            无任何权限
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => openEdit(r)}
                          className="btn-secondary btn-sm"
                        >
                          编辑
                        </button>
                      )}
                      {canDelete && !r.is_system && (
                        <button
                          type="button"
                          onClick={() => handleDelete(r)}
                          className="btn-danger btn-sm"
                        >
                          删除
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 新建/编辑角色抽屉（含权限矩阵编辑器） */}
      <Drawer
        open={editOpen}
        title={editing ? `编辑角色：${editing.name}` : '新建角色'}
        onClose={() => setEditOpen(false)}
        width="w-[640px]"
        footer={
          <>
            <button
              type="button"
              onClick={() => setEditOpen(false)}
              className="btn-secondary"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="btn-primary"
            >
              {saving ? '保存中…' : '保存'}
            </button>
          </>
        }
      >
        <Section title="角色基础">
          <TextInput
            label="角色名"
            value={form.name}
            onChange={(v) => setForm((p) => ({ ...p, name: v }))}
            placeholder="如：soc_lead"
            hint={editing?.is_system ? '系统内置角色名建议不修改' : ''}
          />
          <TextInput
            label="描述"
            value={form.description}
            onChange={(v) => setForm((p) => ({ ...p, description: v }))}
            placeholder="角色职责说明"
          />
        </Section>

        <Section
          title="权限矩阵"
          hint="勾选对应模块下的动作，admin 角色自动拥有全部权限"
        >
          <div className="flex flex-col gap-2">
            {moduleEntries.map(([modName, actions]) => {
              const userActions = form.permissions[modName] || []
              const allSelected =
                actions.length > 0 &&
                actions.every((a) => userActions.includes(a))
              return (
                <div
                  key={modName}
                  className="rounded-md border border-gray-800 bg-gray-800/40 p-2.5"
                >
                  <div className="mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-200">
                        {moduleLabels[modName] || modName}
                      </span>
                      <span className="text-[10px] text-gray-500">
                        ({modName})
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setModuleAll(modName, actions, !allSelected)}
                      className="rounded border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:bg-gray-700 hover:text-gray-200"
                    >
                      {allSelected ? '清空' : '全选'}
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    {actions.map((a) => (
                      <CheckRow
                        key={a}
                        label={actionLabels[a] || a}
                        checked={userActions.includes(a)}
                        onChange={() => togglePermission(modName, a)}
                      />
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </Section>
      </Drawer>
    </div>
  )
}

export default RoleManagement
