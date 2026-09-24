# LLM 底座 + 设备工具化 —— 分阶段落地方案（终版执行稿）

> 定位：一份**面向交付执行**的分步骤、分阶段落地方案。基于 `docs/architecture/soar架构方案.md`(v1.3) 的定稿结论，以及双方(Codex 初稿 ↔ Cursor 审阅)讨论后的最终裁决编排而成。
> 原则：**不删除任何既有内容**；本稿为新增执行稿，矛盾时以 `docs/architecture/soar架构方案.md` v2.0 定稿 / 本稿「定稿决策表」为准。
> 前置阅读：`docs/architecture/soar架构方案.md` §13(阶段计划)、§15(验收)、§20(评审记录)、附录 B(工具统一管理)；`docs/architecture/待办与开工清单.md`。

---

## 0. 前置共识（两方讨论已定稿，直接照做）

| 决策点 | 定稿结论 | 来源 |
|--------|---------|------|
| 设备工具形态 | **C：动作级投影为主 + 门面 `device_action` 兜底 + 枚举工具** | soar方案 §6.4 |
| 写工具判定 | **`tool_source=device` 或 `device_` 前缀**，兼容 `device_action` | soar方案 §6.4 / §7.3 |
| 执行统一 | **一律 DeviceGateway**，禁止旁路 `run_http_tool` 直打设备 | soar方案 §6.3/§6.7 |
| 统一管理 | **不用 MCP**；内置/设备/外部同一装配(tool_engine)+分来源(tool_source) | soar方案 §5.5、附录 B |
| 远程对接服务 | **阶段 3**；阶段 1 本地 Gateway | soar方案 §20.4 |
| 幂等 | 阶段 1 `idempotency_key`；阶段 2 `correlation_id` | soar方案 §6.5 |
| `block_ip` 治理 | 语义 `block_ip`(Gateway 薄封装)+ `block_ip_on_firewall` 转发，避免治理链失效 | soar方案 §6.8、§21.2#1 |
| 投影命名 | `device_{device_id}_{action_id}`(用 action_id 防同 type 多动作冲突) | soar方案 §21.2#7、验收#11 |
| `enabled_devices` | 阶段 1 新增 ORM 字段(设备 id 列表) | soar方案 §5.5 |
| `device` source | `types.py` 增 `TOOL_SOURCE_DEVICE` | soar方案 附录 B.5 |

---

## 1. 三条硬性门禁（阶段不可抢跑）

1. **阶段 0 未完成，不得启动阶段 1** 设备工具注册（避免双运行时 + 契约漂移）。
2. **设备执行必须经 DeviceGateway**——不允许新的第四套 httpx 直连路径。
3. **写工具治理键是元数据/前缀，不是硬编码工具名**——新增写工具无需再改名单。

---

## 2. 阶段 0：基座收口（必须最先完成）

**任务**
- 封禁研判 Hermes Agent：`ban_risk_analyze` 契约 + 只读工具 + `LLMConfig` 就绪。
- `invoke_agent` + 双适配器（`soc_decision` / `ban_risk_analyze`）。
- 封禁 `agent_client` 迁移至 `invoke_agent`（保同步语义、重试、`agent_invocation_logs`）。
- `/chat` 与 `/test/stream` 对齐（共用 Hermes SSE）。
- `engine` 默认 `hermes`（`langgraph` 仅 warning）。

**产出**：`invoke_agent` 全链路可用；`BAN_ANALYST_AGENT_ID` 就绪。
**验收**：soar方案 §15 #6、#7；进度勾选见 `@docs/architecture/LangGraph → Hermes 实施进度.md`。

> 注意：本阶段**不做**大范围设备改造，避免与收口互相干扰。

---

## 3. 阶段 1：设备工具化（约 1～2 人周，本方案的执行主体）

按依赖顺序拆成 **7 个小步**，每步有独立产出与验证点。

### 1.1 DeviceGateway（统一执行缝）
- 新建 `DeviceGateway.invoke(db, device_id, action_id|action_type, params, ctx)`。
- 包装 `execute_device_action`；统一写 `DeviceCallLog`；支持 `idempotency_key`(重复请求返回已有结果)。
- **收敛**：`node_executors.device_action`、`devices.py` 动作测试、`banned_ips` 全部改调 Gateway，删除内联 httpx。
- ✅ 验证：三条调用路径的 DeviceCallLog.source 正确(workflow/manual_test/api)。

