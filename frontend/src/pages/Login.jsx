import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../store/authStore'

// 登录页：用户名密码登录，获取 JWT 后跳转主页
function Login() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await authApi.login(username.trim(), password)
      setAuth(res.access_token, res.user)
      navigate('/editor', { replace: true })
    } catch (err) {
      setError(err.message || '登录失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center overflow-hidden bg-gray-950">
      {/* 背景装饰 */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-40 -top-40 h-96 w-96 rounded-full bg-brand-500/10 blur-3xl" />
        <div className="absolute -bottom-40 -right-40 h-96 w-96 rounded-full bg-brand-500/10 blur-3xl" />
      </div>

      {/* 登录卡片 */}
      <div className="relative w-full max-w-md">
        <div className="rounded-2xl border border-gray-800 bg-gray-900/80 p-8 shadow-2xl backdrop-blur">
          {/* Logo */}
          <div className="mb-8 flex flex-col items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 text-2xl font-bold text-white shadow-lg">
              S
            </div>
            <div className="text-center">
              <h1 className="text-xl font-semibold text-gray-100">SOAR 平台</h1>
              <p className="mt-1 text-xs text-gray-500">安全编排自动化响应</p>
            </div>
          </div>

          {/* 表单 */}
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-400">
                用户名
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="请输入用户名"
                className="w-full rounded-lg border border-gray-700 bg-gray-800/60 px-3.5 py-2.5 text-sm text-gray-100 placeholder-gray-600 outline-none transition-colors focus:border-brand-500/60 focus:ring-1 focus:ring-brand-500/40"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-400">
                密码
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="请输入密码"
                className="w-full rounded-lg border border-gray-700 bg-gray-800/60 px-3.5 py-2.5 text-sm text-gray-100 placeholder-gray-600 outline-none transition-colors focus:border-brand-500/60 focus:ring-1 focus:ring-brand-500/40"
              />
            </div>

            {error && (
              <div className="rounded-lg border border-danger-500/40 bg-danger-500/10 px-3.5 py-2 text-xs text-red-300">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="mt-2 w-full btn-primary"
            >
              {loading ? '登录中...' : '登 录'}
            </button>
          </form>

          {/* 默认账号提示 */}
          <div className="mt-6 rounded-lg border border-gray-800 bg-gray-800/40 px-3.5 py-2.5 text-[11px] text-gray-500">
            <div className="font-medium text-gray-400">默认管理员账号</div>
            <div className="mt-1 font-mono">
              admin / admin123
            </div>
            <div className="mt-1 text-gray-600">
              首次部署后请及时修改密码
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Login
