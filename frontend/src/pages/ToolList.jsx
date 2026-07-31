import { useEffect, useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { tools as toolsApi } from '../api/client'
import { Modal } from '../components/Dialog'
import { inputCls } from '../components/property/FormControls'
import { TutorialButton, TutorialDrawer } from '../components/TutorialDrawer'
import { TOOL_TUTORIAL } from '../components/tutorialContent'
import { CATEGORY_META, UNCATEGORIZED } from '../constants/toolCategories'

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 根据参数 schema 字段类型生成合适的默认值
function defaultValueForType(type) {
  switch ((type || 'String').toLowerCase()) {
    case 'number':
      return ''
    case 'boolean':
      return false
    case 'object':
    case 'array':
      return ''
    default:
      return ''
  }
}

// 工具测试参数输入弹窗：根据 parameters_schema 自动生成输入控件
function ToolTestModal({ open, tool, onClose, onSubmit, running }) {
  const [params, setParams] = useState({})

  useEffect(() => {
    if (open && tool) {
      const init = {}
      ;(tool.parameters_schema || []).forEach((p) => {
        init[p.name] = defaultValueForType(p.type)
      })
      setParams(init)
    }
  }, [open, tool])

  if (!open || !tool) return null

  const handleSubmit = () => {
    // 将参数按 schema 类型转换为合适的 JS 值
    const parsed = {}
    ;(tool.parameters_schema || []).forEach((p) => {
      const raw = params[p.name]
      if (raw === '' || raw === undefined || raw === null) {
        // 不传
        return
      }
      switch ((p.type || 'String').toLowerCase()) {
        case 'number': {
          const n = Number(raw)
          parsed[p.name] = isNaN(n) ? raw : n
          break
        }
        case 'boolean':
          parsed[p.name] = raw === true || raw === 'true'
          break
        case 'object':
        case 'array':
          try {
            parsed[p.name] = JSON.parse(raw)
          } catch {
            parsed[p.name] = raw
          }
          break
        default:
          parsed[p.name] = raw
      }
    })
    onSubmit(parsed)
  }

  return (
    <Modal
      open={open}
      title={`测试工具：${tool.name || ''}`}
      onClose={onClose}
      maxWidth="max-w-2xl"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={running}
            className="btn-primary"
          >
            {running ? '运行中…' : '开始测试'}
          </button>
        </>
      }
    >
      {(tool.parameters_schema || []).length === 0 ? (
        <p className="text-sm text-gray-500">该工具没有参数，可直接点击「开始测试」。</p>
      ) : (
        <div className="flex flex-col gap-4">
          {(tool.parameters_schema || []).map((p) => (
            <div key={p.name}>
              <label className="mb-1 block text-xs font-medium text-gray-400">
                {p.name}
                <span className="ml-1 text-[10px] text-gray-500">({p.type})</span>
                {p.required && <span className="ml-1 text-danger-400">*</span>}
              </label>
              {p.type === 'Boolean' ? (
                <select
                  className={inputCls}
                  value={params[p.name] === true ? 'true' : 'false'}
                  onChange={(e) =>
                    setParams((prev) => ({ ...prev, [p.name]: e.target.value === 'true' }))
                  }
                >
                  <option value="false">false</option>
                  <option value="true">true</option>
                </select>
              ) : p.type === 'Object' || p.type === 'Array' ? (
                <textarea
                  className={`${inputCls} resize-y font-mono`}
                  rows={3}
                  value={params[p.name] ?? ''}
                  onChange={(e) =>
                    setParams((prev) => ({ ...prev, [p.name]: e.target.value }))
                  }
                  placeholder={p.type === 'Array' ? '["a","b"]' : '{"key":"value"}'}
                />
              ) : (
                <input
                  className={inputCls}
                  value={params[p.name] ?? ''}
                  onChange={(e) =>
                    setParams((prev) => ({ ...prev, [p.name]: e.target.value }))
                  }
                  placeholder={p.description || ''}
                />
              )}
              {p.description && (
                <p className="mt-1 text-[11px] text-gray-500">{p.description}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

// 工具列表：列出 GET /tools，支持新建/编辑跳转、测试、删除、从模板新建
function ToolList() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tutorialOpen, setTutorialOpen] = useState(false)

  // 测试相关
  const [testOpen, setTestOpen] = useState(false)
  const [testTool, setTestTool] = useState(null)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [resultErr, setResultErr] = useState('')
  const [resultOpen, setResultOpen] = useState(false)

  // 模板相关
  const [tplOpen, setTplOpen] = useState(false)
  const [templates, setTemplates] = useState([])
  const [tplLoading, setTplLoading] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await toolsApi.list()
      setRows(Array.isArray(data) ? data : [])
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleDelete = async (id, name) => {
    if (!window.confirm(`确定删除工具「${name || id}」吗？`)) return
    try {
      await toolsApi.remove(id)
      setRows((prev) => prev.filter((r) => r.id !== id))
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  const openTest = (tool) => {
    setTestTool(tool)
    setTestOpen(true)
  }

  // 执行测试：POST /tools/{id}/test body={parameters}
  const handleTest = async (params) => {
    setTestOpen(false)
    if (!testTool) return
    setRunning(true)
    setResultErr('')
    try {
      const res = await toolsApi.test(testTool.id, params)
      setResult(res)
      setResultOpen(true)
    } catch (err) {
      setResultErr(err.message || String(err))
      setResultOpen(true)
    } finally {
      setRunning(false)
    }
  }

  // 从模板新建：拉取 GET /tools/templates，选中后跳转到编辑器并携带模板信息
  const openTemplates = async () => {
    setTplOpen(true)
    setTplLoading(true)
    try {
      const data = await toolsApi.templates()
      setTemplates(Array.isArray(data) ? data : [])
    } catch (err) {
      window.alert(`加载模板失败：${err.message || err}`)
    } finally {
      setTplLoading(false)
    }
  }

  // 选中模板 -> 通过 sessionStorage 传递 -> 跳到 /tools/new
  const pickTemplate = (tpl) => {
    sessionStorage.setItem('soar:tool:template', JSON.stringify(tpl))
    setTplOpen(false)
    navigate('/tools/new')
  }

  // 按工具集分类分组（category 为 null/undefined 归入 "其他"）
  const grouped = useMemo(() => {
    const map = new Map()
    for (const r of rows) {
      const cat = r.category || '_uncategorized'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat).push(r)
    }
    // 按 CATEGORY_META 定义的顺序排序，未分类放最后
    const order = Object.keys(CATEGORY_META)
    const sorted = [...map.entries()].sort((a, b) => {
      const ia = order.indexOf(a[0])
      const ib = order.indexOf(b[0])
      if (ia === -1 && ib === -1) return 0
      if (ia === -1) return 1
      if (ib === -1) return -1
      return ia - ib
    })
    return sorted
  }, [rows])

  // 渲染单行工具
  const renderToolRow = (r, idx) => (
    <tr
      key={r.id}
      className={`border-t border-gray-800 transition-colors hover:bg-brand-500/5 ${
        idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
      }`}
    >
      <td className="px-4 py-3 font-mono text-brand-300">#{r.id}</td>
      <td className="truncate px-4 py-3 text-gray-200">{r.name || '-'}</td>
      <td className="truncate px-4 py-3 text-gray-400" title={r.description || ''}>
        {r.description || '-'}
      </td>
      <td className="px-4 py-3">
        <span
          className={`inline-flex shrink-0 items-center whitespace-nowrap rounded border px-2 py-0.5 text-[11px] font-medium ${
            r.tool_type === 'http'
              ? 'border-brand-500/40 bg-brand-500/10 text-brand-300'
              : r.tool_type === 'framework'
              ? 'border-purple-500/40 bg-purple-500/10 text-purple-300'
              : 'border-gray-700 bg-gray-800 text-gray-400'
          }`}
          title={
            r.tool_type === 'http'
              ? 'HTTP 接口工具'
              : r.tool_type === 'framework'
              ? 'Hermes 框架内置工具（schema 入库，执行走引擎拦截）'
              : 'Python 代码工具'
          }
        >
          {r.tool_type === 'http'
            ? 'HTTP'
            : r.tool_type === 'framework'
            ? '框架内置'
            : 'Code'}
        </span>
      </td>
      <td className="px-4 py-3">
        <span
          className={`rounded px-2 py-0.5 text-[11px] font-medium ${
            r.enabled ? 'bg-success-500/20 text-success-300' : 'bg-gray-700 text-gray-400'
          }`}
        >
          {r.enabled ? '启用' : '禁用'}
        </span>
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-gray-400">{fmtTime(r.updated_at)}</td>
      <td className="px-4 py-3">
        <div className="flex flex-nowrap gap-2">
          <button
            type="button"
            onClick={() => navigate(`/tools/${r.id}/edit`)}
            className="btn-secondary btn-sm"
          >
            编辑
          </button>
          {r.tool_type !== 'framework' && (
            <button
              type="button"
              disabled={running && testTool?.id === r.id}
              onClick={() => openTest(r)}
              className="btn-secondary btn-sm"
            >
              测试
            </button>
          )}
          {r.tool_type !== 'framework' && (
            <button
              type="button"
              onClick={() => handleDelete(r.id, r.name)}
              className="btn-danger btn-sm"
            >
              删除
            </button>
          )}
        </div>
      </td>
    </tr>
  )

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-100">工具</h1>
          <span className="text-xs text-gray-500">共 {rows.length} 个</span>
        </div>
        <div className="flex items-center gap-2">
          <TutorialButton onClick={() => setTutorialOpen(true)} />
          <button
            type="button"
            onClick={load}
            className="btn-secondary btn-sm"
          >
            刷新
          </button>
          <button
            type="button"
            onClick={openTemplates}
            className="btn-secondary btn-sm"
          >
            从模板新建
          </button>
          <button
            type="button"
            onClick={() => navigate('/tools/new')}
            className="btn-primary btn-sm"
          >
            + 新建工具
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">
            加载中...
          </div>
        ) : rows.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">🔧</div>
            <div className="text-sm">暂无工具</div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {grouped.map(([cat, tools]) => {
              const meta = cat === '_uncategorized' ? UNCATEGORIZED : (CATEGORY_META[cat] || UNCATEGORIZED)
              return (
                <div key={cat} className="overflow-hidden rounded-lg border border-gray-800">
                  {/* 工具集分组标题 */}
                  <div className="flex items-center gap-2 border-b border-gray-800 bg-gray-900/60 px-4 py-2.5">
                    <span className="text-base">{meta.icon}</span>
                    <span className="text-sm font-semibold text-gray-200">{meta.label}</span>
                    <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400">{tools.length}</span>
                    <span className="text-[11px] text-gray-500">{meta.desc}</span>
                  </div>
                  {/* 工具表格 */}
                  <div className="overflow-x-auto">
                    <table className="w-full table-fixed border-collapse text-sm">
                      <thead className="bg-gray-900/40 text-gray-400">
                        <tr>
                          <th className="w-16 px-4 py-2 text-left font-medium">ID</th>
                          <th className="px-4 py-2 text-left font-medium">名称</th>
                          <th className="px-4 py-2 text-left font-medium">描述</th>
                          <th className="w-28 px-4 py-2 text-left font-medium">类型</th>
                          <th className="w-20 px-4 py-2 text-left font-medium">启用</th>
                          <th className="w-44 px-4 py-2 text-left font-medium">更新时间</th>
                          <th className="w-60 px-4 py-2 text-left font-medium">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tools.map((r, idx) => renderToolRow(r, idx))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 测试参数弹窗 */}
      <ToolTestModal
        open={testOpen}
        tool={testTool}
        onClose={() => setTestOpen(false)}
        onSubmit={handleTest}
        running={running}
      />

      {/* 测试结果弹窗 */}
      <Modal
        open={resultOpen}
        title={`工具测试结果${testTool ? `：${testTool.name || ''}` : ''}`}
        onClose={() => setResultOpen(false)}
        maxWidth="max-w-3xl"
        footer={
          <button
            type="button"
            onClick={() => setResultOpen(false)}
            className="btn-primary"
          >
            关闭
          </button>
        }
      >
        {resultErr ? (
          <div className="rounded-md border border-danger-500/40 bg-danger-500/10 p-4 text-sm text-danger-300">
            {resultErr}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <div className="mb-1 text-xs text-gray-500">Result</div>
              <pre className="max-h-72 w-full overflow-auto rounded-md bg-gray-950 p-4 font-mono text-xs text-gray-200 ring-1 ring-gray-800">
                {result?.result == null
                  ? '(空)'
                  : typeof result.result === 'string'
                  ? result.result
                  : JSON.stringify(result.result, null, 2)}
              </pre>
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">
                日志（{(result?.logs || []).length} 条）
              </div>
              <div className="max-h-48 w-full overflow-auto rounded-md bg-gray-950 p-4 ring-1 ring-gray-800">
                {(result?.logs || []).length === 0 ? (
                  <div className="text-xs text-gray-600">暂无日志</div>
                ) : (
                  <div className="flex flex-col gap-1">
                    {result.logs.map((log, idx) => (
                      <div key={idx} className="font-mono text-xs">
                        <span className="mr-2 text-gray-400">[{(log.level || 'info').toUpperCase()}]</span>
                        <span className="text-gray-300">{log.message}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* 模板选择弹窗 */}
      <Modal
        open={tplOpen}
        title="从模板新建工具"
        onClose={() => setTplOpen(false)}
        maxWidth="max-w-2xl"
        footer={
          <button
            type="button"
            onClick={() => setTplOpen(false)}
            className="btn-secondary"
          >
            取消
          </button>
        }
      >
        {tplLoading ? (
          <div className="text-sm text-gray-500">加载中...</div>
        ) : templates.length === 0 ? (
          <div className="text-sm text-gray-500">暂无模板</div>
        ) : (
          <div className="flex flex-col gap-2">
            {templates.map((tpl, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => pickTemplate(tpl)}
                className="w-full rounded-md border border-gray-800 bg-gray-900/60 p-4 text-left transition hover:border-brand-600 hover:bg-gray-900"
              >
                <div className="text-sm font-medium text-gray-100">{tpl.name}</div>
                {tpl.description && (
                  <div className="mt-1 text-xs text-gray-400">{tpl.description}</div>
                )}
              </button>
            ))}
          </div>
        )}
      </Modal>

      {/* 使用教程 */}
      <TutorialDrawer
        open={tutorialOpen}
        onClose={() => setTutorialOpen(false)}
        title="工具管理使用教程"
        subtitle="了解如何创建、配置和测试工具"
        sections={TOOL_TUTORIAL}
      />
    </div>
  )
}

export default ToolList
