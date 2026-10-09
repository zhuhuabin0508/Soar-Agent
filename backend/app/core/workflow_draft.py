"""工作流草稿生成：自然语言 → 规则化骨架（V2.4 PoC，后续可接 LLM）。"""
from __future__ import annotations

from typing import Any


def generate_workflow_skeleton_from_text(text: str) -> dict[str, Any]:
    t = (text or "").lower()
    has_ban = any(k in t for k in ("封禁", "block", "ban"))
    has_notify = any(k in t for k in ("通知", "邮件", "值班", "alert"))
    has_webhook = any(k in t for k in ("告警", "webhook", "入库"))
    name = (text or "").strip()[:40] or "AI 生成工作流草稿"
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    last_id: str | None = None

    def add(node_id: str, node_type: str, label: str, data: dict[str, Any] | None = None) -> None:
        nonlocal last_id
        nodes.append({
            "id": node_id,
            "type": node_type,
            "position": {"x": 80 + len(nodes) * 280, "y": 80},
            "data": {"label": label, **(data or {})},
        })
        if last_id:
            edges.append({
                "id": f"e_{last_id}_{node_id}",
                "source": last_id,
                "target": node_id,
                "animated": True,
            })
        last_id = node_id

    if has_webhook or not last_id:
        add("n_webhook", "webhook_trigger", "接收告警", {
            "method": "POST",
            "body_params": [
                {"name": "src_ip", "type": "String", "required": True},
                {"name": "alert_type", "type": "String", "required": True},
            ],
        })
    add("n_agent", "ai_agent", "AI 研判", {
        "agent_id": None,
        "user_prompt": "请根据告警研判源 IP：{{payload.src_ip}}",
    })
    if has_ban:
        add("n_block", "block_ip", "封禁 IP", {"ip": "{{payload.src_ip}}", "duration": 86400})
    if has_notify:
        add("n_notify", "send_notification", "发送通知", {
            "channel": "email",
            "title": "处置完成",
            "content": "工作流已执行",
        })
    return {"name": name, "graph_config": {"nodes": nodes, "edges": edges, "variables": []}}
