"""工作流执行引擎（同步/测试运行版）。

与 ``app/tasks/workflow_tasks.py`` 中的 Celery 异步执行逻辑对应，
但本模块为纯 async 实现，供 ``/workflows/{id}/test-run`` 与 ``/workflows/test-node``
在请求内同步执行，便于调试与节点级测试。

执行流程：
1. 用 ``app/core/dag.py`` 的拓扑排序校验 DAG 并确定入口节点。
2. BFS 遍历节点，调用 ``node_executors.execute_node`` 执行。
3. 节点输出写入 ctx（key=节点 id）；条件节点写 ctx["_route"]，
   通过 ``find_next_nodes`` 按 edge.sourceHandle 选择下游。
4. 每个节点产生 trace（输入/输出/状态/时间戳）与 log。
"""
import logging
import re
from collections import deque
from datetime import datetime
from app.core.timezone import beijing_now, beijing_now_iso
from typing import Any, Callable, Optional

from app.core.dag import find_next_nodes, topological_sort
from app.core.node_executors import execute_node

logger = logging.getLogger(__name__)

# 变量引用正则：${var} 或 ${a.b.c}
_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')


def _get_nested(ctx: dict, path: str) -> Any:
    """从 ctx 中按点分路径取值，如 payload.src_ip → ctx["payload"]["src_ip"]。"""
    parts = path.strip().split(".")
    cur: Any = ctx
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and p.lstrip("-").isdigit():
            idx = int(p)
            cur = cur[idx] if -len(cur) <= idx < len(cur) else None
        else:
            return None
    return cur


