// 前端权限工具：从 localStorage 中读取用户信息判断权限
//
// 后端 require_permission 是真正鉴权防线，前端只做 UI 隐藏/禁用以提升体验。
// admin 角色（含 role_id 关联到 admin 角色）默认拥有全部权限。

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
  // admin 角色自动通过
  if (user.role === 'admin') return true
  // DEFAULT_ROLES 简化映射（与后端 permissions.py 保持一致）
  const DEFAULT_ROLE_PERMS = {
    analyst: {
      workflow: ['view', 'edit', 'execute'],
      tool: ['view', 'execute'],
      agent: ['view'],
      knowledge_base: ['view'],
      skill: ['view', 'edit'],
      llm_config: ['view'],
      dashboard: ['view'],
      approval: ['view', 'approve'],
      execution: ['view'],
    },
    viewer: {
      workflow: ['view'],
      tool: ['view'],
      agent: ['view'],
      knowledge_base: ['view'],
      skill: ['view'],
      llm_config: ['view'],
      dashboard: ['view'],
      approval: ['view'],
      execution: ['view'],
    },
  }
  const perms = DEFAULT_ROLE_PERMS[user.role]
  if (!perms) return false
  const actions = perms[module]
  if (!actions) return false
  return actions.includes(action)
}

/**
 * 是否为管理员（admin 角色）。
 */
export function isAdmin() {
  const user = useAuthStore.getState().user
  return !!user && user.role === 'admin'
}

export default { hasPermission, isAdmin }
