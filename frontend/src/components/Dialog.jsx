import { useState, useEffect } from 'react'
import { inputCls } from './property/FormControls'

// 通用模态弹窗容器：覆盖整屏，居中显示，深色主题
export function Modal({ open, title, onClose, children, footer, maxWidth = 'max-w-2xl' }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center bg-black/60 p-4">
      <div className={`relative z-modal flex max-h-[90vh] w-full ${maxWidth} flex-col rounded-lg border border-gray-700 bg-gray-900 shadow-2xl`}>
        <div className="flex shrink-0 items-center justify-between border-b border-gray-800 px-4 py-3">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 flex flex-col gap-2">{children}</div>
        {footer && (
          <div className="flex shrink-0 justify-end gap-2 border-t border-gray-800 px-4 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}

// 右侧抽屉 Drawer：从右侧滑入，全屏高度，内容区可滚动
// 适用于内容较多、需要长期编辑的场景（如权限矩阵、复杂表单）
// width: 抽屉宽度 class，如 'w-[480px]' / 'w-[640px]' / 'max-w-2xl w-full'
export function Drawer({ open, title, onClose, children, footer, width = 'w-[560px]' }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-drawer flex justify-end bg-black/60">
      <div
        className={`relative z-drawer flex h-full ${width} max-w-[95vw] flex-col border-l border-gray-700 bg-gray-900 shadow-2xl`}
        role="dialog"
        aria-modal="true"
      >
        {/* 顶部标题栏（sticky） */}
        <div className="flex shrink-0 items-center justify-between border-b border-gray-800 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-gray-400 transition hover:bg-gray-800 hover:text-white"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>
        {/* 内容区：可滚动 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {/* 底部操作栏（sticky） */}
        {footer && (
          <div className="flex shrink-0 justify-end gap-2 border-t border-gray-800 bg-gray-900/80 px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}

// 简易 JSON 输入弹窗：用于「试运行」时让用户填入示例输入
export function JsonInputDialog({
  open,
  title,
  defaultValue,
  onClose,
  onSubmit,
  submitText = '运行',
}) {
  const [text, setText] = useState(
    defaultValue ||
      '{\n  "alert_data": {\n    "src_ip": "192.168.1.100",\n    "alert_type": "brute_force"\n  }\n}'
  )
  const [parseErr, setParseErr] = useState('')

  // 弹窗每次打开时重置为最新 defaultValue
  useEffect(() => {
    if (open && defaultValue !== undefined) {
      setText(defaultValue)
      setParseErr('')
    }
  }, [open, defaultValue])

  if (!open) return null

  const handleSubmit = () => {
    let parsed
    try {
      parsed = text.trim() ? JSON.parse(text) : {}
      setParseErr('')
    } catch (err) {
      setParseErr(`JSON 解析失败：${err.message}`)
      return
    }
    onSubmit(parsed)
  }

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary btn-sm"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            className="btn-primary btn-sm"
          >
            {submitText}
          </button>
        </>
      }
    >
      <textarea
        className={`${inputCls} resize-y font-mono`}
        rows={12}
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
      />
      {parseErr && <p className="text-xs text-danger-400">{parseErr}</p>}
    </Modal>
  )
}

export default Modal
