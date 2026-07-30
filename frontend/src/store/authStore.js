// 鉴权状态管理：token 与用户信息持久化到 localStorage
import { create } from 'zustand'

const TOKEN_KEY = 'soar_token'
const USER_KEY = 'soar_user'

/**
 * 从 localStorage 恢复初始状态
 */
function loadToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || null
  } catch {
    return null
  }
}

function loadUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const useAuthStore = create((set, get) => ({
  token: loadToken(),
  user: loadUser(),

  // 是否已登录
  isAuthenticated: () => !!get().token,

  // 登录成功后保存凭证
  setAuth: (token, user) => {
    try {
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    } catch {
      // localStorage 不可用时仅内存保存
    }
    set({ token, user })
  },

  // 登出：清除凭证
  logout: () => {
    try {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    } catch {
      // ignore
    }
    set({ token: null, user: null })
  },
}))

export default useAuthStore
