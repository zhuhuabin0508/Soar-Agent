import { useEffect, useState, useCallback, useMemo } from 'react'
import { skills as skillsApi } from '../api/client'
import { Modal } from '../components/Dialog'
import { inputCls, textareaCls, labelCls, hintCls } from '../components/property/FormControls'
import { hasPermission } from '../utils/permissions'
import { TutorialButton, TutorialDrawer } from '../components/TutorialDrawer'
import { SKILL_TUTORIAL } from '../components/tutorialContent'

// 预设分类（与文档约定一致）
const CATEGORIES = ['处置流程', '角色设定', '领域规则', 'SOP', '其他']

// 分类徽章配色
const CATEGORY_STYLES = {
  处置流程: 'border border-brand-500/40 bg-brand-500/10 text-brand-300',
  角色设定: 'border border-purple-500/40 bg-purple-500/10 text-purple-300',
  领域规则: 'border border-blue-500/40 bg-blue-500/10 text-blue-300',
  SOP: 'border border-amber-500/40 bg-amber-500/10 text-amber-300',
  其他: 'border border-gray-700 bg-gray-800 text-gray-400',
}

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 空表单模板
const EMPTY_FORM = {
  name: '',
  description: '',
  content: '',
  category: '处置流程',
  tags: [],
  enabled: true,
  priority: 0,
}

