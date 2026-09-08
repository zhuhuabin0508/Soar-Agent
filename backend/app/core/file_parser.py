"""知识库文件解析器。

按文件扩展名解析上传文件内容为纯文本，供 ``KnowledgeDocument.content`` 存储与
后续检索（``kb_retriever.search_kb``）使用。

支持格式：
- 文本类（txt/md/csv/json/log/html/htm/xml）：utf-8 解码，html 剥离标签。
- pdf：pypdf 提取文本。
- docx：python-docx 提取段落。
- xlsx：openpyxl 按行拼接。
- xls：xlrd 按行拼接（旧版 Excel 二进制格式，openpyxl 不支持）。
- pptx：依赖 python-pptx，未安装时返回占位提示并跳过。
- 其它/解析失败：返回空字符串（不抛异常）。

文本上限 5MB（5*1024*1024 字符），超长则尾部加 ``...[内容已截断]``。
分段（chunking）在 ``app/core/chunker.py`` 中按知识库配置进一步切分。
"""
import asyncio
import logging
import os
import re

logger = logging.getLogger(__name__)

# 文本截断上限（字符数）：5MB，作为存储安全网；检索由分段处理
_MAX_CONTENT_CHARS = 5 * 1024 * 1024

# 直接 utf-8 解码的扩展名集合
_TEXT_EXTENSIONS = {
    "txt", "md", "csv", "json", "log", "html", "htm", "xml",
}

# 简单 HTML 标签剥离正则
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def parse_filename(filename: str) -> tuple[str, str]:
    """从文件名解析出标题（去扩展名）与扩展名（小写无点）。

    Args:
        filename: 原始文件名，如 ``"报告.pdf"``。

    Returns:
        ``(title, file_type)``，如 ``("报告", "pdf")``。
        无扩展名时 ``file_type`` 为空字符串。
    """
    if not filename:
        return "", ""
    # 仅取文件名部分（防 ``a/b.txt``）
    base = os.path.basename(filename)
    stem, ext = os.path.splitext(base)
    return stem, ext.lstrip(".").lower()


def _truncate(text: str) -> str:
    """超长文本截断并加尾部标记。"""
    if len(text) <= _MAX_CONTENT_CHARS:
        return text
    return text[:_MAX_CONTENT_CHARS] + "\n...[内容已截断]"


def _strip_html(text: str) -> str:
    """剥离 HTML 标签，保留纯文本。"""
    return _HTML_TAG_RE.sub("", text)


def _read_text_file(file_path: str, file_type: str) -> str:
    """读取文本类文件，html 需剥离标签。"""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    if file_type in ("html", "htm"):
        content = _strip_html(content)
    return content


def _read_pdf(file_path: str) -> str:
    """用 pypdf 提取 PDF 文本。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf 未安装，无法解析 PDF")
        return ""
    reader = PdfReader(file_path)
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("PDF 页解析失败: %s", exc)
    return "\n".join(parts)


def _read_docx(file_path: str) -> str:
    """用 python-docx 提取段落文本。"""
    try:
        import docx  # python-docx
    except ImportError:
        logger.warning("python-docx 未安装，无法解析 DOCX")
        return ""
    document = docx.Document(file_path)
    parts: list[str] = [p.text for p in document.paragraphs if p.text]
    return "\n".join(parts)


def _is_default_sheet_name(name: str) -> bool:
    """判断是否为无意义的默认工作表名（Sheet1/工作表1 等）。

    这类名称对检索无价值，单 Sheet 时不作为字段前缀，避免每行重复噪音。
    """
    if not name:
        return True
    n = name.strip().lower()
    defaults = {"sheet1", "sheet", "sheet0", "工作表1", "工作表", "工作表sheet1"}
    return n in defaults


def _read_xlsx(file_path: str) -> str:
    """用 openpyxl 解析 Excel（.xlsx），按"表头+行"序列化为带字段名的自然语言文本。

    相比单纯 tab 分隔拼接，这里把每个数据行写成 ``列名: 值 | 列名: 值`` 的形式，
    让字段名与值一并进入文本。这样关键词检索（如查"部门"会命中"部门: 研发部"）
    和后续向量语义检索都能更精准定位表格数据。

    工作表名处理：旧实现单独输出 ``[Sheet名]`` 行，在 line 分段模式下会被切成
    独立的无用段落（用户反馈"工作表名被当成数据分段"）。现改为将 ``工作表: Sheet名``
    作为每行数据的**首字段前缀**，使表名跟随数据行进入分段，不再独立成段。

    前缀策略（避免单 Sheet 时的冗余噪音）：
    - 多 Sheet：每行都带 ``工作表: Sheet名``，便于区分来源。
    - 单 Sheet 且表名为默认无意义名（Sheet1/工作表1）：不加前缀。
    - 单 Sheet 但表名有语义（如 IP 段名）：加前缀，让表名可被检索命中。

    注意：openpyxl 仅支持 ``.xlsx`` 格式，旧版 ``.xls`` 请用 ``_read_xls``（xlrd）。
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        logger.warning("openpyxl 未安装，无法解析 XLSX")
        return ""
    wb = load_workbook(filename=file_path, read_only=True, data_only=True)
    parts: list[str] = []
    multi_sheet = len(wb.worksheets) > 1
    for ws in wb.worksheets:
        sheet_name = ws.title or "Sheet"
        # 是否在每行前缀 "工作表: Sheet名"
        show_sheet = multi_sheet or not _is_default_sheet_name(sheet_name)
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        # 第一行作为表头
        header = ["" if c is None else str(c).strip() for c in rows[0]]
        for row in rows[1:]:
            cells = ["" if c is None else str(c).strip() for c in row]
            if not any(cells):
                continue  # 跳过空行
            # 字段名: 值 配对，跳过空表头列
            pairs = []
            if show_sheet:
                pairs.append(f"工作表: {sheet_name}")
            for idx, val in enumerate(cells):
                col_name = header[idx] if idx < len(header) else f"列{idx + 1}"
                if not col_name:
                    col_name = f"列{idx + 1}"
                if val:
                    pairs.append(f"{col_name}: {val}")
            if pairs:
                parts.append(" | ".join(pairs))
    wb.close()
    return "\n".join(parts)


