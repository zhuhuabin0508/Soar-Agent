# LangGraph → Hermes 收口 · 实施进度

> 类型：**进度跟踪文档**（随代码与站会更新）  
> 最后更新：2026-10-10（基座审查补丁：会话隔离、显式输出模式、流式收口）  
> **方案与冲突评判标准（定稿，不随进度改）**：[`LangGraph → Hermes 统一.md`](./LangGraph%20→%20Hermes%20统一.md)  
> **基座 MVP 范围**：[`SOAR Agent 平台基座优化方案.md`](./SOAR%20Agent%20平台基座优化方案.md) §13.2  

---

## 1. 文档分工（后续有问题怎么办）

| 文档 | 作用 | 何时改 |
|------|------|--------|
| `LangGraph → Hermes 统一.md` | **方案定稿**：架构、契约、Step 1～4、§10 验收定义 | 仅当方案本身要修订时（走评审，升版本号） |
| **本文** | **实施进度**：任务清单、完成标准勾选、当前状态、评审待补 | 每完成一项任务 / 每次站会 |
| `SOAR Agent 平台基座优化方案.md` | 基座总方向、MVP §13.2 | 产品/基座范围变更时 |

**有冲突时怎么判**（Agent 运行时领域）：

1. **技术契约**（`output_mode`、三路径优先级、能否删 LangGraph）→ 以 **`LangGraph → Hermes 统一.md`** 为准  
2. **任务是否算 Done** → 以 **本文 §2 完成标准** 全部满足为准  
3. **MVP 做不做某项** → 以 **基座 §13.2** 为准  
4. **实现与方案不一致** → 要么改代码对齐方案，要么先改方案文档再改代码（**禁止**只改进度表糊弄）

---

## 2. 任务完成清单（完成标准 + 状态）

**图例**：✅ 已完成 · 🟡 部分完成 · ⬜ 未开始 · 🚫 本阶段不做  

**判定规则**：某任务行「完成标准」每一条均满足，才可标 ✅；否则 🟡 或 ⬜。

### Phase A — Week 1 / Step 1 立门面

| ID | 任务 | 完成标准 | 状态 | 备注 / 证据 |
|----|------|----------|------|-------------|
| W1-① | 新建 `app/platform/agent_runtime.py` | ① `invoke_agent` + `invoke_agent_sse`<br>② `RunContext` + `_log_invoke`<br>③ `adapt_soc_decision` / `adapt_ban_risk_analyze`<br>④ `resolve_engine`<br>⑤ `build_hermes_executor` | ✅ | `backend/app/platform/agent_runtime.py` |
| W1-② | `/chat` 迁入 runtime | ① 调用 `invoke_agent_sse`，不直建 Executor<br>② 日志可见 `_log_invoke`<br>③ history / Execution / 持久化不回归 | ✅ | `agents.py` `chat_agent` |
| W1-②b | `/test/stream` 迁入 runtime | ① `invoke_agent_sse`，禁止 `run_agent_decision_stream`<br>② 与 `/chat` 共用 Hermes `sse_stream`<br>③ 前端 SSE 契约兼容 | ✅ | 已补 Execution 写入 |
| W1-③ | 修复 `_create_llm` import（C-3） | ① 无 `app.core.config`<br>② import 正常 | ✅ | `from app.config import settings` |
| W1-④ | 适配器单测 | ① soc / ban 场景覆盖<br>② `pytest tests/test_agent_runtime.py` 全绿 | ✅ | 10/10 passed |
| W1-补 | Week 1 评审待补 | ① `REQUIRED_FIELDS` 与 `agent_client` 同源<br>② `/test/stream` 补 Execution<br>③ `/chat` 去掉重复 `resolve_engine` | ✅ | |

**Week 1 阶段结论**：✅ **已完成**

---

### Phase B — Week 2 / Step 2 Hermes 默认

