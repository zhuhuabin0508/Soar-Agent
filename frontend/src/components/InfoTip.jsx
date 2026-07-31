/**
 * InfoTip —— 圆圈感叹号 Tooltip 组件
 *
 * 将页面中的小字辅助说明替换为：一个圆圈中间感叹号的图标，
 * 鼠标 hover 时弹出 tooltip 显示说明文字，保持页面整洁。
 *
 * 用法：
 *   <InfoTip text="这是说明文字" />
 *   <InfoTip text="顶部弹出" placement="top" />
 *   <InfoTip text={<>支持 <code>JSX</code> 内容</>} />
 */
import { useState } from 'react'

const PLACEMENT_CLS = {
  top: 'bottom-full left-1/2 mb-2 -translate-x-1/2',
  bottom: 'top-full left-1/2 mt-2 -translate-x-1/2',
  left: 'right-full top-1/2 mr-2 -translate-y-1/2',
  right: 'left-full top-1/2 ml-2 -translate-y-1/2',
}

const ARROW_CLS = {
  top: 'top-full left-1/2 -translate-x-1/2 border-t-gray-700',
  bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-gray-700',
  left: 'left-full top-1/2 -translate-y-1/2 border-l-gray-700',
  right: 'right-full top-1/2 -translate-y-1/2 border-r-gray-700',
}

function InfoTip({ text, placement = 'top', className = '' }) {
  const [show, setShow] = useState(false)

  // 空内容时不渲染，避免无用图标
  if (!text) return null

  return (
    <span
      className={`relative inline-flex shrink-0 items-center ${className}`}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      {/* 圆圈感叹号图标 */}
      <span
        className="flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-gray-600 text-[9px] font-bold text-gray-500 transition-colors hover:border-brand-500 hover:text-brand-400"
        tabIndex={0}
        role="img"
        aria-label="提示"
      >
        !
      </span>

      {/* Tooltip 气泡 */}
      {show && (
        <span
          className={`pointer-events-none absolute z-50 w-max max-w-xs whitespace-normal rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-xs leading-relaxed text-gray-300 shadow-xl ${PLACEMENT_CLS[placement] || PLACEMENT_CLS.top}`}
        >
          {text}
          {/* 小箭头 */}
          <span
            className={`absolute h-0 w-0 border-4 border-transparent ${ARROW_CLS[placement] || ARROW_CLS.top}`}
          />
        </span>
      )}
    </span>
  )
}

export default InfoTip
