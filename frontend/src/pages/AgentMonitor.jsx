import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { agents as agentsApi } from '../api/client'
import { Modal } from '../components/Dialog'

function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

function fmtDuration(ms) {
  if (!ms || ms <= 0) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// 状态徽章
function StatusBadge({ status }) {
  const map = {
    success: { cls: 'bg-success-500/20 text-success-300', label: '成功' },
    failed: { cls: 'bg-danger-500/20 text-danger-300', label: '失败' },
    running: { cls: 'bg-brand-500/20 text-brand-300', label: '运行中' },
    pending: { cls: 'bg-gray-700 text-gray-400', label: '等待中' },
  }
  const m = map[status] || { cls: 'bg-gray-700 text-gray-400', label: status }
  return (
    <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${m.cls}`}>
      {m.label}
    </span>
  )
}

// 统计卡片
function StatCard({ label, value, sub, color = 'text-gray-100' }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${color}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-gray-600">{sub}</div>}
    </div>
  )
}

// 简易柱状图（最近7天执行趋势）
function TrendChart({ data }) {
  if (!data || data.length === 0) return null
  const maxCount = Math.max(...data.map((d) => d.count), 1)
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
        最近 7 天执行趋势
      </div>
      <div className="flex items-end justify-between gap-2" style={{ height: '120px' }}>
        {data.map((d, idx) => (
          <div key={idx} className="flex flex-1 flex-col items-center gap-1">
            <div className="text-[10px] text-gray-500">{d.count}</div>
            <div
              className="w-full rounded-t bg-brand-500/60 transition-all hover:bg-brand-400"
              style={{
                height: `${(d.count / maxCount) * 80 + 4}px`,
                minHeight: '4px',
              }}
              title={`${d.date}: ${d.count} 次`}
            />
            <div className="text-[10px] text-gray-500">{d.date}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// 工具调用详情卡片
function ToolCallCard({ tc, idx }) {
  const [expanded, setExpanded] = useState(false)
  const resultStr = typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)
  const argsStr = tc.args ? (typeof tc.args === 'string' ? tc.args : JSON.stringify(tc.args, null, 2)) : ''
  const isLong = (resultStr || '').length > 200

  return (
    <div className="rounded-md border border-gray-800 bg-gray-900/60 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="rounded bg-brand-500/15 px-1.5 py-0.5 text-[10px] font-mono text-brand-300">
            #{idx + 1}
          </span>
          <span className="text-sm font-medium text-gray-200">{tc.name}</span>
          {tc.status === 'done' && (
            <span className="rounded bg-success-500/15 px-1.5 py-0.5 text-[10px] text-success-300">
              完成
            </span>
          )}
          {tc.status === 'running' && (
            <span className="rounded bg-brand-500/15 px-1.5 py-0.5 text-[10px] text-brand-300">
              执行中
            </span>
          )}
        </div>
        {tc.duration_ms != null && (
          <span className="text-[11px] text-gray-500">{fmtDuration(tc.duration_ms)}</span>
        )}
      </div>

      {argsStr && (
        <div className="mt-2">
          <div className="text-[10px] text-gray-500">参数</div>
          <pre className="mt-1 max-h-24 overflow-auto rounded bg-gray-950 p-2 text-[11px] text-gray-400 ring-1 ring-gray-800">
            {argsStr}
          </pre>
        </div>
      )}

      {resultStr && (
        <div className="mt-2">
          <div className="flex items-center justify-between">
            <div className="text-[10px] text-gray-500">结果</div>
            {isLong && (
              <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                className="text-[10px] text-brand-300 hover:text-brand-200"
              >
                {expanded ? '收起' : '展开全部'}
              </button>
            )}
          </div>
          <pre
            className="mt-1 overflow-auto rounded bg-gray-950 p-2 text-[11px] text-gray-400 ring-1 ring-gray-800"
            style={{ maxHeight: expanded ? '400px' : '80px' }}
          >
            {resultStr}
          </pre>
        </div>
      )}
    </div>
  )
}

function AgentMonitor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [agent, setAgent] = useState(null)
  const [stats, setStats] = useState(null)
  const [executions, setExecutions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 执行详情弹窗
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailExec, setDetailExec] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [agentData, statsData, execData] = await Promise.all([
        agentsApi.get(id),
        agentsApi.monitor(id),
        agentsApi.executions(id, 50),
      ])
      setAgent(agentData)
      setStats(statsData)
      setExecutions(Array.isArray(execData) ? execData : [])
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => navigate('/agents')}
            className="text-sm text-gray-400 hover:text-gray-200"
          >
            ← 返回
          </button>
          <h1 className="text-xl font-semibold text-gray-100">
            智能体监控
            {agent && (
              <span className="ml-2 text-sm font-normal text-gray-400">
                {agent.name || `#${id}`}
              </span>
            )}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate(`/agents/${id}/edit`)}
            className="btn-secondary btn-sm"
          >
            编辑
          </button>
          <button type="button" onClick={load} className="btn-secondary btn-sm">
            刷新
          </button>
        </div>
      </header>

      {error && (
        <div className="m-4 rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-40 items-center justify-center text-sm text-gray-500">
          加载中...
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-6">
          {/* 智能体信息 */}
          {agent && (
            <div className="mb-4 rounded-lg border border-gray-800 bg-gray-900/40 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-md bg-brand-500/15 text-xl">
                  🤖
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-gray-100">
                    {agent.name}
                  </div>
                  <div className="truncate text-xs text-gray-500">
                    {agent.description || '无描述'}
                  </div>
                </div>
                <div className="flex gap-2 text-[11px] text-gray-500">
                  <span>模型配置 #{agent.model_config_id ?? '-'}</span>
                  <span>·</span>
                  <span>迭代上限 {agent.max_iterations ?? '-'}</span>
                </div>
              </div>
            </div>
          )}

          {/* 统计卡片 */}
          {stats && (
            <div className="mb-4 grid grid-cols-5 gap-3">
              <StatCard label="总执行次数" value={stats.total ?? 0} />
              <StatCard
                label="成功"
                value={stats.success ?? 0}
                color="text-success-400"
              />
              <StatCard
                label="失败"
                value={stats.failed ?? 0}
                color="text-danger-400"
              />
              <StatCard label="今日执行" value={stats.today ?? 0} />
              <StatCard
                label="平均耗时"
                value={fmtDuration(stats.avg_duration_ms)}
              />
            </div>
          )}

          {/* 趋势图 */}
          {stats && <TrendChart data={stats.recent_7d} />}

          {/* 执行历史 */}
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                执行历史（{executions.length} 条）
              </h2>
            </div>
            {executions.length === 0 ? (
              <div className="flex h-32 items-center justify-center text-sm text-gray-600">
                暂无执行记录，点击列表页「测试」按钮执行智能体后将在此显示
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-gray-800">
                <table className="w-full table-fixed border-collapse text-sm">
                  <thead className="bg-gray-900 text-gray-400">
                    <tr>
                      <th className="w-16 px-3 py-2 text-left font-medium">ID</th>
                      <th className="w-24 px-3 py-2 text-left font-medium">状态</th>
                      <th className="w-32 px-3 py-2 text-left font-medium">模型</th>
                      <th className="w-20 px-3 py-2 text-left font-medium">迭代</th>
                      <th className="w-24 px-3 py-2 text-left font-medium">Token</th>
                      <th className="w-28 px-3 py-2 text-left font-medium">工具调用</th>
                      <th className="w-40 px-3 py-2 text-left font-medium">执行时间</th>
                      <th className="w-20 px-3 py-2 text-left font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {executions.map((e, idx) => {
                      const r = e.result || {}
                      const model = r.model || {}
                      const tokens = r.token_usage || {}
                      const tools = r.tool_calls || []
                      return (
                        <tr
                          key={e.id}
                          className={`cursor-pointer border-t border-gray-800 transition-colors hover:bg-brand-500/5 ${
                            idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
                          }`}
                          onClick={() => {
                            setDetailExec(e)
                            setDetailOpen(true)
                          }}
                        >
                          <td className="px-3 py-2 font-mono text-brand-300">
                            #{e.id}
                          </td>
                          <td className="px-3 py-2">
                            <StatusBadge status={e.status} />
                          </td>
                          <td className="truncate px-3 py-2 text-xs text-gray-400" title={model.name}>
                            {model.name || '-'}
                          </td>
                          <td className="px-3 py-2 text-xs text-gray-400">
                            {r.iterations ?? '-'}
                          </td>
                          <td className="px-3 py-2 text-xs text-gray-400">
                            {tokens.total_tokens ? tokens.total_tokens.toLocaleString() : '-'}
                          </td>
                          <td className="px-3 py-2">
                            {tools.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {tools.slice(0, 3).map((t, i) => (
                                  <span
                                    key={i}
                                    className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400"
                                  >
                                    {t.name}
                                  </span>
                                ))}
                                {tools.length > 3 && (
                                  <span className="text-[10px] text-gray-500">
                                    +{tools.length - 3}
                                  </span>
                                )}
                              </div>
                            ) : (
                              <span className="text-xs text-gray-600">-</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-xs text-gray-500">
                            {fmtTime(e.created_at)}
                          </td>
                          <td className="px-3 py-2">
                            <button
                              type="button"
                              onClick={(ev) => {
                                ev.stopPropagation()
                                setDetailExec(e)
                                setDetailOpen(true)
                              }}
                              className="text-xs text-brand-300 hover:text-brand-200"
                            >
                              详情
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 执行详情弹窗 */}
      <Modal
        open={detailOpen}
        title={detailExec ? `执行详情 #${detailExec.id}` : '执行详情'}
        onClose={() => setDetailOpen(false)}
        maxWidth="max-w-4xl"
        footer={
          <button
            type="button"
            onClick={() => setDetailOpen(false)}
            className="btn-primary"
          >
            关闭
          </button>
        }
      >
        {detailExec && (() => {
          const r = detailExec.result || {}
          const model = r.model || {}
          const tokens = r.token_usage || {}
          const tools = r.tool_calls || []
          return (
            <div className="flex flex-col gap-4">
              {/* 基本信息 */}
              <div className="grid grid-cols-4 gap-3">
                <div className="rounded-md border border-gray-800 bg-gray-900/60 p-3">
                  <div className="text-xs text-gray-500">状态</div>
                  <div className="mt-1">
                    <StatusBadge status={detailExec.status} />
                  </div>
                </div>
                <div className="rounded-md border border-gray-800 bg-gray-900/60 p-3">
                  <div className="text-xs text-gray-500">模型</div>
                  <div className="mt-1 truncate text-sm text-gray-200" title={model.name}>
                    {model.name || '-'}
                  </div>
                  <div className="text-[10px] text-gray-600">{model.provider || ''}</div>
                </div>
                <div className="rounded-md border border-gray-800 bg-gray-900/60 p-3">
                  <div className="text-xs text-gray-500">迭代次数</div>
                  <div className="mt-1 text-sm font-mono text-brand-300">
                    {r.iterations ?? '-'}
                  </div>
                </div>
                <div className="rounded-md border border-gray-800 bg-gray-900/60 p-3">
                  <div className="text-xs text-gray-500">Token 消耗</div>
                  <div className="mt-1 text-sm font-mono text-gray-200">
                    {tokens.total_tokens ? tokens.total_tokens.toLocaleString() : '-'}
                  </div>
                  {tokens.input_tokens != null && (
                    <div className="text-[10px] text-gray-600">
                      输入 {tokens.input_tokens?.toLocaleString()} · 输出 {tokens.output_tokens?.toLocaleString()}
                    </div>
                  )}
                </div>
              </div>

              {/* 执行时间 */}
              <div>
                <div className="mb-1 text-xs text-gray-500">执行时间</div>
                <div className="text-sm text-gray-300">
                  {fmtTime(detailExec.created_at)}
                  {detailExec.finished_at &&
                    ` → ${fmtTime(detailExec.finished_at)}`}
                </div>
              </div>

              {/* 思维链信息 */}
              {r.thinking_chars > 0 && (
                <div className="rounded-md border border-gray-800 bg-gray-900/60 p-3">
                  <div className="text-xs text-gray-500">思维链长度</div>
                  <div className="mt-1 text-sm text-gray-300">
                    {r.thinking_chars.toLocaleString()} 字符
                  </div>
                </div>
              )}

              {/* 用户输入 */}
              {r.input && (
                <div>
                  <div className="mb-1 text-xs text-gray-500">用户输入</div>
                  <pre className="max-h-32 w-full overflow-auto rounded-md bg-gray-950 p-3 font-mono text-xs text-gray-400 ring-1 ring-gray-800">
                    {typeof r.input === 'string' ? r.input : JSON.stringify(r.input, null, 2)}
                  </pre>
                </div>
              )}

              {/* 工具调用详情 */}
              {tools.length > 0 && (
                <div>
                  <div className="mb-2 text-xs font-semibold text-gray-400">
                    工具调用（{tools.length} 次）
                  </div>
                  <div className="flex flex-col gap-2">
                    {tools.map((tc, i) => (
                      <ToolCallCard key={i} tc={tc} idx={i} />
                    ))}
                  </div>
                </div>
              )}

              {/* AI 回复 */}
              {r.reply && (
                <div>
                  <div className="mb-1 text-xs text-gray-500">AI 回复</div>
                  <pre className="max-h-60 w-full overflow-auto rounded-md bg-gray-950 p-3 text-xs text-gray-300 ring-1 ring-gray-800 whitespace-pre-wrap">
                    {r.reply}
                  </pre>
                </div>
              )}

              {/* 错误信息 */}
              {r.error && (
                <div>
                  <div className="mb-1 text-xs text-danger-400">错误信息</div>
                  <pre className="w-full overflow-auto rounded-md border border-danger-500/40 bg-danger-500/5 p-3 text-xs text-danger-300">
                    {r.error}
                  </pre>
                </div>
              )}
            </div>
          )
        })()}
      </Modal>
    </div>
  )
}

export default AgentMonitor
