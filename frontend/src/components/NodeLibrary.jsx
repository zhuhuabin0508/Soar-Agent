import { useEffect, useMemo, useState } from 'react'
import { nodeCatalog } from '../constants/nodeCatalog'
import { tools as toolsApi } from '../api/client'

// 工具节点卡片的固定展示色（与 nodeCatalog 中 tool 节点一致）
const TOOL_COLOR = '#14b8a6'

// 左侧节点库面板：顶部搜索框 + 静态节点 + 动态工具节点
function NodeLibrary() {
  // 静态节点拖拽：dataTransfer 仅设节点 type
  const onDragStart = (e, type) => {
    e.dataTransfer.setData('application/reactflow', type)
    e.dataTransfer.effectAllowed = 'move'
  }

  // 工具节点拖拽：额外携带工具名，供 FlowCanvas 注入到节点 data
  const onToolDragStart = (e, toolName) => {
    e.dataTransfer.setData('application/reactflow', 'tool')
    e.dataTransfer.setData('application/reactflow-tool-name', toolName)
    e.dataTransfer.effectAllowed = 'move'
  }

  // 动态拉取后端工具列表
  const [toolList, setToolList] = useState([])
  const [loadingTools, setLoadingTools] = useState(true)
  const [toolErr, setToolErr] = useState('')

  // 搜索关键词（同时过滤静态节点与工具节点）
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const data = await toolsApi.list()
        if (!alive) return
        setToolList(Array.isArray(data) ? data : [])
        setToolErr('')
      } catch (err) {
        setToolErr(err.message || '加载工具失败')
        setToolList([])
      } finally {
        if (alive) setLoadingTools(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  // 按关键词过滤静态节点（匹配 label / type / description）
  const filteredNodes = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return nodeCatalog
    return nodeCatalog.filter(
      (n) =>
        n.label.toLowerCase().includes(kw) ||
        n.type.toLowerCase().includes(kw) ||
        (n.description || '').toLowerCase().includes(kw)
    )
  }, [keyword])

  // 按关键词过滤工具节点（匹配 name / description）
  const filteredTools = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return toolList
    return toolList.filter(
      (t) =>
        (t.name || '').toLowerCase().includes(kw) ||
        (t.description || '').toLowerCase().includes(kw)
    )
  }, [keyword, toolList])

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-300">
          节点库
        </h2>
        <span className="text-[11px] text-gray-500">拖拽到画布</span>
      </div>

      {/* 搜索框：过滤节点与工具 */}
      <input
        className="w-full rounded-md border border-gray-700 bg-gray-800 px-2.5 py-1.5 text-sm text-white outline-none transition placeholder:text-gray-500 focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        placeholder="搜索节点 / 工具…"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />

      {/* 静态内置节点 */}
      <div className="flex flex-col gap-2">
        {filteredNodes.length === 0 && keyword.trim() && (
          <p className="px-1 text-[11px] text-gray-600">无匹配的节点</p>
        )}
        {filteredNodes.map((n) => (
          <div
            key={n.type}
            draggable
            onDragStart={(e) => onDragStart(e, n.type)}
            title={n.description}
            className="group w-full cursor-grab rounded-lg border border-gray-700 bg-gray-800 p-3 transition hover:border-brand-500 hover:bg-gray-700 active:cursor-grabbing"
          >
            <div className="flex items-center gap-2.5">
              {/* 图标徽章 */}
              <div
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-lg"
                style={{ background: `${n.color}22`, color: n.color }}
              >
                <span>{n.icon}</span>
              </div>
              {/* 名称 + 描述：填满剩余横向空间 */}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-white">
                  {n.label}
                </div>
                <div className="truncate text-xs text-gray-400">
                  {n.description}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 工具节点分区：动态拉取已注册工具 */}
      {!keyword.trim() || filteredTools.length > 0 ? (
        <div className="mt-2 border-t border-gray-800 pt-3">
          <div className="mb-1 flex items-center justify-between px-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-300">
              工具节点
            </h3>
            <span className="text-[11px] text-gray-500">
              {filteredTools.length > 0
                ? `${filteredTools.length} 个`
                : ''}
            </span>
          </div>
          {!keyword.trim() && (
            <p className="mb-2 px-1 text-[11px] leading-relaxed text-gray-500">
              来自后端已注册工具，拖拽到画布将自动绑定 tool_name。
            </p>
          )}

          {loadingTools ? (
            <div className="rounded-md border border-gray-800 bg-gray-800/40 p-3 text-center text-[11px] text-gray-500">
              加载中…
            </div>
          ) : toolErr ? (
            <div className="rounded-md border border-danger-700/40 bg-danger-900/20 p-3 text-center text-[11px] text-danger-400">
              {toolErr}
            </div>
          ) : filteredTools.length === 0 ? (
            <div className="rounded-md border border-gray-800 bg-gray-800/40 p-3 text-center text-[11px] text-gray-600">
              暂无已注册工具
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {filteredTools.map((t) => (
                <div
                  key={t.id ?? t.name}
                  draggable
                  onDragStart={(e) => onToolDragStart(e, t.name)}
                  title={t.description || t.name}
                  className="group w-full cursor-grab rounded-lg border border-gray-700 bg-gray-800 p-3 transition hover:border-teal-500 hover:bg-gray-700 active:cursor-grabbing"
                >
                  <div className="flex items-center gap-2.5">
                    <div
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-lg"
                      style={{
                        background: `${TOOL_COLOR}22`,
                        color: TOOL_COLOR,
                      }}
                    >
                      <span>🛠️</span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-semibold text-white">
                        {t.name || `工具 ${t.id}`}
                        {t.enabled === false && (
                          <span className="ml-1 text-[10px] text-gray-500">
                            （已禁用）
                          </span>
                        )}
                      </div>
                      <div className="truncate text-xs text-gray-400">
                        {t.description || '自定义工具'}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}

export default NodeLibrary