def resolve_variables(value: Any, ctx: dict) -> Any:
    """递归解析 value 中的 ${var} 变量引用。

    支持的变量路径：
    - ${payload.xxx}        → 触发 payload 中的字段
    - ${variables.my_var}   → 工作流级自定义变量
    - ${execution_id}       → 当前执行 ID
    - ${workflow_id}        → 工作流 ID
    - ${timestamp}          → 执行时间戳（ISO 格式）
    - ${node_id.field}      → 上游节点输出中的字段（node_id 为节点 ID）

    若整个字符串为 ``${xxx}`` 形式，返回原始类型值（数字/对象/列表）；
    否则做字符串替换。
    """
    if isinstance(value, str):
        stripped = value.strip()
        full_match = _VAR_PATTERN.fullmatch(stripped)
        if full_match:
            return _get_nested(ctx, full_match.group(1))
        return _VAR_PATTERN.sub(
            lambda m: str(_get_nested(ctx, m.group(1)) or ""), value
        )
    if isinstance(value, dict):
        return {k: resolve_variables(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_variables(v, ctx) for v in value]
    return value


def _safe_jsonable(value: Any) -> Any:
    """把对象转为可 JSON 序列化的结构（剥离非基本类型）。"""
    try:
        import json

        return json.loads(json.dumps(value, default=str, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        return {"_serializable": False}


def _build_node_input(node_type: str, node_data: dict, ctx: dict, payload: dict) -> dict:
    """为节点构建输入快照（用于 trace）。"""
    if node_type in ("webhook_trigger", "ai_agent"):
        return {"payload": payload}
    if node_type == "condition_branch":
        return {"decision": ctx.get("decision"), "_route": ctx.get("_route")}
    if node_type == "block_ip":
        agent_decision = ctx.get("agent_decision") or {}
        return {
            "target_ip": agent_decision.get("target_ip") or payload.get("src_ip"),
            "duration": agent_decision.get("duration"),
            "reason": agent_decision.get("reason"),
        }
    if node_type == "http_request":
        return {"url": node_data.get("url"), "method": node_data.get("method", "GET")}
    if node_type == "tool":
        return {
            "tool_name": node_data.get("tool_name"),
            "parameters": node_data.get("parameters", {}),
        }
    if node_type == "human_review":
        return {
            "title": node_data.get("title") or node_data.get("label") or "",
            "instructions": node_data.get("instructions") or "",
            "ctx_keys": list(ctx.keys()),
        }
    if node_type == "end":
        return {"end_type": node_data.get("end_type", "success")}
    return {"ctx_keys": list(ctx.keys())}


async def run_workflow(
    graph_config: dict,
    payload: dict,
    log_callback: Optional[Callable[[str, str, str], None]] = None,
    trigger_type: str = "test_run",
    execution_id: Optional[Any] = None,
    workflow_id: Optional[Any] = None,
    env_vars: Optional[dict[str, str]] = None,
) -> dict:
    """异步执行工作流图。

    Args:
        graph_config: 工作流图配置，含 ``nodes``、``edges``、可选 ``variables``。
        payload: 触发 payload。
        log_callback: 可选日志回调，签名 ``(node_id, level, message)``。
        trigger_type: 触发类型，仅用于日志标记。
        execution_id: 执行 ID（注入到 ctx 供 ${execution_id} 引用）。
        workflow_id: 工作流 ID（注入到 ctx 供 ${workflow_id} 引用）。
        env_vars: 已解密的环境变量字典 ``{name: value}``，注入到 ctx.env 供
            节点参数中 ``${env.名称}`` 引用。None 或空字典则不注入 env 字段。

    Returns:
        ``{"status", "traces", "ctx", "logs"}``。
        traces 元素含 node_id/node_type/status/input/output/started_at/finished_at；
        logs 元素含 node_id/level/message/timestamp。
    """
    nodes: list[dict] = graph_config.get("nodes", []) or []
    edges: list[dict] = graph_config.get("edges", []) or []
    node_map: dict[str, dict] = {n["id"]: n for n in nodes}

    logs: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    # 初始化上下文：注入 payload、工作流级变量、内置上下文变量、环境变量
    ctx: dict[str, Any] = {"payload": payload}

    # 工作流级自定义变量：graph_config.variables = [{ name, description, default_value }]
    variables_list = graph_config.get("variables", []) or []
    workflow_vars: dict[str, Any] = {}
    for v in variables_list:
        name = v.get("name") if isinstance(v, dict) else None
        if name:
            workflow_vars[name] = v.get("default_value")
    ctx["variables"] = workflow_vars

    # 环境变量：${env.名称} 引用（已由调用方解密为明文）
    if env_vars:
        ctx["env"] = dict(env_vars)

    # 内置上下文变量
    ctx["execution_id"] = execution_id
    ctx["workflow_id"] = workflow_id
    ctx["timestamp"] = beijing_now_iso()

    def log(node_id: str, level: str, message: str) -> None:
        ts = beijing_now_iso()
        logs.append({
            "node_id": node_id,
            "level": level,
            "message": message,
            "timestamp": ts,
        })
        if log_callback is not None:
            try:
                log_callback(node_id, level, message)
            except Exception as exc:  # noqa: BLE001
                logger.debug("log_callback 异常: %s", exc)

    if workflow_vars:
        log("workflow", "info", f"已加载 {len(workflow_vars)} 个工作流变量: {list(workflow_vars.keys())}")
    if env_vars:
        log("workflow", "info", f"已加载 {len(env_vars)} 个环境变量: {list(env_vars.keys())}")

    logger.info("run_workflow 启动: trigger_type=%s, nodes=%d, edges=%d", trigger_type, len(nodes), len(edges))

    # 1. 拓扑排序校验 DAG（检测环）
    try:
        topological_sort(nodes, edges)
    except ValueError as exc:
        log("workflow", "error", f"工作流图校验失败: {exc}")
        return {"status": "failed", "traces": traces, "ctx": _safe_jsonable(ctx), "logs": logs}

    # 2. 计算入口节点（入度为 0）
    in_degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    for edge in edges:
        target = edge.get("target")
        if target in in_degree:
            in_degree[target] += 1
    entry_nodes: list[str] = [nid for nid, deg in in_degree.items() if deg == 0]
    log("workflow", "info", f"入口节点: {entry_nodes}")

    if not entry_nodes:
        log("workflow", "error", "未找到入口节点")
        return {"status": "failed", "traces": traces, "ctx": _safe_jsonable(ctx), "logs": logs}

    # 3. BFS 遍历执行
    queue: deque[str] = deque(entry_nodes)
    visited: set[str] = set()
    status = "success"

    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)

        node = node_map.get(node_id)
        if node is None:
            log(node_id, "warning", f"节点不在图中，跳过: {node_id}")
            continue

        node_type: str = node.get("type", "unknown")
        node_data: dict = {**(node.get("data", {}) or {}), "id": node_id}
        # 执行前解析节点 data 中的 ${var} 变量引用（深拷贝后替换，不污染原图）
        node_data = resolve_variables(node_data, ctx)
        node_input = _build_node_input(node_type, node_data, ctx, payload)

        started_at = beijing_now()
        log(node_id, "info", f"开始执行节点 type={node_type}")
        try:
            output = await execute_node(node_type, node_data, node_input, ctx, log)
            node_status = "success"
            log(node_id, "info", f"节点执行完成 type={node_type}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("节点执行异常: %s", node_id)
            output = {"error": str(exc)}
            node_status = "failed"
            log(node_id, "error", f"节点执行异常: {exc}")
        finished_at = beijing_now()

        traces.append({
            "node_id": node_id,
            "node_type": node_type,
            "status": node_status,
            "input": _safe_jsonable(node_input),
            "output": _safe_jsonable(output),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        })

        ctx[node_id] = output

        if node_status == "failed":
            status = "failed"
            # 失败即终止（与 Celery 任务行为一致）
            break

        # 条件路由：读 ctx["_route"] 选择下游
        route: Optional[str] = ctx.get("_route") if node_type == "condition_branch" else None
        next_ids = find_next_nodes(edges, node_id, route)
        log(node_id, "info", f"下游节点: {next_ids}")
        for nid in next_ids:
            if nid not in visited:
                queue.append(nid)

    log("workflow", "info", f"工作流执行结束 status={status}")
    return {
        "status": status,
        "traces": traces,
        "ctx": _safe_jsonable(ctx),
        "logs": logs,
    }
