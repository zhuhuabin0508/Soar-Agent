# SOAR 架构方案

> **LLM 为底座 + 模块工具化**  
> 路径：`docs/architecture/soar架构方案.md`（方案文档目录，见同目录 `README.md`）  
> 状态：**架构定稿 v2.0**（2026-09-24）  
> 评审：**Cursor / Codex / 项目组架构方向已统一**；无未决路线分歧。  
> 定位：SOAR 平台**最终架构原则与模块边界**；执行节奏与任务勾选仍以 `@docs/architecture/SOAR Agent 平台基座优化方案.md` §13.2、`@docs/architecture/LangGraph → Hermes 统一.md`、`@docs/architecture/LangGraph → Hermes 实施进度.md` 为准。  
> 待补充细节与开工任务：**[待办与开工清单.md](./待办与开工清单.md)**（不阻塞本文定稿）。  
> 关联文档：  
>
> - `@docs/architecture/SOAR Agent 平台基座优化方案.md` §13.2（MVP 执行清单）  
> - `@docs/architecture/LangGraph → Hermes 统一.md`（Agent 运行时契约与收口步骤）  
> - `@docs/architecture/LangGraph → Hermes 实施进度.md`（Agent 收口进度跟踪）  
> - `@docs/architecture/module-responsibilities-and-relations.md`（五模块职责与已知问题）  
> - `@docs/architecture/device-integration-architecture.md`（设备对接松耦合专项，已吸收并见 §6.7 反驳说明）

---



## 1. 摘要

本方案定义 SOAR 平台的总体架构原则：**以 Hermes + LLM 为编排中枢，各业务模块以「工具」形式向平台暴露能力，由 LLM 根据上下文串联调用；模块实现内聚，模块之间不直接耦合。**


| 维度       | 定调                                                                      |
| -------- | ----------------------------------------------------------------------- |
| 编排中枢     | Hermes ReAct 循环（`invoke_agent` 统一入口）                                    |
| 模块接入     | 只暴露工具契约（name + schema + execute），禁止横向 import                            |
| 工具串联     | **由 LLM + 平台中介**：工具 A 执行后将结果交回 LLM，再由 LLM 决定是否调工具 B                     |
| 设备对接     | 动作目录 + DeviceGateway；**动作级投影为主 +** `device_action` **门面兜底**（见 §6）       |
| 自动化      | 固定 SOP 走工作流节点；需语义判断的链路由 LLM 多轮调工具                                       |
| 与 MVP 关系 | **必须先完成** `@docs/architecture/SOAR Agent 平台基座优化方案.md` §13.2，再阶段 1 设备工具化 |
| 工具统一管理   | **单注册表 +** `tool_source` **分类**；内置/设备/外部一并装配，**不用 MCP**（见附录 B、§5.5）     |


**一句话**：SOAR 以 LLM 为底座，各模块统一工具化注册；平台统一执行、治理与审计；改场景加工具/加配置，不改引擎。

**定稿结论**：架构方向与代码现状、基座 §13.2 一致，**可作为设计与评审依据**。历史修订痕迹见 §6.7；评审结案见 §20；**尚未细化的实施细节**见 [待办与开工清单.md](./待办与开工清单.md)。

### 1.1 文档分工


| 文档                                                      | 作用                                | 何时改           |
| ------------------------------------------------------- | --------------------------------- | ------------- |
| **本文**                                                  | 总体架构、模块边界、设备工具化、扩展原则              | 架构方向或模块契约变更时  |
| [待办与开工清单.md](./待办与开工清单.md)                              | 可迭代细节、分阶段开工任务与状态勾选                | 实施前拍板、开工、勾进度时 |
| `@docs/architecture/LangGraph → Hermes 统一.md`           | Agent 运行时技术契约、收口 Step、output_mode | 运行时契约变更时（走评审） |
| `@docs/architecture/LangGraph → Hermes 实施进度.md`         | Agent 收口任务勾选与证据                   | 每完成一项收口任务     |
| `@docs/architecture/SOAR Agent 平台基座优化方案.md` §13.2       | 本季度 MVP 唯一执行清单                    | 产品/基座范围变更时    |
| `@docs/architecture/device-integration-architecture.md` | 设备对接代码落点与 HTTP 工具路线补充             | 设备模块实施细节变更时   |


**有冲突时**：Agent 运行时技术细节 → 以 `@docs/architecture/LangGraph → Hermes 统一.md` 为准；本季度做不做某项 → 以 §13.2 为准；模块边界与工具化原则 → 以本文为准；设备暴露形态细节 → 以本文 §6 为准（已吸收专项文档并标明反驳项）。

---



## 2. 背景与目标



### 2.1 背景

SOAR 平台当前已具备：

- Hermes Agent 引擎（护栏、验证、委派、预算、tool_search 等）
- 工具多源（builtin / code / http / framework）与 `ToolCatalog`
- 设备管理（`Device` / `DeviceAction` / `DeviceCallLog`）与 `action_executor`
- 工作流三路径（封禁专用 / Celery 通用 / test-run）
- `invoke_agent` 门面（`app/platform/agent_runtime.py`，收口进行中）
- 告警接入与封禁触发（`ingest`、`alerts`、`ban_workflow`）

`@docs/architecture/device-integration-architecture.md` 指出：底座与设备数据模型已具备约九成能力，**关键缺口是** `device_action` **在 Hermes 护栏/校验/调度中已预留名称，但 ToolCatalog / tool_engine 未注册执行体**。本文采纳该判断，并明确：**缺口在「接线」而非「再造框架」**。

待统一的问题：

- 运行时分裂（LangGraph legacy、三路径行为不一致）
- 工具注册与执行多入口
- 设备执行路径重复（`action_executor` vs `node_executors` 内联 httpx）
- Agent 封禁工具与真实设备 API 未对齐（Mock firewall vs `DeviceAction`）
- 部分能力双轨挂载（如 `search_assets`）、tool_search 可能隐藏关键工具（见 §17）



### 2.2 目标


| 目标      | 说明                                       |
| ------- | ---------------------------------------- |
| **高解耦** | Hermes / API 不 import 厂商 SDK；模块只通过工具契约对外 |
| **可扩展** | 新厂商、新动作 = 注册工具或导入动作目录，不发版引擎              |
| **可用**  | 对话、工作流、手动 API 共用同一执行能力与审计                |
| **可落地** | 分阶段实施，与 §13.2 MVP 不冲突                    |




### 2.3 非目标（本方案不做）

