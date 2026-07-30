import { useCallback, useEffect, useState } from 'react'
import { agents as agentsApi } from '../api/client'
import { Section, SelectInput, NumberInput } from './property/FormControls'

// ============================================================================
// 工具搜索状态组件 —— 编辑 tool_configs.tool_search + 展示装配预览
//
// 数据契约（与后端 backend/app/agent/hermes/tool_search.py:ToolSearchConfig 对齐）：
//   tool_configs.tool_search = {
//     enabled: 'auto' | 'on' | 'off',   // 默认 'auto'
//     threshold_pct: number,             // 0-100, 默认 10
//     search_default_limit: int,         // 默认 5
//     max_search_limit: int,             // 默认 20
//   }
//
// 后端端点 GET /agents/{id}/tool-search-status 返回：
//   {
//     supported: bool,
//     config: { enabled, threshold_pct, search_default_limit, max_search_limit },
//     classification: { visible: [...], deferrable: [...], visible_by_source, deferrable_by_source },
//     stats: { visible_count, deferrable_count, visible_tokens, deferrable_tokens, would_activate, ... },
//     source_catalog: { core_sources, deferrable_sources },
//   }
// ============================================================================

const TS_DEFAULTS = {
  enabled: 'auto',
  threshold_pct: 10,
  search_default_limit: 5,
  max_search_limit: 20,
}

const MODE_OPTIONS = [
  { value: 'auto', label: 'auto（阈值门控）' },
  { value: 'on', label: 'on（强制激活）' },
  { value: 'off', label: 'off（禁用）' },
]

// source → 中文标签 + 颜色
const SOURCE_META = {
  builtin: { label: '内置工具', color: 'text-emerald-300', bg: 'bg-emerald-500/10' },
  kb: { label: '知识库', color: 'text-blue-300', bg: 'bg-blue-500/10' },
  delegate: { label: '子代理委派', color: 'text-purple-300', bg: 'bg-purple-500/10' },
  memory: { label: '记忆', color: 'text-cyan-300', bg: 'bg-cyan-500/10' },
  persisted: { label: '持久化结果', color: 'text-amber-300', bg: 'bg-amber-500/10' },
  db_code: { label: 'DB 代码工具', color: 'text-orange-300', bg: 'bg-orange-500/10' },
  db_http: { label: 'DB HTTP 工具', color: 'text-red-300', bg: 'bg-red-500/10' },
  openapi_dynamic: { label: 'OpenAPI 动态', color: 'text-pink-300', bg: 'bg-pink-500/10' },
  workflow: { label: '工作流包装', color: 'text-indigo-300', bg: 'bg-indigo-500/10' },
  unknown: { label: '未知', color: 'text-gray-400', bg: 'bg-gray-500/10' },
}

function getSourceMeta(source) {
  return SOURCE_META[source] || SOURCE_META.unknown
}

// ============================================================================
// 配置读写辅助
// ============================================================================
function getTSConfig(value) {
  const raw = value?.tool_search
  if (!raw || typeof raw !== 'object') return { ...TS_DEFAULTS }
  return {
    enabled: raw.enabled ?? TS_DEFAULTS.enabled,
    threshold_pct: raw.threshold_pct ?? TS_DEFAULTS.threshold_pct,
    search_default_limit: raw.search_default_limit ?? TS_DEFAULTS.search_default_limit,
    max_search_limit: raw.max_search_limit ?? TS_DEFAULTS.max_search_limit,
  }
}

function updateTSConfig(value, patch) {
  const cur = getTSConfig(value)
  return { ...(value || {}), tool_search: { ...cur, ...patch } }
}

