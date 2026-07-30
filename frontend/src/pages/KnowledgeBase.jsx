import { useEffect, useState, useCallback, useMemo } from 'react'
import { knowledgeBases as kbApi, llmConfigs as llmApi } from '../api/client'
import { Modal } from '../components/Dialog'
import { inputCls, textareaCls } from '../components/property/FormControls'
import { TutorialButton, TutorialDrawer } from '../components/TutorialDrawer'
import { KNOWLEDGE_BASE_TUTORIAL } from '../components/tutorialContent'

// 格式化时间
function fmtTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

// 根据文件扩展名映射徽章图标与标签
function fileBadge(fileType) {
  const ft = (fileType || '').toLowerCase().replace(/^\./, '')
  const map = {
    pdf: { icon: '📄', label: 'PDF' },
    txt: { icon: '📝', label: 'TXT' },
    md: { icon: '📝', label: 'MD' },
    csv: { icon: '📊', label: 'CSV' },
    xls: { icon: '📊', label: 'XLS' },
    xlsx: { icon: '📊', label: 'XLSX' },
    doc: { icon: '📄', label: 'DOC' },
    docx: { icon: '📄', label: 'DOCX' },
    json: { icon: '🔧', label: 'JSON' },
    html: { icon: '🌐', label: 'HTML' },
    htm: { icon: '🌐', label: 'HTML' },
  }
  return map[ft] || { icon: '📄', label: (ft || 'FILE').toUpperCase() }
}

// 分段模式选项（5种，对标 Dify）
const CHUNK_MODES = [
  { value: 'auto', label: '自动解析', hint: '系统自动根据段落、标点切分，自动识别 IP 列表/日志等结构化数据按行切分' },
  { value: 'line', label: '按行切分', hint: '每行或每N行一段，适合 IP 列表、日志、CSV 表格等行级数据' },
  { value: 'fixed_length', label: '按固定长度切分', hint: '设置每个块的最大字符数，如 500' },
  { value: 'delimiter', label: '按分隔符切分', hint: '自定义分隔符（如 \\n\\n、---），适合结构化文档' },
  { value: 'qa', label: 'Q&A 模式提取', hint: '自动识别问题和答案分别切块，适合 FAQ 文档' },
]

// 索引模式选项
const INDEX_MODES = [
  { value: 'keyword', label: '关键词检索', hint: '纯 BM25，适合代码、编号、专有名词' },
  { value: 'vector', label: '向量检索', hint: '纯 Embedding，自然语言语义理解' },
  { value: 'hybrid', label: '混合检索（推荐）', hint: '既懂语义，又抓关键词，精准度最高' },
]

// Embedding 模型选项（标注特长）—— 仅用于维度参考，知识库实际从模型设置中选择已配置的嵌入模型
const EMBEDDING_MODELS = [
  { value: 'text-embedding-ada-002', label: 'OpenAI ada-002', specialty: '通用', dim: 1536, hint: 'OpenAI 经典模型，英文/多语言通用' },
  { value: 'text-embedding-3-small', label: 'OpenAI 3-small', specialty: '通用·轻量', dim: 1536, hint: '性价比高，支持动态降维' },
  { value: 'text-embedding-3-large', label: 'OpenAI 3-large', specialty: '高精度', dim: 3072, hint: '精度最高，支持动态降维到 256/768/1536' },
  { value: 'bge-large-zh', label: 'BAAI bge-large-zh', specialty: '中文', dim: 1024, hint: '中文语义检索效果最佳' },
  { value: 'bge-m3', label: 'BAAI bge-m3', specialty: '多语言', dim: 1024, hint: '支持 100+ 语言，跨语言检索强' },
  { value: 'm3e-base', label: 'm3e-base', specialty: '中文·开源', dim: 768, hint: '开源中文模型，适合本地部署' },
  { value: 'embedding-2', label: '智谱 embedding-2', specialty: '中文', dim: 1024, hint: '智谱国产模型，中文效果好' },
  { value: 'volcengine-doubao-embedding', label: '火山引擎 Doubao Embedding', specialty: '中文', dim: 2048, hint: '火山引擎国产模型' },
]

// 常见 Embedding 模型默认向量维度映射（选择嵌入配置时自动填充维度，未知模型默认 1024）
const EMBEDDING_DIM_BY_MODEL = EMBEDDING_MODELS.reduce((acc, m) => {
  acc[m.value] = m.dim
  return acc
}, {})

// Rerank 重排序模型选项
const RERANK_MODELS = [
  { value: 'bge-reranker-v2-m3', label: 'BAAI bge-reranker-v2-m3', hint: '多语言，业界主流重排序模型' },
  { value: 'bge-reranker-large', label: 'BAAI bge-reranker-large', hint: '中英双语，精度高' },
  { value: 'cohere-rerank-3', label: 'Cohere Rerank 3', hint: '商用 API，多语言支持' },
  { value: 'jina-reranker-v2', label: 'Jina jina-reranker-v2', hint: '开源，支持 8K 上下文' },
]

