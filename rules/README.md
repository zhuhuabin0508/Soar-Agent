# 项目规则母本（rules）

本目录是仓库级**单一事实来源**。开发组审核通过后，再派生 Cursor `.mdc` / Codex `AGENTS.md` / 各成员智能体编写规范。派生件不得另写一套宪法。

`agentrulescursor/`、`agentrulescodex/` 只是加载形态，口径以本目录为准。

## 文件

| 文件 | 层 | 谁必须带上 |
|------|----|------------|
| `CONSTITUTION.md` | 1 宪法 | 所有人、所有 Agent |
| `ARCHITECTURE.md` | 2 架构 | 改运行时、动目录、加场景入口 |
| `STYLE.md` | 3 风格与落点 | 改仓库代码 |
| `AI_CODING_RULES.md` | 3 生成红线 | `create_tool` / 生成 Skill·Tool·Agent 配置；以及会写工具 Python 的 Agent |
| `PLATFORM_STABILITY.md` | 2 展开 | 扩工具、改并发/预算/研判热路径。宪法里「基座优先 / 性能与稳定」不依赖读本文件已生效 |

## 两种 Agent（派生时按此裁剪，不要每人全量塞五份）

| 角色 | 允许 | 必读 |
|------|------|------|
| 场景组装 / 内置 Skill | 盘点→拆解→创建→固化；绑定已有工具 | 宪法 + `AI_CODING_RULES.md` |
| 基座研发 | 改 Hermes 公共层、分页、barrier、toolfactory 转发 | 宪法 + `ARCHITECTURE.md` + `STYLE.md`；动热路径再加 `PLATFORM_STABILITY.md` |

场景 Agent **禁止**改 `hermes/executor.py`、`guardrails.py`、`tool_dispatch.py`。基座 Agent 可以改，但高风险合入必须人审。

## 审核通过后：成员智能体规范怎么生成

1. 每人一份只含：宪法摘要（可全文）+ 其角色对应的 1～2 份细则。
2. 禁止把 `PLATFORM_STABILITY.md` 全文塞进只做页面文案的 Agent。
3. 禁止在成员规范里新增与本目录冲突的条款；只能变窄（例如「本 Agent 只许改 `frontend/`」）。
4. Cursor 成员：从本目录生成 `.cursor/rules` 与 skill，不要手写第二套硬约束。
5. Codex 成员：根加载用宪法全文；生成工具时附加 `AI_CODING_RULES.md`。

## 状态

待开发组审核。通过前以本目录讨论口径；通过后再提交 git、再派生成员规范。
