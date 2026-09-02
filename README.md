# SOAR 智能安全运营平台

一个面向安全运营自动化（SOAR）的全栈平台，集成智能体编排、工作流自动化、知识库检索、威胁情报研判与封禁决策能力。基于 Hermes 引擎实现可观测的 ReAct 智能体，支持流式输出、工具调用、技能注入与多轮对话上下文。

## ✨ 核心功能

- **智能体管理**：基于 Hermes 引擎的 ReAct 智能体，支持流式输出（SSE）、工具调用、技能注入、多轮对话上下文持久化、思考过程展示
- **工作流编排**：可视化拖拽编排（React Flow），支持 AI 智能体节点、条件分支、HTTP 节点、Webhook 触发，节点输出变量以卡片形式展示
- **知识库**：文档上传/分段/向量化/检索（BM25 + 向量），支持 Excel/Word/PDF/CSV/TXT，配置分块模式、索引模式、Embedding 模型
- **工具系统**：HTTP/OpenAPI 工具，GET/POST/DELETE 方法色标区分，参数映射、执行时机（自动/确认）、异常处理配置
- **技能系统**：纯文本指令注入智能体 system prompt
- **IP 风险研判与封禁决策**：智能体自动查询资产归属与威胁情报，输出 6 模块研判报告，支持封禁时长计算与记录管理
- **已封禁 IP 管理**：手动/智能体两种来源标识，支持手动新增、解封、硬删除、CSV 导入导出
- **系统监控**：服务健康、容器日志查看、模型调用监控、审计日志（记录所有写操作含 IP）
- **权限体系**：基于角色的访问控制（RBAC），管理员/分析师/访客
- **通知中心**：系统更新自动推送更新明细

## 🏗️ 技术栈

### 后端
- **FastAPI** + **Uvicorn** — API 服务
- **SQLAlchemy** + **PostgreSQL** — ORM 与数据存储
- **Celery** + **Redis** — 异步任务与消息中间件
- **LangGraph** + **LangChain** — 智能体框架（Hermes 引擎）
- **PyJWT** + **passlib/bcrypt** — 鉴权与密码哈希

### 前端
- **React 19** + **Vite** — UI 框架与构建工具
- **TailwindCSS** — 样式
- **React Flow** — 工作流可视化编排
- **Zustand** — 状态管理
- **ECharts** — 数据可视化

### 基础设施
- **Docker Compose** — 一键编排（postgres / redis / backend / worker / frontend）
- **Nginx** — 前端静态资源 + 反向代理（SSE 流式关闭缓冲）

## 🚀 快速开始

### 环境要求
- Docker & Docker Compose
- 端口：8080（前端）、8001（后端）、5432（PostgreSQL）、6379（Redis）

### 一键部署

```bash
# 1.（可选）配置环境变量，覆盖开发默认值
cp .env.example .env
# 编辑 .env，生产环境务必修改 JWT_SECRET、数据库密码、管理员密码

# 2. 构建并启动所有服务
docker compose up -d --build

# 3. 访问平台
#    前端：http://localhost:8080
#    后端 API：http://localhost:8001/docs
#    默认管理员：admin / admin123（首次启动自动创建）
```

### 重建后端后的注意事项

重建后端容器会改变其容器 IP，前端 Nginx 可能缓存旧 IP 导致 502。重建后需重启前端容器刷新 DNS：

```bash
docker compose up -d --build backend
docker restart soar-frontend
```

## ⚙️ 配置说明

所有配置项通过环境变量注入，开发默认值见 `.env.example`。主要配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `POSTGRES_PASSWORD` | 数据库密码 | `postgres`（生产必改）|
| `JWT_SECRET` | JWT 签名密钥 | 开发占位值（生产必改）|
| `SEED_ADMIN_PASSWORD` | 初始管理员密码 | `admin123`（生产必改）|
| `CORS_ORIGINS` | CORS 允许源 | 本地开发地址 |

> **安全提示**：LLM 的 API Key 在系统「模型设置」页面配置，存储于数据库，不出现在代码或环境变量中。

## 📁 项目结构

```
.
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── agent/hermes/   # Hermes ReAct 引擎（执行器、SSE、工具引擎）
│   │   ├── api/v1/         # REST API 端点
│   │   ├── core/           # 配置、安全、种子数据、Celery
│   │   ├── models/         # SQLAlchemy 数据模型
│   │   ├── tools/          # 工具实现（资产查询、威胁情报、封禁等）
│   │   └── tasks/          # Celery 异步任务
│   ├── Dockerfile
│   ├── requirements.txt
│   └── entrypoint.sh
├── frontend/               # React 前端
│   ├── src/
│   │   ├── pages/          # 页面组件
│   │   ├── components/     # 通用组件
│   │   ├── api/            # API 客户端
│   │   └── store/          # Zustand 状态
│   ├── Dockerfile
│   └── package.json
├── docs/                   # 设计文档
├── docker-compose.yml      # 一键编排
├── .env.example            # 环境变量模板
└── .gitignore
```

## 📖 设计文档

- [Hermes 引擎集成](docs/hermes-engine-integration.md)
- [Hermes 附加功能集成](docs/hermes-additional-features-integration.md)
- [技能系统 Prompt 注入](docs/skill-system-prompt-injection.md)
- [工具迁移到系统级](docs/hermes-tools-migration-to-system.md)

## 🔒 安全说明

- 密码使用 bcrypt 哈希存储，永不存明文
- JWT 鉴权，所有 API 需登录访问
- 审计日志记录所有写操作（操作人、模块、资源 ID、IP）
- 数据库凭证、JWT 密钥等均通过环境变量注入，`.env` 已在 `.gitignore` 中
- 知识库数据存储于 Docker 数据卷，不在代码仓库中

## 📄 许可证

本项目仅供学习与内部使用。
