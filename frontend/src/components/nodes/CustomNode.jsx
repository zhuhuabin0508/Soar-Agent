import { memo, useState } from 'react'
import { Handle, Position, NodeToolbar } from 'reactflow'
import { getNodeDefinition } from '../../constants/nodeCatalog'
import { useWorkflowStore } from '../../store/workflowStore'
import { workflows as workflowsApi } from '../../api/client'
import { Modal } from '../Dialog'

// 根据节点类型与 data 生成简要摘要
function getSummary(type, data) {
  switch (type) {
    case 'webhook_trigger':
      return `${data?.method || 'POST'} · ${data?.content_type || 'application/json'}`
    case 'condition_branch': {
      if (data?.mode === 'switch') {
        return `SWITCH · ${data?.cases?.length || 0} 个分支`
      }
      const n = data?.conditions?.length || 0
      return `IF · ${n} 个条件 (${data?.logic || 'AND'})`
    }
    case 'http_request':
      return `${data?.method || 'GET'}  ${data?.url ? data.url : '未配置 URL'}`
    case 'ai_agent':
      return `${data?.model || '未配置模型'} · 工具 ${data?.enabled_tools?.length || 0}`
    case 'block_ip':
      return `${data?.action === 'unblock' ? '解封' : '封禁'} ${data?.target_ip || '{{src_ip}}'} · ${data?.duration_value || 24}${data?.duration_unit || '小时'}`
    case 'device_action':
      return `设备 #${data?.device_id || '?'} · 动作 #${data?.action_id || '?'}`
    case 'send_notification':
      return `${data?.channel || 'email'} · ${data?.severity || 'warning'}`
    case 'tool':
      return `工具: ${data?.tool_name || '未选择'}`
    case 'human_review':
      return `${data?.title || '人工审批工单'}`
    case 'code_execute':
      return `Python · ${data?.code ? data.code.split('\n')[0].slice(0, 40) : '未配置代码'}`
    case 'loop':
      return data?.loop_mode === 'while'
        ? `WHILE · ${data?.loop_condition || '未配置条件'}`
        : `COUNT · ${data?.count || 1} 次`
    case 'iteration':
      return `遍历 · ${data?.data_source || 'input'} 源`
    case 'end':
      return `结束 · ${data?.end_type || 'success'}`
    default:
      return ''
  }
}

// 条件分支的多出口 handle；end 节点无出口 handle
function BranchHandles({ type, data }) {
  // end 节点不渲染出口，标识流程终止
  if (type === 'end') {
    return null
  }
  if (type !== 'condition_branch') {
    return (
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: '#06b6d4', width: 10, height: 10 }}
      />
    )
  }

  // 收集出口列表：[{ id, label }]
  let outputs = []
  if (data?.mode === 'switch') {
    outputs = (data?.cases || []).map((c) => ({ id: c.label, label: c.label }))
    outputs.push({ id: 'default', label: '默认' })
  } else {
    outputs = [
      { id: data?.true_label || '是', label: data?.true_label || '是' },
      { id: data?.false_label || '否', label: data?.false_label || '否' },
    ]
  }

  // 多个 handle 垂直排列在右侧
  const gap = 26
  const start = 50 - ((outputs.length - 1) * gap) / 2
  return (
    <>
      {outputs.map((o, i) => (
        <div
          key={o.id}
          className="absolute right-0 flex items-center"
          style={{ top: `${start + i * gap}%`, transform: 'translateY(-50%)' }}
        >
          <span className="mr-1 rounded bg-gray-900/80 px-1 text-[10px] text-gray-300">
            {o.label}
          </span>
          <Handle
            type="source"
            position={Position.Right}
            id={o.id}
            style={{ background: '#06b6d4', width: 10, height: 10 }}
          />
        </div>
      ))}
    </>
  )
}

// 节点 hover 工具栏按钮样式
const toolbarBtnCls =
  'flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition whitespace-nowrap'

