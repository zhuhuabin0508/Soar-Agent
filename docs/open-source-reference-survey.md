# 可借鉴的开源项目调研清单（SOAR 平台大版本改造参考）

> 调研日期：2026-09-17。数据经 GitHub 官方 API/仓库/官方文档核实。目标：为 SOAR 安全智能体平台的"自然语言 → 工作流草稿 → 人工优化 → 发布成对话智能体或条件触发流程"改造，筛选可直接借鉴的开源项目。

---

## 一、结论先行（给决策用）

**既有现成开源平台，也有开源框架，分三类：**
- **可视化编排平台**（用户是运营人员，最该抄交互）：Dify、n8n、Langflow、Coze Studio、FastGPT、W5（国产开源 SOAR）。
- **安全专用 SOAR/自动化**（最同赛道，直接对标）：Shuffle、StackStorm、TheHive+Cortex、DFIR-IRIS。
- **Agent/编排代码框架**（做后台引擎）：LangGraph、AutoGen、OpenAI Agents SDK、CrewAI、Qwen-Agent、AgentScope。

**核心判断**：用户是安全运营人员（非开发者），所以**顶层交互抄"可视化平台"，底层运行引擎借"代码框架"**；"AI 生成编排草稿"目前业内最成熟的是 **n8n 的 AI Workflow Builder**，但它是 fair-code 非纯开源。

**最推荐的"组合拳"参考**（不是只抄一家）：
1. **n8n** — 抄"自然语言 → 草稿 → 人审 → 发布"全链路交互（AI 生成编排最强）；
2. **Shuffle** — 抄"安全工作流 + OpenAPI 工具接入 + 触发"的领域模型（唯一开源专业 SOAR，产品形态最像你要做的）；
3. **Dify** — 抄"Workflow(批处理)+Chatflow(对话) 双范式 + 应用草稿→调测→发布"的产品生命周期；
4. **LangGraph** — 抄后台运行引擎（图/状态机 + 持久化 + 人工审批 + 可审计）。

---

## 二、开源可视化编排平台（用户友好交互，优先抄）

| 项目 | Star | 许可 | 定位 | AI 生成草稿 | 推荐点 |
|---|---|---|---|---|---|
| **n8n** (n8n-io/n8n) | ~205k | fair-code | 可视化工作流 + 原生 AI + 400+ 集成 | **强（最完整）**：AI Workflow Builder 用自然语言创建/精修/调试工作流 | **AI 生成编排草稿这条线的最佳参照**；Chat Trigger 可直接当对话智能体发布；hanan-in-the-loop 人工确认 |
| **Dify** (langgenius/dify) | ~156k | 自定义（Apache 修改版，多租户/去 LOGO 需商业授权） | 一站式 LLM 应用平台，Workflow+Chatflow 双范式 | 弱/非主打（以手动拖拽为主） | 借鉴"应用草稿→调测→发布→监控"生命周期；许可对多租户商业化有风险，建议仅抄交互 |
| **Langflow** (langflow-ai/langflow) | ~155k | **MIT（最干净）** | 可视化 Agent/工作流，Python 组件生态 | 强（支持 NL→建 flow） | 开放协议 + Python 生态便于封装安全工具 + API/Webhook 触发；二次开发限制最少 |
| **Coze Studio** (coze-dev/coze-studio) | ~21.6k | 开源可自部署（Docker） | Coze 官方开源版，可视化 Agent 平台 | 部分 | "平台型"体验样本，插件/工作流/知识库整合完整 |
| **FastGPT** (labring/FastGPT) | ~29.7k | 开源 | 国产，可视化 AI 工作流编排 + 知识库 | 部分 | 中文友好，流程+文档研判型业务可参考 |
| **ByteDance FlowGram** (bytedance/flowgram.ai) | ~8.4k | 开源（部分企业版） | 工作流开发框架（画布/表单/变量底座） | 不主打 | 若打算**自研 SOAR 画布**，可作画布脚手架底座 |

---

## 三、开源安全 SOAR / 安全自动化（最同赛道，直接对标）

| 项目 | Star | 许可 | 定位 | 关键机制 | 推荐点 |
|---|---|---|---|---|---|
| **Shuffle** (Shuffle/Shuffle) | ~2.4k | AGPL-3.0 | **开源专业 SOAR**，安全自动化/编排 | 可视化节点工作流 + **OpenAPI/Swagger 自动生成 App**(FREAK) + 触发(WEBHOOK/SCHEDULE/MAIL/告警) + 案例管理 + 已在推 AI 生成 | **产品形态最像你要搭的东西，首推对标**；安全工作流+工具接入+触发机制现成 |
| **StackStorm** (StackStorm/st2) | ~6.5k | Apache-2.0 | 事件驱动自动化 "IFTTT for Ops" | 规则引擎(Trigger/Rule/Action) + 工作流 DSL(Orquesta) + 160+ 集成包、6000+ 动作 + ChatOps | **条件触发与规则引擎**的成熟工程范本；但无 AI、缺对话智能体 |
| **TheHive + Cortex** | ~3.9k / ~1.6k | AGPL-3.0 | 协作案件管理 + 可观测分析/响应引擎 | 案件建模 + Observable→Analysis + 响应器驱动主动响应 | 借鉴案件闭环与"分析器/响应器"动作抽象；注意官方已转向商业版 5 |
| **DFIR-IRIS** (dfir-iris/iris-web) | ~1.6k | LGPL-3.0 | 协作式事件响应(DFIR) 案件管理 | Case/证据/TTP 建模 + 模块化扩展 | 借鉴安全事件响应数据模型/案件闭环 |
| **W5** (w5teams/w5) | ~1.5k | GPL-3.0 | **国产开源低代码 SOAR**，面向中文安全运营 | 可视化剧本编辑器 + Trigger + App 封装 + 运维自动化 | 国内稀缺的真正开源 SOAR，UI 与交互最贴近中文运营用户；GPL 二次开发需开源回馈 |