// 知识库编辑/新建弹窗（含 Dify 风格配置）
function KBFormModal({ open, initial, onClose, onSubmit, saving }) {
  // 嵌入模型配置列表（从模型设置中 model_type=embedding 的 LLM 配置拉取）
  const [embeddingConfigs, setEmbeddingConfigs] = useState([])
  const [loadingConfigs, setLoadingConfigs] = useState(false)

  const [form, setForm] = useState(() => ({
    name: '',
    description: '',
    chunk_mode: 'auto',
    chunk_size: 500,
    chunk_overlap: 50,
    chunk_delimiter: '\n\n',
    ocr_enabled: false,
    index_mode: 'hybrid',
    embedding_model: 'text-embedding-ada-002',
    embedding_config_id: null,
    embedding_dimension: 1536,
    retrieval_top_k: 5,
    score_threshold: 55,
    rerank_enabled: true,
    rerank_model: 'bge-reranker-v2-m3',
    hybrid_vector_weight: 70,
    hybrid_keyword_weight: 30,
    ...(initial || {}),
  }))

  // 弹窗打开时拉取嵌入模型配置列表
  useEffect(() => {
    if (!open) return
    setLoadingConfigs(true)
    llmApi.list()
      .then((data) => {
        const list = Array.isArray(data) ? data.filter((c) => (c.model_type || 'chat') === 'embedding') : []
        setEmbeddingConfigs(list)
      })
      .catch(() => setEmbeddingConfigs([]))
      .finally(() => setLoadingConfigs(false))
  }, [open])

  useEffect(() => {
    if (open) {
      setForm({
        name: '',
        description: '',
        chunk_mode: 'auto',
        chunk_size: 500,
        chunk_overlap: 50,
        chunk_delimiter: '\n\n',
        ocr_enabled: false,
        index_mode: 'hybrid',
        embedding_model: 'text-embedding-ada-002',
        embedding_config_id: null,
        embedding_dimension: 1536,
        retrieval_top_k: 5,
        score_threshold: 55,
        rerank_enabled: true,
        rerank_model: 'bge-reranker-v2-m3',
        hybrid_vector_weight: 70,
        hybrid_keyword_weight: 30,
        ...(initial || {}),
      })
    }
  }, [open, initial])

  const set = (k) => (v) => setForm((p) => ({ ...p, [k]: v }))
  const needEmbedding = form.index_mode === 'vector' || form.index_mode === 'hybrid'
  const isHybrid = form.index_mode === 'hybrid'
  // 当前选中的 Embedding 配置（从模型设置中选取）
  const selectedEmbCfg = embeddingConfigs.find((c) => c.id === form.embedding_config_id) || null
  const selectedChunkMode = CHUNK_MODES.find((m) => m.value === form.chunk_mode)
  const selectedIndex = INDEX_MODES.find((m) => m.value === form.index_mode)

  // 选择嵌入模型配置时：自动填充 model_name（兜底用）与维度
  const onEmbConfigChange = (configId) => {
    const cfg = embeddingConfigs.find((c) => c.id === Number(configId))
    setForm((p) => ({
      ...p,
      embedding_config_id: configId ? Number(configId) : null,
      embedding_model: cfg?.model_name || p.embedding_model,
      embedding_dimension: cfg ? (EMBEDDING_DIM_BY_MODEL[cfg.model_name] || 1024) : p.embedding_dimension,
    }))
  }

  // 混合检索权重联动（两者之和 = 100）
  const onVectorWeightChange = (val) => {
    const v = Math.max(0, Math.min(100, val))
    setForm((p) => ({ ...p, hybrid_vector_weight: v, hybrid_keyword_weight: 100 - v }))
  }

  return (
    <Modal
      open={open}
      title={initial ? `编辑知识库：${initial.name || ''}` : '新建知识库'}
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={() => onSubmit(form)}
            disabled={saving || !form.name}
            className="btn-primary"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </>
      }
    >
      <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto">
        {/* 基本信息 */}
        <div className="flex flex-col gap-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">基本信息</h3>
          <div className="grid grid-cols-2 gap-3">
            <label>
              <div className="mb-1 text-xs font-medium text-gray-400">名称 <span className="text-danger-400">*</span></div>
              <input className={inputCls} value={form.name} onChange={(e) => set('name')(e.target.value)} placeholder="知识库名称" />
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-gray-400">描述</div>
              <input className={inputCls} value={form.description} onChange={(e) => set('description')(e.target.value)} placeholder="可选" />
            </label>
          </div>
        </div>

        {/* ===== 分段设置 ===== */}
        <div className="flex flex-col gap-3 rounded-md border border-gray-800 bg-gray-900/40 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">分段设置（解析与切片）</h3>
          {/* 解析模式：卡片式单选 */}
          <div>
            <div className="mb-1.5 text-xs font-medium text-gray-400">解析模式 / 切片规则</div>
            <div className="grid grid-cols-2 gap-2">
              {CHUNK_MODES.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => set('chunk_mode')(m.value)}
                  className={`rounded-md border p-2 text-left transition ${
                    form.chunk_mode === m.value
                      ? 'border-brand-500 bg-brand-500/10'
                      : 'border-gray-700 bg-gray-800/40 hover:border-gray-600'
                  }`}
                >
                  <div className="text-xs font-semibold text-gray-200">{m.label}</div>
                  <div className="text-[10px] text-gray-500">{m.hint}</div>
                </button>
              ))}
            </div>
          </div>
          {selectedChunkMode && (
            <p className="text-[11px] text-gray-500">💡 {selectedChunkMode.hint}</p>
          )}

          {/* 分块大小 + 重叠度（非 auto 模式显示） */}
          {form.chunk_mode !== 'auto' && (
            <div className="grid grid-cols-2 gap-3">
              <label>
                <div className="mb-1 text-xs font-medium text-gray-400">
                  {form.chunk_mode === 'line' ? '每段行数' : '分块大小（字符）'}
                  <span className="text-gray-600">
                    {form.chunk_mode === 'line' ? ' 1=每行一段，建议 1-5' : ' 建议 300-1000'}
                  </span>
                </div>
                <input
                  type="number"
                  className={inputCls}
                  value={form.chunk_size}
                  onChange={(e) => set('chunk_size')(Number(e.target.value))}
                  min={form.chunk_mode === 'line' ? 1 : 100}
                  max={form.chunk_mode === 'line' ? 50 : 10000}
                />
              </label>
              <label>
                <div className="mb-1 text-xs font-medium text-gray-400">
                  {form.chunk_mode === 'line' ? '重叠行数' : '分块重叠度（字符）'}
                  <span className="text-gray-600">
                    {form.chunk_mode === 'line' ? ' 段间重叠的行数' : ' 建议块大小的 10%-20%'}
                  </span>
                </div>
                <input type="number" className={inputCls} value={form.chunk_overlap} onChange={(e) => set('chunk_overlap')(Number(e.target.value))} min={0} max={form.chunk_mode === 'line' ? 20 : 1000} />
              </label>
            </div>
          )}

          {/* 分隔符输入（delimiter 模式显示） */}
          {form.chunk_mode === 'delimiter' && (
            <label>
              <div className="mb-1 text-xs font-medium text-gray-400">自定义分隔符</div>
              <input className={inputCls} value={form.chunk_delimiter} onChange={(e) => set('chunk_delimiter')(e.target.value)} placeholder="如 \n\n、---、## 等" />
            </label>
          )}

          {/* OCR 开关 */}
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={form.ocr_enabled} onChange={(e) => set('ocr_enabled')(e.target.checked)} className="h-4 w-4 accent-brand-500" />
            <span className="text-sm text-gray-300">OCR 识别（针对扫描版 PDF / 图片提取文字）</span>
          </label>
        </div>

        {/* ===== 索引设置 ===== */}
        <div className="flex flex-col gap-3 rounded-md border border-gray-800 bg-gray-900/40 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">索引设置</h3>
          {/* 索引模式：卡片式单选 */}
          <div>
            <div className="mb-1.5 text-xs font-medium text-gray-400">检索策略</div>
            <div className="grid grid-cols-3 gap-2">
              {INDEX_MODES.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => set('index_mode')(m.value)}
                  className={`rounded-md border p-2 text-left transition ${
                    form.index_mode === m.value
                      ? 'border-brand-500 bg-brand-500/10'
                      : 'border-gray-700 bg-gray-800/40 hover:border-gray-600'
                  }`}
                >
                  <div className="text-xs font-semibold text-gray-200">{m.label}</div>
                  <div className="text-[10px] text-gray-500">{m.hint}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Embedding 模型选择（vector/hybrid 模式显示）—— 从模型设置中已配置的嵌入模型选取 */}
          {needEmbedding && (
            <>
              <label>
                <div className="mb-1 text-xs font-medium text-gray-400">
                  嵌入模型配置 <span className="text-danger-400">*</span>
                  <span className="ml-1 text-gray-600">（从「模型设置」中 model_type=embedding 的配置选取）</span>
                </div>
                <select
                  className={inputCls}
                  value={form.embedding_config_id || ''}
                  onChange={(e) => onEmbConfigChange(e.target.value)}
                  disabled={loadingConfigs}
                >
                  <option value="">{loadingConfigs ? '加载中…' : '请选择嵌入模型配置'}</option>
                  {embeddingConfigs.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}（{c.provider} · {c.model_name}）
                    </option>
                  ))}
                </select>
              </label>
              {embeddingConfigs.length === 0 && !loadingConfigs && (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
                  ⚠️ 未找到已配置的嵌入模型。请先到「模型设置」页面添加 model_type=<span className="font-mono">embedding</span> 的 LLM 配置（如火山引擎 Doubao Embedding、OpenAI text-embedding-3-small 等），并测试通过后再回到此处选择。
                </div>
              )}
              {selectedEmbCfg && (
                <div className="flex items-center gap-3 rounded-md border border-gray-800 bg-gray-800/30 px-3 py-2">
                  <span className="rounded bg-brand-600/20 px-2 py-0.5 text-[10px] font-semibold text-brand-300">
                    {selectedEmbCfg.provider}
                  </span>
                  <span className="truncate text-[11px] text-gray-400">
                    模型名：<span className="font-mono text-gray-300">{selectedEmbCfg.model_name || '-'}</span>
                  </span>
                  <span className="ml-auto text-[10px] text-gray-600">
                    Base URL: {selectedEmbCfg.base_url || '默认'}
                  </span>
                </div>
              )}
              <label>
                <div className="mb-1 text-xs font-medium text-gray-400">
                  向量维度 <span className="text-gray-600">（部分模型支持动态降维，降低可减少存储/检索成本）</span>
                </div>
                <div className="flex items-center gap-2">
                  <input type="number" className={inputCls} value={form.embedding_dimension} onChange={(e) => set('embedding_dimension')(Number(e.target.value))} min={256} max={8192} />
                  {selectedEmbCfg && form.embedding_dimension < (EMBEDDING_DIM_BY_MODEL[selectedEmbCfg.model_name] || 1024) && (
                    <span className="shrink-0 rounded bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-300">
                      已降维 {EMBEDDING_DIM_BY_MODEL[selectedEmbCfg.model_name] || 1024} → {form.embedding_dimension}
                    </span>
                  )}
                </div>
              </label>
            </>
          )}
          {!needEmbedding && (
            <p className="text-[11px] text-gray-500">关键词检索模式无需 Embedding 模型，使用 PostgreSQL 全文匹配。</p>
          )}

          {/* 混合检索权重（hybrid 模式显示） */}
          {isHybrid && (
            <div className="rounded-md border border-gray-800 bg-gray-800/30 p-3">
              <div className="mb-2 text-xs font-medium text-gray-400">融合权重（RRF）</div>
              <div className="flex items-center gap-3">
                <span className="shrink-0 text-[11px] text-blue-300">向量 {form.hybrid_vector_weight}%</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={form.hybrid_vector_weight}
                  onChange={(e) => onVectorWeightChange(Number(e.target.value))}
                  className="flex-1 accent-brand-500"
                />
                <span className="shrink-0 text-[11px] text-amber-300">关键词 {form.hybrid_keyword_weight}%</span>
              </div>
              <p className="mt-1 text-[10px] text-gray-600">💡 向量擅长语义匹配，关键词擅长专有名词/编号。推荐 向量 70% | 关键词 30%</p>
            </div>
          )}
        </div>

        {/* ===== 检索设置 ===== */}
        <div className="flex flex-col gap-3 rounded-md border border-gray-800 bg-gray-900/40 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">检索设置（召回参数微调）</h3>
          <div className="grid grid-cols-2 gap-3">
            <label>
              <div className="mb-1 text-xs font-medium text-gray-400">召回 Top-K 数量 <span className="text-gray-600">建议 3-5</span></div>
              <input type="number" className={inputCls} value={form.retrieval_top_k} onChange={(e) => set('retrieval_top_k')(Number(e.target.value))} min={1} max={50} />
              <p className="mt-0.5 text-[10px] text-gray-600">过多易导致 LLM 抓错重点</p>
            </label>
            <label>
              <div className="mb-1 text-xs font-medium text-gray-400">相似度阈值 <span className="text-gray-600">0-100</span></div>
              <input type="number" className={inputCls} value={form.score_threshold} onChange={(e) => set('score_threshold')(Number(e.target.value))} min={0} max={100} />
              <p className="mt-0.5 text-[10px] text-gray-600">低于此分数的内容将被丢弃，防止幻觉</p>
            </label>
          </div>

          {/* Rerank 重排序模型 */}
          <div className="rounded-md border border-gray-800 bg-gray-800/30 p-3">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.rerank_enabled} onChange={(e) => set('rerank_enabled')(e.target.checked)} className="h-4 w-4 accent-brand-500" />
              <span className="text-sm font-medium text-gray-300">Rerank 重排序模型</span>
              <span className="rounded bg-success-500/20 px-1.5 py-0.5 text-[10px] text-success-300">强烈推荐</span>
            </label>
            <p className="mt-1 ml-6 text-[10px] text-gray-600">
              💡 向量检索充当"粗排"快速捞出 Top-K，Rerank 模型充当"精排"逐字交叉注意力打分，回答准确率通常提升 15%+
            </p>
            {form.rerank_enabled && (
              <label className="mt-2 block">
                <div className="mb-1 text-xs font-medium text-gray-400">选择 Reranker 模型</div>
                <select className={inputCls} value={form.rerank_model} onChange={(e) => set('rerank_model')(e.target.value)}>
                  {RERANK_MODELS.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label} — {m.hint}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>
      </div>
    </Modal>
  )
}

