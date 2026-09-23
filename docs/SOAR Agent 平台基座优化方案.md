# SOAR Agent 平台基座优化方案

> 状态：**实施指南 v0.7（终审稿）**（2026-09-22）— **唯一执行清单见 §13.2**；§7/§1.1/§12 含历史与评审记录，勿全做。  
> §12.8 为 Codex 对照意见；§13 为独立审视；§16 为终审结论（项目组讨论用）。
> 范围：后端 Hermes/LangChain 双轨、工具运行时、工作流执行、部署与外网预留、前端与 Nginx 边界。
> 定位：在 **不推翻 Hermes 引擎** 的前提下，收敛架构分裂、统一工具化调用与复用，并为内网 → 外网演进预留扩展点；**借鉴 Flocks 声明式插件体系**，实现内网部署下的高可扩展与高解耦。
> 关联文档：
> - `docs/soar-agent-current-state.md` — 现状全貌
> - `docs/module-responsibilities-and-relations.md` — 五模块关系
> - `docs/soar-agent-v2-master-plan.md` — V2 产品层（双用户/模板/交付）
> - `docs/hermes-engine-integration.md` — Hermes 集成说明
> - `docs/open-source-reference-survey.md` — 开源对标（Shuffle/n8n/LangGraph）
> - 外部参考：`D:/Programming/PySppace/agent/flocks` — 声明式工具/工作流/Skill 插件与 ExtensionPoint 加载器

---

## 1. 摘要

| 级别 | 数量 | 说明 |
|------|------|------|
| 🔴 Critical | 3 | 生产行为错误、引擎路由分裂、分层/导入缺陷 |
| 🟠 High | 6 | 工具三源重复、双工厂、鉴权与引擎默认值 |
| 🟡 Medium | 12 | 内网硬编码、外网预留、OpenAPI/迁移/挂载、**声明式与解耦** |
| 🔵 Low | 5 | UX、文档、限流、测试耦合 |

**优先修复顺序**：Critical #1 → #2 → #3 → High #4～#9 → Medium 工具统一与外网配置 → Low 收尾。

**核心判断**：

- 底层已是 **LangGraph + 自研 Hermes**；Hermes 含委派/护栏/预算/验证/威胁扫描等商用级能力，**不应替换**，应作为唯一主引擎收敛。
- 当前最大技术债：**三套工具实现 + Celery/test-run 双工作流执行器 + API 端点与 `engine` 字段不对齐**；能力写死在 Python/DB seed 字符串中，**扩展必须改代码、改多处**。
- **高可扩展必须以高解耦为前提**：运行时（Hermes）/ 注册（Catalog）/ 声明（YAML·JSON）/ 实现（Handler·Code）/ 交付（DB·UI）五层分离；借鉴 Flocks 的 `_provider.yaml` + 工具 YAML + `workflow.json` + `SKILL.md` + `PluginLoader` 模式。
- 内网不等于低扩展：内网部署仍可能对接多厂商设备（TDP/天眼/青藤/XDR）、多场景 Agent、多客户策略；**声明式包 + Provider 注册** 比「改 backend 发版」更符合基座定位。
- **内网定位为主**：本项目为纯内网私有化部署，安全与合规（Phase S）、无状态化与可扩展预留（Phase F）是基座级硬要求；**外网演进仅留口子（低优先）**——`DEPLOY_MODE` 开关、可配置网络策略、ToolProvider 抽象、统一运行时入口、插件目录热加载，而非重写 Agent 框架。
- **四维验收框架**：安全与合规 / 架构与扩展 / 智能体核心能力 / 工程与运维 均按内网适配裁剪（见 §1.1），避免为外网/云原生标准过度设计。

---

## 1.1 内网部署约束与四维验收框架

> 本项目为**纯内网私有化部署**（不发生任何外网出站，模型/数据/日志全程内网）。
> 本方案的内网定位决定了四维要求（安全与合规 / 架构与扩展 / 智能体核心能力 / 工程与运维）
> 必须做**内网适配裁剪**：保留安全合规全维、架构扩展砍到「能横向但不云原生」、
> 智能核心做内网适配（本地模型为主、A2A/MCP 降权）、运维裁掉重件（K8s/Temporal 列为演进项）。

### 1.1.1 四维验收框架 × 内网适配裁剪

| 维度 | 要求项 | 内网定位 | 落地归属 | 状态 |
|------|--------|----------|----------|------|
| 安全与合规 | 完全本地化私有化部署 | 天然满足 | - | 已具备 |
| 安全与合规 | 网络出口控制（网络层，非 Prompt 层） | **P0 必做** | Phase S | 缺口 |
| 安全与合规 | 容器级执行隔离（高危操作不外泄） | **P0 必做** | Phase S | AST+builtins 沙箱，非容器隔离 |
| 安全与合规 | Policy-as-Code + Reviewer Agent | **P0 必做** | Phase S | 缺口 |
| 安全与合规 | 动作分级（1-10 级）+ 高等级人工审批 + 回滚账本 | **P0 必做** | Phase S | 有 approvals，无分级/回滚账本 |
| 安全与合规 | Append-only 审计（工具/LLM/RAG + Finding + Evidence） | **P0 必做** | Phase S | 有 audit_middleware，非 append-only |
| 架构与扩展 | 高解耦（Agent 逻辑与执行环境分离） | 必做 | Phase B | 方向对，Hermes 上帝类待拆 |
| 架构与扩展 | 可扩展（横向扩容、无状态 Worker） | 预留能力 | Phase F | memory/ws/cache 有状态 |
| 架构与扩展 | 高可用（无 SPOF + 故障恢复） | 内网够用级 | Phase F | 单实例 compose |
| 架构与扩展 | 云原生（K8s/HPA/命名空间） | **降级为演进项** | 演进项 | 暂不实施 |
| 架构与扩展 | 持久化工作流引擎（Temporal） | 降级为可选预留 | 演进项 | Celery+DB 持久化够用 |
| 智能核心 | 多模型管理与路由 + 本地推理（Ollama/vLLM） | 内网刚需 | Phase B | 有 provider，无路由层/本地节点 |
| 智能核心 | MCP 标准工具集成 | 内网降权（HTTP/OpenAPI 为主，预留 Provider 口子） | 演进项 | 维持「暂不实施」，留扩展点 |
| 智能核心 | 持久化记忆 + RAG（ATT&CK/Runbook） | 必做 | Phase F | 有 RAG；记忆三处并存未打通（见 §12.8.1） |
| 智能核心 | 多 Agent 协作 / A2A | A2A 内网降权；delegator 内部协作够用 | - | delegator 已有 |
| 工程与运维 | 全链路可观测（Tracing） | 必做 | Phase F | 有 trace_id 概念，无 OTel span |
| 工程与运维 | 分级 HITL（可配置审批门） | 网安核心 | Phase S | 单级审批，缺多级 Gate |
| 工程与运维 | 容量控制/优先级调度 | 内网只用 LLM 限流+任务优先级（无多租户配额） | Phase B | 无全局调度 |

> **级别对齐说明（v0.5）**：表中「Phase S」列仍沿用 v0.3 四维框架表述；**v0.4 已拆为 S-lite（纳入 P1）/ S-full（演进项）**，详见 §12.2.5。实施时勿按表中「P0 必做 + Phase S 全量」推进，以 §12.4 为准。

**裁剪原则**：
- **安全与合规整维保留且最高优先**（内网生命线，且是合规硬门槛）。
- **架构扩展砍到「能横向 + 无状态 + 双副本冗余」**，不引入 K8s/HPA/Temporal 作为内网硬要求；云原生与持久化工作流引擎标记为**演进项**。
- **MCP 维持「声明式 HTTP/OpenAPI 工具为主 + 预留 MCP Provider 扩展点」**，不因「事实标准」强行上 MCP。
- **A2A 内网降权**，用 Hermes `delegator` 内部协调器即可。
- **容量调度内网不引入多租户配额**，仅做 LLM 并发限流 + 任务优先级 + Token 预算。

---

## 2. 现状架构（代码核验）

### 2.1 运行时双轨（含工作流三路径，v0.4 修正）

> ⚠️ v0.3 曾将「Celery 不走 Hermes」等同于封禁生产问题；**封禁主链路实际走路径 A**，详见 §12.2.1。

```
【Agent 对话】
  POST /agents/{id}/chat          → HermesAgentExecutor（要求 engine=hermes）
  POST /agents/{id}/test/stream   → run_agent_decision_stream（LangGraph，未校验 engine）❌

【工作流 — 三路径】
  路径 A 封禁专用（生产主链路）
    workflow/engine.py → agent_analyze → agent_client HTTP → /internal/mock
    ❌ 不经 Hermes / LangGraph ReAct

  路径 B 通用 Celery
    workflow_tasks._execute_node → ai_agent → run_agent_decision ❌

  路径 C test-run / 同步
    workflow_runner → node_executors.execute_ai_agent（支持 Hermes ✅，需 agent_id）
```

### 2.2 工具链多源