- 不替换 Hermes，不新增第三条 Agent 运行时
- 本季度不做 PluginLoader、WorkflowSpec 包、物理删除 LangGraph
- 不做 K8s / Temporal / OTel 全量接入（关联键可先落，见 §6.5）
- 不在用户 code 工具内实现「工具 A 直接调用工具 B」旁路（见 §3.4）
- 阶段 1 **不做**独立设备对接 HTTP 微服务（见 §6.7 反驳）

---



## 3. 架构总览



### 3.1 分层模型（统一编号：L1 实现 → L5 交付）

自下而上五层，全文仅此一套编号。**编排中枢（LLM）** 位于 L2 之上、驱动 L2，不单独占用 L1～L5 编号，避免与 v1.1 §3.1 / §8 编号冲突（v1.1 评审 P0-1，已修正）。

```
  ┌─────────────────────────────────────────────────────────────┐
  │  编排中枢（LLM / Hermes ReAct）  — 驱动下层，非独立「L0」     │
  └────────────────────────────┬────────────────────────────────┘
                               │
  ┌────────────────────────────▼────────────────────────────────┐
  │  L2  平台运行时                                              │
  │  invoke_agent · invoke_tool（规划）· tool_engine · 治理链    │
  └────────────────────────────┬────────────────────────────────┘
                               │ 仅通过工具契约向上暴露
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
    [设备模块]            [安全/资产/KB]         [工作流/通知]
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  L1  模块实现（不对 LLM 暴露：executor / gateway / runner）   │
  └─────────────────────────────────────────────────────────────┘

  L3 注册层 — ToolCatalog → ToolRegistryBuilder
  L4 声明层 — Tool 表、DeviceAction、Agent ORM、Workflow JSON、Skill
  L5 交付层 — UI、模板、导入导出（只写 L4，执行必须经 L2）
```

**读图要点**：业务「模块」通过 L2 注册为工具；L1 是实现；L3～L5 是注册、声明、交付，与运行时正交。

### 3.2 六条架构规则

1. **LLM 只通过工具认识世界**——不直接访问 DB、HTTP、厂商 API。
2. **模块只向上暴露工具契约**，模块间禁止横向 import 实现代码。
3. **工具串联由 LLM 中介**；固定 SOP 用工作流节点。
4. **三种消费入口、一套 L1 实现**：对话、工作流、管理 API 共用 DeviceGateway 等执行缝。
5. **技能只改 prompt，不产生动作**。
6. **研判与执行分离**：研判 Agent 只读；写操作由工作流节点或处置类工具完成。



### 3.3 与五模块的关系

见 `@docs/architecture/module-responsibilities-and-relations.md`。编排层：Agent、Workflow；能力层：Tool；内容层：Skill、Knowledge Base。

### 3.4 LLM 编排 vs 工具内互调


| 模式                                | 本架构态度         |
| --------------------------------- | ------------- |
| LLM 中介（A → LLM → B）               | **默认**（对话、研判） |
| 工作流编排                             | **固定 SOP**    |
| L1 服务复用（工具内调 `context_tools` 等函数） | **允许**        |
| Agent 层工具 A 直调平台工具 B              | **禁止**        |


---



## 4. 统一调用模型



### 4.1 对话场景

```
用户 / 告警 → invoke_agent → Hermes 选工具 → tool_engine → L1 → 结果回 LLM
```

入口：`POST /agents/{id}/chat`、`POST /agents/{id}/test/stream`（`app/platform/agent_runtime.py`）。

### 4.2 工作流三路径


| 路径         | 入口                                    | 契约                 | 目标态            |
| ---------- | ------------------------------------- | ------------------ | -------------- |
| A 封禁专用     | `workflow/engine.py` → `agent_client` | `ban_risk_analyze` | `invoke_agent` |
| B Celery   | `workflow_tasks._execute_node`        | `soc_decision`     | `invoke_agent` |
| C test-run | `workflow_runner` → `node_executors`  | Hermes             | 已部分支持          |


封禁触发规则（`/ban-workflow/rules`）与通用工作流是两套体系，见 `@docs/architecture/module-responsibilities-and-relations.md`。

### 4.3 管理 API

`banned_ips`、`devices` 测试接口 → L1 / DeviceGateway → DeviceCallLog。

### 4.4 告警 → 封禁端到端（参考纵切 / 暂时 MVP 验收绳）

> **定位**：非产品唯一场景，而是**验证 Agent 底座最起码可用**的端到端样例（项目组 **D-1 已定**，2026-09-24）。跑通即说明 `invoke_agent`、研判/执行分离、工作流与审计主线可用；后续可增多场景 E2E 与自动化搭建测试，不替代本条暂时标准。

```
ingest → alerts → ban_workflow → 路径 A 研判(ban_risk_analyze)
  → condition_branch → block_ip / device_action 节点
  → DeviceGateway → 厂商 API → banned_ips + DeviceCallLog
```

| 阶段 | 本链验收范围 |
|------|----------------|
| 阶段 0 | 研判走真 Hermes Agent（非长期 mock）；工作流分支与 `ban_risk_analyze` 字段完整 |
| 阶段 1 | 写节点 / 手动封禁 / Agent 处置工具共走 DeviceGateway |

---



## 5. 模块工具化映射



### 5.1 对照表


| 模块   | 对 LLM 暴露的工具                                                                                                    | L1 实现                             |
| ---- | -------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| 安全研判 | `get_threat_intel`、`check_whitelist`、`check_subnet`                                                            | `app/tools/context_tools.py`      |
| 资产   | `search_assets`（`enabled_asset_types` 驱动）                                                                      | `decision._build_asset_tool`      |
| 知识库  | `search_knowledge_base`、`query_kb_file`                                                                        | `kb_retriever`                    |
| 设备   | 语义 `block_ip`；投影 `device_{device_id}_{action_id}`；枚举 `list_devices` / `list_device_actions`；兜底 `device_action` | `DeviceGateway`、`action_executor` |
| 封禁   | 研判只读；执行走节点/工具                                                                                                  | `api/v1/banned_ips.py`            |
| 工作流  | `trigger_workflow_skill`、`workflow_{id}_*`                                                                     | `workflow_as_tool`                |
| 框架   | `delegate_task`、`clarify`、`tool_search` 等                                                                      | `hermes/`                         |




### 5.2 工具类型


| tool_type   | 执行器                | 设备相关用法                          |
| ----------- | ------------------ | ------------------------------- |
| `code`      | `tool_runner`      | 投影工具可注册为 code，内部调 DeviceGateway |
| `http`      | `tool_http_runner` | 独立对接服务代理（阶段 3+）                 |
| `framework` | Hermes executor    | `tool_search` 桥接                |


