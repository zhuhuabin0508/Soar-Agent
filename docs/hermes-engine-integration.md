# Hermes-Agent 架构集成方案

## Context（为什么做这个改动）

用户要求 1:1 对标 Hermes Agent 架构，在现有 Soar 平台上构建 Hermes 级的智能体引擎底座。经深入研究 Hermes 源码（`D:\trae project\Soar Agent\hermes-source\hermes-agent-main`），得到三个**纠正性结论**：

1. **Hermes 的 Skill 是纯文本指令（SKILL.md），不是 DAG 状态机**。这恰好是上一轮已实现的能力（`backend/app/agent/prompt_assembler.py` + `models/skill.py` + `api/v1/skills.py`）。用户设想的「DAG + need_human_confirm + 中断恢复」其实是现有 **Soar 工作流系统**（已具备节点/条件/审批）。
2. **Hermes 的工具并行不是无脑 gather**，而是分段感知调度（`_plan_tool_batch_segments`）：把一批 tool_calls 拆成「并行安全段」与「顺序屏障段」，保留 emission 顺序。还有**不可信工具结果包装**（`<untrusted_tool_result>`）防 prompt injection。
3. **Hermes 是单用户 CLI**，Soar 是多用户服务端。记忆必须按 `(user_id, agent_id)` 分区，存储走 PostgreSQL 而非 SQLite/FTS5。

**用户已确认的三个决策**：(1) Skill 忠实方案——技能保持纯文本（已建），`HermesSkillEngine` 做成桥接器触发现有工作流；(2) 新增可选引擎——`backend/app/agent/hermes/` 包，Agent 加 `engine` 字段（默认 `langgraph`，零侵入）；(3) 全量范围——三大核心模块 + 上下文压缩 + 记忆系统 + 委派子代理。

**预期结果**：`engine=hermes` 的 Agent 走 Hermes 风格 ReAct 循环（分段并行工具、JSON 容错、SSE 流式、上下文压缩、多用户记忆、工作流技能中断/恢复、子代理委派）；`engine=langgraph`（默认）完全不变。

---

## 关键复用清单（已逐一核实存在，不得重写）

| 用途 | 现有文件:函数 |
|---|---|
| 技能注入（已建） | `app/agent/prompt_assembler.py:assemble_system_prompt` / `render_variables` |
| 工具构造 | `app/agent/decision.py:_build_db_tools` / `_build_kb_tool` / `_build_file_query_tool` / `_build_args_model` / `_load_llm_config` / `_extract_json_object` |
| 工具执行 | `app/core/tool_runner.py:run_tool` / `load_tool_function`；`app/core/tool_http_runner.py:run_http_tool` |
| OpenAPI 导入 | `app/api/v1/tools_manage.py:_parse_openapi_spec` / `_openapi_param_location` / `_openapi_param_type` / `_extract_operations_from_openapi` / `build_from_operation` |
| 工作流 DAG | `app/core/workflow_runner.py:run_workflow` / `resolve_variables` / `_get_nested` / `_build_node_input`；`app/core/dag.py:topological_sort` / `find_next_nodes`；`app/core/node_executors.py:execute_node` / `NODE_EXECUTORS` / `execute_human_review_node`（创建 `waiting_for_approval` Execution） |
| 审批信号 | `app/api/v1/approvals.py`（Redis `lpush` 到 `approval:{execution_id}`）；`app/core/redis_client.py:get_redis` |
| LLM 创建 | `app/core/llm_helper.py:create_llm_from_config` / `normalize_openai_base_url` |
| Celery | `app/core/celery_app.py:celery_app` |
| DB/迁移/权限 | `app/core/security.py:ensure_columns` / `run_lightweight_migrations`；`app/core/permissions.py`；`app/dependencies.py:require_permission` / `get_current_user` |
| SSE 模式 | `app/api/v1/agents.py:test_agent_stream`（事件类型 `start`/`token`/`done`/`error`/`log`/`message`/`status`） |

---

## 模块布局

新建 `backend/app/agent/hermes/` 包：