| 来源 | 路径 | 说明 |
|------|------|------|
| 运行时 Mock/真源 | `app/tools/context_tools.py` | `check_whitelist` 等，部分返回 `bool` |
| DB 预置种子 | `app/core/tools/definitions/builtin.py` | 内联重复逻辑，返回 `dict` |
| LangGraph 默认集 | `app/agent/agent_tools.py` | 4 个 StructuredTool |
| 执行层 | `app/core/tool_runner.py` | code 沙箱 |
| HTTP 层 | `app/core/tool_http_runner.py` | 声明式 HTTP |
| Hermes 注册表 | `app/agent/hermes/tool_engine.py` | 并行/guardrails/verification |
| LangGraph 工厂 | `app/agent/decision.py` | `_build_db_tools` |
| 统一目录（部分） | `app/core/tools/catalog.py` | `ToolCatalog`，未完全贯通 |

### 2.3 五模块与基座关系

智能体为编排中枢，引用模型/技能/知识库/工具/资产类型；工作流可调用智能体与工具。详见 `docs/module-responsibilities-and-relations.md`。

### 2.4 与 Flocks 的扩展性差距（为何需要声明式）

| 维度 | Flocks（声明式 + 插件） | SOAR 现状（内联 + DB） | 扩展成本 |
|------|------------------------|------------------------|----------|
| 设备工具 | `_provider.yaml` + 多工具 YAML + `handler.py` | `builtin.py` 内联 code 字符串 + `tool_runner` | 改 seed + 发版 |
| 工作流场景 | `plugins/workflows/{id}/workflow.json` + `workflow.md` | React Flow JSON 存 DB + Celery 旧执行器 | UI 与运行时耦合 |
| Agent | `agent.yaml` + `prompt_builder.py` | Agent ORM + 前端表单 | 字段膨胀 |
| Skill | `SKILL.md` + `flocks_skills` 发现/安装 | Skill 表纯文本 | 无包格式、无依赖 |
| 加载机制 | `PluginLoader` + ExtensionPoint 扫描 | 启动 seed + 手工 import | 无热加载、无版本目录 |
| 凭证 | `credential_fields` + secret store | 环境变量 / SystemConfig 分散 | 设备接入不可声明 |

Flocks 的 TDP 告警研判工作流（`tdp_alert_triage`）与 SOAR 封禁/研判链路业务同构，但 Flocks 以 **workflow.json 节点 + tool.run_safe** 声明完成，SOAR 仍大量依赖 Python 节点硬编码与 mock 分支。

---

## 3. 目标架构（基座优化后）

### 3.1 统一运行时

```
invoke_agent(agent_id, input, channel, stream)
invoke_tool(name, args, agent_id, user_id, trace_id)
        │
        ├── ToolRegistryBuilder（单一工厂）
        │     ├── BuiltinProvider      ← ToolCatalog
        │     ├── CodeToolProvider     ← tool_runner
        │     ├── HttpToolProvider     ← tool_http_runner
        │     ├── OpenApiProvider      ← core/openapi_tools（从 API 层下沉）
        │     └── DeviceProvider       ← 设备插件包（参考 Flocks _provider.yaml）
        │
        ├── HermesAgentExecutor（主引擎）
        └── LangGraph decision（deprecated 降级/Mock）
```

### 3.2 部署模式

| 配置项 | 内网默认 | 外网建议 |
|--------|----------|----------|
| `DEPLOY_MODE` | `intranet` | `extranet` |
| `INTERNAL_API_SECRET` | 强随机 | 必须启用 |
| `security.whitelist_cidrs` | RFC1918 | 客户自定义 |
| `OUTBOUND_HTTP_PROXY` | 内网代理 | 直连或云代理 |
| `/internal` Mock | 可开（需 secret） | 必须关闭 |
| CORS | 内网域名 | 公网域名 + SystemConfig 联动 |

### 3.3 声明式扩展 + 高解耦分层（借鉴 Flocks）

**原则**：改场景 ≠ 改引擎；改设备对接 ≠ 改 Hermes；改策略 ≠ 改 API 路由。

```
┌─────────────────────────────────────────────────────────────────┐
│  L5 交付层   UI 向导 / 模板市场 / resource_shares / DSL 导入     │
├─────────────────────────────────────────────────────────────────┤
│  L4 声明层   AgentSpec · WorkflowSpec · ToolSpec · SkillPack     │
│              （YAML/JSON/MD，版本化目录或 DB manifest 字段）       │
├─────────────────────────────────────────────────────────────────┤
│  L3 注册层   ToolCatalog · PluginRegistry · ProviderRegistry     │
│              ExtensionPoint: TOOLS | WORKFLOWS | SKILLS | AGENTS │
├─────────────────────────────────────────────────────────────────┤
│  L2 运行时   invoke_agent · invoke_tool · WorkflowEngine         │
│              HermesToolEngine · node_executors（唯一执行入口）      │
├─────────────────────────────────────────────────────────────────┤
│  L1 实现层   handler.py · code 沙箱 · HTTP runner · OpenAPI      │
│              （可替换 Mock / 真设备 / 外网 SaaS）                  │
└─────────────────────────────────────────────────────────────────┘
         ▲                              ▲
         │ 扫描加载                      │ 仅通过 L2 调用
  plugins/ 或 DB manifest          禁止 API/Hermes 直 import 设备 SDK
```

**Flocks → SOAR 映射**：

| Flocks 构件 | SOAR 目标构件 | 存储位置建议 |
|-------------|---------------|--------------|
| `plugins/tools/device/{id}/_provider.yaml` | `ToolProviderManifest` | `plugins/tools/` 或 DB `tools.provider_manifest` |
| `tdp_*.yaml`（inputSchema + provider） | `ToolSpec`（声明式 HTTP/设备调用） | 同 Provider 目录 |
| `handler.py`（签名/HMAC） | `ProviderHandler` 协议类 | 插件目录，L1 实现 |
| `workflow.json` + `workflow.md` | `WorkflowSpec` + 人类可读 SOP | `plugins/workflows/` 或导入 DB |
| `agent.yaml` | `AgentSpec`（engine/tools/skills 引用） | DSL / 模板包 |
| `SKILL.md` + frontmatter | `SkillPack` | `plugins/skills/`，对齐 V2 skill-package |
| `PluginLoader` + ExtensionPoint | `app/platform/plugin_loader.py` | 启动扫描 + 可选 watch 热重载 |
| `tool.run_safe(name, **kwargs)` | `invoke_tool(name, args, ctx)` | 统一 L2 入口 |

**解耦约束（编码规范）**：

1. **Hermes / LangGraph 不得 import 具体设备模块**（如 TDP client）；只调 `invoke_tool`。
2. **API 层不得解析 OpenAPI / 编译工具**；只做 CRUD 与包上传，解析在 L3/L4。
3. **工作流节点不得分叉执行器**；Celery 与 test-run 共用 `execute_node`（见 C-1）。
4. **builtin 种子不得内联业务 Python**；改为引用 `context_tools` 或加载声明式 Spec。
5. **场景包版本独立**：`tdp_v3_3_10` 目录并存，Provider 按 `product_version` 选择。

**声明式 ToolSpec 示例（目标格式）**：

```yaml
# plugins/tools/device/tdp_v3_3_10/tdp_log_search.yaml
name: tdp_log_search
provider: tdp_api
tool_type: http
category: device
input_schema: { ... }          # JSON Schema，与 Flocks inputSchema 对齐
http:
  method: POST
  path: "/api/v1/logs/search"
  auth_ref: tdp_hmac           # 引用 _provider.yaml 的 auth 块
requires_confirmation: false
tool_source: device
```

**声明式 WorkflowSpec 示例（与 Flocks workflow.json 对齐的子集）**：

```json
{
  "id": "tdp_alert_triage",
  "start": "receive_alert",
  "nodes": [
    { "id": "receive_alert", "type": "python", "code_ref": "nodes/receive_alert.py" },
    { "id": "query_intel", "type": "tool", "tool_name": "threatbook_ip_query", "tool_args": { "ip": "{{parsed_alert.src_ip}}" } },
    { "id": "join_results", "type": "join", "join": true }
  ],
  "edges": [ ... ],
  "triggers": [{ "type": "webhook", "path": "/alerts/tdp" }]
}
```

内网场景下 `code_ref` 仍可在沙箱执行；复杂逻辑逐步从 DB 内联字符串迁到 **插件目录 + 版本 pin**，避免「改研判逻辑 = 改平台镜像」。

---

## 4. 问题清单与修复 Diff

### 4.1 🔴 Critical

#### C-1 通用 Celery 工作流与 test-run 执行器分裂

