# SOAR 智能体 V2.0 激进改造执行单（直接给 Cursor 改代码）

> 定位：交给 Cursor 直接修改代码的执行单。激进落地"双用户 + 双入口 + 收复杂度"，满足要求即可。
> 重要：**先核实后动手**——下列每项都标注了【Y=已具备/已实现】或【N=缺失/需做】。Cursor 只做 N，Y 的不要重复造。
> 总原则：不动后端引擎 `backend/app/agent/hermes/`（除特别标注）；前端优先；向后兼容。

---

## ⚠️ 动手前先读（现状盘点：避免白干）

已核实存在（Y）：
- 工具来源徽章：`ToolList.jsx` 已有 `resolveToolSource` + `SOURCE_META`（builtin/framework/custom）+「类型/来源」列双徽章；后端 `GET /tools` 已返回 `is_preset`/`tool_type`。→ **来源打标已做，无需重做。**
- 智能体模板：`constants/agentTemplates.js`（含告警研判员/封禁决策员）+ `AgentList.jsx`「从模板创建」弹窗。
- 知识库引导：`KnowledgeBase.jsx` 已有欢迎引导页雏形。
- 资源授权：`resource_shares` 已覆盖 agent/workflow/tool/skill/kb 五模块。

待做（N）集中在下面各节。

---

## 一、智能体：新建入口优先"模板"（N，改 AgentList）
- 文件：`frontend/src/pages/AgentList.jsx`、`frontend/src/App.jsx`
- 现状（Y）：已有"从模板创建"弹窗，但点"新建"仍是直接进空 `AgentEditor`。
- 激进改法：
  1. 把"新建智能体"主按钮默认行为改为**先打开模板选择**（复用现有 `templateOpen` 弹窗），仅在模板弹窗里提供"从零开始(高级)"次级入口直达 `/agents/new`。
  2. 模板卡片丰富：图标 + 名称 + 一句话 + 适用场景标签（`AGENT_TEMPLATES` 已有字段）。
- 验收：点"新建"先看到模板卡片，能一键进模板预填；"从零开始"仍可达。

---

## 二、智能体：极简向导 `AgentQuickCreate.jsx`（N，新增）
- 文件：新增 `frontend/src/pages/AgentQuickCreate.jsx`，路由加 `/agents/quick`
- 激进改法：三步向导，复用 `AGENT_TEMPLATES.form` + `stashAgentTemplate`：
  1. 选模板（高亮可预览）
  2. 填：名称、角色一句话（写 system_prompt）、可勾选工具（默认按模板）
  3. 可选挂知识库（显示文档数）+ 完成
  - 完成时：先 `stashAgentTemplate(模板)` 再跳 `/agents/new`（复用现有预填链路），或直接 POST 新建。
- 验收：小白 ≤3 步建好可用智能体，全程不直视画布。

---

## 三、智能体编辑器：简单/高级切换（N，改 AgentEditor）
- 文件：`frontend/src/pages/AgentEditor.jsx`
- 激进改法：页面顶部加"简单/高级"开关。
  - 简单视图：只显示 4 块 —— 基础信息、模型选择、角色(system_prompt)、能力(工具/知识库/技能/资产，复用现有 `abilityTab`)。
  - 高级视图：现状完整表单（保留，含 engine/记忆/tool_configs/变量/调试等）。
  - 用读取时切块渲染实现，**不删任何字段/状态**。
- 验收：同一 Agent 两种视图可切，字段不丢；默认进简单视图。

---

## 四、知识库：强化空态引导 + 智能体联动（部分做）
- 现状（Y）：`KnowledgeBase.jsx` 已有欢迎引导页。
- 激进改法（补强，N）：
  1. `KnowledgeBase.jsx` 空库时，引导文案明确"三步：上传文档→自动分段/向量化→在智能体勾选启用"，并给"上传"高亮入口。
  2. `AgentEditor.jsx` 知识库勾选处，显示每库文档数/最近更新；若一个都没选，给出"去知识库建库"链接。
- 验收：空库有清晰三步引导；建智能体时能看见库信息与引导。

---

