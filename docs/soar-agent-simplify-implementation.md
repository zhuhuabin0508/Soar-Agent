# SOAR 智能体「收复杂度」优化实现说明（给 Cursor 执行）

> 用途：本文件是给 Cursor 按步骤改代码用的实现说明。
> 总体思路：**能力保留、默认接管、界面收敛** —— 把 Hermes 引擎的复杂能力隐藏/默认化，前端建智能体收敛成"模型+角色+工具+知识库"四个心智，不删能力、不推倒重做。
> 原则：改动要可逐步验证、可回退；每阶段有明确文件和验收标准。

---

## 阶段总览（建议按序执行，每阶段可独立验证）

| 阶段 | 内容 | 对应痛点 | 风险 |
|------|------|---------|------|
| V2.1 | 统一工具（来源打标 + 高级选项折叠） | 工具杂乱无法统一管理 | 低（前端展示为主） |
| V2.2 | 启用知识库（内置种子 + 空状态引导 + 检索可观测） | 知识库未启用 | 低 |
| V2.3 | 智能体向导化（AgentEditor 收敛成四心智 + 模板） | 搭建繁琐杂乱 | 中（前端大改） |
| V2.4 | 工作流闭环（AI 生成草稿→审阅→固化） | 工作流没人用 | 高（需 AI 能力） |

> 建议先做 **V2.1 和 V2.2**（低风险、见效快），V2.3/V2.4 在两者稳定后再做。

---

## 阶段一：V2.1 统一工具（来源打标 + 高级选项折叠）

### 目标
工具列表一眼可辨「内置 / 自建 / 框架」来源；研判类智能体默认看到关键工具（不被 tool_search 误藏）；工具行为的高级项默认收起。

### 改动 1A：工具列表来源徽章
- **文件**：`frontend/src/pages/ToolList.jsx`
- **现状**：已有分类分组（`CATEGORY_META` / `groupToolsByCategory`），但缺"来源"展示。
- **改动**：
  - 在工具行/卡片上，根据工具字段展示来源徽章：
    - `is_preset === true` → 徽章「内置」
    - `tool_type === 'framework'` → 徽章「框架」
    - 其余 → 徽章「自建」
  - 在 `TOOL_TYPE_META` / 筛选处增加"来源"筛选维度（内置/自建/框架）。
- **验收**：工具列表每个工具能看出是内置/自建/框架，且可按来源筛选。

### 改动 1B：后端工具列表返回来源字段
- **文件**：`backend/app/api/v1/tools.py`、`backend/app/api/v1/tools_manage.py`
- **现状**：`Tool` 模型已有 `is_preset`、`tool_type` 字段，确认序列化输出是否包含。
- **改动**：确保列表/详情返回包含 `is_preset`、`tool_type`（用于前端徽章判断）；若已包含则跳过。
- **验收**：前端能读到这两个字段。

### 改动 1C：研判类智能体默认不隐藏关键工具（收敛 tool_search）
- **文件**：`backend/app/agent/hermes/tool_search.py`、`backend/app/agent/hermes/tool_engine.py`
- **现状**：`tool_search` 会动态延迟挂载非核心工具（`is_deferrable_by_source`），威胁情报/封禁等工具可能被隐藏。
- **改动**：将"研判类核心工具"默认改为不延迟（`tool_search` 默认 `off` 或 `auto` 但核心工具永载）；把 `_NEVER_DEFER` 工具集合显式列出。
- **验收**：研判智能体的工具列表始终能看到威胁情报/封禁等关键工具。

### 改动 1D：工具行为高级项折叠（AgentEditor）
- **文件**：`frontend/src/pages/AgentEditor.jsx`
- **现状**：工具行为配置（timeout/retry/require_confirm/tool_search/guardrails 等 `tool_configs`）直接可见，复杂。
- **改动**：包进一个默认**折叠**的「高级选项」折叠面板；默认不展开。
- **验收**：默认界面简洁，高级项在折叠面板内可展开。

---

## 阶段二：V2.2 启用知识库（内置种子 + 引导 + 可观测）

### 目标
知识库从"0 数据、无用法"变成"有内容、有引导、检索可见"。

### 改动 2A：内置知识库种子
- **文件**：`backend/app/core/kb_service.py` 或新增 `backend/app/core/kb_seed.py`
- **改动**：提供 1~2 个开箱知识库（如「安全响应规范」「常用研判口径」），在初始化时写入 seed 文档并向量化。
- **验收**：新建环境后知识库列表能看到内置库，且能被检索。

### 改动 2B：知识库空状态引导
- **文件**：`frontend/src/pages/KnowledgeBase.jsx`
- **改动**：知识库为空时，展示"三步建库：上传文档 → 自动分段/向量化 → 在智能体中勾选启用"引导 + 示例文档入口。
- **验收**：空库时出现清晰引导。

### 改动 2C：AgentEditor 知识库联动提示
- **文件**：`frontend/src/pages/AgentEditor.jsx`
- **现状**：`abilityTab` 已有 knowledge Tab。
- **改动**：在勾选知识库处显示每个库的文档数/最近更新；若一个库都没选，给出引导链接到知识库页。
- **验收**：勾选集成了库信息展示，未选时有引导。

