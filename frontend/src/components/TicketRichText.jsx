// 工单富文本组件：所见即所得图片粘贴 + 双击放大预览 + 附件后缀校验
// - RichEditable：contentEditable 富文本输入框，粘贴截图后在框内直接以图片呈现（所见即所得），
//   数据层仍为纯文本 + `![名称](url)` 图片引用（与展示端 RichTextView / 存量数据完全兼容）；
//   框内图片双击弹出 Lightbox 放大预览
// - RichTextView：只读展示，图片引用渲染为缩略图，双击放大预览
// - attachmentFileError / ATTACHMENT_EXTS / ATTACHMENT_ACCEPT：附件后缀白名单（与后端一致）
// 注意：本文件避免出现方括号正则字面量（如带连字符的字符类），Tailwind 会误扫为任意值类名生成非法 CSS
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { toast } from '../store/toastStore'
import ticketApi, { attachmentUrl } from '../api/tickets'

// 附件允许的后缀（有序，与后端白名单一致；拒绝一切可执行文件）
export const ATTACHMENT_EXTS = [
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp',
  'pdf', 'txt', 'log', 'md', 'csv', 'zip',
]
// 文件选择框 accept 属性
export const ATTACHMENT_ACCEPT = ATTACHMENT_EXTS.map((e) => `.${e}`).join(',')

// 上传前的后缀校验：返回错误消息（null 表示通过）
export function attachmentFileError(file) {
  if (!file) return '未选择文件'
  const ext = String(file.name || '').split('.').pop().toLowerCase()
  if (!ATTACHMENT_EXTS.includes(ext)) {
    return `不支持的文件类型「${file.name}」，仅支持：${ATTACHMENT_EXTS.join(' / ')}`
  }
  return null
}

// 图片 markdown：![label](url)
const IMG_MD_RE = /!\[([^\]]*)\]\(([^)\s]+)\)/g
// 本系统附件路径前缀（mdToHtml 仅放行该前缀，防外链注入）
const ATTACH_URL_PREFIX = '/api/v1/tickets/attachments/'