def _read_xls(file_path: str) -> str:
    """用 xlrd 解析旧版 ``.xls`` 文件，输出格式与 ``_read_xlsx`` 一致。

    openpyxl 不支持 ``.xls``（旧版二进制格式），需用 xlrd 读取。
    xlrd 2.0+ 仅支持 ``.xls``（已移除 ``.xlsx`` 支持），正好互补。
    """
    try:
        import xlrd
    except ImportError:
        logger.warning("xlrd 未安装，无法解析旧版 .xls 文件")
        return ""
    wb = xlrd.open_workbook(file_path)
    parts: list[str] = []
    multi_sheet = len(wb.sheets()) > 1
    for sheet in wb.sheets():
        sheet_name = sheet.name or "Sheet"
        if sheet.nrows == 0:
            continue
        # 是否在每行前缀 "工作表: Sheet名"（与 _read_xlsx 同策略，避免 [Sheet名] 独立成段）
        show_sheet = multi_sheet or not _is_default_sheet_name(sheet_name)
        # 第一行作为表头
        header = ["" if c is None else str(c).strip() for c in sheet.row_values(0)]
        for row_idx in range(1, sheet.nrows):
            raw = sheet.row_values(row_idx)
            cells = ["" if c is None else str(c).strip() for c in raw]
            if not any(cells):
                continue  # 跳过空行
            pairs = []
            if show_sheet:
                pairs.append(f"工作表: {sheet_name}")
            for idx, val in enumerate(cells):
                col_name = header[idx] if idx < len(header) else f"列{idx + 1}"
                if not col_name:
                    col_name = f"列{idx + 1}"
                if val:
                    pairs.append(f"{col_name}: {val}")
            if pairs:
                parts.append(" | ".join(pairs))
    return "\n".join(parts)


def _read_pptx(file_path: str) -> str:
    """提取 PPTX 幻灯片文本（需 python-pptx）。

    若未安装 python-pptx，记录提示并返回空字符串。
    """
    try:
        from pptx import Presentation  # type: ignore
    except ImportError:
        logger.warning("PPTX 解析需 python-pptx，已跳过")
        return ""
    prs = Presentation(file_path)
    parts: list[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            text = getattr(shape, "text", None)
            if text:
                parts.append(text)
    return "\n".join(parts)


async def parse_file_content(file_path: str, file_type: str) -> str:
    """按扩展名解析上传文件，返回纯文本。

    所有解析路径均 ``try/except``，失败时记录日志并返回空字符串，
    不抛异常（保证上传接口对未知/损坏文件不报错）。

    Args:
        file_path: 已保存的本地文件路径。
        file_type: 扩展名（小写无点），如 ``"pdf"`` / ``"docx"``。

    Returns:
        解析后的文本（已截断至 1MB 上限）；解析失败返回空字符串。
    """
    ftype = (file_type or "").lower()
    try:
        if ftype in _TEXT_EXTENSIONS:
            content = _read_text_file(file_path, ftype)
        elif ftype == "pdf":
            content = _read_pdf(file_path)
        elif ftype == "docx":
            content = _read_docx(file_path)
        elif ftype == "xlsx":
            content = _read_xlsx(file_path)
        elif ftype == "xls":
            content = _read_xls(file_path)
        elif ftype == "pptx":
            content = _read_pptx(file_path)
        else:
            logger.info("不支持的文件类型，content 留空: %s", ftype)
            content = ""
    except Exception as exc:  # noqa: BLE001
        logger.exception("文件解析失败: type=%s, error=%s", ftype, exc)
        content = ""
    return _truncate(content or "")