- **位置**：`backend/app/tasks/workflow_tasks.py` L336–403；`backend/app/core/node_executors.py` L177–295
- **问题**：Celery 的 `ai_agent` 固定 `run_agent_decision(payload)`，忽略 `agent_id` 与 `engine=hermes`；test-run 已支持 Hermes。
- **影响**：**通用** Celery 工作流（路径 B）在生产不走 Hermes。**封禁主链路（路径 A）另有独立问题**，见 §12 P0-0，不能仅靠本项解决。
- **修复建议**：新增 `_execute_node_async` 适配层，按节点类型委托 `node_executors.execute_node`；**禁止**整函数替换；落地前盘点存量工作流 `agent_id` 配置。

> v0.3 原 Diff（`asyncio.run(execute_node(...))` 整段替换）**已废弃**，见 §12.2.2。

---

#### C-2 `/test/stream` 不校验 engine，Hermes Agent 误走 LangGraph

- **位置**：`backend/app/api/v1/agents.py` L782–904
- **问题**：有工具时固定 `run_agent_decision_stream`；`/chat` 要求 `engine=hermes`，路径不对称。
- **影响**：Playground 与正式对话行为不一致；Hermes 安全能力在测试中不可见。
- **修复建议**：按 `agent.engine` 分流；hermes 复用 `HermesAgentExecutor` + SSE 生成逻辑。

```diff
--- a/backend/app/api/v1/agents.py
+++ b/backend/app/api/v1/agents.py
@@ -796,6 +796,10 @@ async def test_agent_stream(
     user_input = body.input or ""
     has_tools = bool(agent.enabled_tools) or bool(agent.enabled_kbs) ...
+    if (agent.engine or "langgraph") == "hermes" and has_tools:
+        # 与 /chat 共用 Hermes 执行路径（提取 sse 生成器避免重复）
+        return await _hermes_agent_sse(agent, body, db)
```

---

#### C-3 Hermes 依赖 API 层且存在错误 import

- **位置**：`backend/app/api/v1/agents.py` L80；`backend/app/agent/hermes/executor.py` 引用 `_create_llm`
- **问题**：`from app.core.config import settings` 应为 `app.config`；执行器反向依赖 API 路由。
- **影响**：环境变量回退路径 ImportError；难以独立测试与外网 SDK 化。
- **修复建议**：LLM 创建统一下沉 `core/llm_helper.py`。

```diff
--- a/backend/app/api/v1/agents.py
+++ b/backend/app/api/v1/agents.py
@@ -79,7 +79,7 @@ def _create_llm(...):
-    from app.core.config import settings
+    from app.config import settings
```

```diff
--- a/backend/app/agent/hermes/executor.py
+++ b/backend/app/agent/hermes/executor.py
@@
-        from app.api.v1.agents import _create_llm
+        from app.core.llm_helper import create_llm_from_config
```

---

### 4.2 🟠 High

#### H-1 三套工具实现，返回值语义不一致

- **位置**：`app/tools/context_tools.py` L43–50；`app/core/tools/definitions/builtin.py` L6–16；`app/agent/agent_tools.py`
- **问题**：`check_whitelist` 一处返回 `bool`，一处返回 `{"in_whitelist": ...}`；`verification.py` 只认 dict。
- **影响**：封禁前校验可能失效；改一处另一处不生效。
- **修复建议**：`context_tools` 为唯一真源；builtin 种子改为薄包装；统一 schema。

```diff
--- a/backend/app/tools/context_tools.py
+++ b/backend/app/tools/context_tools.py
@@ -42,8 +42,11 @@ def _is_in_whitelist(ip: str) -> bool:
 
-async def check_whitelist(ip: str) -> bool:
+async def check_whitelist(ip: str) -> dict:
     await asyncio.sleep(random.uniform(0.05, 0.15))
-    return _is_in_whitelist(ip)
+    ok = _is_in_whitelist(ip)
+    return {"ip": ip, "in_whitelist": ok}
```

---

#### H-2 LangGraph / Hermes 双套工具工厂重复维护

- **位置**：`app/agent/decision.py` `_build_db_tools`；`app/agent/hermes/tool_engine.py` `_register_db_tools`
- **问题**：新增 OpenAPI/MCP/设备 Provider 需改两处。
- **影响**：工具化复用与外网扩展成本高。
- **修复建议**：新建 `app/agent/tool_factory.py` — `ToolRegistryBuilder`，两引擎共用。

```python
# app/agent/tool_factory.py（新建示意）
class ToolRegistryBuilder:
    def __init__(self, db, agent): ...
    def build_langchain_tools(self) -> list: ...
    def build_hermes_entries(self) -> dict: ...
    def build_openai_schemas(self) -> list[dict]: ...
```

---

#### H-3 `/internal` Mock 服务生产无鉴权

- **位置**：`backend/app/api/v1/internal_mock.py` L10–11
- **问题**：`/internal` 不做用户态鉴权；研判/封禁 mock 可被任意调用。
- **影响**：内网横向风险；封禁路径 A 当前依赖该端点。
- **修复建议**：`INTERNAL_API_SECRET` 强制鉴权；**dev 须提供默认 secret 并始终挂载**（v0.4 修正：禁止「无 secret 则不挂载」）。生产在 P0-0 完成后改为真实 Hermes 研判，mock 限 dev/staging。

```diff
--- a/backend/app/config.py
+++ b/backend/app/config.py
@@
+    DEPLOY_MODE: str = "intranet"
+    INTERNAL_API_SECRET: str = "change-me-in-dev-only"
```

```diff
--- a/backend/app/api/v1/internal_mock.py
+++ b/backend/app/api/v1/internal_mock.py
+# 所有 /internal 请求校验 X-Internal-Secret（含 dev 默认 secret）
```

> v0.3 建议「无 secret 不挂载 router」已废弃，见 §12.2.3。

---

#### H-4 Agent.engine 默认值与产品战略不一致

- **位置**：`backend/app/models/agent.py` L64；`api/v1/agents.py` L171 / L309 / L499
- **问题**：ORM 默认 `langgraph`；DSL/from-dsl 默认 `hermes`；API create 又用 `langgraph`。
- **影响**：新建 Agent 易走错引擎。
- **修复建议**：ORM 与 API 默认统一为 `hermes`；LangGraph 标注 deprecated。

```diff
--- a/backend/app/models/agent.py
+++ b/backend/app/models/agent.py
-    engine = Column(String(16), nullable=False, default="langgraph")
+    engine = Column(String(16), nullable=False, default="hermes")
```

---

#### H-5 Celery 中 `http_request` 仍为 mock

- **位置**：`workflow_tasks.py` L371–375 vs `node_executors` 真实 HTTP
- **影响**：生产工作流 HTTP 节点返回假数据。
- **修复建议**：随 C-1 统一走 `node_executors`。

---

#### H-6 Framework 工具仅 Hermes 路径可用

- **位置**：`executor._react_loop` 拦截 vs `node_executors.execute_tool_node` 直调 `run_tool`
- **影响**：工作流 tool 节点无法触发 `clarify` / `delegate_task` 等 framework 能力。
- **修复建议**：定义 `FrameworkToolRegistry`，在 `run_tool` 前统一 dispatch。

---

### 4.3 🟡 Medium

#### M-1 内网白名单 RFC1918 硬编码

- **位置**：`context_tools.py` L18–23；`builtin.py`；`kb_seed.py`
- **影响**：外网/多租户无法配置不同白名单策略。
- **修复建议**：`SystemConfig.security.whitelist_cidrs` + `settings.WHITELIST_CIDRS` fallback。

```diff
--- a/backend/app/api/v1/system_config.py
+++ b/backend/app/api/v1/system_config.py
+    "security.whitelist_cidrs": {
+        "value": "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
+        "description": "内网白名单 CIDR（逗号分隔）",
+    },
+    "security.deploy_mode": {
+        "value": "intranet",
+        "description": "部署模式：intranet | extranet",
+    },
```

```diff
--- a/backend/app/tools/context_tools.py
+++ b/backend/app/tools/context_tools.py
+def load_whitelist_networks() -> list:
+    from app.config import settings
+    raw = getattr(settings, "WHITELIST_CIDRS", "") or "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
+    return [ipaddress.ip_network(c.strip()) for c in raw.split(",") if c.strip()]
```

---

#### M-2 服务 URL 硬编码

- **位置**：`workflow/agent_client.py` L27；`workflow/ban_client.py` L20；`tools/security_tools.py`；`.env.example` L48
- **修复建议**：迁入 `config.py` 的 `ServiceEndpoints` 分组，支持 SystemConfig 热更新。

```diff
--- a/backend/app/config.py
+++ b/backend/app/config.py
+    BAN_AGENT_BASE_URL: str = "http://127.0.0.1:8001/api/v1/internal"
+    BAN_TOOL_BASE_URL: str = "http://127.0.0.1:8001/api/v1/internal"
+    OUTBOUND_HTTP_PROXY: str = ""
+    OUTBOUND_NO_PROXY: str = "localhost,127.0.0.1"
```

---

#### M-3 ToolCatalog 未完全贯通

- **位置**：`core/tools/catalog.py` vs `core/tool_templates.py`（第三份定义）
- **修复建议**：废弃 `TOOL_TEMPLATES`，模板 API 由 `ToolCatalog.preset_definitions()` 生成；增加 `tool_provider` 字段（builtin/device/mcp/http/user）。

