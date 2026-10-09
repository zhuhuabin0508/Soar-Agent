# 智能体如何建立：工具 / 技能 / 提示词 / 知识库如何结合

> 目的：帮助熟悉「智能体是怎么建起来、以及四类能力在运行时如何拧到一起的」。
> 配套：`docs/architecture/module-responsibilities-and-relations.md`（模块职责与关系总览）。
> 代码主链：`app/agent/hermes/executor.py` → `prompt_assembler.py` + `tool_engine.py` → `llm.bind_tools(...)`。

---

## 一、一句话直觉

**智能体 = 模型 + 系统提示词 + 一组可调用的工具。**
而「技能」是注入提示词的**文字**，「知识库」「工具」「资产类型」是注册给**模型调用**的能力。运行时一次问答 =
组装好的一段提示词 + 绑定的工具清单，交给 LLM 循环执行（ReAct：想 → 调工具 → 看结果 → 再想）。

在平台里，你把下面这些"配料"勾选/填进一个智能体，构建时它们天然地各归其位：

| 你配置的 | 用途 | 运行时去哪 |
|---------|------|-----------|
| 模型 + 温度/轮数 | 大脑与参数 | 构造 LLM 实例 |
| 系统提示词 `system_prompt` | 角色/职责 | 作为提示词正文 |
| 技能 `enabled_skills` | 操作方法（文字） | 追加进提示词「启用技能」段落 |
| 知识库 `enabled_kbs` | 领域知识（数据） | 生成 `search_knowledge_base` / `query_kb_file` 工具 |
| 工具 `enabled_tools` | 可调动作 | 绑定为 LLM 可调用工具 |
| 资产类型 `enabled_asset_types` | 资产检索范围 | 生成 `search_assets` 工具 |

---

## 二、建立一个智能体的步骤（前端视角）

1. **填基本信息**：名称、描述、头像、开场白/引导问题。
2. **选模型**：关联一条 LLM 配置（`model_config_id`），设温度、max_tokens、上下文轮数。
3. **写系统提示词**：定义角色、目标、输出格式（可选，可为空）。
4. **挂能力**（可组合，可多选）：
   - **工具** `enabled_tools`：勾选可调用的动作。
   - **技能** `enabled_skills`：勾选注入的方法论/流程指导。
   - **知识库** `enabled_kbs`：勾选可检索的知识库。
   - **资产类型** `enabled_asset_types`：勾选允许检索的资产范围。
5. **高级项**：记忆开关、自定义变量 `{{key}}`、工具行为配置（tool_search / guardrails / 重试确认）。
6. **保存 → 调试**：在编辑器里"调试运行"验证实际效果。

---

## 三、运行时是怎么把这些结合起来的（后端主链）

以最常用的 **Hermes 引擎** 为例，构建一次会话做三件事：

### 1) 组装系统提示词 —— `prompt_assembler.assemble_system_prompt`
```
base = agent.system_prompt            # 你写的提示词
技能  = 加载 agent.enabled_skills 中启用且未被删除的，按 priority 降序
final = base + "\n\n=== 启用技能 ===\n" + 技能内容拼接 + "\n=== 启用技能结束 ==="
```
> 关键：**技能不产生动作能力**，它只是"教模型怎么做"的文本，被注入提示词。想在提示词里引用变量用 `{{key}}`（由 `render_variables` 替换）。

### 2) 构建工具注册表 —— `tool_engine._build_registry()`（HermesToolEngine）
按顺序注册四类来源：

| 顺序 | 来源 | 说明 |
|---|---|---|
| 1 | `enabled_tools` 里的 DB 工具 | code/http（framework 由 executor 特殊处理；search_assets 被跳过，走第 3 步） |
| 2 | `enabled_kbs` | 非空时注册 `search_knowledge_base` + `query_kb_file` |
| 3 | `enabled_asset_types` | 非空时注册 `search_assets`（资产检索） |
| 4 | （内置 framework） | `plan` / `delegate_task` / `clarify` / `tool_search` 等 |

生成的每个工具带 `source` 标签（db_code / db_http / kb / asset / builtin / framework），**assembly 阶段会按 source 决定是否延迟**（见 `tool_search.py`）。

### 3) 绑定给 LLM —— `executor` 里
```python
self.llm_with_tools = llm.bind_tools(get_assembled_openai_tools())
```
然后进入 ReAct 循环：把 `system_prompt` + 用户输入交给 LLM，模型自主决定调哪个工具、传什么参数、何时出结论。

---

## 四、四种"能力"的本质区别（务必分清楚）

| 能力 | 本质 | 是否产生"可调用动作" | 是否会占模型上下文 | 典型场景 |
|---|---|---|---|---|
| **工具 Tool** | 一段可执行代码（code/http/framework） | ✅ 是 | 占用（工具 schema 发给模型） | 查资产、封禁、发邮件、扫描 |
| **技能 Skill** | 一段提示词文本（方法/流程/SOP） | ❌ 否（只是文字） | 占用（拼进 system_prompt） | 教模型按研判流程一步步做 |
| **系统提示词** | 角色设定 + 总目标 | ❌ 否（只是文字） | 占用 | 定义"你是安全分析师" |
| **知识库** | 外部文档/向量数据 | ✅ 是（生成检索工具） | 不直接占；按需检索 | 翻规章制度、查历史报告 |

> 结论：**「技能 / 提示词」管"怎么思考"，「工具 / 知识库」管"能做什么/知道什么"**。二者互补，不冲突。

---

## 五、容易踩的坑（结合本次排查）

1. **`search_assets` 是特殊的**：它在工具表里也有（id=123），但真正挂载靠的是**智能体勾选的「资产类型」**，不是勾选工具。所以"配置了工具却没生效"很常见。
2. **tool_search 会隐藏工具**：若智能体 `tool_configs.tool_search.enabled="on"`，非核心工具会被延迟进目录，模型要先调 `tool_search` 才看到。研判类智能体建议 `auto`/`off`。
3. **技能空、提示词空时的兜底**：`assemble_system_prompt` 若两者皆空会用 fallback 提示词。
4. **记忆会"跳步"**：`enable_memory=true` 时模型会记住结论，重复同样 IP 可能跳过资产/情报查询。