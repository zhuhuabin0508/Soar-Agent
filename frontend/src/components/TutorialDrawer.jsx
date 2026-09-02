/**
 * 通用教程抽屉组件 —— 任意页面可在 header 放一个「使用教程」按钮，
 * 点击后从右侧滑出教程面板。
 *
 * 用法：
 *   const [tutorialOpen, setTutorialOpen] = useState(false)
 *   <TutorialButton onClick={() => setTutorialOpen(true)} />
 *   <TutorialDrawer open={tutorialOpen} onClose={...} title="..." sections={[...]} />
 *
 * sections 格式：[{ icon, title, content: JSX | string, tips?: [string] }]
 */
import { useEffect } from 'react'
import {
  BookOpen, Lightbulb, X,
  Wrench, Sparkles, ClipboardList, FlaskConical, Link, Library, Upload,
  Search, Target, Settings, RefreshCw, Brain, BarChart3, Plug, FileText,
  MessageSquare, Database, Send, Shield, Tag, Code2, Zap,
} from 'lucide-react'

// emoji → lucide 图标映射：教程内容中 icon 字段存的是 emoji 字符串，
// 渲染时统一转换为 lucide 图标，保持全站图标风格一致
const EMOJI_TO_ICON = {
  '📖': BookOpen, '✨': Sparkles, '📝': FileText, '⚙️': Settings, '🧠': Brain,
  '💬': MessageSquare, '🔧': Wrench, '📚': Library, '🎯': Target, '🧩': Plug,
  '📋': ClipboardList, '🔗': Link, '🔄': RefreshCw, '📊': BarChart3, '🔌': Plug,
  '🧪': FlaskConical, '📤': Upload, '🔍': Search, '🏷️': Tag, '💾': Database,
  '⚡': Zap, '🛡️': Shield, '📨': Send, '💻': Code2,
}
function renderTutorialIcon(emoji, className = 'h-4 w-4') {
  const Icon = EMOJI_TO_ICON[emoji]
  return Icon ? <Icon className={className} /> : <span>{emoji}</span>
}

export function TutorialButton({ onClick, label = '使用教程' }) {
  return (
    <button type="button" onClick={onClick} className="btn-secondary btn-sm inline-flex items-center gap-1.5">
      <BookOpen className="h-4 w-4" />
      {label}
    </button>
  )
}

export function TutorialDrawer({ open, onClose, title, subtitle, sections = [] }) {
  // ESC 关闭
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  // 阻止滚动穿透
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
      return () => {
        document.body.style.overflow = ''
      }
    }
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[9000] flex justify-end">
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-black/50 transition-opacity"
        onClick={onClose}
      />
      {/* 抽屉面板 */}
      <div className="relative flex h-full w-full max-w-2xl flex-col bg-background shadow-2xl ring-1 ring-border">
        {/* 头部 */}
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-foreground">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-muted-foreground/70">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {/* 内容滚动区 */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="space-y-8">
            {sections.map((sec, idx) => (
              <section key={idx} className="scroll-mt-6">
                <div className="mb-3 flex items-center gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary ring-1 ring-primary/30">
                    {renderTutorialIcon(sec.icon, 'h-4 w-4')}
                  </span>
                  <h3 className="text-base font-semibold text-foreground">{sec.title}</h3>
                </div>
                <div className="space-y-2 pl-1 text-sm leading-relaxed text-muted-foreground">
                  {typeof sec.content === 'string' ? <p>{sec.content}</p> : sec.content}
                </div>
                {sec.tips && sec.tips.length > 0 && (
                  <div className="mt-3 rounded-md border border-primary/30 bg-primary/10 px-3 py-2">
                    {sec.tips.map((tip, i) => (
                      <div key={i} className="flex gap-2 py-0.5 text-xs text-primary/80">
                        <Lightbulb className="h-4 w-4 shrink-0" />
                        <span>{tip}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            ))}
          </div>
        </div>

        {/* 底部 */}
        <footer className="border-t border-border px-6 py-3">
          <button type="button" onClick={onClose} className="btn-primary btn-sm w-full">
            我已了解
          </button>
        </footer>
      </div>
    </div>
  )
}

export default TutorialDrawer
