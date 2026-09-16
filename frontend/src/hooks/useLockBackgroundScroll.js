import { useEffect } from 'react'

/**
 * 打开抽屉/弹层时锁住背后页面滚动（含 AppShell 的 overflow-auto）。
 * 仅允许带 data-allow-scroll 的容器滚动；滚到顶/底时也不把滚轮传给列表。
 * 多层叠加时用计数，避免内层关闭后提前解开外层。
 */
let lockCount = 0
let prevOverflow = ''
let wheelHandler = null
let touchHandler = null

function onWheel(e) {
  const scroller = e.target.closest?.('[data-allow-scroll]')
  if (scroller) {
    const dy = e.deltaY
    if (!dy) return
    const top = scroller.scrollTop
    const max = scroller.scrollHeight - scroller.clientHeight
    const atTop = top <= 0 && dy < 0
    const atBottom = top >= max - 1 && dy > 0
    if (atTop || atBottom) e.preventDefault()
    return
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
