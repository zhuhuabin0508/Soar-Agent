# 平台架构定稿：LLM 底座 + 模块化工具适配层（High-Level 定稿方案）

> 状态：**待评审定稿**。本文是"底座(LLM) 与 各业务/设备模块 高解耦、可按需本地或远程执行、可持续扩展"的落地架构总纲。
> 目标四条：**可扩展性 / 可用性 / 高解耦 / 可落地**。所有结论均基于现有代码，尽可能复用既有机制，少造新轮子。

---

## 一、核心思想（一句话）

**底座 = LLM 运行时 + 工具契约；业务/设备模块 = 只暴露"动作/查询"接口，不依赖底座；二者唯一的耦合点是"工具 Schema + 执行端点"。**

```
┌──────────────── 底座（Agent Runtime / Hermes 引擎）────────────────┐
│  LLM 配置 & 提示词装配 & ReAct 循环 & 护栏/校验/审计               │
│                     │ 通过『工具契约』下发                          │
└──────────▲──────────┴──────────────────────▲──────────────────────┘
           │                                  │
   ┌───────┴────────┐                 ┌───────┴────────────┐
   │  本地工具执行    │                 │  远程执行器（可选）   │
   │  in-process     │                 │  经 API / 消息队列  │
   └────────────────┘                 └────────────────────┘
              │ 统一契约(schema)      │
   ┌──────────▼──────────────────────▼──────────────────────┐
   │                       各业务 / 设备模块                    │
   │  设备(Device+Action)  资产  知识库  工作流  通知  威胁情报  │
   └──────────────────────────────────────────────────────────┘
```

关键点：**底座不认识"某台防火墙"，只认识"一个名叫 `device_block`、参数 schema 明确、终点是某个 URL 的工具"**。模块的真实调用者（本地函数、远程 HTTP、消息队列 Worker）被封装在工具契约背后。

---

## 二、分层与职责（定稿）

### 1）底座层（Agent Runtime）
职责：LLM 配置、system prompt、ReAct/Hermes 循环、工具绑定、护栏、写操作校验、预算、记忆、流式 SSE、审计。
- 唯一入口：`backend/app/agent/decision.py`（LangGraph 路线）与 `backend/app/agent/hermes/`（Hermes 引擎）。
- 底座**不 import** 任何业务/设备模块的实现（除工具目录注册表）。

### 2）工具契约层（核心解耦点）
底座与模块之间的**唯一稳定接口**。两种形态：
- **DB Tool（数据驱动）**：`Tool` 模型（`tool_type='http'|'code'`），`parameters_schema` 描述入参 → 运行时绑定。
- **工具注册表**：`backend/app/core/tools/catalog.py` + `ToolCatalog`。内置/框架/安全/用户自建，统一来源。
- Hermes 引擎每轮从 `ToolEntry`（name/description/schema/executor）构建可调用工具。

### 3）模块层（业务 / 设备）
对外只暴露：
- **HTTP 动作/查询**：`DeviceAction` 等声明式配置（method/path/params_schema/body_template/auth_type）。
- **webhook / 回调**：供反向触发（入站）。
- **只读查询**：资产、情报、知识库等。
模块内实现细节、状态、鉴权、日志全部内聚在模块内。

### 4）执行层（本地 vs 远程）
统一由工具契约承载，同一 schema 可对接不同执行器：
- **本地执行（默认）**：`run_http_tool`（`tool_http_runner.py`）在底座进程内发 HTTP；或 `code` 工具沙箱内运行。
- **远程执行（可选，高可用/隔离）**：把工具执行委托给独立 Worker / 独立微服务 / 消息队列（Celery 已有）。底座只发"工具调用指令"，等待结果。→ 天然支撑负载隔离、故障域隔离、横向扩容。

---

## 三、可扩展性设计

1. **新增一种能力 = 新增一种工具契约，不改底座**。
   - 新增设备类型：加一条 `Device` + 若干 `DeviceAction` 配置（`devices.py` CRUD 已有）。
   - 新增外部系统：OpenAPI 导入（`tools_manage.py:OpenAPIImportRequest`）一键生成 HTTP 工具。
   - 新增专属逻辑：`code` 工具（沙箱执行，`tool_runner.py`）。
2. **统一命名约定**：
   - 写操作前缀 `device_`/`send_`/`trigger_`（写 → 顺序 barrier + 证据校验）。
   - 读操作前缀 `query_`/`get_`/`list_`/`search_`（读 → 可并行，`tool_dispatch._PARALLEL_SAFE_PREFIXES` 已支持）。