`ToolCatalog` 注释与 `@docs/architecture/device-integration-architecture.md` 一致：对外集成走 REST + HTTP 工具；MCP 暂不实施。

### 5.3 Agent 装配

`enabled_tools`、`enabled_kbs`、`enabled_asset_types`、`enabled_workflows`、`tool_configs`（含 tool_search、verification）。研判 Agent 建议 `tool_search=off` 或 `auto`。

### 5.4 新模块接入契约

工具名 + schema + execute + 元数据（`tool_source`、`risk_level`、`parallel_safe`）；不 export SDK。

### 5.5 工具统一管理（内置 / 设备 / 外部是否一块管）

**结论**：运行时**一块装配**（同一 `tool_engine` → 同一治理链）；元数据**分** `tool_source` **管理**；**不引入 MCP** 作为主方案。


| 来源                 | 是否进 `Tool` 表                                      | Agent 配置字段                                        | 装配方式                                              |
| ------------------ | ------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------- |
| builtin / security | 是（seed）                                           | `enabled_tools`                                   | `_register_db_tools`                              |
| framework          | 种子定义存在，**运行时由 Hermes executor 注入/拦截**，非普通 DB 执行路径 | 引擎自动附加                                            | executor + `tool_engine` 跳过 `tool_type=framework` |
| 用户 code / http     | 是                                                 | `enabled_tools`                                   | `_register_db_tools`                              |
| 知识库 / 资产           | 否（动态）                                             | `enabled_kbs` / `enabled_asset_types`             | `_register_kb_tools` / `_register_asset_tools`    |
| 工作流包装              | 否（动态）                                             | `enabled_workflows`                               | `_register_workflow_tools`                        |
| 设备投影（规划）           | **可不落表**（运行时物化）                                   | `enabled_devices`**（推荐新增）** 或 `enabled_tools` 白名单 | `_register_device_tools`                          |


统一管理不靠 MCP，靠：**阶段 2** `ToolRegistryBuilder` **+** `invoke_tool` 收敛上述 Provider；阶段 1 设备接线可先在 `tool_engine` 落地，视为过渡。细则见 **附录 B**。

**推荐**：Agent ORM 新增 `enabled_devices: list[int]`（设备 id 列表），UI「勾选设备」比让用户记投影工具名更清晰；投影工具名由平台生成，**主键用** `action_id` **防冲突**（§6.8）。

### 5.6 `Tool.tool_source` 与 `ToolEntry.source`（避免实施混淆）

ORM 字段 `Tool.tool_source`（`types.py`）与运行时 `ToolEntry.source`（`tool_engine.py`）**不是同一枚举**，实施时不要混填。


| `Tool.tool_source`（持久化） | 典型 `ToolEntry.source`（运行时） | 说明                                    |
| ----------------------- | -------------------------- | ------------------------------------- |
| `builtin`               | `builtin` / `db_code`      | seed 的 code 工具在 engine 里常标为 `db_code` |
| `security`              | `db_code`                  | 安全扫描类                                 |
| `framework`             | 不进 registry 执行管线           | 由 executor `extra_tool_defs` 注入       |
| `custom`                | `db_code` / `db_http`      | 用户自建                                  |
| `device`（阶段 1 增）        | `device`                   | 投影物化，建议两边同名                           |


阶段 2 `ToolRegistryBuilder` 应输出统一元数据对象，消除双枚举漂移。

---



## 6. 设备对接模块



### 6.1 定位

设备模块维护动作目录与下发；对 Agent 只暴露工具。管理 API：`/api/v1/devices`。实现：`backend/app/devices/`、`backend/app/models/device.py`。

### 6.2 动作目录

`DeviceAction` 字段：`action_type`、`http_method`、`api_path`、`params_schema`、`body_template`、`risk_level`、`category`。登记：UI、模板（`core/device_templates.py`）、`POST /devices/import`。

### 6.3 DeviceGateway（统一执行缝）

```text
DeviceGateway.invoke(
  db, device_id, action_id | action_type, params,
  ctx: { source, user_id, agent_id, workflow_id, correlation_id, idempotency_key }
) -> { success, status_code, response_body, error }
```


| source        | 含义           |
| ------------- | ------------ |
| `manual_test` | 设备页测试        |
| `workflow`    | 工作流节点        |
| `agent`       | Hermes 工具调用  |
| `api`         | banned_ips 等 |


**现状**：`action_executor.py` 已有 HTTP 逻辑；`node_executors.execute_device_action` 仍内联 httpx，阶段 1 必须收敛。

### 6.4 设备工具暴露策略（v1.4 定稿）

采纳评审结论 **C：动作级投影为主 + 门面兜底**，并吸收 `@docs/architecture/device-integration-architecture.md` 方案 A/B，但**不采纳「完全绕过 Gateway 走 run_http_tool」**（见 §6.7）。


| 层级       | 形态                 | 说明                                                                                                                                   |
| -------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| **主路径**  | 动作级投影              | 每个启用的 `DeviceAction` → 工具名 `device_{device_id}_{action_id}`（稳定唯一），`parameters_schema` 来自 `params_schema`；描述中带 `action_type` 供 LLM 理解 |
| **发现**   | 只读枚举               | `list_devices`、`list_device_actions(device_id?)`；仅暴露 `enabled=True` 且设备 `status=online` 的项                                           |
| **兜底**   | 门面 `device_action` | `device_id` + `action_type` + `params`；供工作流胶水、未投影动作、运维单条下发                                                                           |
| **短期验证** | 手工 HTTP 工具         | `@docs/architecture/device-integration-architecture.md` 方案 C：零代码验证 API，**不与 Device 配置联动，仅 PoC**                                      |


**投影注册**：新增 `backend/app/devices/as_tool.py`（名称可调整），由 `tool_engine._register_device_tools()` 加载。

**Agent 绑定（v1.3 定稿）**：优先在 `models/agent.py` 增加 `enabled_devices`（JSON，设备 id 列表）；勾选设备后装配该设备下所有启用且在线的动作投影 + 枚举工具。`enabled_tools` 仅用于显式追加单个投影名或门面 `device_action`，不作为主配置入口。

**写工具治理键（阶段 1 必改）**：`verification.py`、`tool_dispatch.py`、`tool_result_classification.py` 当前按工具名 `device_action` 硬编码。引入投影后须改为：

- `tool_source == "device"` 或工具名前缀 `device_` → 写工具 barrier + verification；
- `risk_level == high_risk` 或 `category in (block, dispose)` → 加强校验；
- 保留对工具名 `device_action` 的兼容。



### 6.5 幂等与关联键

采纳评审 P1-2，**反驳**「阶段 1 必须上全链路 trace_id」：