// HTML 转义（任何文本进入编辑器 DOM 前必须转义，防 XSS）
function escapeHtml(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

// 编辑态内嵌图片类名（Tailwind 扫描源码字符串生成对应 CSS）
const EDIT_IMG_CLS = 'inline-block max-h-24 max-w-full cursor-zoom-in rounded-md border border-border align-middle'

// markdown → 安全 HTML：文本段转义 + 换行转 <br>；图片引用仅放行本系统附件路径
function mdToHtml(v) {
  const s = String(v ?? '')
  let html = ''
  let last = 0
  const pushText = (t) => { html += escapeHtml(t).split('\n').join('<br>') }
  for (const m of s.matchAll(IMG_MD_RE)) {
    if (m.index > last) pushText(s.slice(last, m.index))
    if (m[2].startsWith(ATTACH_URL_PREFIX)) {
      html += `<img src="${escapeHtml(m[2])}" alt="${escapeHtml(m[1] || '图片')}" class="${EDIT_IMG_CLS}">`
    } else {
      pushText(m[0])
    }
    last = m.index + m[0].length
  }
  if (last < s.length) pushText(s.slice(last))
  return html
}

// DOM 节点 → markdown：文本原样、<br>→换行、<img>→图片引用（仅本系统附件）、其余标签剥格式取文本
function nodeToMd(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue
  const tag = node.nodeName
  if (tag === 'BR') return '\n'
  if (tag === 'IMG') {
    const src = node.getAttribute('src') || ''
    if (!src.startsWith(ATTACH_URL_PREFIX)) return ''
    return `![${node.getAttribute('alt') || '图片'}](${src})`
  }
  let out = ''
  node.childNodes.forEach((c) => { out += nodeToMd(c) })
  if (tag === 'DIV' || tag === 'P') out += '\n'
  return out
}

function htmlToMd(rootEl) {
  let out = ''
  rootEl.childNodes.forEach((c) => { out += nodeToMd(c) })
  return out
}

// 图片放大预览（Portal 挂 body，点击空白 / 双击图片 / Esc 关闭）
function Lightbox({ src, name, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div className="fixed inset-0 z-[200] flex select-none flex-col items-center justify-center gap-3 bg-black/85 p-8"
      onClick={onClose}>
      <div className="max-w-[85vw] truncate text-sm text-white/85">{name || '图片'}</div>
      <img src={src} alt={name || '图片'} className="max-h-[78vh] max-w-[90vw] cursor-zoom-out rounded-md border border-white/20 object-contain"
        onClick={(e) => e.stopPropagation()} onDoubleClick={onClose} />
      <div className="text-xs text-white/50">双击图片或点击空白处关闭（Esc 同样生效）</div>
    </div>,
    document.body,
  )
}

// 只读富文本展示：文本段落保留换行，图片渲染为缩略图，双击放大预览
export function RichTextView({ text }) {
  const [lightbox, setLightbox] = useState(null)
  const s = String(text ?? '')
  const matches = [...s.matchAll(IMG_MD_RE)]
  if (!matches.length) return <span className="break-all">{s}</span>
  const parts = []
  let last = 0
  matches.forEach((m, i) => {
    if (m.index > last) parts.push(<span key={`t${i}`} className="whitespace-pre-wrap break-all">{s.slice(last, m.index)}</span>)
    parts.push(
      <img key={`i${i}`} src={attachmentUrl(m[2])} alt={m[1] || '图片'} loading="lazy" title="双击查看大图"
        className="my-1 block max-h-60 w-fit max-w-full cursor-zoom-in rounded-md border border-border"
        onDoubleClick={() => setLightbox({ src: attachmentUrl(m[2]), name: m[1] || '图片' })} />,
    )
    last = m.index + m[0].length
  })
  if (last < s.length) parts.push(<span key="tail" className="whitespace-pre-wrap break-all">{s.slice(last)}</span>)
  return (
    <div className="space-y-1">
      {parts}
      {lightbox && <Lightbox src={lightbox.src} name={lightbox.name} onClose={() => setLightbox(null)} />}
    </div>
  )
}

// 所见即所得富文本输入框（工单 textarea 类型字段 / 处理意见 / 发起备注）
// value 为 markdown 格式纯文本；粘贴截图自动上传并在光标处插入图片本体（非 URL 文本）
export function RichEditable({ value, onChange, placeholder, className, minHeight = 64 }) {
  const ref = useRef(null)
  const lastExported = useRef(undefined)
  const [lightbox, setLightbox] = useState(null)
  const [pasting, setPasting] = useState(false)

  // 挂载：按初始值渲染内容（调用方 key 已含节点/流程前缀，切换时重挂载保证同步）
  useEffect(() => {
    lastExported.current = value ?? ''
    if (ref.current) ref.current.innerHTML = mdToHtml(value ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 外部值变化时同步 DOM：聚焦编辑中不重写（避免光标跳动），清空场景强制同步
  useEffect(() => {
    if (value === lastExported.current) return
    if (document.activeElement === ref.current && value !== '') return
    lastExported.current = value ?? ''
    if (ref.current) ref.current.innerHTML = mdToHtml(value ?? '')
  }, [value])

  const exportMd = () => {
    const md = ref.current ? htmlToMd(ref.current) : ''
    // 内容清空时移除残留空标签，恢复 placeholder
    if (!md && ref.current && !ref.current.querySelector('img') && !ref.current.innerText.trim()) {
      ref.current.innerHTML = ''
    }
    lastExported.current = md
    onChange(md)
  }

  const handlePaste = async (e) => {
    const items = e.clipboardData?.items
    if (!items || pasting) return
    // 剪贴板同时含文本时不拦截（如从 Excel/网页复制），仅拦截纯截图/图片粘贴
    let hasText = false
    let imgItem = null
    for (const it of items) {
      if (it.kind === 'string' && it.type === 'text/plain') hasText = true
      if (it.kind === 'file' && it.type.startsWith('image/')) imgItem = imgItem || it
    }
    if (hasText || !imgItem) return
    const imgFile = imgItem.getAsFile()
    if (!imgFile) return
    e.preventDefault()
    setPasting(true)
    try {
      const ext = (imgFile.type.split('/')[1] || '').toLowerCase().replaceAll('jpeg', 'jpg')
      if (!ATTACHMENT_EXTS.includes(ext)) {
        toast.error(`不支持的图片类型（${imgFile.type}），请另存为 ${ATTACHMENT_EXTS.slice(0, 6).join(' / ')} 后粘贴`)
        return
      }
      const stamp = new Date().toISOString().slice(0, 19).split('-').join('').split(':').join('').split('T').join('')
      const file = new File([imgFile], `截图-${stamp}.${ext}`, { type: imgFile.type })
      const res = await ticketApi.uploadAttachment(file)
      // 在光标处插入图片本体（所见即所得），数据层由 exportMd 导出为 markdown 引用
      document.execCommand('insertHTML', false,
        `<img src="${escapeHtml(res.url)}" alt="${escapeHtml(res.name || '截图')}" class="${EDIT_IMG_CLS}">`)
      exportMd()
      toast.success('截图已插入')
    } catch (err) {
      toast.error(err.message || '图片上传失败')
    } finally {
      setPasting(false)
    }
  }

  const handleDblClick = (e) => {
    const t = e.target
    if (t?.tagName === 'IMG') {
      e.preventDefault()
      setLightbox({ src: attachmentUrl(t.getAttribute('src') || ''), name: t.getAttribute('alt') || '图片' })
    }
  }

  return (
    <>
      <style>{'.rich-editable:empty::before{content:attr(data-placeholder);color:var(--muted-foreground);pointer-events:none;}'}</style>
      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-multiline="true"
        tabIndex={0}
        data-placeholder={placeholder || ''}
        onInput={exportMd}
        onPaste={handlePaste}
        onDoubleClick={handleDblClick}
        className={`rich-editable cursor-text overflow-y-auto whitespace-pre-wrap break-words ${className || ''}`}
        style={{ minHeight }}
      />
      {lightbox && <Lightbox src={lightbox.src} name={lightbox.name} onClose={() => setLightbox(null)} />}
    </>
  )
}
