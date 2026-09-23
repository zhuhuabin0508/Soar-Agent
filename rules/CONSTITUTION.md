# Agent 宪法（不可协商）

本文件是项目第一层约束。任何任务、任何 Agent、任何场景都不得突破。细则与「为什么」见 `ARCHITECTURE.md`。风格见 `STYLE.md`。AI 生成 Skill/Tool/Agent 或工具代码时见 `AI_CODING_RULES.md`。

`docs/agent-architecture-debt-and-plan.md` **不是宪法**；已拍板条款以本文为准。

---

## 技术栈

- 后端：Python **3.11**（与 `backend/Dockerfile` 的 `python:3.11-slim` 一致）+ FastAPI + SQLAlchemy + PostgreSQL。禁止第二套 Web 框架。
- 前端：React + Vite。禁止为同一产品再开一套前端框架。
- 用户可见运行时：**仅 Hermes**。禁止第三条对话引擎。LangGraph 只用于工作流 DAG。
- 禁止把 Dify / Coze 嵌进本仓库当运行时。
- 异步：Celery + Redis。长扫描可进队列。禁止为工具执行另引一套任务框架。

## 架构边界

- 产品是 **网安领域的 Agent 平台地基**：用智能体或工作流组装多种安全场景。禁止做成跨行业 Bot 市场，也禁止收成只会自动封禁。封禁链是样板，不是唯一场景。
- Hermes / 执行器禁止 `import app.agent.decision` 的私有函数。工具构建走公共层（目标：`toolfactory` + `system_tools`）。
- 工具定义一次、多处绑定：只按 **id 或 name** 引用，禁止把工具代码复制进 Agent。不做工具 semver。
- 新设备 / 内网：声明式 HTTP + `/devices`。禁止把 MCP 或公网插件商店当内网接入前提。
- 并发禁止写进工具 `run()`。写工具保持 barrier；扩展只接到现有 `tool_dispatch`。
- 禁止为预留增加无人读的数据库空列。
- `variables` 只放提示词变量。发布状态只认 `publish_status` 列。
- **基座优先**：Hermes、工作流 DAG、告警入库、审批熔断、工具分发是所有场景的公共地基。新场景用工作室绑定或内置 Skill/工具组装。禁止为单个场景改执行器、加对话引擎、或在热路径堆逻辑。
- **性能与稳定**：禁止 FastAPI/Hermes 热路径同步长阻塞（长扫描进 Celery）。禁止在 `run()` 里自行 `gather`/限流（只接到 `tool_dispatch` / `limiter`）。禁止对话/列表无分页全表扫。写工具必须走 barrier / Guardrail。禁止默认研判 Agent 绑定 nmap/nuclei/sqlmap。预算、上下文截断、模型健康检查不得为场景关掉。
- 场景沉淀为内置 Skill / Tool：生成走「盘点 → 拆解 → 创建 → 固化」。禁止 fork Skill 代码，禁止绕过底座另起执行链。

## 安全红线

- 封禁、解封、改设备配置、通知轰炸等必须经 Guardrail / 审批 / 熔断。禁止 LLM 输出直接变成不可逆处置。
- 对话与封禁触发只能跑 `publish_status=published`。禁止草稿进生产。禁止再解析名称前缀或 `variables._publish_status`。
- 密钥禁止明文新写入库；禁止用 XOR 做新存储。
- 工具默认不可隐式访问公网。
- 禁止 `db.query(User).first()` 当工作流 / 系统执行身份。

## 代码契约

- 模块边界用 Pydantic，禁止新代码用裸 dict 当合同。
- 绑定工具只用 id/name 列表。
- 对外文案：简体中文。

## 禁止事项

- 禁止 `print` 做业务日志，使用 `logging`。
- 禁止提交密钥、`.env`、证书。禁止 `git push --force` 到 `main`/`master`。
- Workspace 为保存壳；Advanced 不得复制 `enabled_*` 写入逻辑。
- 禁止用浏览器 RPA 作为设备集成主路径。
- 生成工具代码必须遵守 `AI_CODING_RULES.md`：查重留痕、先 `test_tool_code`、权限校验、写操作不绕过护栏、合入前人工复核。
