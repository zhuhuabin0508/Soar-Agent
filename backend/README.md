# SOAR Platform Backend

SOAR 平台后端骨架（阶段一：基建）。技术栈：Python + FastAPI + Celery + PostgreSQL + Redis + SQLAlchemy，依赖管理使用 pip + requirements.txt。

## 目录结构

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 入口，挂载 /api/v1 路由
│   ├── config.py                # Pydantic Settings 配置
│   ├── database.py              # SQLAlchemy engine + SessionLocal + Base
│   ├── models/                  # ORM 模型 (Workflow, Execution)
│   ├── schemas/                 # Pydantic Schema
│   ├── api/v1/                  # 业务路由 (workflows, webhook, health)
│   ├── core/                    # Celery 实例 + DAG 拓扑排序解析器
│   └── tasks/                   # Celery 任务 (execute_workflow)
├── requirements.txt
├── .env.example
└── README.md
```

## 环境准备

需要预先启动 PostgreSQL 与 Redis。

1. 复制环境变量文件并按需修改：
   ```bash
   cp .env.example .env
   ```
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 在 PostgreSQL 中创建数据库 `soar`，并建表：
   ```bash
   python -c "from app.database import Base, engine; from app.models import Workflow, Execution; Base.metadata.create_all(bind=engine)"
   ```

## 启动

### 启动 FastAPI（API 服务）

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：
- 健康检查：`GET http://localhost:8000/api/v1/health`
- API 文档：`http://localhost:8000/docs`

### 启动 Celery Worker（异步执行）

```bash
celery -A app.core.celery_app worker --loglevel=info
```

## 主要端点

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | `/api/v1/workflows` | 创建工作流 |
| GET | `/api/v1/workflows` | 列出工作流 |
| GET | `/api/v1/workflows/{id}` | 工作流详情 |
| PUT | `/api/v1/workflows/{id}` | 更新工作流 |
| DELETE | `/api/v1/workflows/{id}` | 删除工作流 |
| POST | `/api/v1/webhook/{workflow_id}` | 接收告警并触发异步执行 |
| GET | `/api/v1/health` | 健康检查 |

## 调用示例

1. 创建工作流：
   ```bash
   curl -X POST http://localhost:8000/api/v1/workflows \
     -H "Content-Type: application/json" \
     -d '{"name":"demo","graph_config":{"nodes":[{"id":"n1","type":"webhook"},{"id":"n2","type":"notify"}],"edges":[{"source":"n1","target":"n2"}]}}'
   ```
2. 触发执行（假设返回的 workflow id 为 1）：
   ```bash
   curl -X POST http://localhost:8000/api/v1/webhook/1 \
     -H "Content-Type: application/json" \
     -d '{"src_ip":"1.2.3.4","alert":"test"}'
   ```
