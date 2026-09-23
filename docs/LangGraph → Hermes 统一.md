# Agent 运行时收口方案：LangGraph → Hermes 统一

> 状态：**专项执行文档 v1.1（终审稿）**（2026-09-22）  
> 适用：SOAR 平台 Agent 基座（内网私有化部署）  
> 关联：`docs/SOAR Agent 平台基座优化方案.md`（**实施优先级以 §13.2 为准**；§12.4 为历史 P0～P2 对照）  
> §13 为 Codex 评审对照；§14 为独立审视；**§15 为终审结论（与基座 §16 同步）**

---

## 1. 背景与问题

当前项目存在 **两套 Agent ReAct 运行时**：

| 路径 | 代码 | 用途 |
|------|------|------|
| LangGraph | `graph.py` + `decision.run_agent_decision` | 旧主链路、Celery ai_agent、test/stream、工具测试 |
| Hermes | `agent/hermes/executor.py` | /chat、test-run 工作流（有 agent_id）、定时任务 |

二者功能重叠（拼 prompt → 绑工具 → LLM 循环 → 调工具），但能力不对等：Hermes 有 guardrails、verification、委派、tool_search、SSE 等；LangGraph 路径无这些能力。

**冲突根因**：历史「零侵入叠加 Hermes」+ `engine` 字段未贯穿全链路 + 工具工厂双份维护。  
**不是** LangGraph 与 Hermes 两个框架理论互斥，而是 **同一能力做了两套实现，迁移只做了一半**。

另需区分 **工作流三路径**（详见基座优化方案 §12.2.1）：

```
路径 A — 封禁专用：workflow/engine.py → agent_client HTTP → /internal/mock
路径 B — 通用 Celery：workflow_tasks → run_agent_decision
路径 C — test-run：workflow_runner → node_executors.execute_ai_agent
```

收口 Agent 运行时 **不能** 只改路径 B；封禁主链路（路径 A）须单独接入 `invoke_agent`。

---

## 2. 收口目标

| 目标 | 说明 |
|------|------|
| 单入口 | 全项目经 `invoke_agent()` / `invoke_tool()` 调用 Agent |
| 单实现 | ReAct 循环只在 Hermes 维护 |
| 兼容可删 | `run_agent_decision` / `graph.py` 降为薄壳，稳定后删除 |
| 库可留 | `langchain-core`（Message/LLM）可继续使用；LangGraph **图编排**与 Agent 循环解绑后可评估卸载 |
| engine 收口 | 对外只认 `hermes`；`langgraph` 为 legacy alias，日志告警后转 Hermes |

**收口的是「Agent 运行时主权」，不是立刻卸载所有 LangChain 依赖。**

---

## 3. 目标架构（三层）

```
┌─────────────────────────────────────────────────────────┐
│ L3 调用方（只认这一层）                                    │
│   POST /agents/{id}/chat                                 │
│   POST /agents/{id}/test/stream                          │
│   node_executors.execute_ai_agent                        │
│   workflow_tasks ai_agent                                │
│   agent_client.analyze_ip_risk（封禁研判）                 │
│   tools_manage / skills 测试                             │
└───────────────────────────┬─────────────────────────────┘
                            │ invoke_agent(ctx)
                            ▼
┌─────────────────────────────────────────────────────────┐
│ L2 AgentRuntime（新建 app/platform/agent_runtime.py）   │
│   - 加载 Agent / User / RunContext                       │
│   - stream / 非 stream                                   │
│   - output_mode：chat | soc_decision | ban_risk_analyze  │
│   - engine=langgraph → 告警并转 hermes                   │
└───────────────────────────┬─────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
┌──────────────────────────┐   ┌──────────────────────────┐
│ HermesAgentExecutor       │   │ MockFallback（无 LLM）   │
│ + HermesToolEngine        │   │ 规则化 SOC 降级          │
│ （唯一 ReAct 实现）        │   │ 非 LangGraph              │
└──────────────────────────┘   └──────────────────────────┘
              │
              ▼
┌──────────────────────────┐
│ ToolRegistryBuilder      │
│ invoke_tool()            │
└──────────────────────────┘

删除目标（稳定 1～2 版本后）：
  graph.build_agent_graph
  decision 内 LangGraph 循环
  node_executors._run_langgraph_agent
```

