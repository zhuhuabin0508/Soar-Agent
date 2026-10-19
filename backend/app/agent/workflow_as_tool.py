from __future__ import annotations

import re
from typing import Any, Optional

GLOBAL_WORKFLOW_TOOL_NAMES = frozenset({
    "trigger_workflow_skill",
    "list_workflow_skills",
})


def make_tool_name(workflow_id: int, name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", name or "").strip("_")
    slug = slug[:40]
    if slug and re.match(r"^[A-Za-z]", slug):
        return f"workflow_{workflow_id}_{slug}"
    return f"workflow_{workflow_id}"


def infer_parameters(graph_config: Any) -> dict:
    properties: dict[str, Any] = {}
    required: list[str] = []
    nodes = []
    if isinstance(graph_config, dict):
        nodes = graph_config.get("nodes") or []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data") or {}
        ntype = node.get("type") or data.get("type") or ""
        if ntype not in ("webhook_trigger", "manual_trigger", "start"):
            continue
        for item in (data.get("body_params") or []) + (data.get("entry_form") or []):
            if not isinstance(item, dict):
                continue
            pname = (item.get("name") or "").strip()
            if not pname or pname in properties:
                continue
            properties[pname] = {
                "type": "string",
                "description": item.get("description") or pname,
            }
            if item.get("required"):
                required.append(pname)
        break
    if not properties:
        properties = {
            "input": {
                "type": "object",
                "description": "工作流输入参数",
            }
        }
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    return schema


# ============================================================================
# 工作流 → 危险等级 / 自门控（供确认闸使用）
# ============================================================================

# 节点类型 → 危险等级（保守映射：不确定的一律 high，避免绕过确认）
_DANGER_NODE_TYPES = {
    "block_ip": "high",
    "device_action": "high",
    "tool": "high",              # 图内调工具，具体工具未知 → 保守 high
    "send_notification": "low",
}
_DANGER_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
# 自带人工审批的节点 → 该工作流「自门控」，Agent 侧不再二次确认
_APPROVAL_NODE_TYPES = frozenset({"human_review", "approval_ticket"})


def _iter_nodes(graph_config: Any) -> list[dict]:
    if isinstance(graph_config, dict):
        return [n for n in (graph_config.get("nodes") or []) if isinstance(n, dict)]
    return []


def _node_type(node: dict) -> str:
    data = node.get("data") or {}
    return str(node.get("type") or data.get("type") or "")


def workflow_danger(graph_config: Any) -> str:
    """工作流危险等级 = 图内节点的最高危险（无节点 → low）。"""
    levels = [_DANGER_NODE_TYPES.get(_node_type(n), "low") for n in _iter_nodes(graph_config)]
    if not levels:
        return "low"
    return max(levels, key=lambda x: _DANGER_RANK.get(x, 0))


def workflow_self_gates(graph_config: Any) -> bool:
    """图内是否含 human_review / approval_ticket 节点（自带人工审批）。"""
    return any(_node_type(n) in _APPROVAL_NODE_TYPES for n in _iter_nodes(graph_config))


async def invoke_workflow_as_tool(
    *,
    db,
    workflow_id: int,
    agent_id: Optional[int],
    payload: dict,
) -> dict:
    from app.core.security import decrypt_env_value
    from app.core.workflow_runner import run_workflow
    from app.models.execution import Execution
    from app.models.workflow import Workflow

    wf = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.enabled.is_(True))
        .first()
    )
    if wf is None:
        return {"error": f"Workflow {workflow_id} not found or disabled"}

    execution = Execution(
        workflow_id=workflow_id,
        trigger_type="agent_tool",
        status="running",
        agent_id=agent_id,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    env_vars = {
        v["name"]: decrypt_env_value(v.get("value") or "")
        for v in (wf.env_vars or [])
        if isinstance(v, dict) and v.get("name")
    }
    result = await run_workflow(
        graph_config=wf.graph_config,
        payload=payload if isinstance(payload, dict) else {"input": payload},
        execution_id=execution.id,
        workflow_id=workflow_id,
        env_vars=env_vars,
    )
    execution.status = result.get("status", "failed")
    execution.result = result
    db.commit()
    return result
