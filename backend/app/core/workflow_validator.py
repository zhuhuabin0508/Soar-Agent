"""工作流可运行性校验。

提供 :func:`validate_workflow`，对前端传入的 ``graph_config`` 进行结构与
语义层面的校验，返回阻断性错误（``errors``）与提示性警告（``warnings``）。

校验规则参见项目契约1：
- 空图、悬空边、环、无入口节点为阻断错误；
- 多入口、入口类型非 webhook_trigger、悬空节点、条件分支出口缺失为警告。
"""
import logging

from app.core.dag import topological_sort

logger = logging.getLogger(__name__)


def validate_workflow(graph_config: dict) -> dict:
    """校验工作流图配置的可运行性。

    Args:
        graph_config: 工作流图配置，含 ``nodes`` 与 ``edges``。

    Returns:
        ``{"valid": bool, "errors": list[str], "warnings": list[str]}``。
        ``valid`` 为 ``True`` 当且仅当 ``errors`` 为空。
    """
    errors: list[str] = []
    warnings: list[str] = []

    nodes: list[dict] = (graph_config or {}).get("nodes", []) or []
    edges: list[dict] = (graph_config or {}).get("edges", []) or []

    # 1. 空图校验
    if not nodes:
        errors.append("工作流为空，没有任何节点")
        return {"valid": False, "errors": errors, "warnings": warnings}

    node_ids: set[str] = {n.get("id") for n in nodes if n.get("id")}

    # 2. 边指向不存在节点校验
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids or target not in node_ids:
            errors.append(f"连线 {source}->{target} 指向不存在的节点")

    # 3. 环检测（仅在节点 id 合法时尝试，避免 topological_sort 内部 KeyError）
    if not errors:
        try:
            topological_sort(nodes, edges)
        except ValueError:
            errors.append("工作流存在环")

    # 4. 入口节点（入度为 0）分析
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    out_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in in_degree and target in in_degree:
            in_degree[target] += 1
            out_degree[source] += 1

    entry_nodes: list[str] = [nid for nid, deg in in_degree.items() if deg == 0]

    if not entry_nodes:
        # 整体成环，无入口
        errors.append("未找到入口节点（入度为0的节点），可能存在环")
    else:
        # 4.1 多入口警告
        if len(entry_nodes) > 1:
            warnings.append(f"存在多个入口节点：{entry_nodes}，建议仅保留一个触发器入口")
        # 4.2 入口类型警告
        for nid in entry_nodes:
            node = next((n for n in nodes if n.get("id") == nid), None)
            if node is None:
                continue
            ntype = node.get("type", "unknown")
            if ntype != "webhook_trigger":
                warnings.append(
                    f"入口节点 {nid}({ntype}) 不是 Webhook 触发器，可能无法被外部事件触发"
                )

    # 5. 悬空节点警告（既无入边也无出边，且不是唯一节点）
    if len(nodes) > 1:
        for node in nodes:
            nid = node.get("id")
            if nid is None:
                continue
            if in_degree.get(nid, 0) == 0 and out_degree.get(nid, 0) == 0:
                ntype = node.get("type", "unknown")
                warnings.append(f"节点 {nid}({ntype}) 未连接到任何其它节点")

    # 6. condition_branch 出口完整性检查
    for node in nodes:
        nid = node.get("id")
        if nid is None:
            continue
        if node.get("type") != "condition_branch":
            continue
        data = node.get("data") or {}
        _check_condition_branch_outputs(nid, data, edges, warnings)

    valid = len(errors) == 0
    logger.info(
        "工作流校验完成: valid=%s, errors=%d, warnings=%d",
        valid,
        len(errors),
        len(warnings),
    )
    return {"valid": valid, "errors": errors, "warnings": warnings}


def _check_condition_branch_outputs(
    node_id: str,
    node_data: dict,
    edges: list[dict],
    warnings: list[str],
) -> None:
    """检查条件分支节点的所有出口是否都有对应的下游边。

    Handle ID 方案（与前端 BranchHandles 对齐）：
    - if_else 模式：``true`` / ``false``
    - switch 模式：``br_0``, ``br_1``, ... ``default``

    Args:
        node_id: 条件分支节点 id。
        node_data: 节点 data 字段。
        edges: 全图边列表。
        warnings: 警告收集列表（会被追加）。
    """
    # 当前节点所有出边的 sourceHandle 集合
    out_handles: set[str] = set()
    for edge in edges:
        if edge.get("source") == node_id:
            sh = edge.get("sourceHandle")
            if sh is not None:
                out_handles.add(sh)

    mode = node_data.get("mode") or "if_else"

    if mode == "switch":
        cases = node_data.get("cases") or []
        expected_handles: list[str] = [f"br_{i}" for i in range(len(cases))]
        expected_handles.append("default")
        for i, h in enumerate(expected_handles):
            label = cases[i].get("label", f"分支{i + 1}") if i < len(cases) else "默认"
            if h not in out_handles:
                warnings.append(
                    f"条件分支节点 {node_id} 的「{label}」出口未连接下游"
                )
        return

    # if_else 模式
    if "true" not in out_handles:
        true_label = node_data.get("true_label") or "是"
        warnings.append(f"条件分支节点 {node_id} 的「{true_label}」出口未连接下游")
    if "false" not in out_handles:
        false_label = node_data.get("false_label") or "否"
        warnings.append(f"条件分支节点 {node_id} 的「{false_label}」出口未连接下游")