// 技能编辑/新建弹窗
function SkillFormModal({ open, initial, onClose, onSubmit, saving }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [tagsText, setTagsText] = useState('')
  const [err, setErr] = useState('')

  // 弹窗每次打开时用 initial 重置表单
  useEffect(() => {
    if (open) {
      const src = initial || EMPTY_FORM
      setForm({
        name: src.name || '',
        description: src.description || '',
        content: src.content || '',
        category: src.category || '处置流程',
        tags: Array.isArray(src.tags) ? src.tags : [],
        enabled: src.enabled !== false,
        priority: src.priority ?? 0,
      })
      setTagsText(Array.isArray(src.tags) ? src.tags.join(', ') : '')
      setErr('')
    }
  }, [open, initial])

  const setField = (field) => (value) => setForm((prev) => ({ ...prev, [field]: value }))

  const handleSubmit = () => {
    if (!form.name.trim()) {
      setErr('请填写技能名称')
      return
    }
    if (!form.content.trim()) {
      setErr('请填写技能正文')
      return
    }
    // tags 文本按逗号拆分
    const tags = tagsText
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    onSubmit({ ...form, tags })
  }

  return (
    <Modal
      open={open}
      title={initial ? `编辑技能：${initial.name || ''}` : '新建技能'}
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saving}
            className="btn-primary"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {err && (
          <div className="rounded-md border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-xs text-danger-300">
            {err}
          </div>
        )}
        {/* 名称 + 分类 */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>技能名称 *</label>
            <input
              className={inputCls}
              value={form.name}
              onChange={(e) => setField('name')(e.target.value)}
              placeholder="如：告警研判SOP"
            />
          </div>
          <div>
            <label className={labelCls}>分类</label>
            <select
              className={inputCls}
              value={form.category}
              onChange={(e) => setField('category')(e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* 摘要 */}
        <div>
          <label className={labelCls}>简短摘要（列表展示用）</label>
          <input
            className={inputCls}
            value={form.description}
            onChange={(e) => setField('description')(e.target.value)}
            placeholder="一句话说明这个技能做什么"
          />
        </div>

        {/* 标签 */}
        <div>
          <label className={labelCls}>标签（逗号分隔）</label>
          <input
            className={inputCls}
            value={tagsText}
            onChange={(e) => setTagsText(e.target.value)}
            placeholder="如：告警, SOC, 一级响应"
          />
        </div>

        {/* 正文 */}
        <div>
          <label className={labelCls}>技能正文 *（注入到 Agent system prompt）</label>
          <textarea
            className={textareaCls}
            rows={12}
            value={form.content}
            onChange={(e) => setField('content')(e.target.value)}
            placeholder={
              '用自然语言描述处置流程 / 角色设定 / 领域规则 / SOP。\n\n' +
              '示例：\n' +
              '你是 {{role}} 专家。当收到告警时：\n' +
              '1. 先核对告警源 IP 是否在白名单；\n' +
              '2. 调用 get_threat_intel 查询威胁情报；\n' +
              '3. 若为恶意，封禁 24h 并通知值班人员。'
            }
            spellCheck={false}
          />
          <p className={hintCls}>
            💡 可用 <code className="rounded bg-gray-800 px-1 text-brand-300">{'{{key}}'}</code> 引用智能体变量（在智能体编辑页「变量」处配置）。
            启用后会被注入到智能体的 system prompt，持续塑造 AI 行为。
          </p>
        </div>

        {/* 优先级 + 启用 */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>优先级（越大越靠前）</label>
            <input
              type="number"
              className={inputCls}
              value={form.priority}
              onChange={(e) => setField('priority')(Number(e.target.value))}
            />
          </div>
          <div>
            <label className={labelCls}>启用状态</label>
            <select
              className={inputCls}
              value={form.enabled ? 'true' : 'false'}
              onChange={(e) => setField('enabled')(e.target.value === 'true')}
            >
              <option value="true">启用</option>
              <option value="false">禁用</option>
            </select>
          </div>
        </div>
      </div>
    </Modal>
  )
}

// 技能列表页
function SkillList() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 搜索与筛选
  const [keyword, setKeyword] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')

  // 弹窗
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null) // null=新建, 对象=编辑
  const [saving, setSaving] = useState(false)
  const [togglingId, setTogglingId] = useState(null)
  const [tutorialOpen, setTutorialOpen] = useState(false)

  const canEdit = hasPermission('skill', 'edit')
  const canDelete = hasPermission('skill', 'delete')

  const load = useCallback(async () => {
    try {
      const data = await skillsApi.list()
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

  // 前端搜索 + 分类过滤（数据量小，本地过滤即可）
  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return rows.filter((r) => {
      if (categoryFilter && r.category !== categoryFilter) return false
      if (!kw) return true
      const hay = `${r.name || ''} ${r.description || ''} ${(r.tags || []).join(' ')}`.toLowerCase()
      return hay.includes(kw)
    })
  }, [rows, keyword, categoryFilter])

  const openCreate = () => {
    setEditing(null)
    setModalOpen(true)
  }

  const openEdit = (skill) => {
    setEditing(skill)
    setModalOpen(true)
  }

  const handleSubmit = async (body) => {
    setSaving(true)
    try {
      if (editing) {
        const updated = await skillsApi.update(editing.id, body)
        setRows((prev) => prev.map((r) => (r.id === editing.id ? updated : r)))
      } else {
        const created = await skillsApi.create(body)
        setRows((prev) => [created, ...prev])
      }
      setModalOpen(false)
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id, name) => {
    if (!window.confirm(`确定删除技能「${name || id}」吗？\n引用该技能的智能体下次组装提示词时将自动移除该技能段。`))
      return
    try {
      await skillsApi.remove(id)
      setRows((prev) => prev.filter((r) => r.id !== id))
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  // 切换启用状态（即时生效：禁用后下次 Agent 组装 prompt 立即移除）
  const handleToggleEnabled = async (skill) => {
    setTogglingId(skill.id)
    try {
      const updated = await skillsApi.update(skill.id, { ...skill, enabled: !skill.enabled })
      setRows((prev) => prev.map((r) => (r.id === skill.id ? updated : r)))
    } catch (err) {
      window.alert(`切换状态失败：${err.message || err}`)
    } finally {
      setTogglingId(null)
    }
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-100">技能</h1>
          <span className="text-xs text-gray-500">共 {rows.length} 个</span>
          <span className="hidden text-xs text-gray-600 sm:inline">
            纯文本指令，注入智能体 system prompt
          </span>
        </div>
        <div className="flex items-center gap-2">
          <TutorialButton onClick={() => setTutorialOpen(true)} />
          <button type="button" onClick={load} className="btn-secondary btn-sm">
            刷新
          </button>
          {canEdit && (
            <button type="button" onClick={openCreate} className="btn-primary btn-sm">
              + 新建技能
            </button>
          )}
        </div>
      </header>

      {/* 工具栏：搜索 + 分类筛选 */}
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-800 bg-gray-900/30 px-6 py-3">
        <input
          className={`${inputCls} max-w-xs`}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="搜索名称 / 摘要 / 标签"
        />
        <select
          className={`${inputCls} max-w-[180px]`}
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
        >
          <option value="">全部分类</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <span className="text-xs text-gray-500">显示 {filtered.length} / {rows.length}</span>
      </div>

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
        ) : filtered.length === 0 ? (
          <div className="flex h-60 flex-col items-center justify-center gap-2 text-gray-500">
            <div className="text-4xl">🎯</div>
            <div className="text-sm">
              {rows.length === 0 ? '暂无技能，点击「新建技能」创建一个纯文本指令' : '无匹配结果'}
            </div>
          </div>
        ) : (
          <div className="w-full overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full table-fixed border-collapse text-sm">
              <thead className="bg-gray-900 text-gray-400">
                <tr>
                  <th className="w-16 px-4 py-3 text-left font-medium">ID</th>
                  <th className="w-48 px-4 py-3 text-left font-medium">名称</th>
                  <th className="px-4 py-3 text-left font-medium">摘要</th>
                  <th className="w-24 px-4 py-3 text-left font-medium">分类</th>
                  <th className="w-16 px-4 py-3 text-left font-medium">优先级</th>
                  <th className="w-24 px-4 py-3 text-left font-medium">启用</th>
                  <th className="w-44 px-4 py-3 text-left font-medium">更新时间</th>
                  <th className="w-40 px-4 py-3 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, idx) => (
                  <tr
                    key={r.id}
                    className={`border-t border-gray-800 transition-colors hover:bg-brand-500/5 ${
                      idx % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-900/20'
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-brand-300">#{r.id}</td>
                    <td className="truncate px-4 py-3 text-gray-200" title={r.name}>
                      {r.name || '-'}
                    </td>
                    <td className="truncate px-4 py-3 text-gray-400" title={r.description || ''}>
                      {r.description || '-'}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                          CATEGORY_STYLES[r.category] || CATEGORY_STYLES['其他']
                        }`}
                      >
                        {r.category || '未分类'}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-gray-400">{r.priority ?? 0}</td>
                    <td className="px-4 py-3">
                      {canEdit ? (
                        <button
                          type="button"
                          disabled={togglingId === r.id}
                          onClick={() => handleToggleEnabled(r)}
                          className={`rounded px-2 py-0.5 text-[11px] font-medium transition ${
                            r.enabled
                              ? 'bg-success-500/20 text-success-300 hover:bg-success-500/30'
                              : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                          } ${togglingId === r.id ? 'opacity-50' : ''}`}
                          title={r.enabled ? '点击禁用（即时从 Agent prompt 移除）' : '点击启用'}
                        >
                          {togglingId === r.id ? '…' : r.enabled ? '启用' : '禁用'}
                        </button>
                      ) : (
                        <span
                          className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                            r.enabled
                              ? 'bg-success-500/20 text-success-300'
                              : 'bg-gray-700 text-gray-400'
                          }`}
                        >
                          {r.enabled ? '启用' : '禁用'}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-400">{fmtTime(r.updated_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        {canEdit && (
                          <button
                            type="button"
                            onClick={() => openEdit(r)}
                            className="btn-secondary btn-sm"
                          >
                            编辑
                          </button>
                        )}
                        {canDelete && (
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
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <SkillFormModal
        open={modalOpen}
        initial={editing}
        onClose={() => setModalOpen(false)}
        onSubmit={handleSubmit}
        saving={saving}
      />

      {/* 使用教程 */}
      <TutorialDrawer
        open={tutorialOpen}
        onClose={() => setTutorialOpen(false)}
        title="技能管理使用教程"
        subtitle="了解如何创建技能并关联工作流"
        sections={SKILL_TUTORIAL}
      />
    </div>
  )
}

export default SkillList