3. **Schema 即文档即白名单**：`parameters_schema` 限制 LLM 能传的参数，天然防注入、限定边界。
4. **目录 + 种子**：`ToolCatalog` + `seed_service` 统一注册，新模块向目录注册即生效，前端自动可搜可用。

---

## 四、可用性设计（高可用 / 故障隔离）

1. **执行故障域隔离**：默认本地执行，风险动作/重活可切远程 Worker（Celery 已有队列），底座崩溃不影响已有模块、模块故障不拖垮 LLM 循环。
2. **超时/重试/熔断**：
   - 每个工具有 `timeout`/`retry`（`tool_http_runner` 已内置 5xx 重试）。
   - 建议在工具执行器外层加**超时护栏 + 可选熔断（连续失败 N 次临时禁用该工具）**，避免单个模块拖慢 Agent。
3. **设备健康门控**：只把 `Device.status='online'` 且 `action.enabled=True` 的动作物化成工具，LLM 不会去调离线设备（`Device.status/last_heartbeat` 字段已就绪）。
4. **降级策略**：
   - LLM 配置缺失 → 回退规则化 Mock（`decision.py` 已有）。
   - 工具执行失败 → 返回结构化错误给 LLM，由 LLM 重试或改策略；写工具失败可走人工审批节点。
5. **幂等与审计**：所有写操作落 `DeviceCallLog`（已含 agent_id/user_id/source_ip），可重放、可追溯。

---

## 五、高解耦具体措施

| 维度 | 底座（LLM） | 业务/设备模块 |
|------|------------|--------------|
| 依赖方向 | 只依赖工具契约（schema） | 只暴露契约，不依赖底座引擎 |
| 代码引用 | 不 import 模块实现 | 不 import 底座内核（可复用核心工具如 httpx runner） |
| 数据 | 只读工具描述与调用结果 | 自持状态/配置/日志 |
| 运行 | 调度/编排 | 执行/被调 |
| 接入 | 声明（注册表 + schema） | 发布（暴露接口 + 契约声明） |

**边界唯一入口**：`ToolCatalog` 注册 + `run_http_tool`/沙箱执行器。只要这两个稳定，两端可独立演进、独立部署、独立扩容。

---

## 六、可落地的实施路线（里程碑）

- **M0（现状确认，已完成）**：底座工具系统 + 设备模块均已存在，方向与本文一致。
- **M1（打通最小闭环）**：新增 `backend/app/devices/as_tool.py`，把在线设备的启用动作物化为 HTTP 工具；在 `tool_engine._register_db_tools`（Hermes）与 `decision._build_db_tools`（LangGraph）注册。→ 设备动作可被 LLM 调用。
- **M2（配置联动）**：`Agent` 增加 `enabled_devices`（JSON），联动"勾设备/勾动作 → 绑定工具"，前端可配。
- **M3（可用性加固）**：执行器外层超时护栏 + 熔断；写工具默认走 `verification`（复用 `_verify_device_action`）；补 `DeviceCallLog` 全链路。
- **M4（远程执行，可选演进）**：抽象"执行器后端"接口（本地 httpx / Celery Worker / 独立微服务），同一 schema 可切换，实现底座与模块的物理隔离与水平扩容。

---

## 七、待定项（需你拍板）

1. **执行形态**：M4 是否要做"远程独立服务"？还是先用"本地执行 + 必要时切 Celery Worker"？（决定高可用投入）
2. **设备动作绑定粒度**：按"动作级"（每个 DeviceAction 一个工具，推荐）还是"桥工具 device_action"（单入口）？
3. **是否继续补 Hermes 已预留的 `device_action` 写校验**：建议接上 `verification._verify_device_action`，否则写设备动作无证据链。
4. **命名与权限**：设备工具命名（`device_{id}_{type}`）与"管理设备动作"的权限策略（建议 `device:use` / `device:manage`）。

---

## 附：关键文件索引
- 底座：`backend/app/agent/hermes/`、`backend/app/agent/decision.py`
- 契约：`backend/app/models/tool.py`、`backend/app/core/tool_http_runner.py`、`backend/app/core/tool_runner.py`、`backend/app/core/tools/catalog.py`
- 设备：`backend/app/models/device.py`、`backend/app/devices/action_executor.py`、`backend/app/api/v1/devices.py`
- 编排/校验：`backend/app/agent/hermes/verification.py`、`tool_dispatch.py`、`backend/app/core/node_executors.py`