// 文档编辑弹窗（含元数据）
function DocEditModal({ open, initial, onClose, onSubmit, saving }) {
  const [form, setForm] = useState({
    title: '',
    content: '',
    description: '',
    category: '',
    retrieval_weight: 1,
  })

  useEffect(() => {
    if (open) {
      setForm({
        title: initial?.title || '',
        content: initial?.content || '',
        description: initial?.description || '',
        category: initial?.category || '',
        retrieval_weight: initial?.retrieval_weight ?? 1,
      })
    }
  }, [open, initial])

  const set = (k) => (v) => setForm((p) => ({ ...p, [k]: v }))

  return (
    <Modal
      open={open}
      title={initial ? `编辑文档：${initial.title || ''}` : '编辑文档'}
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={() => onSubmit(form)}
            disabled={saving || !form.title}
            className="btn-primary"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">文档标题</div>
          <input
            className={inputCls}
            value={form.title}
            onChange={(e) => set('title')(e.target.value)}
          />
        </label>
        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">文档描述</div>
          <input
            className={inputCls}
            value={form.description}
            onChange={(e) => set('description')(e.target.value)}
            placeholder="可选，有助于语义检索"
          />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">分类</div>
            <input
              className={inputCls}
              value={form.category}
              onChange={(e) => set('category')(e.target.value)}
              placeholder="如：产品手册"
            />
          </label>
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">检索权重（1-10）</div>
            <input
              type="number"
              className={inputCls}
              value={form.retrieval_weight}
              onChange={(e) => set('retrieval_weight')(Number(e.target.value))}
              min={1}
              max={10}
            />
          </label>
        </div>
        <label>
          <div className="mb-1 text-xs font-medium text-gray-400">文档内容</div>
          <textarea
            className={`${textareaCls} resize-y font-mono`}
            rows={12}
            value={form.content}
            onChange={(e) => set('content')(e.target.value)}
          />
        </label>
      </div>
    </Modal>
  )
}

