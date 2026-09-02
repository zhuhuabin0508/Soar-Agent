// 主题切换按钮：light / dark / system 三态
//
// 用法（直接放进顶栏）：
//   import ThemeToggle from './ThemeToggle'
//   <ThemeToggle />
//
// 设计：
// - 单击：在 light → dark → system → light 之间循环
// - 长按 / 点击下拉箭头：展开下拉菜单，显式选三种之一
// - 图标随当前 resolvedTheme 实时变化（Sun / Moon / Monitor）
// - 与 AppShell 顶栏其他图标按钮风格一致
import { useState, useRef, useEffect } from 'react'
import { Sun, Moon, Monitor, ChevronDown } from 'lucide-react'
import { useThemeStore, setTheme } from '../store/themeStore'

export default function ThemeToggle({ className = '' }) {
  const { theme, resolved } = useThemeStore()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  // 外部点击关闭菜单
  useEffect(() => {
    if (!menuOpen) return
    const handler = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  // 当前主题对应的图标
  const CurIcon = theme === 'system' ? Monitor : (resolved === 'dark' ? Moon : Sun)

  // 单击：循环切换
  const handleClick = () => {
    const next = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light'
    setTheme(next)
  }

  const options = [
    { value: 'light', label: '亮色', icon: Sun },
    { value: 'dark', label: '暗色', icon: Moon },
    { value: 'system', label: '跟随系统', icon: Monitor },
  ]

  return (
    <div ref={menuRef} className={`relative ${className}`}>
      <div className="flex items-center">
        <button
          type="button"
          onClick={handleClick}
          title={`当前主题：${theme === 'system' ? '跟随系统' : theme === 'dark' ? '暗色' : '亮色'}`}
          aria-label="切换主题"
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <CurIcon className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          aria-label="展开主题选项"
          className="flex h-8 w-5 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <ChevronDown className="h-3 w-3" />
        </button>
      </div>
      {menuOpen && (
        <div className="absolute right-0 z-dropdown mt-1 w-36 overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-xl">
          {options.map((opt) => {
            const Icon = opt.icon
            const active = theme === opt.value
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  setTheme(opt.value)
                  setMenuOpen(false)
                }}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${
                  active ? 'text-primary' : 'text-muted-foreground'
                }`}
              >
                <Icon className="h-4 w-4" />
                <span className="flex-1">{opt.label}</span>
                {active && <span className="text-xs">✓</span>}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
