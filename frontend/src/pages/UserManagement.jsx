import { useEffect, useState, useCallback } from 'react'
import { usersApi } from '../api/users'
import { rolesApi } from '../api/roles'
import { useAuthStore } from '../store/authStore'
import { hasPermission } from '../utils/permissions'
import { Modal } from '../components/Dialog'
import {
  Section,
  TextInput,
  SelectInput,
  CheckRow,
} from '../components/property/FormControls'

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 角色中文映射
const ROLE_LABELS = {
  admin: '管理员',
  analyst: '分析师',
  viewer: '访客',
}

// 用户管理页面：CRUD + 角色分配 + 重置密码 + 启停
function UserManagement() {
  const [rows, setRows] = useState([])
  const [roles, setRoles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const currentUser = useAuthStore((s) => s.user)

  // 编辑相关
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    username: '',
    password: '',
    display_name: '',
    email: '',
    role: 'analyst',
    role_id: null,
    is_active: true,
  })
  const [saving, setSaving] = useState(false)

  // 重置密码弹窗
  const [resetOpen, setResetOpen] = useState(false)
  const [resetTarget, setResetTarget] = useState(null)
  const [newPassword, setNewPassword] = useState('')
  const [resetting, setResetting] = useState(false)

  const canView = hasPermission('user', 'view')
  const canEdit = hasPermission('user', 'edit')
  const canDelete = hasPermission('user', 'delete')

  const load = useCallback(async () => {
    if (!canView) {
      setError('您没有查看用户列表的权限')
      setLoading(false)
      return
    }
    try {
      const [userData, roleData] = await Promise.all([
        usersApi.list(),
        rolesApi.list(),
      ])
      setRows(Array.isArray(userData) ? userData : [])
      setRoles(Array.isArray(roleData) ? roleData : [])
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
    setForm({
      username: '',
      password: '',
      display_name: '',
      email: '',
      role: 'analyst',
      role_id: null,
      is_active: true,
    })
    setEditOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    setForm({
      username: row.username || '',
      password: '', // 编辑时不修改密码
      display_name: row.display_name || '',
      email: row.email || '',
      role: row.role || 'analyst',
      role_id: row.role_id || null,
      is_active: !!row.is_active,
    })
    setEditOpen(true)
  }

  const setField = (field) => (value) =>
    setForm((prev) => ({ ...prev, [field]: value }))

  const handleSave = async () => {
    if (!form.username.trim()) {
      window.alert('请填写用户名')
      return
    }
    if (!editing && !form.password) {
      window.alert('请填写初始密码')
      return
    }
    if (!editing && form.password.length < 6) {
      window.alert('密码至少 6 位')
      return
    }
    setSaving(true)
    try {
      if (editing) {
        // 更新（不含密码）
        const body = {
          display_name: form.display_name || null,
          email: form.email || null,
          role: form.role,
          role_id: form.role_id,
          is_active: form.is_active,
        }
        await usersApi.update(editing.id, body)
      } else {
        // 新建
        const body = {
          username: form.username,
          password: form.password,
          display_name: form.display_name || null,
          email: form.email || null,
          role: form.role,
          role_id: form.role_id,
          is_active: form.is_active,
        }
        await usersApi.create(body)
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
    if (!window.confirm(`确定删除用户「${row.display_name || row.username}」吗？`))
      return
    try {
      await usersApi.remove(row.id)
      await load()
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  const handleToggleActive = async (row) => {
    try {
      await usersApi.toggleActive(row.id)
      await load()
    } catch (err) {
      window.alert(`操作失败：${err.message || err}`)
    }
  }

  const openReset = (row) => {
    setResetTarget(row)
    setNewPassword('')
    setResetOpen(true)
  }

  const handleReset = async () => {
    if (!newPassword || newPassword.length < 6) {
      window.alert('新密码至少 6 位')
      return
    }
    setResetting(true)
    try {
      await usersApi.resetPassword(resetTarget.id, newPassword)
      setResetOpen(false)
      window.alert(`已重置 ${resetTarget.username} 的密码`)
    } catch (err) {
      window.alert(`重置失败：${err.message || err}`)
    } finally {
      setResetting(false)
    }
  }

  // 角色选项
  const roleOptions = roles.map((r) => ({
    value: String(r.id),
    label: `${r.name}${r.is_system ? '（系统）' : ''}`,
  }))
  // 兼容旧 role 字段（admin/analyst/viewer）
  const legacyRoleOptions = [
    { value: 'admin', label: '管理员' },
    { value: 'analyst', label: '分析师' },
    { value: 'viewer', label: '访客' },
  ]

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between gap-4 border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-100">用户管理</h1>
          <span className="text-xs text-gray-500">共 {rows.length} 个用户</span>
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
              + 新建用户
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
        ) : rows.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">👤</div>
            <div className="text-sm">暂无用户</div>
          </div>
        ) : (
          <div className="w-full overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full min-w-[820px] table-fixed border-collapse text-sm">
              <thead className="bg-gray-900 text-gray-400">
                <tr>
                  <th className="w-16 px-4 py-3 text-left font-medium">ID</th>
                  <th className="px-4 py-3 text-left font-medium">用户名</th>
                  <th className="px-4 py-3 text-left font-medium">显示名</th>
                  <th className="px-4 py-3 text-left font-medium">邮箱</th>
                  <th className="w-24 px-4 py-3 text-left font-medium">角色</th>
                  <th className="w-20 px-4 py-3 text-left font-medium">状态</th>
                  <th className="w-40 px-4 py-3 text-left font-medium">最后登录</th>
                  <th className="w-52 px-4 py-3 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, idx) => (
                  <tr
                    key={r.id}
                    className={`border-t border-gray-800 transition-colors hover:bg-brand-500/5 ${
                      idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
                    }`}
                  >
                    <td className="truncate px-4 py-3 font-mono text-brand-300">#{r.id}</td>
                    <td className="truncate px-4 py-3 text-gray-200">{r.username}</td>
                    <td className="truncate px-4 py-3 text-gray-300">
                      {r.display_name || '-'}
                    </td>
                    <td className="truncate px-4 py-3 text-gray-400">
                      {r.email || '-'}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-brand-500/20 px-2 py-0.5 text-[11px] font-medium text-brand-300">
                        {ROLE_LABELS[r.role] || r.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {r.is_active ? (
                        <span className="rounded bg-success-500/20 px-2 py-0.5 text-[11px] font-medium text-success-300">
                          启用
                        </span>
                      ) : (
                        <span className="rounded bg-gray-500/20 px-2 py-0.5 text-[11px] font-medium text-gray-400">
                          禁用
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-400">{fmtTime(r.last_login_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {canEdit && (
                          <button
                            type="button"
                            onClick={() => openEdit(r)}
                            className="btn-secondary btn-sm"
                          >
                            编辑
                          </button>
                        )}
                        {canEdit && (
                          <button
                            type="button"
                            onClick={() => openReset(r)}
                            className="btn-secondary btn-sm"
                          >
                            重置密码
                          </button>
                        )}
                        {canEdit && currentUser && r.id !== currentUser.id && (
                          <button
                            type="button"
                            onClick={() => handleToggleActive(r)}
                            className="btn-secondary btn-sm"
                          >
                            {r.is_active ? '禁用' : '启用'}
                          </button>
                        )}
                        {canDelete && currentUser && r.id !== currentUser.id && (
                          <button
                            type="button"
                            onClick={() => handleDelete(r)}
                            className="btn-danger btn-sm"
                          >
                            删除
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 新建/编辑用户弹窗 */}
      <Modal
        open={editOpen}
        title={editing ? `编辑用户：${editing.username}` : '新建用户'}
        onClose={() => setEditOpen(false)}
        maxWidth="max-w-xl"
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
        <Section title="账号信息">
          <TextInput
            label="用户名"
            value={form.username}
            onChange={setField('username')}
            placeholder="登录用户名"
            hint={editing ? '用户名创建后不可修改' : ''}
          />
          {!editing && (
            <TextInput
              label="初始密码"
              value={form.password}
              onChange={setField('password')}
              placeholder="至少 6 位"
            />
          )}
        </Section>

        <Section title="个人资料">
          <TextInput
            label="显示名"
            value={form.display_name}
            onChange={setField('display_name')}
            placeholder="如：张三"
          />
          <TextInput
            label="邮箱"
            value={form.email}
            onChange={setField('email')}
            placeholder="user@example.com"
          />
        </Section>

        <Section title="角色与状态">
          <SelectInput
            label="角色（旧版字段）"
            value={form.role}
            onChange={setField('role')}
            options={legacyRoleOptions}
            hint="兼容旧 role 字段，建议同时选择下面的角色 ID"
          />
          {roleOptions.length > 0 && (
            <SelectInput
              label="角色 ID（关联角色表）"
              value={form.role_id ? String(form.role_id) : ''}
              onChange={(v) => setField('role_id')(v ? Number(v) : null)}
              options={[{ value: '', label: '不关联（使用旧 role 字段）' }, ...roleOptions]}
              hint="优先使用角色 ID 进行权限矩阵校验"
            />
          )}
          <CheckRow
            label="启用账号"
            checked={form.is_active}
            onChange={setField('is_active')}
          />
        </Section>
      </Modal>

      {/* 重置密码弹窗 */}
      <Modal
        open={resetOpen}
        title={`重置密码：${resetTarget?.username || ''}`}
        onClose={() => setResetOpen(false)}
        maxWidth="max-w-md"
        footer={
          <>
            <button
              type="button"
              onClick={() => setResetOpen(false)}
              className="btn-secondary"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleReset}
              disabled={resetting}
              className="btn-primary"
            >
              {resetting ? '重置中…' : '确认重置'}
            </button>
          </>
        }
      >
        <TextInput
          label="新密码"
          value={newPassword}
          onChange={setNewPassword}
          placeholder="至少 6 位"
        />
        <p className="text-[11px] text-gray-500">
          重置后请通知用户尽快登录并修改为自己的密码。
        </p>
      </Modal>
    </div>
  )
}

export default UserManagement
