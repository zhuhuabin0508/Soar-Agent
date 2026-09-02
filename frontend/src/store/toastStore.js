// 全局 Toast 通知系统
// 统一替代各页面的 window.alert，提供 success / error / warning / info 四种语义。
//
// 用法：
//   import { toast } from '../store/toastStore'
//   toast.success('保存成功')
//   toast.error('删除失败：' + err.message)
//   toast.warning('该操作不可撤销')
//   toast.info('已刷新列表')
//
// 设计要点：
// - 基于 zustand，全局单例，任意组件 / 非组件均可调用
// - 自动消失（默认 success/info 3s，warning 4s，error 5s）
// - 支持手动关闭（点击关闭按钮）
// - 最多同时显示 5 条，超出自动移除最早的
import { create } from 'zustand'

let _id = 0

const VARIANT_CONFIG = {
  success: { duration: 3000, icon: 'success' },
  error: { duration: 5000, icon: 'error' },
  warning: { duration: 4000, icon: 'warning' },
  info: { duration: 3000, icon: 'info' },
}

function _push(variant, message, options = {}) {
  const cfg = VARIANT_CONFIG[variant] || VARIANT_CONFIG.info
  const id = ++_id
  const item = {
    id,
    variant,
    message,
    title: options.title || '',
    duration: options.duration != null ? options.duration : cfg.duration,
    // 可点击跳转：点击弹窗主体或操作按钮触发
    onClick: typeof options.onClick === 'function' ? options.onClick : null,
    actionLabel: options.actionLabel || '',
  }
  // 自动消失定时器
  if (item.duration > 0) {
    setTimeout(() => {
      useToastStore.getState().dismiss(id)
    }, item.duration)
  }
  // 入队，超出上限移除最早的
  useToastStore.setState((s) => {
    const next = [...s.items, item]
    if (next.length > 5) next.splice(0, next.length - 5)
    return { items: next }
  })
  return id
}

export const useToastStore = create((set) => ({
  items: [],
  dismiss: (id) =>
    set((s) => ({
      items: s.items.map((it) =>
        it.id === id ? { ...it, leaving: true } : it
      ),
    })),
  // 真正移除（动画结束后调用）
  remove: (id) =>
    set((s) => ({ items: s.items.filter((it) => it.id !== id) })),
  clear: () => set({ items: [] }),
}))

// 便捷 API：任意位置可调用
export const toast = {
  success: (msg, opts) => _push('success', msg, opts),
  error: (msg, opts) => _push('error', msg, opts),
  warning: (msg, opts) => _push('warning', msg, opts),
  info: (msg, opts) => _push('info', msg, opts),
  // 兜底：根据布尔值自动选 success / error
  result: (ok, successMsg, errorMsg) =>
    ok ? _push('success', successMsg) : _push('error', errorMsg),
}

export default toast
