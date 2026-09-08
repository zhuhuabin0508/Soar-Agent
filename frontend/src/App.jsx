import { createBrowserRouter, RouterProvider, Navigate, Outlet } from 'react-router-dom'
import AppShell from './components/AppShell'
import { GlobalLoadingProvider } from './components/GlobalLoading'
import ToastContainer from './components/ToastContainer'
import { ConfirmDialogHost } from './components/ConfirmDialog'
import { ErrorBoundary, RouteErrorFallback } from './components/ErrorBoundary'
import { useHotkeys } from './hooks/useHotkeys'
import Login from './pages/Login'
import { useAuthStore } from './store/authStore'
import WorkflowEditor from './pages/WorkflowEditor'
import WorkflowList from './pages/WorkflowList'
import WorkflowMonitor from './pages/WorkflowMonitor'
import AgentList from './pages/AgentList'
import AgentEditor from './pages/AgentEditor'
import ToolList from './pages/ToolList'
import ToolEditor from './pages/ToolEditor'
import KnowledgeBase from './pages/KnowledgeBase'
import SkillList from './pages/SkillList'
import LLMConfig from './pages/LLMConfig'
import DeviceManagement from './pages/DeviceManagement'
import AgentMonitor from './pages/AgentMonitor'
import ApprovalCenter from './pages/ApprovalCenter'
import ExecutionDetail from './pages/ExecutionDetail'
import LogCenter from './pages/LogCenter'
import Dashboard from './pages/Dashboard'
import ChatPage from './pages/ChatPage'
import UserManagement from './pages/UserManagement'
import RoleManagement from './pages/RoleManagement'
import SystemSettings from './pages/SystemSettings'
import SystemMonitor from './pages/SystemMonitor'
import NotificationCenter from './pages/NotificationCenter'
import BackupManagement from './pages/BackupManagement'
import Assets from './pages/Assets'
import AssetOverview from './pages/AssetOverview'
import AssetList from './pages/AssetList'
import AssetTemplates from './pages/AssetTemplates'
import Profile from './pages/Profile'
import AgentTutorial from './pages/AgentTutorial'
import About from './pages/About'
import MyFeedback from './pages/MyFeedback'
import FeedbackAdmin from './pages/FeedbackAdmin'
import DeliverableManagement from './pages/DeliverableManagement'
import DutyMemberManagement from './pages/DutyMemberManagement'
import DutySchedule from './pages/DutySchedule'
import DutyLeave from './pages/DutyLeave'
import DutyAdjustmentLogs from './pages/DutyAdjustmentLogs'
import StrategyList from './pages/StrategyList'
import StrategyEdit from './pages/StrategyEdit'
import AlertList from './pages/AlertList'
import IngestionMonitor from './pages/IngestionMonitor'
import BanTriggerRules from './pages/ban/BanTriggerRules'