---

## 四、Agent / 编排代码框架（做后台引擎参考）

| 项目 | Star | 许可 | 定位 | 推荐点 |
|---|---|---|---|---|
| **LangGraph** (langchain-ai/langgraph) | ~41.8k | MIT | 图状有状态 Agent 编排框架 | **SOAR 运行时形态的直接模板**：图/状态机 + checkpoint 持久化 + human-in-the-loop 人工审批 |
| **AutoGen** (microsoft/autogen) | ~61k | MIT | 微软多 Agent 编程框架 | 多 Agent 协商/图式编排可靠，作引擎层而非 UI |
| **OpenAI Agents SDK** (openai/openai-agents-python) | ~29.5k | MIT | OpenAI 官方轻量多 Agent 框架 | Agent+Handoff+Guardrail+Tool/MCP，Guardrail 可作**安全护栏**参考 |
| **CrewAI** (crewAIInc/crewAI) | ~59k | MIT | 角色扮演式多 Agent 协作 | "角色化分工"可用于研判/处置/复盘多角色流程设计 |
| **Qwen-Agent** (QwenLM/Qwen-Agent) | ~17.1k | Apache-2.0 | 通义千问官方 Agent 框架 | 国产模型适配好，若用 Qwen 系做内部引擎优先看 |
| **AgentScope** (agentscope-ai/agentscope) | ~31.8k | Apache-2.0 | 阿里多 Agent 框架，可视化监控 | 兼顾"可信可观测"，适合安全运营的可信审计需求 |
| **AgentUniverse** (agentuniverse-ai/agentUniverse) | ~2.4k | Apache-2.0 | 蚂蚁多 Agent 框架（企业级） | 企业业务落地/治理范式 |

---

## 五、专门做"自然语言 → 工作流/自动化"的开源方向

| 项目 | Star | 许可 | 定位 | 说明 |
|---|---|---|---|---|
| **Chat2Workflow** (zjunlp/Chat2Workflow) | ~39 | MIT | 学术界：NL → 可执行可视化工作流基准 | 用来**评估"AI 生成编排草稿"效果**的参照框架，非成熟产品 |
| **n8n-workflow-builder** (makafeli/n8n-workflow-builder) | ~0.5k | MIT | 通过 **MCP** 让 AI 用自然语言创建/管理 n8n 工作流 JSON | **"LLM+MCP→生成原生编排 JSON"的现成工程样板**，与 SOAR AI 生成草稿完全对应 |
| **n8n**（官方） | ~205k | fair-code | AI Workflow Builder | 用自然语言创建/精修/调试，人类审阅后发布，**全链路标杆** |

---

## 六、合规提示（商业化前必查）

- **纯 OSI 开源、可放心改**：Langflow(MIT)、Shuffle(AGPL-3.0，再分发需开源回馈)、StackStorm(Apache-2.0)、LangGraph/AutoGen/OpenAI SDK/CrewAI/AgentScope/Qwen-Agent(MIT/Apache-2.0)。
- **fair-code / 自定义许可，非纯开源**：n8n(Sustainable Use License，部分高级功能付费)、Dify(自定义，多租户/去 LOGO 需授权)、Flowise(source-available)、TheHive 商业版。
- **GPL/AGPL 系需注意传染性**：Shuffle(AGPL)、W5(GPL)、TheHive/Cortex(AGPL)——做平台对外分发时要评估开源回馈义务。

---

## 七、落地建议（把"参考"变"方案"）

- **产品交互对标**：n8n（AI 生成草稿闭环）+ Dify（双范式发布、版本化）+ W5/Coze（中文运营交互）。
- **领域模型对标**：Shuffle（安全工作流 + OpenAPI 工具接入 + 触发 + 案例）+ StackStorm（规则引擎）。
- **后台引擎对标**：LangGraph（图/状态机 + 持久化 + 人工审批 + 可审计）。
- **AI 生成编排草稿**：借鉴 n8n-workflow-builder 的"MCP + 原生 JSON"思路 + Chat2Workflow 的评测方法，自研为平台差异化亮点。

> 下一步建议：从上面挑 2-3 个（如 Shuffle + n8n + LangGraph）做**细粒度功能拆解对照**，映射回你们现有 SOAR 的智能体/工作流/工具/技能/知识库模块，形成改造清单。