## 五、工作流：新建入口"模板/一句话/从零"（N，改 WorkflowList）
- 文件：`frontend/src/pages/WorkflowList.jsx`、`frontend/src/App.jsx`
- 现状（N）：新建直接进 `/editor` 空白画布（这是"看一眼不想搭"的根因）。
- 激进改法：点"新建工作流"先弹"创建方式"选择：
  - ① 从模板复制（预置几个常用模板，如告警研判→封禁）
  - ② 用一句话生成（AI 出草稿，V2.4 能力，先做成占位/调用入口）
  - ③ 从零开始（进现画布）
- 验收：新建不直接进空白画布；有模板兜底。

---

## 六、工作流：AI 生成草稿 → 审阅 → 固化（N，V2.4 核心）
- 激进改法（后端 + 前端）：
  1. 后端：新增草稿模型 `Draft`（或复用 execution 记录）+ 接口：`POST /workflows/drafts/generate`（自然语言→节点草稿）、`GET/PUT /workflows/drafts/:id`、`POST /workflows/drafts/:id/publish`。
  2. 生成逻辑：复用 Hermes 的 plan 能力（`agent/hermes/` 内已有 plan/工具调度），把自然语言转成节点 JSON；不做 LLM 时可用规则生成骨架兜底。
  3. 前端：草稿库页（列表 + 编辑：换节点/工具）+「定稿发布」→ 落成 Workflow。
- 验收：一句话能生成可保存、可发布的流程草稿。
- ⚠️ 难度高，若时间紧可先做"规则化骨架生成 + 占位"，LLM 增强后补。

---

## 七、工作流：画布降级高级入口 + 体系对齐（N,低风险）
- 文件：`frontend/src/pages/WorkflowList.jsx`、`frontend/src/components/AppShell.jsx`
- 改动：
  1. 现有三栏 `WorkflowEditor` 作为"从零/高级"入口保留，不作为默认第一站。
  2. `AppShell.jsx` 导航：把「触发规则」作为封禁工作流的触发配置子项，避免"通用 vs 封禁"混淆（收敛层级）。

---

## 八、交付闭环：模板发布 + 按角色授权 + 模板市场（N, 后端为主）
- 现状（Y）：`resource_shares` 已按 user 覆盖五模块；`AGENT_TEMPLATES` 前端模板。
- 激进改法：
  1. 后端 `resource_shares.py`：支持按 role 共享（或在现有基础上加 shared_with_role 字段）。
  2. 新增"发布为模板"：开发者保存角色/工具/知识库配置为模板（落 DB 或复用 AGENT_TEMPLATES 动态化）。
  3. 小白模板列表数据源 = 内置模板 + 共享给我的（前端在导向上联 resource-shares + templates）。
- 验收：开发者建好可授权给指定用户/角色；小白能在模板列表看到并采用。

---

## 九、落地顺序（给 Cursor 按序执行，每步可验证）
1. 【一】智能体新建→模板第一屏（低风险）
2. 【二】新增 `AgentQuickCreate` 极简向导（低）
3. 【三】AgentEditor 简单/高级切换（中）
4. 【四】知识库空态补强 + 智能体联动（低）
5. 【五】工作流新建→模板/一句话/从零（低）
6. 【七】工作流体系对齐 + 画布降级（低）
7. 【八】资源按 role + 模板发布（中，后端）
8. 【六】AI 生成草稿闭环（高，最后/可分期）

> 1-5 优先做（都是前端、低中风险、能立刻看到"变简单"的效果）；6 低风险；7-8 后端；6/8 进阶。

---

## 十、给 Cursor 的硬约束
1. **不动** `backend/app/agent/hermes/` 引擎（V2.4 生成逻辑除外，可新增但别改引擎核心）。
2. **Y 项不重做**：来源徽章、模板弹窗、知识库引导页、resource_shares 五模块授权都已有，别推倒。
3. 所有改动 **向后兼容**：不删现有路由/字段/状态；简单视图只是"切块渲染"，不破坏高级视图。
4. 前端改完看 dev（http://localhost:8080）；后端加接口后看 uvicorn --reload 与日志。
5. 新增接口集中在：DSL/草稿/按 role 授权/模板发布（`agents.py`、`workflows.py`、`resource_shares.py`）。
