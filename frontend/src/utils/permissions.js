// 前端权限工具：基于后端 /auth/me 返回的权限矩阵驱动 UI 隐藏/禁用
//
// 后端 require_permission 是真正鉴权防线，前端只做 UI 隐藏/禁用以提升体验。
// 权限矩阵来源：登录/刷新时 /auth/me 返回的 user.permissions（与后端 Role.permissions 一致）。
// admin 角色自动拥有全部权限（后端 _resolve_permissions 已展开为全量矩阵）。

import { useAuthStore } from '../store/authStore'

/**
 * 判断当前用户是否拥有指定模块动作权限（前端仅用于 UI 隐藏）。
 * @param {string} module 模块名，如 "user" / "workflow"
 * @param {string} action 动作名，如 "view" / "edit" / "delete"
 * @returns {boolean}
 */
export function hasPermission(module, action) {
  const user = useAuthStore.getState().user
  if (!user) return false
  // admin 角色自动通过（后端已返回全量权限矩阵，此为兜底）
  if (user.role === 'admin') return true
  // 优先使用后端返回的权限矩阵（支持自定义角色）
  const perms = user.permissions
  if (perms && typeof perms === 'object') {
    const actions = perms[module]
    return Array.isArray(actions) && actions.includes(action)
  }
  return false
}

/**
 * 是否为管理员（admin 角色）。
 */
export function isAdmin() {
  const user = useAuthStore.getState().user
  return !!user && user.role === 'admin'
}

/**
 * 判断当前用户是否可编辑指定资源（资源级 owner 控制）。
 *
 * 优先级：
 * 1. admin 角色可编辑所有资源；
 * 2. 后端返回的 ``can_edit`` 标志（列表/详情接口已计算，覆盖 owner 与被授权用户）；
 * 3. 兜底：当前用户是资源创建者（``created_by === user.id``），用于详情接口未返回 can_edit 时。
 *
 * @param {object|null} resource 资源对象（列表项或详情），需含 can_edit 或 created_by 字段
 * @returns {boolean}
 */
export function canEditResource(resource) {
  const user = useAuthStore.getState().user
  if (!user) return false
  if (user.role === 'admin') return true
  if (resource && typeof resource.can_edit === 'boolean') return resource.can_edit
  // 兜底：详情接口若未返回 can_edit，则按 owner 判断（被授权用户需依赖 can_edit）
  if (resource && resource.created_by != null) return resource.created_by === user.id
  return false
}

/**
 * 判断当前用户是否可管理资源共享（仅 admin 或 owner）。
 *
 * 被授权用户虽可编辑资源，但不能管理共享（不能再转授或撤销）。
 * @param {object|null} resource 资源对象，需含 created_by 字段
 * @returns {boolean}
 */
export function canManageShare(resource) {
  const user = useAuthStore.getState().user
  if (!user) return false
  if (user.role === 'admin') return true
  if (resource && resource.created_by != null) return resource.created_by === user.id
  return false
}

export default { hasPermission, isAdmin, canEditResource, canManageShare }
