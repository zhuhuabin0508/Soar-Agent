import { createBrowserRouter, RouterProvider, Navigate, Outlet } from 'react-router-dom'
import AppShell from './components/AppShell'
import { GlobalLoadingProvider } from './components/GlobalLoading'
import Login from './pages/Login'
import { useAuthStore } from './store/authStore'
import WorkflowEditor from './pages/WorkflowEditor'
import WorkflowList from './pages/WorkflowList'
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
import ExecutionList from './pages/ExecutionList'
import ExecutionDetail from './pages/ExecutionDetail'
import MonitorDashboard from './pages/MonitorDashboard'
import Dashboard from './pages/Dashboard'
import ChatPage from './pages/ChatPage'
import UserManagement from './pages/UserManagement'
import RoleManagement from './pages/RoleManagement'
import SystemSettings from './pages/SystemSettings'
import SystemMonitor from './pages/SystemMonitor'
import NotificationCenter from './pages/NotificationCenter'
import BackupManagement from './pages/BackupManagement'
import BannedIPs from './pages/BannedIPs'
import Profile from './pages/Profile'
import AgentTutorial from './pages/AgentTutorial'

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
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: '/', element: <Navigate to="/dashboard" replace /> },
          { path: '/chat', element: <ChatPage /> },
          { path: '/editor', element: <WorkflowEditor /> },
          { path: '/workflows', element: <WorkflowList /> },
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
          { path: '/executions', element: <ExecutionList /> },
          { path: '/executions/:id', element: <ExecutionDetail /> },
          { path: '/monitor', element: <MonitorDashboard /> },
          { path: '/banned-ips', element: <BannedIPs /> },
          { path: '/dashboard', element: <Dashboard /> },
          // 系统配置
          { path: '/users', element: <UserManagement /> },
          { path: '/roles', element: <RoleManagement /> },
          { path: '/system-settings', element: <SystemSettings /> },
          { path: '/system-monitor', element: <SystemMonitor /> },
          { path: '/notifications', element: <NotificationCenter /> },
          { path: '/backup', element: <BackupManagement /> },
          // 个人中心
          { path: '/profile', element: <Profile /> },
          // 兜底：未匹配的受保护路由跳转运营大屏
          { path: '*', element: <Navigate to="/dashboard" replace /> },
        ],
      },
    ],
  },
])

// 应用根组件：用 RouterProvider 挂载 data router，
// 外层包 GlobalLoadingProvider 提供全局加载态。
function App() {
  return (
    <GlobalLoadingProvider>
      <RouterProvider router={router} />
    </GlobalLoadingProvider>
  )
}

export default App
