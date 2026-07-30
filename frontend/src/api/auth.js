// 认证 API：登录、当前用户、修改密码
import request from './client'

export const authApi = {
  // 登录：返回 { access_token, token_type, user }
  login: (username, password) =>
    request('/auth/login', { method: 'POST', body: { username, password } }),

  // 获取当前登录用户信息
  me: () => request('/auth/me'),

  // 修改密码
  changePassword: (oldPassword, newPassword) =>
    request('/auth/change-password', {
      method: 'POST',
      body: { old_password: oldPassword, new_password: newPassword },
    }),

  // 用户自助修改个人资料（display_name / email），返回更新后的 UserInfo
  updateProfile: (body) =>
    request('/auth/profile', { method: 'PUT', body }),
}

export default authApi
