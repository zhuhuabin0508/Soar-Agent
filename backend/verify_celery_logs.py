"""运行时验证：Celery 工作流执行日志留存。容器内执行：docker exec soar-worker python /tmp/verify_celery_logs.py

直接同步调用 execute_workflow（Celery task 对象可直接调用以同步执行函数体），
验证 ExecutionLog 表有日志写入。
"""
import json
from datetime import datetime

from app.database import SessionLocal
from app.models import Execution, ExecutionLog
from app.tasks.workflow_tasks import execute_workflow

# 简单图：webhook_trigger -> send_notification
graph_config = {
    "nodes": [
        {"id": "n1", "type": "webhook_trigger", "data": {"method": "POST"}},
        {"id": "n2", "type": "send_notification", "data": {"channel": "email", "body": "test"}},
    ],
    "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
}
payload = {"src_ip": "10.0.0.99", "alert_type": "brute_force"}

db = SessionLocal()
try:
    # 创建 Execution 记录
    execution = Execution(workflow_id=None, status="running", trigger_type="manual")
    db.add(execution)
    db.commit()
    db.refresh(execution)
    eid = execution.id
    print(f"created execution id={eid}")

    # 同步调用 Celery 任务函数
    result = execute_workflow(
        workflow_id=0,
        payload=payload,
        graph_config=graph_config,
        execution_id=eid,
    )
    print("execute_workflow result status:", result.get("status"))

    # 查询 ExecutionLog
    logs = (
        db.query(ExecutionLog)
        .filter(ExecutionLog.execution_id == eid)
        .order_by(ExecutionLog.timestamp.asc())
        .all()
    )
    print(f"ExecutionLog count: {len(logs)}")
    for lg in logs[:8]:
        print(f"  [{lg.level}] node={lg.node_id}: {lg.message}")

    # 复查 Execution 最终状态
    db.refresh(execution)
    print(f"execution final status: {execution.status}, finished_at: {execution.finished_at}")

    assert len(logs) > 0, "ExecutionLog 未写入！"
    print("\nCELERY LOGS PERSISTENCE PASSED")
finally:
    db.close()
