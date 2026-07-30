import { useState } from 'react'
import { useWorkflowStore } from '../store/workflowStore'
import { inputCls } from './property/FormControls'

// 内置上下文变量列表（执行时自动注入，不可编辑）
const BUILTIN_VARS = [
  { name: 'payload', desc: '触发 payload 对象，如 ${payload.src_ip}', path: 'payload' },
  { name: 'execution_id', desc: '当前执行 ID', path: 'execution_id' },
  { name: 'workflow_id', desc: '工作流 ID', path: 'workflow_id' },
  { name: 'timestamp', desc: '执行时间戳（ISO 格式）', path: 'timestamp' },
]

// 全局变量管理面板：工作流级自定义变量 CRUD + 可用变量引用提示
function VariablePanel() {
  const variables = useWorkflowStore((s) => s.variables)
  const addVariable = useWorkflowStore((s) => s.addVariable)
  const updateVariable = useWorkflowStore((s) => s.updateVariable)
  const removeVariable = useWorkflowStore((s) => s.removeVariable)
  const [copied, setCopied] = useState('')

  // 复制变量引用语法到剪贴板
  const copyVar = async (path) => {
    const ref = `\${${path}}`
    try {
      await navigator.clipboard.writeText(ref)
      setCopied(path)
      setTimeout(() => setCopied(''), 1500)
    } catch {
      // 降级：用 prompt 让用户手动复制
      window.prompt('复制变量引用：', ref)
    }
  }

  return (
    <div className="flex flex-col gap-3 p-3 text-gray-200">
      {/* 标题与新增按钮 */}
      <div className="flex items-center justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-white">全局变量</h3>
          <p className="mt-0.5 text-[11px] text-gray-500">
            工作流级自定义变量，节点参数中用{' '}
            <code className="rounded bg-gray-800 px-1 text-brand-300">{'${variables.名称}'}</code>{' '}
            引用
          </p>
        </div>
        <button
          type="button"
          onClick={() => addVariable()}
          className="shrink-0 rounded-md bg-brand-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-500"
        >
          + 新增
        </button>
      </div>

      {/* 自定义变量列表 */}
      <div className="flex flex-col gap-2">
        {variables.length === 0 ? (
          <div className="rounded-md border border-dashed border-gray-700 px-3 py-6 text-center text-xs text-gray-500">
            暂无自定义变量
            <br />
            点击右上角「新增」创建
          </div>
        ) : (
          variables.map((v, i) => (
            <div
              key={i}
              className="rounded-md border border-gray-800 bg-gray-900/60 p-2.5"
            >
              <div className="flex items-center gap-2">
                <input
                  className={`${inputCls} min-w-0 flex-1 font-mono text-xs`}
                  placeholder="变量名（如 alert_threshold）"
                  value={v.name}
                  onChange={(e) => updateVariable(i, { name: e.target.value })}
                />
                {v.name && (
                  <button
                    type="button"
                    onClick={() => copyVar(`variables.${v.name}`)}
                    title="复制引用语法"
                    className="shrink-0 rounded border border-gray-700 px-2 py-1 text-[11px] text-brand-300 hover:bg-gray-800"
                  >
                    {copied === `variables.${v.name}` ? '✓ 已复制' : '复制 ${}'}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => removeVariable(i)}
                  title="删除变量"
                  className="shrink-0 rounded border border-danger-700/60 px-2 py-1 text-[11px] text-danger-400 hover:bg-danger-900/40"
                >
                  ✕
                </button>
              </div>
              <input
                className={`${inputCls} mt-1.5 text-xs`}
                placeholder="描述（可选）"
                value={v.description}
                onChange={(e) =>
                  updateVariable(i, { description: e.target.value })
                }
              />
              <input
                className={`${inputCls} mt-1.5 text-xs`}
                placeholder="默认值（留空为 null）"
                value={v.default_value ?? ''}
                onChange={(e) =>
                  updateVariable(i, { default_value: e.target.value })
                }
              />
            </div>
          ))
        )}
      </div>

      {/* 内置上下文变量（只读） */}
      <div>
        <h4 className="mb-2 text-xs font-semibold text-gray-400">
          内置上下文变量
        </h4>
        <div className="flex flex-col gap-2">
          {BUILTIN_VARS.map((bv) => (
            <div
              key={bv.path}
              className="flex items-center justify-between rounded-md border border-gray-800 bg-gray-900/40 px-2.5 py-1.5"
            >
              <div className="min-w-0">
                <div className="truncate font-mono text-xs text-brand-300">
                  {'${'}
                  {bv.path}
                  {'}'}
                </div>
                <div className="truncate text-[11px] text-gray-500">
                  {bv.desc}
                </div>
              </div>
              <button
                type="button"
                onClick={() => copyVar(bv.path)}
                className="shrink-0 rounded border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              >
                {copied === bv.path ? '✓' : '复制'}
              </button>
            </div>
          ))}
        </div>
        <div className="mt-2 rounded-md bg-gray-900/60 p-2 text-[11px] text-gray-500">
          <div className="font-medium text-gray-400">引用上游节点输出：</div>
          <div className="mt-1">
            用{' '}
            <code className="rounded bg-gray-800 px-1 text-brand-300">
              {'${node_id.field}'}
            </code>{' '}
            引用上游节点的输出字段（node_id 为画布上的节点 ID）
          </div>
        </div>
      </div>
    </div>
  )
}

export default VariablePanel