### 1.2 投影 + 枚举 + 门面（`devices/as_tool.py`）
- `list_devices`、`list_device_actions(device_id?)` 只读枚举(仅 `enabled=True` 且 `status=online`)。
- 动作级投影：`device_{device_id}_{action_id}`，`parameters_schema` 取自 `params_schema`。
- 门面 `device_action`(device_id + action_type + params)兜底。
- ✅ 验证：LLM 可先 `list_device_actions` 拿到合法 id 再调投影工具(验收#3)。

### 1.3 工具注册与治理键泛化
- `tool_engine._register_device_tools()` 加载设备工具(独立于 `_register_db_tools`)。
- `types.py` 增 `TOOL_SOURCE_DEVICE`。
- 治理链(`verification`/`tool_dispatch`/`tool_result_classification`)从「按名 `device_action`」泛化为「`tool_source==device` 或 `device_` 前缀」。
- ✅ 验证：投影工具 + 门面都进 verification/barrier(验收#8)。

### 1.4 语义 block_ip 与命名收敛
- 语义工具 `block_ip`(Gateway 薄封装) + 默认设备解析；`block_ip_on_firewall` **转发**至 `block_ip`(不强行改名)。
- 修复治理链「认 `block_ip`、真实工具 `block_ip_on_firewall`」缺口(soar §21.2#1)。
- ✅ 验证：语义 `block_ip` 无默认设备时返回明确错误，不静默 Mock(验收#10)。

### 1.5 Agent 装配字段 `enabled_devices`
- `Agent` 新增 `enabled_devices: list[int]`；API + 前端「勾选设备」。
- 投影工具名由平台生成，用户不记忆工具名。
- ✅ 验证：UI 勾设备即把该设备已启用动作装配进工具。

### 1.6 工作流节点对齐
- 工作流 `device_action` / `block_ip` 节点改调 Gateway(与 Agent 工具同 L1)。
- ✅ 验证：工作流与对话下发的 L1 与审计一致(验收#2)。

### 1.7 阶段 1 收尾与冒烟
- 高频写动作优先投影，读/枚举可延迟(接入 `tool_search` 分级，见附录 B)。
- 冒烟：对话一句话封 IP、工作流自动封禁、手动封禁三条路径一致。

**阶段 1 过渡说明**：设备工具经 `tool_engine` 直接注册(过渡态)；阶段 2 收敛为 `ToolRegistryBuilder` 单一工厂后删除重复注册逻辑。

---

## 4. 阶段 2：工具运行时统一

- `invoke_tool(name, args, ctx)` 统一工具执行入口。
- `ToolRegistryBuilder`：Builtin / Code / Http / Device / OpenApi Provider。
- Celery ai_agent 经 `invoke_agent`；工具测试经 `invoke_tool`。
- `DeviceCallLog.correlation_id` 关联 `agent_invocation_logs`。
- `internal` 鉴权、S-lite egress 白名单。
- ✅ 验收：soar方案 §15 #9(无双工厂重复注册)。

---

## 5. 阶段 3：扩展与演进(按需)

- 外部设备服务 → HTTP 工具批量注册(远程执行形态)。
- 全量动作投影、动作投影缓存失效策略收敛。
- 声明式 `ToolProviderManifest`（插件包，演进项）。
- 未来若接入第三方 MCP Server ➜ 用 `types.py` 预留 `mcp` source（非当前优先级）。

---

## 6. 每阶段负责人与依赖速查

| 阶段 | 前置依赖 | 主要产出 | 可并行项 |
|------|---------|---------|---------|
| 0 | — | invoke_agent 收口 | — |
| 1.1 | 0 | DeviceGateway | — |
| 1.2 | 1.1 | 投影/枚举/门面 | 与 1.3 的 types.py 可并行 |
| 1.3 | 1.1 | 注册 + 治理泛化 | — |
| 1.4 | 1.1/1.3 | block_ip 收敛 | 与 1.5 可并行 |
| 1.5 | 1.2 | enabled_devices + UI | — |
| 1.6 | 1.1 | 工作流节点对齐 | — |
| 2 | 1.x | invoke_tool / Builder | — |
| 3 | 2 | 外部服务/Manifest | — |

---

## 7. 两方讨论的修正痕迹记录（保留，不删除）

> 为保留讨论过程，以下列出「初稿观点 → 裁定结论」；**不修改任何旧文档**，仅作留痕与溯源。

| # | 初稿观点(Codex) | 裁定(经 Cursor 审阅 + 代码核验) | 落点 |
|---|----------------|-------------------------------|------|
| 1 | 设备工具注册进 `_register_db_tools` | 改为独立 `_register_device_tools`（设备工具动态物化，不查 Tool 表名） | §3.1.3 |
| 2 | 解耦边界「唯一入口 = ToolCatalog + run_http_tool」 | 统一装配 + 分来源；执行统一经 DeviceGateway | soar §5.5/附录B |
| 3 | 方案 A「设备动作完全物化为 HTTP 工具走 run_http_tool、零胶水」 | **反驳**：绕过 Gateway 审计，鉴权在 Device 表 | soar §6.7/§16 |
| 4 | 命名 `device_{id}_{action_type}` | 改 `device_{id}_{action_id}`（防同 type 多动作冲突） | soar §21.2#7 |
| 5 | 「所有工具都在同一张 Tool 表」 | 区分持久化(builtin/security/custom) vs 运行时物化(KB/资产/工作流/设备) | soar 附录 B.2 |
| 6 | 早期把 framework 工具当普通 DB 工具 | framework 由 Hermes executor 注入/拦截，非 `_register_db_tools` 执行 | soar §21.2#6 |
| 7 | 未识别 `block_ip` 治理缺口 | 治理链认 `block_ip`，真实工具 `block_ip_on_firewall`——已核验属实，阶段1修复 | soar §21.2#1、§3.1.4 |

---

## 8. 验收清单汇总（可直接勾选）

- [ ] 阶段 0：invoke_agent / ban_risk_analyze / 研判执行分离完成
- [ ] 1.1 DeviceGateway 收敛三条路径，source 正确
- [ ] 1.2 LLM 经 `list_device_actions` 枚举后下发（不硬编码 id）
- [ ] 1.3 投影+门面工具均过 verification/barrier
- [ ] 1.4 语义 block_ip 无默认设备不静默 Mock
- [ ] 1.5 enabled_devices 字段 + UI 勾选生效
- [ ] 1.6 工作流/对话/API 设备下发一致
- [ ] 阶段 2 invoke_tool + ToolRegistryBuilder + correlation_id
- [ ] 阶段 3 外部 HTTP 服务 / Manifest（按需）
