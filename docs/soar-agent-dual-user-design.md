# SOAR 智能体「双用户分层」产品交互设计（给 Cursor 执行）

> 用途：按"小白用户 + 开发者"两类用户，重构智能体/工作流的搭建入口，让小白不需要面对复杂画布，开发者可直接代码。
> 现状依据：已有 `frontend/src/constants/agentTemplates.js`（AGENT_TEMPLATES，含告警研判员/封禁决策员等）+ `AgentList.jsx` 已有"从模板创建"入口 + `App.jsx` 路由 + `AgentEditor.jsx`（2656 行）+ `WorkflowEditor.jsx`（三栏编辑器）。
> 原则：**复用现有模板/表单基建，不改 Hermes 引擎**；把"重"的 UI 藏成高级/开发者入口。

---

## 一、产品分层模型（核心）

| 用户 | 身份 | 搭建复杂度 | 主入口 | 界面形态 |
|------|------|-----------|--------|---------|
| **小白** | 有专业能力的运营/业务人员 | 简单好用 | **向导 + 模板 + 一句话生成** | 极简引导式，**全程不直视画布** |
| **开发者** | 你们（开发） | 复杂 | **代码/DSL** | 代码优先视图，弱化可视化 |

**核心原则**：
- 小白**默认进入"极简搭建"**，不接触三栏画布；
- 现有三栏可视化编辑器**降级为"高级模式"**（小白隐藏，开发按需进）；
- 开发者最终落点**代码/DSL**，可视化画布不是刚需。

---

## 二、小白入口：极简搭建（新增/重构）

### 目标
`新建智能体/工作流` 对小白是"选模板 → 填几步 → 完成"，全程入口即导航，不出现空白画布。

### 改动 A1：新建主入口改为"模板选择 + 引导创建"
- **文件**：`frontend/src/App.jsx`（路由）、`frontend/src/pages/AgentList.jsx`、`frontend/src/pages/WorkflowList.jsx`
- **现状**：`AgentList` 已有"从模板创建"按钮弹窗（用 `AGENT_TEMPLATES` + `stashAgentTemplate`）。
- **改动**：
  - 把"从模板创建"从弹窗提升为**新建的第一屏**：点"新建智能体"先进入"模板选择页/卡片"，而非直接进空 `AgentEditor`。
  - 模板卡片展示：图标 + 名称 + 一句话说明 + 适用场景；底部有"从零开始（高级）"次级入口。
  - 工作流同样：新建先进入"模板 + AI 生成 + 从零（高级）"的选择。
- **验收**：小白新建时先看到模板，不直接面对空白表单/画布。

### 改动 A2：创建一个"极简向导组件"（复用现有表单字段）
- **文件**：新增 `frontend/src/pages/AgentQuickCreate.jsx`（或改造 `AgentList` 内嵌）
- **改动**：三步极简向导，**不显示 Hermes 高级配置**：
  1. 选模板（默认选中 AGENT_TEMPLATES）
  2. 填 4 个必备字段：名称、角色/职责一句话（写进 system_prompt）、开场白(可默认)、勾选要用的工具（默认已按模板勾好，只做增减）
  3. 可选挂知识库（显示每个库文档数）+ 完成
- **数据**：最终落成一个 `Agent` 表单对象（复用 `AGENT_TEMPLATES` 的 form 预填 + 用户改动），提交到现有 `POST /agents`。
- **验收**：小白能 3 步完成建一个可用智能体，全程不到 5 个字段。

### 改动 A3：一句话生成（可选，V2.4 前置）
- **文件**：后端复用 Hermes plan 能力，新增草稿 API；前端在 quick create 里加"用一句话描述我想要什么"
- **改动**：输入自然语言 → 生成模板/配置建议 → 预填表单。若暂不做，可在向导里留占位按钮。
- **验收**：一句话能生成可编辑的创建表单（PO PT）。

---

## 三、可视化编辑器降级为"高级/开发者模式"

### 目标
三栏编辑器（`WorkflowEditor` / `AgentEditor` 完整模式）不再作为小白默认入口，收进高级入口。

### 改动 B1：隐藏/位移高级入口
- **文件**：`frontend/src/pages/AgentList.jsx`、`WorkflowList.jsx`
- **现状**：可直接"新建"进入 `WorkflowEditor`（空白画布）或 `AgentEditor`。
- **改动**：
  - 列表页"新建"主按钮 = 极简向导（改动 A1/A2）。
  - "从零开始 / 高级模式 / 开发者"作为**次级灰字链接**放入向导底部或列表页二级菜单。