### 改动 2D：检索可观测
- **文件**：调试面板/相关组件
- **改动**：在调试输出中展示知识库检索命中的片段与来源（kb 名/文档），让用户看到"知识库生效了"。
- **验收**：调试时能看到检索命中信息。

---

## 阶段三：V2.3 智能体向导化（四心智收敛 + 模板）

### 目标
建智能体从"面对十几个配置项"变成"四步：基础 → 角色 → 能力 → 行为"，并支持模板一键创建。

### 改动 3A：AgentEditor 分步向导化
- **文件**：`frontend/src/pages/AgentEditor.jsx`
- **现状**：单页超大表单，已用 Section/abilityTab 分组，但所有项堆在一屏。
- **改动**：顶部化为 **4 步向导**（可点击切换、可分别保存草稿）：
  1. 基础信息（名称/描述/头像/开场白/引导问题）
  2. 大脑与角色（选模型、系统提示词、人物设定、语气/变量）
  3. 挂能力（工具/技能/知识库/资产类型，复用现有 abilityTab）
  4. 行为与记忆（温度/轮数/记忆/引擎/高级选项）+ 调试
- **验收**：能按四步完成建智能体，每步可保存，不丢失现有字段。

### 改动 3B：导航分层收敛
- **文件**：`frontend/src/components/AppShell.jsx`
- **现状**：智能体/工作流/技能/工具/知识库 平铺在「智能体编排」下。
- **改动**：重组为三层子分组：
  - 执行：智能体、工作流（含触发规则）
  - 能力：工具
  - 内容：技能、知识库
- **验收**：侧边栏分层清晰，层级一目了然。

### 改动 3C：模板库
- **文件**：后端加 seed（`backend/app/core/seed.py` 附近）+ 前端 `AgentList.jsx` 或新建创建向导
- **改动**：预置模板（告警研判员 / 封禁决策员 / 资产分析员 / 自定义）；列表页"从模板创建"一键生成再微调。
- **验收**：能从一个模板一键创建智能体。

---

## 阶段四：V2.4 工作流闭环（AI 生成草稿→审阅→固化）

> 难度最高，先做 PoC。这是"工作流没人用"的根治：让用户用一句话生成流程，而不是从零拖拽。

### 改动 4A：AI 生成编排草稿
- **文件**：`backend/app/agent/hermes/`（可复用 Hermes 的 plan/工具能力）+ 新增草稿 API `backend/app/api/v1/workflows.py` 附近
- **改动**：用户在对话/调试中用自然语言描述流程 → 后端生成结构化编排草稿（步骤+工具+依赖），**持久化到草稿表**（新增 `Draft` 模型或复用 execution 记录）。
- **验收**：一句话能生成可保存的流程草稿。

### 改动 4B：草稿库 + 审阅/固化
- **文件**：前端新增草稿页（列表 + 简单编辑），编辑可换节点/工具；`WorkflowList.jsx` / `WorkflowEditor.jsx` 打通
- **改动**：草稿可编辑 →「定稿」发布为对话智能体 或 流程/触发。
- **验收**：草稿可被审阅、编辑、发布。

### 改动 4C：工作流体系对齐
- **文件**：`frontend/src/components/AppShell.jsx`
- **改动**：导航上将「触发规则」作为封禁工作流的触发配置子项呈现，消除"通用工作流 vs 封禁工作流"两套体系的混淆。
- **验收**：工作流导航层级清晰、不混淆。

---

## 给 Cursor 的执行建议

1. **一次只做一个阶段**，每阶段完成后跑验证：
   - 前端改动 → `cd frontend && npm.cmd run dev`（当前已在 http://localhost:8080 运行）看 UI。
   - 后端改动 → 看 `docker logs soar-backend-dev`（uvicorn --reload 会自动热重载）。
2. **不要删 Hermes 引擎里的高级能力**；只做"默认化/折叠/隐藏"，能力函数保留。
3. **向后兼容**：`Agent` / `Tool` / 现有字段都保留，只新增展示字段（如来源徽章用已有 `is_preset`/`tool_type`）。
4. **涉及搜代码的关键词**：`tool_search` / `is_deferrable_by_source` / `enabled_asset_types` / `search_assets` / `tool_configs` / `abilityTab` / `CATEGORY_META` / `groupToolsByCategory`。
5. 每阶段改动不大时，优先改动前端展示层（风险低），后端收敛（search_assets 双轨、tool_search）需单独回归研判/封禁链路。

---

## 附：现状关键信息（供 Cursor 定位）

- 后端运行：`soar-backend-dev`(127.0.0.1:8001)，LangGraph+LangChain 底座，Hermes 自研壳 `backend/app/agent/hermes/`。
- 前端运行：Vite http://localhost:8080，页面 `frontend/src/pages/`。
- 导航：`frontend/src/components/AppShell.jsx`。
- 工具模型：`backend/app/models/tool.py`（含 category/tags/tool_type/is_preset/http_config）。
- 智能体模型：`backend/app/models/agent.py`（含 enabled_tools/enabled_kbs/enabled_skills/enabled_asset_types/tool_configs/engine/mode 等）。
- 技能模型：`backend/app/models/skill.py`。
- 知识库后端：`backend/app/core/kb_service.py` / `kb_retriever.py` / `kb_file_query.py`，API 在 `backend/app/api/v1/knowledge_base.py`。
- 工具分类常量：`frontend/src/constants/toolCategories.js`。
