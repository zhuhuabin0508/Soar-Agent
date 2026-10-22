import { useEffect } from 'react'

/**
 * 打开抽屉/弹层时锁住背后页面滚动（含 AppShell 的 overflow-auto）。
 * 仅允许带 data-allow-scroll 的容器（及其内部嵌套滚动容器）滚动；
 * 滚动链全部到顶/到底时也不把滚轮传给背后列表。
 * 多层叠加时用计数，避免内层关闭后提前解开外层。
 */
let lockCount = 0
let prevOverflow = ''
let wheelHandler = null
let touchHandler = null

// el 是否为可滚动容器且能沿 dy 方向继续滚动
function canScroll(el, dy) {
  if (el.scrollHeight - el.clientHeight <= 1) return false
  const oy = el.nodeType === 1 ? window.getComputedStyle(el).overflowY : ''
  if (oy !== 'auto' && oy !== 'scroll') return false
  return dy > 0 ? el.scrollTop + el.clientHeight < el.scrollHeight - 1 : el.scrollTop > 0
}

function onWheel(e) {
  const root = e.target.closest?.('[data-allow-scroll]')
  if (!root) {
    e.preventDefault()
    return
  }
  const dy = e.deltaY
  if (!dy) return
  // 从事件目标到 root 的滚动链上，找到第一个「可沿当前方向滚动」的容器：
  // 找到 → 交回浏览器原生滚动（内层到底后浏览器自然链式交给外层）；
  // 全部到顶/到底 → 拦截，防止滚轮外溢到背后页面。
  // 注意不能只看 root 的滚动位置：root（如弹窗体）到底时 preventDefault
  // 会连带取消其内部嵌套滚动容器（max-h + overflow-y-auto 列表）的原生滚动，
  // 导致滚轮失效、只能拖滚动条。
  let el = e.target
  while (el && el.nodeType === 1) {
    if (canScroll(el, dy)) return
    if (el === root) break
    el = el.parentElement
  }
  e.preventDefault()
}

function onTouchMove(e) {
  if (e.target.closest?.('[data-allow-scroll]')) return
  e.preventDefault()
}

function acquire() {
  if (lockCount === 0) {
    prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    wheelHandler = onWheel
    touchHandler = onTouchMove
    document.addEventListener('wheel', wheelHandler, { passive: false })
    document.addEventListener('touchmove', touchHandler, { passive: false })
  }
  lockCount += 1
}

function release() {
  lockCount = Math.max(0, lockCount - 1)
  if (lockCount === 0) {
    document.body.style.overflow = prevOverflow
    if (wheelHandler) document.removeEventListener('wheel', wheelHandler)
    if (touchHandler) document.removeEventListener('touchmove', touchHandler)
    wheelHandler = null
    touchHandler = null
  }
}

export default function useLockBackgroundScroll(locked) {
  useEffect(() => {
    if (!locked) return undefined
    acquire()
    return () => release()
  }, [locked])
}