// 路由守卫：未登录跳转 /login
// 作为布局路由使用：通过则渲染 <Outlet />（子路由），否则跳转登录页。
function ProtectedRoute() {
  const token = useAuthStore((s) => s.token)
  if (!token) {
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}

// 使用 createBrowserRouter 创建 data router。
// ⚠️ useBlocker / useFetcher 等 hook 必须在 data router 上下文中使用，
// 旧的 <BrowserRouter> 不提供 data router 上下文，会导致编辑页面的
// useUnsavedChanges（内部用 useBlocker）报错：
//   "useBlocker must be used within a data router"
// 改用 createBrowserRouter + RouterProvider 后，所有 data router hook 均可用。
const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
    errorElement: <RouteErrorFallback />,
  },
  {
    element: <ProtectedRoute />,
    errorElement: <RouteErrorFallback />,
    children: [
      {
        element: <AppShell />,
        errorElement: <RouteErrorFallback />,
        children: [
          { path: '/', element: <Navigate to="/dashboard" replace /> },
          { path: '/chat', element: <ChatPage /> },
          { path: '/editor', element: <WorkflowEditor /> },
          { path: '/workflows', element: <WorkflowList /> },
          { path: '/workflows/:id/monitor', element: <WorkflowMonitor /> },
          { path: '/agents', element: <AgentList /> },
          { path: '/agents/new', element: <AgentEditor /> },
          { path: '/agents/:id/edit', element: <AgentEditor /> },
          { path: '/agents/:id/monitor', element: <AgentMonitor /> },
          { path: '/agent-tutorial', element: <AgentTutorial /> },
          { path: '/tools', element: <ToolList /> },
          { path: '/tools/new', element: <ToolEditor /> },
          { path: '/tools/:id/edit', element: <ToolEditor /> },
          { path: '/knowledge-base', element: <KnowledgeBase /> },
          { path: '/skills', element: <SkillList /> },
          { path: '/llm-configs', element: <LLMConfig /> },
          { path: '/devices', element: <DeviceManagement /> },
          { path: '/approvals', element: <ApprovalCenter /> },
          { path: '/executions', element: <LogCenter /> },
          { path: '/executions/:id', element: <ExecutionDetail /> },
          { path: '/logs', element: <LogCenter /> },
          { path: '/banned-ips', element: <Navigate to="/dashboard" replace /> },
          { path: '/assets', element: <AssetOverview /> },
          { path: '/assets/list', element: <AssetList /> },
          { path: '/assets/templates', element: <AssetTemplates /> },
          { path: '/assets/legacy', element: <Assets /> },
          { path: '/dashboard', element: <Dashboard /> },
          // 系统配置
          { path: '/users', element: <UserManagement /> },
          { path: '/roles', element: <RoleManagement /> },
          { path: '/system-settings', element: <SystemSettings /> },
          { path: '/system-monitor', element: <SystemMonitor /> },
          { path: '/notifications', element: <NotificationCenter /> },
          { path: '/backup', element: <BackupManagement /> },
          { path: '/about', element: <About /> },
          // 个人中心
          { path: '/profile', element: <Profile /> },
          // 系统反馈
          { path: '/feedbacks/mine', element: <MyFeedback /> },
          { path: '/feedbacks/admin', element: <FeedbackAdmin /> },
          { path: '/deliverables', element: <DeliverableManagement /> },
          // 运营管理 - 值班
          { path: '/duty/members', element: <DutyMemberManagement /> },
          { path: '/duty/schedule', element: <DutySchedule /> },
          { path: '/duty/leaves', element: <DutyLeave /> },
          { path: '/duty/logs', element: <DutyAdjustmentLogs /> },
          // 连接配置 - 设备对接（设备列表 / 解析策略 / 告警列表 / 入库监控）
          { path: '/strategies', element: <StrategyList /> },
          { path: '/strategies/new', element: <StrategyEdit /> },
          { path: '/strategies/:id/edit', element: <StrategyEdit /> },
          // 告警接入 - 告警列表与解析入库监控
          { path: '/alerts', element: <AlertList /> },
          { path: '/ingest-monitor', element: <IngestionMonitor /> },
          // 告警自动封禁工作流：触发规则独立页面；审批/封禁/历史已合并进工作台 Tab
          { path: '/ban-workflow/instances', element: <Navigate to="/approvals?tab=all" replace /> },
          { path: '/ban-workflow/approvals', element: <Navigate to="/approvals" replace /> },
          { path: '/ban-workflow/banned', element: <Navigate to="/approvals?tab=banned" replace /> },
          { path: '/ban-workflow/rules', element: <BanTriggerRules /> },
          // 兜底：未匹配的受保护路由跳转运营大屏
          { path: '*', element: <Navigate to="/dashboard" replace /> },
        ],
      },
    ],
  },
])

// 应用根组件：用 RouterProvider 挂载 data router，
// 外层包 GlobalLoadingProvider 提供全局加载态。
// ToastContainer / ConfirmDialogHost 为全局反馈层，挂载在路由外层。
// ErrorBoundary 包裹整个应用，捕获路由 errorElement 处理不到的同步异常。
function App() {
  return (
    <ErrorBoundary>
      <GlobalLoadingProvider>
        <RouterProvider router={router} />
        <ToastContainer />
        <ConfirmDialogHost />
      </GlobalLoadingProvider>
    </ErrorBoundary>
  )
}

// 顶层快捷键监听器:全局挂在 RouterProvider 外不可,需在 Router 内才能用 useNavigate
// 故单独组件,由路由树内的根路由(AppShell/ProtectedRoute)渲染
export function GlobalHotkeys() {
  useHotkeys()
  return null
}

export default App