| ID | 任务 | 完成标准 | 状态 | 方案依据 |
|----|------|----------|------|----------|
| W2-⓪ | 封禁研判 Hermes Agent | ① 已发布 Agent + LLMConfig<br>② `BAN_ANALYST_AGENT_ID`<br>③ 只读工具，不绑 `block_ip` | 🟡 | 代码与配置项就绪；**D2 运维交付待你验证** |
| W2-⑤ | `agent_client` → `invoke_agent` | ① `output_mode=ban_risk_analyze`<br>② 保留重试/日志/`AgentCallError` 外层<br>③ 缺字段不猜测<br>④ E2E §10 #7/#8 | 🟡 | 代码就绪；E2E 待配置 `BAN_ANALYST_AGENT_ID` |
| W2-⑥ | `run_agent_decision` 转发 | ① 仅转发 `invoke_agent`<br>② `DeprecationWarning`<br>③ 不调 `build_agent_graph` | ✅ | Step 4 已删 `graph.py` |
| W2-⑥b | `POST /test` 迁入 | ① 经 `invoke_agent` | ✅ | |
| W2-⑦ | `engine` 默认 hermes | ① ORM/API 默认 hermes<br>② langgraph 仅 warning | ✅ | |

---

### Phase C — Week 3 / Step 3 工作流

| ID | 任务 | 完成标准 | 状态 | 方案依据 |
|----|------|----------|------|----------|
| W3-⑧ | `execute_ai_agent` | ① 仅 `invoke_agent`<br>② 无直建 Executor | ✅ | `invoke_agent_for_workflow` |
| W3-⑨ | Celery ai_agent | ① 适配层，禁止整替 `_execute_node`<br>② `soc_decision` | ✅ | Celery `ai_agent` → `execute_ai_agent` |
| W3-⑩ | tools / skills 测试 | ① 经 runtime | ✅ | skills / tools debug 均 `invoke_agent`；debug 依赖 SOC Agent 预配工具 |
| W3-补 | `WORKFLOW_SYSTEM_USER_ID` | ① 替代 `User.first()` | ✅ | 未配置时用 `runtime-system`，不再 `User.first()` |

---

### Phase D — Week 4+ / Step 4 删 Legacy

| ID | 任务 | 完成标准 | 状态 | 方案依据 |
|----|------|----------|------|----------|
| W4-⑪ | ToolRegistryBuilder | ① 唯一工具工厂 | ⬜ | 统一.md §7 |
| W4-⑫ | agent_id 迁移 | ① graph_config + seed 扫描 | ⬜ | 统一.md §5.1 |
| W4-⑬ | 删 LangGraph 循环 | ① grep 干净 + legacy 删除 | ✅ | 已删 `graph.py`、卸 `langgraph` 包；§10 体验项另计 |

---

## 3. 总体验收进度（对应方案 §10）

| # | 验收条目（摘自方案 §10） | 状态 |
|---|-------------------------|------|
| 1 | /chat、/test/stream、test-run、Celery 行为一致 | 🟡 | Playground + test-run 已验；**Celery 全路径排在基座初步收口之后**，统一体验测试 |
| 2 | 封禁经 `invoke_agent`，生产不依赖 mock | 🟡 | **封禁 E2E 同上**，基座收口后再验 |
| 3 | 无业务层直建 `HermesAgentExecutor` / `build_agent_graph` | ✅ | 业务路径经 `invoke_agent`；委派子 Agent 在 Hermes 内部 |
| 4 | `run_agent_decision` 仅剩转发或为零 | ✅ | 有 Agent 时转发 `invoke_agent`；无配置非 dev 返回 `need_human_approval` |
| 5 | `engine=langgraph` 仅 warning，实际 Hermes | ✅ |
| 6 | `soc_decision` 满足 condition_branch | 🟡 | 运行时字段已具备；**分支条件配置**在基座收口后体验测试中一并验证 |
| 7 | 封禁 E2E + mock 降级 | 🟡 | 与 #2 同批；问题 **统一收集反馈** 后再改 |
| 8 | `ban_risk_analyze` 与 `REQUIRED_FIELDS` 一致 | ✅ |

---

## 4. 变更记录（仅本文）