- **阶段 1**：`DeviceGateway` 支持 `idempotency_key`（建议 `hash(source, agent_id, workflow_id, device_id, action_type, 业务主键如 ip)`）；重复请求返回已有 `DeviceCallLog` 结果，避免重复封禁。
- **阶段 2**：`DeviceCallLog.correlation_id` 关联 `agent_invocation_logs`；全量 OTel 仍为演进项（与 `@docs/architecture/SOAR Agent 平台基座优化方案.md` §13.2 一致）。



### 6.6 研判与执行分离

研判 Agent：只读工具；输出 `ban_risk_analyze`（字段同 `agent_client.REQUIRED_FIELDS`）。执行：工作流节点或处置 Agent 的投影/门面工具。**禁止**路径 A 使用 `soc_decision`。

生产封禁主路径（路径 A）的写操作**默认由工作流节点**（`block_ip` / `device_action`）完成；对话场景的处置 Agent 才通过工具下发。

### 6.7 历史表述与修订痕迹（保留，勿删）

> **编辑原则**：下文保留 v1.0～v1.3 中被评审推翻或事后修正的表述，供对照「我们曾错在哪里」。**现行定稿以 §6.4、§6.8 及 §20 为准**；引用 §6.7 处表示「见本节历史与反驳上下文」。


| #    | 历史表述（已废弃或部分废弃）                                             | 问题                                   | v1.4+ 定稿                                                       |
| ---- | ---------------------------------------------------------- | ------------------------------------ | -------------------------------------------------------------- |
| H-1  | 投影工具名 `device_{device_id}_{action_type}`                   | 同设备同 `action_type` 多动作冲突             | `device_{device_id}_{action_id}`（§6.4）                         |
| H-2  | 附录 B 开篇「内置/设备/外部工具同一张 `Tool` 登记表」                          | 与 §5.5「持久化表 + 运行时物化」矛盾               | 附录 B 已改首段；KB/资产/设备投影**可不落表**                                   |
| H-3  | 分层图「L0 = 编排中枢」                                             | 与 §8「L1～L5」编号冲突（评审 P0-1）             | **编排中枢不占用 L1～L5 编号**（§3.1）                                     |
| H-4  | 将 builtin 种子 `block_ip_on_firewall` **改名为** `block_ip`     | 破坏历史 seed / `enabled_tools` 引用       | **新增语义** `block_ip`，`block_ip_on_firewall` 转发/deprecated（§6.8） |
| H-5  | Agent 设备绑定主要靠 `enabled_tools` 勾选投影名                        | 用户难记 `device_12_block_ip_xxx`        | `enabled_devices`**（设备 id 列表）** 为主入口（§5.5、§6.4）                |
| H-6  | DeviceAction 物化为 `tool_type=http` 后走 `run_http_tool`，「零胶水」 | 绕过 DeviceGateway，审计与 `banned_ips` 分裂 | **物化 schema/注册，执行一律 Gateway**（§6.9）                            |
| H-7  | 阶段 1 投影**全部** DeviceAction                                 | 工具爆炸，拖垮 tool_search                  | **高频写动作 + 全量只读**；其余 `list_device_actions` + 门面（§6.9）           |
| H-8  | 阶段 1 硬门槛「全链路 OpenTelemetry trace_id」                       | 代码无统一 trace 注入点                      | 阶段 1 `idempotency_key`；阶段 2 `correlation_id`（§6.5）             |
| H-9  | 设备接线与 Hermes 收口**可并行**                                     | 双运行时与契约漂移加剧                          | **阶段 0 门禁**，未完成不得启动阶段 1（§13）                                   |
| H-10 | 阶段 1 建设独立设备 HTTP 微服务                                       | 范围过大，与本地 Gateway 重复                  | **阶段 3** 再评估（§2.3、§6.9）                                        |


**曾写错、现已修正的句子示例**（保留原文痕迹）：

- ~~「每个 DeviceAction 投影为~~ `device_{device_id}_{action_type}`~~」~~ → 见 §6.4 `action_id` 主键。
- ~~「所有工具（含 KB、设备）统一写入 Tool 表一张登记表」~~ → 见 §5.5 / 附录 B.2「持久化 + 物化并存」。
- ~~「Hermes 与设备接线可同周并行」~~ → 反驳，见 §13 阶段 0 门禁。



### 6.8 语义工具 vs 技术工具（v1.4 增补，优化 LLM 体验）

设备对接不要只暴露「技术投影」，应分两层，避免 LLM 必须理解 `device_id`：


| 层级      | 工具                                               | 谁用               | 行为                                                               |
| ------- | ------------------------------------------------ | ---------------- | ---------------------------------------------------------------- |
| **语义层** | `block_ip(ip, duration, reason)`                 | 处置 Agent、研判后对话封禁 | 名称与 Hermes 治理链一致；内部按 **Agent/系统默认设备** 解析 `block_ip` 动作并调 Gateway |
| **技术层** | `device_{device_id}_{action_id}`、`device_action` | 多设备、多厂商、精确下发     | 显式设备与动作                                                          |


**默认设备解析（阶段 1 建议，优于让 LLM 猜 id）**：

1. `Agent.variables.default_device_id` 或处置 Agent 专用配置；
2. 若无，按设备 `tags`（如 `封禁`、`production`）+ `action_type=block_ip` 匹配唯一在线设备；
3. 仍无法解析 → 返回结构化错误，提示先 `list_devices` 或配置默认设备（**不静默失败**）。

**与** `block_ip_on_firewall` **的关系（v1.4 定稿，优于改名）**：

- **保留** builtin 种子名 `block_ip_on_firewall` 兼容历史数据；
- **新增** 语义工具 `block_ip`（Hermes 已按此名做 verification/barrier），实现为 Gateway 薄封装；
- `block_ip_on_firewall` 可标记 deprecated，内部转发 `block_ip` 或 Gateway，避免双实现。

工作流 `block_ip` **节点**不走 LLM tool_call，应直接调 Gateway（与 Agent 工具共用 L1，不是第三套逻辑）。

### 6.9 对外部专项文档的采纳与反驳

对照 `@docs/architecture/device-integration-architecture.md`：


