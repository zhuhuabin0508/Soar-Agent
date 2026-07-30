import { Modal } from './Dialog'

// 不同变体对应的确认按钮样式
const VARIANT_BTN = {
  danger: 'btn-danger',
  warning: 'btn-primary',
  info: 'btn-primary',
}

// 不同变体对应的图标
const VARIANT_ICON = {
  danger: '⚠️',
  warning: '⚠️',
  info: 'ℹ️',
}

// 自定义确认弹窗，替代 window.confirm
function ConfirmDialog({
  open,
  title = '确认操作',
  message = '',
  confirmText = '确定',
  cancelText = '取消',
  variant = 'danger',
  onConfirm,
  onCancel,
}) {
  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button type="button" onClick={onCancel} className="btn-secondary">
            {cancelText}
          </button>
          <button type="button" onClick={onConfirm} className={VARIANT_BTN[variant] || 'btn-primary'}>
            {confirmText}
          </button>
        </>
      }
    >
      <div className="flex items-start gap-3 py-2">
        <span className="text-xl">{VARIANT_ICON[variant] || 'ℹ️'}</span>
        <p className="flex-1 text-sm text-gray-300">{message}</p>
      </div>
    </Modal>
  )
}

export default ConfirmDialog