// ============================================================================
// 主组件
// ============================================================================
export default function ToolSearchStatus({ agentId, value, onChange }) {
  const cfg = getTSConfig(value)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const fetchStatus = useCallback(async () => {
    if (!agentId) {
      setStatus(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await agentsApi.toolSearchStatus(agentId)
      setStatus(data)
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [agentId])

  // 首次加载 + agentId 变化时拉取
  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  const supported = status?.supported !== false
  const stats = status?.stats || {}
  const classification = status?.classification || {}
  const visibleBySource = classification.visible_by_source || {}
  const deferrableBySource = classification.deferrable_by_source || {}

  return (
    <div className="flex flex-col gap-4">
      {/* ────────────── 配置编辑区 ────────────── */}
      <Section
        title="tool_search 配置"
        hint="渐进式工具披露：可延迟工具（DB code/http、OpenAPI、工作流）按需检索，节省上下文"
      >
        <SelectInput
          label="模式（enabled）"
          value={cfg.enabled}
          onChange={(v) => onChange(updateTSConfig(value, { enabled: v }))}
          options={MODE_OPTIONS}
          hint="auto=按阈值门控；on=强制激活（有可延迟工具就替换为桥接工具）；off=禁用"
        />

        <div className="grid grid-cols-3 gap-2">
          <NumberInput
            label="激活阈值（%）"
            value={cfg.threshold_pct}
            onChange={(v) => onChange(updateTSConfig(value, { threshold_pct: v }))}
            min={0}
            max={100}
            step={1}
            hint="可延迟工具 token ≥ 上下文窗口 × 此阈值时激活（仅 auto 模式）"
          />
          <NumberInput
            label="默认返回数"
            value={cfg.search_default_limit}
            onChange={(v) => onChange(updateTSConfig(value, { search_default_limit: v }))}
            min={1}
            max={cfg.max_search_limit}
            hint="tool_search 默认返回的工具数"
          />
          <NumberInput
            label="最大返回数"
            value={cfg.max_search_limit}
            onChange={(v) => onChange(updateTSConfig(value, { max_search_limit: v }))}
            min={1}
            max={50}
            hint="tool_search 单次最多返回数"
          />
        </div>

        <div className="rounded-md border border-gray-800 bg-gray-800/20 p-2 text-[11px] leading-relaxed text-gray-500">
          <span className="text-gray-400">桥接工具：</span>
          <span className="ml-1 font-mono text-gray-400">tool_search</span>（BM25 检索）/
          <span className="font-mono text-gray-400"> tool_describe</span>（详情）/
          <span className="font-mono text-gray-400"> tool_call</span>（执行）——
          激活后替代可延迟工具出现在模型可见数组
        </div>
      </Section>

      {/* ────────────── 装配预览区（只读） ────────────── */}
      <Section
        title="装配预览"
        hint="基于当前 agent 启用的工具实时计算（需保存后刷新）"
      >
        {!agentId && (
          <div className="rounded-md border border-amber-700/40 bg-amber-900/10 p-2 text-[11px] text-amber-300">
            ⚠ 新建智能体尚未保存，无法获取工具分类预览。请先保存后再查看装配状态。
          </div>
        )}

        {agentId && (
          <>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={fetchStatus}
                disabled={loading}
                className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-[11px] text-gray-300 hover:bg-gray-700 disabled:opacity-50"
              >
                {loading ? '刷新中…' : '↻ 刷新预览'}
              </button>
              {error && (
                <span className="text-[11px] text-red-400">加载失败: {error}</span>
              )}
            </div>

            {!supported && (
              <div className="rounded-md border border-gray-700 bg-gray-800/30 p-2 text-[11px] text-gray-400">
                {status?.message || '当前引擎不支持 tool_search'}
              </div>
            )}

            {supported && loading && !status && (
              <div className="rounded-md border border-gray-700 bg-gray-800/30 p-3 text-center text-[11px] text-gray-400">
                正在加载工具分类数据…
              </div>
            )}

            {supported && status && (
              <div className="flex flex-col gap-3">
                {/* 统计卡片 */}
                <div className="grid grid-cols-4 gap-2">
                  <StatCard
                    label="核心工具"
                    value={stats.visible_count ?? 0}
                    suffix="个"
                    sub={`${stats.visible_tokens ?? 0} token`}
                    color="emerald"
                  />
                  <StatCard
                    label="可延迟工具"
                    value={stats.deferrable_count ?? 0}
                    suffix="个"
                    sub={`${stats.deferrable_tokens ?? 0} token`}
                    color="orange"
                  />
                  <StatCard
                    label="激活阈值"
                    value={stats.threshold_pct ?? cfg.threshold_pct}
                    suffix="%"
                    sub={
                      stats.threshold_tokens
                        ? `${stats.threshold_tokens} token`
                        : '上下文未知'
                    }
                    color="blue"
                  />
                  <StatCard
                    label="当前模式"
                    value={cfg.enabled}
                    suffix=""
                    sub={
                      stats.would_activate === true
                        ? '✓ 会激活'
                        : stats.would_activate === false
                        ? '✗ 不激活'
                        : '运行时确定'
                    }
                    color={
                      stats.would_activate === true
                        ? 'emerald'
                        : stats.would_activate === false
                        ? 'gray'
                        : 'amber'
                    }
                  />
                </div>

                {/* 核心工具列表（按 source 分组） */}
                <div>
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-300">
                      核心工具（永不延迟）
                    </span>
                    <span className="text-[10px] text-gray-500">
                      {stats.visible_count ?? 0} 个 · {stats.visible_tokens ?? 0} token
                    </span>
                  </div>
                  {Object.keys(visibleBySource).length === 0 ? (
                    <EmptyHint text="无核心工具" />
                  ) : (
                    <div className="flex flex-col gap-1.5">
                      {Object.entries(visibleBySource).map(([src, group]) => (
                        <SourceGroup key={src} source={src} group={group} />
                      ))}
                    </div>
                  )}
                </div>

                {/* 可延迟工具列表（按 source 分组） */}
                <div>
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-orange-300">
                      可延迟工具（进入目录，按需检索）
                    </span>
                    <span className="text-[10px] text-gray-500">
                      {stats.deferrable_count ?? 0} 个 · {stats.deferrable_tokens ?? 0} token
                    </span>
                  </div>
                  {Object.keys(deferrableBySource).length === 0 ? (
                    <EmptyHint text="无可延迟工具（所有工具都常驻可见）" />
                  ) : (
                    <div className="flex flex-col gap-1.5">
                      {Object.entries(deferrableBySource).map(([src, group]) => (
                        <SourceGroup key={src} source={src} group={group} />
                      ))}
                    </div>
                  )}
                </div>

                {/* source 分类目录 */}
                <div className="rounded-md border border-gray-800 bg-gray-900/40 p-2 text-[10px] text-gray-500">
                  <div className="mb-1 text-gray-400">source 分类规则：</div>
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                    <span>
                      <span className="text-emerald-400">核心</span> ={' '}
                      {(status.source_catalog?.core_sources || []).join(', ')}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                    <span>
                      <span className="text-orange-400">可延迟</span> ={' '}
                      {(status.source_catalog?.deferrable_sources || []).join(', ')}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </Section>
    </div>
  )
}

// ============================================================================
// 子组件：统计卡片
// ============================================================================
function StatCard({ label, value, suffix, sub, color }) {
  const colorMap = {
    emerald: 'border-emerald-700/40 bg-emerald-900/10 text-emerald-300',
    orange: 'border-orange-700/40 bg-orange-900/10 text-orange-300',
    blue: 'border-blue-700/40 bg-blue-900/10 text-blue-300',
    amber: 'border-amber-700/40 bg-amber-900/10 text-amber-300',
    gray: 'border-gray-700 bg-gray-800/30 text-gray-300',
  }
  return (
    <div className={`rounded-md border p-2 ${colorMap[color] || colorMap.gray}`}>
      <div className="text-[10px] font-medium uppercase tracking-wider opacity-80">
        {label}
      </div>
      <div className="mt-0.5 text-base font-semibold">
        {value}
        <span className="ml-0.5 text-[10px] opacity-70">{suffix}</span>
      </div>
      <div className="text-[10px] opacity-60">{sub}</div>
    </div>
  )
}

// ============================================================================
// 子组件：source 分组
// ============================================================================
function SourceGroup({ source, group }) {
  const meta = getSourceMeta(source)
  return (
    <div className={`rounded-md border border-gray-800 p-2 ${meta.bg}`}>
      <div className="mb-1 flex items-center gap-2">
        <span className={`text-[10px] font-semibold ${meta.color}`}>
          {meta.label}
        </span>
        <span className="rounded bg-gray-700/40 px-1 py-0.5 text-[9px] text-gray-400">
          {source}
        </span>
        <span className="text-[10px] text-gray-500">
          {group.count} 个 · {group.tokens} token
        </span>
      </div>
      <div className="flex flex-wrap gap-1">
        {group.tools.map((t) => (
          <span
            key={t.name}
            title={t.description || t.name}
            className="rounded bg-gray-900/60 px-1.5 py-0.5 font-mono text-[10px] text-gray-300"
          >
            {t.name}
            <span className="ml-1 text-gray-500">{t.tokens}t</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function EmptyHint({ text }) {
  return (
    <div className="rounded-md border border-dashed border-gray-800 p-2 text-center text-[10px] text-gray-600">
      {text}
    </div>
  )
}
