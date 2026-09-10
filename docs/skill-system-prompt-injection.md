# 技能（Skill）系统：常驻 system-prompt 文本注入

## Context（背景与目标）

当前平台创建"工具/技能"时只有两种形式：`code`（写 Python 代码）和 `http`（声明式接口），都是可执行逻辑。用户需要一种**纯文本**形式——直接写自然语言描述处置流程/角色设定/领域规则/SOP，启用后**注入到 Agent 的 system prompt**，持续塑造 AI 行为（类似 Claude Skill）。这不是可调用工具，而是常驻指令文本。

经确认，用户选择「B：常驻 system-prompt 技能」语义。

**关键发现（已验证）**：
- Agent 的 system_prompt 在 `agents.py` 的 `test_agent`/`test_agent_stream` 两条路径（纯对话 + LangGraph）组装，这是注入技能的正确位置。
- 工作流 `ai_agent` 节点（`node_executors.py:177`）用 `node_data.get("system_prompt")`，**不引用 Agent 实体**，v1 无需覆盖。
- `agent.variables` 的 `{{key}}` 替换在 `models/agent.py:49` 注释中承诺但**全后端未实现**——本方案顺便在共享 helper 中补齐。
- Agent 的 `enabled_tools`/`enabled_kbs` 均为 JSON 数组（非关联表），`enabled_skills` 沿用此模式。

---

## 一、数据模型

### 1.1 新建 Skill 模型 — `backend/app/models/skill.py`（新建）

参考 `backend/app/models/tool.py` 结构：

```python
class Skill(Base):
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)        # 摘要（列表展示）
    content = Column(Text, nullable=False)            # 注入 system prompt 的正文，支持 {{key}}
    category = Column(String(64), nullable=True)      # 处置流程/角色设定/领域规则/SOP/其他
    tags = Column(JSON, nullable=True, default=list)
    enabled = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=0)  # 注入顺序，越大越靠前
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

### 1.2 Agent 表加字段 — `backend/app/models/agent.py`

紧邻 `enabled_kbs`（L27）后追加：
```python
enabled_skills = Column(JSON, nullable=True, default=list)  # 启用的技能 id 列表
```

### 1.3 模型注册 — `backend/app/models/__init__.py`

L6 区追加 `from app.models.skill import Skill`，`__all__` 加 `"Skill"`。`main.py` 的 `Base.metadata.create_all` 会自动建 `skills` 表，无需手写 DDL。

---

## 二、system_prompt 注入（核心）

### 2.1 新建共享 helper — `backend/app/agent/prompt_assembler.py`（新建）

集中处理：技能加载 + 变量替换 + 分段标记 + 长度告警。

```python
_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")  # 仅匹配 {{word}}，避免误伤字面量
_PROMPT_LENGTH_WARN = 32000

def render_variables(text: str, variables: dict | None) -> str:
    """把 {{key}} 替换为 variables 值；缺失则保留原占位符并 warning。
    补齐 models/agent.py:49 承诺但未实现的能力。"""

def assemble_system_prompt(db, agent, fallback_prompt: str | None = None) -> str:
    """组装最终 system prompt：基础提示词 + 启用技能正文。
    规则：
    1. base = agent.system_prompt 或 fallback_prompt（仅当无技能且 base 为空时用 fallback）
    2. 对 base 做 {{key}} 替换（用 agent.variables）
    3. 加载 enabled_skills 中 enabled=True 的技能，按 priority 降序（禁用/删除的自然 miss）
    4. 每个技能 content 做 {{key}} 替换，空内容跳过
    5. 分段标记包裹：
       === 启用技能 ===
       --- 技能: {name} --- / {content} / --- 技能: {name} 结束 ---
       === 启用技能结束 ===
    6. base 为空但有技能：以技能段作为完整 prompt
    7. 总长度 > 阈值时 logger.warning（不阻断）
    """
