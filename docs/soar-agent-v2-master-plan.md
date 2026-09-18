# SOAR 智能体体系 第二代（V2.0）迭代优化总方案

> 状态：**总方案定稿，供评审与分阶段实施**。
> 覆盖：智能体 / 工作流 / 工具 / 技能 / 知识库 全模块。
> 顶层理念：**双用户分层 + 全模块双入口 + 开发到交付闭环**，并结合"收复杂度"（能力保留、默认接管、界面收敛）。
> 配套：`docs/soar-agent-simplify-implementation.md`（实现说明）、`docs/soar-agent-dual-user-design.md`（双用户交互设计）、`docs/open-source-reference-survey.md`（开源调研）。

---

## 一、顶层产品理念（一句话）

**两类用户、两条搭建路径、覆盖全部编排模块、开发到交付闭环：**
- **小白用户**：无基础，想搭适合自己的智能体提效 → 用**极简入口**（向导 / 模板 / 一句话生成）自建。
- **开发者（你们）**：收集用户问题 → **用代码开发**智能体/工作流/工具 → **交付给用户使用**（授权/发布共享）。

**这一原则贯穿全部模块**：智能体、工作流、工具、技能、知识库，每个都保留"小白简单方式 + 开发者代码方式"两条扩展路径。

---

## 二、双用户分层模型

| 用户 | 身份 | 搭建复杂度 | 主入口 | 界面形态 |
|------|------|-----------|--------|---------|
| **小白** | 运营/业务人员（无编程） | 简单好用 | 向导 + 模板 + 一句话生成 | 极简引导式，**不直视画布/代码** |
| **开发者** | 你们（开发） | 复杂 | 代码 / DSL / 精细配置 | 代码优先视图，可版本化 |

**交叉点**：小白自建的成果可沉淀为模板/共享；开发者交付的成果由小白"使用"。
**视觉原则**：底层复杂能力（Hermes 12+ 项）保留并默认接管，界面只露"干什么"。

---

## 三、全模块双入口矩阵（核心交付物）

| 模块 | 小白入口（极简） | 开发者入口（代码/精细） | 复用/新建 |
|------|-----------------|----------------------|----------|
| **智能体** | 三/四步向导：选模板 + 填角色 + 勾工具 + 挂知识库（`AgentQuickCreate.jsx`） | 代码/DSL 编辑视图（YAML/JSON），`POST /agents/from-dsl` | 复用 `AGENT_TEMPLATES` |
| **工作流** | 模板 / 一句话生成（AI 出稿→审阅）；常用流程一键复制 | JSON/YAML DSL 编辑，导入导出 | 复用现有 workflow 模型 |
| **工具** | 简单声明式（http 工具：填 URL/参数即可用） | 写 Python 代码（code 工具）+ framework | 复用 `Tool` 模型（tool_type） |
| **技能** | 从现成技能库选（角色设定/流程/SOP） | 直接写 prompt 文本 + 变量 | 复用 `Skill` 模型 |
| **知识库** | 上传文档即用（自动分段/向量化） | 精细管理：分段/索引/embedding/多库 | 复用 `kb_service` |

**关键**：每一个模块都在**同一个心智**下提供"小白/开发者"两个入口，避免"智能体易用、工具却很技术"的割裂。

---

## 四、开发到交付闭环（新增打通）

### 现状（已具备的有利基础）
- 后端已有完整 `resource_shares` 机制（`api/v1/resource_shares.py`），`resource_type` 白名单覆盖 **agent / workflow / tool / skill / knowledge_base** 全部五模块（按 user 授权共享）。
- 已有 `AGENT_TEMPLATES` 模板 + `stashAgentTemplate` 预填机制（`frontend/src/constants/agentTemplates.js`）。

### 交付闭环设计
1. **开发者开发**：用代码/DSL 或高级模式完成智能体/工作流/工具制作。
2. **发布为模板**：开发者将成品"另存为模板"（进入共享/模板库），或通过 `resource_shares` 按 **user / role** 授权给目标用户。
3. **小白使用**：小白在"极简向导"的模板列表 / 我的共享里看到可用资源，一键采用或授权使用。
4. **沉淀回库**：小白自建或使用中调优的成果可反向沉淀为模板，形成生态。

### 待补
- **模板市场入口**：把"共享/模板"提升为小白向导的主要数据源（`GET` 共享模板列表）。
- **角色级授权**：`resource_shares` 目前按 user，可扩展按 role（或复用现有 RBAC）。
- **"交付即隔离"**：开发者交付的资源可只读/只授权，避免小白误改。

---

## 五、工作流编排专项方案（含"工作流创建没人用"根治）

### 5.1 问题根因（UI 层面，已代码核验）
- `WorkflowEditor.jsx` 是三栏工程化布局（顶部工具栏 + 左节点库 + 中画布 + 右属性面板），是开发者 IDE 形态。
- `NodeLibrary.jsx` 一堆节点 + 大量分类图标，空画布无冷启动引导 → 小白"看一眼不想搭"。