| 日期 | 说明 |
|------|------|
| 2026-09-23 | 初版 + Week 1/2 代码 |
| 2026-09-28 | Week 3 工作流/Celery 收口；C0-6/7/8/9/10 代码；待用户 E2E 验证 |
| 2026-09-28 | 基座收口第二轮：禁决策 LangGraph、生产禁封禁 mock、SOC/系统用户门禁、tools debug→runtime |
| 2026-09-28 | 研发收口自检 §8；`asset_tasks` 迁入 `invoke_agent` |
| 2026-10-08 | 研发冻结 Agent 基座 MVP；删 `state.py`/`agent_tools.py`；文档与过时 LangGraph 表述收尾 |
| 2026-10-10 | 审查补丁合入 `main`：`AgentRun`、会话 `user_id`、`output_mode`、正式对话覆盖收紧、工具构造拆出 `tool_builders.py`。双账号隔离已验证；封禁 E2E 仍未做。详见体验问题清单 B-1～B-4 |

---

## 5. 更新说明（给维护人）

1. 完成任务后：改 §2 对应行「状态」+ 可选「备注 / 证据」（PR 链接、commit）  
2. 同步更新 §3 总体验收表中相关行  
3. **不要**为了省事去改 `LangGraph → Hermes 统一.md` 里的状态勾选  
4. 若发现方案本身有误：先提方案修订（统一.md 升 v1.2+），再改代码与本文  

---

## 6. 基座「初步完成」关门清单（给你排期用）

| 阶段 | 内容 | 谁做 | 状态 |
|------|------|------|------|
| **A** | 运行时单门面（本轮代码） | 研发 | ✅ | invoke_agent 全路径；`asset_tasks` 已迁入 runtime |
| **B** | D2-1～D2-8：研判 Agent + `BAN_ANALYST_AGENT_ID` + 封禁 E2E | 你 | ⬜ **排在基座初步收口之后**；与 §10 #2/#7 同批体验测试 |
| **C** | 工作流 **节点绑定 Agent**（主路径）；`WORKFLOW_SYSTEM_USER_ID` 可选；`WORKFLOW_SOC_AGENT_ID` **仅兜底** | 你 | 🟡 节点选名即可；env SOC id **非搭建 Agent 必需** |
| **D** | Step 4 物理删 Legacy：删 `graph.py`、`langgraph` 包依赖等（**Hermes 内 `langchain_core` 暂保留**） | 研发 | ✅ |
| **E** | 版本/架构文档出版与 §10 全 ✅ | 你+研发 | 🟡 | **研发侧 Agent 基座已冻结（2026-10-08）**；§10 剩余项随体验测试更新 |
| **F** | Agent 搭建、Playground/工作流体验测试 | 你 | 🟡 **通用 SOC Demo 初步通过**；封禁 E2E 未做 |

**计划顺序**：A + **D**（研发收口）→ **E 基座初步完成** → **F + B + §10 #1/#6/#2/#7**（你方统一体验测试、问题汇总反馈）→ 再迭代修复。

> **排期约定（2026-09-28）**：Celery 全路径、封禁 E2E、条件分支配齐等 🟡 项 **不阻塞** 基座初步收口；基座优化初步完成后集中测试，使用问题统一收集再改。

---

## 7. 现阶段情况与初步测试结果

### 7.1 现状摘要（2026-09-28）

| 项 | 状态 |
|----|------|
| Hermes 单门面 / 工作流 `execute_ai_agent` → `invoke_agent_for_workflow` | 已合入并 **test-run 验证** |
| 决策路径 LangGraph | 已禁用；无 Agent 配置时 dev Mock 或 `need_human_approval` |
| 业务人员搭 Agent | 智能体管理创建发布；**工作流节点按名称选 Agent**，保存后为 `agent_id` |
| `WORKFLOW_SOC_AGENT_ID` | **可选兜底**（空节点、工具 debug）；**节点已选 Agent 时不依赖** |
| `BAN_ANALYST_AGENT_ID` | 封禁路径用；**与通用 SOC Demo 无关**，D2 未验 |
| 节点库部分变灰 | **后端 `NODE_EXECUTORS` 未实现** → 前端禁拖，防运行报错（C0-10） |
| Step 4 删 `graph.py` | ✅ 2026-09-28；保留 `langchain_core` |

