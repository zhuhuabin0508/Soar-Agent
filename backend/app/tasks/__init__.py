"""Celery 任务包。

导入此包时会自动注册 :func:`execute_workflow` 和 :func:`scan_asset_agents` 任务。
"""
from app.tasks.asset_tasks import scan_asset_agents
from app.tasks.workflow_tasks import execute_workflow

__all__ = ["execute_workflow", "scan_asset_agents"]
