# 设备对接方案：Agent 底座松耦合集成设计

> 目的：梳理"后续设备对接 + API 下发指令"如何与 Agent 底座结合，做到 **设备模块作为独立模块、只经 API/工具调用、不与底座直接耦合**。本文先给出已验证的现状，再给出推荐架构、落地步骤与可作参照的既有代码。  
> **架构定稿以** [@docs/architecture/soar架构方案.md](./soar架构方案.md) **§6 为准**；本文作代码落点与历史方案 A/B/C 补充。

---

## 一、结论先说（TL;DR）

**你们要的方案，项目里已经具备 90% 的底座能力**，缺的不是新造框架，而是把两条现成链路接通：

1. **底座工具系统（属主：Agent）**：`Tool` 模型天然支持 `tool_type='http'` 声明式接口工具（`backend/app/core/tool_http_runner.py`），且支持 OpenAPI 导入（`backend/app/api/v1/tools_manage.py`），绑定到智能体通过 `Agent.enabled_tools` 完成——**这正是"设备模块只经 API 调用、不与底座耦合"的载体**。
2. **设备模块（属主：设备对接）**：`Device / DeviceAction / DeviceCallLog`（`backend/app/models/device.py`）+ `action_executor.py` 已把"设备 + 动作"抽象成**数据配置**，工作流节点 `device_action`、`banned_ips` 已在消费它。

**关键缺口（需补）：** `device_action` 这个 Agent 工具名已出现在 Hermes 的护栏/校验/调度代码里（`guardrails.py` / `verification.py` / `tool_dispatch.py` / `threat_scanner.py`），**但没有任何地方真正注册它的执行体**。即"Hermes 已准备好会用 `device_action`，但没人把它接线到 `action_executor`"。

所以落地 = 在底座工具系统中补一个 `device_action` HTTP 桥（或设备专属工具生成器），让"设备动作"变成可下发给 LLM 的工具，其余全部复用现有机制。

---

## 二、现状核查（代码落点）

### 2.1 底座工具系统（Agent 侧）
| 能力 | 位置 | 说明 |
|------|------|------|
| `Tool` 模型（code/http/框架） | `backend/app/models/tool.py` | `tool_type='http'` + `http_config` 声明式接口 |
| HTTP 工具执行器 | `backend/app/core/tool_http_runner.py:run_http_tool` | 参数分发(query/body/header/path)、鉴权、重试、JSONPath 提取 |
| 工具加载/缓存 | `backend/app/core/tool_runner.py:load_tool_function` (L580) | 按 `tool_type` 分发给 code/http |
| OpenAPI 导入 | `backend/app/api/v1/tools_manage.py:OpenAPIImportRequest` | 从 OpenAPI/Swagger 一键生成 HTTP 工具 |
| 绑定到智能体 | `backend/app/agent/decision.py:_build_db_tools` (L132)、`backend/app/agent/hermes/tool_engine.py:_register_db_tools` (L191) | 读 `Agent.enabled_tools` → 加载为工具 |
| 平台工具目录 | `backend/app/core/tools/catalog.py` | 内置/框架/安全工具定义 |

> 关键：`catalog.py` 注释已写明方向——"对外集走 REST/Webhook + HTTP 工具；MCP 暂不实施"。**你们选的就是官方推荐路线。**

### 2.2 设备模块（设备侧）
| 能力 | 位置 | 说明 |
|------|------|------|
| `Device` 模型 | `backend/app/models/device.py` | api_url / 鉴权 / 状态 / 心跳 / 标签 |
| `DeviceAction` 模型 | 同文件 | 每个动作 = 一个 API 调用（method/path/params_schema/body_template/auth_type） |
| `DeviceCallLog` 模型 | 同文件 | 每次动作调用日志 |
| 执行器 | `backend/app/devices/action_executor.py` | `execute_device_action` 实际发 http；`find_device_action_by_type` 找动作 |
| 工作流节点 | `backend/app/core/node_executors.py:execute_device_action` (L825) | `device_action` 节点 |
| CRUD API | `backend/app/api/v1/devices.py` | 设备/动作/测试/模板/导入 |

### 2.3 Hermes 已预留但未接线的 `device_action`
`backend/app/agent/hermes/` 多处把 `device_action` 当"写工具"处理：
- `guardrails.py`：写工具防循环
- `verification.py:WRITE_TOOLS_REQUIRING_VERIFICATION`：写操作证据链校验（含 `_verify_device_action` L198）
- `tool_dispatch.py`：写工具 → 顺序 barrier
- `threat_scanner.py` / `tool_result_classification.py`：威胁检测/结果分类
- **但没有工具定义、没有执行体注册** → 这就是要补的桥。

---

## 三、推荐架构（松耦合三选一，推荐 A）

### 方案 A（推荐）：设备动作 → HTTP 工具（数据驱动，零代码，官方路线）
> 把 `DeviceAction` 当作"接口声明"，由底座把已启用的动作**动态物化成 `tool_type='http'` 工具**，走 `run_http_tool` 执行，天然与底座解耦。

