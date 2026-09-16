"""安全代码执行子进程包装器（由 node_executors 以 ``sys.executable -I`` 调用）。

设计目标（渗透测试整改 漏洞2：Python 沙箱逃逸）：
- 以 ``python -I``（isolated 模式）运行，配合父进程 ``env={}``，使子进程内
  ``os.environ`` 为空，切断了 JWT 密钥 / 数据库 / Redis 等宿主机凭据泄露路径。
- 父进程已通过 ``preexec_fn`` 完成 setuid/setgid 降权到 nobody、并设置 RLIMIT 资源上限；
  本脚本只负责在受限命名空间中 ```exec`` 用户代码并回传结果。
- 本脚本不应被 import，只作为独立可执行脚本运行。

用法：
    python -I safe_code_runner.py <input.json> <output.json>

input.json: {"code": str, "input_data": dict, "ctx": dict}
output.json: {"result": <any>} 或 {"error": str, "traceback": str}
"""
import json
import sys


def _safe_builtins() -> dict:
    """构造受限内置函数子集（不含 open/eval/exec/compile/__import__/globals/locals 等）。"""
    blt = __builtins__ if isinstance(__builtins__, dict) else vars(__import__("builtins"))
    deny = {
        "open", "eval", "exec", "compile", "__import__", "globals",
        "locals", "vars", "dir", "getattr", "setattr", "delattr", "input", "breakpoint",
    }
    allowed = [
        "print", "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
        "range", "enumerate", "zip", "map", "filter", "sorted", "reversed", "sum",
        "min", "max", "abs", "round", "isinstance", "type", "Exception",
        "ValueError", "TypeError", "KeyError", "IndexError", "ImportError",
    ]
    return {name: blt[name] for name in allowed if name in blt}


def main() -> int:
    input_path = sys.argv[1]
    output_path = sys.argv[2]

    with open(input_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    code = payload.get("code", "")
    input_data = payload.get("input_data", {})
    ctx = payload.get("ctx", {})

    safe_globals = {"__builtins__": _safe_builtins(), "__name__": "__safe_runner__"}
    safe_globals.update({
        "json": __import__("json"),
        "re": __import__("re"),
        "math": __import__("math"),
        "datetime": __import__("datetime"),
        "hashlib": __import__("hashlib"),
        "base64": __import__("base64"),
    })
    local_vars = {"input_data": input_data, "ctx": ctx, "result": None}

    try:
        exec(compile(code, "<user_code>", "exec"), safe_globals, local_vars)
        result = local_vars.get("result")
    except BaseException as exc:  # noqa: BLE001
        import traceback
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                {"error": f"{type(exc).__name__}: {exc}",
                 "traceback": traceback.format_exc(limit=3)},
                f,
                ensure_ascii=False,
            )
        return 0

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"result": result}, f, ensure_ascii=False)
    except (TypeError, ValueError):
        # result 不可 JSON 序列化时，回退为可读表示
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                {"error": "result 无法序列化为 JSON", "result": repr(result)},
                f,
                ensure_ascii=False,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