function CustomNode({ id, type, data, selected }) {
  const def = getNodeDefinition(type)
  // 从 store 获取节点操作 actions（函数引用稳定，不会导致额外重渲染）
  const duplicateNode = useWorkflowStore((s) => s.duplicateNode)
  const removeNode = useWorkflowStore((s) => s.removeNode)
  const setSelectedNode = useWorkflowStore((s) => s.setSelectedNode)

  // 单节点运行状态
  const [running, setRunning] = useState(false)
  const [runResult, setRunResult] = useState(null)
  const [resultOpen, setResultOpen] = useState(false)

  if (!def) return null

  const summary = getSummary(type, data)
  const accent = def.color

  // 运行此步骤：调用后端 POST /test-node
  const handleRunNode = async () => {
    setRunning(true)
    setRunResult(null)
    try {
      const res = await workflowsApi.testNode(
        { id, type, data },
        data?.test_input || {}
      )
      setRunResult(res)
      setResultOpen(true)
    } catch (err) {
      setRunResult({
        output: { error: err.message || String(err) },
        logs: [{ node_id: id, level: 'error', message: err.message || String(err) }],
      })
      setResultOpen(true)
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      {/* hover 工具栏：鼠标移入节点时显示 */}
      <NodeToolbar position={Position.Top} offset={8}>
        <div className="flex items-center gap-0.5 rounded-md border border-gray-700 bg-gray-900/95 p-1 shadow-xl backdrop-blur">
          <button
            type="button"
            onClick={handleRunNode}
            disabled={running}
            title="运行此步骤（单节点测试）"
            className={`${toolbarBtnCls} text-success-300 hover:bg-success-900/40 disabled:opacity-50`}
          >
            {running ? '⏳' : '▶'} 运行
          </button>
          <button
            type="button"
            onClick={() => setSelectedNode(id)}
            title="更改节点（打开属性面板）"
            className={`${toolbarBtnCls} text-brand-300 hover:bg-brand-900/40`}
          >
            ✏ 更改
          </button>
          <button
            type="button"
            onClick={() => duplicateNode(id)}
            title="复制节点"
            className={`${toolbarBtnCls} text-brand-300 hover:bg-brand-900/40`}
          >
            ⧉ 复制
          </button>
          <button
            type="button"
            onClick={() => removeNode(id)}
            title="删除节点"
            className={`${toolbarBtnCls} text-danger-400 hover:bg-danger-900/40`}
          >
            ✕ 删除
          </button>
        </div>
      </NodeToolbar>

      <div
        className="relative rounded-lg bg-gray-800 text-white shadow-lg w-full"
        style={{
          minWidth: 220,
          maxWidth: 280,
          borderWidth: 2,
          borderStyle: 'solid',
          borderColor: selected ? accent : '#374151',
          boxShadow: selected
            ? `0 0 0 2px ${accent}40`
            : '0 4px 12px rgba(0,0,0,0.4)',
        }}
      >
        {/* 左侧入口连接点 */}
        <Handle
          type="target"
          position={Position.Left}
          style={{ background: accent, width: 10, height: 10 }}
        />

        {/* 顶部彩条（类型标识色） */}
        <div
          className="h-1 w-full rounded-t-lg"
          style={{ background: accent }}
        />

        <div className="px-3 py-2.5">
          <div className="flex items-center gap-2.5">
            {/* 图标徽章 */}
            <div
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-base"
              style={{ background: `${accent}22`, color: accent }}
            >
              <span>{def.icon}</span>
            </div>
            {/* 节点名称：优先显示用户自定义 label，回退到类型默认 label */}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold leading-tight">
                {data?.label || def.label}
              </div>
              <div className="truncate text-[11px] text-gray-400 leading-tight">
                {type}
                <span className="ml-1 text-gray-600">· 双击改名</span>
              </div>
            </div>
          </div>

          {/* 用户自定义描述（若有） */}
          {data?.description && (
            <div
              className="mt-1.5 truncate text-[11px] italic text-gray-400"
              title={data.description}
            >
              {data.description}
            </div>
          )}

          {/* 关键字段摘要 */}
          <div
            className="mt-2 truncate rounded bg-gray-900/60 px-2 py-1 text-xs text-gray-300"
            title={summary}
          >
            {summary}
          </div>
        </div>

        {/* 右侧出口连接点（条件分支为多出口） */}
        <BranchHandles type={type} data={data} />
      </div>

      {/* 单节点运行结果弹窗 */}
      <Modal
        open={resultOpen}
        title={`节点运行结果：${data?.label || def.label}`}
        onClose={() => setResultOpen(false)}
        maxWidth="max-w-2xl"
        footer={
          <button
            type="button"
            onClick={() => setResultOpen(false)}
            className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-500"
          >
            关闭
          </button>
        }
      >
        <div className="flex flex-col gap-3">
          {/* 输出 */}
          <div>
            <div className="mb-1 text-xs font-medium text-gray-400">输出（output）</div>
            <pre className="max-h-60 overflow-auto rounded-md bg-gray-950 p-3 text-xs text-success-300 ring-1 ring-gray-800">
              {runResult?.output
                ? JSON.stringify(runResult.output, null, 2)
                : '(空)'}
            </pre>
          </div>
          {/* 日志 */}
          <div>
            <div className="mb-1 text-xs font-medium text-gray-400">
              日志（{(runResult?.logs || []).length} 条）
            </div>
            <div className="max-h-48 overflow-auto rounded-md bg-gray-950 p-2 ring-1 ring-gray-800">
              {(runResult?.logs || []).length === 0 ? (
                <div className="text-xs text-gray-600">暂无日志</div>
              ) : (
                <div className="flex flex-col gap-1">
                  {runResult.logs.map((l, i) => (
                    <div key={i} className="text-xs">
                      <span
                        className={`mr-2 font-mono ${
                          l.level === 'error'
                            ? 'text-danger-400'
                            : l.level === 'warn'
                            ? 'text-warning-400'
                            : 'text-gray-500'
                        }`}
                      >
                        [{l.level}]
                      </span>
                      <span className="text-gray-300">{l.message}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </Modal>
    </>
  )
}

export default memo(CustomNode)
