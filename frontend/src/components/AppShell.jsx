import { useState, useEffect, useRef } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { hasPermission } from '../utils/permissions'
import { authApi } from '../api/auth'
import NotificationBell from './NotificationBell'

// 导航分组配置：按业务逻辑分类排序
// 每项可指定 perm: [module, action] 用于权限过滤
// 支持_children_子项：父项可展开/收起，子项缩进渲染
const NAV_GROUPS = [
  {
    title: '',
    items: [
      { to: '/dashboard', icon: '📊', label: '运营大屏', perm: ['dashboard', 'view'] },
      { to: '/approvals', icon: '🧑‍💻', label: '工作台', perm: ['approval', 'view'] },
      { to: '/chat', icon: '💬', label: '对话', perm: ['agent', 'view'] },
    ],
  },
  {
    title: '编排与资源',
    items: [
      { to: '/agents', icon: '🤖', label: '智能体', perm: ['agent', 'view'] },
      {
        to: '/workflows',
        icon: '📁',
        label: '工作流管理',
        perm: ['workflow', 'view'],
        children: [
          { to: '/workflows', icon: '📋', label: '工作流列表', end: true, perm: ['workflow', 'view'] },
          { to: '/editor', icon: '🛠️', label: '工作流编排', end: true, perm: ['workflow', 'view'] },
        ],
      },
      { to: '/skills', icon: '🎯', label: '技能', perm: ['skill', 'view'] },
      { to: '/tools', icon: '🔧', label: '工具', perm: ['tool', 'view'] },
      { to: '/knowledge-base', icon: '📚', label: '知识库', perm: ['knowledge_base', 'view'] },
    ],
  },
  {
    title: '配置对接',
    items: [
      { to: '/llm-configs', icon: '🧠', label: '模型设置', perm: ['llm_config', 'view'] },
      { to: '/devices', icon: '🛡️', label: '设备对接', perm: ['llm_config', 'view'] },
    ],
  },
  {
    title: '监控追溯',
    items: [
      { to: '/executions', icon: '📜', label: '执行追溯', perm: ['execution', 'view'] },
      { to: '/monitor', icon: '📈', label: '执行监测', perm: ['execution', 'view'] },
      { to: '/banned-ips', icon: '🚫', label: '已封禁 IP', perm: ['execution', 'view'] },
      { to: '/assets', icon: '📋', label: '资产管理', perm: ['execution', 'view'] },
      { to: '/notifications', icon: '🔔', label: '通知中心', perm: ['notification', 'view'] },
    ],
  },
  {
    title: '系统配置',
    items: [
      { to: '/users', icon: '👥', label: '用户管理', perm: ['user', 'view'] },
      { to: '/roles', icon: '🎭', label: '角色管理', perm: ['role', 'view'] },
      { to: '/system-settings', icon: '⚙️', label: '系统设置', perm: ['system_config', 'view'] },
      { to: '/system-monitor', icon: '🩺', label: '系统监控', perm: ['system_monitor', 'view'] },
      { to: '/backup', icon: '💾', label: '备份恢复', perm: ['system_config', 'view'] },
    ],
  },
]

// 角色中文映射
const ROLE_LABELS = {
  admin: '管理员',
  analyst: '分析师',
  viewer: '访客',
}

// 路由 → 面包屑映射
const BREADCRUMB_MAP = {
  '/dashboard': ['运营大屏'],
  '/approvals': ['工作台'],
  '/chat': ['对话'],
  '/agents': ['编排与资源', '智能体'],
  '/workflows': ['编排与资源', '工作流管理'],
  '/editor': ['编排与资源', '工作流管理', '工作流编排'],
  '/skills': ['编排与资源', '技能'],
  '/tools': ['编排与资源', '工具'],
  '/knowledge-base': ['编排与资源', '知识库'],
  '/llm-configs': ['配置对接', '模型设置'],
  '/devices': ['配置对接', '设备对接'],
  '/executions': ['监控追溯', '执行追溯'],
  '/monitor': ['监控追溯', '执行监测'],
  '/banned-ips': ['监控追溯', '已封禁 IP'],
  '/assets': ['监控追溯', '资产管理'],
  '/notifications': ['监控追溯', '通知中心'],
  '/agent-tutorial': ['智能体', '使用教程'],
  '/users': ['系统配置', '用户管理'],
  '/roles': ['系统配置', '角色管理'],
  '/system-settings': ['系统配置', '系统设置'],
  '/system-monitor': ['系统配置', '系统监控'],
  '/backup': ['系统配置', '备份恢复'],
}

