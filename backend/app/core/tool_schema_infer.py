"""工具输入输出 schema 自动推断。

用 :mod:`ast` 静态解析工具代码（``async def run(**kwargs)``），推断：

- **输入**：扫描函数体中 ``kwargs.get("x")`` / ``kwargs["x"]`` 的访问，
  收集 key 名作为入参。``get`` 视为可选，``[...]`` 索引访问视为必填。
  ``get`` 带默认值时按默认值类型推断入参 type。
- **输出**：扫描所有 ``return {...}`` 语句，提取字典字面量的 key 作为输出字段名，
  type 按字面量值推断。

解析失败或无 ``run`` 函数时，inputs 回退到 ``fallback_parameters_schema``，
outputs 回退到 ``[{"name": "result", "type": "Object"}]``。

类型推断规则：
- int/float → ``Number``
- True/False → ``Boolean``
- dict → ``Object``
- list → ``Array``
- 其它/默认 → ``String``
"""
import ast
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 默认 outputs 回退值
_DEFAULT_OUTPUTS: list[dict[str, str]] = [{"name": "result", "type": "Object"}]


def _infer_type_from_constant(value: Any) -> str:
    """根据 Python 字面量推断 schema type 字符串。"""
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, (int, float)):
        return "Number"
    if isinstance(value, dict):
        return "Object"
    if isinstance(value, list):
        return "Array"
    return "String"


def _infer_type_from_node(node: ast.AST) -> str:
    """根据 AST 节点推断 schema type 字符串。

    比 :func:`_infer_type_from_constant` 多覆盖 ``List`` / ``Dict`` / ``Name``
    等字面量与表达式节点，避免空容器 ``[]`` / ``{}`` 被误判为 String。
    """
    # ast.Constant 统一覆盖 Num/Str/NameConstant/Bytes（Python 3.8+）
    if isinstance(node, ast.Constant):
        return _infer_type_from_constant(node.value)
    if isinstance(node, ast.List):
        return "Array"
    if isinstance(node, ast.Dict):
        return "Object"
    if isinstance(node, ast.Set):
        return "Array"
    if isinstance(node, ast.NameConstant):  # pragma: no cover
        return _infer_type_from_constant(node.value)
    if isinstance(node, ast.Num):  # pragma: no cover
        return "Number"
    if isinstance(node, ast.Str):  # pragma: no cover
        return "String"
    return "String"


def _find_run_function(tree: ast.AST) -> Optional[ast.FunctionDef]:
    """在模块 AST 中查找 ``run`` 函数定义（async 或同步均可）。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            return node
    return None


def _infer_inputs(run_node: ast.FunctionDef) -> list[dict[str, Any]]:
    """扫描 run 函数体，从 kwargs 访问中推断入参。"""
    inputs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for node in ast.walk(run_node):
        # kwargs.get("x") 或 kwargs.get("x", default)
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Name)
                and func.value.id == "kwargs"
            ):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    name = node.args[0].value
                    if name in seen:
                        continue
                    seen.add(name)
                    # 有第二参数（默认值）则按其类型推断
                    if len(node.args) >= 2:
                        ptype = _infer_type_from_node(node.args[1])
                    else:
                        ptype = "String"
                    inputs.append({
                        "name": name,
                        "type": ptype,
                        "required": False,
                        "description": "",
                    })
            continue

        # kwargs["x"] 索引访问（视为必填）
        if isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Name) and value.id == "kwargs":
                key = _extract_subscript_key(node)
                if key is None or key in seen:
                    continue
                seen.add(key)
                inputs.append({
                    "name": key,
                    "type": "String",
                    "required": True,
                    "description": "",
                })

    return inputs


def _extract_subscript_key(node: ast.Subscript) -> Optional[str]:
    """从 ``kwargs[...]`` 的 subscript 节点提取字符串 key。

    兼容 Python 3.8（slice 直接是 Constant）与 3.9+（slice 是 Constant 包在
    ``ast.Subscript`` 中无额外封装；3.9+ 不再包 ``ast.Index``）。
    """
    sl = node.slice
    # Python 3.8: slice 是 ast.Index
    if isinstance(sl, ast.Index):  # pragma: no cover
        sl = sl.value
    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
        return sl.value
    return None


def _infer_outputs(run_node: ast.FunctionDef) -> list[dict[str, str]]:
    """扫描 run 函数体，从 ``return {...}`` 推断输出字段。"""
    outputs: list[dict[str, str]] = []
    seen: set[str] = set()

    for node in ast.walk(run_node):
        if not isinstance(node, ast.Return):
            continue
        if node.value is None or not isinstance(node.value, ast.Dict):
            continue
        for key_node, value_node in zip(node.value.keys, node.value.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            name = key_node.value
            if name in seen:
                continue
            seen.add(name)
            outputs.append({
                "name": name,
                "type": _infer_type_from_node(value_node),
            })

    return outputs if outputs else list(_DEFAULT_OUTPUTS)


def infer_tool_io(
    code: str,
    fallback_parameters_schema: Optional[list[dict]] = None,
) -> dict[str, list[dict[str, Any]]]:
    """从工具代码推断输入输出 schema。

    Args:
        code: 工具源码字符串，预期定义 ``async def run(**kwargs)``。
        fallback_parameters_schema: AST 解析失败或无 ``run`` 函数时，
            inputs 回退到此 schema（原样返回）；为 None 时回退到空列表。

    Returns:
        ``{"inputs": [...], "outputs": [...]}``。
    """
    if not code or not code.strip():
        logger.info("工具代码为空，使用回退 schema")
        return {
            "inputs": list(fallback_parameters_schema or []),
            "outputs": list(_DEFAULT_OUTPUTS),
        }

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        logger.warning("工具代码 AST 解析失败，使用回退 schema: %s", exc)
        return {
            "inputs": list(fallback_parameters_schema or []),
            "outputs": list(_DEFAULT_OUTPUTS),
        }

    run_node = _find_run_function(tree)
    if run_node is None:
        logger.info("工具代码未找到 run 函数，使用回退 schema")
        return {
            "inputs": list(fallback_parameters_schema or []),
            "outputs": list(_DEFAULT_OUTPUTS),
        }

    try:
        inputs = _infer_inputs(run_node)
        outputs = _infer_outputs(run_node)
    except Exception as exc:  # noqa: BLE001
        logger.exception("工具 schema 推断异常，使用回退 schema: %s", exc)
        return {
            "inputs": list(fallback_parameters_schema or []),
            "outputs": list(_DEFAULT_OUTPUTS),
        }

    # inputs 推断为空时也回退到 fallback（保持与 parameters_schema 一致）
    if not inputs and fallback_parameters_schema:
        inputs = list(fallback_parameters_schema)

    return {"inputs": inputs, "outputs": outputs}
