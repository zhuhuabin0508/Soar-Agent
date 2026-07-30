"""工具执行器：编译并运行用户编辑的 Python 工具代码。

安全说明（P0-3 升级）：
本平台为用户自有的内部 SOAR 平台，工具代码由平台管理员/授权用户编写。
但在多用户/角色场景下，仍需防止恶意或误操作的工具代码执行系统命令、
读取敏感文件、发起网络连接。因此引入两层沙箱防护：

1. **AST 静态审查**（``app.core.tool_sandbox.validate_tool_code``）：
   在 ``exec`` 前对源码做 AST 解析，禁止导入 os/subprocess/socket 等高危模块，
   禁止访问双下划线属性（防 ``__class__.__mro__`` 逃逸）。
2. **builtins 白名单**（``app.core.tool_sandbox.build_safe_builtins``）：
   将 exec 命名空间的 ``__builtins__`` 替换为白名单字典，
   运行时无法访问 ``__import__`` / ``open`` / ``eval`` 等。

工具代码约定：必须定义 ``async def run(**kwargs)``，返回任意可 JSON 序列化的结果。
可用注入模块：asyncio / json / datetime / timedelta / re / ipaddress / httpx（仅 HTTP 客户端，无文件系统访问）。
文档读取：openpyxl / docx / pypdf + ``read_uploaded_file(file_name)`` 辅助函数
（按文件名读取已上传的 xlsx/docx/pdf/csv/txt 文件，内部查 DB 定位文件，工具代码无需关心路径）。
"""
import asyncio
import ipaddress
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from app.core.tool_sandbox import (
    CodeValidationError,
    build_safe_builtins,
    validate_tool_code,
)

logger = logging.getLogger(__name__)

# 日志回调类型：(level: str, message: str) -> None；与 tool_http_runner.LogHandler 一致
LogHandler = Callable[[str, str], None]

# 保留字段名：run_tool 注入 log_handler 给 HTTP 工具时使用的 kwarg 名。
# 以下划线开头，避免与用户参数命名冲突；_http_run 会将其弹出后再调用 run_http_tool。
_LOG_HANDLER_KWARG = "_soar_log_handler"

# 进程级缓存：工具名 -> (run 函数, code 摘要)
# 当 code 变化时重新编译，避免重复 exec 开销。
_tool_cache: dict[str, tuple[Callable, str]] = {}


def read_uploaded_file(file_name: str) -> dict:
    """读取已上传的智能体文件内容（供工具代码调用）。

    本函数注入到沙箱命名空间，工具代码可直接调用 ``read_uploaded_file("报表.xlsx")``。
    内部通过 DB 查询 AgentFile 定位文件，按扩展名自动解析：
    - xlsx/xls：openpyxl 读取所有 sheet，返回 ``{sheet_name: [[row], ...]}``
    - docx：python-docx 读取段落，返回 ``{"text": "...", "paragraphs": [...]}``
    - pdf：pypdf 读取所有页，返回 ``{"pages": ["page1_text", ...], "text": "..."}``
    - csv/txt/md/json：直接读文本

    Args:
        file_name: 文件名（用户上传时的原始名，与 AgentFile.original_name 匹配）。

    Returns:
        ``{"file_name": ..., "file_type": ..., "content": ...}`` 或 ``{"error": "..."}``
    """
    if not file_name or not isinstance(file_name, str):
        return {"error": "请提供文件名（file_name 参数）"}

    # 安全：仅取文件名部分，防止路径遍历
    safe_name = os.path.basename(file_name.strip())

    # 延迟导入，避免循环依赖
    from app.database import SessionLocal
    from app.models.agent_file import AgentFile

    db = SessionLocal()
    try:
        # 先精确匹配 original_name，再尝试 stored_name
        record = db.query(AgentFile).filter(AgentFile.original_name == safe_name).first()
        if record is None:
            record = db.query(AgentFile).filter(AgentFile.stored_name == safe_name).first()
        if record is None:
            available = [r.original_name for r in db.query(AgentFile).all()]
            return {
                "error": f"文件不存在: {safe_name}",
                "available_files": available,
            }

        file_path = record.file_path
        if not os.path.exists(file_path):
            return {"error": f"文件在磁盘上不存在: {safe_name}"}

        ext = record.file_type.lower()
        try:
            if ext in ("xlsx", "xls"):
                import openpyxl
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                sheets = {}
                for ws in wb.sheetnames:
                    sheet = wb[ws]
                    rows = []
                    for row in sheet.iter_rows(values_only=True):
                        rows.append([str(c) if c is not None else "" for c in row])
                    sheets[ws] = rows
                wb.close()
                return {
                    "file_name": record.original_name,
                    "file_type": ext,
                    "sheets": sheets,
                    "content": json.dumps(sheets, ensure_ascii=False),
                }

            elif ext == "docx":
                import docx
                doc = docx.Document(file_path)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                full_text = "\n".join(paragraphs)
                return {
                    "file_name": record.original_name,
                    "file_type": ext,
                    "paragraphs": paragraphs,
                    "content": full_text,
                }

            elif ext == "pdf":
                from pypdf import PdfReader
                reader = PdfReader(file_path)
                pages = []
                for page in reader.pages:
                    text = page.extract_text() or ""
                    pages.append(text.strip())
                full_text = "\n\n".join(pages)
                return {
                    "file_name": record.original_name,
                    "file_type": ext,
                    "pages": pages,
                    "page_count": len(pages),
                    "content": full_text,
                }

            else:
                # csv / txt / md / json：直接读文本
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                return {
                    "file_name": record.original_name,
                    "file_type": ext,
                    "content": text,
                }

        except Exception as exc:  # noqa: BLE001
            logger.exception("读取文件失败: %s, error=%s", safe_name, exc)
            return {"error": f"读取文件失败: {exc}"}
    finally:
        db.close()