---

#### M-4 CORS 双源未联动

- **位置**：`config.py` CORS_ORIGINS；`system_config.py` cors_origins；`main.py` 仅读 env
- **修复建议**：启动时 SystemConfig 覆盖 middleware，或 UI 明确「仅 env 生效」。

---

#### M-5 `search_assets` 双轨挂载

- **位置**：`decision.py` / `tool_engine.py` 中 `if name == "search_assets": continue`
- **修复建议**：勾选工具即挂载；`enabled_asset_types` 仅作 scope 过滤。

```diff
--- a/backend/app/agent/hermes/tool_engine.py
+++ b/backend/app/agent/hermes/tool_engine.py
-            if name == "search_assets":
-                continue
+            if name == "search_assets":
+                scope = agent.enabled_asset_types or None
+                entry = self._build_asset_tool(scope)
+                ...
```

（需与 decision.py 同步，删除重复路径。）

---

#### M-6 无 Alembic，轻量迁移散落

- **位置**：`core/security.py` `run_lightweight_migrations`
- **修复建议**：引入 Alembic；lightweight 仅 bootstrap。

---

#### M-7 OpenAPI 工具解析在 API 层

- **位置**：`api/v1/tools_manage.py`
- **修复建议**：下沉 `core/openapi_tools.py`，Hermes/LangGraph/工作流共用。

---

### 4.4 🔵 Low

#### L-1 前端 API 客户端缺部署模式感知

- **位置**：`frontend/src/api/client.js`（相对路径 `/api/v1` 设计正确 ✅）
- **建议**：读取 `system-config` 的 `deploy_mode`，外网隐藏 mock/security-tools 入口。

---

#### L-2 Nginx 外网需补 rate limit

- **位置**：`deploy/nginx.conf`
- **建议**：`limit_req_zone` 针对 `/api/v1/auth/*`、`/webhook/*`；SSE `/chat` 显式 `proxy_buffering off`。

---

#### L-3 LangGraph 路径标注 deprecated

- **位置**：`app/agent/graph.py` 硬编码 SOC SYSTEM_PROMPT
- **建议**：保留 Mock/降级，UI 禁止新建 langgraph Agent。

---

#### L-4 测试脚本 localhost 耦合

- **位置**：`backend/tests/*`、`verify_*.py`
- **建议**：`BASE_URL` 环境变量化。

---

#### L-5 `tool_search` 默认隐藏关键工具

- **位置**：`hermes/tool_search.py` + Agent `tool_configs`
- **建议**：研判/封禁模板默认 `tool_search=off`（对齐 V2.1）。

---

### 4.5 🟡 Medium（声明式与高解耦专项）

#### M-8 业务逻辑内联在 builtin seed 与 ORM 字段中

- **位置**：`core/tools/definitions/builtin.py`（千行级内联 code）；Agent/Workflow 全量 JSON 存 DB
- **问题**：与 Flocks 声明式 YAML 相反；每增设备/场景需改 Python 字符串并 seed。
- **影响**：内网多厂商并行对接时发版频率高；无法「只交付插件包」。
- **修复建议**：builtin 仅保留薄引用；设备/场景迁入 `plugins/` 或 `ToolSpec` manifest。

```diff
--- a/backend/app/core/tools/definitions/builtin.py
+++ b/backend/app/core/tools/definitions/builtin.py
@@
-        "code": (
-            "import ipaddress\n"
-            "async def check_whitelist(ip: str):\n"
-            "    ... 内联 RFC1918 ...\n"
-        ),
+        "code": "from app.tools.context_tools import check_whitelist\n",
+        "tool_source": "builtin",
+        "spec_version": 1,
```

---

#### M-9 缺少 PluginRegistry / ExtensionPoint 统一加载

- **位置**：无；Flocks 参考 `flocks/plugin/loader.py`
- **问题**：工具/工作流/技能/Agent 模板各自 seed，无扫描目录、无版本目录、无热加载。
- **影响**：扩展点分散，第三方或另一团队无法独立交付包。
- **修复建议**：新增 `app/platform/plugin_loader.py`。

```python
# app/platform/plugin_loader.py（新建示意）
class ExtensionPoint(str, Enum):
    TOOLS = "tools"
    WORKFLOWS = "workflows"
    SKILLS = "skills"
    AGENTS = "agents"

class PluginLoader:
    def __init__(self, root: Path): ...
    def scan(self) -> dict[ExtensionPoint, list[dict]]: ...
    def register_into_catalog(self, catalog: ToolCatalog) -> None: ...
```

内网默认目录：`/opt/soar/plugins/` 或 `{SOAR_DATA_DIR}/plugins/`（不入 git，可挂载）。

---

#### M-10 Provider 凭证与端点未声明化

- **位置**：设备 API Key 散落 env；Flocks 用 `_provider.yaml` 的 `credential_fields` + secret store
- **修复建议**：`ToolProviderManifest` + SystemConfig/加密字段；UI「设备接入」页只读 manifest 渲染表单。

```yaml
# plugins/tools/device/tdp_v3_3_10/_provider.yaml（SOAR 目标，对齐 Flocks）
name: TDP
service_id: tdp_api
version: "3.3.10"
auth:
  type: hmac_sha256
credential_fields:
  - { key: api_key, storage: secret, secret_id: tdp_api_key }
  - { key: base_url, storage: config, default: "https://{secret:tdp_host}" }
```

---

#### M-11 工作流 Spec 与 React Flow 画布双写

- **位置**：`Workflow.graph_config`（UI 画布 JSON）vs 无独立 `WorkflowSpec` 导出
- **问题**：Flocks 的 `workflow.json` 可 Git 管理、可 CI 测；SOAR 画布 JSON 难 diff、难包化。
- **修复建议**：`graph_config` 作为 UI 视图；增加 `spec_yaml` / `spec_version` 字段或 sidecar 文件；导入导出走同一 Spec  schema。

```diff
--- a/backend/app/models/workflow.py
+++ b/backend/app/models/workflow.py
+    spec_version = Column(String(16), nullable=True)
+    spec_source = Column(String(32), nullable=True)  # ui | plugin | dsl
+    plugin_id = Column(String(128), nullable=True)   # 如 tdp_alert_triage
```

---

#### M-12 Hermes 与 API/Workflow 层交叉 import

- **位置**：`executor` → `agents._create_llm`；`tools_manage` OpenAPI 解析；`builder._check_permission` 复制权限
- **问题**：违反 L2/L3 分层，阻碍「只换 L1 Provider 不动引擎」。
- **修复建议**：依赖倒置 — 引擎只依赖 `platform/runtime` 与 `platform/registry` 接口。

```python
# app/platform/runtime.py
class AgentRuntime(Protocol):
    async def invoke_tool(self, name: str, args: dict, ctx: RunContext) -> ToolResult: ...
    async def invoke_agent(self, agent_id: int, input: str, ctx: RunContext) -> AgentResult: ...
```

---

## 5. 工具化调用与复用专项

### 5.1 统一对外运行时（外网/SDK 预留）

建议新增模块 `app/platform/tool_runtime.py`：

```python
async def invoke_tool(
    name: str,
    args: dict,
    *,
    agent_id: int | None,
    user_id: int,
    trace_id: str,
) -> ToolResult: ...

async def invoke_agent(
    agent_id: int,
    input: str,
    *,
    channel: str,
    stream: bool = False,
): ...
```

Playground、工作流节点、Webhook、未来 OpenAPI SDK **共用此层**。

### 5.2 设备工具插件化（对齐 Flocks 声明式 Provider）

| Flocks | SOAR 目标 |
|--------|-----------|
| `plugins/tools/device/tdp_v3_3_10/_provider.yaml` | `ToolProviderManifest`（auth/credential_fields/version） |
| `tdp_*.yaml` + `inputSchema` | `ToolSpec` → 编译为 http/code 工具，**不写进 builtin.py** |
| `tdp.handler.py`（HMAC 签名） | `ProviderHandler` 协议，L1 可测可换 |
| `tool.run_safe('tdp_log_search', ...)` | `invoke_tool('tdp_log_search', {...}, ctx)` |
| 目录 `tdp_v3_3_10` 版本并存 | `Tool.provider_version` + 迁移脚本 |

**解耦要点**：Handler 只负责「签名 + HTTP 拼装」；业务语义（白名单跳过、IOC 去重）放在 **WorkflowSpec 节点** 或 **Skill**，不塞进 Handler。

### 5.3 场景工作流包（借鉴 `tdp_alert_triage`）

SOAR 封禁/研判链路与 Flocks `tdp_alert_triage` 同构，建议首批插件包：

| 插件 id | 节点模式 | SOAR 映射 |
|---------|----------|-----------|
| `tdp_alert_triage` | receive → 并行(tool/llm) → join → report | 告警解析 + 情报 + LLM 研判 + 报告 |
| `ip_ban_decision` | agent + verification + ban_executor | 现有 ban 工作流 Spec 化 |
| `asset_lookup` | tool 链 | search_assets + get_asset_info |

