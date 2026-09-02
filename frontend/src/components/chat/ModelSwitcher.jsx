/**
 * 模型切换下拉选择器（对标 new-api Playground 模型选择）
 *
 * 列出所有 chat 类型的 LLM 配置，用户可切换覆盖智能体默认模型。
 * 选择"使用智能体默认"（value=""）时不清空智能体配置，仅本次会话不覆盖。
 *
 * Props:
 * - value: 当前选中的 model_config_id（null/'' 表示用智能体默认）
 * - onChange: (modelConfigId | null) => void
 * - llmConfigs: LLM 配置列表（来自 llmConfigsApi.list()）
 * - agentDefaultModelId: 智能体配置的默认 model_config_id（用于显示标签）
 */
import { ChevronDown, Cpu } from 'lucide-react'

export default function ModelSwitcher({
  value = null,
  onChange,
  llmConfigs = [],
  agentDefaultModelId = null,
}) {
  // 只显示 chat 类型配置（过滤 embedding）
  const chatConfigs = llmConfigs.filter((c) => (c.model_type || 'chat') === 'chat')
  // 当前选中模型名（用于显示）
  const selectedId = value || ''
  const selectedConfig = chatConfigs.find((c) => String(c.id) === String(selectedId))
  // 去重：name 和 model_name 相同时只显示一次
  const formatLabel = (c) => {
    if (!c) return '智能体默认'
    const name = c.name || ''
    const model = c.model_name || ''
    if (name && model && name !== model) return `${name} · ${model}`
    return name || model || '未知模型'
  }
  const selectedLabel = selectedConfig
    ? formatLabel(selectedConfig)
    : agentDefaultModelId
    ? (() => {
        const def = chatConfigs.find((c) => String(c.id) === String(agentDefaultModelId))
        return def ? `默认 · ${formatLabel(def)}` : '智能体默认'
      })()
    : '智能体默认'

  return (
    <div className="relative inline-flex items-center">
      <Cpu className="pointer-events-none absolute left-2 h-3.5 w-3.5 text-muted-foreground/60" />
      <select
        value={selectedId}
        onChange={(e) => {
          const v = e.target.value
          onChange && onChange(v ? Number(v) : null)
        }}
        className="h-8 cursor-pointer appearance-none rounded-md border border-border bg-secondary pl-7 pr-7 text-xs text-foreground transition hover:bg-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
        title="切换模型（仅本次会话生效）"
      >
        <option value="">智能体默认</option>
        {chatConfigs.map((c) => (
          <option key={c.id} value={c.id}>
            {formatLabel(c)}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 h-3 w-3 text-muted-foreground/60" />
      {/* 选中值预览标签（紧凑显示，避免 select 宽度跳变） */}
      <span className="sr-only">{selectedLabel}</span>
    </div>
  )
}
