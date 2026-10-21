// 绝对时间格式化（公共工具）：YYYY-MM-DD HH:mm:ss
// 配合相对时间（「3 分钟前」等）使用：悬停 title 显示完整绝对时间
export function fmtAbs(t) {
  if (t == null || t === '') return '-'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return '-'
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