```
[设备] ⇄ HTTP ⇄ [Device+DeviceAction 配置(数据)] 
                              ↓ 物化为 HTTP 工具 (run_http_tool)
                        [Agent.enabled_tools] → LLM 可直接调用
```
- **优点**：不加新运行时；复用 OpenAPI 导入、参数 schema、鉴权、重试、JSONPath；设备类型可无限扩展，只需配 `DeviceAction`。
- **耦合**：设备侧只产生"配置 + 调用端点"，底座只消费"HTTP 工具 schema"，彼此无代码依赖。
- **落地**：新增一个 `_register_device_tools`（仿 `tool_engine._register_db_tools`），把选中设备的启用动作包装成 `ToolEntry`；或在 agent 建连时自动生成 `device_action` 桥工具。

### 方案 B（备选）：桥工具 `device_action`（单一入口，需实现执行体）
> 补上 Hermes 已预留的名字：注册一个 `device_action` 写工具，`run` 内部查 `DeviceAction` → 调 `action_executor.execute_device_action`。
- **优点**：正好填补 `verification.py` 已写好的 `_verify_device_action`；LLM 说话更"人话"（"把 8.8.8.8 封了"）。
- **缺点**：需要一个"动作选择 + 参数映射"层，比方案 A 多一点胶水代码。

### 方案 C（最简）：每个动作直接建 HTTP 工具（人工配置即可用）
> 运维在工具管理里，按设备提供的动作 API 手建/OpenAPI 导入 HTTP 工具，勾给智能体。
- **优点**：零后端改动，先用起来。
- **缺点**：与 `Device` 配置不联动，重复录入；丢失设备状态/鉴权上下文。

> **建议组合**：短期用 C 快速验证；中期用 A 自动化生成；需要"一句话封 IP"这类人性化入口时叠加 B。A+B 共用 `run_http_tool` 与 `verification`，是长期主线。

---

## 四、落地步骤（推荐 A 为主，含代码落点）

1. **桥接生成器**：新增 `backend/app/devices/as_tool.py`（或并入 `action_executor.py`），提供
   - `device_actions_to_http_tools(db, device_ids|action_ids)` → 把启用动作转成 `run_http_tool` 闭包（复用 `tool_runner.py` 的 http 分支模式，L637 `_http_run`）。
   - 每个工具 `name` 建议 `device_{device_id}_{action_type}`，`parameters_schema` 直接复用 `DeviceAction.params_schema`。
2. **注册进智能体**：在 `backend/app/agent/hermes/tool_engine.py` 新增 `_register_device_tools()`，读取设备启用动作；`decision.py:_build_db_tools` 同样兜底（LangGraph 路线）。
3. **配置联动**：`Agent` 加 `enabled_devices=JSON`（或复用 `enabled_tools` 白名单），把"勾设备动作"暴露成智能体配置。
4. **写操作校验**：若走单一 `device_action` 名，`verification.py:_verify_device_action` 已就绪，直接复用；建议把 `verify_device_action` 纳入 `Agent.tool_configs`。
5. **审计闭环**：所有下发都走 `DeviceCallLog` 记 `workflow_id / agent_id / user_id / source_ip`（字段已齐），满足 SOC 审计。
6. **健康与寻址**：只把 `status in ('online')` 且动作 `enabled=True` 的设备物化成工具，避免 LLM 调离线设备。

---

## 五、最佳实践 / 好方案补充

1. **先声明、再执行、后审计**：所有写操作必须三段式——声明工具（schema）→ 证据校验（verification）→ 落 `DeviceCallLog`。项目已为这三段备好地基。
2. **参数即白名单**：`DeviceAction.params_schema` 定义"该动作能传哪些参数"，LLM 只能传 schema 内的参数；复杂设备用 `body_template` 占位符（`{{param}}`），天然防注入。
3. **超时/重试闭环**：设备动作统一走 `httpx`，`timeout`/`retry`/`verify_tls` 已入模型；建议在工具层兜底一次重试。
4. **命名空间隔离**：设备工具名统一前缀 `device_`/`query_`（读）区分读写；`tool_dispatch` 的 `_PARALLEL_SAFE_PREFIXES` 已按 `get_/query_/list_/search_` 判读并行安全，读动作可并行、写动作走 barrier。
5. **不暴露敏感的鉴权**：`http_config` / `api_key` 上屏/返回给 LLM 时脱敏（`devices.py` 已有相关处理思想），`redact.py`/`message_sanitization.py` 可复用。
6. **向后兼容**：保留 `hard`（代码耦合）路径不动，新增 `http` 路径为默认，逐步迁移，避免一次性大改。

---

## 六、你们"不与模块直接耦合"目标的满足点

- **设备模块**：内部只做"录入配置 + 定义动作 + 调设备 API"，不 import 底座引擎。
- **底座（Agent）**：只消费"HTTP 工具 schema + 执行端点"，不 import 设备模块实现。
- **耦合边界**：唯一的衔接点是 `Tool`/`ToolEntry` 的 schema，以及（可选的）`device_action` 桥工具名——都属于"接口/数据契约"，非代码耦合。
- **扩展**：新增一种设备/动作 = 加一条 `DeviceAction` 配置，无需改底座代码。

---

## 附：关键文件索引
- 底座工具：`backend/app/models/tool.py`、`backend/app/core/tool_http_runner.py`、`backend/app/core/tool_runner.py`、`backend/app/core/tools/catalog.py`
- 设备模块：`backend/app/models/device.py`、`backend/app/devices/action_executor.py`、`backend/app/api/v1/devices.py`
- Hermes 预留：`backend/app/agent/hermes/verification.py`、`guardrails.py`、`tool_dispatch.py`
- 绑定入口：`backend/app/agent/hermes/tool_engine.py`、`backend/app/agent/decision.py`



