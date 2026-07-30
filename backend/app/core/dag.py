"""DAG 拓扑排序解析器（Kahn 算法）。

提供 :func:`topological_sort`，根据节点与边列表返回拓扑排序后的节点序列。
若检测到环则抛出 :class:`ValueError`。
"""
import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


def topological_sort(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """对节点和边执行 Kahn 算法拓扑排序。

    Args:
        nodes: 节点列表，每个节点至少含 ``id`` 字段，通常还含 ``type`` / ``data``。
        edges: 边列表，每条边含 ``source`` 与 ``target`` 字段。

    Returns:
        拓扑排序后的节点列表（顺序保证：被依赖的节点排在前面）。

    Raises:
        ValueError: 当图中存在环时抛出 ``DAG contains a cycle``。
    """
    logger.info("Starting topological sort: nodes=%d, edges=%d", len(nodes), len(edges))

    # 节点 id -> 节点对象
    node_map: dict[str, dict] = {node["id"]: node for node in nodes}
    node_ids: list[str] = list(node_map.keys())
    logger.debug("Node ids: %s", node_ids)

    # 邻接表与入度表
    adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}

    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        adjacency[source].append(target)
        in_degree[target] += 1
        logger.debug("Edge: %s -> %s", source, target)

    # 入口节点：入度为 0
    queue: deque[str] = deque([nid for nid in node_ids if in_degree[nid] == 0])
    entry_nodes = list(queue)
    logger.info("Entry nodes (in-degree=0): %s", entry_nodes)

    sorted_nodes: list[dict] = []
    visited_count = 0

    while queue:
        current_id = queue.popleft()
        current_node = node_map[current_id]
        sorted_nodes.append(current_node)
        visited_count += 1
        logger.debug(
            "Visiting node: %s (type=%s)",
            current_id,
            current_node.get("type"),
        )

        for neighbor in adjacency[current_id]:
            in_degree[neighbor] -= 1
            logger.debug(
                "Decremented in-degree of %s to %d",
                neighbor,
                in_degree[neighbor],
            )
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    logger.info("Visited %d / %d nodes", visited_count, len(node_ids))

    if visited_count != len(node_ids):
        unvisited = [nid for nid in node_ids if in_degree[nid] > 0]
        logger.error(
            "Cycle detected: only %d of %d nodes visited, unvisited=%s",
            visited_count,
            len(node_ids),
            unvisited,
        )
        raise ValueError("DAG contains a cycle")

    logger.info(
        "Topological sort completed. Order: %s",
        [n["id"] for n in sorted_nodes],
    )
    return sorted_nodes


def find_next_nodes(
    edges: list[dict], current_node_id: str, decision_value: Optional[str] = None
) -> list[str]:
    """根据当前节点与决策值查找下游生效节点。

    条件路由节点（condition_branch）的出边带有 ``sourceHandle`` 字段，
    用于标识分支（如 "block_ip" / "ignore" / "need_human_approval"）。
    本函数根据 ``decision_value`` 匹配对应分支的下游节点。

    - 若边携带 ``sourceHandle``：仅返回 ``sourceHandle == decision_value`` 的目标节点。
    - 若边无 ``sourceHandle``：视为普通顺序执行，返回所有目标节点。

    Args:
        edges: 工作流图的边列表。
        current_node_id: 当前执行完成的节点 id。
        decision_value: 条件分支决策值（如 "block_ip"）；普通节点传 None。

    Returns:
        下游生效节点 id 列表（可能为空）。
    """
    next_ids: list[str] = []
    matched_branch: bool = False

    for edge in edges:
        if edge.get("source") != current_node_id:
            continue
        source_handle = edge.get("sourceHandle")
        target = edge.get("target")
        if target is None:
            continue

        # 带 sourceHandle 的边：仅当与决策值匹配时才生效
        if source_handle is not None:
            if decision_value is not None and source_handle == decision_value:
                next_ids.append(target)
                matched_branch = True
                logger.debug(
                    "条件分支命中: %s --[%s]--> %s",
                    current_node_id,
                    source_handle,
                    target,
                )
            else:
                logger.debug(
                    "条件分支跳过: %s --[%s]--> %s (decision=%s)",
                    current_node_id,
                    source_handle,
                    target,
                    decision_value,
                )
        else:
            # 普通边：顺序执行
            next_ids.append(target)
            logger.debug("顺序下游: %s --> %s", current_node_id, target)

    logger.info(
        "find_next_nodes: current=%s, decision=%s, next=%s, matched_branch=%s",
        current_node_id,
        decision_value,
        next_ids,
        matched_branch,
    )
    return next_ids