交付方式：开发者提交 `plugins/workflows/{id}/` → `PluginLoader` 注册 → 管理端「导入场景包」→ 可选发布为模板（V2.3）。

### 5.4 Skill 包（借鉴 Flocks `SKILL.md`）

| Flocks | SOAR 目标 |
|--------|-----------|
| `SKILL.md` + YAML frontmatter | `SkillPack`（md + metadata.json） |
| `flocks_skills find/install` | `POST /skills/import-pack` + 依赖检查 |
| 设备 skill（tdp/skyeye/qingteng） | 强制路由：有 skill 时禁止 bypass 直调 device tools |

与 `docs/skill-package-plan.md` 合并实施。

### 5.5 ToolCatalog 与 seed 收敛

- 单一真源：`ToolCatalog.preset_definitions()`
- 启动：`ensure_preset_tools()`（已有）
- 删除：builtin 内联重复 Python 字符串逻辑 → 调用 `context_tools` 或加载声明式 Spec
- **PluginLoader 启动时合并**：`ToolCatalog.preset_definitions()` ∪ `plugins/**/ToolSpec`

### 5.6 Agent 声明式 Spec（借鉴 `agent.yaml`）

```yaml
# plugins/agents/ip_risk_analyst/agent.yaml（目标）
name: ip_risk_analyst
engine: hermes
model_ref: default_analyst
enabled_tools: [check_whitelist, get_threat_intel, search_assets]
enabled_skills: [ip_ban_sop_v2]
tool_configs:
  tool_search: "off"
delegatable: false
prompt_ref: prompts/system.md
```

`POST /agents/from-dsl` 已存在；扩展为接受 **目录包 zip**（agent.yaml + prompts + 引用的 workflow/tool 清单）。

---

## 6. 与 V2 产品方案的衔接

| 基座优化项 | 支撑 V2 能力 |
|------------|-------------|
| ToolRegistryBuilder + 来源打标 | V2.1 工具分组/内置打标 |
| invoke_agent 统一入口 | V2.2 极简向导与 Playground 一致 |
| DSL + ToolCatalog + **AgentSpec/WorkflowSpec 包** | V2.3 开发者代码视图与模板发布 |
| 工作流 execute_node 统一 + **WorkflowSpec 导入** | V2.4 AI 生成草稿 → Celery 发布一致 |
| DeviceProvider + SkillPack + PluginLoader | V2.5 五模块双入口齐平 |
| **声明式 Provider（内网多设备）** | 运营无感扩展厂商版本，开发者只交付插件目录 |

**原则**：V2 做界面与交付闭环；本方案做运行时与工具基座 + **声明式扩展层**；**不动 Hermes 核心能力文件的业务逻辑**，只做收敛、抽象与包化。

---

## 7. 分阶段落地路线

> **v0.4 说明**：本节为能力 backlog；**实际实施顺序以 §12.4（P0～P2）为准**，勿将 Phase A～F 作为同期全部交付承诺。

### Phase A — 行为一致（2～3 周，必做）

| 序号 | 任务 | 对应条目 | 验收 |
|------|------|----------|------|
| A1 | Celery 复用 `node_executors` | C-1, H-5 | 生产封禁流走 Hermes guardrails |
| A2 | `/test/stream` 按 engine 分流 | C-2 | Playground 与 /chat 行为一致 |
| A3 | 修复 `_create_llm` + LLM 工厂下沉 | C-3 | 无 DB LLMConfig 时 Hermes 可启动 |
| A4 | `check_whitelist` schema 统一 | H-1 | verification 封禁前校验稳定 |
| A5 | `Agent.engine` 默认 hermes | H-4 | 新建 Agent 默认 Hermes |

### Phase S — 安全与合规（内网生命线，P0，与 Phase A 并行或紧随）

> **v0.4**：拆为 **S-lite**（纳入 P1 基座）与 **S-full**（独立立项/演进项）。下表保留 backlog；Reviewer Agent、RollbackLedger、Append-only 重构、容器全量隔离归 **S-full**，见 §12.2.5。

| 序号 | 任务 | 对应验收（§1.1） | 落点 |
|------|------|------------------|------|
| S1 | **统一网络出口策略层（Egress）**：所有出站（LLM/HTTP 工具/code 工具的 httpx/厂商）经统一出口，默认全禁、按目标地址+端口白名单放行 | 网络出口控制（网络层） | `app/platform/egress.py` + `Tool.network_policy` |
| S2 | **code 工具出网约束**：注入的 `httpx` 改为受限客户端，域名白名单/无出站开关，后门外置 | 网络出口控制 | `core/tool_runner.py:674` |
| S3 | **容器级执行隔离**：高危/写操作工具改子进程或容器运行（禁止访问宿主 FS），`docker.sock` 相关挂载收敛 | 容器级执行隔离 | `core/tool_sandbox.py` + `deploy/` |
| S4 | **Policy-as-Code + Reviewer Agent**：独立审查 Agent/规则引擎决定动作是否可执行，不依赖 LLM Prompt | Policy-as-Code | `app/platform/policy.py` + `app/agent/reviewer.py` |
| S5 | **动作分级 + 回滚账本**：处置分级（1-10），高等级人工审批；执行前记录回滚命令，形成 Append-only 回滚账本 | 分级审批 + 回滚账本 | `approvals` 扩展 + `RollbackLedger` 表 |
| S6 | **Append-only 审计**：审计日志仅追加 + 结构化 Finding/Evidence 引用，覆盖工具/LLM/RAG | Append-only 审计 | `core/audit.py` 重构 + 证据表 |

### Phase B — 工具基座（4～6 周）

| 序号 | 任务 | 对应条目 | 验收 |
|------|------|----------|------|
| B1 | 实现 `ToolRegistryBuilder` | H-2 | 新增工具类型只改一处 |
| B2 | `invoke_tool` / `invoke_agent` 运行时 | §5.1 | 三入口共用 |
| B3 | ToolCatalog 贯通，废弃 TOOL_TEMPLATES | M-3 | 模板 API 单一来源 |
| B4 | FrameworkToolRegistry | H-6 | 工作流 tool 节点可调 framework |
| B5 | OpenAPI 解析下沉 | M-7 | Hermes/LangGraph 共用 |

### Phase C — 外网预留（内网低优先，留口子演进项）

| 序号 | 任务 | 对应条目 | 验收 |
|------|------|----------|------|
| C1 | DEPLOY_MODE + INTERNAL_API_SECRET | H-3 | extranet 无 /internal |
| C2 | 白名单 CIDR 可配置 | M-1 | 多客户不同策略 |
| C3 | ServiceEndpoints 配置化 | M-2 | 无 127.0.0.1 硬编码 |
| C4 | CORS SystemConfig 联动 | M-4 | 改域名无需改代码 |
| C5 | Nginx rate limit + SSE | L-2 | 外网扫描/滥用防护 |
| C6 | Alembic 迁移 | M-6 | 滚动升级可预期 |

### Phase D — 产品收尾（与 V2.4/V2.5 并行）

- `search_assets` 单轨（M-5）
- `tool_search` 模板默认 off（L-5）
- LangGraph deprecated（L-3）
- 前端 deploy_mode 感知（L-1）

### Phase E — 声明式插件与高解耦（6～10 周，与 Phase B/C 可部分并行）

| 序号 | 任务 | 对应条目 | 验收 |
|------|------|----------|------|
| E1 | `PluginLoader` + ExtensionPoint | M-9 | 启动扫描 `plugins/tools` 注册到 Catalog |
| E2 | `ToolProviderManifest` + 凭证 UI | M-10 | TDP 接入不改 Python seed |
| E3 | 首批设备包 `tdp_v3_3_10` 从 Flocks 结构迁移 | §5.2, M-8 | 工具 YAML + handler，无 builtin 内联 |
| E4 | `WorkflowSpec` 导入 + `plugin_id` | M-11 | `tdp_alert_triage` 包导入可执行 |
| E5 | `SkillPack` 导入 | §5.4 | SKILL.md 包上线 |
| E6 | `AgentSpec` 目录包 + zip 导入 | §5.6 | 与 V2.3 DSL 互通 |
| E7 | 分层 lint：禁止 Hermes import 设备实现 | M-12, §3.3 | CI 规则或 import 测试 |

**内网交付形态**：镜像只含 L2 运行时 + 空 `plugins/`；客户/团队通过 **挂载目录或管理端上传 zip** 扩展，无需重打 backend 镜像。

---
### Phase F — 无状态化与可扩展预留（内网高可用基线，6～8 周）

> **v0.5**：F1 须先做**记忆三处现状梳理**再收敛（见 §12.8.1）；F4/F5 大部分降为**演进项**；F6 本地推理路由见 §12.4 P1，不单列 Phase F6。

> 内网不引入 K8s/HPA/Temporal，但必须以「可横向 + 无状态 + 双副本冗余」为基线，为将来演进留口子。

