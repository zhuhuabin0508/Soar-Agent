# LangGraph → Hermes 收口 · 实施进度

> 类型：**进度跟踪文档**（随代码与站会更新）  
> 最后更新：2026-09-23  
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
| W1-④ | 适配器单测 | ① soc / ban 场景覆盖<br>② `pytest tests/test_agent_runtime.py` 全绿 | ✅ | 10/10 passed（2026-09-23） |
| W1-补 | Week 1 评审待补 | ① `REQUIRED_FIELDS` 与 `agent_client` 同源<br>② `/test/stream` 补 Execution<br>③ `/chat` 去掉重复 `resolve_engine` | ✅ | `BAN_RISK_REQUIRED_FIELDS` 引用 `agent_client.REQUIRED_FIELDS` |

**Week 1 阶段结论**：✅ **已完成** — 可进入 Week 2。

---

### Phase B — Week 2 / Step 2 Hermes 默认

| ID | 任务 | 完成标准 | 状态 | 方案依据 |
|----|------|----------|------|----------|
| W2-⓪ | 封禁研判 Hermes Agent | ① 已发布 Agent + LLMConfig<br>② `BAN_ANALYST_AGENT_ID`<br>③ 只读工具，不绑 `block_ip` | 🟡 | `config.py` 已增 `BAN_ANALYST_AGENT_ID`（默认 0）；Agent 发布待运维配置 |
| W2-⑤ | `agent_client` → `invoke_agent` | ① `output_mode=ban_risk_analyze`<br>② 保留重试/日志/`AgentCallError` 外层<br>③ 缺字段不猜测<br>④ E2E §10 #7/#8 | 🟡 | 代码已切；`BAN_ANALYST_AGENT_ID>0` 走 Hermes，0 回退 HTTP mock |
| W2-⑥ | `run_agent_decision` 转发 | ① 仅转发 `invoke_agent`<br>② `DeprecationWarning`<br>③ 不调 `build_agent_graph` | 🟡 | 有 `agent_id` 时转发；无 `agent_id` 仍 legacy |
| W2-⑥b | `POST /test` 迁入 | ① 经 `invoke_agent` | ✅ | `agents.py` `test_agent` |
| W2-⑦ | `engine` 默认 hermes | ① ORM/API 默认 hermes<br>② langgraph 仅 warning | ✅ | ORM/API/security 默认 hermes；runtime `resolve_engine` 告警 |

---

### Phase C — Week 3 / Step 3 工作流

| ID | 任务 | 完成标准 | 状态 | 方案依据 |
|----|------|----------|------|----------|
| W3-⑧ | `execute_ai_agent` | ① 仅 `invoke_agent`<br>② 无直建 Executor | ⬜ | 统一.md Step 1 调用方表 |
| W3-⑨ | Celery ai_agent | ① 适配层，禁止整替 `_execute_node`<br>② `soc_decision` | ⬜ | 统一.md §5.2；路径 B |
| W3-⑩ | tools / skills 测试 | ① 经 runtime | ⬜ | |
| W3-补 | `WORKFLOW_SYSTEM_USER_ID` | ① 替代 `User.first()` | ⬜ | 统一.md §5.3 |

---

### Phase D — Week 4+ / Step 4 删 Legacy

| ID | 任务 | 完成标准 | 状态 | 方案依据 |
|----|------|----------|------|----------|
| W4-⑪ | ToolRegistryBuilder | ① 唯一工具工厂 | ⬜ | 统一.md §7 |
| W4-⑫ | agent_id 迁移 | ① graph_config + seed 扫描 | ⬜ | 统一.md §5.1 |
| W4-⑬ | 删 LangGraph 循环 | ① grep 干净 + §10 全 ✅ | ⬜ | 统一.md Step 4 |

---

## 3. 总体验收进度（对应方案 §10）

全项目 **Done** = 下表全部为 ✅。

| # | 验收条目（摘自方案 §10） | 状态 |
|---|-------------------------|------|
| 1 | /chat、/test/stream、test-run、Celery 行为一致 | 🟡 |
| 2 | 封禁经 `invoke_agent`，生产不依赖 mock | 🟡 |
| 3 | 无业务层直调 `HermesAgentExecutor` / `build_agent_graph` | 🟡 |
| 4 | `run_agent_decision` 仅剩转发或为零 | 🟡 |
| 5 | `engine=langgraph` 仅 warning，实际 Hermes | ✅ |
| 6 | `soc_decision` 满足 condition_branch | 🟡 |
| 7 | 封禁 E2E + mock 降级 | 🟡 |
| 8 | `ban_risk_analyze` 与 `REQUIRED_FIELDS` 一致 | ✅ |

---

## 4. 变更记录（仅本文）

| 日期 | 说明 |
|------|------|
| 2026-09-23 | 初版：从 Week 1 实施与代码评审同步；方案文档保持 v1.1 不动 |
| 2026-09-23 | Week 1 完成 + W1-补；Week 2 代码：W2-⑤/⑥/⑥b/⑦ + `BAN_ANALYST_AGENT_ID` |

---

## 5. 更新说明（给维护人）

1. 完成任务后：改 §2 对应行「状态」+ 可选「备注 / 证据」（PR 链接、commit）  
2. 同步更新 §3 总体验收表中相关行  
3. **不要**为了省事去改 `LangGraph → Hermes 统一.md` 里的状态勾选  
4. 若发现方案本身有误：先提方案修订（统一.md 升 v1.2+），再改代码与本文
