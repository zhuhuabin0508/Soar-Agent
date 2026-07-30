"""Celery 任务包。

导入此包时会自动注册 :func:`execute_workflow` 任务。
"""
from app.tasks.workflow_tasks import execute_workflow

__all__ = ["execute_workflow"]