| 专项文档观点                                                   | 本文态度                                                                                                                                                                                          |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 底座已具备约 90%，缺的是接线                                         | **采纳**                                                                                                                                                                                        |
| `device_action` 已预留但未注册                                  | **采纳**，阶段 1 必做                                                                                                                                                                                |
| 方案 A：DeviceAction 物化为 `tool_type=http`，走 `run_http_tool` | **部分采纳，部分反驳**：物化的是**工具 schema 与注册**，**执行仍必须经 DeviceGateway**，不得绕过。理由：鉴权在 `Device` 表、`DeviceCallLog.source` 审计、`banned_ips` 与 Agent 路径需同一执行缝；若每动作独立 `http_config` 且不复用 Gateway，会再现「三处 httpx」分裂 |
| 方案 B：桥工具 `device_action`                                 | **采纳**为兜底，非主路径                                                                                                                                                                                |
| 方案 C：手工建 HTTP 工具                                         | **采纳**仅作 PoC，非主线                                                                                                                                                                              |
| 推荐 A+B 组合                                                | **采纳**为「投影（A 的注册面）+ 门面（B）+ Gateway 执行」                                                                                                                                                        |
| 设备模块不 import 底座、底座不 import 设备实现                          | **采纳**；衔接点为 ToolEntry schema 与 Gateway 协议，非 Python 交叉 import                                                                                                                                  |



| 评审意见                                      | 本文态度                                                                                     |
| ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| P0-1 分层编号矛盾                               | **采纳**，v1.2 已统一                                                                          |
| P0-2 门面不足以支撑 LLM，投影应为主路径                  | **采纳**                                                                                   |
| P1-1 缺 list_devices / list_device_actions | **采纳**，阶段 1                                                                              |
| P1-2 幂等 idempotency_key                   | **采纳**，阶段 1                                                                              |
| P1-3 治理钩子需泛化                              | **采纳**，阶段 1 与投影同步                                                                        |
| P2-2 trace_id 无落点                         | **部分采纳**：correlation_id 阶段 2；**反驳** trace_id 作为阶段 1 硬门槛                                  |
| 「阶段 1 必须投影全部动作」                           | **反驳**：动作量大时，**先投影高频写动作 + 全部只读动作**；其余经 `list_device_actions` + 门面兜底；避免工具爆炸拖垮 tool_search |
| 「远程独立服务阶段 1 不做」                           | **采纳**（与 A.4 一致）                                                                         |


---



## 7. 平台运行时



### 7.1 双入口


| 入口             | 调用方                              | 现状                            |
| -------------- | -------------------------------- | ----------------------------- |
| `invoke_agent` | `/chat`、研判、Playground            | 已建；内部经 Hermes + `tool_engine` |
| `invoke_tool`  | 工作流节点（目标态）、管理 API、脚本/Celery 直调工具 | 规划，基座第二波                      |


```
invoke_agent → HermesAgentExecutor → tool_engine → Provider → L1
invoke_tool  → ToolRegistryBuilder → 同一治理链 → Provider → L1
```

阶段 2 之前：工作流写节点直调 L1/Gateway；Agent 对话经 `invoke_agent`。**禁止**第三条工具执行路径。

**边界（阶段 2 定稿）**：


| 入口             | 调用方                                  | 阶段   |
| -------------- | ------------------------------------ | ---- |
| `invoke_agent` | `/chat`、`/test/stream`、研判、Playground | 现已可用 |
| `invoke_tool`  | 工作流写节点、管理 API、Celery/脚本直调工具          | 阶段 2 |


二者共用 `ToolRegistryBuilder` 产出的注册表与治理链；**对话场景不得绕过** `invoke_agent` **直调** `tool_engine`。

### 7.2 output_mode（不可混用）


| 模式                 | 下游                      |
| ------------------ | ----------------------- |
| `chat`             | `/chat`、SSE             |
| `soc_decision`     | Celery、condition_branch |
| `ban_risk_analyze` | 封禁路径 A                  |


契约细节：`@docs/architecture/LangGraph → Hermes 统一.md`。

### 7.3 治理链

`tool_dispatch`、`verification`、`guardrails`、`threat_scanner`、`middleware`、`tool_result_classification`、`DeviceCallLog`。写工具须 barrier；设备类写工具判定规则见 §6.4。

---



## 8. 五层解耦模型（与 §3.1 一致）


| 层   | 名称  | 内容                                     |
| --- | --- | -------------------------------------- |
| L1  | 实现层 | executor、runner、DeviceGateway          |
| L2  | 运行时 | invoke_agent、invoke_tool、tool_engine   |
| L3  | 注册层 | ToolCatalog、ToolRegistryBuilder        |
| L4  | 声明层 | Tool、DeviceAction、Agent、Workflow、Skill |
| L5  | 交付层 | UI、模板、导入导出                             |


编码约束：Hermes 不 import 设备 SDK；新工具不双写 `agent_tools.py` 与 `builtin.py`；Celery 不整函数替换 `_execute_node`（`@docs/architecture/LangGraph → Hermes 统一.md`）。

---



## 9. 代码目录映射


| 区域       | 路径                                                               |
| -------- | ---------------------------------------------------------------- |
| Agent 门面 | `backend/app/platform/agent_runtime.py`                          |
| Hermes   | `backend/app/agent/hermes/`                                      |
| 工具       | `backend/app/core/tools/`、`tool_runner.py`、`tool_http_runner.py` |
| 设备       | `backend/app/devices/`、`api/v1/devices.py`                       |
| 工作流      | `backend/app/workflow/`、`core/node_executors.py`                 |
| 封禁客户端    | `backend/app/workflow/agent_client.py`                           |


设备专项索引见 `@docs/architecture/device-integration-architecture.md` 附录。

---



## 10. 可扩展性

新厂商：模板/导入 DeviceAction。新动作：DB + 投影注册。新场景：新 Agent 配置。固定 SOP：工作流。外部服务：HTTP 工具（阶段 3+）。插件包：演进项。

---



## 11. 可用性设计


| 场景   | 入口                 |
| ---- | ------------------ |
| 对话研判 | `/chat`、Playground |
| 自动封禁 | 触发规则 → 路径 A        |
| 手动封禁 | 已封禁 IP 页           |
| 设备运维 | 设备管理、调用日志          |


**设备工具可用性（v1.2 增补）**：

- 仅 `Device.enabled=True` 且 `status=online` 的动作参与投影与枚举
- 设备配置变更后，Agent 侧工具目录**按会话/装配时重建**（与 `tool_search` 无状态目录原则一致，见 `hermes/tool_search.py` 注释）
- 单设备离线不阻塞其他设备工具（故障域隔离）
- LLM 先 `list_device_actions` 再调投影工具，**禁止在技能中硬编码 device_id**（仅工作流节点可写死 device_id）

内网：`LLMConfig` 先就绪；生产封禁不依赖 `/internal` mock。

---



## 12. 现状差距


