"""工具代码沙箱：AST 静态审查 + builtins 白名单。

设计目标（P0-3）：
在 ``app/core/tool_runner.py`` 的 ``exec`` 之前，先对用户编写的工具代码做两层防护：

1. **AST 静态审查**（``validate_tool_code``）：
   - 禁止导入高危模块（os / subprocess / socket / pickle / ctypes / shutil / sys / signal 等）。
   - 禁止访问双下划线属性（``__builtins__`` / ``__import__`` / ``__subclasses__`` 等），
     防止通过 ``"".__class__.__mro__[1].__subclasses__()`` 链逃逸。
   - 禁止直接调用 ``eval`` / ``exec`` / ``compile`` / ``globals`` / ``locals`` / ``getattr`` 对双下划线的访问。

2. **builtins 白名单**（``build_safe_builtins``）：
   - 替换 namespace 的 ``__builtins__`` 为白名单字典，仅暴露安全内建函数。
   - 即使 AST 漏网，运行时也无法访问 ``__import__`` / ``open`` / ``eval`` 等。

注意：本方案无法抵御 0-day Python 内部漏洞，但能阻断常规逃逸路径。
对于高安全要求场景，仍建议叠加子进程/容器隔离（P0-3 方案 B）。
"""
import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ============ 危险模块黑名单 ============
# 这些模块允许工具代码直接操作文件系统/进程/网络/解释器内部，必须禁止。
_FORBIDDEN_MODULES: set[str] = {
    "os", "sys", "subprocess", "socket", "pickle", "cPickle",
    "ctypes", "shutil", "signal", "multiprocessing", "threading",
    "pty", "commands", "platform", "pathlib",  # pathlib 可读任意路径，禁用
    "glob", "importlib", "builtins", "code", "codeop",
    "runpy", "codecs", "tempfile", "getpass",
    "webbrowser", "antigravity", "asyncio.subprocess",  # asyncio.subprocess 可起进程
}

# ============ builtins 白名单 ============
# 仅暴露纯计算与基础数据结构操作，不含 IO / import / eval。
_SAFE_BUILTINS: dict[str, Any] = {
    # 基础类型
    "int": int, "float": float, "str": str, "bool": bool,
    "list": list, "tuple": tuple, "dict": dict, "set": set, "frozenset": frozenset,
    "bytes": bytes, "bytearray": bytearray, "complex": complex,
    # 基础函数
    "len": len, "range": range, "enumerate": enumerate, "zip": zip,
    "map": map, "filter": filter, "sum": sum, "min": min, "max": max,
    "abs": abs, "round": round, "sorted": sorted, "reversed": reversed,
    "any": any, "all": all, "isinstance": isinstance, "issubclass": issubclass,
    "type": type, "id": id, "hash": hash, "repr": repr, "ascii": ascii,
    "format": format, "chr": chr, "ord": ord, "hex": hex, "oct": oct, "bin": bin,
    "divmod": divmod, "pow": pow, "iter": iter, "next": next,
    "slice": slice, "property": property, "staticmethod": staticmethod, "classmethod": classmethod,
    "super": super, "object": object,
    # 异常（允许 raise 与 catch）
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
    "ZeroDivisionError": ZeroDivisionError, "NotImplementedError": NotImplementedError,
    "LookupError": LookupError, "ArithmeticError": ArithmeticError,
    "AssertionError": AssertionError, "NameError": NameError,
    # 工具代码常用：json（已显式注入）/ re / datetime（已显式注入）
    # 不暴露 print（避免日志污染，工具应 return 结果而非打印），
    # 不暴露 open / input / eval / exec / compile / __import__ / globals / locals / vars / dir / help / exit / quit
    "True": True, "False": False, "None": None,
}

# 显式禁止的危险内建名（防御性，即便漏到白名单也再次拦截）
_BLOCKED_BUILTIN_NAMES: set[str] = {
    "open", "input", "eval", "exec", "compile", "__import__",
    "globals", "locals", "vars", "dir", "help", "exit", "quit",
    "breakpoint", "memoryview", "copyright", "credits", "license",
}


class CodeValidationError(ValueError):
    """工具代码静态审查失败异常。"""


def _check_import(node: ast.AST) -> None:
    """禁止所有 import 语句。

    沙箱通过 ``build_safe_builtins`` 移除了 ``__import__``，运行时任何
    ``import`` / ``from ... import`` 都会抛 ``NameError: __import__``。
    因此在 AST 阶段直接拦截，给出明确编译期错误，而非等到运行时才以
    「工具完成（错误）」的形式暴露。

    常用模块已由 ``tool_runner.load_tool_function`` 注入命名空间，工具代码
    可直接使用：asyncio / json / datetime / re / ipaddress / httpx /
    openpyxl / docx / PdfReader / read_uploaded_file / save_agent_memory /
    recall_agent_memory / get_asset_info / get_threat_intel / check_whitelist /
    check_subnet / block_ip_on_firewall。无需也不应使用 import。
    """
    if isinstance(node, ast.Import):
        names = ", ".join(alias.name for alias in node.names)
        raise CodeValidationError(
            f"禁止使用 import 语句（沙箱无 __import__）：import {names}。"
            f"常用模块已注入命名空间，请直接使用，例如 json / re / ipaddress。"
        )
    elif isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        names = ", ".join(alias.name for alias in node.names)
        raise CodeValidationError(
            f"禁止使用 from...import 语句（沙箱无 __import__）：from {mod} import {names}。"
            f"常用模块已注入命名空间，请直接使用。"
        )


def _check_attribute(node: ast.AST) -> None:
    """检查属性访问是否触及双下划线（防逃逸）。"""
    if isinstance(node, ast.Attribute):
        attr = node.attr
        if attr.startswith("__") and attr.endswith("__"):
            # 允许 dunder 方法定义（如 __init__），但禁止访问
            # 这里检查的是"访问"场景（Attribute 节点），定义在 FunctionDef.name 不会走到这里
            raise CodeValidationError(
                f"禁止访问双下划线属性: {attr}（防止通过 __class__.__mro__ 等逃逸）"
            )


def _check_name(node: ast.AST) -> None:
    """检查 Name 节点是否引用了被禁内建。"""
    if isinstance(node, ast.Name):
        if node.id in _BLOCKED_BUILTIN_NAMES:
            raise CodeValidationError(f"禁止使用内建函数: {node.id}")


def validate_tool_code(code: str) -> None:
    """对工具代码做 AST 静态审查。

    Args:
        code: 工具源码字符串。

    Raises:
        CodeValidationError: 命中任何危险模式时抛出，含具体原因。
    """
    if not code or not code.strip():
        raise CodeValidationError("工具代码为空")

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise CodeValidationError(f"工具代码语法错误: {exc}") from exc

    for node in ast.walk(tree):
        _check_import(node)
        _check_attribute(node)
        _check_name(node)

    logger.debug("工具代码 AST 审查通过")


def build_safe_builtins() -> dict[str, Any]:
    """构造安全的 __builtins__ 字典（白名单）。

    返回的字典可直接作为 exec namespace 的 ``__builtins__``，
    确保工具代码运行时无法访问 ``__import__`` / ``open`` / ``eval`` 等。
    """
    # 复制一份，避免外部修改污染
    safe = dict(_SAFE_BUILTINS)
    return safe