---

## 4. 四步收口路线

### Step 1 — 立门面（约 1 周，行为可不变）

新建 `backend/app/platform/agent_runtime.py`：

```python
async def invoke_agent(
    *,
    db,
    agent_id: int | None = None,
    agent: Agent | None = None,
    input: str | dict,
    user,
    channel: str = "api",
    stream: bool = False,
    output_mode: str = "chat",  # chat | soc_decision | ban_risk_analyze
    inline_config: dict | None = None,  # 过渡：无 agent_id 的旧节点
) -> AgentResult | AsyncIterator[SSEEvent]:
    ...
```

**第一批接入调用点（只换入口，逻辑迁入 runtime）：**

| 调用方 | 文件 | 现状 |
|--------|------|------|
| 正式对话 | `api/v1/agents.py` `/chat` | 直接 HermesExecutor |
| Playground | `api/v1/agents.py` `/test/stream` | LangGraph stream |
| 工作流节点 | `core/node_executors.py` `execute_ai_agent` | 按 engine 分叉 |
| Celery | `tasks/workflow_tasks.py` ai_agent | run_agent_decision |
| 封禁研判 | `workflow/agent_client.py` | HTTP → /internal/mock |
| 工具测试 | `api/v1/tools_manage.py` | run_agent_decision |
| 技能测试 | `api/v1/skills.py` | run_agent_decision |

**验收**：所有路径经 `invoke_agent` 打点日志（agent_id、engine、channel、output_mode）。

---

### Step 2 — Hermes 为默认实现（约 1～2 周）

在 `invoke_agent` 内统一路由：

```python
engine = (agent.engine or "hermes").lower()
if engine in ("langgraph", "legacy"):
    logger.warning("engine=%s deprecated, routing to hermes", engine)
    engine = "hermes"
```

**流式**：`stream=True` → `hermes_sse_stream(...)`（与 `/chat` 共用生成器，禁止 test/stream 单独走 LangGraph）。

**非流式 + 响应适配器（两种契约，不可混用）**：

| output_mode | 契约 | 消费方 |
|-------------|------|--------|
| `soc_decision` | `{decision, target_ip, reason, duration}` | Celery ai_agent、通用 condition_branch |
| `ban_risk_analyze` | `{is_banned, risk_level, action, need_confirm, ban_plan, monitoring_advice, reasons}` | 封禁路径 A（`agent_client` / `action_branch`） |

`soc_decision` 示例：

```json
{
  "decision": "block_ip | ignore | need_human_approval",
  "target_ip": "...",
  "reason": "...",
  "duration": "24h",
  "messages": [],
  "logs": []
}
```

`ban_risk_analyze` 示例（与 `agent_client.REQUIRED_FIELDS` 一致）：

```json
{
  "is_banned": false,
  "risk_level": "高危",
  "action": "ban | monitor",
  "need_confirm": true,
  "ban_plan": {"ban_level": "high", "ban_duration": 7200, "reason": "..."},
  "monitoring_advice": "...",
  "reasons": ["..."]
}
```

**封禁路径 A（P0-0，最高优先）**：

```python
# workflow/agent_client.analyze_ip_risk — 注意是 ban_risk_analyze，不是 soc_decision
decision = await invoke_agent(
    db=db,
    agent_id=settings.BAN_ANALYST_AGENT_ID,
    input={"ip": ip, "alert_context": alert_context},
    user=resolve_system_user(db),
    output_mode="ban_risk_analyze",
)
```

**soc_decision 保真手段（实现前必须写死，见 §5.5）**：

