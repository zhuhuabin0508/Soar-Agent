// 反馈模块共享常量与工具：类型/状态/优先级的中文映射 + 标签样式 + 附件辅助
// 供 FeedbackDrawer / MyFeedback / FeedbackAdmin 复用，保持展示一致

// ===== 类型 =====
export const FEEDBACK_TYPES = [
  { value: 'bug', label: 'BUG' },
  { value: 'suggestion', label: '优化建议' },
  { value: 'other', label: '其他' },
]

export function typeMeta(type) {
  switch (type) {
    case 'bug':
      return { label: 'BUG', cls: 'bg-red-500/15 text-red-400' }
    case 'suggestion':
      return { label: '优化建议', cls: 'bg-blue-500/15 text-blue-400' }
    default:
      return { label: '其他', cls: 'bg-muted text-muted-foreground' }
  }
}

// ===== 状态 =====
export const FEEDBACK_STATUSES = [
  { value: 'pending', label: '待处理' },
  { value: 'processing', label: '处理中' },
  { value: 'replied', label: '已回复' },
  { value: 'resolved', label: '已解决' },
  { value: 'closed', label: '已关闭' },
]

export function statusMeta(status) {
  switch (status) {
    case 'pending':
      return { label: '待处理', cls: 'bg-amber-500/15 text-amber-400' }
    case 'processing':
      return { label: '处理中', cls: 'bg-primary/15 text-primary' }
    case 'replied':
      return { label: '已回复', cls: 'bg-purple-500/15 text-purple-400' }
    case 'resolved':
      return { label: '已解决', cls: 'bg-emerald-500/15 text-emerald-400' }
    case 'closed':
      return { label: '已关闭', cls: 'bg-muted text-muted-foreground' }
    default:
      return { label: status || '-', cls: 'bg-muted text-muted-foreground' }
  }
}

// ===== 优先级 =====
export const FEEDBACK_PRIORITIES = [
  { value: 'urgent', label: '紧急' },
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
]

export function priorityMeta(priority) {
  switch (priority) {
    case 'urgent':
      return { label: '紧急', cls: 'bg-red-500/15 text-red-400' }
    case 'high':
      return { label: '高', cls: 'bg-orange-500/15 text-orange-400' }
    case 'medium':
      return { label: '中', cls: 'bg-amber-500/15 text-amber-400' }
    case 'low':
      return { label: '低', cls: 'bg-muted text-muted-foreground' }
    default:
      return { label: priority || '-', cls: 'bg-muted text-muted-foreground' }
  }
}

// ===== 处理历史动作中文映射 =====
export function actionLabel(action) {
  const map = {
    create: '创建',
    created: '创建',
    reply: '回复',
    status_change: '状态变更',
    status_changed: '状态变更',
    reopen: '重新打开',
    assign: '分配',
    assigned: '分配',
    batch: '批量操作',
    edit: '编辑',
    edited: '编辑',
    update: '编辑',
    updated: '编辑',
  }
  return map[(action || '').toLowerCase()] || action || '-'
}

// ===== 时间格式化（与现有列表页一致） =====
export function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// ===== 附件辅助 =====
// 附件扩展名白名单（与后端一致）
export const ATTACH_EXT_WHITELIST = [
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp',
  'pdf', 'txt', 'log', 'md', 'csv', 'zip',
]

export function fileExt(name) {
  const i = String(name || '').lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

// 是否图片附件（用于缩略图展示）
export function isImageAttachment(name) {
  return ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(fileExt(name))
}

// 文件大小格式化
export function fmtSize(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n < 0) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
