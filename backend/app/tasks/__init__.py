"""Celery 任务包。

导入此包时会自动注册 :func:`execute_workflow` / :func:`execute_approved_tool` 任务。
"""
from app.tasks.approval_tasks import execute_approved_tool
from app.tasks.workflow_tasks import execute_workflow

__all__ = ["execute_workflow", "execute_approved_tool"]
