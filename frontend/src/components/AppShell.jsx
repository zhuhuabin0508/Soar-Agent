import { useState, useEffect, useRef, useCallback } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Workflow as WorkflowIcon, MessageSquare, Bot, FolderKanban,
  List as ListIcon, Wrench, Target, BookOpen, BrainCircuit, Shield,
  ScrollText, ClipboardList, Bell, Users, ShieldCheck,
  Settings, HeartPulse, DatabaseBackup, LogOut, ChevronLeft, ChevronRight,
  ChevronsRight, UserRound, PieChart, Boxes, Info, Bug, MessageSquareWarning, Inbox, PackageCheck,
  CalendarClock, CalendarRange, CalendarX, History, Monitor, FileJson, BellRing, Activity,
  ShieldBan, Filter,
} from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import { hasPermission } from '../utils/permissions'
import { authApi } from '../api/auth'
import NotificationBell from './NotificationBell'
import ThemeToggle from './ThemeToggle'
import PageTransition from './PageTransition'
import ForceChangePassword from './ForceChangePassword'
import FeedbackDrawer from './FeedbackDrawer'
import { GlobalHotkeys } from '../App'

// 导航分组配置：按业务逻辑分类排序
// icon 使用 lucide-react 矢量图标组件（替代 emoji，保证跨平台一致与可调色）
// 每项可指定 perm: [module, action] 用于权限过滤
// 支持 children 子项：父项可展开/收起，子项缩进渲染
const NAV_GROUPS = [
  {
    title: '运营中心',
    items: [
      { to: '/dashboard', icon: LayoutDashboard, label: '运营大屏', perm: ['dashboard', 'view'] },
      { to: '/approvals', icon: WorkflowIcon, label: '工作台', perm: ['approval', 'view'] },
      { to: '/chat', icon: MessageSquare, label: '对话', perm: ['chat', 'view'] },
    ],
  },
  {
    title: '智能体编排',
    items: [
      { to: '/agents', icon: Bot, label: '智能体', perm: ['agent', 'view'] },
      {
        to: '/workflows',
        icon: FolderKanban,
        label: '工作流',
        perm: ['workflow_list', 'view'],
        children: [
          { to: '/workflows', icon: ListIcon, label: '工作流列表', end: true, perm: ['workflow_list', 'view'] },
          { to: '/editor', icon: Wrench, label: '工作流编排', end: true, perm: ['workflow_editor', 'view'] },
          { to: '/ban-workflow/rules', icon: Filter, label: '触发规则', end: true, perm: ['ban_workflow', 'view'] },
        ],
      },
      { to: '/skills', icon: Target, label: '技能', perm: ['skill', 'view'] },
      { to: '/tools', icon: Wrench, label: '工具', perm: ['tool', 'view'] },
      { to: '/knowledge-base', icon: BookOpen, label: '知识库', perm: ['knowledge_base', 'view'] },
    ],
  },
  {
    title: '资源管理',
    items: [
      {
        to: '/assets',
        icon: ClipboardList,
        label: '资产管理',
        perm: ['asset_overview', 'view'],
        children: [
          { to: '/assets', icon: PieChart, label: '资产总览', end: true, perm: ['asset_overview', 'view'] },
          { to: '/assets/list', icon: ListIcon, label: '资产清单', end: true, perm: ['asset_list', 'view'] },
          { to: '/assets/templates', icon: Boxes, label: '类型模板', end: true, perm: ['asset_templates', 'view'] },
        ],
      },
      { to: '/deliverables', icon: PackageCheck, label: '材料管理', perm: ['deliverable', 'view'] },
    ],
  },
  {
    title: '运营管理',
    items: [
      {
        to: '/duty/members',
        icon: CalendarClock,
        label: '值班管理',
        perm: ['duty', 'view'],
        children: [
          { to: '/duty/members', icon: Users, label: '值班人员', end: true, perm: ['duty_member', 'view'] },
          { to: '/duty/schedule', icon: CalendarRange, label: '值班表', end: true, perm: ['duty_schedule', 'view'] },
          { to: '/duty/leaves', icon: CalendarX, label: '请假管理', end: true, perm: ['duty_leave', 'view'] },
          { to: '/duty/logs', icon: History, label: '调班记录', end: true, perm: ['duty_log', 'view'] },
        ],
      },
      { to: '/strategies', icon: FileJson, label: '解析策略', perm: ['strategy', 'view'] },
      { to: '/alerts', icon: BellRing, label: '告警列表', perm: ['alert', 'view'] },
      { to: '/ingest-monitor', icon: Activity, label: '入库监控', perm: ['monitor', 'view'] },
    ],
  },
  {
    title: '连接配置',
    items: [
      { to: '/llm-configs', icon: BrainCircuit, label: '模型设置', perm: ['llm_config', 'view'] },
      { to: '/devices', icon: Shield, label: '设备对接', perm: ['device', 'view'] },
    ],
  },
  {
    title: '运行监控',
    items: [
      { to: '/executions', icon: ScrollText, label: '日志中心', perm: ['execution', 'view'] },
      { to: '/notifications', icon: Bell, label: '通知中心', perm: ['notification', 'view'] },
    ],
  },
  {
    title: '系统管理',
    items: [
      { to: '/users', icon: Users, label: '用户管理', perm: ['user', 'view'] },
      { to: '/roles', icon: ShieldCheck, label: '角色管理', perm: ['role', 'view'] },
      { to: '/system-settings', icon: Settings, label: '系统设置', perm: ['system_config', 'view'] },
      { to: '/system-monitor', icon: HeartPulse, label: '系统监控', perm: ['system_monitor', 'view'] },
      { to: '/backup', icon: DatabaseBackup, label: '备份恢复', perm: ['system_config', 'view'] },
      { to: '/feedbacks/admin', icon: Bug, label: '反馈管理', perm: ['feedback', 'view'] },
      { to: '/about', icon: Info, label: '关于', perm: ['system_config', 'view'] },
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
  '/dashboard': ['运营中心', '运营大屏'],
  '/approvals': ['运营中心', '工作台'],
  '/chat': ['运营中心', '对话'],
  '/agents': ['智能体编排', '智能体'],
  '/workflows': ['智能体编排', '工作流', '工作流列表'],
  '/workflows/:id/monitor': ['智能体编排', '工作流', '监控'],
  '/editor': ['智能体编排', '工作流', '工作流编排'],
  '/skills': ['智能体编排', '技能'],
  '/tools': ['智能体编排', '工具'],
  '/knowledge-base': ['智能体编排', '知识库'],
  '/llm-configs': ['连接配置', '模型设置'],
  '/devices': ['连接配置', '设备对接'],
  '/executions': ['运行监控', '日志中心'],
  '/logs': ['运行监控', '日志中心'],
  '/assets': ['资源管理', '资产管理', '资产总览'],
  '/assets/list': ['资源管理', '资产管理', '资产清单'],
  '/assets/templates': ['资源管理', '资产管理', '类型模板'],
  '/assets/legacy': ['资源管理', '资产管理'],
  '/deliverables': ['资源管理', '材料管理'],
  '/duty/members': ['运营管理', '值班管理', '值班人员'],
  '/duty/schedule': ['运营管理', '值班管理', '值班表'],
  '/duty/leaves': ['运营管理', '值班管理', '请假管理'],
  '/duty/logs': ['运营管理', '值班管理', '调班记录'],
  '/strategies': ['运营管理', '解析策略'],
  '/strategies/new': ['运营管理', '解析策略', '新建'],
  '/strategies/:id/edit': ['运营管理', '解析策略', '编辑'],
  '/alerts': ['运营管理', '告警列表'],
  '/ingest-monitor': ['运营管理', '入库监控'],
  '/ban-workflow/rules': ['智能体编排', '工作流', '触发规则'],
  '/notifications': ['运行监控', '通知中心'],
  '/agent-tutorial': ['智能体', '使用教程'],
  '/users': ['系统管理', '用户管理'],
  '/roles': ['系统管理', '角色管理'],
  '/system-settings': ['系统管理', '系统设置'],
  '/system-monitor': ['系统管理', '系统监控'],
  '/backup': ['系统管理', '备份恢复'],
  '/feedbacks/admin': ['系统管理', '反馈管理'],
  '/about': ['系统管理', '关于'],
  '/feedbacks/mine': ['个人中心', '我的反馈'],
}

// 右下角可拖动反馈按钮：避免遮挡其他按钮
// - 鼠标按住可拖动；位移 < 5px 视为单击，打开反馈抽屉
// - 松开后自动吸附到最近的左/右边缘
// - 边界约束在视口内；位置持久化到 localStorage
const FEEDBACK_BTN_STORAGE_KEY = 'soar_feedback_btn_pos_v1'
const FEEDBACK_BTN_MARGIN = 4
const FEEDBACK_BTN_DRAG_THRESHOLD = 5

function DraggableFeedbackButton({ onClick }) {
  const btnRef = useRef(null)
  const [pos, setPos] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(FEEDBACK_BTN_STORAGE_KEY) || 'null')
      if (saved && typeof saved.x === 'number' && typeof saved.y === 'number') {
        return saved
      }
    } catch { /* ignore */ }
    return null // null 表示使用默认右下角
  })

  const draggingRef = useRef(false)
  const downPosRef = useRef({ x: 0, y: 0 })
  const downBtnPosRef = useRef({ x: 0, y: 0 })
  const movedRef = useRef(false)

  const persist = useCallback((p) => {
    try { localStorage.setItem(FEEDBACK_BTN_STORAGE_KEY, JSON.stringify(p)) } catch { /* ignore */ }
  }, [])

  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return
    // 只响应主按钮，避免影响右键菜单
    if (!btnRef.current) return
    e.preventDefault()
    const rect = btnRef.current.getBoundingClientRect()
    downPosRef.current = { x: e.clientX, y: e.clientY }
    downBtnPosRef.current = { x: rect.left, y: rect.top }
    movedRef.current = false
    draggingRef.current = true
    document.body.style.userSelect = 'none'
  }, [])

  useEffect(() => {
    const onMove = (e) => {
      if (!draggingRef.current || !btnRef.current) return
      const dx = e.clientX - downPosRef.current.x
      const dy = e.clientY - downPosRef.current.y
      if (Math.abs(dx) >= FEEDBACK_BTN_DRAG_THRESHOLD || Math.abs(dy) >= FEEDBACK_BTN_DRAG_THRESHOLD) {
        movedRef.current = true
      }
      const w = btnRef.current.offsetWidth
      const h = btnRef.current.offsetHeight
      const maxX = window.innerWidth - w - FEEDBACK_BTN_MARGIN
      const maxY = window.innerHeight - h - FEEDBACK_BTN_MARGIN
      const newX = Math.max(FEEDBACK_BTN_MARGIN, Math.min(maxX, downBtnPosRef.current.x + dx))
      const newY = Math.max(FEEDBACK_BTN_MARGIN, Math.min(maxY, downBtnPosRef.current.y + dy))
      setPos({ x: newX, y: newY })
    }
    const onUp = () => {
      if (!draggingRef.current) return
      draggingRef.current = false
      document.body.style.userSelect = ''
      // 松开后吸附到最近的左/右边缘
      setPos((p) => {
        if (!p || !btnRef.current) return p
        const w = btnRef.current.offsetWidth
        const half = window.innerWidth / 2
        const snapped = (p.x + w / 2 < half)
          ? { ...p, x: FEEDBACK_BTN_MARGIN }
          : { ...p, x: window.innerWidth - w - FEEDBACK_BTN_MARGIN }
        persist(snapped)
        return snapped
      })
      // 未拖动则视为点击
      if (!movedRef.current) onClick()
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
  }, [onClick, persist])

  // 窗口尺寸变化时约束位置
  useEffect(() => {
    const onResize = () => {
      setPos((p) => {
        if (!p || !btnRef.current) return p
        const w = btnRef.current.offsetWidth
        const h = btnRef.current.offsetHeight
        const maxX = window.innerWidth - w - FEEDBACK_BTN_MARGIN
        const maxY = window.innerHeight - h - FEEDBACK_BTN_MARGIN
        const clamped = {
          x: Math.max(FEEDBACK_BTN_MARGIN, Math.min(maxX, p.x)),
          y: Math.max(FEEDBACK_BTN_MARGIN, Math.min(maxY, p.y)),
        }
        persist(clamped)
        return clamped
      })
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [persist])

  const style = pos
    ? { left: `${pos.x}px`, top: `${pos.y}px`, right: 'auto', bottom: 'auto' }
    : { right: '24px', bottom: '24px' }

  return (
    <div
      ref={btnRef}
      className="group fixed z-40"
      style={style}
      onMouseDown={handleMouseDown}
      title="提交反馈（按住可拖动）"
    >
      <button
        type="button"
        // 点击由 mouseup 处理（区分拖动/点击）；此处禁用原生 click 触发
        onClick={(e) => e.preventDefault()}
        aria-label="提交反馈（按住可拖动）"
        className="flex h-12 cursor-grab items-center rounded-full bg-primary px-3.5 text-primary-foreground shadow-lg shadow-primary/20 transition-all duration-200 hover:px-4 hover:shadow-primary/40 active:cursor-grabbing"
      >
        <MessageSquareWarning className="h-5 w-5 shrink-0" />
        <span className="max-w-0 overflow-hidden whitespace-nowrap text-sm font-medium opacity-0 transition-all duration-200 group-hover:ml-1.5 group-hover:max-w-[96px] group-hover:opacity-100">
          提交反馈
        </span>
      </button>
    </div>
  )
}

// 根据路径生成面包屑
function getBreadcrumbs(pathname) {
  // 精确匹配
  if (BREADCRUMB_MAP[pathname]) return BREADCRUMB_MAP[pathname]
  // 模糊匹配动态路由
  if (pathname.startsWith('/agents/') && pathname.endsWith('/edit')) return ['智能体', '编辑']
  if (pathname.startsWith('/agents/') && pathname.endsWith('/monitor')) return ['智能体', '监控']
  if (pathname.startsWith('/workflows/') && pathname.endsWith('/monitor')) return ['智能体编排', '工作流', '监控']
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
  // 版本化 key：默认收起策略调整（v3），清除历史展开偏好重新开始
  const NAV_EXPANDED_KEY = 'soar_nav_expanded_v3'
  const [expandedParents, setExpandedParents] = useState(() => {
    // 二级菜单默认收起，仅自动展开当前路由对应的父项（确保当前页面导航可见）
    const defaults = new Set()
    const path = location.pathname
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        if (item.children && (path === item.to || path.startsWith(item.to + '/') ||
            item.children.some((c) => path === c.to))) {
          defaults.add(item.to)
        }
      }
    }
    // 合并用户保存的展开偏好（用户主动展开的其他项）
    try {
      const saved = localStorage.getItem(NAV_EXPANDED_KEY)
      if (saved) {
        const savedArr = JSON.parse(saved)
        return new Set([...defaults, ...savedArr])
      }
    } catch {
      // ignore
    }
    return defaults
  })
  useEffect(() => {
    try {
      localStorage.setItem(NAV_EXPANDED_KEY, JSON.stringify([...expandedParents]))
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

  // 提交反馈抽屉（用户菜单与右下角悬浮按钮共用）
  const [feedbackOpen, setFeedbackOpen] = useState(false)
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

  const handleLogout = async () => {
    setUserMenuOpen(false)
    // 调用后端登出接口（拉黑 token），然后清除本地凭证
    await logout()
    navigate('/login', { replace: true })
  }

  // 过滤无权限的导航项（含子项权限过滤）
  const visibleGroups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items
      .map((it) =>
        it.children
          ? {
              ...it,
              children: it.children.filter(
                (c) => !c.perm || hasPermission(c.perm[0], c.perm[1])
              ),
            }
          : it
      )
      // 父级目录：只要有任一可见子项即保留；叶子项：按自身权限过滤
      .filter((it) =>
        it.children ? it.children.length > 0 : !it.perm || hasPermission(it.perm[0], it.perm[1])
      ),
  })).filter((g) => g.items.length > 0)

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      {/* 左侧垂直导航栏（可折叠） */}
      <aside
        className={`relative z-sticky flex shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-all duration-200 ${
          collapsed ? 'w-[56px]' : 'w-[220px]'
        }`}
      >
        {/* 品牌 Logo 区 + 折叠按钮 */}
        <div
          className={`flex items-center border-b border-sidebar-border py-4 ${
            collapsed ? 'justify-center px-2' : 'gap-2 px-4'
          }`}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-primary to-primary/70 text-sm font-bold text-primary-foreground">
            S
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1 leading-tight">
              <div className="truncate text-sm font-semibold text-sidebar-foreground">
                {platformName}
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? '展开侧边栏' : '收起侧边栏'}
            aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground ${
              collapsed ? 'absolute right-2 top-3' : ''
            }`}
          >
            <ChevronLeft
              className="h-3.5 w-3.5"
              style={{ transform: collapsed ? 'rotate(180deg)' : 'none' }}
            />
          </button>
        </div>

        {/* 导航菜单（分组渲染，支持子项展开/收起） */}
        <nav className="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
          {visibleGroups.map((group, gi) => {
            // 分组内是否有激活项（用于分组标题轻微高亮，帮助定位）
            const groupHasActive = group.items.some((it) =>
              location.pathname === it.to ||
              location.pathname.startsWith(it.to + '/') ||
              (it.children || []).some((c) => location.pathname === c.to)
            )
            return (
              <div key={gi} className="flex flex-col gap-1">
                {group.title && !collapsed && (
                  <div
                    className={`px-3 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wider transition-colors ${
                      groupHasActive ? 'text-primary/80' : 'text-muted-foreground/70'
                    }`}
                  >
                    {group.title}
                  </div>
                )}
                {group.items.map((item) => {
                  const hasChildren = item.children && item.children.length > 0
                  const isExpanded = expandedParents.has(item.to)
                  // 父项高亮：自身激活或任一子项激活
                  const childActive = (item.children || []).some(
                    (c) => location.pathname === c.to
                  )
                  const ItemIcon = item.icon
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
                              isActive || childActive
                                ? 'bg-primary/10 text-primary ring-1 ring-primary/30'
                                : 'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground'
                            }`
                          }
                        >
                          {ItemIcon && <ItemIcon className="h-[18px] w-[18px] shrink-0" />}
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
                            aria-label={isExpanded ? '收起子菜单' : '展开子菜单'}
                            className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
                          >
                            <ChevronRight
                              className="h-3 w-3"
                              style={{ transform: isExpanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
                            />
                          </button>
                        )}
                      </div>
                      {/* 子项列表（展开时渲染，三级菜单缩进加深 + 字号/颜色更淡，明确层级） */}
                      {hasChildren && isExpanded && !collapsed && (
                        <div className="flex flex-col gap-0.5 pl-6">
                          {item.children.map((child) => {
                            const ChildIcon = child.icon
                            return (
                              <NavLink
                                key={child.to}
                                to={child.to}
                                end={child.end}
                                title={child.label}
                                className={({ isActive }) =>
                                  `flex items-center rounded-md px-3 py-1.5 text-[13px] transition-colors ${
                                    isActive
                                      ? 'bg-primary/10 text-primary ring-1 ring-primary/30'
                                      : 'text-muted-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-foreground'
                                  }`
                                }
                              >
                                {ChildIcon && <ChildIcon className="mr-2 h-3.5 w-3.5" />}
                                <span className="font-normal">{child.label}</span>
                              </NavLink>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </nav>

        {/* 底部用户信息 + 个人中心 + 登出（版本号已移至「关于」页面） */}
        <div className={`border-t border-sidebar-border py-3 ${collapsed ? 'px-2' : 'px-3'}`}>
          {user && (
            <div
              className={`flex items-center ${
                collapsed ? 'flex-col gap-1' : 'gap-2'
              }`}
            >
              <NavLink
                to="/profile"
                title="个人中心"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary transition-colors hover:bg-primary/30"
              >
                {(user.username || '?')[0].toUpperCase()}
              </NavLink>
              {!collapsed && (
                <div className="min-w-0 flex-1 leading-tight">
                  <div className="truncate text-xs font-medium text-sidebar-foreground">
                    {user.display_name || user.username}
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    {ROLE_LABELS[user.role_name] || user.role_name || ROLE_LABELS[user.role] || user.role}
                  </div>
                </div>
              )}
              <NavLink
                to="/profile"
                title="个人中心"
                aria-label="个人中心"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
              >
                <UserRound className="h-3.5 w-3.5" />
              </NavLink>
              <button
                type="button"
                onClick={handleLogout}
                title="退出登录"
                aria-label="退出登录"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* 右侧页面内容区：填满剩余宽度 */}
      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* 顶部栏：面包屑 + 用户信息 + 通知铃铛（毛玻璃半透明）
            relative z-sticky：顶栏整体抬升至 z-30，避免下方 overflow-auto 页面内容区
            （同样形成层叠上下文）覆盖下拉菜单的溢出部分 */}
        <div className="relative z-sticky flex h-11 shrink-0 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur">
          {/* 左侧：面包屑 */}
          <div className="flex min-w-0 items-center gap-1.5 text-sm">
            {breadcrumbs.length > 0 ? (
              breadcrumbs.map((crumb, idx) => (
                <span key={idx} className="flex items-center gap-1.5">
                  {idx > 0 && <ChevronsRight className="h-3.5 w-3.5 text-muted-foreground/50" />}
                  <span
                    className={
                      idx === breadcrumbs.length - 1
                        ? 'text-foreground'
                        : 'text-muted-foreground'
                    }
                  >
                    {crumb}
                  </span>
                </span>
              ))
            ) : (
              <span className="text-muted-foreground">{platformName}</span>
            )}
          </div>

          {/* 右侧：主题切换 + 用户信息 + 通知 */}
          <div className="flex items-center gap-3">
            <ThemeToggle />
            {/* 用户信息下拉 */}
            <div ref={userMenuRef} className="relative">
              <button
                type="button"
                onClick={() => setUserMenuOpen((o) => !o)}
                className="flex items-center gap-2 rounded-md px-2 py-1 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
                  {(user?.username || 'U').charAt(0).toUpperCase()}
                </div>
                <span className="hidden max-w-[120px] truncate sm:inline">
                  {user?.display_name || user?.username || '用户'}
                </span>
                <span className="hidden rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground md:inline">
                  {ROLE_LABELS[user?.role_name] || user?.role_name || ROLE_LABELS[user?.role] || user?.role || '-'}
                </span>
              </button>
              {userMenuOpen && (
                <div className="absolute right-0 z-dropdown mt-1 w-48 overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-xl">
                  <div className="border-b border-border px-4 py-2.5">
                    <div className="truncate text-sm font-medium text-foreground">
                      {user?.display_name || user?.username || '用户'}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      {ROLE_LABELS[user?.role_name] || user?.role_name || ROLE_LABELS[user?.role] || user?.role || '-'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setUserMenuOpen(false)
                      setFeedbackOpen(true)
                    }}
                    className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    <MessageSquareWarning className="h-4 w-4" />
                    <span>提交反馈</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setUserMenuOpen(false)
                      navigate('/feedbacks/mine')
                    }}
                    className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    <Inbox className="h-4 w-4" />
                    <span>我的反馈</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setUserMenuOpen(false)
                      navigate('/system-settings')
                    }}
                    className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    <Settings className="h-4 w-4" />
                    <span>系统设置</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleLogout}
                    className="flex w-full items-center gap-2 border-t border-border px-4 py-2 text-left text-sm text-destructive transition-colors hover:bg-accent"
                  >
                    <LogOut className="h-4 w-4" />
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
          <PageTransition>
            <Outlet />
          </PageTransition>
        </div>
        {/* 全局快捷键监听器:无 UI,仅注册 keydown */}
        <GlobalHotkeys />
      </div>

      {/* 右下角可拖动反馈按钮：按住拖动 / 点击打开抽屉 / 位置自动持久化 */}
      <DraggableFeedbackButton onClick={() => setFeedbackOpen(true)} />

      {/* 提交反馈抽屉（用户菜单与悬浮按钮共用） */}
      <FeedbackDrawer open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />

      {/* 首次登录/重置密码后强制改密弹窗（user.must_change_password=true 时显示） */}
      {user?.must_change_password && (
        <ForceChangePassword onSuccess={() => { /* authStore 已更新，组件自动消失 */ }} />
      )}
    </div>
  )
}

export default AppShell