```
backend/app/agent/hermes/
├── __init__.py              # 导出 HermesAgentExecutor、sse_stream
├── types.py                 # ToolCall/ToolResult/ToolEntry/SkillContext/SSEEvent/IterationBudget
├── json_repair.py           # 剥离 ```json 围栏 + 复用 _extract_json_object + 截断补全
├── untrusted.py             # _maybe_wrap_untrusted / neutralize_delimiters（移植 Hermes）
├── tool_dispatch.py         # plan_tool_batch_segments（异步版分段策略）
├── tool_engine.py           # HermesToolEngine：工具注册表 + 分段并行执行
├── skill_engine.py          # HermesSkillEngine：把 Soar Workflow 作为可中断技能触发
├── skill_var.py             # {{node_id.output.field}} 变量抽取/替换
├── executor.py              # HermesAgentExecutor：ReAct while 循环 + 响应拦截 + 迭代预算
├── context_compressor.py    # token 阈值 + 滑动窗口 + LLM 摘要
├── memory_provider.py       # MemoryProvider 抽象基类 + PostgresMemoryProvider
├── memory_manager.py        # MemoryManager（多用户，按 user_id+agent_id 分区）
├── curator.py               # Celery 周期任务：记忆归档/合并
├── delegator.py             # Delegator：子代理派生（ContextVar 深度限制）
└── sse.py                   # SSEEvent dataclass + sse_stream 异步生成器
```

新增模型：`backend/app/models/agent_memory.py`（`AgentMemory` 表，按 user_id+agent_id 分区，PostgreSQL `to_tsvector` 全文索引）。

---

## 各模块设计要点

### 1. HermesToolEngine（`tool_engine.py` + `tool_dispatch.py` + `json_repair.py` + `untrusted.py`）

- **工具注册表**：构造时调 `decision._build_db_tools(db, agent.enabled_tools)` 拿 `StructuredTool`，抽取 `(name, description, args_schema, coroutine)` 存入 `ToolEntry` 注册表。KB 工具复用 `_build_kb_tool` / `_build_file_query_tool`。
- **分段并行调度**：`plan_tool_batch_segments(tool_calls)` 返回 `[("parallel", calls), ("sequential", calls)]`。规则：`block_ip`/`send_notification`/`delegate_task` 等写工具 = barrier；`check_whitelist`/`get_threat_intel`/`search_knowledge_base` 等只读 = parallel-safe；前缀 `query_`/`get_`/`list_`/`search_` = parallel-safe；未知 = barrier；并行段 <2 降级。**并行段用 `asyncio.gather(return_exceptions=True)`**（Soar 工具是 async，比 Hermes 的 ThreadPoolExecutor 更自然）；结果按 `original_index` 回填保证顺序。
- **JSON 容错**：`repair_json(text)` = 剥离 ```json 围栏 → 复用 `decision._extract_json_object`（已正确处理字符串/转义的平衡括号匹配）→ 截断时尝试补全。
- **不可信包装**：`maybe_wrap_untrusted(name, content)` 移植 Hermes `tool_dispatch_helpers.py:583-630`，把 `search_knowledge_base`/`query_kb_file`/`http_*`/`openapi_*` 工具结果包在 `<untrusted_tool_result source="...">` 中，并中和嵌入的分隔符 token（`untrusted-tool-result`）。防 prompt injection。
- **OpenAPI 动态装载**：`register_openapi(spec_text)` 复用 `tools_manage._parse_openapi_spec` / `_extract_operations_from_openapi` / `build_from_operation` 的纯函数逻辑，把操作转成内存态 `ToolEntry`（不入库，仅本次会话）。
- **工具结果格式**：`{"role":"tool","name":...,"tool_call_id":...,"content":...}`（OpenAI 兼容）。

### 2. HermesSkillEngine（`skill_engine.py` + `skill_var.py`）— 工作流桥接器

- 提供**虚拟工具** `trigger_workflow_skill`（参数 `workflow_id`/`input`/`resume_token`），LLM 可调用它启动一个 Soar 工作流作为子流程。
- `trigger_skill(workflow_id, payload)`：查 `Workflow(enabled=True)` → 创建 `Execution(trigger_type="agent_skill", agent_id=...)` → 调 `run_interruptible_workflow`。
- `run_interruptible_workflow`：复用 `workflow_runner.resolve_variables` / `_get_nested` / `_build_node_input` + `dag.topological_sort` + `execute_node` 遍历 DAG，**但在 `human_review` 节点处不阻塞**：创建审批工单后立即返回 `status="interrupted"`，把 `execution_id` 存入 `SkillContext.pending_approval`。
- `resume_skill(skill_run_id, decision)`：复用 Redis `brpop(f"approval:{execution_id}")` 等审批信号；approve → 继续下游节点；reject → 标记 failed。
- **变量传递**：`skill_var.render_node_vars(text, node_outputs)` 用正则 `\{\{\s*([\w-]+)\.output\.([\w.]+)\s*\}\}`（含 `.output.` 中缀，与 `prompt_assembler` 的 `{{word}}` 不冲突）替换 `{{node_id.output.field}}`。技能完成后各节点输出渲染回 Agent 上下文。
- 审批端点 `/approvals/{id}/approve` 已通过 Redis 发信号，**无需改动**。

