// 用户管理 API：列表/新建/更新/删除/重置密码/启停
import request from './client'

export const usersApi = {
  // 用户列表
  list: () => request('/users'),
  // 新建用户
  create: (body) => request('/users', { method: 'POST', body }),
  // 更新用户资料（不含密码）
  update: (id, body) => request(`/users/${id}`, { method: 'PUT', body }),
  // 删除用户
  remove: (id) => request(`/users/${id}`, { method: 'DELETE' }),
  // 管理员重置用户密码
  resetPassword: (id, newPassword) =>
    request(`/users/${id}/reset-password`, {
      method: 'POST',
      body: { new_password: newPassword },
    }),
  // 启用/禁用用户
  toggleActive: (id) =>
    request(`/users/${id}/toggle-active`, { method: 'POST' }),
  // 强制下线指定用户的所有会话
  forceLogout: (id) =>
    request(`/users/${id}/force-logout`, { method: 'POST' }),
}

export default usersApi
