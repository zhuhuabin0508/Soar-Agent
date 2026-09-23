# AI 编码与生成规范

当 Agent 被派去 **生成 Skill / Tool / Agent 配置** 或 **编写将进入 `create_tool` 的 Python** 时遵守本文。仓库内改基座代码另守 `CONSTITUTION.md` + `STYLE.md`，不要用「禁止改执行器」挡基座研发角色（见 `README.md` 角色表）。

目标：产出可复核、不破坏基座、能过安全审查的能力，而不是能跑就行。

---

## 一、角色

- **场景组装 Agent**：只允许写工具代码、Skill 文本、Agent 配置、绑定。禁止改 `hermes/executor.py`、`guardrails.py`、`tool_dispatch.py`，禁止加框架。
- **基座研发 Agent**：可以改公共运行时，但禁止为单个场景在执行器加 if/elif；高风险（Guardrail、审批、并发、发布门禁）必须人审后合入。
- 两种角色都是执行者不是决策者。无痕改动禁止。边界不清必须停下问人。

## 二、生成工具代码硬红线

- 创建前 `list_tools` / `list_skills` / `list_agents` 查重。名称唯一小写下划线，禁止与预设冲突。`created_by` 与时间留痕。
- code 工具：先 `test_tool_code`（AST 安全审查 + 编译 + `async def run(**kwargs)`），通过后才能 `create_tool`。直接改进仓库定义时等价跑 `validate_tool_code`。
- `parameters_schema` 为 `[{name,type,required,description}]`，`description` 写给 LLM 何时调用。返回可序列化 dict。
- 禁止：`eval` / `exec` / `__import__` / 动态 import；子进程；直接文件系统；socket / 自行网络外连；绕过 import 白名单。设备 HTTP 只走已有 runner + `/devices`。
- 禁止硬编码 URL / 密钥；禁止 `print`；禁止在 `run()` 里自行并发/限流。
- `create_tool` / `create_skill` / `create_agent` 必须走现有 `_check_permission`，禁止冒充身份。

## 三、强制流程（场景生成）

1. 盘点：list 查重，有则复用。
2. 拆解：怎么想 → Skill；做什么 → Tool；谁来做 → Agent 绑定。
3. 建工具：`test_tool_code` → `create_tool`（须管理员权限）。
4. 建 Skill：纯文本 SOP（目标/前置/步骤/判据/止损），不带运行时代码。
5. 建 Agent：`engine=hermes`，默认草稿，工具按 id/name，Skill 按 id。
6. 固化：跑通后登记 seed / `ensure_builtin_skills` 一类机制，禁止每次再生成一份。

## 四、权限

- 写操作类工具必须接 Guardrail / 审批 / 熔断，禁止生成绕过护栏直接处置的代码。
- 渗透 / 扫描单独权限包，默认不进研判 Agent。禁止默认给运营平铺 bash / 改库能力。

## 五、交工清单

- [ ] `test_tool_code` / `validate_tool_code` 通过
- [ ] 命名未冲突；`created_by` 正确
- [ ] 无密钥 / `.env` / 敏感报文入库
- [ ] 写操作不绕过 Guardrail；不新增对话引擎
- [ ] 结构化日志；Pydantic 合同（改 API 时）
- [ ] 改运行时/封禁/并发/门控时 `backend/tests/` 至少一条失败用例
- [ ] 不新增空列、不预加 semver / MCP / 插件市场

## 六、熔断

- 破坏底座 / 绕过门控 / 引入新框架 / 大规模无关改动：拒绝合入、回滚、向人说明。
- 运行时、Guardrail、审批、并发不得由 AI 单独放行。
- 同一处反复失败：停止更激进的改法。
- 异常时保基座，不让单个场景先跑起来。