| 序号 | 任务 | 对应条目 | 验收 |
|------|------|----------|------|
| F1 | **Agent 记忆收敛**：三处现状梳理 → 统一落 `AgentMemory` 表 + Hermes `memory_manager` 接入；废弃 `tool_runner` 全局 `memory.json` | §1.1 记忆+RAG、§12.8.1 | 多用户/多副本无串扰 |
| F2 | **`_tool_cache` 版本化/集中失效**：Redis 广播失效，消除多副本旧编译缓存 | §1.1 可扩展 | 改工具即时全员生效 |
| F3 | **`ws_manager` 外置**：WebSocket 连接注册表 + 进度推送走 Redis pub/sub | §1.1 高可用 | 副本重启/切换不丢推送 |
| F4 | **部署冗余**：backend 双副本 + 健康/就绪探针 + Celery 幂等/`acks_late` + Postgres 主从/备份恢复演练 | §1.1 高可用 | 单组件故障不整体失明 |
| F5 | **全链路可观测**：接入 OpenTelemetry（span 贯穿 agent/tool/LLM）+ 结构化日志关联 `execution_id` | §1.1 可观测 | 跨副本可排障 |

> F6「本地推理 + 模型路由」已提升至 **§12.4 P1** 独立一行（内网刚需，避免被工具化改造淹没）；Phase F 表内不再重复列出。

**演进项（暂缓/可选，不作为内网验收门槛）**：K8s 工作负载化与 HPA、Temporal 持久化工作流引擎、A2A 协议、MCP 生态、多租户配额调度。这些在需求明确后再评估，不在本期内网基座落地。

---

## 8. 风险与约束

| 风险 | 缓解 |
|------|------|
| Celery async 适配 | 先写 `execute_node_sync` 集成测试，覆盖封禁 E2E |
| 白名单 schema 变更 | 同步改 agent_tools、builtin seed、前端工具说明 |
| 外网关闭 mock | 提供真实设备/情报 Provider 或 staging 环境 |
| GPL/AGPL 外网组件 | 参考 `open-source-reference-survey.md` 许可表 |
| ARM64 生产 | 保持 git 同步源码、服务器构建镜像纪律（见 README） |
| 插件包恶意 code | ToolSpec 编译前 `validate_tool_code` + 签名校验 + 仅 admin 可上传 |
| 声明式与 UI 画布漂移 | WorkflowSpec 为 source of truth；画布为视图，导入导出双向同步 |
| Flocks 代码直接拷贝 | 仅借鉴 **Spec  schema 与目录约定**；运行时仍走 SOAR Hermes + RBAC |

---

## 9. 验收标准（基座优化完成定义）

1. **引擎一致**：同一 Agent 在 Playground、/chat、工作流 Celery、工作流 test-run 四条路径行为一致（Hermes）。
2. **工具单一工厂**：新增 code/http/openapi/**device** 工具类型仅改 `ToolRegistryBuilder` + ToolSpec。
3. **工具返回值统一**：安全类工具（白名单/情报/资产）schema 有文档化 JSON Schema。
4. **外网开关**：`DEPLOY_MODE=extranet` 下 mock 关闭、internal 鉴权强制、CIDR 可配。
5. **可观测**：每次 tool/agent 调用有 `trace_id`，审计日志可关联 execution_id。
6. **声明式扩展**：新增 TDP 工具版本仅增 `plugins/tools/device/tdp_x/` 目录，**不改** `hermes/` 与 `builtin.py`。
7. **高解耦**：Hermes 依赖图无 `app.tools.device.*` / `app.api.v1.agents._create_llm` 等跨层 import（M-12）。
8. **场景包化**：至少 1 条研判工作流（如 `tdp_alert_triage`）以 WorkflowSpec 包导入并 Celery 执行通过。

**内网基座专有验收（对应 §1.1，Phase S/F）**：
9. **网络出口受控**：`DEPLOY_MODE=intranet` 下默认全禁出站；任一 Tool/LLM 出站均在 `egress` 白名单内，无不受控外联。
10. **高危动作隔离**：封禁/设备动作等写工具在隔离容器/子进程执行，无宿主 FS 访问；`docker.sock` 挂载已收敛。
11. **分级审批 + 回滚账本**：处置分级可配，高等级动作必须人工审批；每次执行前生成回滚命令并入 Append-only 账本。
12. **Append-only 审计**：工具/LLM/RAG 调用均入仅追加审计，含结构化 Finding 与 Evidence 引用；不可篡改。
13. **无状态化**：Agent 记忆、WebSocket 连接、工具缓存均外置（DB/Redis），后端可与 Worker 多副本共享，无单副本依赖。

---

## 10. 附录：关键符号速查

```
引擎入口
  HermesAgentExecutor.run()           app/agent/hermes/executor.py
  run_agent_decision()                app/agent/decision.py
  execute_ai_agent()                  app/core/node_executors.py

工具加载
  load_tool_function() / run_tool()   app/core/tool_runner.py
  HermesToolEngine.execute_tool_calls app/agent/hermes/tool_engine.py
  ToolCatalog.preset_definitions()    app/core/tools/catalog.py

工作流
  workflow_runner / execute_node      app/core/workflow_runner.py
  run_workflow_task (Celery)          app/tasks/workflow_tasks.py  ← Phase A 对齐

配置
  Settings                            app/config.py
  SystemConfig DEFAULT_CONFIGS        app/api/v1/system_config.py

声明式扩展（目标）
  PluginLoader.scan()                 app/platform/plugin_loader.py
  ToolProviderManifest                plugins/tools/device/*/_provider.yaml
  WorkflowSpec                        plugins/workflows/*/workflow.json
  SkillPack                           plugins/skills/*/SKILL.md
  invoke_tool / invoke_agent          app/platform/runtime.py
```

---

## 11. 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-09-22 | v0.1 | 初稿：全库架构评审 + 内网/外网预留 + 工具化路线 |
| 2026-09-22 | v0.2 | 增补 Flocks 声明式借鉴、五层解耦模型、Phase E 插件路线、M-8～M-12 |
| 2026-09-22 | v0.3 | 明确纯内网定位；新增 §1.1 四维验收框架与内网适配裁剪；新增 Phase S（安全合规）、Phase F（无状态化/可扩展预留）；Phase C 降为内网低优先演进项；验收补内网专有项 9～13 |
| 2026-09-22 | v0.4 | 新增 §12 评审意见；修正工作流三路径认知、C-1/H-3/Phase S/F 范围裁剪、P0～P2 优先级 |
| 2026-09-22 | v0.5 | Codex 二次评审反馈写入 §12.8（四项细化） |
| 2026-09-22 | v0.6 | §13 独立审视：否定「整体定稿」；压缩 P0、修正记忆/本地模型表述；§13.2 为唯一执行清单 |
| 2026-09-22 | v0.7 | §13.2 封禁契约对齐 v1.1（ban_risk_analyze）；§16 终审结论 |

---

## 12. 评审意见与 v0.4 修订要点

> 评审日期：2026-09-22（v0.4 修订）；**2026-09-22 Codex 二次评审（v0.5）**  
> 评审对象：本文 v0.3 → v0.4 修订稿  
> v0.4 结论：**方向正确，实施前须按 §12.2 修正 P0 范围与 Diff。**  
> **v0.5 Codex 结论：整体通过**，核心论断经代码核验属实，**不需要再大手术**；§12.8 四项为可选细化（建议采纳 1、2）。

### 12.1 总体评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 问题诊断（双引擎/工具多源） | ⭐⭐⭐⭐ | 核心矛盾准确 |
| 优先级（Phase A） | ⭐⭐⭐⭐ | C-2/C-3/H-1/H-4 值得先做 |
| 与真实生产链路对齐 | ⭐⭐ | 封禁流路径描述有误（见 12.2.1） |
| Diff 可落地性 | ⭐⭐ | C-1 整函数替换不可直接应用 |
| Phase S/F 范围 | ⭐⭐ | 偏独立安全/平台项目，超出「基座优化」 |
| Flocks 声明式借鉴 | ⭐⭐⭐⭐ | 方向对，Phase E 节奏偏激进 |
| 内网定位（§1.1） | ⭐⭐⭐⭐ | 较 v0.1 更贴合；Phase C 与 §1.1 仍有部分重复 |

### 12.2 必须修正的错误与偏差

#### 12.2.1 🔴 工作流三路径未区分（v0.3 最大偏差）

v0.3 将「Celery 不走 Hermes」等价为「封禁/告警生产无 guardrails」，**不成立**。代码中存在三条独立路径：

```
路径 A — 封禁专用流（生产主链路，优先级最高）
  app/workflow/engine.py
    → agent_analyze（workflow/nodes/agent_analyze.py）
    → agent_client.analyze_ip_risk（HTTP POST）
    → /api/v1/internal/agent/ip-risk-analyze（internal_mock）
  ❌ 不经过 HermesAgentExecutor
  ❌ 不经过 run_agent_decision（LangGraph）