### 3. AgentExecutor（`executor.py` + `sse.py`）

- **ReAct while 循环**：`run(user_input)` 是 async generator，yield `SSEEvent`。循环：预取记忆 → `while budget.consume():` 压缩上下文 → 调 LLM → 拦截响应 → 拼结果消息 → 同步记忆。预算耗尽时一次 grace call（注入「请基于已有信息给出最终回答」，与 Hermes 一致：不中途施压）。
- **响应拦截** `_handle_response`：纯文本且无 tool_calls → 结束；tool_calls 非空 → `tool_engine.execute_tool_calls`；含 `trigger_workflow_skill` → `skill_engine.trigger_skill`（遇中断 yield `skill_interrupt` 事件）；含 `delegate_task` → `delegator.spawn`。
- **SSE 事件契约**：`start`/`status`/`token`/`tool_start`/`tool_end`/`skill_interrupt`/`delegate`/`log`/`done`/`error`。新增类型是现有契约（`start`/`token`/`done`/`error`/`log`/`message`/`status`）的超集，前端兼容。
- **迭代预算** `IterationBudget`：移植 Hermes `iteration_budget.py`，单实例无需跨进程共享。

### 4. ContextCompressor（`context_compressor.py`）

- `maybe_compress(messages, llm)`：粗估 token（字符数/3.5，不引入 tiktoken），超 24000 阈值则保留 system + 最近 6 条，中间消息交 LLM 摘要为一条 `{"role":"system","content":"[历史摘要]..."}`。长工具结果（>2000 字符）单独摘要。在 `executor.run` 循环顶部调用。

### 5. MemoryManager（`memory_provider.py` + `memory_manager.py` + `curator.py` + `models/agent_memory.py`）

- **多用户适配**：`AgentMemory` 表按 `(user_id, agent_id)` 分区，所有查询带 `WHERE user_id=:uid AND agent_id=:aid`。存储走 PostgreSQL（不引入 SQLite/FTS5）。
- **检索**：PostgreSQL `to_tsvector('chinese', content)` + `ts_rank`（GIN 索引，迁移用原生 SQL `CREATE INDEX IF NOT EXISTS ... USING gin(...)`）。**降级方案**：若环境无中文分词配置，改用 `ILIKE` + `pg_trgm` 相似度。
- **MemoryProvider 抽象** + `PostgresMemoryProvider` 内置实现：`prefetch(query)` 返回相关记忆文本块注入 system prompt；`sync(messages)` 提取最后一条 user+assistant 写入；`on_session_end` 持久化。
- **MemoryManager**：`prefetch_all` / `sync_all` 用 `asyncio.gather` 并行多 provider。
- **Curator**：`@celery_app.task(name="hermes.memory.curate")` 周期任务（每天 3 点），清理 90 天未命中 + 合并相似条目。
- **异步 DB**：现有 `SessionLocal` 同步，Memory/Skill 内 DB 操作用 `asyncio.to_thread` 包装，不大改 `database.py`。

### 6. Delegator（`delegator.py`）

- 移植 Hermes `delegation_context.py` 的 ContextVar 模式（`_DELEGATE_DEPTH` / `_DELEGATE_CHILD`），**删除 Kanban env / 子进程逻辑**（Soar 纯同进程 async）。
- `spawn(task, max_iterations=10)`：检查 `current_depth() < MAX_SPAWN_DEPTH=3`，在 `delegated_child_context()` 中递归构造 `HermesAgentExecutor`（共享父 agent 配置，独立预算），结果作为 `{"role":"tool","name":"delegate_task",...}` 回灌。
- 暴露 `delegate_task` 虚拟工具给 LLM。

---

## Agent 模型与 API 改动（最小侵入）

### `backend/app/models/agent.py`
追加 `engine = Column(String(16), nullable=False, default="langgraph")`。

### `backend/app/core/security.py`
`agents` 表 `ensure_columns` 追加 `"engine": "VARCHAR(16) NOT NULL DEFAULT 'langgraph'"`；新增 `agent_memories` 表 GIN 索引原生 SQL。

### `backend/app/models/agent_memory.py`（新）+ `models/__init__.py` 注册
`AgentMemory` ORM（user_id/agent_id/session_id/content/summary/category/hit_count/timestamps）。