- **验收**：默认新建走向导；高级入口不显眼但可达。

### 改动 B2：AgentEditor 支持"简 / 高级"两种视图开关
- **文件**：`frontend/src/pages/AgentEditor.jsx`
- **现状**：2656 行单页，所有配置项堆在一起；已有 `abilityTab`、Section 折叠。
- **改动**：
  - 顶部加"简单 / 高级"切换。
  - **简单视图**：只暴露 模型 + 角色 + 工具(默认按模板) + 知识库 四块（新增一个精简视图分支）。
  - **高级视图**：现在的完整表单（保留，供开发者）。
- **验收**：同一 Agent 可在简单/高级两种视图间切换，字段不丢失。

---

## 四、开发者：代码优先视图（新增）

### 目标
开发者搭复杂智能体直接写代码/DSL（YAML/JSON），比可视化更快、可版本化。

### 改动 C1：新增"代码/DSL 编辑视图"
- **文件**：新增 `frontend/src/pages/AgentCodeEditor.jsx` + 后端 `api/v1/agents.py` 加 DSL 导入/导出
- **改动**：
  - 提供一个文本编辑视图，把 Agent 配置（system_prompt、tools、kbs、skills、温度、记忆、tool_configs 等）序列化为 **YAML/JSON** 供编辑。
  - 提供"导入 DSL 创建智能体 / 当前智能体导出 DSL"。后端新增 `POST /agents/from-dsl`、`GET /agents/:id/dsl`（或复用现有 model 序列化）。
- **验收**：开发者能用 DSL 文件创建/更新智能体，无需点表单。

### 改动 C2：工作流同样支持 DSL/JSON（可选）
- **文件**：`WorkflowEditor` 或新增代码视图
- **改动**：工作流定义（nodes/edges）以 JSON/YAML 编辑，可导入导出。
- **验收**：开发能用代码定义工作流节点。

> 注：若你们开发已习惯直接写代码/JSON，这一步成本最低、收益最高——可视化画布甚至可以只读展示。

---

## 五、落地路线（给 Cursor 顺序执行）

| 步 | 内容 | 文件 | 风险 |
|----|------|------|------|
| 1 | 新建入口改为"模板选择"（先智能体，后工作流） | `App.jsx`、`AgentList.jsx`、`WorkflowList.jsx` | 低 |
| 2 | 新增极简向导 `AgentQuickCreate.jsx`（复用 AGENT_TEMPLATES.form） | 新增前端 | 低 |
| 3 | AgentEditor 加"简单/高级"切换 + 简单视图只露 4 块 | `AgentEditor.jsx` | 中 |
| 4 | 新增代码/DSL 视图 + 后端 DSL 导入/导出 | 新增前端 + `agents.py` | 中 |
| 5 | 可视化编辑器降级为高级入口 | 列表页 | 低 |

> 先做 1-2（小白主链路），再做 3（高级开关），4（开发者 DSL）按需。

---

## 六、给 Cursor 的执行注意

1. **复用** `AGENT_TEMPLATES`、`stashAgentTemplate`、`AGENT_TEMPLATE_STORAGE_KEY`，不要重造模板。
2. 现有路由 `/agents/new`、`/agents/:id/edit`、`/editor` 保留，只是入口改到向导/高级。
3. **不动** `backend/app/agent/hermes/` 引擎；只动前端入口 + `api/v1/agents.py` 加 DSL 接口（可选）。
4. 前端 dev 已在 http://localhost:8080 运行，改动后可直接看。
5. 保持新建链路向后兼容：小白向导最终提交的都是现有 `POST /agents` 的 Agent 对象。

## 附：现状关键文件速查
- 模板：`frontend/src/constants/agentTemplates.js`
- 列表：`frontend/src/pages/AgentList.jsx`、`WorkflowList.jsx`
- 编辑器：`frontend/src/pages/AgentEditor.jsx`、`WorkflowEditor.jsx`、`frontend/src/components/FlowCanvas.jsx` 等
- 路由：`frontend/src/App.jsx`
- 智能体模型：`backend/app/models/agent.py`；API：`backend/app/api/v1/agents.py`
