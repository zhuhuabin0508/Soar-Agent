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
- **React 19** + **Vite** — UI 框架与开发服务器（HMR）
- **TailwindCSS** — 样式
- **React Flow** — 工作流可视化编排
- **Zustand** — 状态管理
- **ECharts** — 数据可视化

### 基础设施
- **Docker Compose** — 唯一编排：postgres / redis / backend-dev / worker-dev / beat-dev / frontend-dev
- **Vite Dev Server** — 前端热更新 + `/api` 反向代理

## 🚀 部署架构

**只有一套环境：源码挂载 + 热重载。** 已去掉 Nginx 前端镜像栈（`soar-frontend` / `soar-backend` 无 `-dev` 后缀的那套）。

| 组件 | 容器 | 机制 |
|------|------|------|
| 后端 API | `soar-backend-dev` | 挂载 `./backend/app` + `uvicorn --reload`，改 `.py` 自动重启 |
| 前端 | `soar-frontend-dev` | 挂载 `./frontend` + Vite HMR，改前端文件自动热更新 |
| 异步任务 | `soar-worker-dev` | 挂载源码 + Celery（改代码需手动重启） |
| 定时调度 | `soar-beat-dev` | 挂载源码 + Celery Beat |
| 数据库 | `soar-postgres` | PostgreSQL 15 |
| 缓存 | `soar-redis` | Redis 7.4 |

端口映射：

- 前端：`8080`（映射容器内 Vite `5173`）
- 后端 API：`8001`（映射容器内 `8000`）
- PostgreSQL：`5432`

后端仍使用镜像 `soar-backend:latest`（Python 依赖预装），源码通过挂载覆盖，不必每次改代码都 rebuild。前端不打镜像，直接用 `node:20-alpine`。

## 🚀 快速开始

### 环境要求

- Docker & Docker Compose
- 已有 `soar-backend:latest`（或先执行 `bash scripts/build-and-export-images.sh`）
- Linux 内核 `fs.inotify` 限制足够（热重载依赖，见下方「inotify 限制」）

### 启动

```bash
cp .env.example .env.dev   # 按环境修改密码与 JWT_SECRET

# 方式一
bash dev.sh up

# 方式二
docker compose --env-file .env.dev up -d
```

启动后访问：

- 前端：`http://<服务器IP>:8080`
- 后端 API 文档：`http://<服务器IP>:8001/docs`

默认管理员账号由 `.env.dev` 中的 `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD` 决定（首次空库 seed 时创建）。

### 从旧「镜像栈」切过来

仓库里已删除 `docker-compose.dev.yml` 和 Nginx 前端镜像编排。机器上如果还在跑没有 `-dev` 后缀的容器，或 postgres 是旧编排起的：

```bash
# 只删容器，不要带 -v（数据卷 soaragent_pgdata 必须保留）
docker rm -f soar-frontend soar-backend soar-worker soar-beat
# 若即将由新编排接管库和 Redis，先去掉旧容器（数据在卷里）
docker rm -f soar-postgres soar-redis
bash dev.sh up
```

已在跑 `soar-*-dev` 的服务器：`git pull` 后执行一次 `bash dev.sh up` 即可套用新编排（会补上 postgres/redis/beat）。名称冲突时按上面先 `docker rm` 旧容器。

## 🔄 日常更新部署

本地改代码 → 提交推送 → 服务器执行更新脚本，源码同步后**热重载自动生效**，无需重新构建镜像：

```bash
# 常规更新（源码热重载自动生效）
sudo bash scripts/update.sh

# 同时重启 worker（改了 Celery 相关代码时）
RESTART_WORKER=1 sudo bash scripts/update.sh
```

> **注意**：
> - 只改源码（`.py` / `.tsx` / `.jsx` / `.css` 等）热重载自动生效，无需任何手动操作。
> - 改了 `requirements.txt` / `package.json`（增删依赖）热重载**不会**自动安装，`update.sh` 会检测并提示手动执行安装命令。
> - 改了 docker-compose、环境变量等需手动 `bash dev.sh up` 重建容器。

### inotify 限制

`uvicorn --reload` 与 Vite 依赖文件监听，若 `fs.inotify.max_user_watches` 过低会报 `OS file watch limit reached` / `ENOSPC`。`update.sh` 每次运行会自动检查并设置（同时永久化写入 `/etc/sysctl.conf`）。手动设置一次：

```bash
sysctl -w fs.inotify.max_user_watches=524288
echo "fs.inotify.max_user_watches=524288" >> /etc/sysctl.conf
sysctl -w fs.inotify.max_user_instances=512
echo "fs.inotify.max_user_instances=512" >> /etc/sysctl.conf
```

## ⚙️ 配置说明

所有配置通过 `.env.dev` 注入。主要配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `POSTGRES_DB` | 数据库名 | 以 `.env.dev` 为准（示例为 `soar`） |
| `POSTGRES_PASSWORD` | 数据库密码 | `postgres` |
| `JWT_SECRET` | JWT 签名密钥 | 见 `.env.dev` |
| `SEED_ADMIN_USERNAME` | 初始管理员账号 | `admin` |
| `SEED_ADMIN_PASSWORD` | 初始管理员密码 | 见 `.env.dev` |

> **安全提示**：LLM 的 API Key 在系统「模型设置」页面配置，存储于数据库，不出现在代码或环境变量中。

## 📁 项目结构

```
.
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── agent/            # Hermes ReAct 引擎
│   │   ├── api/v1/           # REST API 端点
│   │   ├── core/             # 配置、安全、种子数据、Celery
│   │   ├── models/           # SQLAlchemy 数据模型
│   │   ├── tools/            # 工具实现（资产查询、威胁情报、封禁等）
│   │   └── tasks/            # Celery 异步任务
│   ├── Dockerfile
│   ├── requirements.txt
│   └── entrypoint.sh
├── frontend/                 # React 前端
│   ├── src/
│   │   ├── pages/            # 页面组件
│   │   ├── components/       # 通用组件
│   │   ├── api/              # API 客户端
│   │   └── store/            # Zustand 状态
│   ├── vite.config.dev.js    # dev server 配置（HMR + /api 代理）
│   └── package.json
├── scripts/
│   ├── update.sh             # 热重载部署更新脚本
│   ├── build-and-export-images.sh  # 联网构建后端镜像并导出 tar
│   └── ...
├── docs/                     # 设计文档
├── docker-compose.yml        # 唯一运行环境（热重载）
├── docker-compose.security-tools.yml  # DefectDojo / BloodHound（可选）
├── .env.dev                  # 环境变量（不入库，从 .env.example 复制）
├── .env.example              # 环境变量模板
└── dev.sh                    # 启动/停止/日志便捷脚本
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
- 数据库凭证、JWT 密钥等均通过环境变量注入，`.env*` 已在 `.gitignore` 中
- 业务数据存储于 Docker 数据卷（`soaragent_pgdata`），不在代码仓库中

## 📄 许可证

本项目仅供学习与内部使用。

测试推送