### `backend/app/api/v1/agents.py`
- `AgentBase` 加 `engine: str = Field("langgraph")`；create/update 同步赋值。
- `test_agent` / `test_agent_stream` 顶部加分支：`if agent.engine == "hermes":` → 走 `HermesAgentExecutor`，否则现有逻辑不变。
- 新增 `POST /{agent_id}/chat`（SSE，仅 hermes 引擎，`require_permission("agent","execute")`）。
- 新增 `POST /{agent_id}/skills/{skill_run_id}/resume`（恢复中断技能）。

### `backend/app/core/permissions.py`
`PERMISSION_MODULES["agent"]` 追加 `"execute"`；`DEFAULT_ROLES.analyst.agent` 追加 `"execute"`；前端 `utils/permissions.js` 同步。

### `backend/app/agent/hermes/__init__.py`
导出 `HermesAgentExecutor`、`sse_stream`。**所有对 `app.agent.decision`/`app.core.*` 的引用用延迟导入**（函数内 import）避免循环依赖。

---

## 验证计划

1. **回归（默认路径零影响）**：现有 `engine=langgraph` Agent 调 `/test` 与 `/test/stream`，行为与集成前完全一致（`decision.py`/`graph.py` 零改动）。
2. **engine 字段**：创建 `engine=hermes` Agent，`GET /agents` 确认字段持久化；其他 Agent 仍 `langgraph`。
3. **分段并行**：hermes Agent 启用 3 个只读工具（`check_whitelist`/`get_asset_info`/`get_threat_intel`），`POST /agents/{id}/chat` 流式触发，SSE 出现 3 个并行 `tool_start`→`tool_end`，日志可见 "parallel segment with 3 calls"；换 `block_ip` 验证串行。
4. **JSON 容错**：构造带 ```json 围栏的 LLM 响应，验证 `repair_json` 剥离并解析。
5. **不可信包装**：知识库注入含 `</untrusted_tool_result>` 的文档，验证结果被包装且分隔符中和为 `untrusted-tool-result`。
6. **工作流技能中断/恢复**：建含 `human_review` 节点的工作流；hermes Agent 调 `trigger_workflow_skill` → SSE 出 `skill_interrupt`（含 execution_id）→ `/approvals/{id}/approve` → `/agents/{id}/skills/{run_id}/resume` → 继续执行 `block_ip` → `done`。
7. **上下文压缩**：长对话（>24000 token）触发，日志出现 "compressing context"，后续 LLM 调用正常，token 数下降。
8. **记忆多用户隔离**：user A 对话「我叫张三」→ user B 问「我叫什么」→ B 得不到 A 的信息；`SELECT user_id, agent_id, content FROM agent_memories` 验证分区。
9. **委派**：hermes Agent 收到「分别查询 8.8.8.8 和 1.1.1.1」→ SSE 出 2 个 `delegate` 事件 → 汇总 `token` → `done`；深度超 3 拒绝。
10. **权限**：viewer 角色调 `/agents/{id}/chat` 返回 403（无 `agent.execute`）。

---

## 关键风险与缓解

1. **循环依赖**：`hermes/` 包内对 `app.agent.decision`/`app.core.*` 一律延迟导入（函数内 import）；`executor.py` 对 `skill_engine`/`delegator` 用构造函数注入。
2. **异步 DB session**：现有 `SessionLocal` 同步，Memory/Skill 内 DB 操作用 `asyncio.to_thread` 包装，不大改 `database.py`。
3. **PG 中文全文检索**：`to_tsvector('chinese', ...)` 需中文分词配置；降级用 `ILIKE` + `pg_trgm`。
4. **SSE 长连接**：响应头加 `X-Accel-Buffering: no` 禁用 nginx 缓冲。
5. **并发安全**：`SkillContext` 按 UUID `skill_run_id` 隔离，同 agent 多用户触发不冲突。

## 实施顺序

1. 基础设施：`types.py` + `models/agent_memory.py` + Agent.engine 字段 + 迁移 + 权限
2. `json_repair.py` + `untrusted.py` + `tool_dispatch.py`（纯函数，可单测）
3. `tool_engine.py`（依赖 1+2）
4. `skill_var.py` + `skill_engine.py`（依赖工作流系统）
5. `sse.py` + `executor.py`（依赖 3+4，最小可用：先不含 memory/compressor/delegator）
6. `agents.py` 路由分发 + `/chat` 端点 → 此时已可端到端验证 ReAct + 并行工具 + JSON 修复 + SSE
7. `context_compressor.py` + `memory_provider.py` + `memory_manager.py` + `curator.py` → 接入 executor
8. `delegator.py` → 接入 executor
9. 前端 `utils/permissions.js` 同步 `agent.execute`；AgentEditor 加 engine 选择
10. 全量验证（上述 10 项）
