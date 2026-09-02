// 角色管理 API：列表/新建/更新/删除 + 权限模块元数据
import request from './client'

export const rolesApi = {
  // 角色列表
  list: () => request('/roles'),
  // 获取权限模块定义（PERMISSION_MODULES + labels）
  modules: () => request('/roles/modules'),
  // 新建角色
  create: (body) => request('/roles', { method: 'POST', body }),
  // 更新角色
  update: (id, body) => request(`/roles/${id}`, { method: 'PUT', body }),
  // 删除角色
  remove: (id) => request(`/roles/${id}`, { method: 'DELETE' }),
}

export default rolesApi
