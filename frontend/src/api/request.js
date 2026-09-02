// 统一请求封装：复用 client.js 的 request 函数（含 token 注入与 401 统一处理）
// 避免重复实现导致 token 遗漏或 401 处理不一致

export { request, default } from './client'
