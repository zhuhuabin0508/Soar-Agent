// 材料管理页：左侧树形目录（最多 10 级） + 右侧材料文件列表
// 功能：树形目录 CRUD / 子目录创建 / 多文件上传(白名单) / 预览 / 在线编辑 / 单/批量下载 / 删除
// 权限：deliverable.view 可见/预览；.edit 可建目录/上传/编辑/在线修改；.delete 可删除
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckCircle2, ChevronDown, ChevronRight, ChevronsUp, CloudUpload, Download,
  Eye, FileArchive, FileSpreadsheet, FileText, Folder, FolderArchive, FolderOpen,
  FolderPlus, HardDrive, LayoutGrid, List, Loader2, MoreVertical, Move,
  Pencil, Plus, Save, Search, Trash2, Upload, X, XCircle,
} from 'lucide-react'
import { deliverablesApi } from '../api/client'
import { toast } from '../store/toastStore'
import { PageContainer, PageHeader, Button, EmptyState, Pagination } from '../components/ui'
import { confirm } from '../components/ConfirmDialog'
import { hasPermission } from '../utils/permissions'
import { TutorialButton, TutorialDrawer } from '../components/TutorialDrawer'
import { DELIVERABLE_TUTORIAL } from '../components/tutorialContent'

const PAGE_SIZE = 20
const MAX_LEVEL = 10
// 与后端 ALLOWED_EXTENSIONS 保持一致
const ALLOWED_EXTS = ['xlsx', 'xls', 'doc', 'docx', 'ppt', 'pptx', 'pdf', 'zip', 'rar', '7z', 'txt', 'csv', 'md']
const MAX_SIZE = 200 * 1024 * 1024
// 可在线预览的文件扩展名
const PREVIEW_PDF_EXTS = ['pdf']
const TEXT_EDIT_EXTS = ['txt', 'csv', 'md']
const PREVIEWABLE_EXTS = ['pdf', 'txt', 'csv', 'md']

// 扩展名 → 图标/颜色
function FileIcon({ ext, className = 'h-4 w-4' }) {
  if (['xlsx', 'xls', 'csv'].includes(ext)) return <FileSpreadsheet className={`${className} text-emerald-500`} />
  if (['doc', 'docx'].includes(ext)) return <FileText className={`${className} text-blue-500`} />
  if (['ppt', 'pptx'].includes(ext)) return <FileText className={`${className} text-orange-500`} />
  if (['zip', 'rar', '7z'].includes(ext)) return <FileArchive className={`${className} text-amber-500`} />
  return <FileText className={`${className} text-muted-foreground`} />
}

function fmtSize(bytes) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// 校验上传文件（前端预检，后端仍强校验）
function validateFile(file) {
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!ALLOWED_EXTS.includes(ext)) {
    return `不支持的文件类型 .${ext}（允许：${ALLOWED_EXTS.join(' / ')}）`
  }
  if (file.size > MAX_SIZE) return `文件大小不能超过 200MB（当前 ${fmtSize(file.size)}）`
  if (file.size === 0) return '文件内容为空'
  return ''
}

// 从扁平列表构建树：{ id, name, parent_id, level, children: [] }
function buildTree(items) {
  const map = new Map()
  const roots = []
  items.forEach((it) => {
    map.set(it.id, { ...it, children: [] })
  })
  map.forEach((node) => {
    if (node.parent_id && map.has(node.parent_id)) {
      map.get(node.parent_id).children.push(node)
    } else {
      roots.push(node)
    }
  })
  return roots
}

// 通用小 Modal
function Modal({ title, children, onClose, footer }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <button type="button" className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}

// 输入行
function Field({ label, children, hint }) {
  return (
    <div className="mb-3">
      <label className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-muted-foreground/80">{hint}</p>}
    </div>
  )
}

const inputCls =
  'w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary'