| 优先级 | 项                                                    | 目标                                                      |
| --- | ---------------------------------------------------- | ------------------------------------------------------- |
| P0  | invoke_agent 收口                                      | §13.2 + `@docs/architecture/LangGraph → Hermes 实施进度.md` |
| P0  | 封禁路径 A E2E                                           | `BAN_ANALYST_AGENT_ID` + 真研判                            |
| P1  | DeviceGateway + 投影 + 枚举 + 门面                         | §13 阶段 1                                                |
| P1  | 治理键泛化（device_ 前缀 / tool_source）                      | 与投影同步                                                   |
| P1  | idempotency_key                                      | DeviceGateway                                           |
| P1  | invoke_tool                                          | 第二波                                                     |
| P2  | correlation_id、动作全量投影                                | 按需                                                      |
| P1  | 语义 `block_ip` + Gateway；`block_ip_on_firewall` 转发/废弃 | §6.8，优于强行改名种子                                           |
| P1  | `types.py` 增加 `device` source                        | 附录 B.5                                                  |
| P2  | `search_assets` 单轨                                   | §17                                                     |


---



## 13. 分阶段实施计划（摘要）


| 阶段    | 目标                                                     | 人周（估） | 门禁              |
| ----- | ------------------------------------------------------ | ----- | --------------- |
| **0** | Hermes 收口、`invoke_agent` 单门面                           | 2～3   | 无（起点）           |
| **1** | DeviceGateway + 设备工具投影/门面 + 语义 `block_ip`              | 1～2   | **阶段 0 验收通过**   |
| **2** | `invoke_tool` + `ToolRegistryBuilder` + correlation_id | 2～4   | 阶段 1 封禁 E2E 可演示 |
| **3** | 外部 HTTP 服务、全量投影、ToolProviderManifest                   | 按需    | 阶段 2 工具工厂唯一     |


**阶段 0 不得与阶段 1 并行**（反驳 H-9，§6.7）。分阶段执行清单不在本文展开，见基座 §13.2 与 `@docs/architecture/LangGraph → Hermes 实施进度.md`。

**暂时 MVP 验收绳**：封禁 E2E（§4.4）——阶段 1 门禁表「封禁 E2E 可演示」亦指此链写段经 Gateway 打通。

---



## 14. 安全与治理

写工具 barrier；封禁 verification；`risk_level` + `approval_ticket`；审计 DeviceCallLog + `agent_invocation_logs`；研判执行分离；S-lite egress（第二波）。

---



## 15. 验收标准


| #   | 条目                                                     |
| --- | ------------------------------------------------------ |
| 1   | 无厂商 SDK 直入 Hermes/API                                  |
| 2   | 对话/工作流/API 设备下发共走 DeviceGateway                        |
| 3   | LLM 可通过 `list_device_actions` 枚举后下发，不依赖硬编码 id（工作流节点除外） |
| 4   | 投影工具与门面工具均写 `DeviceCallLog`，`source` 正确                |
| 5   | 重复 `idempotency_key` 不重复封禁                             |
| 6   | 研判 Agent 无写工具；路径 A 用 `ban_risk_analyze`                |
| 7   | §13.2 MVP 完成                                           |
| 8   | 治理链对 `device_*` 投影工具与 `device_action` 均生效              |
| 9   | 新工具无双工厂重复注册                                            |
| 10  | 语义 `block_ip` 在无默认设备时返回明确错误，不静默 Mock                   |
| 11  | 投影工具名使用 `action_id`，同设备同 `action_type` 多动作不冲突          |


---



## 16. 反模式清单


| 反模式                                 | 后果                             |
| ----------------------------------- | ------------------------------ |
| Hermes import 厂商 SDK                | 耦合                             |
| 投影/HTTP 工具绕过 DeviceGateway          | 审计分裂（**反驳纯 run_http_tool 方案**） |
| 研判 Agent 绑 block_ip                 | 误封                             |
| 路径 A 用 soc_decision                 | 契约错误                           |
| 阶段 1 抢跑、跳过 invoke_agent 收口          | 双运行时加剧                         |
| 工具 A 在 Agent 层直调工具 B                | 绕过治理                           |
| 只暴露 `device_id` 投影、不提供语义 `block_ip` | LLM 误用率高                       |
| 无默认设备却让处置 Agent 调写工具                | 幻觉 device_id                   |


---



## 17. 已知问题

见 `@docs/architecture/module-responsibilities-and-relations.md`：`search_assets` 双轨、tool_search 隐藏关键工具、内置工具混列、两套工作流概念等。不阻塞阶段 0。

本文 v1.3 补充（代码核验）：


| #   | 问题                                                   | 处理阶段                                        |
| --- | ---------------------------------------------------- | ------------------------------------------- |
| 7   | Hermes 认 `block_ip`，builtin 为 `block_ip_on_firewall` | 阶段 1 增语义 `block_ip`（§6.8）                   |
| 11  | `Tool.tool_source` 与 `ToolEntry.source` 双枚举          | 阶段 2 Provider 统一（§5.6）                      |
| 12  | 无默认封禁设备配置                                            | 阶段 1 `Agent.variables` 或 SystemConfig（§6.8） |
| 8   | framework 工具非普通 DB 执行路径，勿当用户可删工具                     | 文档 §5.5；实施注意                                |
| 9   | `enabled_devices` 字段尚未存在                             | 阶段 1 ORM/API                                |
| 10  | 尚无 `invoke_tool`，工作流与 Agent 工具审计路径不一致                | 阶段 2                                        |


---



## 18. 术语表


| 术语             | 定义                                                 |
| -------------- | -------------------------------------------------- |
| 动作投影           | 每个 DeviceAction → `device_{device_id}_{action_id}` |
| 语义工具           | `block_ip`，内部解析默认设备后走 Gateway                      |
| 门面工具           | `device_action`，显式 device + action 下发              |
| DeviceGateway  | 设备唯一执行缝                                            |
| correlation_id | 关联 agent/workflow 调用，阶段 2；非 OTel trace_id          |


---



## 19. 变更记录


