"""知识库文件查询工具：让 AI 直接读取上传的原始文件（Excel/CSV）并按条件查询。

与 ``search_kb``（分段级 BM25/向量检索）互补：
- ``search_kb`` 适合"语义模糊匹配"，返回相关文本段。
- ``query_kb_file`` 适合"精确结构化查询"，返回表格行列数据，AI 可按列值过滤。

查询流程：
1. 按 ``doc_id`` 或在 ``enabled_kbs`` 范围内查找文档。
2. 优先读取原始上传文件（Excel/CSV），保留完整表格结构（列名 + 行）。
3. 无原始文件时回退到 ``doc.content`` 解析（Excel 解析格式为 ``列名: 值 | 列名: 值``）。
4. 按 ``query`` 过滤行：支持关键词匹配（任意列包含）和 ``列名=值`` 条件过滤。
5. 返回结构化 JSON：``{doc_id, title, columns, rows, total, matched}``。

典型用法（Agent 工具调用）：
    query_kb_file(query="192.168.1.1", kb_id=1)
    query_kb_file(query="部门=研发部", doc_id=5)
    query_kb_file(query="", doc_id=5, limit=10)  # 查看前10行
"""
import csv
import io
import logging
import os
from typing import Any

from app.database import SessionLocal
from app.models.knowledge_base import KnowledgeDocument

logger = logging.getLogger(__name__)

# uploads 目录（与 knowledge_base.py 中 UPLOAD_DIR 一致，但本文件少一层目录）
# __file__ = backend/app/core/kb_file_query.py → 上溯 3 级到 backend/
_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "uploads",
)
# 单次查询返回行数上限
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 200


def _resolve_file_path(file_path: str | None) -> str | None:
    """将 doc.file_path（相对文件名）解析为绝对路径。"""
    if not file_path:
        return None
    abs_path = os.path.join(_UPLOAD_DIR, file_path)
    if os.path.isfile(abs_path):
        return abs_path
    return None