路径 B — 通用 Celery 工作流
  app/tasks/workflow_tasks.py → _execute_node
    → ai_agent 节点 → run_agent_decision(payload)
  ✅ v0.3 C-1 主要描述此路径

路径 C — test-run / 同步编排
  app/core/workflow_runner.py → node_executors.execute_ai_agent
  ✅ 已支持 engine=hermes（需 agent_id）
```

**v0.4 修订**：

- C-1 标题改为「通用 Celery 与 node_executors 对齐」，**不得**再写「修复封禁流 Hermes」。
- **新增 P0 项 P0-0**：封禁路径 A — `agent_analyze` / `agent_client` 改为调用 `invoke_agent`（指定研判 Agent），逐步废弃对 `/internal` mock 的结构化 JSON 契约依赖（mock 仅保留 dev/staging）。
- §2.1 运行时图须替换为上述三路径。

#### 12.2.2 🔴 C-1 Diff 不可直接落地

原 Diff 用 `asyncio.run(execute_node(...))` 整体替换 `_execute_node`，存在：

| 问题 | 说明 |
|------|------|
| 签名不一致 | `execute_node(node_type, node_data, input_data, ctx, log)` vs `_execute_node(..., context, payload, log)` |
| 编排上下文 | Celery BFS、ExecutionTrace、审批暂停、变量解析在 `workflow_tasks` 外层，不能删 |
| 回退仍存在 | `execute_ai_agent` 无 `agent_id` 时仍回退 `run_agent_decision`（`node_executors.py` L226-243） |
| 输出形状 | 旧 `ai_agent` 写 `ctx["decision"]` 供 `block_ip`；Hermes 路径返回 `response`，下游节点需对齐 |

**v0.4 修订 Diff 方向**（示意，非整文件替换）：

```python
# app/tasks/workflow_tasks.py — 新增适配层，而非删除 _execute_node
async def _execute_node_async(node_type, node_data, context, payload, log):
    node_input = _build_node_input(node_type, node_data, context, payload)
    if node_type in NODE_EXECUTORS:
        return await execute_node(node_type, node_data, node_input, context, log)
    return _execute_node_legacy(node_type, node_data, context, payload, log)

def _execute_node(...):
    return asyncio.run(_execute_node_async(...))
```

落地前须：**存量工作流盘点**（哪些节点有 `agent_id`、哪些仍走旧 SOC JSON 决策）。

#### 12.2.3 🟠 H-3 internal mock 方案在内网会误伤

v0.3 建议 `INTERNAL_API_SECRET` 为空则不挂载 mock → **封禁路径 A 立即不可用**（当前默认依赖 `/internal`）。

**v0.4 修订**：

- 内网：`/internal` **必须鉴权**（`X-Internal-Secret` 或 mTLS），但 dev 环境提供默认 secret，**禁止**「无 secret 即不挂载」。
- 生产：mock 路由与真实研判 Agent 二选一；封禁 P0-0 完成后 mock 可降为仅 dev。

#### 12.2.4 🟠 C-2 Diff 过于粗糙

`test/stream` 直接 `return await chat_agent(..., current_user=None)` 可能破坏权限、审计用户、`conversation` 渠道校验。

**v0.4 修订**：提取 `_hermes_sse_stream(agent, body, db, user)`，与 `/chat` 共用，保留 test 专用 override 与当前用户上下文。

#### 12.2.5 🟠 Phase S 超出基座范围且与 Hermes 重叠

| v0.3 项 | 问题 | v0.4 处置 |
|---------|------|-----------|
| S4 Policy-as-Code + Reviewer Agent | 与 Hermes `guardrails` / `verification` 职责重叠 | 移至 **S-full 独立立项** |
| S3 容器级隔离所有写工具 | ARM64 + compose 成本高；现有 `tool_sandbox.py` 为 AST 方案 | S-lite：加强沙箱；S-full：容器隔离 |
| S6 Append-only 审计重构 | 工作量大 | S-lite：结构化字段扩展；S-full：账本重构 |
| S1 默认全禁出站 | 内网 LLM/设备/情报仍需内网网段通信 | 改为 **分域 egress 白名单**，非零出站 |

**Phase S 拆分**：

- **S-lite（纳入基座 P1）**：internal 鉴权、egress 配置化、写工具与现有 verification 对齐。  
- **S-full（演进项/独立 PRD）**：Reviewer Agent、RollbackLedger、Append-only 重构、容器隔离。

#### 12.2.6 🟠 Phase F 与现状不符或过重

| v0.3 项 | 偏差 | v0.4 处置 |
|---------|------|-----------|
| F1 memory.json → DB | 已有 `AgentMemory` 表，但 **三处并存且均未打通**（§12.8.1） | 梳理三处 → 收敛到表 + Hermes memory_manager |
| F4 双副本 + PG 主从 | 运维大改，非当前基座必做 | 降为演进项 |
| F5 OpenTelemetry | 有价值但重 | P1 先做 trace_id 贯通；OTel 演进项 |
| F6 Ollama/vLLM 路由 | 与 Phase B / `llm_helper` 重叠 | 并入 Phase B 子项 |

#### 12.2.7 🟡 Flocks 借鉴略理想化

- Flocks `workflow.json` 含大量 **python 节点内联 code**，并非纯声明式；SOAR React Flow + DB 在运营可视化上仍有价值。  
- 「镜像只含运行时 + 空 plugins/」与当前 **52 工具 seed 进 DB** 冲突，须写清 **DB → 插件包** 迁移策略后再做 Phase E。  
- Phase E 6～10 周与 Phase B 并行偏激进 → **E1～E3（Tool Provider）优先**，WorkflowSpec 包后置。

### 12.3 文档遗漏项（v0.4 补充，v0.5 强化）

1. **封禁流与 Hermes 打通**（`agent_analyze` / `agent_client`）— 优先级高于 Celery ai_agent alone。  
2. **两套工作流体系**：通用 React Flow（`workflow_tasks`）vs 封禁专用（`workflow/engine.py` + `NODE_REGISTRY`）— 与 V2「触发规则混淆」同源，基座须单列治理。  
3. **`execute_ai_agent` 无 agent_id 回退** — 存量工作流迁移清单与截止时间。  
4. **工作流 Hermes 执行主体（P0-0 必做，见 §12.8.2）**：`node_executors._run_hermes_agent` 使用 `db.query(User).first()`（约 L288）作为 system user。多用户下记忆、`current_user_id`、文件归属会串到同一用户；**封禁接 Hermes 前必须**绑定执行主体（Agent 所有者 / 配置 `WORKFLOW_SYSTEM_USER_ID` / 实例触发人）。  
5. **收敛引擎 ≠ 卸载 langgraph 包** — Hermes 可能仍依赖 langchain-core Message/LLM 封装。

### 12.4 v0.4 修正后优先级（替代 §7 全 Phase 一口气实施）

```
P0（2～3 周）— 底座一致性 + 封禁主链路
  P0-0  封禁路径 A：agent_analyze → invoke_agent（Hermes 研判 Agent）
        + 工作流执行主体（禁止 User.first()；见 §12.8.2）
  P0-1  Celery ai_agent 适配 node_executors（有 agent_id 的通用流）
  P0-2  /test/stream 与 /chat Hermes 对齐（共用 sse 生成器）
  P0-3  修复 _create_llm import + LLM 工厂下沉
  P0-4  check_whitelist schema 统一 + engine 默认 hermes
  P0-5  internal 鉴权（不破坏 dev 默认 secret）

P1（4～6 周）— 扩展性 + 内网智能核心
  ToolRegistryBuilder、invoke_tool/agent、ToolCatalog 贯通、OpenAPI 下沉
  本地推理节点 + 模型路由层（Ollama/vLLM，内网刚需，独立一行不淹没）
  S-lite：egress 分域白名单、写工具与 verification 对齐
  F1 记忆三处梳理与收敛（见 §12.8.1，可与 P1 并行）

P2（按需）— 声明式
  ToolProviderManifest + 首个 TDP 插件包（E1～E3）
  WorkflowSpec / SkillPack 包化（E4～E6 后置）

演进项（单独立项，不作为内网基座验收门槛）
  Phase S-full、Phase F 双副本/OTel、K8s/Temporal、MCP 全家桶