export default function DeliverableManagement() {
  // 权限
  const canEdit = hasPermission('deliverable', 'edit')
  const canDelete = hasPermission('deliverable', 'delete')

  // 目录类别状态（扁平列表，前端构建树）
  const [categories, setCategories] = useState([])
  const [totalDeliverables, setTotalDeliverables] = useState(0)
  const [catLoading, setCatLoading] = useState(false)
  const [activeCatId, setActiveCatId] = useState(null)
  // 展开的节点 ID 集合
  const [expandedIds, setExpandedIds] = useState(() => new Set())
  // 类别弹窗：{ mode, id?, name, description, parentId, parentName?, parentLevel }
  const [catModal, setCatModal] = useState(null)
  const [catSaving, setCatSaving] = useState(false)

  // 材料状态
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [loading, setLoading] = useState(false)

  // 批量选择
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [batchDownloading, setBatchDownloading] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [selectingAll, setSelectingAll] = useState(false)

  // 上传弹窗：{ files: [{ file, status }], version, description }
  // status: 'pending' | 'uploading' | 'success' | 'failed'
  const [uploadModal, setUploadModal] = useState(null)
  const [uploading, setUploading] = useState(false)
  // 编辑弹窗：{ id, name, version, description, file, filename }
  const [editModal, setEditModal] = useState(null)
  const [editSaving, setEditSaving] = useState(false)

  // 预览/编辑弹窗：{ row, type: 'pdf'|'text'|'unsupported', loading, content, blobUrl, error, dirty, saving }
  const [previewModal, setPreviewModal] = useState(null)
  const [previewSaving, setPreviewSaving] = useState(false)
  // 移动目录弹窗：{ id, name, description, currentParentId, targetParentId }
  const [moveModal, setMoveModal] = useState(null)
  const [moveSaving, setMoveSaving] = useState(false)

  // 视图模式：list / grid
  const [viewMode, setViewMode] = useState(() => localStorage.getItem('soar_dlv_view') || 'list')
  // 右键菜单：{ x, y, node } | null
  const [contextMenu, setContextMenu] = useState(null)
  // 拖拽上传高亮
  const [dragOver, setDragOver] = useState(false)
  // 新建目录：保存并继续
  const [saveContinue, setSaveContinue] = useState(false)
  // 目录树宽度（可拖拽调节，持久化）
  const [treeWidth, setTreeWidth] = useState(() => {
    const saved = parseInt(localStorage.getItem('soar_dlv_tree_w'))
    return saved && saved >= 180 && saved <= 520 ? saved : 288
  })
  const [treeResizing, setTreeResizing] = useState(false)
  // 拖拽起始位置记录
  const resizeStartRef = useRef({ x: 0, width: 0 })

  const [deleting, setDeleting] = useState(false)
  // 目录导出中（记录正在导出的目录 ID，禁用按钮防重复点击）
  const [exportingCatId, setExportingCatId] = useState(null)
  const [exportProgress, setExportProgress] = useState(null) // { phase: 'packing'|'downloading', percent: 0-100, loaded: bytes, name: '' }
  // 使用教程抽屉
  const [tutorialOpen, setTutorialOpen] = useState(false)

  // 构建树
  const tree = useMemo(() => buildTree(categories), [categories])
  const activeCat = categories.find((c) => c.id === activeCatId) || null
  const totalFiles = totalDeliverables
  const allChecked = rows.length > 0 && rows.every((r) => selectedIds.has(r.id))
  const someChecked = rows.some((r) => selectedIds.has(r.id))

  // 面包屑路径：从根到当前目录
  const breadcrumbPath = useMemo(() => {
    if (!activeCat) return []
    const path = []
    let current = activeCat
    let safety = 0
    while (current && safety < MAX_LEVEL) {
      path.unshift(current)
      current = categories.find((c) => c.id === current.parent_id)
      safety++
    }
    return path
  }, [activeCat, categories])

  // 当前目录的直接子目录（文件夹卡片展示）
  const subCategories = useMemo(() => {
    if (!activeCatId) return []
    return categories.filter((c) => c.parent_id === activeCatId)
  }, [activeCatId, categories])

  // 双击进入子目录
  const enterSubCategory = useCallback((cat) => {
    setActiveCatId(cat.id)
    setPage(1)
    // 同步展开树
    setExpandedIds((prev) => {
      const next = new Set(prev)
      next.add(cat.id)
      return next
    })
  }, [])

  // 切换视图模式（持久化）
  const changeViewMode = (mode) => {
    setViewMode(mode)
    localStorage.setItem('soar_dlv_view', mode)
  }

  // 关闭右键菜单（全局点击）
  useEffect(() => {
    if (!contextMenu) return
    const close = () => setContextMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [contextMenu])

  // 目录树宽度拖拽：监听全局 mousemove / mouseup
  useEffect(() => {
    if (!treeResizing) return
    const onMove = (e) => {
      e.preventDefault()
      const delta = e.clientX - resizeStartRef.current.x
      const newWidth = Math.min(520, Math.max(180, resizeStartRef.current.width + delta))
      setTreeWidth(newWidth)
    }
    const onUp = () => {
      setTreeResizing(false)
      setTreeWidth((w) => {
        localStorage.setItem('soar_dlv_tree_w', String(w))
        return w
      })
    }
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [treeResizing])

  // 开始拖拽
  const handleResizeStart = (e) => {
    e.preventDefault()
    resizeStartRef.current = { x: e.clientX, width: treeWidth }
    setTreeResizing(true)
  }

  // 持久化展开状态
  const toggleExpand = useCallback((id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      localStorage.setItem('soar_dlv_expanded', JSON.stringify([...next]))
      return next
    })
  }, [])

  // ===== 数据加载 =====
  const loadCategories = useCallback(async (keepActive = true) => {
    setCatLoading(true)
    try {
      const res = await deliverablesApi.categories()
      const items = res.items || []
      setCategories(items)
      setTotalDeliverables(res.total_deliverables || 0)
      if (keepActive && items.some((c) => c.id === activeCatId)) return
      setActiveCatId(items.length > 0 ? items[0].id : null)
    } catch (err) {
      toast.error(err.message || '加载目录类别失败')
    } finally {
      setCatLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCatId])

  const loadDeliverables = useCallback(async () => {
    if (!activeCatId) {
      setRows([])
      setTotal(0)
      return
    }
    setLoading(true)
    try {
      const res = await deliverablesApi.list({
        category_id: activeCatId,
        search,
        page,
        size: pageSize,
      })
      setRows(res.items || [])
      setTotal(res.total || 0)
    } catch (err) {
      toast.error(err.message || '加载材料失败')
    } finally {
      setLoading(false)
    }
  }, [activeCatId, search, page, pageSize])

  useEffect(() => {
    loadCategories(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    loadDeliverables()
  }, [loadDeliverables])

  // 切换类别时清空选择
  useEffect(() => {
    setSelectedIds(new Set())
  }, [activeCatId, page, pageSize, search])

  // ===== 目录类别操作 =====
  const handleCatSave = async (continueMode = false) => {
    if (!catModal?.name.trim()) {
      toast.warning('请输入目录名称')
      return
    }
    setCatSaving(true)
    try {
      const parentId = catModal.parentId || 0
      if (catModal.mode === 'create') {
        await deliverablesApi.createCategory(catModal.name.trim(), catModal.description.trim(), parentId)
        toast.success(parentId ? '子目录已创建' : '目录已创建')
        // 自动展开父节点
        if (parentId) {
          setExpandedIds((prev) => {
            const next = new Set(prev)
            next.add(parentId)
            localStorage.setItem('soar_dlv_expanded', JSON.stringify([...next]))
            return next
          })
        }
        if (continueMode) {
          // 保存并继续：清空名称，保留父级和描述
          setCatModal((prev) => ({ ...prev, name: '', description: '' }))
          await loadCategories()
        } else {
          setCatModal(null)
          await loadCategories()
        }
      } else {
        await deliverablesApi.updateCategory(catModal.id, catModal.name.trim(), catModal.description.trim())
        toast.success('目录已更新')
        setCatModal(null)
        await loadCategories()
      }
    } catch (err) {
      toast.error(err.message || '保存失败')
    } finally {
      setCatSaving(false)
    }
  }

  const handleConfirmDelete = async (target) => {
    if (!target || deleting) return
    const isCat = target.type === 'category'
    const ok = await confirm({
      title: isCat ? `删除目录「${target.name}」？` : `删除材料「${target.name}」？`,
      message: isCat
        ? '删除后不可恢复。目录下有子目录或材料时将被拒绝。'
        : `将同时删除文件「${target.filename}」，操作不可恢复。`,
      confirmText: '确认删除',
    })
    if (!ok) return
    setDeleting(true)
    try {
      if (isCat) {
        await deliverablesApi.deleteCategory(target.id)
        toast.success('目录已删除')
        await loadCategories()
      } else {
        await deliverablesApi.remove(target.id)
        toast.success('材料已删除')
        await loadDeliverables()
        await loadCategories()
      }
    } catch (err) {
      toast.error(err.message || '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  // ===== 材料操作 =====
  const handleUpload = async () => {
    const files = uploadModal?.files || []
    const pending = files.filter((f) => f.status !== 'success')
    if (pending.length === 0) {
      toast.warning('请先选择文件')
      return
    }
    // 前端预检全部文件
    const invalid = pending.find((f) => {
      const err = validateFile(f.file)
      if (err) {
        f._err = err
        return true
      }
      return false
    })
    if (invalid) {
      toast.error(invalid._err)
      return
    }

    setUploading(true)
    let successCount = 0
    let failCount = 0
    for (const item of pending) {
      // 标记为 uploading
      setUploadModal((prev) => ({
        ...prev,
        files: prev.files.map((f) =>
          f === item ? { ...f, status: 'uploading' } : f
        ),
      }))
      try {
        await deliverablesApi.upload(activeCatId, item.file, {
          name: item.file.name.replace(/\.[^.]+$/, ''),
          version: uploadModal.version.trim(),
          description: uploadModal.description.trim(),
        })
        successCount++
        setUploadModal((prev) => ({
          ...prev,
          files: prev.files.map((f) =>
            f === item ? { ...f, status: 'success' } : f
          ),
        }))
      } catch (e) {
        failCount++
        const errMsg = e.message || '上传失败'
        setUploadModal((prev) => ({
          ...prev,
          files: prev.files.map((f) =>
            f === item ? { ...f, status: 'failed', error: errMsg } : f
          ),
        }))
      }
    }

    setUploading(false)
    if (failCount === 0) {
      toast.success(`全部 ${successCount} 个文件上传成功`)
      setUploadModal(null)
    } else if (successCount === 0) {
      toast.error(`全部 ${failCount} 个文件上传失败`)
    } else {
      toast.warning(`上传完成：成功 ${successCount} 个，失败 ${failCount} 个`)
    }
    await loadDeliverables()
    await loadCategories()
  }

  const handleEditSave = async () => {
    if (!editModal?.name.trim()) {
      toast.warning('请输入材料名称')
      return
    }
    if (editModal.file) {
      const err = validateFile(editModal.file)
      if (err) {
        toast.error(err)
        return
      }
    }
    setEditSaving(true)
    try {
      await deliverablesApi.update(
        editModal.id,
        {
          name: editModal.name.trim(),
          version: editModal.version.trim(),
          description: editModal.description.trim(),
        },
        editModal.file || null
      )
      toast.success('材料已更新')
      setEditModal(null)
      await loadDeliverables()
    } catch (err) {
      toast.error(err.message || '保存失败')
    } finally {
      setEditSaving(false)
    }
  }

  const handleDownload = async (row) => {
    try {
      await deliverablesApi.download(row.id, row.filename)
      toast.success('开始下载')
    } catch (err) {
      toast.error(err.message || '下载失败')
    }
  }

  // ===== 预览 / 在线编辑 =====
  const handlePreview = async (row) => {
    const ext = (row.file_ext || '').toLowerCase()
    if (PREVIEW_PDF_EXTS.includes(ext)) {
      // PDF：fetch blob → iframe 预览
      setPreviewModal({ row, type: 'pdf', loading: true, blobUrl: null, error: null })
      try {
        const url = await deliverablesApi.previewBlob(row.id)
        setPreviewModal((prev) => ({ ...prev, loading: false, blobUrl: url }))
      } catch (err) {
        setPreviewModal((prev) => ({ ...prev, loading: false, error: err.message || '预览加载失败' }))
      }
    } else if (TEXT_EDIT_EXTS.includes(ext)) {
      // 文本：fetch content → 编辑器
      setPreviewModal({ row, type: 'text', loading: true, content: '', original: '', dirty: false, error: null })
      try {
        const res = await deliverablesApi.getContent(row.id)
        setPreviewModal((prev) => ({
          ...prev,
          loading: false,
          content: res.content || '',
          original: res.content || '',
          dirty: false,
        }))
      } catch (err) {
        setPreviewModal((prev) => ({ ...prev, loading: false, error: err.message || '内容加载失败' }))
      }
    } else {
      // 其他类型：不支持预览，提示下载
      setPreviewModal({ row, type: 'unsupported', loading: false, error: null })
    }
  }

  const closePreview = () => {
    if (previewModal?.blobUrl) {
      URL.revokeObjectURL(previewModal.blobUrl)
    }
    setPreviewModal(null)
  }

  // ===== 移动目录 =====
  // 计算某节点的所有后代 ID（用于移动时排除不可选目标）
  const getDescendantIds = useCallback(
    (nodeId) => {
      const result = new Set()
      let frontier = [nodeId]
      for (let i = 0; i < MAX_LEVEL; i++) {
        const next = categories
          .filter((c) => c.parent_id && frontier.includes(c.parent_id))
          .map((c) => c.id)
        if (next.length === 0) break
        next.forEach((id) => result.add(id))
        frontier = next
      }
      return result
    },
    [categories]
  )

  const handleMoveSave = async () => {
    if (!moveModal) return
    const targetId = moveModal.targetParentId // 0=根级, 正整数=目标父级
    setMoveSaving(true)
    try {
      // parentId: "0"=移到根级, 正整数字符串=移到指定父级
      await deliverablesApi.updateCategory(
        moveModal.id,
        moveModal.name,
        moveModal.description || '',
        String(targetId)
      )
      toast.success('目录已移动')
      setMoveModal(null)
      // 自动展开目标父级
      if (targetId) {
        setExpandedIds((prev) => {
          const next = new Set(prev)
          next.add(targetId)
          localStorage.setItem('soar_dlv_expanded', JSON.stringify([...next]))
          return next
        })
      }
      await loadCategories()
    } catch (err) {
      toast.error(err.message || '移动失败')
    } finally {
      setMoveSaving(false)
    }
  }

  const handleSearch = () => {
    setSearch(searchInput)
    setPage(1)
  }

  const handleSaveContent = async () => {
    if (!previewModal?.row || previewModal.type !== 'text') return
    setPreviewSaving(true)
    try {
      await deliverablesApi.saveContent(previewModal.row.id, previewModal.content)
      setPreviewModal((prev) => ({ ...prev, original: prev.content, dirty: false }))
      toast.success('内容已保存')
      await loadDeliverables()
      await loadCategories()
    } catch (err) {
      toast.error(err.message || '保存失败')
    } finally {
      setPreviewSaving(false)
    }
  }

  // ===== 批量选择 / 下载 =====
  const toggleRow = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    // 仅切换当前页行的选中状态，不影响跨页已选
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (rows.every((r) => next.has(r.id))) {
        rows.forEach((r) => next.delete(r.id))
      } else {
        rows.forEach((r) => next.add(r.id))
      }
      return next
    })
  }

  const handleSelectAll = async () => {
    setSelectingAll(true)
    try {
      const res = await deliverablesApi.allIds({ category_id: activeCatId, search })
      const next = new Set([...selectedIds, ...res.ids])
      setSelectedIds(next)
      if (res.truncated) {
        toast.warning(`已选 ${res.ids.length} 个（超过 10000 上限，请缩小搜索范围）`)
      } else {
        toast.success(`已全选 ${res.ids.length} 个材料`)
      }
    } catch (err) {
      toast.error(err.message || '全选失败')
    } finally {
      setSelectingAll(false)
    }
  }

  const handleClearSelection = () => {
    setSelectedIds(new Set())
  }

  const handleBatchDownload = async () => {
    const ids = [...selectedIds]
    if (ids.length === 0) {
      toast.warning('请先选择要下载的文件')
      return
    }
    setBatchDownloading(true)
    try {
      await deliverablesApi.batchDownload(ids)
      toast.success(`开始下载 ${ids.length} 个文件（zip）`)
      setSelectedIds(new Set())
    } catch (err) {
      toast.error(err.message || '批量下载失败')
    } finally {
      setBatchDownloading(false)
    }
  }

  // 批量删除材料（仅 canDelete 可见，二次确认 + 同步清理落盘文件由后端完成）
  const handleBatchDelete = async () => {
    const ids = [...selectedIds]
    if (ids.length === 0) {
      toast.warning('请先选择要删除的文件')
      return
    }
    if (batchDeleting) return
    const ok = await confirm({
      title: `批量删除 ${ids.length} 个材料？`,
      message: '将同时删除对应的落盘文件，操作不可恢复。请确认未误选。',
      confirmText: '确认删除',
    })
    if (!ok) return
    setBatchDeleting(true)
    try {
      const res = await deliverablesApi.batchRemove(ids)
      const msg = `已删除 ${res.deleted} 个材料`
      toast.success(res.not_found > 0 ? `${msg}（${res.not_found} 个未找到已跳过）` : msg)
      setSelectedIds(new Set())
      await loadDeliverables()
      await loadCategories()
    } catch (err) {
      toast.error(err.message || '批量删除失败')
    } finally {
      setBatchDeleting(false)
    }
  }

  // 导出目录：将目录及其所有子目录递归打包为 zip（保留目录结构）
  const handleExportCategory = async (node) => {
    if (!node || !node.id) return
    if (exportingCatId) return
    setExportingCatId(node.id)
    setExportProgress({ phase: 'packing', percent: 0, name: node.name })
    try {
      const { count } = await deliverablesApi.exportCategory(node.id, (pct, phase, loaded) => {
        setExportProgress({ phase, percent: pct, loaded, name: node.name })
      })
      toast.success(`已导出「${node.name}」共 ${count} 个文件（zip）`)
    } catch (err) {
      toast.error(err.message || '导出目录失败')
    } finally {
      setExportingCatId(null)
      setTimeout(() => setExportProgress(null), 800)
    }
  }

  // ===== 树形节点递归渲染 =====
  // 层级缩进表：一级 16 → 二级 32 → 三级 52 → 四级 72 → ...每级固定 20px 递进
  const INDENTS = [16, 32, 52, 72, 92, 112, 132, 152, 172, 192]
  // 层级字号表：0-1 级 text-sm，2 级 text-[13px]，3+ 级 text-xs
  const FONT_SIZES = ['text-sm', 'text-sm', 'text-[13px]', 'text-xs', 'text-xs', 'text-xs', 'text-xs', 'text-xs', 'text-xs', 'text-xs']

  const renderTreeNode = (node, depth = 0) => {
    const active = node.id === activeCatId
    const expanded = expandedIds.has(node.id)
    const hasChildren = (node.descendant_count || 0) > 0
    const isEmpty = (node.deliverable_count || 0) === 0
    const indent = INDENTS[depth] || 192
    const fontSize = FONT_SIZES[depth] || 'text-xs'
    return (
      <div key={node.id}>
        <div
          role="button"
          tabIndex={0}
          onClick={() => {
            setActiveCatId(node.id)
            setPage(1)
            if (hasChildren) toggleExpand(node.id)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              setActiveCatId(node.id)
              setPage(1)
              if (hasChildren) toggleExpand(node.id)
            }
          }}
          onContextMenu={(e) => {
            e.preventDefault()
            e.stopPropagation()
            setContextMenu({ x: e.clientX, y: e.clientY, node })
          }}
          style={{ paddingLeft: `${indent}px` }}
          className={`group relative mb-0.5 flex cursor-pointer items-center gap-1 rounded-md py-1.5 pr-2 transition-colors ${
            active
              ? 'bg-[#00d4aa]/10'
              : 'hover:bg-muted/60'
          }`}
        >
          {/* 选中态：左侧 3px 青色竖线 */}
          {active && (
            <span
              className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r"
              style={{ background: '#00d4aa' }}
            />
          )}
          {/* 展开/折叠按钮 */}
          {hasChildren ? (
            <button
              type="button"
              title={expanded ? '折叠' : '展开'}
              className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={(e) => {
                e.stopPropagation()
                toggleExpand(node.id)
              }}
            >
              {expanded ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
            </button>
          ) : (
            <span className="inline-block w-[18px] shrink-0" aria-hidden />
          )}
          {/* 目录图标：空目录灰色，实目录亮色，选中青色 */}
          {expanded || hasChildren ? (
            <FolderOpen
              className={`h-4 w-4 shrink-0 ${
                active ? 'text-[#00d4aa]' : isEmpty ? 'text-[#484f58]' : 'text-amber-500/80'
              }`}
            />
          ) : (
            <Folder
              className={`h-4 w-4 shrink-0 ${
                active ? 'text-[#00d4aa]' : isEmpty ? 'text-[#484f58]' : 'text-amber-500/80'
              }`}
            />
          )}
          {/* 目录名称：空目录灰色，截断 + tooltip */}
          <span
            className={`min-w-0 flex-1 truncate ${fontSize} ${
              active
                ? 'font-medium text-[#00d4aa]'
                : isEmpty
                  ? 'text-[#484f58]'
                  : 'text-[#c9d1d9]'
            }`}
            title={node.name}
          >
            {node.name}
          </span>
          {/* 数字徽章 */}
          <span
            className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] tabular-nums ${
              active
                ? 'bg-[#00d4aa]/15 text-[#00d4aa]'
                : isEmpty
                  ? 'bg-[#21262d] text-[#484f58]'
                  : 'bg-[#21262d] text-[#8b949e]'
            }`}
          >
            {node.deliverable_count}
          </span>
          {/* 悬停操作按钮组：渐变显示 */}
          {canEdit && (
            <span className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-0.5 rounded-md border border-border bg-card px-1 py-0.5 opacity-0 shadow-sm transition-opacity duration-150 group-hover:opacity-100">
              {node.level < MAX_LEVEL && (
                <button
                  type="button"
                  title="新建子目录"
                  className="rounded p-0.5 text-muted-foreground hover:text-primary"
                  onClick={(e) => {
                    e.stopPropagation()
                    setCatModal({
                      mode: 'create',
                      name: '',
                      description: '',
                      parentId: node.id,
                      parentName: node.name,
                      parentLevel: node.level,
                    })
                  }}
                >
                  <FolderPlus className="h-3 w-3" />
                </button>
              )}
              <button
                type="button"
                title="编辑目录"
                className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                onClick={(e) => {
                  e.stopPropagation()
                  setCatModal({
                    mode: 'edit',
                    id: node.id,
                    name: node.name,
                    description: node.description || '',
                    parentId: node.parent_id,
                  })
                }}
              >
                <Pencil className="h-3 w-3" />
              </button>
              <button
                type="button"
                title="移动目录"
                className="rounded p-0.5 text-muted-foreground hover:text-primary"
                onClick={(e) => {
                  e.stopPropagation()
                  setMoveModal({
                    id: node.id,
                    name: node.name,
                    description: node.description || '',
                    currentParentId: node.parent_id,
                    targetParentId: node.parent_id || 0,
                  })
                }}
              >
                <Move className="h-3 w-3" />
              </button>
              <button
                type="button"
                title="导出目录（递归打包 zip）"
                disabled={exportingCatId === node.id}
                className="rounded p-0.5 text-muted-foreground hover:text-primary disabled:opacity-50"
                onClick={(e) => {
                  e.stopPropagation()
                  handleExportCategory(node)
                }}
              >
                {exportingCatId === node.id ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <FolderArchive className="h-3 w-3" />
                )}
              </button>
              {canDelete && (
                <button
                  type="button"
                  title="删除目录"
                  className="rounded p-0.5 text-muted-foreground hover:text-red-500"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleConfirmDelete({
                      type: 'category',
                      id: node.id,
                      name: node.name,
                    })
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              )}
            </span>
          )}
        </div>
        {/* 子节点容器：纯缩进，无竖线 */}
        {expanded && hasChildren && (
          <div>
            {node.children.map((child) => renderTreeNode(child, depth + 1))}
          </div>
        )}
      </div>
    )
  }

  // 父级目录下拉选项（带缩进前缀，供新建目录弹窗使用）
  const parentOptions = useMemo(() => {
    const opts = [{ id: 0, label: '根级（最顶层）' }]
    const sorted = [...categories].sort((a, b) => (a.level || 1) - (b.level || 1))
    sorted.forEach((c) => {
      const d = Math.max(0, (c.level || 1) - 1)
      const prefix = '\u00A0\u00A0\u00A0\u00A0'.repeat(d) + (d > 0 ? '└ ' : '')
      opts.push({ id: c.id, label: prefix + c.name })
    })
    return opts
  }, [categories])

  // ===== 渲染 =====
  return (
    <PageContainer>
      <PageHeader
        title="材料管理"
        description="按树形目录归档管理交付文件，支持最多 10 级子目录"
        actions={
          <div className="flex items-center gap-2">
            <TutorialButton onClick={() => setTutorialOpen(true)} />
            {canEdit && (
              <>
                <Button size="sm" variant="secondary" onClick={() => setCatModal({ mode: 'create', name: '', description: '', parentId: 0 })}>
                  <FolderPlus className="h-3.5 w-3.5" />
                  新建目录
                </Button>
                <Button
                  size="sm"
                  disabled={!activeCatId}
                  onClick={() => setUploadModal({ files: [], version: '', description: '' })}
                >
                  <CloudUpload className="h-3.5 w-3.5" />
                  上传材料
                </Button>
              </>
            )}
          </div>
        }
      />

      {/* 紧凑统计条 */}
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-border bg-card px-4 py-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <FolderOpen className="h-3.5 w-3.5 text-primary" />
          目录总数 <b className="text-foreground tabular-nums">{categories.length}</b>
        </span>
        <span className="h-3 w-px bg-border" aria-hidden />
        <span className="flex items-center gap-1.5">
          <HardDrive className="h-3.5 w-3.5 text-primary" />
          材料总数 <b className="text-foreground tabular-nums">{totalFiles}</b>
        </span>
        {activeCat && (
          <>
            <span className="h-3 w-px bg-border" aria-hidden />
            <span className="flex items-center gap-1.5">
              当前目录
              <span className="inline-flex items-center gap-1 rounded-full bg-[#00d4aa]/15 px-2 py-0.5 font-medium text-[#00d4aa]">
                {activeCat.name}
              </span>
              含子目录共 <b className="text-foreground tabular-nums">{activeCat.deliverable_count || 0}</b> 个材料
            </span>
          </>
        )}
        <span className="ml-auto text-muted-foreground/60">支持 xlsx / word / pdf / zip 等 13 种类型，单文件 ≤ 200MB</span>
      </div>

      {/* 面包屑导航 */}
      {breadcrumbPath.length > 0 && (
        <nav className="mb-3 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
          {breadcrumbPath.map((cat, idx) => (
            <span key={cat.id} className="flex items-center gap-1">
              {idx > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground/60" />}
              <button
                type="button"
                className={`rounded px-1.5 py-0.5 hover:bg-muted hover:text-foreground ${
                  idx === breadcrumbPath.length - 1 ? 'font-medium text-foreground' : ''
                }`}
                onClick={() => {
                  setActiveCatId(cat.id)
                  setPage(1)
                }}
                title="跳转到此目录"
              >
                {cat.name}
              </button>
            </span>
          ))}
        </nav>
      )}

      {/* 主体三栏布局 */}
      <div className="flex gap-0">
        {/* 左：目录树 */}
        <aside
          className="flex shrink-0 flex-col rounded-l-lg border border-r-0 border-border bg-card"
          style={{ width: treeWidth }}
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
            <span className="text-xs font-semibold text-muted-foreground">目录结构</span>
            <div className="flex items-center gap-1">
              {categories.length > 0 && (
                <>
                  <button
                    type="button"
                    title="全部展开"
                    className="rounded p-1 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                    onClick={() => {
                      const all = new Set(categories.map((c) => c.id))
                      setExpandedIds(all)
                      localStorage.setItem('soar_dlv_expanded', JSON.stringify([...all]))
                    }}
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    title="一键收起"
                    className="rounded p-1 text-muted-foreground hover:bg-primary/10 hover:text-primary disabled:opacity-40 disabled:hover:bg-transparent"
                    disabled={expandedIds.size === 0}
                    onClick={() => {
                      setExpandedIds(new Set())
                      localStorage.setItem('soar_dlv_expanded', '[]')
                    }}
                  >
                    <ChevronsUp className="h-3.5 w-3.5" />
                  </button>
                </>
              )}
              {canEdit && (
                <button
                  type="button"
                  title="新建根目录"
                  className="rounded p-1 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                  onClick={() => setCatModal({ mode: 'create', name: '', description: '', parentId: 0 })}
                >
                  <FolderPlus className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
          <div className="min-h-[120px] max-h-[calc(100vh-260px)] flex-1 overflow-y-auto p-2">
            {catLoading && categories.length === 0 ? (
              <div className="px-2 py-6 text-center text-xs text-muted-foreground">加载中…</div>
            ) : categories.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-2 py-6 text-center text-xs text-muted-foreground">
                <FolderPlus className="h-6 w-6 text-muted-foreground/50" />
                <span>暂无目录</span>
                {canEdit && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setCatModal({ mode: 'create', name: '', description: '', parentId: 0 })}
                  >
                    <FolderPlus className="h-3.5 w-3.5" />
                    新建目录
                  </Button>
                )}
              </div>
            ) : (
              tree.map((node) => renderTreeNode(node, 0))
            )}
          </div>
          <div className="flex items-center justify-between border-t border-border px-3 py-2 text-[10px] text-muted-foreground">
            <span className="tabular-nums">
              共 {categories.length} 个目录
              {expandedIds.size > 0 && (
                <span className="ml-1 text-primary/80">· 已展开 {expandedIds.size}</span>
              )}
            </span>
            {expandedIds.size > 0 && (
              <button
                type="button"
                title="一键收起全部目录"
                className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-primary/10 hover:text-primary"
                onClick={() => {
                  setExpandedIds(new Set())
                  localStorage.setItem('soar_dlv_expanded', '[]')
                }}
              >
                <ChevronsUp className="h-3 w-3" />
                收起
              </button>
            )}
          </div>
        </aside>

        {/* 拖拽分隔条 */}
        <div
          onMouseDown={handleResizeStart}
          className={`group relative z-10 w-1 shrink-0 cursor-col-resize border-y border-border transition-colors ${
            treeResizing ? 'bg-primary' : 'bg-border hover:bg-primary/50'
          }`}
          title="拖拽调节目录宽度"
        >
          <div className="absolute inset-y-0 -left-1 -right-1" />
        </div>

        {/* 中：材料列表 */}
        <section className="flex min-w-0 flex-1 flex-col rounded-lg border border-border bg-card">
          {/* 工具栏 */}
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              <FolderOpen className="h-3.5 w-3.5" />
              {activeCat ? activeCat.name : '未选择目录'}
            </span>
            <span className="text-xs text-muted-foreground">
              本目录 {total} 个
              {activeCat && (activeCat.deliverable_count || 0) > total && (
                <span className="ml-1 text-muted-foreground/70">/ 含子目录共 {activeCat.deliverable_count} 个</span>
              )}
            </span>
            {selectedIds.size > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/15 px-2.5 py-1 text-xs font-medium text-primary">
                已选 {selectedIds.size} 个
                <button
                  type="button"
                  className="ml-0.5 rounded text-primary/70 hover:text-primary"
                  onClick={handleClearSelection}
                  title="清空选择"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}
            <div className="ml-auto flex items-center gap-2">
              {selectedIds.size > 0 && (
                <Button
                  size="sm"
                  variant="secondary"
                  loading={batchDownloading}
                  onClick={handleBatchDownload}
                >
                  <Download className="h-3.5 w-3.5" />
                  批量下载 ({selectedIds.size})
                </Button>
              )}
              {selectedIds.size > 0 && canDelete && (
                <Button
                  size="sm"
                  variant="danger"
                  loading={batchDeleting}
                  onClick={handleBatchDelete}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  批量删除 ({selectedIds.size})
                </Button>
              )}
              {/* 列表/网格视图切换按钮组 */}
              <div className="flex items-center rounded-md border border-border p-0.5">
                <button
                  type="button"
                  title="列表视图"
                  className={`rounded p-1.5 ${viewMode === 'list' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground'}`}
                  onClick={() => changeViewMode('list')}
                >
                  <List className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  title="网格视图"
                  className={`rounded p-1.5 ${viewMode === 'grid' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground'}`}
                  onClick={() => changeViewMode('grid')}
                >
                  <LayoutGrid className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <input
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSearch()
                  }}
                  placeholder="搜索名称 / 文件名 / 版本"
                  className="w-52 rounded-md border border-border bg-background py-1.5 pl-8 pr-3 text-xs text-foreground outline-none focus:border-primary"
                />
              </div>
              <Button size="sm" variant="secondary" onClick={handleSearch}>搜索</Button>
            </div>
          </div>

          {/* 内容区 */}
          {!activeCat ? (
            <EmptyState
              icon={<FolderPlus className="h-10 w-10" />}
              title="请先创建目录"
              description={canEdit ? '点击下方按钮或左上角「新建目录」开始归档材料' : '等待管理员创建目录'}
              action={
                canEdit && (
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setCatModal({ mode: 'create', name: '', description: '', parentId: 0 })}
                    >
                      <FolderPlus className="h-3.5 w-3.5" />
                      新建目录
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setUploadModal({ files: [], version: '', description: '' })}
                      disabled
                    >
                      <CloudUpload className="h-3.5 w-3.5" />
                      上传材料
                    </Button>
                  </div>
                )
              }
              className="py-20"
            />
          ) : loading ? (
            <div className="px-4 py-12 text-center text-sm text-muted-foreground">加载中…</div>
          ) : (
            <>
              {/* 子目录文件夹卡片 */}
              {subCategories.length > 0 && !search && (
                <div className="border-b border-border px-4 py-3">
                  <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <Folder className="h-3.5 w-3.5" />
                    子目录（{subCategories.length}）
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {subCategories.map((cat) => (
                      <div
                        key={cat.id}
                        onClick={() => { setActiveCatId(cat.id); setPage(1) }}
                        onDoubleClick={() => enterSubCategory(cat)}
                        title={`双击进入「${cat.name}」`}
                        className="group flex w-36 cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-border bg-card p-3 transition-colors hover:border-primary/40 hover:bg-primary/5"
                      >
                        <Folder className="h-8 w-8 text-amber-500/80 transition-transform group-hover:scale-110" />
                        <span
                          className="w-full truncate text-center text-xs font-medium text-foreground"
                          title={cat.name}
                        >
                          {cat.name}
                        </span>
                        <span className="text-[10px] text-muted-foreground tabular-nums">
                          {cat.deliverable_count || 0} 个材料
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {rows.length === 0 ? (
            <EmptyState
              icon={
                search ? (
                  <Search className="h-10 w-10" />
                ) : (
                  <CloudUpload className="h-10 w-10" />
                )
              }
              title={search ? '未找到匹配的材料' : '该目录暂无材料'}
              description={
                search
                  ? '换个关键词试试，或清空搜索查看全部'
                  : canEdit
                    ? `可直接上传文件到此目录${(activeCat.deliverable_count || 0) > 0 ? `，子目录中共有 ${activeCat.deliverable_count} 个材料` : ''}`
                    : '等待有权限的用户上传'
              }
              action={
                <div className="flex items-center gap-2">
                  {search && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setSearchInput('')
                        setSearch('')
                        setPage(1)
                      }}
                    >
                      清空搜索
                    </Button>
                  )}
                  {!search && canEdit && (
                    <Button
                      size="sm"
                      onClick={() => setUploadModal({ files: [], version: '', description: '' })}
                    >
                      <CloudUpload className="h-3.5 w-3.5" />
                      上传材料
                    </Button>
                  )}
                  {!search && canEdit && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setCatModal({ mode: 'create', name: '', description: '', parentId: activeCatId || 0, parentName: activeCat?.name })}
                    >
                      <FolderPlus className="h-3.5 w-3.5" />
                      新建子目录
                    </Button>
                  )}
                </div>
              }
              className="py-16"
            />
          ) : viewMode === 'grid' ? (
            // 网格视图
            <div className="grid grid-cols-2 gap-3 p-4 md:grid-cols-3 xl:grid-cols-4">
              {rows.map((r) => {
                const checked = selectedIds.has(r.id)
                const canPreview = PREVIEWABLE_EXTS.includes((r.file_ext || '').toLowerCase())
                return (
                  <div
                    key={r.id}
                    className={`group relative flex flex-col gap-2 rounded-lg border p-3 transition-colors ${
                      canPreview ? 'cursor-pointer hover:border-primary/40 hover:bg-primary/5' : ''
                    } ${checked ? 'border-primary/40 bg-primary/5' : 'border-border bg-card'}`}
                    onClick={() => canPreview && handlePreview(r)}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleRow(r.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="absolute left-2 top-2 h-3.5 w-3.5 cursor-pointer rounded border-border accent-primary"
                    />
                    {r.version && (
                      <span className="absolute right-2 top-2 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-foreground">
                        {r.version}
                      </span>
                    )}
                    <div className="flex flex-col items-center gap-2 pt-5 text-center">
                      <FileIcon ext={r.file_ext} className="h-8 w-8" />
                      <span
                        className="w-full text-xs font-medium text-foreground"
                        style={{
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                          wordBreak: 'break-word',
                        }}
                        title={r.name}
                      >
                        {r.name}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                      <span className="truncate" title={r.filename}>{r.filename}</span>
                      <span className="shrink-0 tabular-nums">{fmtSize(r.file_size)}</span>
                    </div>
                    <div
                      className="flex items-center justify-end gap-1 border-t border-border/60 pt-2 opacity-0 transition-opacity group-hover:opacity-100"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {canPreview && (
                        <button
                          type="button"
                          title="预览"
                          className="rounded p-1 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                          onClick={() => handlePreview(r)}
                        >
                          <Eye className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        title="下载"
                        className="rounded p-1 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                        onClick={() => handleDownload(r)}
                      >
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      {canEdit && (
                        <button
                          type="button"
                          title="编辑"
                          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                          onClick={() =>
                            setEditModal({
                              id: r.id,
                              name: r.name,
                              version: r.version || '',
                              description: r.description || '',
                              file: null,
                              filename: r.filename,
                            })
                          }
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {canDelete && (
                        <button
                          type="button"
                          title="删除"
                          className="rounded p-1 text-muted-foreground hover:bg-red-500/10 hover:text-red-500"
                          onClick={() => handleConfirmDelete({ type: 'deliverable', id: r.id, name: r.name, filename: r.filename })}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            // 列表视图
            <div className="overflow-x-auto">
              <table className="w-full table-fixed border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/30 text-left text-xs text-muted-foreground">
                    <th className="w-12 px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={allChecked}
                          ref={(el) => {
                            if (el) el.indeterminate = someChecked && !allChecked
                          }}
                          onChange={toggleAll}
                          className="h-3.5 w-3.5 cursor-pointer rounded border-border accent-primary"
                          title={allChecked ? '取消选中当前页' : '全选当前页'}
                        />
                        {total > rows.length && selectedIds.size < total && (
                          <button
                            type="button"
                            disabled={selectingAll}
                            onClick={handleSelectAll}
                            className="truncate text-xs text-primary hover:underline disabled:opacity-50"
                            title="选中当前条件下所有材料（含其他页）"
                          >
                            {selectingAll ? '加载中…' : `全选 ${total}`}
                          </button>
                        )}
                      </div>
                    </th>
                    <th className="px-4 py-2.5 font-medium">材料名称</th>
                    <th className="w-40 px-4 py-2.5 font-medium">文件</th>
                    <th className="w-20 px-4 py-2.5 font-medium">版本</th>
                    <th className="w-20 px-4 py-2.5 font-medium">大小</th>
                    <th className="w-24 px-4 py-2.5 font-medium">上传人</th>
                    <th className="w-36 px-4 py-2.5 font-medium">上传时间</th>
                    <th className="w-32 px-4 py-2.5 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const checked = selectedIds.has(r.id)
                    return (
                      <tr key={r.id} className={`border-b border-border/60 transition-colors last:border-0 hover:bg-primary/5 ${checked ? 'bg-primary/5' : ''}`}>
                        <td className="px-4 py-2.5">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleRow(r.id)}
                            className="h-3.5 w-3.5 cursor-pointer rounded border-border accent-primary"
                          />
                        </td>
                        <td className="min-w-0 px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <FileIcon ext={r.file_ext} className="h-4 w-4 shrink-0" />
                            <div className="min-w-0 flex-1">
                              <div className="truncate font-medium text-foreground" title={r.name}>{r.name}</div>
                              {r.description && (
                                <div className="truncate text-xs text-muted-foreground" title={r.description}>{r.description}</div>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="min-w-0 px-4 py-2.5">
                          <span className="block truncate text-xs text-muted-foreground" title={r.filename}>{r.filename}</span>
                        </td>
                        <td className="px-4 py-2.5">
                          {r.version ? (
                            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-foreground">{r.version}</span>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs tabular-nums text-muted-foreground">{fmtSize(r.file_size)}</td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">{r.creator_name || '—'}</td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs tabular-nums text-muted-foreground">{fmtTime(r.created_at)}</td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-right">
                          <span className="inline-flex items-center gap-1">
                            {PREVIEWABLE_EXTS.includes((r.file_ext || '').toLowerCase()) && (
                              <button
                                type="button"
                                title="预览"
                                className="rounded p-1.5 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                                onClick={() => handlePreview(r)}
                              >
                                <Eye className="h-3.5 w-3.5" />
                              </button>
                            )}
                            <button
                              type="button"
                              title="下载"
                              className="rounded p-1.5 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                              onClick={() => handleDownload(r)}
                            >
                              <Download className="h-3.5 w-3.5" />
                            </button>
                            {canEdit && (
                              <button
                                type="button"
                                title="编辑"
                                className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                                onClick={() =>
                                  setEditModal({
                                    id: r.id,
                                    name: r.name,
                                    version: r.version || '',
                                    description: r.description || '',
                                    file: null,
                                    filename: r.filename,
                                  })
                                }
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                            )}
                            {canDelete && (
                              <button
                                type="button"
                                title="删除"
                                className="rounded p-1.5 text-muted-foreground hover:bg-red-500/10 hover:text-red-500"
                                onClick={() => handleConfirmDelete({ type: 'deliverable', id: r.id, name: r.name, filename: r.filename })}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {activeCat && total > 0 && (
            <div className="border-t border-border px-4 py-3">
              <Pagination
                page={page}
                pageSize={pageSize}
                total={total}
                onPageChange={setPage}
                onPageSizeChange={(s) => {
                  setPageSize(s)
                  setPage(1)
                }}
                pageSizeOptions={[10, 20, 50]}
              />
            </div>
          )}
            </>
          )}
        </section>

        {/* 右：预览面板（仅 previewModal 存在时显示） */}
        {previewModal && (
          <aside className="flex w-96 shrink-0 flex-col rounded-lg border border-border bg-card">
            {/* 标题栏 */}
            <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <FileIcon ext={previewModal.row.file_ext} className="h-4 w-4 shrink-0" />
                <span className="truncate text-sm font-medium text-foreground" title={previewModal.row.filename}>
                  {previewModal.row.filename}
                </span>
                <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {fmtSize(previewModal.row.file_size)}
                </span>
                {previewModal.type === 'text' && previewModal.dirty && (
                  <span className="shrink-0 text-[10px] text-amber-500">未保存</span>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {previewModal.type === 'text' && canEdit && (
                  <Button
                    size="sm"
                    loading={previewSaving}
                    disabled={previewSaving || !previewModal.dirty}
                    onClick={handleSaveContent}
                  >
                    <Save className="h-3.5 w-3.5" />
                    保存
                  </Button>
                )}
                <button
                  type="button"
                  className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  onClick={closePreview}
                  title="关闭预览"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            {/* 内容区 */}
            <div
              className="flex min-h-0 flex-1 flex-col overflow-hidden"
              style={{ maxHeight: 'calc(100vh - 200px)' }}
            >
              {previewModal.loading ? (
                <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  加载中…
                </div>
              ) : previewModal.error ? (
                <div className="flex h-64 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
                  <p className="text-red-500">{previewModal.error}</p>
                  <Button size="sm" variant="secondary" onClick={() => handleDownload(previewModal.row)}>
                    <Download className="h-3.5 w-3.5" />
                    下载文件
                  </Button>
                </div>
              ) : previewModal.type === 'pdf' && previewModal.blobUrl ? (
                <iframe
                  src={previewModal.blobUrl}
                  title="PDF 预览"
                  className="w-full flex-1 border-0"
                  style={{ minHeight: '400px' }}
                />
              ) : previewModal.type === 'text' ? (
                <textarea
                  value={previewModal.content}
                  onChange={(e) =>
                    setPreviewModal((prev) => ({
                      ...prev,
                      content: e.target.value,
                      dirty: e.target.value !== prev.original,
                    }))
                  }
                  readOnly={!canEdit}
                  spellCheck={false}
                  placeholder={canEdit ? '在此编辑文件内容…' : '无编辑权限，只读模式'}
                  className="w-full flex-1 resize-none border-0 bg-background p-4 font-mono text-sm leading-relaxed text-foreground outline-none"
                  style={{ minHeight: '400px' }}
                />
              ) : previewModal.type === 'unsupported' ? (
                <div className="flex h-64 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
                  <FileArchive className="h-10 w-10 text-muted-foreground/50" />
                  <p>该文件类型（.{previewModal.row.file_ext}）暂不支持在线预览</p>
                  <p className="text-xs">支持预览：PDF / TXT / CSV / MD</p>
                  <Button size="sm" variant="secondary" onClick={() => handleDownload(previewModal.row)}>
                    <Download className="h-3.5 w-3.5" />
                    下载文件
                  </Button>
                </div>
              ) : null}
            </div>
          </aside>
        )}
      </div>

      {/* 右键菜单（fixed 定位） */}
      {contextMenu && contextMenu.node && (
        <div
          className="fixed z-50 min-w-[160px] rounded-md border border-border bg-card py-1 shadow-lg"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          {contextMenu.node.level < MAX_LEVEL && (
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground hover:bg-muted"
              onClick={() => {
                const node = contextMenu.node
                setContextMenu(null)
                setCatModal({
                  mode: 'create',
                  name: '',
                  description: '',
                  parentId: node.id,
                  parentName: node.name,
                  parentLevel: node.level,
                })
              }}
            >
              <FolderPlus className="h-3.5 w-3.5" />
              新建子目录
            </button>
          )}
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground hover:bg-muted"
            onClick={() => {
              const node = contextMenu.node
              setContextMenu(null)
              setCatModal({
                mode: 'edit',
                id: node.id,
                name: node.name,
                description: node.description || '',
                parentId: node.parent_id,
              })
            }}
          >
            <Pencil className="h-3.5 w-3.5" />
            编辑目录
          </button>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground hover:bg-muted"
            onClick={() => {
              const node = contextMenu.node
              setContextMenu(null)
              setMoveModal({
                id: node.id,
                name: node.name,
                description: node.description || '',
                currentParentId: node.parent_id,
                targetParentId: node.parent_id || 0,
              })
            }}
          >
            <Move className="h-3.5 w-3.5" />
            移动目录
          </button>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground hover:bg-muted disabled:opacity-50"
            disabled={exportingCatId === contextMenu.node.id}
            onClick={() => {
              const node = contextMenu.node
              setContextMenu(null)
              handleExportCategory(node)
            }}
          >
            {exportingCatId === contextMenu.node.id ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <FolderArchive className="h-3.5 w-3.5" />
            )}
            {exportingCatId === contextMenu.node.id ? '导出中...' : '导出目录'}
          </button>
          {canDelete && (
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-red-500 hover:bg-red-500/10"
              onClick={() => {
                const node = contextMenu.node
                setContextMenu(null)
                handleConfirmDelete({
                  type: 'category',
                  id: node.id,
                  name: node.name,
                })
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
              删除目录
            </button>
          )}
        </div>
      )}

      {/* 目录新建/编辑弹窗 */}
      {catModal && (
        <Modal
          title={catModal.mode === 'create' ? (catModal.parentId ? '新建子目录' : '新建根目录') : '编辑目录'}
          onClose={() => setCatModal(null)}
          footer={
            <>
              <Button size="sm" variant="secondary" onClick={() => setCatModal(null)}>取消</Button>
              {/* 创建模式：保存并继续 */}
              {catModal.mode === 'create' && (
                <Button
                  size="sm"
                  variant="secondary"
                  loading={catSaving}
                  onClick={() => handleCatSave(true)}
                >
                  保存并继续
                </Button>
              )}
              <Button size="sm" loading={catSaving} onClick={() => handleCatSave(false)}>保存</Button>
            </>
          }
        >
          {catModal.mode === 'create' ? (
            // 创建模式：下拉选择父级目录
            <Field label="父级目录" hint="可选择任意已有目录作为父级，「根级」为最顶层">
              <select
                value={catModal.parentId || 0}
                onChange={(e) => {
                  const pid = Number(e.target.value) || 0
                  const parent = pid ? categories.find((c) => c.id === pid) : null
                  setCatModal({
                    ...catModal,
                    parentId: pid,
                    parentName: parent ? parent.name : '',
                    parentLevel: parent ? parent.level : 0,
                  })
                }}
                className={inputCls}
              >
                {parentOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            // 编辑模式：只读显示父级
            catModal.parentId ? (
              <Field label="父级目录">
                <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                  {categories.find((c) => c.id === catModal.parentId)?.name || '根级'}
                </div>
              </Field>
            ) : null
          )}
          <Field label="目录名称">
            <input
              autoFocus
              value={catModal.name}
              onChange={(e) => setCatModal({ ...catModal, name: e.target.value })}
              maxLength={100}
              placeholder="输入目录名称"
              className={inputCls}
            />
          </Field>
          <Field label="描述（可选）">
            <textarea
              value={catModal.description}
              onChange={(e) => setCatModal({ ...catModal, description: e.target.value })}
              maxLength={500}
              rows={2}
              placeholder="该目录的归档范围说明"
              className={`${inputCls} resize-none`}
            />
          </Field>
        </Modal>
      )}

      {/* 上传弹窗（支持多文件 + 拖拽） */}
      {uploadModal && (
        <Modal
          title="上传材料"
          onClose={() => !uploading && setUploadModal(null)}
          footer={
            <>
              <Button size="sm" variant="secondary" disabled={uploading} onClick={() => setUploadModal(null)}>
                {uploading ? '关闭' : '取消'}
              </Button>
              <Button
                size="sm"
                loading={uploading}
                disabled={uploading || (uploadModal.files || []).every((f) => f.status === 'success')}
                onClick={handleUpload}
              >
                上传{(uploadModal.files || []).filter((f) => f.status !== 'success').length > 0
                  ? ` (${(uploadModal.files || []).filter((f) => f.status !== 'success').length})`
                  : ''}
              </Button>
            </>
          }
        >
          {/* 大面积拖拽区域 */}
          <div
            onDragOver={(e) => {
              e.preventDefault()
              if (!uploading) setDragOver(true)
            }}
            onDragLeave={(e) => {
              e.preventDefault()
              setDragOver(false)
            }}
            onDrop={(e) => {
              e.preventDefault()
              setDragOver(false)
              if (uploading) return
              const dropped = Array.from(e.dataTransfer.files || [])
              if (dropped.length === 0) return
              setUploadModal((prev) => ({
                ...prev,
                files: [...(prev.files || []), ...dropped.map((file) => ({ file, status: 'pending' }))],
              }))
            }}
            onClick={() => !uploading && document.getElementById('dlv-upload-input')?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors ${
              dragOver
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-primary/50 hover:bg-muted/40'
            }`}
          >
            <Upload className="h-8 w-8 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium text-foreground">拖拽文件到此处</p>
              <p className="text-xs text-muted-foreground">
                或点击选择文件（支持 {ALLOWED_EXTS.length} 种类型，单文件 ≤ 200MB，可多选）
              </p>
            </div>
            <input
              id="dlv-upload-input"
              type="file"
              multiple
              accept={ALLOWED_EXTS.map((e) => `.${e}`).join(',')}
              onChange={(e) => {
                const picked = Array.from(e.target.files || [])
                if (picked.length === 0) return
                setUploadModal((prev) => ({
                  ...prev,
                  files: [...(prev.files || []), ...picked.map((file) => ({ file, status: 'pending' }))],
                }))
                e.target.value = ''
              }}
              onClick={(e) => e.stopPropagation()}
              className="hidden"
            />
          </div>

          {/* 待上传列表 */}
          {(uploadModal.files || []).length > 0 && (
            <div className="mt-3 max-h-44 overflow-y-auto rounded-md border border-border">
              {(uploadModal.files || []).map((item, idx) => (
                <div
                  key={idx}
                  className="relative flex items-center gap-2 border-b border-border/60 px-3 py-1.5 last:border-0"
                >
                  <FileIcon ext={(item.file.name.split('.').pop() || '').toLowerCase()} className="h-3.5 w-3.5" />
                  <span className="min-w-0 flex-1 truncate text-xs text-foreground" title={item.file.name}>
                    {item.file.name}
                  </span>
                  <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                    {fmtSize(item.file.size)}
                  </span>
                  {/* 状态图标 */}
                  {item.status === 'uploading' && (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
                  )}
                  {item.status === 'success' && (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-500" />
                  )}
                  {item.status === 'failed' && (
                    <span className="shrink-0" title={item.error}>
                      <XCircle className="h-3.5 w-3.5 text-red-500" />
                    </span>
                  )}
                  {/* 移除按钮（上传中禁用） */}
                  {!uploading && (
                    <button
                      type="button"
                      title="移除"
                      className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-red-500"
                      onClick={() =>
                        setUploadModal((prev) => ({
                          ...prev,
                          files: prev.files.filter((_, i) => i !== idx),
                        }))
                      }
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                  {/* 上传中进度条（不定宽 animate-pulse） */}
                  {item.status === 'uploading' && (
                    <div className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden bg-muted">
                      <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {!uploading && (uploadModal.files || []).length > 0 && (
            <button
              type="button"
              className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
              onClick={() => document.getElementById('dlv-upload-input')?.click()}
            >
              <Plus className="h-3 w-3" />
              继续添加文件
            </button>
          )}

          {/* 统一批量设置区 */}
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Field label="版本（可选，应用于全部）">
              <input
                value={uploadModal.version}
                onChange={(e) => setUploadModal({ ...uploadModal, version: e.target.value })}
                maxLength={50}
                placeholder="如 v1.0 / 2024-06"
                className={inputCls}
              />
            </Field>
            <Field label="上传到">
              <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                {activeCat?.name || '—'}
              </div>
            </Field>
          </div>
          <Field label="描述（可选，应用于全部）">
            <textarea
              value={uploadModal.description}
              onChange={(e) => setUploadModal({ ...uploadModal, description: e.target.value })}
              rows={2}
              placeholder="材料说明"
              className={`${inputCls} resize-none`}
            />
          </Field>
        </Modal>
      )}

      {/* 编辑弹窗 */}
      {editModal && (
        <Modal
          title="编辑材料"
          onClose={() => !editSaving && setEditModal(null)}
          footer={
            <>
              <Button size="sm" variant="secondary" disabled={editSaving} onClick={() => setEditModal(null)}>取消</Button>
              <Button size="sm" loading={editSaving} onClick={handleEditSave}>保存</Button>
            </>
          }
        >
          <Field label="名称">
            <input
              value={editModal.name}
              onChange={(e) => setEditModal({ ...editModal, name: e.target.value })}
              maxLength={200}
              className={inputCls}
            />
          </Field>
          <Field label="版本（可选）">
            <input
              value={editModal.version}
              onChange={(e) => setEditModal({ ...editModal, version: e.target.value })}
              maxLength={50}
              className={inputCls}
            />
          </Field>
          <Field label="描述（可选）">
            <textarea
              value={editModal.description}
              onChange={(e) => setEditModal({ ...editModal, description: e.target.value })}
              rows={2}
              className={`${inputCls} resize-none`}
            />
          </Field>
          <Field label="替换文件（可选）" hint={editModal.file ? `新文件：${editModal.file.name}` : `当前文件：${editModal.filename}`}>
            <input
              type="file"
              accept={ALLOWED_EXTS.map((e) => `.${e}`).join(',')}
              onChange={(e) => setEditModal({ ...editModal, file: e.target.files?.[0] || null })}
              className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground file:mr-3 file:rounded file:border-0 file:bg-primary/10 file:px-2 file:py-1 file:text-primary"
            />
          </Field>
        </Modal>
      )}

      {/* 移动目录弹窗 */}
      {moveModal && (() => {
        // 排除自身及所有后代，构建可选目标列表
        const excludeIds = getDescendantIds(moveModal.id)
        excludeIds.add(moveModal.id)
        const selectable = categories.filter((c) => !excludeIds.has(c.id))
        // 构建可选目标树
        const selTree = buildTree(selectable)
        // 计算目标层级
        const targetId = moveModal.targetParentId
        let targetLevel = 1
        if (targetId) {
          const tCat = categories.find((c) => c.id === targetId)
          targetLevel = (tCat?.level || 1) + 1
        }
        const currentLevel = categories.find((c) => c.id === moveModal.id)?.level || 1
        const willChangeLevel = targetLevel !== currentLevel

        const renderMoveNode = (node, depth = 0) => {
          const selected = moveModal.targetParentId === node.id
          return (
            <div key={node.id}>
              <button
                type="button"
                style={{ paddingLeft: `${8 + depth * 16}px` }}
                onClick={() => setMoveModal({ ...moveModal, targetParentId: node.id })}
                className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-sm transition-colors ${
                  selected
                    ? 'border-primary/40 bg-primary/10 text-primary'
                    : 'border-transparent hover:bg-muted/60 text-foreground'
                }`}
              >
                <span
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                    selected ? 'border-primary' : 'border-border'
                  }`}
                >
                  {selected && <span className="h-2 w-2 rounded-full bg-primary" />}
                </span>
                {node.children.length > 0 ? (
                  <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-500/80" />
                ) : (
                  <Folder className="h-3.5 w-3.5 shrink-0 text-amber-500/80" />
                )}
                <span className="min-w-0 flex-1 truncate" title={node.name}>{node.name}</span>
                <span className="shrink-0 text-[10px] text-muted-foreground">L{node.level}</span>
              </button>
              {node.children.map((child) => renderMoveNode(child, depth + 1))}
            </div>
          )
        }

        return (
          <Modal
            title={`移动目录「${moveModal.name}」`}
            onClose={() => !moveSaving && setMoveModal(null)}
            footer={
              <>
                <Button size="sm" variant="secondary" disabled={moveSaving} onClick={() => setMoveModal(null)}>取消</Button>
                <Button
                  size="sm"
                  loading={moveSaving}
                  disabled={moveSaving || moveModal.targetParentId === (moveModal.currentParentId || 0)}
                  onClick={handleMoveSave}
                >
                  确认移动
                </Button>
              </>
            }
          >
            <Field label="选择新的父级目录" hint={willChangeLevel ? `层级将从 L${currentLevel} 变为 L${targetLevel}` : `层级保持 L${currentLevel}（≤ ${MAX_LEVEL}）`}>
              <div className="max-h-64 overflow-y-auto rounded-md border border-border p-1.5">
                {/* 根级选项 */}
                <button
                  type="button"
                  onClick={() => setMoveModal({ ...moveModal, targetParentId: 0 })}
                  className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-sm transition-colors ${
                    moveModal.targetParentId === 0
                      ? 'border-primary/40 bg-primary/10 text-primary'
                      : 'border-transparent hover:bg-muted/60 text-foreground'
                  }`}
                >
                  <span
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                      moveModal.targetParentId === 0 ? 'border-primary' : 'border-border'
                    }`}
                  >
                    {moveModal.targetParentId === 0 && <span className="h-2 w-2 rounded-full bg-primary" />}
                  </span>
                  <FolderPlus className="h-3.5 w-3.5 shrink-0 text-primary" />
                  <span className="font-medium">根级（最顶层）</span>
                  <span className="shrink-0 text-[10px] text-muted-foreground">L1</span>
                </button>
                {/* 可选目录树 */}
                {selTree.length > 0 ? (
                  selTree.map((node) => renderMoveNode(node, 0))
                ) : (
                  <div className="px-2 py-4 text-center text-xs text-muted-foreground">
                    没有可选的目标目录
                  </div>
                )}
              </div>
            </Field>
            {targetLevel > MAX_LEVEL && (
              <p className="mt-2 text-xs text-red-500">
                目标层级 L{targetLevel} 超过上限 {MAX_LEVEL}，请选择更浅的父级
              </p>
            )}
          </Modal>
        )
      })}

      {/* 使用教程 */}
      <TutorialDrawer
        open={tutorialOpen}
        onClose={() => setTutorialOpen(false)}
        title="材料管理使用教程"
        subtitle="了解目录树浏览、上传材料、预览编辑与批量下载"
        sections={DELIVERABLE_TUTORIAL}
      />

      {/* 导出进度浮层 */}
      {exportProgress && (
        <div className="fixed bottom-6 right-6 z-[300] w-80 rounded-xl border border-border bg-card p-4 shadow-2xl">
          <div className="mb-2 flex items-center gap-2">
            <FolderArchive className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium text-foreground">
              {exportProgress.phase === 'packing' ? '正在打包目录' : '正在下载压缩包'}
            </span>
          </div>
          <div className="mb-1 text-xs text-muted-foreground">
            {exportProgress.phase === 'packing' ? (
              <span className="flex items-center gap-1.5">
                <Loader2 className="h-3 w-3 animate-spin" />
                服务器正在递归打包「{exportProgress.name}」的文件…
              </span>
            ) : exportProgress.percent >= 0 ? (
              <span className="tabular-nums">{exportProgress.percent}%</span>
            ) : (
              <span className="tabular-nums">已下载 {fmtSize(exportProgress.loaded || 0)}</span>
            )}
          </div>
          {/* 进度条 */}
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            {exportProgress.phase === 'packing' ? (
              <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" style={{ animation: 'slide 1.2s ease-in-out infinite' }} />
            ) : exportProgress.percent >= 0 ? (
              <div
                className="h-full rounded-full bg-primary transition-all duration-300"
                style={{ width: `${exportProgress.percent}%` }}
              />
            ) : (
              <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" />
            )}
          </div>
        </div>
      )}

      {/* 打包进度动画 keyframes */}
      <style>{`
        @keyframes slide {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(300%); }
        }
      `}</style>
    </PageContainer>
  )
}