# 智能体记忆存储路径（JSON 文件，持久化在 uploads 卷中）
_AGENT_MEMORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "uploads", "agent_memory",
)
_AGENT_MEMORY_FILE = os.path.join(_AGENT_MEMORY_DIR, "memory.json")


def _load_memory_store() -> dict:
    """加载记忆 JSON 文件，返回 dict。文件不存在时返回空 dict。"""
    if not os.path.exists(_AGENT_MEMORY_FILE):
        return {}
    try:
        with open(_AGENT_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_memory_store(store: dict) -> None:
    """将记忆 dict 写入 JSON 文件。"""
    os.makedirs(_AGENT_MEMORY_DIR, exist_ok=True)
    with open(_AGENT_MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def save_agent_memory(key: str, value: str) -> dict:
    """保存一条键值对到智能体长期记忆（供工具代码调用）。

    存储在 ``uploads/agent_memory/memory.json`` 中，跨工具调用持久化。
    """
    if not key or not isinstance(key, str):
        return {"error": "请提供 key 参数"}
    store = _load_memory_store()
    store[key] = value
    try:
        _save_memory_store(store)
        return {"ok": True, "key": key, "saved": True, "total_keys": len(store)}
    except OSError as exc:
        logger.exception("保存记忆失败: key=%s, error=%s", key, exc)
        return {"error": f"保存记忆失败: {exc}"}


def recall_agent_memory(key: str = "") -> dict:
    """从智能体长期记忆检索数据（供工具代码调用）。

    - 传入 key：返回对应的值
    - 不传 key：返回所有已保存的记忆键列表
    """
    store = _load_memory_store()
    if not key:
        return {"keys": list(store.keys()), "total": len(store)}
    if key in store:
        return {"key": key, "value": store[key]}
    return {"key": key, "value": None, "error": f"未找到记忆: {key}", "available_keys": list(store.keys())}


def load_tool_function(tool, enabled_kbs=None) -> Callable:
    """加载工具的 ``run`` 异步函数。

    按 ``tool.tool_type`` 分发：
    - ``code``：编译用户 Python 代码（沙箱审查），缓存以 code 摘要为键。
    - ``http``：构造一个调用 ``run_http_tool`` 的协程函数，缓存以 http_config 摘要为键。

    若该工具已缓存且配置未变化，则直接复用缓存。

    Args:
        tool: ``Tool`` ORM 实例，需含 ``name``、``tool_type``，
            ``code`` 工具还需 ``code``，``http`` 工具还需 ``http_config``。

    Returns:
        可 await 的 ``run`` 函数对象。

    Raises:
        ValueError: 代码为空 / AST 审查失败 / 未定义 ``run`` 函数。
    """
    name = getattr(tool, "name", "unknown")
    tool_type = (getattr(tool, "tool_type", "code") or "code").lower()
    code = getattr(tool, "code", "") or ""
    http_config = getattr(tool, "http_config", None) or {}

    # 缓存摘要：code 工具用 code，http 工具用 http_config + parameters_schema 序列化
    # 注意：必须把 parameters_schema 纳入摘要，否则仅更新 schema（如把参数 location 改为
    # path）而 http_config 未变时，会复用旧闭包中绑定的旧 schema，导致路径参数不生效。
    if tool_type == "http":
        schema_for_cache = getattr(tool, "parameters_schema", None) or []
        cache_summary = "http:" + json.dumps(
            {"http_config": http_config, "parameters_schema": schema_for_cache},
            sort_keys=True,
            ensure_ascii=False,
        )
    else:
        # code 工具的缓存键需纳入 enabled_kbs：同一工具在不同智能体下注入的
        # 知识库列表不同（namespace 中 enabled_kbs / search_kb 闭包捕获的值不同），
        # 若只用 code 作键会复用旧缓存，导致查到错误智能体的知识库。
        cache_summary = code + "||enabled_kbs=" + ",".join(str(k) for k in (enabled_kbs or []))

    cached = _tool_cache.get(name)
    if cached is not None and cached[1] == cache_summary:
        logger.debug("复用工具缓存: %s", name)
        return cached[0]

    # ===== HTTP 工具：构造 run 协程 =====
    if tool_type == "http":
        from app.core.tool_http_runner import run_http_tool

        # 用闭包绑定 http_config / schema，避免延迟捕获问题
        cfg_snapshot = json.loads(json.dumps(http_config))  # 深拷贝
        schema_snapshot = list(getattr(tool, "parameters_schema", None) or [])

        async def _http_run(**kwargs):
            # 弹出内部保留的 log_handler kwarg（run_tool 为 HTTP 工具注入），
            # 不传递给 run_http_tool 的 parameters，避免污染参数分发。
            lh = kwargs.pop(_LOG_HANDLER_KWARG, None)
            return await run_http_tool(cfg_snapshot, kwargs, schema_snapshot, log_handler=lh)

        _tool_cache[name] = (_http_run, cache_summary)
        logger.info("HTTP 工具已加载并缓存: %s, url=%s", name, cfg_snapshot.get("url"))
        return _http_run

    # ===== Code 工具：编译 Python 代码（沙箱审查） =====
    if not code.strip():
        raise ValueError(f"工具 {name} 代码为空")

    # P0-3：AST 静态审查，拦截危险 import 与双下划线访问
    try:
        validate_tool_code(code)
    except CodeValidationError as exc:
        logger.warning("工具 %s 代码安全审查失败: %s", name, exc)
        raise ValueError(f"工具 {name} 代码安全审查失败: {exc}") from exc

    # 独立命名空间，注入常用模块供用户代码使用
    # 注意：__builtins__ 替换为白名单，阻断 __import__/open/eval 等运行时访问
    namespace: dict[str, Any] = {
        "__name__": f"tool_{name}",
        "__builtins__": build_safe_builtins(),
        "asyncio": asyncio,
        "json": json,
        "datetime": datetime,
        "timedelta": timedelta,
        "re": re,
        "ipaddress": ipaddress,
    }
    # httpx 按需注入（允许工具发起 HTTP 请求，但禁止文件系统/进程操作）
    try:
        import httpx  # noqa: F401

        namespace["httpx"] = httpx
    except ImportError:  # pragma: no cover
        logger.debug("httpx 未安装，工具命名空间不注入 httpx")

    # 文档读取能力注入：read_uploaded_file 辅助函数 + 文档解析库
    # read_uploaded_file 内部查 DB 定位文件并解析（xlsx/docx/pdf/csv/txt），
    # 工具代码无需关心文件路径，直接调用 read_uploaded_file("报表.xlsx") 即可。
    namespace["read_uploaded_file"] = read_uploaded_file
    namespace["save_agent_memory"] = save_agent_memory
    namespace["recall_agent_memory"] = recall_agent_memory

    # 安全上下文工具注入：沙箱禁止 __import__，工具代码无法用 import 语句
    # 导入 app.tools.context_tools / app.devices.firewall。此处将函数直接注入
    # 命名空间，工具代码可直接调用 get_asset_info(ip) 等，无需 import。
    try:
        from app.tools.context_tools import (
            check_subnet,
            check_whitelist,
            get_asset_info,
            get_threat_intel,
        )
        namespace["get_asset_info"] = get_asset_info
        namespace["get_threat_intel"] = get_threat_intel
        namespace["check_whitelist"] = check_whitelist
        namespace["check_subnet"] = check_subnet
    except ImportError:  # pragma: no cover
        logger.debug("context_tools 未安装，工具命名空间不注入安全上下文函数")
    try:
        from app.devices.firewall import block_ip_on_firewall
        namespace["block_ip_on_firewall"] = block_ip_on_firewall
    except ImportError:  # pragma: no cover
        logger.debug("firewall 模块未安装，工具命名空间不注入 block_ip_on_firewall")
    try:
        import openpyxl  # noqa: F401
        namespace["openpyxl"] = openpyxl
    except ImportError:  # pragma: no cover
        logger.debug("openpyxl 未安装，工具命名空间不注入 openpyxl")
    try:
        import docx  # noqa: F401
        namespace["docx"] = docx
    except ImportError:  # pragma: no cover
        logger.debug("python-docx 未安装，工具命名空间不注入 docx")
    try:
        from pypdf import PdfReader  # noqa: F401
        namespace["PdfReader"] = PdfReader
    except ImportError:  # pragma: no cover
        logger.debug("pypdf 未安装，工具命名空间不注入 pypdf")

    # 知识库检索能力注入：允许工具代码查询「当前智能体勾选的知识库」。
    # - search_kb(kb_id, query, top_k=5)：分段级混合检索，返回命中片段列表。
    # - enabled_kbs：当前智能体勾选的知识库 ID 列表（由 tool_engine 传入）。
    # 工具代码可直接遍历 enabled_kbs 调用 search_kb，无需 import（沙箱禁止 import）。
    # 典型场景：get_asset_info 查询勾选知识库中的 IP 资产归属。
    try:
        from app.core.kb_retriever import search_kb

        namespace["search_kb"] = search_kb
    except ImportError:  # pragma: no cover
        logger.debug("kb_retriever 未安装，工具命名空间不注入 search_kb")
    namespace["enabled_kbs"] = list(enabled_kbs or [])

    # 数据库访问注入：允许工具查询/写入已封禁 IP 表（query_banned_ip / record_ban 等）
    # 同时注入 KnowledgeBase / KnowledgeSegment，供 get_asset_info 查询知识库名称和精确 IP 匹配
    try:
        from app.database import SessionLocal
        from app.models.banned_ip import BannedIP
        from app.models.knowledge_base import KnowledgeBase, KnowledgeSegment
        namespace["SessionLocal"] = SessionLocal
        namespace["BannedIP"] = BannedIP
        namespace["KnowledgeBase"] = KnowledgeBase
        namespace["KnowledgeSegment"] = KnowledgeSegment
    except ImportError:  # pragma: no cover
        logger.debug("数据库模块未安装，工具命名空间不注入 SessionLocal/BannedIP/KnowledgeBase")

    try:
        exec(compile(code, f"<tool:{name}>", "exec"), namespace)  # noqa: S102
    except Exception as exc:
        logger.exception("工具 %s 代码编译失败: %s", name, exc)
        raise ValueError(f"工具 {name} 代码编译失败: {exc}") from exc

    run_fn = namespace.get("run")
    if run_fn is None or not callable(run_fn):
        raise ValueError(f"工具 {name} 未定义 run 函数")

    _tool_cache[name] = (run_fn, cache_summary)
    logger.info("工具已加载并缓存（沙箱审查通过）: %s", name)
    return run_fn


async def run_tool(
    tool, parameters: dict, log_handler: LogHandler | None = None
) -> dict:
    """执行工具的 ``run(**parameters)`` 并返回结果。

    捕获执行异常，失败时返回 ``{"error": str(exc)}`` 而非抛出，
    便于工作流节点与 API 测试接口统一处理。

    Args:
        tool: ``Tool`` ORM 实例。
        parameters: 调用参数字典。
        log_handler: 可选日志回调 ``(level, message)``。仅对 HTTP 工具生效：
            通过保留 kwarg ``_soar_log_handler`` 注入到 ``_http_run``，再透传给
            ``run_http_tool``，用于在工具测试时回传「实际请求 URL / 参数分发 /
            响应状态」等执行链路日志。code 工具不接收此回调。

    Returns:
        ``{"result": <run 返回值>}`` 成功，或 ``{"error": "..."}`` 失败。
    """
    name = getattr(tool, "name", "unknown")
    tool_type = (getattr(tool, "tool_type", "code") or "code").lower()
    params = dict(parameters or {})
    # 仅 HTTP 工具注入 log_handler；code 工具的 run() 不识别该 kwarg。
    if log_handler is not None and tool_type == "http":
        params[_LOG_HANDLER_KWARG] = log_handler
    logger.info("执行工具: name=%s, params=%s", name, parameters)
    try:
        run_fn = load_tool_function(tool)
        result = await run_fn(**params)
        logger.info("工具执行成功: name=%s, result=%s", name, result)
        return {"result": result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("工具执行异常: name=%s, error=%s", name, exc)
        if log_handler is not None:
            try:
                log_handler("error", f"工具执行异常: {exc}")
            except Exception:  # noqa: BLE001
                pass
        return {"error": str(exc)}


def clear_tool_cache(name: Optional[str] = None) -> None:
    """清除工具缓存（更新/删除工具时调用）。"""
    if name is None:
        _tool_cache.clear()
        logger.info("已清除全部工具缓存")
    elif name in _tool_cache:
        del _tool_cache[name]
        logger.info("已清除工具缓存: %s", name)