def _read_excel(file_path: str, sheet: str | None = None) -> list[dict[str, Any]]:
    """读取 Excel 文件，返回行字典列表（key=列名，value=单元格值）。

    Args:
        file_path: Excel 文件绝对路径。
        sheet: 指定 sheet 名，不传则读第一个 sheet。
    """
    from openpyxl import load_workbook

    wb = load_workbook(filename=file_path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = ["" if c is None else str(c).strip() for c in rows[0]]
        # 补全空列名
        for i in range(len(header)):
            if not header[i]:
                header[i] = f"列{i + 1}"
        result: list[dict[str, Any]] = []
        for row in rows[1:]:
            cells = ["" if c is None else str(c).strip() for c in row]
            if not any(cells):
                continue  # 跳过空行
            row_dict = {}
            for idx, val in enumerate(cells):
                col_name = header[idx] if idx < len(header) else f"列{idx + 1}"
                row_dict[col_name] = val
            result.append(row_dict)
        return result
    finally:
        wb.close()


def _read_csv(file_path: str) -> list[dict[str, Any]]:
    """读取 CSV 文件，返回行字典列表。"""
    with open(file_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _parse_content_table(content: str) -> list[dict[str, Any]]:
    """从 doc.content 解析表格数据（file_parser 的 Excel 格式：``列名: 值 | 列名: 值``）。

    每行格式为 ``列名: 值 | 列名: 值 | ...``，可能含 ``[Sheet名]`` 标题行。
    """
    if not content:
        return []
    rows: list[dict[str, Any]] = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("["):  # 跳过空行和 Sheet 标题
            continue
        # 按 | 分隔键值对
        pairs = line.split(" | ")
        row_dict = {}
        for pair in pairs:
            if ":" in pair:
                key, _, val = pair.partition(":")
                row_dict[key.strip()] = val.strip()
        if row_dict:
            rows.append(row_dict)
    return rows


def _parse_condition(query: str) -> tuple[str | None, str | None]:
    """解析查询条件：支持 ``列名=值`` 格式，返回 (列名, 值)；无等号则返回 (None, 关键词)。"""
    if not query:
        return None, None
    query = query.strip()
    # 支持 = == ：三种分隔符
    for sep in ["==", "=", "：", ":"]:
        if sep in query:
            col, _, val = query.partition(sep)
            col = col.strip()
            val = val.strip()
            if col and val:
                return col, val
    return None, query


def _filter_rows(
    rows: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """按查询条件过滤行。

    - ``列名=值``：匹配指定列包含该值。
    - 纯关键词：任意列的值包含该关键词即命中。
    - 空查询：不过滤，返回全部（受 limit 限制）。
    """
    if not query or not query.strip():
        return rows
    col_name, col_val = _parse_condition(query)
    matched: list[dict[str, Any]] = []
    kw_lower = (col_val or "").lower()
    for row in rows:
        if col_name:
            # 列名条件：匹配指定列
            cell_val = str(row.get(col_name, "")).lower()
            if kw_lower in cell_val:
                matched.append(row)
        else:
            # 关键词匹配：任意列包含
            found = any(kw_lower in str(v).lower() for v in row.values())
            if found:
                matched.append(row)
    return matched


def query_kb_file(
    query: str = "",
    kb_id: int | None = None,
    doc_id: int | None = None,
    sheet: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    enabled_kbs: list[int] | None = None,
) -> dict[str, Any]:
    """查询知识库文件（Excel/CSV/文本表格），返回结构化行列数据。

    Args:
        query: 查询条件。支持关键词（任意列包含）或 ``列名=值`` 精确过滤。空则返回前 limit 行。
        kb_id: 指定知识库 ID（不传则搜索 enabled_kbs 范围）。
        doc_id: 指定文档 ID（优先于 kb_id）。
        sheet: Excel sheet 名（不传则读第一个 sheet）。
        limit: 返回行数上限。
        enabled_kbs: agent 启用的知识库 ID 列表（kb_id 未指定时在此范围搜索）。

    Returns:
        ``{doc_id, title, file_type, columns, rows, total, matched, truncated}``。
        多文档命中时返回 ``{results: [...]}``。
    """
    # LLM / API 调用方可能将数值参数以字符串传入（如 limit="20"），统一强转 int
    def _coerce_int(value, default=None):
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    limit = max(1, min(_coerce_int(limit, _DEFAULT_LIMIT) or _DEFAULT_LIMIT, _MAX_LIMIT))
    kb_id = _coerce_int(kb_id)
    doc_id = _coerce_int(doc_id)
    logger.info(
        "文件查询: query=%r, kb_id=%s, doc_id=%s, sheet=%s, limit=%s",
        query, kb_id, doc_id, sheet, limit,
    )

    db = SessionLocal()
    try:
        # 确定搜索范围
        q = db.query(KnowledgeDocument)
        if doc_id is not None:
            q = q.filter(KnowledgeDocument.id == doc_id)
        elif kb_id is not None:
            q = q.filter(KnowledgeDocument.kb_id == kb_id)
        elif enabled_kbs:
            q = q.filter(KnowledgeDocument.kb_id.in_(enabled_kbs))
        else:
            return {"error": "未指定查询范围（需提供 doc_id / kb_id / enabled_kbs）"}

        docs = q.all()
        if not docs:
            return {"error": "未找到匹配的文档", "query": query}

        all_results: list[dict[str, Any]] = []
        for doc in docs:
            result = _query_single_doc(doc, query, sheet, limit)
            if result and "error" not in result:
                all_results.append(result)

        if not all_results:
            return {
                "query": query,
                "message": "未找到匹配数据（文档可能不是表格类型或无原始文件）",
                "searched_docs": len(docs),
            }

        # 单文档直接返回，多文档包装为 results
        if len(all_results) == 1:
            return all_results[0]
        return {"query": query, "results": all_results, "total_docs": len(all_results)}
    finally:
        db.close()


def _query_single_doc(
    doc: KnowledgeDocument, query: str, sheet: str | None, limit: int
) -> dict[str, Any] | None:
    """查询单个文档，返回结构化结果。"""
    file_type = (doc.file_type or "").lower()
    rows: list[dict[str, Any]] = []
    source = ""

    # 1. 优先读取原始文件
    abs_path = _resolve_file_path(doc.file_path)
    if abs_path:
        try:
            if file_type in ("xlsx", "xls"):
                rows = _read_excel(abs_path, sheet)
                source = f"excel:{doc.file_path}"
            elif file_type == "csv":
                rows = _read_csv(abs_path)
                source = f"csv:{doc.file_path}"
            elif file_type in ("txt", "md", "json", "log"):
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                rows = _parse_content_table(content)
                source = f"text:{doc.file_path}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取原始文件失败: doc_id=%s, path=%s, err=%s", doc.id, abs_path, exc)
            rows = []

    # 2. 回退到 doc.content 解析
    if not rows and doc.content:
        rows = _parse_content_table(doc.content)
        source = "content"

    if not rows:
        return None

    # 3. 过滤
    matched_rows = _filter_rows(rows, query)
    total = len(rows)
    matched_count = len(matched_rows)

    # 4. 截断到 limit
    truncated = matched_count > limit
    limited_rows = matched_rows[:limit]

    # 5. 提取列名（取第一个行的 keys，保持顺序）
    columns = list(rows[0].keys()) if rows else []

    logger.info(
        "文件查询结果: doc_id=%s, title=%s, source=%s, total=%d, matched=%d, returned=%d",
        doc.id, doc.title, source, total, matched_count, len(limited_rows),
    )
    return {
        "doc_id": doc.id,
        "title": doc.title,
        "file_type": file_type or "unknown",
        "source": source,
        "columns": columns,
        "rows": limited_rows,
        "total": total,
        "matched": matched_count,
        "truncated": truncated,
        "query": query or "(无过滤，返回前 {} 行)".format(limit),
    }