```

### 12.5 v0.4 验收标准增补

在 §9 基础上增加/调整：

| # | 条目 | 说明 |
|---|------|------|
| 0 | **封禁主链路 Hermes** | `workflow/engine.py` 研判节点经 `invoke_agent`，非仅 HTTP mock（mock 限 dev） |
| 1～8 | 保留 §9 原 1～8 | 引擎一致、工具工厂等 |
| 9～13 | §9 内网项 | **降级**：9 egress 分域白名单（非零出站）；10～13 中 10/11 进 S-lite，12/13 进 S-full 或演进项 |

### 12.6 对 v0.3 条目的处置一览

| 原条目 | v0.4 处置 |
|--------|-----------|
| C-1 | 保留问题，**重写 Diff 与影响描述**（见 12.2.1、12.2.2） |
| C-2、C-3 | 保留，C-2 改实现方式 |
| H-1～H-6 | 保留，优先级 P0/P1 |
| H-3 | **修订**（见 12.2.3） |
| M-1～M-12 | 保留，节奏后置 P1/P2 |
| Phase S | **拆 S-lite / S-full** |
| Phase F | **大部分降为演进项** |
| Phase E | **缩 Scope**：E1～E3 优先 |
| Phase C | 维持内网低优先 ✅ |

### 12.7 评审结论（给决策用）

| 问题 | 结论 |
|------|------|
| 方案是否值得做？ | **值得**，Hermes 收敛 + 工具统一方向正确 |
| v0.4 能否原样开干？ | **不能**，须先修正三路径认知与 C-1 Diff |
| Codex v0.5「整体通过」 | **方向对、范围仍过大**；v0.6 以 §13.2 为唯一清单 |
| 最大风险？ | 文档太长导致「全做」；实际应先 MVP 5 项（§13.2） |
| 推荐第一步？ | **invoke_agent + 封禁 agent_client + test/stream 对齐** |

### 12.8 Codex 二次评审（2026-09-22，**供对照，非终审**）

下列 v0.4 关键修正经代码核验**大体属实**；v0.6 对其中 3 项做了降级或语义修正（§13.3）。

| 修正点 | 核验 |
|--------|------|
| 三路径 §12.2.1 | ✅ |
| C-1 不可整函数替换 | ✅ |
| internal mock 内网误伤 | ✅ |
| F1 记忆 | ⚠️ 三处存在，但 ③ 语义不同（§12.8.1） |

#### 12.8.1 🟡 记忆三处并存（Codex 建议；**v0.6 修正语义，见 §13.1.2**）

当前与「记忆」相关的实现分散在三处，**不宜简单写成「memory.json → DB」**：

| # | 位置 | 现状（代码） | 实际用途（需区分） |
|---|------|-------------|-------------------|
| ① | `models/agent_memory.py` | ORM 已有，Hermes 未接 | 对话长期记忆（按 user+agent 分区） |
| ② | `hermes/executor.py` L204 | `memory_manager = None` 占位 | 同上，引擎侧未实现 |
| ③ | `tool_runner.py` L527+ | `uploads/.../memory.json` | **工具代码** `save_agent_memory(key,value)` 的 KV 仓库，语义不同于 ①② |

F1 合理方向：**①② 收敛到 AgentMemory + MemoryManager**；③ 是否合并需产品定夺（工具 KV vs 对话记忆），不可默认一锅炖。

#### 12.8.2 🟡 工作流 Hermes 执行主体（Codex 建议；**v0.6 降级为 P0-0b，见 §13.1.3**）

`User.first()` 确有审计/记忆串扰风险。封禁路径 A 使用 `ban_risk_analyze` + 研判 Agent **`enable_memory=false`** 时，**不必然阻塞 P0-0 功能上线**；`WORKFLOW_SYSTEM_USER_ID` 应在同一迭代内修，而非作为硬门槛夸大。

#### 12.8.3 🟢 本地推理纳入 P1（Codex 建议；**v0.6 降级，见 §13.1.4**）

`provider_templates.py` 已有 **Ollama 模板** + `llm_helper` 支持自定义 `base_url`。内网缺的是「配好 LLMConfig + 健康检查」，不是先做「模型路由层」。路由/降级属 **有多个内网节点之后** 的演进项。

#### 12.8.4 🟢 §1.1 与 §12.4 级别对齐

§1.1 表 Phase S 仍标「P0 必做」；v0.4 已拆 S-lite / S-full。表下已加说明；**执行以 §13.2 为准**。

---

## 13. 独立审视（v0.6 — 实施请以本节为准）

> 不重复 Codex/Cursor 互审。原则：**当前矛盾是双运行时 + 三路径分裂**，不是缺 K8s、Reviewer Agent 或 PluginLoader。

### 13.1 对文档自身的问题

| 问题 | 建议 |
|------|------|
| 1100+ 行、三套优先级（§7 / §12.4 / §1.1） | **只认 §13.2** |
| §1.1 四维像平台 2.0 招标 | 远景归档，不与 MVP 同级 |
| 「整体通过/定稿」 | 改为「方向对、范围须砍」 |
| Phase C 外网、Phase E 插件 | 本季度不做 |
| Phase S-full | 单独立项 |

### 13.2 唯一执行清单（约 2～3 人周 MVP）

> **第 0 步（前置，未就绪则第 1～2 项无对象可接）**：确认并创建「封禁研判 Hermes Agent」。
> 当前封禁走 `/internal` mock；接入 `invoke_agent` 前须先有一个**已发布、可用的 Hermes 研判 Agent**，
> 且约定其 **`output_mode=ban_risk_analyze` 输出契约**（`is_banned` / `action` / `need_confirm` / `ban_plan` 等，
> 见 `LangGraph → Hermes 统一.md` §Step 2 与 §5.5）。**不可**用 `soc_decision`（该契约仅服务路径 B / Celery）。
> 前置依赖 LLMConfig（内网 Ollama/API 已配好，见 §12.8.3）。

> 前置依赖 LLMConfig（内网 Ollama/API 已配好，见 §12.8.3）。若无 Agent 与 LLMConfig，路径 A 无处可接。

| 序 | 任务 | 不做 |
|----|------|------|
| 0 | **确认/创建封禁研判 Hermes Agent**（可发布、`ban_risk_analyze` 契约 + 只读工具 + 已配 LLMConfig） | 不接 mock 直接上线 |
| 1 | `invoke_agent` + **双适配器**（`soc_decision` + `ban_risk_analyze`） | 不删 graph.py |
| 2 | 封禁 `agent_client` → `invoke_agent`（`output_mode=ban_risk_analyze`，**保外层契约**） | 不要求同期改 Celery |
| 3 | `/test/stream` 与 `/chat` 共用 Hermes SSE | — |
| 4 | 修 `_create_llm` + `engine` 默认 hermes | 不卸 langgraph 包 |
| 5 | `check_whitelist` schema 统一 | — |

> **第 2 项契约约束（重要）**：`agent_client.analyze_ip_risk` 现为纯同步 `requests.post`，
> 自带重试（`AGENT_MAX_ATTEMPTS`）、写 `agent_invocation_logs`（`instance_id`/`node_key`）、
> 校验必填字段并抛 `AgentCallError`。改接 `invoke_agent` 时**保留这套外层契约**（同步语义、调用日志、
> 错误语义），只替换内部实现；不可直接替换外层，否则封禁工作流日志/重试/错误传播会断。

**第二波（MVP E2E 后）：** Celery ai_agent 适配层、ToolRegistryBuilder、`WORKFLOW_SYSTEM_USER_ID`、internal 鉴权、S-lite egress。

**本季度明确不做：** Alembic 全量、OTel、PG 主从、PluginLoader、WorkflowSpec 包、Reviewer Agent、物理删 LangGraph。

### 13.3 独立判断（对共识项）

| 论断 | 结论 |
|------|------|
| 三路径 | ✅ 先改路径 A |
| C-1 不可整替 | ✅ Celery 优先级低于封禁 |
| 记忆三处 | ⚠️ ①② 收敛；③ 工具 KV 未必进 AgentMemory |
| User.first() | ⚠️ 要修，但 enable_memory=false 时不阻塞接 Hermes |
| 本地模型路由 P1 | ❌ Ollama 模板已有；先配 LLMConfig |
| Flocks 插件 | ⚠️ runtime 收口后再做 |

### 13.4 阅读顺序

1. §13.2 开干 → 2. §2.1 三路径 → 3. `LangGraph → Hermes 统一.md` → 4. §4/§7/§12 按需查。

### 13.5 结论

**影响大，因为运行时主权未定，不是 Hermes 不行。** 最小动作：`invoke_agent` + 封禁路径 A + 两条 API 对齐。

---

实施以 **§13.2** 为准。Agent 收口见 `docs/LangGraph → Hermes 统一.md`。

---

## 16. 终审结论（2026-09-22，供项目组讨论定稿）

| 项 | 结论 |
|----|------|
| 优化方向 | **建议定稿**：Hermes 单运行时 + `invoke_agent` 门面 + 三路径分别收口 |
| MVP 范围 | **§13.2 六项**（含第 0 步 Agent 就绪）；§7 Phase A～F / §1.1 四维为 backlog |
| 专项文档 | `LangGraph → Hermes 统一.md` v1.1 与 §13.2 **已对齐**（双 output_mode） |
| 最大实施风险 | `ban_risk_analyze` 适配器保真 + `agent_client` 同步/日志/重试外层契约 |
| 定稿前必做 | 项目组确认封禁研判 Agent 配置负责人 + 内网 LLMConfig 可用 |

**不建议纳入 MVP 的讨论项**（可单独立项）：Phase S-full、PluginLoader、WorkflowSpec 包、物理删 LangGraph、OTel/K8s。