- 复用 `decision._parse_action_decision_from_content` + `_VALID_DECISIONS` 校验
- 解析失败 → 强制 `need_human_approval`（现有降级逻辑）
- 可选：Hermes 最后一轮用 structured output / JSON schema 约束，再经同一校验器
- 禁止把未校验的自由文本直接交给 `condition_branch`

**封禁研判 Agent 工具策略**：研判阶段仅绑定只读工具（白名单/资产/威胁情报）；**不绑定 `block_ip`**，避免与 `verification` 及下游 `ban_executor` 职责重叠（见 §5.6）。

配置项新增：`BAN_ANALYST_AGENT_ID`（指向已发布的 Hermes 研判 Agent）。  
`/internal/mock` 保留 dev/staging，生产走 Hermes；`/internal` 须带 `X-Internal-Secret`（dev 有默认 secret，禁止无 secret 不挂载）。

---

### Step 3 — 薄壳兼容（约 1 个版本）

`decision.py` 不再 `build_agent_graph`：

```python
async def run_agent_decision(...):
    import warnings
    warnings.warn("run_agent_decision is deprecated; use invoke_agent", DeprecationWarning)
    return await invoke_agent(
        ...,
        output_mode="soc_decision",
    )
```

`run_agent_decision_stream` 同样转发 `invoke_agent(stream=True)`。

**Mock / 无 LLM**：保留 `decision._mock_decision` 规则逻辑，由 runtime 在 LLM 不可用时调用，**不经过 LangGraph**。

---

### Step 4 — 删除 Legacy（稳定 1～2 版本后）

| 删除/归档项 | 前置条件 |
|-------------|----------|
| `graph.py` 的 `build_agent_graph` | grep 无引用 + E2E 通过 |
| `decision.py` 内 LangGraph 循环代码 | run_agent_decision 仅转发或已删除 |
| `node_executors._run_langgraph_agent` | 已并入 runtime |
| UI/API 的 `engine=langgraph` 选项 | 仅 hermes |
| pip 包 `langgraph` | 确认无其他图依赖 |

**删除可控性（代码核验）**：`build_agent_graph` 引用高度集中——仅 `decision.py`（`:855`、`:1139`）与 `graph.py` 内部示例（`:187`）；grep 通过后可安全删除 LangGraph 循环，风险低于「散落全库」。

---

## 5. 特殊场景处理

### 5.1 无 agent_id 的旧工作流 ai_agent 节点

| 策略 | 说明 |
|------|------|
| **A（推荐）** | 数据迁移：所有 ai_agent 节点绑定 `agent_id`；脚本须**同时**扫描：① `workflows.graph_config`（React Flow 通用工作流）② 若存在 DSL/seed 中的 ai_agent 内联配置（见 `core/seed.py`、`workflow_draft.py`）。封禁专用 `NODE_REGISTRY`（`agent_analyze` 等）**不含** ai_agent 类型，勿只扫 graph_config |
| **B（过渡）** | `invoke_agent(inline_config=...)` 构造临时配置仍走 Hermes；**禁止**再调 LangGraph |

过渡期限建议：1 个 minor 版本，到期强制策略 A。

### 5.2 Celery 与 node_executors 对齐

**禁止**用 `asyncio.run(execute_node(...))` 整段替换 `_execute_node`。

推荐适配层：

```python
async def _execute_node_async(node_type, node_data, context, payload, log):
    node_input = _build_node_input(node_type, node_data, context, payload)
    if node_type in NODE_EXECUTORS:
        return await execute_node(node_type, node_data, node_input, context, log)
    return _execute_node_legacy(...)

def _execute_node(...):
    return asyncio.run(_execute_node_async(...))
```

`ai_agent` 有 `agent_id` 时经 `execute_ai_agent` → `invoke_agent`；无 `agent_id` 走迁移或 inline_config。

### 5.3 工作流 Hermes 的 system user

`node_executors._run_hermes_agent` 当前用 `User.first()` 作执行主体，审计/权限有风险。

收口时改为：

- 配置项 `WORKFLOW_SYSTEM_USER_ID`，或  
- 实例级 `created_by` / 触发人传递  