```

`_load_enabled_skills(db, ids)`：`db.query(Skill).filter(Skill.id.in_(ids), Skill.enabled.is_(True)).order_by(Skill.priority.desc())`，实现"禁用后立即从 prompt 移除"。

### 2.2 改造 4 处调用点 — `backend/app/api/v1/agents.py`

| 行 | 现状 | 改为 |
|---|---|---|
| L220 (`test_agent` 纯对话) | `system_prompt = agent.system_prompt or "你是一个智能助手..."` | `assemble_system_prompt(db, agent, fallback_prompt="你是一个智能助手，请根据用户输入给出有帮助的回答。")` |
| L327 (`test_agent_stream` 纯对话) | 同上 | 同上 |
| L262 (`test_agent` LangGraph) | `system_prompt=agent.system_prompt` | `system_prompt=assemble_system_prompt(db, agent)` |
| L379 (`test_agent_stream` LangGraph) | 同上 | 同上 |

> LangGraph 路径传入非 None 的 system_prompt 后，`decision.py:487` 的 `if system_prompt is not None:` 分支会自动跳过决策 JSON 解析、返回原始响应——正是 Agent 自定义提示词下的期望行为，无需改 decision.py。

### 2.3 边界情况

| 场景 | 处理 |
|---|---|
| 技能禁用 | 查询加 `enabled.is_(True)`，立即移除 |
| 内容为空 | `if not content.strip(): continue` |
| prompt 过长 | >32000 字符 warning，不阻断 |
| 技能被删除仍被引用 | `IN` 查询自然 miss |
| 变量缺失 | 保留 `{{key}}` 原文 + warning |

---

## 三、后端 API

### 3.1 新建 skills 路由 — `backend/app/api/v1/skills.py`（新建）

参考 `tools_manage.py` CRUD 模式。`SkillBase` 含 name/description/content/category/tags/enabled/priority。

端点（路径用 `{skill_id:int}` 转换器）：
- `GET /skills`（支持 `?category=&enabled=` 过滤）
- `GET /skills/{id}`
- `POST /skills`（name 唯一性校验，参考 tools_manage.py:95-97）
- `PUT /skills/{id}`
- `DELETE /skills/{id}`（悬挂引用用惰性清理——assemble 时 IN 查询自然 miss）

权限：列表 `require_permission("skill","view")`，写操作 `edit`/`delete`。

### 3.2 AgentBase 加字段 — `backend/app/api/v1/agents.py`

- `AgentBase`（L71-93）追加 `enabled_skills: list[int] | None`
- `create_agent`（L114-132）追加 `enabled_skills=body.enabled_skills or []`
- `update_agent`（L147-163）追加 `agent.enabled_skills = body.enabled_skills or []`

### 3.3 路由注册 — `backend/app/api/v1/__init__.py`

L10 import 块加 `skills,`；L57 附近加 `api_router.include_router(skills.router)`。

---

## 四、权限与迁移

### 4.1 权限 — `backend/app/core/permissions.py`

- `PERMISSION_MODULES`（L12-27）加 `"skill": ["view", "edit", "delete"]`
- `MODULE_LABELS`（L30-45）加 `"skill": "技能"`
- `DEFAULT_ROLES`：admin 自动全权；analyst 加 `"skill": ["view","edit"]`；viewer 加 `"skill": ["view"]`

### 4.2 迁移 — `backend/app/core/security.py`

`run_lightweight_migrations` 的 agents 表块（L196-209）后追加：
```python
ensure_columns(engine, "agents", {"enabled_skills": "JSON"})
```
Skill 表由 `create_all` 自动建。

### 4.3 前端权限 — `frontend/src/utils/permissions.js`

`DEFAULT_ROLE_PERMS`（L20）的 analyst 加 `skill: ['view','edit']`，viewer 加 `skill: ['view']`。

---

## 五、前端

### 5.1 API client — `frontend/src/api/client.js`

`knowledgeBases`（L158）后加：
```js
export const skills = {
  list: () => request('/skills'),
  get: (id) => request(`/skills/${id}`),
  create: (body) => request('/skills', { method: 'POST', body }),
  update: (id, body) => request(`/skills/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/skills/${id}`, { method: 'DELETE' }),
}
```

### 5.2 技能管理页 — `frontend/src/pages/SkillList.jsx`（新建）

参考 `KnowledgeBase.jsx` 的 Modal 模式 + `ToolList.jsx` 的列表模式：
- 列表：name / category 徽章 / enabled 开关（toggle 调 update）/ 编辑 / 删除（ConfirmDialog）
- 工具栏：搜索 + 分类筛选 + 新建按钮
- `SkillFormModal`：name、description、category（select 预设项）、tags、content（textarea rows=12 font-mono）、priority、enabled
- content 下方提示：`💡 可用 {{key}} 引用智能体变量（在智能体编辑页配置）`
- 复用 `Modal`（`components/Dialog.jsx`）与 `inputCls`/`textareaCls`（`FormControls.jsx`）

预设分类：处置流程 / 角色设定 / 领域规则 / SOP / 其他。

### 5.3 AgentEditor 集成 — `frontend/src/pages/AgentEditor.jsx`

- import 加 `skills as skillsApi`
- form 默认值加 `enabled_skills: []`
- L111 `Promise.all` 改四元组加 `skillsApi.list()`，设 `skillOptions`（仅 enabled）
- L147 setForm 加 `enabled_skills: (agent.enabled_skills||[]).map(String)`
- 保存 body 加 `enabled_skills: form.enabled_skills.map(Number)`
- 在"能力扩展"卡片（L460 区）后插入新 Card「技能注入」：`<CheckboxGroup value={form.enabled_skills} options={skillOptions} columns={2} />` + 空态提示 + 变量引用说明

### 5.4 路由与侧边栏

- `App.jsx`：import `SkillList`，L62 后加 `<Route path="/skills" element={<SkillList />} />`
- `AppShell.jsx`：L18 知识库项后加 `{ to: '/skills', icon: '🎯', label: '技能', perm: ['skill','view'] }`；`BREADCRUMB_MAP` 加 `'/skills': ['技能']`

---

## 六、实施顺序（按依赖）

1. `models/skill.py` 新建 → 2. `models/__init__.py` 注册 → 3. `models/agent.py` 加列 → 4. `security.py` 迁移 → 5. `permissions.py` 注册 → 6. `agent/prompt_assembler.py` 新建（核心）→ 7. `api/v1/skills.py` 新建 → 8. `api/v1/__init__.py` 注册 → 9. `api/v1/agents.py` AgentBase+4 处调用 → 10. 前端 `api/client.js` → 11. `utils/permissions.js` → 12. `pages/SkillList.jsx` → 13. `App.jsx` 路由 → 14. `AppShell.jsx` 侧边栏 → 15. `pages/AgentEditor.jsx` 集成

---

## 七、验证

1. **后端部署**：`bash dev.sh up` 或 `docker compose --env-file .env.dev up -d`，检查 `soar-backend-dev` 启动日志无迁移错误、`skills` 表已建。
2. **CRUD**：用 curl/PowerShell 调 `POST /api/v1/skills` 创建一个"告警研判SOP"技能（content 含 `{{product_name}}` 变量）。
3. **注入验证**：创建 Agent，system_prompt 写 `你是 {{role}} 专家`，variables 设 `{"role":"SOC","product_name":"SOAR平台"}`，启用上述技能，调 `POST /agents/{id}/test`。检查 `test_agent` 返回的 messages 中 SystemMessage 是否含：变量已替换 + 技能段已注入。
4. **禁用即时生效**：把技能 enabled 改 false，再测，确认技能段消失。
5. **前端**：访问 `/skills` 管理页 CRUD；在 Agent 编辑页看到「技能注入」卡片可多选；保存后重新打开回显正确。
6. **权限**：用 viewer 角色登录，确认只能查看不能编辑技能。

---

## 八、关键文件清单

**新建**：
- `backend/app/models/skill.py`
- `backend/app/agent/prompt_assembler.py`（核心注入逻辑）
- `backend/app/api/v1/skills.py`
- `frontend/src/pages/SkillList.jsx`

**修改**：
- `backend/app/models/__init__.py`、`backend/app/models/agent.py`
- `backend/app/core/security.py`、`backend/app/core/permissions.py`
- `backend/app/api/v1/__init__.py`、`backend/app/api/v1/agents.py`（4 处调用 + AgentBase）
- `frontend/src/api/client.js`、`frontend/src/utils/permissions.js`
- `frontend/src/App.jsx`、`frontend/src/components/AppShell.jsx`、`frontend/src/pages/AgentEditor.jsx`
