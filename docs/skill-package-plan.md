# Skill 包方案（说明 + 脚本，可导入）

> 状态：**仅方案，暂不开发。** 现有纯文本 Skill / JSON 导入导出保持不变。
> 目标：支持「一段作业说明 + 脚本包」导入，对齐 Agent Skills / Dify Skill 包形态，运行时仍走 Hermes + 现有 code 工具沙箱。

---

## 1. 结论

- **现在**：Skill = 提示词正文，注入 `system_prompt`。导入只支持平台 JSON。
- **要加的**：一种可选的 **Skill 包**（`.zip` / `.skill`），内含 `SKILL.md` + `scripts/`。
- **落地原则**：说明仍进 Skill 表；脚本变成已有的 **code 工具**，不新造执行引擎，不做 Linux 任意装包沙箱。
- **兼容**：不勾选包、不导入 zip 的智能体行为与现在完全一致。

---

## 2. 包格式（导入约定）

压缩包根目录（允许一层文件夹包裹）：

```text
<skill-id>/
  SKILL.md                 # 必填
  scripts/                 # 可选，*.py
  references/              # 可选，md/txt，仅作说明材料，不执行
```

`SKILL.md` 使用 YAML frontmatter + Markdown 正文：

```markdown
---
name: 封禁决策
description: 根据研判结果计算封禁时长
license: Apache-2.0
---

当用户要求封禁时：先查资产与情报，再调用 calc_ban_duration，按模板输出。
```

约束：

| 项 | 规则 |
|---|---|
| 体积 | 单包 ≤ 10MB（小于 Dify 的 50MB，内网够用） |
| 脚本 | 仅 `scripts/*.py`；每个文件须能抽出 `run(**kwargs)` 或整文件作为工具 `code` |
| 禁止 | `os` / `subprocess` / 网络原始套接字等，导入时走现有 `tool_sandbox.validate_tool_code`，不通过则整包拒绝或跳过该脚本并记警告 |
| 命名 | 工具名 = `skill_<slug>_<script_stem>`，避免与内置工具冲突 |

不支持第一期：二进制、npm、任意 bash、在沙箱里 pip install。

---

## 3. 数据怎么存（复用，少加表）

| 来源 | 落点 | 说明 |
|---|---|---|
| frontmatter.name / description + Markdown 正文 | `skills` 表现有字段 | `content` = SKILL.md 正文（可在文首加「可用脚本工具：…」清单） |
| 每个 `scripts/*.py` | `tools` 表 `tool_type=code` | `is_preset=false`；`category` 可用 `skill_bundle` |
| 包与工具的绑定 | `skills` 新增 JSON 列 `package_meta` | `{source: "agent-skills", files: [...], tool_names: [...]}` |
| 原始 zip | 可选存 `uploads/skill-packages/{id}/` | 便于再次导出；第一期也可只拆入库、不留 zip |

`package_meta` 用 `ensure_columns` 补列，与现有 agents 加列方式一致。无该列的旧技能视为纯文本。

智能体启用该 Skill 时：

1. 提示词组装逻辑不变（`prompt_assembler` 注入 `content`）。
2. **额外**：把 `package_meta.tool_names` 并入本次会话工具注册表（或保存智能体时写入 `enabled_tools`）。推荐运行时并入，避免用户漏勾工具。

---

## 4. 导入 / 导出

### 4.1 保留现有 JSON

`GET /skills/export/all`、`POST /skills/import` 不动，继续导入纯文本技能。

### 4.2 新增包导入（第一期就要做的接口）

`POST /skills/import-package`（multipart：`file`）

流程：

1. 解压到临时目录，定位 `SKILL.md`。
2. 解析 frontmatter；无 name 则用目录名。
3. 校验脚本 AST；通过则创建/更新 Skill + Tools。
4. 同名 Skill：默认拒绝，查询参数 `overwrite=true` 时覆盖正文并同步工具。
5. 返回 `{skill, tools[], warnings[]}`。

前端：技能库「导入」旁增加「导入 Skill 包」，接受 `.zip` / `.skill`。智能体配置页 Skill「添加」仍选库内技能，不必在创建页直接上传。

### 4.3 导出包（第二期）

若 `package_meta` 存在，可导出 zip；纯文本技能仍只出 JSON。

---

## 5. 运行时（Hermes / LangGraph 都不换）

```
用户消息
  → assemble_system_prompt（含 Skill 正文，告诉模型何时调哪些脚本工具）
  → tool_engine 注册 enabled_tools ∪ skill 绑定的 code 工具
  → ReAct 调工具（现有沙箱执行 Python）
```

不做：

- 模型在沙箱里 `bash` / 装系统包
- 把整个 zip 丢给模型当文件系统
- 与 `trigger_workflow_skill` 混名（工作流仍是工作流工具）

可选第二期：**按需加载**。目录里只暴露 Skill 名称+description，模型说要用时再注入全文（省 token）。第一期全量注入即可，与现在一致。

---

## 6. 分阶段

| 阶段 | 内容 | 验收 | 建议 |
|---|---|---|---|
| **S0** | 本文档，不改代码 | 评审通过 | 当前 |
| **S1** | `import-package` + 技能库上传 + `package_meta` + 绑定 code 工具 | 导入示例 zip 后，智能体勾选该 Skill 能调到脚本工具 | 优先 |
| **S2** | 启用 Skill 时运行时自动挂工具；Agent 工作区展示「随包工具」 | 用户只勾 Skill、不必再勾同名工具 | 紧随 S1 |
| **S3** | 导出 zip；按需加载正文 | 与 Dify 包往返 | 可延后 |
| **不做** | Linux sandbox、插件市场、50MB 任意资源 | — | 明确砍掉 |

---

## 7. 涉及文件（实施时）

- `backend/app/models/skill.py`：`package_meta`
- `backend/app/core/security.py`：`ensure_columns`
- `backend/app/api/v1/skills.py`：`import-package`
- 新增 `backend/app/core/skill_package.py`：解压、解析 SKILL.md、校验脚本
- `backend/app/agent/hermes/tool_engine.py`：S2 注册绑定工具
- `frontend/src/pages/SkillList.jsx`：上传入口
- `frontend/src/pages/AgentWorkspace.jsx`：Skill 卡片上标注「含脚本」

不动：`hermes/executor.py` 主循环（S1/S2 均不必改 ReAct）。

---

## 8. 风险

- 脚本与用户自建工具重名：强制 `skill_` 前缀。
- 导入恶意代码：与 code 工具同一套 AST 沙箱，失败则拒绝该脚本。
- 提示词过长：多包全量注入会胀上下文；S3 再做按需加载。
- 同名 Skill 覆盖会改正在使用的智能体行为：默认不覆盖。

---

## 9. 示例包（实施时作为测试夹具）

最小包：`SKILL.md`（封禁口径）+ `scripts/calc_ban_duration.py`（输入 risk_level，返回 duration 字符串）。导入后智能体只勾该 Skill，预览对话里应出现对应工具调用。
