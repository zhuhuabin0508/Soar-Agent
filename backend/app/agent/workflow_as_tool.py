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
