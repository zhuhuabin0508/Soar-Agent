import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useWorkflowStore } from '../store/workflowStore'
import { workflows as workflowsApi } from '../api/client'
import { inputCls } from './property/FormControls'
import { JsonInputDialog } from './Dialog'

// 顶部工具栏：标题 + 工作流名称输入 + 保存/试运行/校验/清空/导入/导出 按钮
function Toolbar() {
  const [searchParams, setSearchParams] = useSearchParams()
  const serialize = useWorkflowStore((s) => s.serialize)
  const clearAll = useWorkflowStore((s) => s.clearAll)
  const workflowName = useWorkflowStore((s) => s.workflowName)
  const workflowId = useWorkflowStore((s) => s.workflowId)
  const setWorkflowName = useWorkflowStore((s) => s.setWorkflowName)
  const setWorkflowId = useWorkflowStore((s) => s.setWorkflowId)
  const markSaved = useWorkflowStore((s) => s.markSaved)
  const setRunLogs = useWorkflowStore((s) => s.setRunLogs)
  const setRunTraces = useWorkflowStore((s) => s.setRunTraces)
  // 用于导入：直接灌入 nodes/edges
  const loadWorkflow = useWorkflowStore((s) => s.loadWorkflow)
  // 脏标记：用于导入前提醒
  const isDirty = useWorkflowStore((s) => s.isDirty)

  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [validating, setValidating] = useState(false)
  const [testOpen, setTestOpen] = useState(false)

  // 隐藏的文件输入：用于导入 JSON 文件
  const fileInputRef = useRef(null)

  // 调用后端校验接口，返回 { valid, errors, warnings }；失败时抛错由调用方处理
  const handleValidate = async (graphConfig) => {
    const res = await workflowsApi.validate(graphConfig)
    return {
      valid: !!res?.valid,
      errors: Array.isArray(res?.errors) ? res.errors : [],
      warnings: Array.isArray(res?.warnings) ? res.warnings : [],
    }
  }

  // 保存：workflowId 存在则 PUT 更新，否则 POST 新建
  const handleSave = async () => {
    const name = (workflowName || '').trim()
    if (!name) {
      window.alert('请先填写工作流名称')
      return
    }
    // 保存前校验：errors 阻止保存；warnings 需用户确认
    setSaving(true)
    try {
      let v
      try {
        v = await handleValidate(serialize())
      } catch (err) {
        window.alert(`校验请求失败：${err.message || err}`)
        return
      }
      if (v.errors.length > 0) {
        window.alert('工作流校验未通过：\n\n' + v.errors.join('\n'))
        return
      }
      if (
        v.warnings.length > 0 &&
        !window.confirm('存在告警：\n' + v.warnings.join('\n') + '\n\n仍要保存吗？')
      ) {
        return
      }
      const body = { name, graph_config: serialize() }
      let data
      if (workflowId) {
        data = await workflowsApi.update(workflowId, body)
      } else {
        data = await workflowsApi.create(body)
        // 新建后回填 workflowId，并同步 URL id 参数
        // 防止刷新页面时 useEffect 检测到无 id 参数而 clearAll 清空画布
        if (data && data.id != null) {
          setWorkflowId(data.id)
          setSearchParams({ id: data.id }, { replace: true })
        }
      }
      // 保存成功后清除脏标记
      markSaved()
      window.alert(`工作流已保存${data && data.id != null ? `（ID: ${data.id}）` : ''}`)
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setSaving(false)
    }
  }

  // 全部试运行：先校验，再调 POST /workflows/{id}/test-run
  const handleTestRunAll = async (payload) => {
    setTestOpen(false)
    if (!workflowId) {
      window.alert('请先保存工作流后再试运行')
      return
    }
    // 试运行前校验：errors 阻止；warnings 需确认
    try {
      const v = await handleValidate(serialize())
      if (v.errors.length > 0) {
        window.alert('工作流校验未通过：\n\n' + v.errors.join('\n'))
        return
      }
      if (
        v.warnings.length > 0 &&
        !window.confirm('存在告警：\n' + v.warnings.join('\n') + '\n\n仍要试运行吗？')
      ) {
        return
      }
    } catch (err) {
      window.alert(`校验请求失败：${err.message || err}`)
      return
    }
    setRunning(true)
    try {
      const res = await workflowsApi.testRun(workflowId, payload)
      setRunTraces(res?.traces || [])
      setRunLogs(res?.logs || [])
      window.alert(`试运行完成：${res?.status || '未知'}`)
    } catch (err) {
      window.alert(`试运行失败：${err.message || err}`)
      setRunLogs([
        {
          level: 'error',
          node_id: '-',
          message: `试运行请求失败：${err.message || err}`,
          timestamp: new Date().toISOString(),
        },
      ])
    } finally {
      setRunning(false)
    }
  }

  // 独立「检查」按钮：主动调用校验接口并用 alert 展示结果
  const handleCheck = async () => {
    setValidating(true)
    try {
      const v = await handleValidate(serialize())
      if (v.errors.length > 0) {
        window.alert(
          `校验未通过（${v.errors.length} 个错误）：\n\n` +
            v.errors.join('\n') +
            (v.warnings.length > 0
              ? '\n\n告警：\n' + v.warnings.join('\n')
              : '')
        )
      } else {
        window.alert(
          '校验通过' +
            (v.warnings.length > 0
              ? `（${v.warnings.length} 个告警）：\n\n` + v.warnings.join('\n')
              : '，无告警。')
        )
      }
    } catch (err) {
      window.alert(`校验请求失败：${err.message || err}`)
    } finally {
      setValidating(false)
    }
  }

  const handleClear = () => {
    if (window.confirm('确定要清空画布吗？所有节点与连线将被移除。')) {
      clearAll()
    }
  }

  // 导出当前画布为 JSON 文件（含工作流名称与图结构）
  const handleExport = () => {
    const graphConfig = serialize()
    const exportData = {
      _type: 'soar_workflow_export',
      _version: '1.0',
      name: workflowName || '未命名工作流',
      exported_at: new Date().toISOString(),
      graph_config: graphConfig,
    }
    const json = JSON.stringify(exportData, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const safeName = (workflowName || 'workflow').replace(/[^\w\u4e00-\u9fa5-]/g, '_')
    a.href = url
    a.download = `${safeName}_${Date.now()}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // 触发文件选择对话框
  const handleImportClick = () => {
    if (isDirty) {
      if (
        !window.confirm(
          '当前画布有未保存的变更，导入将覆盖现有内容。确定继续吗？'
        )
      ) {
        return
      }
    }
    fileInputRef.current?.click()
  }

  // 读取选中的 JSON 文件并灌入画布
  const handleImportFile = (e) => {
    const file = e.target.files?.[0]
    // 清空 input 的 value，便于重复选择同一文件
    e.target.value = ''
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const raw = ev.target?.result
        const data = JSON.parse(typeof raw === 'string' ? raw : '')
        // 兼容两种格式：导出文件 { name, graph_config } 或纯 graph_config { nodes, edges }
        let name = ''
        let graph = null
        if (data && data.graph_config && (data.graph_config.nodes || data.graph_config.edges)) {
          name = data.name || ''
          graph = data.graph_config
        } else if (data && (data.nodes || data.edges)) {
          graph = data
        } else {
          window.alert('文件格式不正确：未找到 nodes/edges 字段')
          return
        }
        // 灌入 store（清空当前画布并加载导入内容）
        loadWorkflow({
          id: null,
          name: name || `${workflowName || '导入工作流'}_副本`,
          graph_config: graph,
        })
        // 同步 URL（清除 id 参数，因为导入的是新工作流）
        setSearchParams({})
        window.alert('工作流已导入，请检查后点击「保存」以持久化')
      } catch (err) {
        window.alert(`导入失败：${err.message || err}`)
      }
    }
    reader.onerror = () => {
      window.alert('文件读取失败')
    }
    reader.readAsText(file)
  }

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-800 bg-gray-900 px-4">
      {/* 左侧标题 + 工作流名称输入 */}
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold leading-tight text-white">
            SOAR 工作流编排
          </h1>
          <p className="truncate text-xs leading-tight text-gray-400">
            安全编排自动化响应 · 可视化流程编排平台
          </p>
        </div>
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <label className="shrink-0 text-xs text-gray-500">名称</label>
          <input
            className={`${inputCls} max-w-[320px]`}
            placeholder="未命名工作流"
            value={workflowName}
            onChange={(e) => setWorkflowName(e.target.value)}
          />
          {workflowId != null && (
            <span className="shrink-0 rounded bg-gray-800 px-2 py-1 font-mono text-[11px] text-gray-400">
              ID: {workflowId}
            </span>
          )}
        </div>
      </div>

      {/* 右侧操作按钮 */}
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={handleImportClick}
          title="从 JSON 文件导入工作流到画布"
          className="rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 transition hover:border-gray-600 hover:bg-gray-700 hover:text-white"
        >
          导入
        </button>
        <button
          type="button"
          onClick={handleExport}
          title="将当前画布导出为 JSON 文件"
          className="rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 transition hover:border-gray-600 hover:bg-gray-700 hover:text-white"
        >
          导出
        </button>
        <button
          type="button"
          onClick={handleClear}
          className="rounded-md border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 transition hover:border-gray-600 hover:bg-gray-700 hover:text-white"
        >
          清空画布
        </button>
        <button
          type="button"
          onClick={handleCheck}
          disabled={validating}
          className="rounded-md border border-success-700 bg-success-900/30 px-3 py-1.5 text-sm text-success-300 transition hover:bg-success-900/60 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {validating ? '检查中…' : '检查'}
        </button>
        <button
          type="button"
          onClick={() => setTestOpen(true)}
          disabled={running}
          className="rounded-md border border-brand-700 bg-brand-900/30 px-3 py-1.5 text-sm text-brand-300 transition hover:bg-brand-900/60 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? '运行中…' : '全部试运行'}
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-brand-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? '保存中…' : '保存'}
        </button>
      </div>

      {/* 隐藏的文件输入：用于导入 JSON 文件 */}
      <input
        ref={fileInputRef}
        type="file"
        accept="application/json,.json"
        onChange={handleImportFile}
        className="hidden"
      />

      <JsonInputDialog
        open={testOpen}
        title="全部试运行 · 输入示例 payload（JSON）"
        onClose={() => setTestOpen(false)}
        onSubmit={handleTestRunAll}
        submitText="开始运行"
      />
    </header>
  )
}

export default Toolbar
