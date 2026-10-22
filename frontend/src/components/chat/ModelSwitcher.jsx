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
import { Cpu } from 'lucide-react'
import { CompactSelect } from '../ui'

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
    <div className="inline-flex items-center gap-1">
      <Cpu className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <CompactSelect
        size="sm"
        variant="ghost"
        className="max-w-[180px]"
        value={selectedId}
        onChange={(e) => {
          const v = e.target.value
          onChange && onChange(v ? Number(v) : null)
        }}
        title="切换模型（仅本次会话生效）"
      >
        <option value="">智能体默认</option>
        {chatConfigs.map((c) => (
          <option key={c.id} value={c.id}>
            {formatLabel(c)}
          </option>
        ))}
      </CompactSelect>
      {/* 选中值预览标签（紧凑显示，避免 select 宽度跳变） */}
      <span className="sr-only">{selectedLabel}</span>
    </div>
  )
}