| 日期         | 版本       | 说明                                                                                                         |
| ---------- | -------- | ---------------------------------------------------------------------------------------------------------- |
| 2026-09-23 | v1.0     | 初版                                                                                                         |
| 2026-09-23 | v1.1     | 补充三路径、DeviceGateway、反模式等                                                                                   |
| 2026-09-23 | v1.2     | 吸收附录评审与 `@docs/architecture/device-integration-architecture.md`；统一分层编号；定稿设备工具策略；§6.7 采纳/反驳表；删除独立附录 A（并入正文） |
| 2026-09-23 | v1.3     | §5.5 工具统一管理；§21 方案自评；修正附录 B；`enabled_devices` 定稿                                                           |
| 2026-09-23 | v1.4     | §5.6 双 source 枚举；§6.8 语义/技术分层与默认设备；投影名统一 action_id；§22 二次自审                                                |
| 2026-09-23 | v1.5     | §6.7 历史修订痕迹（保留废弃表述）；§13 摘要化；**§23 分阶段可执行落地方案**（任务 ID、文件、门禁、回滚）                                             |
| 2026-09-23 | v1.6     | 追加 Codex §24 评审疑问与待决事项                                                                                     |
| 2026-09-24 | **v2.0** | **架构定稿**：三方统一；移除 §23 落地方案正文；合并评审为 §20；**附录 C** 待补充细节任务清单                                                   |
| 2026-09-24 | v2.0.1   | 方案文档迁入 `docs/architecture/`（原 `fangan`）；交叉引用路径更新                                                           |
| 2026-09-24 | v2.0.2   | 附录 C 拆为独立 [待办与开工清单.md](./待办与开工清单.md)                                                                       |
| 2026-09-24 | v2.0.3   | **D-1 已定**：§4.4 标为暂时 MVP 验收绳；§20.4 人工确认记录                                                                       |
| 2026-09-24 | v2.0.4   | **D-2 已定**：C0-1 研判 Agent + LLM 由项目负责人自领；见 §20.4、待办清单 D2-1～D2-8                                                      |


---



## 20. 定稿结论与评审结案

> v1.0～v1.6 评审过程保留于 git 历史与本节摘要；**不删除** §6.7 历史修订痕迹。



### 20.1 已定稿的架构决策


| 决策     | 结论                                                                         |
| ------ | -------------------------------------------------------------------------- |
| 编排中枢   | Hermes + `invoke_agent`；固定 SOP 走工作流，需判断走 LLM 多轮调工具                         |
| 模块接入   | 只暴露工具契约；L1 函数可复用，Agent 层工具互调禁止（§3.4）                                       |
| 设备工具形态 | **投影为主 +** `device_action` **门面 + 枚举**；命名 `device_{device_id}_{action_id}` |
| 设备执行   | **一律 DeviceGateway**；禁止纯 `run_http_tool` 旁路                                |
| 封禁分层   | 语义 `block_ip` + 技术投影；保留 `block_ip_on_firewall` 并转发                         |
| 工具管理   | 同一 `tool_engine` + `tool_source` 分类；**不用 MCP** 作主方案（附录 B）                  |
| 研判与执行  | 研判 Agent 只读；路径 A 用 `ban_risk_analyze`，写操作由工作流节点或处置工具                       |
| 实施门禁   | **阶段 0（基座 §13.2）完成后**再设备接线；不接受与 Hermes 收口并行抢跑                              |




### 20.2 明确不采纳或延期（保留反驳理由）


| 原观点                                  | 处理                                              |
| ------------------------------------ | ----------------------------------------------- |
| DeviceAction 完全走 `run_http_tool`，零胶水 | 不采纳；执行必须经 Gateway（§6.7 H-6）                     |
| 阶段 1 投影全部动作                          | 不采纳；高频写 + 只读全量，其余走门面（§6.7 H-7）                  |
| 阶段 1 全链路 trace_id                    | 延期；阶段 1 `idempotency_key`，阶段 2 `correlation_id` |
| 阶段 1 独立设备 HTTP 微服务                   | 延期至阶段 3                                         |
| 内置 MCP 统一管理                          | 不采纳；演进项（附录 B）                                   |




### 20.3 评审一致性


| 来源            | 结论                                             |
| ------------- | ---------------------------------------------- |
| Cursor        | 与正文一致；L1 复用 ≠ 工具互调（§3.4）                       |
| Codex §24 R 类 | 7 条初读误判，正文已覆盖，**结案**                           |
| Codex §24 Q 类 | 6 条实施细化，**不阻塞定稿**；见 [待办与开工清单.md](./待办与开工清单.md) |
| 项目组           | 架构方向统一；落地方案单独排期，不在本文展开                         |



### 20.4 人工确认（项目组）

| ID | 议题 | 结论 | 日期 |
|----|------|------|------|
| **D-1** | 封禁 E2E 是否为**暂时** MVP 验收绳 | **是**。跑通 §4.4 即证明 Agent 底座最起码可用；非产品边界。阶段 0 验研判+工作流；阶段 1 验 Gateway。后续增加多场景与自动化搭建测试，不替代本条门禁。 | 2026-09-24 |
| **D-2** | C0-1 研判 Agent + LLM 负责人 | **已定**。项目负责人自领 D2-1～D2-8；按默认技术路线（`engine=hermes`、只读工具、不配 `block_ip`）执行，无架构级分歧。 | 2026-09-24 |
| **D-3** | C1-13 高危动作勾选策略 | **待确认**。勾设备时高危写动作是否默认对 LLM 可见；由产品/安全运营在阶段 1 前拍板（A 全装配 / B 高危单独勾 / C 折中）。**不阻塞**阶段 0。 | — |

明细与任务勾选见 [待办与开工清单.md](./待办与开工清单.md) §人工确认记录。


---



## 附录 B：工具统一管理——是否用 MCP 与内置/设备/外部工具如何共存（2026-09-23）

> 本章回答：**大量暴露的工具如何统一管理？要不要封装成 MCP？智能体内置工具与设备/外部工具是分开管还是一起管？**
> 结论先行：**不用 MCP；运行时统一装配 +** `tool_source` **分类 +** `tool_search` **分级**（持久化 Tool 表 + 动态物化并存，见 §5.5、§5.6）。



### B.1 为什么不建议用 MCP

代码与既有设计已明确"对外集成走 REST/Webhook + HTTP 工具，不做 MCP"：

- `backend/app/core/tools/catalog.py`：`ToolCatalog` 类注释——"MCP 接入暂不实施，对外集成走 REST/Webhook + HTTP 工具；见 `@docs/soar-agent-v2-master-plan.md` §九"。
- `backend/app/core/tools/types.py`：`ToolSource = Literal["builtin","framework","security","custom"]`，注释"有需求时可扩展为 `Literal[...,"mcp"]`"。

**MCP 适用场景是"跨 Agent 宿主互操作 / 对接第三方现成 MCP Server"。** 本项目是**单平台内部**管理自己的工具：设备、资产、知识库、内置安全工具都归属同一进程与同一 Hermes 引擎，没有"多个异构宿主"的互操作需求。此时引入 MCP：

- 不会替代平台自己的工具注册表，只是多一层协议包装；
- 设备鉴权在 `Device` 表、执行统一走 `DeviceGateway`（§6.3/§6.7），用 MCP 反而绕过了现有 Governance/审计；
- 增加一整套 server/client 运行时与维护成本。