并在 `invoke_agent` 的 `RunContext` 中强制记录。

### 5.4 test/stream 与 /chat 共用 SSE

提取 `_hermes_sse_stream(agent, body, db, user)`，保留 test 的 `override` 参数与 publish 校验，**禁止** `current_user=None` 硬转 `/chat`。

### 5.5 soc_decision / ban_risk_analyze 适配器保真（P0 实现风险）

Hermes 默认输出自由文本 + 工具循环；结构化契约须由 **runtime 适配层** 保证，不能靠 LLM「自觉」。

| 模式 | 保真策略 | 映射失败 |
|------|----------|----------|
| `soc_decision` | 复用 `_parse_action_decision_from_content`；`decision ∉ _VALID_DECISIONS` 即失败 | 降级为 `need_human_approval` + 写 audit log |
| `ban_risk_analyze` | Pydantic 模型校验 `REQUIRED_FIELDS`（对齐 `agent_client`）；字段缺失即失败 | 抛 `AgentCallError`，走封禁 `error_handler`（与 mock invalid_json 行为一致） |

建议实现顺序：

1. 先把现有解析/校验函数迁入 `agent_runtime.py`（不重复造轮子）
2. 研判 Agent 的 system prompt 明确要求 JSON 形态（两种 schema 分别维护）
3. Step 2 完成前补单测：合法 JSON、缺字段、非法 decision、自由文本

### 5.6 decision 层 vs Hermes verification 职责边界

两层回答不同问题，**不得互相替代**：

| 层 | 职责 | 典型触发 |
|----|------|----------|
| **output_mode 适配器（decision 语义）** | 「建议封 / 忽略 / 人工 / monitor」——工作流路由依据 | Hermes 跑完 → 适配器输出 JSON |
| **verification（执行安全）** | 「此刻能否调用写工具 block_ip」——证据链是否充分 | Hermes 工具循环内调用 `block_ip` 前 |

封禁路径 A 的推荐分工：

- 研判 Agent：**只读工具 + `ban_risk_analyze` 适配器** → `action_branch` / `direct_ban`
- 实际封禁：由 `ban_executor` / `execute_ban` 节点执行，**不**在研判阶段调 `block_ip`
- 若未来研判 Agent 误绑 `block_ip`：verification 仍会在工具层拦截，但应通过配置禁止，而非依赖运行时碰运气

通用 Celery `soc_decision` 路径：同样建议研判类 Agent 不绑写工具；若绑了，`decision=block_ip` 与 verification 拒绝可能同时出现——以 **verification 为准** 执行，以 **soc_decision** 做工作流分支。

---

## 6. engine 字段收口

| 阶段 | 动作 |
|------|------|
| 立即 | ORM / API 创建默认 `hermes`；seed / DSL 已默认 hermes 的保持一致 |
| 过渡 | 读取 `engine=langgraph` 时打 warning，runtime 内映射为 hermes |
| 终态 | UI 隐藏 langgraph；DB 历史行可保留，新写入仅 hermes |

---

## 7. 工具层同步（必须与 Agent 收口一起做）

否则 Agent 收到 Hermes、工具仍从 `decision._build_db_tools` 注册，分裂依旧。

```
invoke_agent
  └─ HermesToolEngine
       └─ ToolRegistryBuilder.build(db, agent)   # 新建，唯一工厂
            ├─ DB code/http/framework tools
            ├─ KB / query_kb_file
            ├─ search_assets（单轨，M-5）
            └─ workflow-as-tool
```

LangGraph 的 `StructuredTool` 组装路径随 Step 4 删除。  
详见基座方案 H-2、`app/agent/tool_factory.py`（待建）。

---

## 8. 不推荐的做法

