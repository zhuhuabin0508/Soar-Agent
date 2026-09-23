# 基座性能与稳定（展开）

**基座优先**与**性能与稳定**已写在 `CONSTITUTION.md`。本文是展开，不是唯一出处。不得为单个场景更快而削弱护栏。

---

## 1 护栏

- 写操作必须沿用 Guardrail / 审批 / 熔断。禁止 LLM 输出直接变成不可逆处置。
- 新增工具不得绕过 `guardrails.py` / `threat_scanner` / 脱敏与消息清洗。`untrusted` 结果按不可信包装。

## 2 并发与吞吐

- 禁止在工具 `run()` 里写并发或限流。写工具 barrier。限流只接到 `tool_dispatch` 与 `limiter.py`。
- 长任务（扫描、大 KB 索引、批量排查）进 Celery，禁止在 Web/Hermes 热路径同步跑。
- 多告警并发遵守 `budget.py` 与 `model_call_monitor`，避免打满事件循环和数据库。

## 3 上下文与模型

- 超预算结果要截断/持久化，禁止灌满 LLM 上下文。
- 遵守 `IterationBudget`、上下文压缩、`tool_search` 渐进披露。
- 不得为场景关掉 `model_health_scheduler` 的健康检查与降级。

## 4 审计

- 新能力必须能在 `/executions`（及既有 `audit.py` / 模型调用监控）回放。禁止只留在 SSE 气泡。
- 日志带 `agent_id` / `execution_id` / `instance_id`。禁止打密钥。

## 5 回归

- 改运行时 / 封禁 / 发布门禁 / 并发 / 工具调度：`backend/tests/` 至少一条失败用例。
- 批量/并发改动建议对比改动前后耗时再合入。

---

## 场景固化

1. `list_skills` / `list_tools` / `list_agents` 查重。
2. 拆成 Skill + Tool + Agent 绑定。
3. 建工具前 `test_tool_code`。
4. 跑通后走 `ensure_builtin_skills` 一类 seed 登记，供其它 Agent 勾选。
5. Skill 写法：目标、前置、步骤、判据、止损；不掺运行时代码。调设备工具前须已绑定对应设备 SOP Skill。
6. 新场景是组合，优先于给基座加新引擎。基座不够时先补 Hermes 工具调度、`skill_engine`、审批、审计，禁止另起执行链。
