// 通知中心 API：通知列表/未读计数/标记已读/全部已读/删除/创建（管理员公告）
import request from './client'

export const notificationsApi = {
  // 获取通知列表（分页）
  list: (limit = 50, offset = 0) => request(`/notifications?limit=${limit}&offset=${offset}`),
  // 获取未读计数
  unreadCount: () => request('/notifications/unread-count'),
  // 标记单条已读
  markRead: (id) => request(`/notifications/${id}/read`, { method: 'PUT' }),
  // 全部标记已读
  markAllRead: () => request('/notifications/read-all', { method: 'PUT' }),
  // 删除通知
  remove: (id) => request(`/notifications/${id}`, { method: 'DELETE' }),
  // 创建通知（管理员公告）
  create: (body) => request('/notifications', { method: 'POST', body }),
}

export default notificationsApi
