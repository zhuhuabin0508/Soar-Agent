# SOAR 智能体 V2.0 详细实施方案（整合细化版）

> 用途：把《总方案》《双用户设计》《收复杂度实现》《开源调研》整合为**可直接执行**的详细计划。
> 每项给出：文件、现状（已核实）、改动、验收。
> 原则：复用现状、不动 Hermes 引擎、前端优先、分阶段可验证。

---

## 〇、整合视角（承接各文档）

| 方案文档 | 贡献到本文的内容 |
|---------|----------------|
| `soar-agent-v2-master-plan.md` | 总框架：双用户分层 + 全模块双入口 + 交付闭环 + V2.1~V2.5 路线 |
| `soar-agent-dual-user-design.md` | 小白向导 / 开发者 DSL 的交互与前端页面设计 |
| `soar-agent-simplify-implementation.md` | "收复杂度"的实现顺序（打标/折叠/默认接管） |
| `open-source-reference-survey.md` | 借鉴点：n8n 草稿闭环、Copilot/Coze 小白体验、Dify 生命周期、Shuffle 领域模型 |

**统一原则（贯穿本文件）**：
1. 每个模块都有 **小白 / 开发者双入口**。
2. **不删 Hermes 能力**，只收敛暴露面 + 默认接管。
3. **后端数据大多已具备**，改前端为主、后端少量加接口。
4. 分阶段、可回退、每阶段可验证。

---

## 一、V2.1 统一工具（含双入口 + 收复杂度）

### 现状（已核实）
- 后端 `GET /tools`（`tools_manage.py:list_tools`）通过 `to_dict_list` 全列序列化，**已返回 `is_preset`/`tool_type`/`category`/`tags`** ——来源打标的后端数据**已现成**。
- 前端 `ToolList.jsx` 已有分类分组（`CATEGORY_META`/`groupToolsByCategory`）与 FilterBar，但**缺来源徽章**。
- `tool_search` 默认 `auto`（`tool_search.py:default_tool_search_config`），会按 source 延迟挂载。

### 小白入口（工具）
1. **新建工具引导**（`ToolEditor.jsx`）：
   - 现状：直接让选 tool_type（code/http/framework），非开发者困惑。
   - 改：新建首屏先问"你要做什么？"三选（接 API / 写代码 / 选现成），**推荐"接 API"（http 声明式）给小白**；code/framework 标注"开发者用"。
   - 验收：小白能按引导建 http 工具。

### 开发者入口（工具）
2. **保留 code / framework 全能力**：`ToolEditor` 的 code 编辑与 http 精细配置保留给开发者；前端给 code/framework 加"开发者"徽章。

### 收复杂度（工具）
3. **来源徽章**（`ToolList.jsx`，纯前端）：
   - 数据已现成（`is_preset`/`tool_type`）。
   - 在行/卡片按规则渲染徽章：`is_preset`→「内置」，`tool_type==='framework'`→「框架」，其余→「自建」。
   - 增加来源筛选维度（内置/自建/框架）。
   - 验收：列表来源可辨、可按来源筛选。**后端零改动。**

4. **研判类关键工具不隐藏**（`tool_search.py`，谨慎）：
   - 现状：`auto` 下非核心 source 可能延迟。
   - 改：新增"核心永载工具名集合"（威胁情报/封禁/白名单/资产等），在 `is_deferrable_by_source` 或装配处强制不延迟；**不要一刀切 off**（会伤上下文）。
   - 验收：研判/封禁智能体关键工具始终在列。**需回归研判/封禁链路。**

5. **工具行为高级项折叠**（`AgentEditor.jsx`）：`tool_configs`（timeout/retry/confirm/tool_search/guardrails）收进默认折叠的「高级选项」面板。

---

## 二、V2.2 启用知识库（含双入口）

### 现状（已核实）
- 后端能力齐备：`kb_service.py`/`kb_retriever.py`/`kb_file_query.py` + `api/v1/knowledge_base.py` 完整 CRUD。
- 库里知识库为 0、无内置内容、无前端引导。

### 小白入口（知识库）
1. **空状态引导**（`KnowledgeBase.jsx`）：三步建库（上传文档→自动分段/向量化→在智能体勾选）+ 示例文档。
2. **一键上传即用**：上传文档后自动走既有分段/embedding，无需配置索引等专业项（默认即可）。
3. **AgentEditor 勾选联动**（`AgentEditor.jsx`）：显示每库文档数/最近更新；未选时给引导链接。

### 开发者入口（知识库）
4. **精细管理**：保留/开放 chunk 分段参数、embedding 模型、索引模式等高级配置（折叠在"高级"）。
5. **内置种子库**（后端）：提供 1~2 个开箱库（"安全响应规范"等），初始化写入并向量化。

### 收复杂度（知识库）
6. **检索可观测**：调试面板显示命中片段与来源，让用户看到"知识库生效"。

> 本迭代为纯增量：不改引擎、不改模型；新增种子 + 前端引导 + 高级折叠。

---

## 三、V2.2/V2.3 智能体双入口

### 现状（已核实）
- `frontend/src/constants/agentTemplates.js` 已有告警研判员/封禁决策员等模板 + `stashAgentTemplate` 预填机制。
- `AgentList.jsx` 已有"从模板创建"弹窗入口。
- `AgentEditor.jsx`（2656 行）单页，已有 `abilityTab`、Section 折叠。

