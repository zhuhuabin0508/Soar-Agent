/**
 * 轻量级 Markdown 渲染组件（无第三方依赖）。
 *
 * 支持：标题(h1-h4)、加粗(**)、斜体(*)、行内代码(``)、
 * 代码块(```)、无序列表(-/*)、有序列表(1.)、引用(>)、
 * 分割线(---)、链接、表格、段落。
 *
 * 流式安全：不完整的 Markdown 标记按普通文本显示，下个 token 到达后自然修正。
 *
 * 用法：<MarkdownRenderer content={msg.content} />
 */
import React, { useMemo } from 'react'

/**
 * 解析行内格式：加粗、斜体、行内代码、链接。
 * 返回 React 元素数组。
 */
function renderInline(text, keyPrefix = '') {
  if (!text) return []

  const elements = []
  let remaining = text
  let keyIdx = 0

  // 顺序匹配：行内代码 → 加粗 → 斜体 → 链接
  // 用占位符保护已匹配的内容，避免嵌套冲突
  const placeholders = []

  // 1. 提取行内代码 `code`
  remaining = remaining.replace(/`([^`]+)`/g, (match, code) => {
    const idx = placeholders.length
    placeholders.push(
      <code
        key={`${keyPrefix}-code-${idx}`}
        className="rounded bg-muted/80 px-1.5 py-0.5 text-[13px] font-mono text-primary"
      >
        {code}
      </code>
    )
    return `\x00${idx}\x00`
  })

  // 2. 提取加粗 **text**
  remaining = remaining.replace(/\*\*([^*]+)\*\*/g, (match, content) => {
    const idx = placeholders.length
    placeholders.push(
      <strong key={`${keyPrefix}-b-${idx}`} className="font-semibold text-foreground">
        {content}
      </strong>
    )
    return `\x00${idx}\x00`
  })

  // 3. 提取斜体 *text*（不匹配 ** 已被上面的占位符保护）
  remaining = remaining.replace(/\*([^*\n]+)\*/g, (match, content) => {
    const idx = placeholders.length
    placeholders.push(
      <em key={`${keyPrefix}-i-${idx}`} className="italic">
        {content}
      </em>
    )
    return `\x00${idx}\x00`
  })

  // 4. 提取链接 [text](url)
  remaining = remaining.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (match, linkText, url) => {
      const idx = placeholders.length
      placeholders.push(
        <a
          key={`${keyPrefix}-a-${idx}`}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline hover:text-primary"
        >
          {linkText}
        </a>
      )
      return `\x00${idx}\x00`
    }
  )

  // 5. 将剩余文本与占位符拼回元素数组
  const parts = remaining.split(/(\x00\d+\x00)/)
  for (const part of parts) {
    if (!part) continue
    const phMatch = part.match(/^\x00(\d+)\x00$/)
    if (phMatch) {
      elements.push(placeholders[parseInt(phMatch[1], 10)])
    } else {
      elements.push(part)
    }
  }

  return elements.length > 0 ? elements : [text]
}

/**
 * 解析整段 Markdown 内容，返回块级元素数组。
 */
function parseMarkdown(content) {
  if (!content) return []

  const lines = content.split('\n')
  const blocks = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // 空行跳过
    if (!trimmed) {
      i++
      continue
    }

    // 代码块 ```
    if (trimmed.startsWith('```')) {
      const lang = trimmed.slice(3).trim()
      const codeLines = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      i++ // 跳过结束的 ```
      blocks.push(
        <pre
          key={`code-${blocks.length}`}
          className="my-2 overflow-x-auto rounded-lg border border-border bg-card/80 p-3 text-[13px] leading-relaxed"
        >
          <code className="font-mono text-muted-foreground">{codeLines.join('\n')}</code>
        </pre>
      )
      continue
    }

    // 标题 # ## ### ####
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.*)/)
    if (headingMatch) {
      const level = headingMatch[1].length
      const text = headingMatch[2]
      const sizes = ['text-xl', 'text-lg', 'text-base', 'text-sm']
      const margins = ['mt-3 mb-2', 'mt-3 mb-1.5', 'mt-2 mb-1', 'mt-2 mb-1']
      blocks.push(
        React.createElement(
          `h${level}`,
          {
            key: `h-${blocks.length}`,
            className: `font-bold text-foreground ${sizes[level - 1]} ${margins[level - 1]}`,
          },
          renderInline(text, `h-${blocks.length}`)
        )
      )
      i++
      continue
    }

    // 分割线 --- ***
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push(
        <hr
          key={`hr-${blocks.length}`}
          className="my-3 border-border"
        />
      )
      i++
      continue
    }

    // 引用 >
    if (trimmed.startsWith('>')) {
      const quoteLines = []
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ''))
        i++
      }
      blocks.push(
        <blockquote
          key={`quote-${blocks.length}`}
          className="my-2 border-l-4 border-border bg-muted py-1.5 pl-3 pr-2 text-muted-foreground"
        >
          {renderInline(quoteLines.join(' '), `quote-${blocks.length}`)}
        </blockquote>
      )
      continue
    }

    // 无序列表 - * +
    if (/^[-*+]\s+/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        const itemText = lines[i].replace(/^\s*[-*+]\s+/, '')
        items.push(itemText)
        i++
      }
      blocks.push(
        <ul
          key={`ul-${blocks.length}`}
          className="my-1.5 list-disc space-y-0.5 pl-5 text-foreground"
        >
          {items.map((item, idx) => (
            <li key={`ul-item-${blocks.length}-${idx}`}>
              {renderInline(item, `ul-item-${blocks.length}-${idx}`)}
            </li>
          ))}
        </ul>
      )
      continue
    }

    // 有序列表 1. 2. etc.
    if (/^\d+\.\s+/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        const itemText = lines[i].replace(/^\s*\d+\.\s+/, '')
        items.push(itemText)
        i++
      }
      blocks.push(
        <ol
          key={`ol-${blocks.length}`}
          className="my-1.5 list-decimal space-y-0.5 pl-5 text-foreground"
        >
          {items.map((item, idx) => (
            <li key={`ol-item-${blocks.length}-${idx}`}>
              {renderInline(item, `ol-item-${blocks.length}-${idx}`)}
            </li>
          ))}
        </ol>
      )
      continue
    }

    // 表格 | col | col |
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      const tableLines = []
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        tableLines.push(lines[i].trim())
        i++
      }
      // 解析表格
      if (tableLines.length >= 2) {
        const parseRow = (row) =>
          row.split('|').slice(1, -1).map((cell) => cell.trim())
        const headers = parseRow(tableLines[0])
        // 第二行是分隔线 |---|---|
        const rows = tableLines.slice(2).map(parseRow).filter((r) => r.length > 0)
        blocks.push(
          <div key={`table-${blocks.length}`} className="my-2 overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr>
                  {headers.map((h, idx) => (
                    <th
                      key={`th-${blocks.length}-${idx}`}
                      className="border border-border bg-secondary px-3 py-1.5 text-left font-semibold text-foreground"
                    >
                      {renderInline(h, `th-${blocks.length}-${idx}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, rIdx) => (
                  <tr key={`tr-${blocks.length}-${rIdx}`}>
                    {row.map((cell, cIdx) => (
                      <td
                        key={`td-${blocks.length}-${rIdx}-${cIdx}`}
                        className="border border-border px-3 py-1.5 text-muted-foreground"
                      >
                        {renderInline(cell, `td-${blocks.length}-${rIdx}-${cIdx}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
        continue
      }
    }

    // 普通段落：收集连续非空、非特殊行
    const paraLines = []
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith('#') &&
      !lines[i].trim().startsWith('```') &&
      !lines[i].trim().startsWith('>') &&
      !/^[-*+]\s+/.test(lines[i].trim()) &&
      !/^\d+\.\s+/.test(lines[i].trim()) &&
      !/^(-{3,}|\*{3,}|_{3,})$/.test(lines[i].trim()) &&
      !(lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|'))
    ) {
      paraLines.push(lines[i])
      i++
    }
    if (paraLines.length > 0) {
      blocks.push(
        <p key={`p-${blocks.length}`} className="my-1 leading-relaxed">
          {renderInline(paraLines.join(' '), `p-${blocks.length}`)}
        </p>
      )
    }
  }

  return blocks
}

export default function MarkdownRenderer({ content, className = '' }) {
  const blocks = useMemo(() => parseMarkdown(content), [content])

  return (
    <div className={`text-sm ${className}`}>
      {blocks}
    </div>
  )
}