// ===== 新增知识文档弹窗（5维度渐进式表单 + 实时预览） =====
function DocAddModal({ open, kbConfig, onClose, onSubmit, saving }) {
  // 文档来源 tab：upload / web / text
  const [sourceTab, setSourceTab] = useState('text')
  // 基础配置
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [content, setContent] = useState('')
  const [uploadFile, setUploadFile] = useState(null)
  const [webUrl, setWebUrl] = useState('')
  // 高级配置展开
  const [showAdvanced, setShowAdvanced] = useState(false)
  // 解析与切片
  const [autoChunk, setAutoChunk] = useState(true)
  const [chunkSize, setChunkSize] = useState(kbConfig?.chunk_size || 500)
  const [chunkOverlap, setChunkOverlap] = useState(kbConfig?.chunk_overlap || 50)
  // 元数据
  const [category, setCategory] = useState('')
  const [tags, setTags] = useState([{ key: '', value: '' }])
  const [effectiveFrom, setEffectiveFrom] = useState('')
  const [effectiveTo, setEffectiveTo] = useState('')
  // 检索权重
  const [retrievalWeight, setRetrievalWeight] = useState(1)

  useEffect(() => {
    if (open) {
      setSourceTab('text')
      setTitle('')
      setDescription('')
      setContent('')
      setUploadFile(null)
      setWebUrl('')
      setShowAdvanced(false)
      setAutoChunk(true)
      setChunkSize(kbConfig?.chunk_size || 500)
      setChunkOverlap(kbConfig?.chunk_overlap || 50)
      setCategory('')
      setTags([{ key: '', value: '' }])
      setEffectiveFrom('')
      setEffectiveTo('')
      setRetrievalWeight(1)
    }
  }, [open, kbConfig])

  // 实时预览切片效果
  const previewChunks = useMemo(() => {
    if (!content || autoChunk) return []
    const chunks = []
    const step = Math.max(1, chunkSize - chunkOverlap)
    for (let i = 0; i < content.length && chunks.length < 3; i += step) {
      chunks.push(content.slice(i, i + chunkSize))
    }
    return chunks
  }, [content, autoChunk, chunkSize, chunkOverlap])

  const totalChunks = useMemo(() => {
    if (!content || autoChunk) return 0
    const step = Math.max(1, chunkSize - chunkOverlap)
    return Math.ceil(content.length / step)
  }, [content, autoChunk, chunkSize, chunkOverlap])

  const canSubmit = () => {
    if (sourceTab === 'upload') return !!uploadFile
    if (sourceTab === 'web') return !!webUrl.trim()
    return !!content.trim()
  }

  const handleSubmit = () => {
    const tagObj = {}
    tags.forEach((t) => {
      if (t.key.trim()) tagObj[t.key.trim()] = t.value.trim()
    })
    const meta = {
      title: title || (uploadFile?.name || webUrl || '未命名文档'),
      description,
      category: category || null,
      tags: Object.keys(tagObj).length > 0 ? tagObj : null,
      effective_from: effectiveFrom || null,
      effective_to: effectiveTo || null,
      retrieval_weight: retrievalWeight,
    }
    if (sourceTab === 'text') {
      onSubmit({ ...meta, sourceType: 'text', content })
    } else if (sourceTab === 'upload') {
      onSubmit({ ...meta, sourceType: 'upload', file: uploadFile })
    } else if (sourceTab === 'web') {
      onSubmit({ ...meta, sourceType: 'web', url: webUrl })
    }
  }

  const sourceTabs = [
    { value: 'text', label: '📝 文本粘贴', icon: '📝' },
    { value: 'upload', label: '📎 本地文件', icon: '📎' },
    { value: 'web', label: '🌐 网页抓取', icon: '🌐' },
  ]

  return (
    <Modal
      open={open}
      title="新增知识文档"
      onClose={onClose}
      maxWidth="max-w-4xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saving || !canSubmit()}
            className="btn-primary"
          >
            {saving ? '处理中…' : '添加文档'}
          </button>
        </>
      }
    >
      <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto">
        {/* 维度一：文档来源 */}
        <div className="flex flex-col gap-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            一、文档来源
          </h3>
          <div className="flex gap-1 rounded-lg border border-gray-800 bg-gray-900/40 p-1">
            {sourceTabs.map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => setSourceTab(tab.value)}
                className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition ${
                  sourceTab === tab.value
                    ? 'bg-brand-600 text-white'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {sourceTab === 'text' && (
            <textarea
              className={`${textareaCls} resize-y font-mono`}
              rows={8}
              placeholder="直接粘贴文档内容…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          )}
          {sourceTab === 'upload' && (
            <div className="flex flex-col gap-2 rounded-md border border-gray-800 bg-gray-900/40 p-4">
              <input
                type="file"
                className="block w-full text-xs text-gray-300 file:mr-3 file:rounded-md file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white hover:file:bg-brand-500"
                onChange={(e) => {
                  setUploadFile(e.target.files?.[0] || null)
                  if (e.target.files?.[0]) setTitle(e.target.files[0].name.replace(/\.[^.]+$/, ''))
                }}
              />
              <div className="text-[11px] text-gray-500">
                支持 PDF / Word / Excel / TXT / Markdown / CSV，单文件 ≤ 50MB
              </div>
              {uploadFile && (
                <div className="text-[11px] text-gray-400">
                  已选择：{uploadFile.name}（{(uploadFile.size / 1024).toFixed(1)} KB）
                </div>
              )}
            </div>
          )}
          {sourceTab === 'web' && (
            <input
              className={inputCls}
              placeholder="https://example.com/article"
              value={webUrl}
              onChange={(e) => setWebUrl(e.target.value)}
            />
          )}
        </div>

        {/* 维度一续：基础信息 */}
        <div className="grid grid-cols-2 gap-3">
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">文档名称</div>
            <input
              className={inputCls}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="自动提取或手动填写"
            />
          </label>
          <label>
            <div className="mb-1 text-xs font-medium text-gray-400">文档描述</div>
            <input
              className={inputCls}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="可选，有助于语义检索"
            />
          </label>
        </div>

        {/* 高级配置（折叠） */}
        <div className="rounded-md border border-gray-800 bg-gray-900/40">
          <button
            type="button"
            onClick={() => setShowAdvanced((s) => !s)}
            className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400 transition hover:bg-gray-800/60"
          >
            <span>⚙ 高级配置（解析切片 / 元数据 / 检索策略）</span>
            <span className="text-gray-600">{showAdvanced ? '▼' : '▶'}</span>
          </button>

          {showAdvanced && (
            <div className="flex flex-col gap-4 border-t border-gray-800 p-3">
              {/* 维度二：解析与切片 */}
              <div className="flex flex-col gap-2">
                <div className="text-[11px] font-semibold text-gray-300">解析与切片</div>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={autoChunk}
                    onChange={(e) => setAutoChunk(e.target.checked)}
                    className="h-4 w-4 accent-brand-500"
                  />
                  <span className="text-xs text-gray-400">自动切分（系统智能分段）</span>
                </label>
                {!autoChunk && (
                  <div className="grid grid-cols-2 gap-3">
                    <label>
                      <div className="mb-1 text-[11px] text-gray-500">分块大小（字符）</div>
                      <input
                        type="number"
                        className={inputCls}
                        value={chunkSize}
                        onChange={(e) => setChunkSize(Number(e.target.value))}
                        min={100}
                        max={10000}
                      />
                    </label>
                    <label>
                      <div className="mb-1 text-[11px] text-gray-500">分块重叠（字符）</div>
                      <input
                        type="number"
                        className={inputCls}
                        value={chunkOverlap}
                        onChange={(e) => setChunkOverlap(Number(e.target.value))}
                        min={0}
                        max={1000}
                      />
                    </label>
                  </div>
                )}
              </div>

              {/* 维度三：元数据与分类 */}
              <div className="flex flex-col gap-2">
                <div className="text-[11px] font-semibold text-gray-300">元数据与分类标签</div>
                <label>
                  <div className="mb-1 text-[11px] text-gray-500">所属分类</div>
                  <input
                    className={inputCls}
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    placeholder="如：产品手册 / 人事政策"
                  />
                </label>
                <div>
                  <div className="mb-1 text-[11px] text-gray-500">自定义标签</div>
                  {tags.map((tag, idx) => (
                    <div key={idx} className="mb-1 flex items-center gap-1.5">
                      <input
                        className={`${inputCls} flex-1`}
                        placeholder="标签名"
                        value={tag.key}
                        onChange={(e) => {
                          const next = [...tags]
                          next[idx] = { ...next[idx], key: e.target.value }
                          setTags(next)
                        }}
                      />
                      <input
                        className={`${inputCls} flex-1`}
                        placeholder="标签值"
                        value={tag.value}
                        onChange={(e) => {
                          const next = [...tags]
                          next[idx] = { ...next[idx], value: e.target.value }
                          setTags(next)
                        }}
                      />
                      {tags.length > 1 && (
                        <button
                          type="button"
                          onClick={() => setTags(tags.filter((_, i) => i !== idx))}
                          className="shrink-0 rounded border border-gray-700 px-1.5 py-1 text-[11px] text-gray-500 hover:text-danger-400"
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() => setTags([...tags, { key: '', value: '' }])}
                    className="text-[11px] text-brand-400 hover:text-brand-300"
                  >
                    + 添加标签
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <label>
                    <div className="mb-1 text-[11px] text-gray-500">生效时间</div>
                    <input
                      type="datetime-local"
                      className={inputCls}
                      value={effectiveFrom}
                      onChange={(e) => setEffectiveFrom(e.target.value)}
                    />
                  </label>
                  <label>
                    <div className="mb-1 text-[11px] text-gray-500">失效时间</div>
                    <input
                      type="datetime-local"
                      className={inputCls}
                      value={effectiveTo}
                      onChange={(e) => setEffectiveTo(e.target.value)}
                    />
                  </label>
                </div>
              </div>

              {/* 维度四：检索策略 */}
              <div className="flex flex-col gap-2">
                <div className="text-[11px] font-semibold text-gray-300">检索策略</div>
                <label>
                  <div className="mb-1 text-[11px] text-gray-500">检索权重（1-10，越高越优先）</div>
                  <input
                    type="range"
                    min={1}
                    max={10}
                    value={retrievalWeight}
                    onChange={(e) => setRetrievalWeight(Number(e.target.value))}
                    className="w-full accent-brand-500"
                  />
                  <div className="text-center text-[11px] text-gray-400">{retrievalWeight}</div>
                </label>
              </div>
            </div>
          )}
        </div>

        {/* 实时预览：切片效果 */}
        {sourceTab === 'text' && content && !autoChunk && previewChunks.length > 0 && (
          <div className="rounded-md border border-brand-500/30 bg-brand-500/5 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[11px] font-semibold text-brand-300">
                📋 切片预览（共 {totalChunks} 块，展示前 {previewChunks.length} 块）
              </span>
            </div>
            <div className="flex flex-col gap-2">
              {previewChunks.map((chunk, idx) => (
                <div
                  key={idx}
                  className="rounded border border-gray-700 bg-gray-900/60 p-2 font-mono text-[11px] text-gray-300"
                >
                  <div className="mb-1 text-[10px] font-semibold text-gray-500">
                    块 {idx + 1}（{chunk.length} 字符）
                  </div>
                  <div className="max-h-20 overflow-y-auto whitespace-pre-wrap break-words">
                    {chunk}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}

// 文档状态映射（parsing/indexing/available/failed）
const DOC_STATUS_MAP = {
  parsing: { label: '解析中', color: 'bg-amber-500/20 text-amber-300', icon: '⏳' },
  indexing: { label: '索引中', color: 'bg-blue-500/20 text-blue-300', icon: '🔄' },
  available: { label: '就绪', color: 'bg-success-500/20 text-success-300', icon: '✓' },
  failed: { label: '失败', color: 'bg-danger-500/20 text-danger-300', icon: '✕' },
}

// 分段查看弹窗：展示文档解析→分段→向量化的完整过程
function SegmentsModal({ open, data, loading, onClose, onReparse, reparsing }) {
  if (!open) return null
  const cfg = data?.kb_config || {}
  const segments = data?.segments || []
  const chunkModeLabel = CHUNK_MODES.find((m) => m.value === cfg.chunk_mode)?.label || cfg.chunk_mode
  const indexModeLabel = INDEX_MODES.find((m) => m.value === cfg.index_mode)?.label || cfg.index_mode

  return (
    <Modal
      open={open}
      title={`分段详情：${data?.title || ''}`}
      onClose={onClose}
      maxWidth="max-w-4xl"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            关闭
          </button>
          <button
            type="button"
            onClick={onReparse}
            disabled={reparsing}
            className="btn-primary"
          >
            {reparsing ? '重新解析中…' : '🔄 重新解析分段'}
          </button>
        </>
      }
    >
      {loading ? (
        <div className="p-8 text-center text-sm text-gray-500">加载分段中…</div>
      ) : !data ? (
        <div className="p-8 text-center text-sm text-gray-500">暂无数据</div>
      ) : (
        <div className="flex max-h-[75vh] flex-col gap-4 overflow-y-auto">
          {/* 解析过程概览 */}
          <div className="rounded-md border border-gray-800 bg-gray-900/40 p-4">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
              解析与索引过程
            </h3>
            {/* 流程步骤 */}
            <div className="mb-3 flex items-center gap-1">
              <div className="flex flex-1 items-center gap-1.5">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-success-500/20 text-[11px] font-semibold text-success-300">1</span>
                <span className="text-[11px] text-gray-300">文件解析</span>
              </div>
              <span className="text-gray-600">→</span>
              <div className="flex flex-1 items-center gap-1.5">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-success-500/20 text-[11px] font-semibold text-success-300">2</span>
                <span className="text-[11px] text-gray-300">文本分段</span>
              </div>
              <span className="text-gray-600">→</span>
              <div className="flex flex-1 items-center gap-1.5">
                <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ${data.has_embedding ? 'bg-success-500/20 text-success-300' : 'bg-gray-700 text-gray-500'}`}>3</span>
                <span className="text-[11px] text-gray-300">向量生成</span>
              </div>
              <span className="text-gray-600">→</span>
              <div className="flex flex-1 items-center gap-1.5">
                <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ${data.status === 'available' ? 'bg-success-500/20 text-success-300' : 'bg-amber-500/20 text-amber-300'}`}>4</span>
                <span className="text-[11px] text-gray-300">可检索</span>
              </div>
            </div>
            {/* 统计指标 */}
            <div className="grid grid-cols-4 gap-2">
              <div className="rounded border border-gray-800 bg-gray-800/30 p-2 text-center">
                <div className="text-[10px] text-gray-500">原文长度</div>
                <div className="text-sm font-semibold text-gray-200">{(data.content_len || 0).toLocaleString()}</div>
                <div className="text-[9px] text-gray-600">字符</div>
              </div>
              <div className="rounded border border-gray-800 bg-gray-800/30 p-2 text-center">
                <div className="text-[10px] text-gray-500">分段数</div>
                <div className="text-sm font-semibold text-brand-300">{data.segment_count || 0}</div>
                <div className="text-[9px] text-gray-600">chunks</div>
              </div>
              <div className="rounded border border-gray-800 bg-gray-800/30 p-2 text-center">
                <div className="text-[10px] text-gray-500">Token 总数</div>
                <div className="text-sm font-semibold text-gray-200">{(data.token_total || 0).toLocaleString()}</div>
                <div className="text-[9px] text-gray-600">分词后</div>
              </div>
              <div className="rounded border border-gray-800 bg-gray-800/30 p-2 text-center">
                <div className="text-[10px] text-gray-500">向量数</div>
                <div className={`text-sm font-semibold ${data.has_embedding ? 'text-blue-300' : 'text-gray-500'}`}>
                  {data.embedding_count || 0}/{data.segment_count || 0}
                </div>
                <div className="text-[9px] text-gray-600">{data.has_embedding ? '已向量化' : '纯关键词'}</div>
              </div>
            </div>
            {/* 配置信息 */}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">分段：{chunkModeLabel}</span>
              <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">块大小：{cfg.chunk_size}</span>
              <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">重叠：{cfg.chunk_overlap}</span>
              <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">索引：{indexModeLabel}</span>
              {cfg.embedding_model && (
                <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">模型：{cfg.embedding_model}</span>
              )}
            </div>
          </div>

          {/* 分段列表 */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                分段列表（{segments.length}）
              </h3>
              <span className="text-[10px] text-gray-600">点击展开查看完整内容</span>
            </div>
            {segments.length === 0 ? (
              <div className="rounded-md border border-gray-800 bg-gray-900/40 p-6 text-center text-xs text-gray-500">
                暂无分段，请点击"重新解析分段"
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                {segments.map((seg) => (
                  <SegmentItem key={seg.id} seg={seg} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

// 单个分段项（可展开）
function SegmentItem({ seg }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="rounded-md border border-gray-800 bg-gray-900/40">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-gray-800/40"
      >
        <span className="shrink-0 rounded bg-brand-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-brand-300">
          #{seg.seq + 1}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-gray-400">
          {seg.preview}
        </span>
        <span className="shrink-0 text-[10px] text-gray-600">{seg.char_count} 字符</span>
        <span className="shrink-0 text-[10px] text-gray-600">{seg.token_count} tokens</span>
        {seg.has_embedding ? (
          <span className="shrink-0 rounded bg-blue-500/15 px-1 py-0.5 text-[9px] text-blue-300" title="已生成向量">
            向量✓
          </span>
        ) : (
          <span className="shrink-0 rounded bg-gray-700 px-1 py-0.5 text-[9px] text-gray-500" title="无向量">
            无向量
          </span>
        )}
        <span className="shrink-0 text-gray-600">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="border-t border-gray-800 p-3">
          <pre className="max-h-60 w-full overflow-auto whitespace-pre-wrap break-words rounded bg-gray-950 p-2 font-mono text-[11px] text-gray-300">
            {seg.content}
          </pre>
        </div>
      )}
    </div>
  )
}

// 文件查询结果展示（表格形式）
function FileQueryResultView({ data }) {
  const columns = data.columns || []
  const rows = data.rows || []
  const isMulti = Array.isArray(data.results)

  if (isMulti) {
    return (
      <div className="flex flex-col gap-2">
        {data.results.map((r, i) => (
          <div key={i} className="rounded border border-gray-800 bg-gray-950/60 p-2">
            <div className="mb-1 text-[11px] font-medium text-gray-300">
              {r.title} <span className="text-gray-600">({r.matched}/{r.total} 行)</span>
            </div>
            <ResultTable columns={r.columns || []} rows={r.rows || []} />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="rounded border border-gray-800 bg-gray-950/60 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[11px] font-medium text-gray-300">
          {data.title}
          <span className="ml-2 text-gray-600">
            共 {data.total} 行，命中 {data.matched} 行{data.truncated ? `（已截断，仅显示前 ${rows.length} 行）` : ''}
          </span>
        </div>
        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[9px] text-gray-500">
          {data.source}
        </span>
      </div>
      <ResultTable columns={columns} rows={rows} />
    </div>
  )
}

// 表格渲染
function ResultTable({ columns, rows }) {
  if (!rows || rows.length === 0) {
    return <div className="py-2 text-center text-[11px] text-gray-600">无匹配行</div>
  }
  // 收集所有列（不同行可能有不同 key）
  const allCols = columns.length > 0 ? columns : [...new Set(rows.flatMap((r) => Object.keys(r)))]
  return (
    <div className="max-h-80 w-full overflow-auto">
      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr className="border-b border-gray-800">
            <th className="sticky top-0 bg-gray-900 px-2 py-1 text-left text-[10px] font-semibold text-gray-500">
              #
            </th>
            {allCols.map((col) => (
              <th
                key={col}
                className="sticky top-0 bg-gray-900 px-2 py-1 text-left text-[10px] font-semibold text-gray-400 whitespace-nowrap"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
              <td className="px-2 py-1 text-gray-600">{i + 1}</td>
              {allCols.map((col) => (
                <td key={col} className="px-2 py-1 text-gray-300 whitespace-nowrap">
                  {row[col] ?? ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// 知识库管理页：左侧知识库列表 + 右侧文档管理 + 搜索
function KnowledgeBase() {
  const [kbList, setKbList] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [docs, setDocs] = useState([])
  const [loadingKb, setLoadingKb] = useState(true)
  const [loadingDocs, setLoadingDocs] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // 新建/编辑文档
  const [newDocTitle, setNewDocTitle] = useState('')
  const [newDocContent, setNewDocContent] = useState('')

  // 文件上传
  const [uploadFile, setUploadFile] = useState(null)
  const [uploading, setUploading] = useState(false)

  // 搜索
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])

  // 文件查询（Excel/CSV 精确查询）
  const [fileQuery, setFileQuery] = useState('')
  const [fileQueryDocId, setFileQueryDocId] = useState(null)
  const [fileQueryResults, setFileQueryResults] = useState(null)
  const [fileQuerying, setFileQuerying] = useState(false)
  const [searching, setSearching] = useState(false)

  // KB 弹窗
  const [kbFormOpen, setKbFormOpen] = useState(false)
  const [kbEditing, setKbEditing] = useState(null)
  const [kbSaving, setKbSaving] = useState(false)

  // 文档编辑弹窗
  const [docEditOpen, setDocEditOpen] = useState(false)
  const [docEditing, setDocEditing] = useState(null)
  const [docSaving, setDocSaving] = useState(false)

  // 文档新增弹窗
  const [docAddOpen, setDocAddOpen] = useState(false)
  const [docAdding, setDocAdding] = useState(false)

  // 分段查看弹窗
  const [segOpen, setSegOpen] = useState(false)
  const [segDoc, setSegDoc] = useState(null)
  const [segData, setSegData] = useState(null)
  const [segLoading, setSegLoading] = useState(false)
  const [segReparsing, setSegReparsing] = useState(false)

  // 批量重新解析
  const [reparseAllLoading, setReparseAllLoading] = useState(false)
  const [tutorialOpen, setTutorialOpen] = useState(false)

  const loadKb = useCallback(async () => {
    try {
      const data = await kbApi.list()
      setKbList(Array.isArray(data) ? data : [])
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoadingKb(false)
    }
  }, [])

  useEffect(() => {
    loadKb()
  }, [loadKb])

  const loadDocs = useCallback(async (kbId) => {
    setLoadingDocs(true)
    try {
      const data = await kbApi.documents(kbId)
      setDocs(Array.isArray(data) ? data : [])
    } catch (err) {
      setError(err.message || '加载文档失败')
    } finally {
      setLoadingDocs(false)
    }
  }, [])

  // 静默轮询：只更新状态/进度有变化的文档，不触发 loading 状态，避免列表闪烁
  const pollDocs = useCallback(async (kbId) => {
    try {
      const data = await kbApi.documents(kbId)
      if (!Array.isArray(data)) return
      setDocs((prev) => {
        const dataMap = new Map(data.map((d) => [d.id, d]))
        let changed = false
        const next = prev.map((d) => {
          const updated = dataMap.get(d.id)
          if (!updated) return d
          if (
            updated.status !== d.status ||
            updated.progress !== d.progress ||
            updated.segment_count !== d.segment_count
          ) {
            changed = true
            return updated
          }
          return d
        })
        // 有新增或删除的文档时也需要更新
        if (data.length !== prev.length) changed = true
        return changed ? (data.length !== prev.length ? data : next) : prev
      })
    } catch {
      // 静默失败，不影响用户体验
    }
  }, [])

  useEffect(() => {
    if (selectedId) loadDocs(selectedId)
    else setDocs([])
  }, [selectedId, loadDocs])

  // 轮询：有文档处于解析/索引中时，每 2.5s 静默刷新进度
  useEffect(() => {
    const hasProcessing = docs.some(
      (d) => d.status === 'parsing' || d.status === 'indexing'
    )
    if (!hasProcessing || !selectedId) return
    const timer = setInterval(() => pollDocs(selectedId), 2500)
    return () => clearInterval(timer)
  }, [docs, selectedId, pollDocs])

  // 新建/编辑知识库
  const handleKbSubmit = async (form) => {
    setKbSaving(true)
    try {
      if (kbEditing) {
        await kbApi.update(kbEditing.id, form)
      } else {
        await kbApi.create(form)
      }
      setKbFormOpen(false)
      setKbEditing(null)
      await loadKb()
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setKbSaving(false)
    }
  }

  const handleDeleteKb = async (kb) => {
    if (!window.confirm(`确定删除知识库「${kb.name || kb.id}」吗？所有文档将一并删除。`)) return
    try {
      await kbApi.remove(kb.id)
      if (selectedId === kb.id) setSelectedId(null)
      await loadKb()
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  // 添加文档
  const handleAddDoc = async () => {
    if (!selectedId) return
    if (!newDocTitle.trim()) {
      window.alert('请填写文档标题')
      return
    }
    setBusy(true)
    try {
      await kbApi.addDocument(selectedId, {
        title: newDocTitle,
        content: newDocContent,
      })
      setNewDocTitle('')
      setNewDocContent('')
      await loadDocs(selectedId)
    } catch (err) {
      window.alert(`添加文档失败：${err.message || err}`)
    } finally {
      setBusy(false)
    }
  }

  // 编辑文档
  const handleDocUpdate = async (body) => {
    if (!selectedId || !docEditing) return
    setDocSaving(true)
    try {
      await kbApi.updateDocument(selectedId, docEditing.id, body)
      setDocEditOpen(false)
      setDocEditing(null)
      await loadDocs(selectedId)
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setDocSaving(false)
    }
  }

  const handleDeleteDoc = async (docId) => {
    if (!selectedId) return
    if (!window.confirm('确定删除该文档吗？')) return
    try {
      await kbApi.removeDocument(selectedId, docId)
      setDocs((prev) => prev.filter((d) => d.id !== docId))
    } catch (err) {
      window.alert(`删除失败：${err.message || err}`)
    }
  }

  // 新增文档：根据来源类型调用不同 API
  const handleDocAdd = async (data) => {
    if (!selectedId) return
    setDocAdding(true)
    try {
      if (data.sourceType === 'text') {
        await kbApi.addDocument(selectedId, {
          title: data.title,
          content: data.content,
          description: data.description,
          category: data.category,
          tags: data.tags,
          effective_from: data.effective_from,
          effective_to: data.effective_to,
          retrieval_weight: data.retrieval_weight,
        })
      } else if (data.sourceType === 'upload') {
        // 文件上传：后端 upload 端点暂不支持 body 元数据，上传后用返回的 doc.id 更新元数据
        const uploadedDoc = await kbApi.uploadDocument(selectedId, data.file)
        // 上传时标题由文件名解析，若有自定义标题或元数据则更新（内容不变不会触发重新分段）
        if (uploadedDoc?.id && (data.title || data.description || data.category || data.tags)) {
          await kbApi.updateDocument(selectedId, uploadedDoc.id, {
            title: data.title || uploadedDoc.title,
            content: uploadedDoc.content,
            description: data.description,
            category: data.category,
            tags: data.tags,
            effective_from: data.effective_from,
            effective_to: data.effective_to,
            retrieval_weight: data.retrieval_weight,
          })
        }
      } else if (data.sourceType === 'web') {
        await kbApi.fetchUrlDocument(selectedId, {
          url: data.url,
          title: data.title,
          description: data.description,
          category: data.category,
          tags: data.tags,
          retrieval_weight: data.retrieval_weight,
        })
      }
      setDocAddOpen(false)
      await loadDocs(selectedId)
    } catch (err) {
      window.alert(`添加文档失败：${err.message || err}`)
    } finally {
      setDocAdding(false)
    }
  }

  const handleUploadFile = async () => {
    if (!selectedId) return
    if (!uploadFile) {
      window.alert('请先选择要上传的文件')
      return
    }
    setUploading(true)
    try {
      await kbApi.uploadDocument(selectedId, uploadFile)
      setUploadFile(null)
      await loadDocs(selectedId)
    } catch (err) {
      window.alert(`上传失败：${err.message || err}`)
    } finally {
      setUploading(false)
    }
  }

  // 查看文档分段
  const handleViewSegments = async (doc) => {
    if (!selectedId) return
    setSegDoc(doc)
    setSegOpen(true)
    setSegData(null)
    setSegLoading(true)
    try {
      const data = await kbApi.segments(selectedId, doc.id)
      setSegData(data)
    } catch (err) {
      window.alert(`加载分段失败：${err.message || err}`)
      setSegOpen(false)
    } finally {
      setSegLoading(false)
    }
  }

  // 重新解析单个文档
  const handleReparseDoc = async () => {
    if (!selectedId || !segDoc) return
    setSegReparsing(true)
    try {
      await kbApi.reparseDocument(selectedId, segDoc.id)
      // 刷新分段数据
      const data = await kbApi.segments(selectedId, segDoc.id)
      setSegData(data)
      await loadDocs(selectedId)
    } catch (err) {
      window.alert(`重新解析失败：${err.message || err}`)
    } finally {
      setSegReparsing(false)
    }
  }

  // 批量重新解析知识库下所有文档
  const handleReparseAll = async () => {
    if (!selectedId) return
    if (!window.confirm('确定重新解析该知识库下所有文档吗？将按最新配置重新分段与向量化。')) return
    setReparseAllLoading(true)
    try {
      const res = await kbApi.reparseAll(selectedId)
      window.alert(`批量重新解析完成：共 ${res.total} 篇文档`)
      await loadDocs(selectedId)
    } catch (err) {
      window.alert(`批量重新解析失败：${err.message || err}`)
    } finally {
      setReparseAllLoading(false)
    }
  }

  const handleSearch = async () => {
    if (!selectedId) return
    if (!query.trim()) {
      setSearchResults([])
      return
    }
    setSearching(true)
    try {
      const res = await kbApi.search(selectedId, query, 0)
      setSearchResults(Array.isArray(res) ? res : [])
    } catch (err) {
      window.alert(`搜索失败：${err.message || err}`)
    } finally {
      setSearching(false)
    }
  }

  // 文件查询（读取原始 Excel/CSV 按条件查询）
  const handleFileQuery = async () => {
    if (!selectedId) return
    setFileQuerying(true)
    setFileQueryResults(null)
    try {
      const res = await kbApi.fileQuery(selectedId, {
        query: fileQuery,
        doc_id: fileQueryDocId,
        limit: 20,
      })
      setFileQueryResults(res)
    } catch (err) {
      window.alert(`文件查询失败：${err.message || err}`)
    } finally {
      setFileQuerying(false)
    }
  }

  const selectedKb = kbList.find((k) => k.id === selectedId)

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-100">知识库</h1>
          <span className="text-xs text-gray-500">共 {kbList.length} 个</span>
        </div>
        <div className="flex items-center gap-2">
          <TutorialButton onClick={() => setTutorialOpen(true)} />
          <button type="button" onClick={loadKb} className="btn-secondary btn-sm">
            刷新
          </button>
          <button
            type="button"
            onClick={() => {
              setKbEditing(null)
              setKbFormOpen(true)
            }}
            className="btn-primary btn-sm"
          >
            + 新建知识库
          </button>
        </div>
      </header>

      {error && (
        <div className="m-4 rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-danger-300">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* 左侧：知识库列表 */}
        <aside className="flex w-[300px] shrink-0 flex-col border-r border-gray-800 bg-gray-900/40">
          <div className="border-b border-gray-800 p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-300">
              知识库列表
            </h2>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {loadingKb ? (
              <div className="p-4 text-center text-xs text-gray-500">加载中...</div>
            ) : kbList.length === 0 ? (
              <div className="p-4 text-center text-xs text-gray-600">暂无知识库</div>
            ) : (
              <div className="flex flex-col gap-1">
                {kbList.map((kb) => (
                  <div
                    key={kb.id}
                    onClick={() => setSelectedId(kb.id)}
                    className={`group cursor-pointer rounded-md border p-2 transition ${
                      selectedId === kb.id
                        ? 'border-brand-500 bg-brand-500/10'
                        : 'border-gray-800 bg-gray-900/40 hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-gray-100">
                          {kb.name || `#${kb.id}`}
                        </div>
                        <div className="truncate text-[11px] text-gray-500">
                          {kb.description || '无描述'} · {kb.doc_count ?? 0} 篇
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          <span className="rounded bg-gray-800 px-1 py-0.5 text-[9px] text-gray-400">
                            {INDEX_MODES.find((m) => m.value === kb.index_mode)?.label || kb.index_mode}
                          </span>
                          <span className="rounded bg-gray-800 px-1 py-0.5 text-[9px] text-gray-400">
                            {CHUNK_MODES.find((m) => m.value === kb.chunk_mode)?.label || kb.chunk_mode}
                          </span>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col gap-1 opacity-0 group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            setKbEditing(kb)
                            setKbFormOpen(true)
                          }}
                          className="rounded border border-gray-700 px-1.5 py-0.5 text-[11px] text-gray-400 hover:border-brand-600 hover:text-brand-300"
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDeleteKb(kb)
                          }}
                          className="rounded border border-gray-700 px-1.5 py-0.5 text-[11px] text-gray-400 hover:border-danger-700 hover:text-danger-400"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* 右侧：文档管理 + 搜索 */}
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {!selectedId ? (
            <div className="flex h-full items-center justify-center text-gray-500">
              <div className="text-center">
                <div className="text-4xl">📚</div>
                <div className="mt-2 text-sm">请在左侧选择一个知识库</div>
              </div>
            </div>
          ) : (
            <>
              {/* 顶部信息条 + 配置 */}
              <div className="border-b border-gray-800 bg-gray-900/40 px-4 py-3">
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-gray-100">
                        {selectedKb?.name || `知识库 #${selectedId}`}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setKbEditing(selectedKb)
                          setKbFormOpen(true)
                        }}
                        className="rounded border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:border-brand-600 hover:text-brand-300"
                      >
                        编辑配置
                      </button>
                    </div>
                    <div className="truncate text-[11px] text-gray-500">
                      {selectedKb?.description || '无描述'}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-gray-500">文档 {docs.length} 篇</span>
                    <button
                      type="button"
                      onClick={handleReparseAll}
                      disabled={reparseAllLoading || docs.length === 0}
                      title="按最新知识库配置重新分段与向量化所有文档"
                      className="rounded border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:border-brand-600 hover:text-brand-300 disabled:opacity-50"
                    >
                      {reparseAllLoading ? '解析中…' : '🔄 批量重建索引'}
                    </button>
                  </div>
                </div>
                {/* 配置标签 */}
                {selectedKb && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">
                      索引：{INDEX_MODES.find((m) => m.value === selectedKb.index_mode)?.label || selectedKb.index_mode}
                    </span>
                    <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">
                      分段：{CHUNK_MODES.find((m) => m.value === selectedKb.chunk_mode)?.label || selectedKb.chunk_mode}
                      {selectedKb.chunk_mode === 'manual' && ` (${selectedKb.chunk_size}/${selectedKb.chunk_overlap})`}
                    </span>
                    {(selectedKb.index_mode === 'vector' || selectedKb.index_mode === 'hybrid') && (
                      <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">
                        Embedding：{selectedKb.embedding_model}
                      </span>
                    )}
                    <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">
                      Top-K：{selectedKb.retrieval_top_k}
                    </span>
                    {selectedKb.score_threshold > 0 && (
                      <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] text-gray-400">
                        阈值：{selectedKb.score_threshold}
                      </span>
                    )}
                    {selectedKb.rerank_enabled > 0 && (
                      <span className="rounded bg-brand-500/15 px-2 py-0.5 text-[10px] text-brand-300">
                        Rerank 已启用
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* 滚动区：新增文档按钮 + 文档列表 + 搜索 */}
              <div className="flex-1 overflow-y-auto p-4">
                {/* 新增文档按钮 */}
                <div className="mb-4">
                  <button
                    type="button"
                    onClick={() => setDocAddOpen(true)}
                    className="btn-primary btn-sm w-full"
                  >
                    + 新增知识文档
                  </button>
                </div>

                {/* 文档列表 */}
                <div className="mb-4">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-300">
                    文档列表
                  </div>
                  {loadingDocs ? (
                    <div className="p-4 text-center text-xs text-gray-500">加载中...</div>
                  ) : docs.length === 0 ? (
                    <div className="p-4 text-center text-xs text-gray-600">暂无文档</div>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {docs.map((doc) => {
                        const isUpload = doc.source_type === 'upload'
                        const badge = isUpload ? fileBadge(doc.file_type) : null
                        const statusInfo = DOC_STATUS_MAP[doc.status] || DOC_STATUS_MAP.available
                        return (
                          <div
                            key={doc.id}
                            className="rounded-md border border-gray-800 bg-gray-900/40 p-4"
                          >
                            <div className="flex items-start justify-between">
                              <div className="min-w-0 flex-1">
                                <div className="flex min-w-0 items-center gap-2">
                                  {isUpload && badge && (
                                    <span
                                      className="shrink-0 rounded bg-brand-500/15 px-1.5 py-0.5 text-[10px] font-medium text-brand-300"
                                      title={`文件类型：${badge.label}`}
                                    >
                                      {badge.icon} {badge.label}
                                    </span>
                                  )}
                                  <div className="truncate text-sm font-medium text-gray-100">
                                    {doc.title || `文档 #${doc.id}`}
                                  </div>
                                  <span
                                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${statusInfo.color}`}
                                    title={`状态：${doc.status}`}
                                  >
                                    {statusInfo.icon} {statusInfo.label}
                                  </span>
                                </div>
                                {isUpload && doc.file_name && (
                                  <div className="mt-0.5 truncate text-[11px] text-gray-400">
                                    📎 {doc.file_name}
                                  </div>
                                )}
                                <div className="text-[11px] text-gray-500">
                                  {fmtTime(doc.created_at)}
                                  {doc.updated_at && doc.updated_at !== doc.created_at
                                    ? ` · 更新于 ${fmtTime(doc.updated_at)}`
                                    : ''}
                                  <span className="ml-2 text-gray-600">·</span>
                                  <span className="ml-2 text-brand-400">
                                    {doc.segment_count ?? 0} 段
                                  </span>
                                  <span className="ml-1 text-gray-600">
                                    / {(doc.content || '').length.toLocaleString()} 字符
                                  </span>
                                </div>
                                {(doc.status === 'parsing' || doc.status === 'indexing') && (
                                  <div className="mt-2 flex items-center gap-2">
                                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-700">
                                      <div
                                        className="h-full rounded-full bg-brand-500 transition-all duration-300"
                                        style={{ width: `${doc.progress || 0}%` }}
                                      />
                                    </div>
                                    <span className="shrink-0 text-[10px] text-gray-400">
                                      {doc.status === 'parsing' ? '解析分段' : '向量化'} {doc.progress || 0}%
                                    </span>
                                  </div>
                                )}
                              </div>
                              <div className="flex shrink-0 gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => handleViewSegments(doc)}
                                  title="查看解析、分段与向量化详情"
                                  className="rounded border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:border-blue-600 hover:text-blue-300"
                                >
                                  查看分段
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setDocEditing(doc)
                                    setDocEditOpen(true)
                                  }}
                                  className="rounded border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:border-brand-600 hover:text-brand-300"
                                >
                                  编辑
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleDeleteDoc(doc.id)}
                                  className="rounded border border-gray-700 px-2 py-0.5 text-[11px] text-gray-400 hover:border-danger-700 hover:text-danger-400"
                                >
                                  删除
                                </button>
                              </div>
                            </div>
                            {doc.content && (
                              <pre className="mt-2 max-h-32 w-full overflow-auto whitespace-pre-wrap break-words rounded bg-gray-950 p-2 font-mono text-[11px] text-gray-400 ring-1 ring-gray-800">
                                {doc.content}
                              </pre>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>

                {/* 搜索 */}
                <div className="rounded-md border border-gray-800 bg-gray-900/40 p-4">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-300">
                    语义搜索
                  </div>
                  <div className="flex gap-2">
                    <input
                      className={inputCls}
                      placeholder="输入查询关键词…"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSearch()
                      }}
                    />
                    <button
                      type="button"
                      onClick={handleSearch}
                      disabled={searching}
                      className="btn-primary btn-sm shrink-0"
                    >
                      {searching ? '搜索中…' : '搜索'}
                    </button>
                  </div>
                  {searchResults.length > 0 && (
                    <div className="mt-3 flex flex-col gap-2">
                      <div className="text-[10px] text-gray-600">
                        💡 命中 {searchResults.length} 段，分数 = 综合相似度（BM25 关键词 + 向量语义，按知识库权重融合）
                      </div>
                      {searchResults.map((r, idx) => (
                        <div
                          key={idx}
                          className="rounded-md border border-gray-800 bg-gray-950/60 p-3"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex min-w-0 items-center gap-2">
                              <span className="shrink-0 rounded bg-brand-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-brand-300">
                                #{idx + 1}
                              </span>
                              <span className="shrink-0 rounded bg-gray-800 px-1.5 py-0.5 text-[9px] text-gray-500">
                                段 #{(r.seq ?? 0) + 1}
                              </span>
                              <div className="min-w-0 truncate text-sm font-medium text-gray-100">
                                {r.title || `文档 #${r.doc_id}`}
                              </div>
                            </div>
                            <span className="shrink-0 rounded bg-success-500/20 px-2 py-0.5 text-[10px] font-medium text-success-300">
                              {(r.score ?? 0).toFixed(4)}
                            </span>
                          </div>
                          {/* 分数明细 */}
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] text-amber-300" title="BM25 关键词匹配分数（归一化）">
                              BM25: {(r.bm25_score ?? 0).toFixed(4)}
                            </span>
                            <span className="rounded bg-blue-500/15 px-1.5 py-0.5 text-[9px] text-blue-300" title="向量语义余弦相似度（归一化）">
                              向量: {(r.vector_score ?? 0).toFixed(4)}
                            </span>
                          </div>
                          {r.content && (
                            <pre className="mt-1.5 max-h-28 w-full overflow-auto whitespace-pre-wrap break-words rounded bg-gray-900 p-2 font-mono text-[11px] text-gray-400 ring-1 ring-gray-800">
                              {r.content}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 文件查询（Excel/CSV 精确查询） */}
                <div className="rounded-md border border-gray-800 bg-gray-900/40 p-4">
                  <div className="mb-1 flex items-center justify-between">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                      文件查询（表格精确查询）
                    </div>
                    <span className="text-[10px] text-gray-600">
                      读取原始 Excel/CSV，按条件过滤行
                    </span>
                  </div>
                  <div className="mb-1.5 text-[10px] text-gray-500">
                    💡 支持关键词（任意列包含）或"列名=值"精确过滤。适合 IP 列表、资产台账等结构化数据。与语义搜索互补。
                  </div>
                  <div className="flex gap-2">
                    <select
                      className={`${inputCls} w-40 shrink-0`}
                      value={fileQueryDocId || ''}
                      onChange={(e) => setFileQueryDocId(e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">全部文档</option>
                      {docs.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.title}
                        </option>
                      ))}
                    </select>
                    <input
                      className={inputCls}
                      placeholder="查询条件，如 192.168.1.1 或 部门=研发部"
                      value={fileQuery}
                      onChange={(e) => setFileQuery(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleFileQuery()
                      }}
                    />
                    <button
                      type="button"
                      onClick={handleFileQuery}
                      disabled={fileQuerying}
                      className="btn-primary btn-sm shrink-0"
                    >
                      {fileQuerying ? '查询中…' : '查询'}
                    </button>
                  </div>
                  {fileQueryResults && (
                    <div className="mt-3">
                      {fileQueryResults.error ? (
                        <div className="rounded border border-gray-800 bg-gray-950/60 p-3 text-xs text-gray-500">
                          {fileQueryResults.error}
                        </div>
                      ) : fileQueryResults.message ? (
                        <div className="rounded border border-gray-800 bg-gray-950/60 p-3 text-xs text-gray-500">
                          {fileQueryResults.message}
                        </div>
                      ) : (
                        <FileQueryResultView data={fileQueryResults} />
                      )}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </main>
      </div>

      {/* 知识库编辑/新建弹窗 */}
      <KBFormModal
        open={kbFormOpen}
        initial={kbEditing}
        onClose={() => {
          setKbFormOpen(false)
          setKbEditing(null)
        }}
        onSubmit={handleKbSubmit}
        saving={kbSaving}
      />

      {/* 文档编辑弹窗 */}
      <DocEditModal
        open={docEditOpen}
        initial={docEditing}
        onClose={() => {
          setDocEditOpen(false)
          setDocEditing(null)
        }}
        onSubmit={handleDocUpdate}
        saving={docSaving}
      />

      {/* 新增知识文档弹窗（5维度渐进式表单） */}
      <DocAddModal
        open={docAddOpen}
        kbConfig={selectedKb}
        onClose={() => setDocAddOpen(false)}
        onSubmit={handleDocAdd}
        saving={docAdding}
      />

      {/* 分段查看弹窗 */}
      <SegmentsModal
        open={segOpen}
        data={segData}
        loading={segLoading}
        reparsing={segReparsing}
        onClose={() => {
          setSegOpen(false)
          setSegDoc(null)
          setSegData(null)
        }}
        onReparse={handleReparseDoc}
      />

      {/* 使用教程 */}
      <TutorialDrawer
        open={tutorialOpen}
        onClose={() => setTutorialOpen(false)}
        title="知识库使用教程"
        subtitle="了解如何创建知识库、上传文档和配置检索"
        sections={KNOWLEDGE_BASE_TUTORIAL}
      />
    </div>
  )
}

export default KnowledgeBase
