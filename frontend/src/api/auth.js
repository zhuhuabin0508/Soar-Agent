// 认证 API：登录、登出、令牌刷新、会话管理、当前用户、修改密码、图形验证码
import request from './client'

export const authApi = {
  // 获取图形验证码：返回 { captcha_id, image }
  getCaptcha: () =>
    request('/auth/captcha'),

  // 获取密码复杂度策略（无需认证）：返回 { min_length, require_uppercase, ... }
  getPasswordPolicy: () =>
    request('/auth/password-policy'),

  // 登录：返回 { access_token, token_type, user }
  login: (username, password, captchaId, captchaCode) =>
    request('/auth/login', {
      method: 'POST',
      body: {
        username,
        password,
        captcha_id: captchaId,
        captcha_code: captchaCode,
      },
    }),

  // 登出：拉黑当前 token + 删除会话记录
  logout: () =>
    request('/auth/logout', { method: 'POST' }),

  // 刷新令牌：返回新的 { access_token, user }，旧 token 立即失效
  refresh: () =>
    request('/auth/refresh', { method: 'POST' }),

  // 获取当前登录用户信息（含权限矩阵）
  me: () => request('/auth/me'),

  // 列出当前用户所有活跃会话（登录设备管理）
  listSessions: () =>
    request('/auth/sessions'),

  // 撤销指定会话（强制下线某设备）
  revokeSession: (sessionId) =>
    request(`/auth/sessions/${sessionId}`, { method: 'DELETE' }),

  // 修改密码
  changePassword: (oldPassword, newPassword) =>
    request('/auth/change-password', {
      method: 'POST',
      body: { old_password: oldPassword, new_password: newPassword },
    }),

  // 用户自助修改个人资料（display_name / email）
  updateProfile: (body) =>
    request('/auth/profile', { method: 'PUT', body }),

  // ============ OTP 二次验证 ============

  // OTP 二步验证登录：用第一步返回的 otp_pending_token + 6 位动态码完成登录
  loginOtp: (otpPendingToken, otpCode) =>
    request('/auth/login/otp', {
      method: 'POST',
      body: { otp_pending_token: otpPendingToken, otp_code: otpCode },
    }),

  // 生成 OTP 密钥 + 二维码（绑定第一步）
  otpSetup: () =>
    request('/auth/otp/setup', { method: 'POST' }),

  // 验证 OTP 动态码并正式启用二步验证
  otpEnable: (code) =>
    request('/auth/otp/enable', { method: 'POST', body: { code } }),

  // 解绑 OTP（需验证当前动态码）
  otpDisable: (code) =>
    request('/auth/otp/disable', { method: 'POST', body: { code } }),

  // ============ 多登录方式（登录页 Tab / OTP 直登 / SSO 提供商） ============

  // 系统启用的登录方式全集：返回 { methods: ['password','otp','sso'], sso_enabled, captcha_enabled }
  loginMethods: () => request('/auth/login-methods'),

  // 指定用户可用的登录方式（用户不存在时后端返回系统启用全集）：返回 { methods: [...] }
  userLoginMethods: (username) =>
    request(`/auth/login-methods/user?username=${encodeURIComponent(username)}`),

  // 已启用的 SSO 提供商列表：返回 { providers: [{id, name, type}] }（空数组=未启用）
  ssoProviders: () => request('/auth/sso/providers'),

  // 发送动态验证码（登录用，邮箱 OTP）：返回 { sent: true, dev_code? }
  // 429=60s 内重发；400=该用户不支持验证码登录或未配置邮箱
  otpSend: (username) =>
    request('/auth/otp/send', { method: 'POST', body: { username } }),

  // 验证码直接登录（免密码）：成功返回 { access_token, user }；401=用户名或验证码错误
  otpDirectLogin: (username, otpCode) =>
    request('/auth/login/otp-direct', {
      method: 'POST',
      body: { username, otp_code: otpCode },
    }),

  // ============ SSO 单点登录 ============

  // 获取 SSO 授权跳转 URL：provider 为提供商 id（如 wecom/dingtalk/ldap），
  // redirect 为回调地址（默认登录页）；返回 { authorize_url }
  ssoAuthorize: (provider, redirect) => {
    const qs = new URLSearchParams()
    if (provider) qs.set('provider', provider)
    if (redirect) qs.set('redirect', redirect)
    const query = qs.toString()
    return request(`/auth/sso/authorize${query ? `?${query}` : ''}`)
  },
}

export default authApi