// 根据路径生成面包屑
function getBreadcrumbs(pathname) {
  // 精确匹配
  if (BREADCRUMB_MAP[pathname]) return BREADCRUMB_MAP[pathname]
  // 模糊匹配动态路由
  if (pathname.startsWith('/agents/') && pathname.endsWith('/edit')) return ['智能体', '编辑']
  if (pathname.startsWith('/agents/') && pathname.endsWith('/monitor')) return ['智能体', '监控']
  if (pathname.startsWith('/tools/') && pathname.endsWith('/edit')) return ['工具', '编辑']
  if (pathname.startsWith('/tools/new')) return ['工具', '新建']
  if (pathname.startsWith('/agents/new')) return ['智能体', '新建']
  return []
}

// 应用外层导航框架：左侧可折叠垂直导航 + 右侧页面内容区
function AppShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const token = useAuthStore((s) => s.token)
  const setAuth = useAuthStore((s) => s.setAuth)
  const logout = useAuthStore((s) => s.logout)

  // 侧边栏折叠状态（localStorage 持久化）
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('soar_sidebar_collapsed') === '1'
    } catch {
      return false
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('soar_sidebar_collapsed', collapsed ? '1' : '0')
    } catch {
      // ignore
    }
  }, [collapsed])
  // 系统版本号与平台名称（从后端获取，左上角与页签显示）
  const [appVersion, setAppVersion] = useState('')
  const [platformName, setPlatformName] = useState('SOAR 平台')
  useEffect(() => {
    fetch('/api/v1/version')
      .then((r) => r.json())
      .then((d) => {
        setAppVersion(d.version || '')
        if (d.platform_name) {
          setPlatformName(d.platform_name)
          document.title = d.platform_name
        }
      })
      .catch(() => {})
  }, [])

  // 子菜单展开状态：记录哪些父项已展开（按父项 to 路径）
  // 默认展开包含当前路由的父项
  const [expandedParents, setExpandedParents] = useState(() => {
    try {
      const saved = localStorage.getItem('soar_nav_expanded')
      if (saved) return new Set(JSON.parse(saved))
    } catch {
      // ignore
    }
    return new Set(['/workflows']) // 默认展开工作流管理
  })
  useEffect(() => {
    try {
      localStorage.setItem('soar_nav_expanded', JSON.stringify([...expandedParents]))
    } catch {
      // ignore
    }
  }, [expandedParents])

  const toggleParent = (to) => {
    setExpandedParents((prev) => {
      const next = new Set(prev)
      if (next.has(to)) next.delete(to)
      else next.add(to)
      return next
    })
  }

  // 挂载时刷新当前用户信息，确保 display_name 等字段为最新
  useEffect(() => {
    if (!token) return
    authApi
      .me()
      .then((fresh) => {
        if (fresh && fresh.id) setAuth(token, fresh)
      })
      .catch(() => {
        // /auth/me 失败时保留旧数据，不强制登出
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 用户下拉菜单
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef(null)
  useEffect(() => {
    if (!userMenuOpen) return
    function handleMouseDown(e) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [userMenuOpen])

  const breadcrumbs = getBreadcrumbs(location.pathname)

  const handleLogout = () => {
    setUserMenuOpen(false)
    logout()
    navigate('/login', { replace: true })
  }

  // 过滤无权限的导航项（含子项权限过滤）
  const visibleGroups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items
      .filter((it) => !it.perm || hasPermission(it.perm[0], it.perm[1]))
      .map((it) =>
        it.children
          ? {
              ...it,
              children: it.children.filter(
                (c) => !c.perm || hasPermission(c.perm[0], c.perm[1])
              ),
            }
          : it
      ),
  })).filter((g) => g.items.length > 0)

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-gray-950 text-gray-100">
      {/* 左侧垂直导航栏（可折叠） */}
      <aside
        className={`relative z-sticky flex shrink-0 flex-col border-r border-gray-800 bg-gray-900 transition-all duration-200 ${
          collapsed ? 'w-[56px]' : 'w-[200px]'
        }`}
      >
        {/* 品牌 Logo 区 + 折叠按钮 */}
        <div
          className={`flex items-center border-b border-gray-800 py-4 ${
            collapsed ? 'justify-center px-2' : 'gap-2 px-4'
          }`}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-gradient-to-br from-brand-400 to-brand-600 text-sm font-bold text-white">
            S
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1 leading-tight">
              <div className="truncate text-sm font-semibold text-gray-100">
                {platformName}
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? '展开侧边栏' : '收起侧边栏'}
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-200 ${
              collapsed ? 'absolute right-2 top-3' : ''
            }`}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ transform: collapsed ? 'rotate(180deg)' : 'none' }}
            >
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
        </div>

        {/* 导航菜单（分组渲染，支持子项展开/收起） */}
        <nav className="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
          {visibleGroups.map((group, gi) => (
            <div key={gi} className="flex flex-col gap-1">
              {group.title && !collapsed && (
                <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-600">
                  {group.title}
                </div>
              )}
              {group.items.map((item) => {
                const hasChildren = item.children && item.children.length > 0
                const isExpanded = expandedParents.has(item.to)
                return (
                  <div key={item.to} className="flex flex-col gap-1">
                    <div className="flex items-center">
                      <NavLink
                        to={item.to}
                        end={item.end}
                        title={collapsed ? item.label : undefined}
                        className={({ isActive }) =>
                          `flex flex-1 items-center rounded-md text-sm transition-colors ${
                            collapsed
                              ? 'justify-center px-2 py-2.5'
                              : 'gap-3 px-3 py-2.5'
                          } ${
                            isActive
                              ? 'bg-gradient-to-r from-brand-500/20 to-brand-500/10 text-brand-300 ring-1 ring-brand-500/40'
                              : 'text-gray-400 hover:bg-gray-800/60 hover:text-gray-200'
                          }`
                        }
                      >
                        <span className="text-base">{item.icon}</span>
                        {!collapsed && (
                          <span className="font-medium">{item.label}</span>
                        )}
                      </NavLink>
                      {/* 展开/收起按钮（仅有子项且侧边栏展开时显示） */}
                      {hasChildren && !collapsed && (
                        <button
                          type="button"
                          onClick={() => toggleParent(item.to)}
                          title={isExpanded ? '收起' : '展开'}
                          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-200"
                        >
                          <svg
                            width="12"
                            height="12"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            style={{ transform: isExpanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
                          >
                            <polyline points="9 18 15 12 9 6" />
                          </svg>
                        </button>
                      )}
                    </div>
                    {/* 子项列表（展开时渲染，缩进显示） */}
                    {hasChildren && isExpanded && !collapsed && (
                      <div className="flex flex-col gap-0.5 pl-4">
                        {item.children.map((child) => (
                          <NavLink
                            key={child.to}
                            to={child.to}
                            end={child.end}
                            title={child.label}
                            className={({ isActive }) =>
                              `flex items-center rounded-md px-3 py-1.5 text-sm transition-colors ${
                                isActive
                                  ? 'bg-brand-500/15 text-brand-300 ring-1 ring-brand-500/30'
                                  : 'text-gray-500 hover:bg-gray-800/60 hover:text-gray-300'
                              }`
                            }
                          >
                            <span className="mr-2 text-xs">{child.icon}</span>
                            <span className="font-medium">{child.label}</span>
                          </NavLink>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </nav>

        {/* 底部用户信息 + 个人中心 + 登出 */}
        <div className={`border-t border-gray-800 py-3 ${collapsed ? 'px-2' : 'px-3'}`}>
          {user && (
            <div
              className={`mb-2 flex items-center ${
                collapsed ? 'flex-col gap-1' : 'gap-2'
              }`}
            >
              <NavLink
                to="/profile"
                title="个人中心"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-xs font-semibold text-brand-300 transition-colors hover:bg-brand-500/40"
              >
                {(user.username || '?')[0].toUpperCase()}
              </NavLink>
              {!collapsed && (
                <div className="min-w-0 flex-1 leading-tight">
                  <div className="truncate text-xs font-medium text-gray-300">
                    {user.display_name || user.username}
                  </div>
                  <div className="text-[10px] text-gray-500">
                    {ROLE_LABELS[user.role] || user.role}
                  </div>
                </div>
              )}
              <NavLink
                to="/profile"
                title="个人中心"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-200"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
              </NavLink>
              <button
                type="button"
                onClick={handleLogout}
                title="退出登录"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-gray-500 transition-colors hover:bg-danger-500/10 hover:text-danger-400"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
              </button>
            </div>
          )}
          {!collapsed && (
            <div className="text-[10px] text-gray-600">v{appVersion || '...'} · 安全增强版</div>
          )}
        </div>
      </aside>

      {/* 右侧页面内容区：填满剩余宽度 */}
      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* 顶部栏：面包屑 + 用户信息 + 通知铃铛 */}
        <div className="flex h-11 shrink-0 items-center justify-between border-b border-gray-800 bg-gray-900/80 px-4 backdrop-blur">
          {/* 左侧：面包屑 */}
          <div className="flex min-w-0 items-center gap-1.5 text-sm">
            {breadcrumbs.length > 0 ? (
              breadcrumbs.map((crumb, idx) => (
                <span key={idx} className="flex items-center gap-1.5">
                  {idx > 0 && <span className="text-gray-600">/</span>}
                  <span
                    className={
                      idx === breadcrumbs.length - 1
                        ? 'text-gray-200'
                        : 'text-gray-500'
                    }
                  >
                    {crumb}
                  </span>
                </span>
              ))
            ) : (
              <span className="text-gray-600">{platformName}</span>
            )}
          </div>

          {/* 右侧：用户信息 + 通知 */}
          <div className="flex items-center gap-3">
            {/* 用户信息下拉 */}
            <div ref={userMenuRef} className="relative">
              <button
                type="button"
                onClick={() => setUserMenuOpen((o) => !o)}
                className="flex items-center gap-2 rounded-md px-2 py-1 text-sm text-gray-300 transition-colors hover:bg-gray-800"
              >
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-500/20 text-xs font-semibold text-brand-300">
                  {(user?.username || 'U').charAt(0).toUpperCase()}
                </div>
                <span className="hidden max-w-[120px] truncate sm:inline">
                  {user?.display_name || user?.username || '用户'}
                </span>
                <span className="hidden rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400 md:inline">
                  {ROLE_LABELS[user?.role] || user?.role || '-'}
                </span>
              </button>
              {userMenuOpen && (
                <div className="absolute right-0 z-dropdown mt-1 w-48 overflow-hidden rounded-lg border border-gray-700 bg-gray-800 shadow-xl">
                  <div className="border-b border-gray-700 px-4 py-2.5">
                    <div className="truncate text-sm font-medium text-gray-100">
                      {user?.display_name || user?.username || '用户'}
                    </div>
                    <div className="text-[11px] text-gray-500">
                      {ROLE_LABELS[user?.role] || user?.role || '-'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setUserMenuOpen(false)
                      navigate('/system-settings')
                    }}
                    className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-gray-300 transition-colors hover:bg-gray-700"
                  >
                    <span>⚙️</span>
                    <span>系统设置</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleLogout}
                    className="flex w-full items-center gap-2 border-t border-gray-700 px-4 py-2 text-left text-sm text-danger-400 transition-colors hover:bg-gray-700"
                  >
                    <span>🚪</span>
                    <span>退出登录</span>
                  </button>
                </div>
              )}
            </div>
            <NotificationBell />
          </div>
        </div>
        {/* 页面内容 */}
        <div className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </div>
      </div>
    </div>
  )
}

export default AppShell
