# 项目背景与架构

第二层：回答「这是什么、为什么这样设计」。未写明的边界按本节意图判断，并遵守 `CONSTITUTION.md`。

拍板过程见 `docs/agent-architecture-debt-and-plan.md`。本文只保留稳定意图。

---

## 项目定位

这是 **网安（SOAR）背景下的 Agent 平台地基**，不是某一个写死的场景产品，也不是 Dify 式跨行业 Bot 工作室。

- **谁用**：安全运营 / 研判分析师 / 可搭剧本的工程师。
- **拼什么**：各网安场景下的智能体或工作流（研判封禁、告警调查、资产排查、设备 SOP、弱口令材料等）。
- **样板**：IP 研判与封禁闭环证明 Agent + 工作流 + 审批能跑通；后续场景复用同一运行时，不新开引擎。
- **基座**：Hermes、工具分发、告警入库、审批熔断必须稳定可预期。场景用配置和内置 Skill 表达，不改地基。

## 核心抽象

| 概念 | 定义 | 关系 |
|------|------|------|
| Agent | 一次研判/对话执行者 | 引用 Skill / Tool / KB / 资产类型 / 工作流 |
| 系统提示词 | 角色与总目标 | 组装时注入 Skill |
| Skill | 平台级纯文本 SOP | 不产生动作；教怎么想 |
| Tool | code / http / framework 动作 | 按 id/name 绑定，定义一次多方复用 |
| KB | 检索型知识 | 启用后生成检索工具 |
| Workflow | 节点编排剧本 | 可调 Agent 或 Tool；封禁专用链是样板 |

Skill 是平台级资产。场景差异用绑定表达，禁止 fork Skill 代码。脚本必须是 Tool。

## 分层

```
场景组装     工作室搭 Agent/工作流；运营中心跑对话、审批、封禁实例
运行时       Hermes ReAct；工作流 DAG（LangGraph）
安全原生能力 告警入库、资产、设备、情报/封禁工具、审批熔断、审计
```

- 场景层只组装，不实现第二套封禁引擎。
- 运行时不直接 import 防火墙 SDK。
- 能力层不关心哪个 Agent 在用。
- 新场景两条路：工作室勾选；或生成内置 Skill 并按工具名绑定。两条路都不许改 Hermes 主循环。

## 已拍板决策

| 决策 | 理由 |
|------|------|
| 用户可见只留 Hermes | 双引擎会双写 SSE、发布门禁、工具加载 |
| LangGraph 只做工作流 DAG | 封禁节点与可视化编排已建在这套上 |
| 不嵌 Dify | 已有护栏/委派/预算；当核会丢掉并引入跨行业抽象 |
| Skill = 提示词注入 | 避免技能包变成第二套工具运行时 |
| 工具按 id/名绑定 | fork 会导致同一封禁动作多份实现 |
| 封禁链 + 通用工作流并存 | 封禁需要熔断/实例/触发；其它场景用 Studio |
| 内网 HTTP 为主 | MCP 不是接入前提 |
| 不预加空列 | 无读取方的 schema 会腐烂 |
| 场景不进执行器 | 基座要给所有场景共用 |

未采用黑板架构：现有 ReAct + DAG 已覆盖研判与编排。热路径：对话 SSE、工具 barrier、发布门禁必须一致；长任务进 Celery。

## 领域模型

领域中心是告警 / 资产 / 处置；Agent 是执行者。

| 对象 | 含义 | 落点 |
|------|------|------|
| Alert | 设备解析后的告警 | `/alerts`、入库、触发规则 |
| Ban instance | 封禁样板案例 | 封禁工作流实例、熔断、时间线 |
| Asset | 资产 / CMDB | `/assets*` |
| Device | 安全设备与连接 | `/devices`、解析策略 |
| IOC / 情报 | 指标查询 | `get_threat_intel` 等 |
| Execution | 一次运行账本 | `/executions`（主路径）；过程日志可落 `execution_logs` |
| Approval | 写操作裁决 | `/approvals`、Guardrail、熔断 |

运营读/写工具应出现在研判默认集合附近：`check_whitelist`、`search_assets`、`get_threat_intel`、`block_ip_on_firewall`、`record_ban`、`calculate_ban_duration`。

## 目录约定

| 路径 | 放什么 | 不放什么 |
|------|--------|----------|
| `rules/` | 本母本 | 工具私有第二套宪法 |
| `backend/app/api/v1/` | HTTP 路由 | 工具 `run`、ReAct 主循环 |
| `backend/app/schemas/` | Pydantic 合同 | 页面 |
| `backend/app/models/` | ORM | 再堆 `security.py` 的 `ADD COLUMN`；新迁移走 Alembic |
| `backend/app/agent/hermes/` | ReAct、dispatch、guardrails | `decision.py` 私有工具工厂 |
| `backend/app/core/tools/` | 工具目录与种子 | 执行器主循环 |
| `backend/app/workflow/` | 工作流与封禁节点 | 前端 |
| `backend/app/engine/` | 告警解析 | Agent ReAct |
| `backend/app/tasks/` | Celery | 同步 API 内核 |
| `frontend/src/pages/` | 页面 | 跨页共享（放 `components/`） |
| `docs/` | 讨论文稿、施工单 | 宪法与 STYLE |

`decision.py` 只许转发到公共工具层。

## 侧栏即产品

| 侧栏 | 路由 | 作用 |
|------|------|------|
| 运营 | `/dashboard` `/approvals` `/chat` | 结果、审批、已发布 Agent 对话 |
| 封禁样板 | `/ban-workflow/rules`、封禁工作台 | 告警 → 研判封禁，含熔断 |
| 工作室 | `/studio`、工具 / 技能 / KB | 搭各网安 Agent 与通用工作流 |
| 资产 | `/assets*` | CMDB |
| 设备对接 | `/devices` `/strategies` `/alerts` | 告警从哪来 |
| 账本 | `/executions` | 运行回放 |

新增能力先问：运营是否要在上述入口看见它。不要只在某张页里埋入口。