| 做法 | 原因 |
|------|------|
| 长期双引擎并存 | 工具/测试/生产持续分裂 |
| 立刻删除 graph.py | 调用点仍多，回归风险大 |
| Celery 整函数替换 execute_node | 签名、BFS 轨迹、审批暂停上下文不同 |
| 只改 engine 默认值 | 路由未收，test/stream 仍走 LangGraph |
| 把 LangGraph 当 SOAR 工作流引擎 | 工作流已是自研 DAG + 封禁 engine，概念勿混 |
| 以为改 Celery 即修复封禁 | 封禁走路径 A，须改 agent_client |
| 把路径 A 当成 soc_decision | 封禁下游读 `action`/`need_confirm`，不是 `decision=block_ip` |

---

## 9. 实施顺序（建议）

```
Week 1
  ① 新建 agent_runtime.py + RunContext + 双适配器（soc_decision + ban_risk_analyze）
  ② /chat、/test/stream 迁入 runtime
  ③ 修复 agents._create_llm → llm_helper（C-3）
  ④ 适配器单测（合法/缺字段/非法 decision）通过后再动封禁

Week 2
  ⑤ agent_client.analyze_ip_risk → invoke_agent（output_mode=ban_risk_analyze，P0-0 封禁）
  ⑥ run_agent_decision / run_agent_decision_stream → 转发 runtime
  ⑦ engine 默认 hermes + langgraph alias 告警

Week 3
  ⑧ node_executors.execute_ai_agent 仅调 invoke_agent
  ⑨ Celery ai_agent 适配层（非整段替换）
  ⑩ tools_manage / skills 测试迁入 runtime

Week 4+
  ⑪ ToolRegistryBuilder 合并双工厂
  ⑫ 存量工作流 agent_id 迁移
  ⑬ 删除 graph LangGraph 循环（Step 4）
```

---

## 10. 验收标准

| # | 条目 |
|---|------|
| 1 | 同一 Hermes Agent：/chat、/test/stream、工作流 test-run、Celery（有 agent_id）行为一致（含 guardrails/verification） |
| 2 | 封禁 instance：`agent_analyze` 经 `invoke_agent`，生产不依赖 /internal/mock（mock 限 dev） |
| 3 | 全项目无新增对 `build_agent_graph` / 直接 `HermesAgentExecutor` 的业务调用（除 runtime 内部） |
| 4 | `run_agent_decision` 调用处仅剩 runtime 转发或为零 |
| 5 | `engine=langgraph` 仅触发 warning，实际走 Hermes |
| 6 | `soc_decision` 输出满足通用工作流 `condition_branch` 契约（`block_ip` / `ignore` / `need_human_approval`） |
| 7 | **封禁 E2E**：真实场景从 `/internal/mock` 切到 Hermes 研判后，`agent_analyze` → `banned_check` → `action_branch` → `direct_ban`/`approval_ticket` → `ban_executor` 全链路通过；LLM 不可用时 mock 降级仍正确 |
| 8 | `ban_risk_analyze` 输出字段与 `agent_client.REQUIRED_FIELDS` 一致，缺字段按解析失败处理（不猜测填充） |

---

## 11. 与基座优化方案的关系

| 基座方案条目 | 本收口方案 |
|--------------|------------|
| §12.4 P0-0 | Step 2 封禁 agent_client |
| §12.4 P0-1 | Step 3 Celery 适配层 |
| §12.4 P0-2 | Step 1 test/stream 共用 SSE |
| C-1 | 改为适配层，非整函数替换 |
| H-2 ToolRegistryBuilder | §7 与 Step 4 前完成 |
| Phase E 声明式插件 | 在 invoke_agent / invoke_tool 稳定后进行 |

**本文件为 Agent 运行时收口专项文档；基座整体优先级以 `SOAR Agent 平台基座优化方案.md` §13.2 为准。**

---

## 12. 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-09-22 | v1.0 | 初稿：三层架构、四步收口、三路径、实施顺序与验收 |
| 2026-09-22 | v1.1 | 拆分 `ban_risk_analyze` vs `soc_decision`；§5.5～5.6 保真与 verification 边界；验收 #7/#8；Codex 对照 §13；独立审视 §14 |

---

