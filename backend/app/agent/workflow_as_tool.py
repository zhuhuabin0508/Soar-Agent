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


def _parameters_to_pydantic(model_name: str, parameters: dict):
    from pydantic import Field, create_model

    props = (parameters or {}).get("properties") or {}
    required = set((parameters or {}).get("required") or [])
    fields: dict[str, Any] = {}
    for key, spec in props.items():
        if not isinstance(spec, dict):
            spec = {}
        desc = spec.get("description") or key
        if key in required:
            fields[key] = (Any, Field(..., description=desc))
        else:
            fields[key] = (Any, Field(default=None, description=desc))
    if not fields:
        fields["input"] = (dict, Field(default_factory=dict, description="工作流输入参数"))
    return create_model(model_name, **fields)


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


def build_langchain_workflow_tools(db, enabled_workflows: list, agent_id: Optional[int] = None) -> list:
    from langchain_core.tools import StructuredTool
    from app.models.workflow import Workflow

    tools: list = []
    for raw_id in enabled_workflows or []:
        try:
            wf_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        wf = (
            db.query(Workflow)
            .filter(Workflow.id == wf_id, Workflow.enabled.is_(True))
            .first()
        )
        if wf is None:
            continue
        tool_name = make_tool_name(wf.id, wf.name)
        description = (wf.description or "").strip() or f"运行已发布工作流：{wf.name}"
        parameters = infer_parameters(wf.graph_config)
        args_model = _parameters_to_pydantic(f"{tool_name}Args", parameters)
        captured_id = wf.id

        async def _coroutine(_wf_id=captured_id, **kwargs):
            from app.database import SessionLocal

            session = SessionLocal()
            try:
                return await invoke_workflow_as_tool(
                    db=session,
                    workflow_id=_wf_id,
                    agent_id=agent_id,
                    payload=kwargs,
                )
            finally:
                session.close()

        tools.append(
            StructuredTool.from_function(
                name=tool_name,
                description=description,
                args_schema=args_model,
                coroutine=_coroutine,
            )
        )
    return tools