### 小白入口（智能体）
1. **新建改为"模板选择第一屏"**（`App.jsx` 路由 + `AgentList.jsx`）：
   - 点"新建智能体"先进模板卡片页（复用 `AGENT_TEMPLATES`），底部次级入口"从零开始(高级)"。
   - 验收：小白新建先看到模板，不直接面对空表单。

2. **极简向导 `AgentQuickCreate.jsx`**（新页面）：
   - 三步：①选模板 ②填名称/角色/勾工具（默认按模板）③可选挂知识库（显示文档数）→完成。
   - 提交现有 `POST /agents` 的 Agent 对象。
   - 验收：小白 ≤3 步建好可用智能体、全程不直视画布。

### 开发者入口（智能体）
3. **AgentEditor 简单/高级切换**（`AgentEditor.jsx`）：
   - 顶部"简单/高级"开关；简单视图只露 模型+角色+工具+知识库；高级视图=现状完整表单。
4. **代码/DSL 视图**（新增 + 后端接口）：
   - 前端：`AgentCodeEditor.jsx` 把 Agent 配置序列化成 YAML/JSON。
   - 后端：`agents.py` 加 `POST /agents/from-dsl`、`GET /agents/:id/dsl`。
   - 验收：开发者能用 DSL 建/改智能体。

---

## 四、V2.4 工作流双入口 + AI 生成（根治"没人用"）

### 现状（已核实）
- `WorkflowEditor.jsx` 三栏 IDE 布局；`NodeLibrary.jsx` 节点库杂乱；无冷启动引导。
- `WorkflowList.jsx` 需要看是否有"从模板"引导（待补 AI 生成草稿）。

### 小白入口（工作流）
1. **新建为先模板/一句话**（`WorkflowList.jsx`）：
   - 三选：从模板复制 / 用一句话生成（AI）/ 从零开始(高级)。
   - 验收：小白新建不直接进空白画布。

2. **AI 生成草稿 → 审阅 → 固化**（核心，借鉴 n8n）：
   - 后端：复用 Hermes plan 能力，新增草稿 API（草稿表 `Draft` 或复用 execution），输入自然语言 → 生成节点草稿。
   - 前端：草稿库（列表 + 简单编辑：换节点/工具）+「定稿」发布为流程/触发。
   - 验收：一句话生成可保存、可发布的流程草稿。

### 开发者入口（工作流）
3. **DSL/JSON 编辑**：工作流 nodes/edges 可 JSON/YAML 导入导出（新增视图，可选）。

### 收复杂度（工作流）
4. **画布降级为高级入口**：三栏编辑器从"主入口"变为"进阶/开发者"入口（默认新建走向导/模板）。
5. **体系对齐**（`AppShell.jsx`）：导航上「触发规则」作为封禁工作流的触发配置子项，消除两套混淆。

---

## 五、V2.3/V2.5 技能 + 全模块交付闭环

### 技能双入口
- **小白**：从技能库选现成（角色设定/流程/SOP 分类），`SkillList.jsx` 加"从模板/推荐"。
- **开发者**：`SkillEditor.jsx` 直接写 prompt 文本 + 变量 `{{key}}`（保留现状）。

### 交付闭环（开发者→小白）
1. **发布为模板**：开发者把成品"另存为模板"（进共享/模板库）。
2. **按用户/角色授权**：复用 `resource_shares`（已覆盖 agent/workflow/tool/skill/kb 五模块）；扩展支持按 role。
3. **模板市场/我的共享**：小白向导的模板列表数据源 = 内置模板 + 共享给我的。
4. **只读隔离**：交付资源可只读/授权，防小白误改。
   - 后端：`resource_shares.py` 加"只读/可编辑"粒度（可选）。

---

## 六、落地执行顺序表（给 Cursor）

| 步 | 迭代 | 详细改动 | 风险 | 依赖 |
|----|------|---------|------|------|
| 1 | V2.1 | 工具来源徽章（前端，数据现成）；工具新建引导；高级项折叠 | 低 | 已具备 |
| 2 | V2.2 | 知识库空态引导 + 内置种子 + AgentEditor 联动 + 检索可观测 | 低 | 已具备 |
| 3 | V2.2/V2.3 | 智能体模板第一屏 + `AgentQuickCreate` 极简向导 | 低 | `AGENT_TEMPLATES` |
| 4 | V2.3 | AgentEditor 简单/高级切换 | 中 | — |
| 5 | V2.3 | 开发者 DSL（前端视图 + 后端 `/from-dsl`、`/dsl`） | 中 | — |
| 6 | V2.4 | 工作流：模板/一句话入口 + 草稿库 + 发布 | 中 | Hermes plan、草稿表 |
| 7 | V2.4 | 画布降级高级 + 工作流体系对齐 | 低 | — |
| 8 | V2.5 | 技能双入口 + `resource_shares` 按 role + 模板市场接入 | 低/中 | 交付闭环 |

> 关键路径：1→2→3（先小白主链路）→6（工作流闭环）→5（开发者 DSL）→8（交付闭环）。

---

## 七、给 Cursor 的硬约束
1. **不动** `backend/app/agent/hermes/` 引擎（仅 tool_search 1 处谨慎收敛除外）。
2. **后端数据已具备**：工具 `is_preset/tool_type`、`resource_shares` 五模块授权、`AGENT_TEMPLATES` —— 先复用再新增。
3. **新增后端接口集中**：DSL(`/from-dsl`,`/dsl`)、草稿(Draft)、resource 按 role、模板发布。
4. 前端 dev http://localhost:8080、后端 uvicorn --reload 热重载，改完即可验。
5. 每阶段向后兼容，不删现有路由/字段。