## 13. Codex 评审对照（2026-09-22，非终审）

Codex 结论：**方向正确、落点准确、可执行**。下列核验**大体成立**：

| 论断 | 独立核验 |
|------|----------|
| 问题定性（迁移做了一半） | ✅ |
| 关键符号与调用方清单 | ✅ |
| 三路径与基座 §12.2.1 一致 | ✅ |
| output_mode 适配器是亮点 | ✅ 但 v1.0 **误把封禁契约写成 soc_decision**，v1.1 已拆 |
| Step 1～4 节奏 | ✅ |
| build_agent_graph 引用集中 | ✅ 已写入 Step 4 |

Codex 五条补强建议：**全部采纳**（已并入 §5.5、§5.6、§5.1、验收 #7、Step 4 说明）。

---

## 14. 独立审视（v1.1 — 实施请以本节为准）

### 14.1 对 Codex「直接采信定稿」的纠偏

| Codex | 独立判断 |
|-------|----------|
| 可直接采信定稿 | **方向采信，文档 v1.0 有一处契约错误，不能原样开干** |
| soc_decision 解决封禁下游 | **仅适用于路径 B**；路径 A 须 `ban_risk_analyze` |
| verification 与 decision 要分清 | ✅ 已 §5.6；研判 Agent 应只读工具 |

### 14.2 v1.0 关键缺陷（已修）

v1.0 Step 2 示例把 `agent_client` 写成 `output_mode=soc_decision`，与代码矛盾：

- `agent_client.REQUIRED_FIELDS` = `is_banned / risk_level / action / ...`
- `run_agent_decision` 返回 = `decision / target_ip / reason / duration`

两套 JSON **服务不同下游**（`action_branch` vs 通用 condition_branch），合并为一个 `soc_decision` 会在 Step 2 直接打挂封禁生产。

### 14.3 与基座 §13.2 的对齐

| 基座 §13.2 | 本文件 |
|------------|--------|
| ① invoke_agent + soc_decision 适配器 | Step 1 + §5.5（含 ban_risk_analyze） |
| ② 封禁 agent_client | Step 2，`ban_risk_analyze` |
| ③ test/stream 与 /chat 共用 SSE | Step 1 / §5.4 |
| ④ _create_llm + engine 默认 | Week 1 ③ |
| ⑤ check_whitelist schema | 并行，非本文件范围 |

### 14.4 建议落地顺序（Week 1 可开）

1. `agent_runtime.py` 骨架 + `output_mode` 枚举 + 两种适配器（先 Mock/Hermes 双路径单测）
2. `/chat`、`/test/stream` 迁入（行为不变）
3. **不要**先做封禁切 Hermes，直到 `ban_risk_analyze` 适配器单测通过

### 14.5 结论

**Codex 评审可采信方向与代码落点。** v1.1 修正契约分裂后，**建议作为 Agent 运行时收口定稿**（见 §15）。

---

## 15. 终审结论（2026-09-22，供项目组讨论定稿）

| 维度 | 结论 |
|------|------|
| 问题定性 | ✅ 准确：同一能力两套实现，迁移做了一半 |
| 代码落点 | ✅ 经复核：`run_agent_decision`、三路径、`agent_client` 契约、调用方清单均属实 |
| 架构设计 | ✅ `invoke_agent` 三层 + 双 `output_mode` + 渐进删 LangGraph，风险可控 |
| 与基座对齐 | ✅ 与 `SOAR Agent 平台基座优化方案.md` §13.2 一致（v0.7 已同步） |
| 定稿建议 | **通过**，作为 Agent 收口专项执行文档 |

**项目组需确认的 3 项（非阻塞定稿，阻塞编码）**：

1. 封禁研判 Hermes Agent 由谁创建/发布（`BAN_ANALYST_AGENT_ID`）  
2. 内网 LLMConfig（Ollama/私有 API）是否已就绪  
3. MVP 验收是否采纳 §10 条目 #7/#8（封禁 E2E + 字段校验）
