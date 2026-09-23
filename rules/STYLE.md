# 代码规范

第三层：统一写法。能靠 ruff / ESLint 强制的以工具为准。本文写工具盖不住的判断。宪法见 `CONSTITUTION.md`。生成 Skill/Tool 代码见 `AI_CODING_RULES.md`。

开工先分 **基座** 还是 **场景**：场景只组装或走生成红线；基座只修稳定、性能、公共工具层。禁止为单个场景改 `hermes/executor.py`。

## 落点

路由 → `api/v1/`；合同 → `schemas/`；ReAct → `agent/hermes/`；工具定义 → `core/tools/definitions/` 或 HTTP + `/devices`；解析 → `engine/`；封禁节点 → `workflow/`。`decision.py` 只许转发。智能体保存只改 Workspace，Advanced 不得复制 `enabled_*`。

## 可执行 Lint

仓库后端尚无全面接线的 `pyproject.toml`。落地时再启用，不要空转预留：

```toml
[tool.ruff]
target-version = "py311"
line-length = 120
src = ["app"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]
```

前端以现有 Vite + React 为准；接上 ESLint 后以其报错为准。

## 命名

| 对象 | 规则 | 例 |
|------|------|-----|
| 模块/函数 | snake_case | `build_db_tools` |
| 类 | PascalCase | `HermesAgentExecutor` |
| 常量 | UPPER_SNAKE | `SOAR_WRITE_TOOL_NAMES` |
| 工具注册名 | 小写蛇形，稳定 | `block_ip_on_firewall` |
| React 文件 | PascalCase | `AgentWorkspace.jsx` |
| API | 复数资源 | `/knowledge-bases` |

## 何时拆文件

- 超过约 800 行且两类职责应拆。
- 禁止再往 `executor.py`、`AgentEditor.jsx` 堆新 framework if/elif 或第二套表单。
- 新工具定义不放进 `hermes/executor.py`。
- 跨页逻辑放 `components/` 或 hooks。

## 错误、日志、测试、类型

- 禁止 `except Exception: pass`、禁止 `print`。用 `logger.exception` / `warning`，用户可见 `HTTPException`/`detail`。
- 日志带 `agent_id`、`execution_id`；禁止打密钥、Cookie、Token。
- 测试优先 `backend/tests/test_<行为>.py`。改运行时/封禁/发布门禁至少补一条失败用例。
- 新 API 用 Pydantic。`Any` 只用于外部 JSON 或旧 `variables` 迁移。
- 新增代码不堆无关注释。前端改行为要验证主路径。

## 提交

```
<type>(<scope>): <祈使句简述>
```

`feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert`。简体中文，不过 50 字，不加句号。不提交 `.env`、密钥、大二进制。