### 5.2 分层方案
| 层 | 适用 | 形态 |
|----|------|------|
| **小白** | 简单流程 | 模板 + AI 生成草稿（一句话）→ 几乎不用进画布 |
| **进阶** | 中等 | 现有三栏画布（默认收起，作为高级/进阶入口） |
| **开发者** | 复杂 | JSON/YAML DSL 直接编辑 |

### 5.3 一句话生成工作流（借鉴 n8n AI Workflow Builder）
- 用户在向导输入"当收到告警后，研判源 IP，若高风险则封禁并通知值班" → 后端（Hermes plan 能力）生成节点草稿。
- 草稿库：列表 + 简单编辑（换节点/工具）；「定稿」发布为流程/触发。
- 需新增：草稿表(Draft) 或复用 execution 记录 + 草稿 API。

### 5.4 工作流体系对齐
- 导航上将「触发规则」作为封禁工作流的触发配置子项呈现，消除"通用工作流 vs 封禁专用"两套混淆。

---

## 六、AI/能力层：收复杂度（贯穿全模块）

- **工具**：来源打标（内置/自建/框架）、研判类默认不隐藏关键工具（tool_search 收敛）、高级项折叠。
- **知识库**：内置种子库、空状态引导、AgentEditor 联动、检索可观测。
- **智能体**：AgentEditor 分"简单/高级"视图、四心智收敛、模板库。
- **不删能力**：Hermes 的委派/护栏/预算/验证/威胁扫描等全部保留为默认接管。

---

## 七、落地路线（分阶段，给 Cursor 执行）

| 迭代 | 范围 | 内容 | 验收 | 优先级 |
|------|------|------|------|--------|
| **V2.1** | 统一工具 + 启用知识库 | 工具来源打标/分组、tool_search 收敛；内置知识库、引导、检索可观测 | 工具可辨、不再是 0 知识库 | 高（地基） |
| **V2.2** | 双用户入口·小白 | 新建入口改模板选择、`AgentQuickCreate` 极简向导、AgentEditor 简单/高级切换 | 小白 3 步建智能体、不直视画布 | 高（主链路） |
| **V2.3** | 开发者代码视图 + 交付 | DSL 导入导出、模板发布、resource_shares 按 role、模板市场入口 | 开发者代码建、交付给指定用户 | 中 |
| **V2.4** | 工作流闭环 | AI 生成草稿→审阅→固化、工作流模板、体系对齐 | 一句话生成可发布流程 | 中（难度高） |
| **V2.5** | 全模块双入口齐平 | 工具/技能/知识库的"小白/开发者"双入口补全 | 五模块都有双入口 | 低（收尾） |

> 建议顺序：V2.1 → V2.2 → V2.3 → V2.4 → V2.5。V2.1/V2.2 是可先行的低风险部分。

---

## 八、给 Cursor / 实施的关键注意

1. **复用而不是重造**：`AGENT_TEMPLATES`、`stashAgentTemplate`、`resource_shares`、`Tool.tool_type`、现有 `Agent`/`Workflow`/`Skill`/`KB` 模型都已具备。
2. **不动 Hermes 引擎**（`backend/app/agent/hermes/`）：只做界面收敛 + 入口重构 + 少量后端接口（DSL、草稿）。
3. **双入口后端落地资产准备**：
   - `POST /agents/from-dsl`、`GET /agents/:id/dsl`；
   - 工作流 DSL 导入导出；
   - 草稿表(Draft) + 草稿 API（V2.4）；
   - `resource_shares` 扩展按 role（V2.3）。
4. **前端 dev** 在 http://localhost:8080 运行、后端 uvicorn --reload 热重载，改完可直接验证。
5. 每阶段向后兼容，不删现有字段/路由。

---

## 附：现状关键文件速查
- 模板：`frontend/src/constants/agentTemplates.js`、`stashAgentTemplate`
- 列表/入口：`frontend/src/pages/AgentList.jsx`、`WorkflowList.jsx`
- 编辑器：`frontend/src/pages/AgentEditor.jsx`(2656行)、`WorkflowEditor.jsx`、`components/FlowCanvas.jsx`、`NodeLibrary.jsx`
- 路由：`frontend/src/App.jsx`；导航：`components/AppShell.jsx`
- 共享授权：`backend/app/api/v1/resource_shares.py`、`models/resource_share.py`
- 模型：`backend/app/models/agent.py`、`tool.py`、`skill.py`、`workflow.py`、`knowledge_base.py`
- 引擎：`backend/app/agent/hermes/`（不动）
- 知识库：`backend/app/core/kb_service.py`、`kb_retriever.py`、`kb_file_query.py`