### 7.2 初步测试记录（Demo：IP 白名单快判）

**智能体**：`Demo-SOC-白名单`（库表 **id=54**，Hermes，工具 `check_whitelist`）。

| # | 场景 | 输入 | 结果 | 结论 |
|---|------|------|------|------|
| T1 | Playground / 流式测试 | `src_ip=8.8.8.8` 研判 | 调用 `check_whitelist`；`decision=need_human_approval` | ✅ Agent 与工具正常 |
| T2 | 工作流 **test-run** | 图：手动触发 → ai_agent(**54**) → 条件分支 → 结束；payload 含 `8.8.8.8` | 日志：`调用智能体(runtime): id=54`；output 含 `decision=need_human_approval`、messages 含 tool 调用；`status=success` | ✅ **工作流可调 Agent** |
| T3 | 条件分支 | 未配或 0 条条件 | `route=false` 走「否」 | 预期行为；配 `decision == need_human_approval` 后走「是」 |
| T4 | Celery 异步执行 | — | 未在本轮记录中复测 | ⬜ 待补 |

**T2 输出要点（摘录）**：`check_whitelist` → `in_whitelist: false`；结构化 `decision: need_human_approval`。若 payload 嵌套 `payload.src_ip`，可能出现 `target_ip: unknown`（顶层无 `src_ip`）；**试运行建议扁平 JSON**：`{"src_ip":"8.8.8.8","input":"demo"}`。

### 7.3 节点库可用范围（与灰节点）

**可拖（白名单，与 `NODE_EXECUTORS` 对齐）**：Webhook / **手动触发**、AI 智能体、LLM、条件分支、结束、发送通知、工具、人工审批、HTTP、封禁/设备动作、循环/迭代/代码执行等（见 `frontend/src/constants/nodeCatalog.js` → `BACKEND_SUPPORTED_NODE_TYPES`）。

**仍禁拖（示例）**：定时触发、事件触发、意图识别等 — **后端执行器未就绪**，非「测试环境限制」。

### 7.4 基座收口后集中测（不阻塞 Demo 结论）

- §10 **#1 Celery**、**#2/#7 封禁 E2E**、**#6 条件分支配置** — 基座初步完成后统一体验测试；问题汇总反馈后再改  
- D2 / `BAN_ANALYST_AGENT_ID>0` — 与封禁 E2E 同批  
- §10 全 ✅、架构 **E** 定稿 — 随上述测试结论更新  
- 条件分支 + 通知 **产品化模板**（可选）

---

## 8. 研发侧基座收口自检（2026-09-28）

| 类别 | 项 | 状态 |
|------|-----|------|
| **运行时** | `invoke_agent` / `invoke_agent_sse` / `invoke_agent_for_workflow` | ✅ |
| | `/chat`、`/test`、`/test/stream`、skills/tools debug | ✅ |
| | Celery `ai_agent` → `execute_ai_agent` | ✅ |
| | 封禁 `agent_client` → `ban_risk_analyze` | ✅ 代码 |
| | `asset_tasks` 扫描 → `invoke_agent`（非直建 Executor） | ✅ |
| **Legacy** | `graph.py` / pip `langgraph` | ✅ 已删 |
| | `run_agent_decision*` 仅转发 runtime | ✅ |
| **默认** | ORM/API/前端默认 `engine=hermes` | ✅ |
| **工作流** | `NODE_EXECUTORS` ↔ 前端白名单 | ✅ |
| **本阶段不做** | W4-⑪ ToolRegistryBuilder、W4-⑫ agent_id 迁移 | ⬜ 阶段 2 |
| **不阻塞研发收口** | §10 #1 Celery 全路径、#2/#7 封禁 E2E、#6 条件分支 | 🟡 你方体验测试后反馈 |
| **运维/产品** | C0-1 封禁研判 Agent 发布 + `BAN_ANALYST_AGENT_ID` | 🟡 |

**研发侧结论**：基座 MVP（§13.2 + Step 4）**可冻结**；剩余 🟡 均为配置/E2E/体验，按 §6 排期在收口后集中测。

---