**结论**：现在不引入 MCP。若将来要接第三方 MCP Server 或让别的 Agent 宿主调用本平台能力，再经 `ToolCatalog` 扩一个 `mcp` source（`types.py` 已预留）。

### B.2 已有：统一装配 + 分来源登记（勿误解为「一切都在 Tool 表」）

> **v1.3 曾写错（保留痕迹）**：~~「内置、设备、外部工具统一登记在同一张~~ `Tool` ~~表」~~ — 与 KB/资产/设备投影的运行时物化矛盾，v1.4 已修正；详见 §6.7 H-2。

**持久化在** `Tool` **表**（`ToolCatalog` + `seed_service`）：`builtin`、`security`、`custom`（含用户 code/http）。

**运行时物化、通常不落表**：KB 检索、资产检索、工作流包装、设备投影（阶段 1 起）。它们在 `tool_engine` 中变成 `ToolEntry`，对 LLM 与持久化工具**同等可见**。


| `tool_source` / 来源    | 存储                                                                            | 举例                                                   | 装配入口                     |
| --------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------ |
| `builtin`             | Tool 表 seed                                                                   | `get_threat_intel`、`check_whitelist`                 | `_register_db_tools`     |
| `security`            | Tool 表 seed                                                                   | `nmap_scan`                                          | `_register_db_tools`     |
| `custom`              | Tool 表用户建                                                                     | OpenAPI 导入、自建 code                                   | `_register_db_tools`     |
| `framework`           | Catalog 定义；**executor 拦截**，`tool_engine` 对 `tool_type=framework` **跳过 DB 执行** | `delegate_task`、`tool_search`                        | Hermes executor + 种子     |
| `device`（阶段 1 增）      | 运行时物化（可选镜像到 Tool 表做 UI 展示）                                                    | `device_{id}_{action_id}`                            | `_register_device_tools` |
| kb / asset / workflow | 动态                                                                            | `search_knowledge_base`、`search_assets`、`workflow_*` | 各自 `_register_*`         |


`Agent.enabled_tools` 管 DB 工具；`enabled_kbs` / `enabled_asset_types` / `enabled_workflows` / `enabled_devices`**（推荐）** 管动态类能力。

> **一块处理** = 同一 `tool_engine` 注册表 + 同一治理链；**分类管理** = `tool_source` + Agent 不同勾选字段。不是强行把所有工具写进一张物理表。



### B.3 已有：运行时"核心 vs 可延迟"分级（解决工具过多）

工具多了 LLM 上下文装不下，项目已有现成分流（`backend/app/agent/hermes/tool_search.py`）：

- **核心来源（永不延迟）**：`builtin` / `kb` / `delegate` / `memory` / `persisted` / `asset` + 显式研判封禁名单 `_EXPLICIT_CORE_NAMES` / `_JUDGMENT_CORE_TOOL_NAMES`（含 `get_threat_intel`、`check_whitelist`、`block_ip_on_firewall` 等）。
- **可延迟来源**：`db_code` / `db_http` / `openapi_dynamic` / `workflow` → 数量多时收进目录，LLM 按需 `tool_search` → `tool_describe` → `tool_call` 再调用（`assemble_tool_defs` / `classify_tools`）。

**设备工具接入这套分级**（阶段 1 落地）：

- 写动作（`block`/`dispose`、`risk_level=high_risk`）→ 归入**核心/显著**，永不延迟，保证"一句话封 IP"可即时下发；
- 只读枚举/查询（`list_device_actions`、`query_*`）→ 走**可延迟**，降低上下文占用；
- 由 `tool_source=="device"` 或 `device_` 前缀参与分类与写工具判定（§6.4 已定）。



### B.4 统一管理的"三合一"视图


| 环节    | 内置工具                        | 设备投影工具                      | 外部/自建工具                  | 统一机制                 |
| ----- | --------------------------- | --------------------------- | ------------------------ | -------------------- |
| 登记    | `ToolCatalog` seed → Tool 表 | 运行时物化（`tool_source=device`） | DB / OpenAPI             | Tool 表 + 动态 Provider |
| 分类    | `tool_source=builtin`       | `tool_source=device`（新）     | `custom/db_http/db_code` | `tool_source` 元数据    |
| 装配    | `tool_engine._register_*`   | `_register_device_tools`    | `_register_db_tools`     | 同一 `tool_engine`     |
| 对 LLM | 核心可见                        | 核心写/可延迟读                    | 按 source 分级              | `tool_search` 分级     |
| 治理    | guardrails/verification     | 同左（按 `device_` 前缀）          | 同左                       | 同一治理链                |
| 审计    | agent_invocation_logs       | `DeviceCallLog`             | 工具执行日志                   | 各自落库                 |


**建议**：不要给设备工具单独建一套"MCP 或插件包"管理；而是把它们并入上面的 `Tool` 表 + `tool_source` 体系。将来若要插件化、要跨宿主互操作，再在 `ToolCatalog` 侧加 Provider/Manifest（§10、§13 阶段 3 演进项），而不是引入独立的 MCP 协议。

### B.5 结论与落地动作

1. **不引入 MCP**：单平台内无跨宿主互操作需求，且会绕过 DeviceGateway/审计（见 §B.1）。
2. **内置与设备/外部工具一块管理**：统一走 `tool_engine` 装配 + `tool_search` 分级；持久化工具进 `Tool` 表，动态工具运行时物化（见 §B.2/B.3、§5.5）。
3. **设备工具作为新** `device` **source** 加入既有体系，写动作核心化、读动作可延迟（见 §B.4）。
4. **阶段 1 落点**：`types.py` 增 `TOOL_SOURCE_DEVICE`；`Agent.enabled_devices`；`tool_engine._register_device_tools()`；`tool_search` 对 device 写核心/读可延迟；投影名优先 `device_{device_id}_{action_id}` 防冲突（§6.4；任务见 [待办与开工清单.md](./待办与开工清单.md) §C.2）。
5. **阶段 2 落点**：`ToolRegistryBuilder` 吸收各 `_register_`*，对外只留 `invoke_tool`。
6. **未来接第三方 MCP**：仅在跨宿主/第三方 MCP Server 需求明确时扩展 `types.py`，不是当前优先级。

**一句话**：统一管理靠 **同一** `tool_engine` **注册表 +** `tool_source` **分类 +** `tool_search` **分级**；MCP 非当前选项。语义工具（`block_ip`）与技术投影（`device_`*）同属设备能力，但服务不同调用场景（§6.8）。