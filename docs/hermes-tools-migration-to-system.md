# Hermes 工具与技能迁移到系统工具

## Context

Hermes 引擎的内置工具和框架级工具目前硬编码在 Python 代码中：
- 4 个安全工具（check_whitelist/get_asset_info/get_threat_intel/check_subnet）定义在 `context_tools.py`，由 `tool_engine._register_builtin_tools()` 作为兜底注册
- 4 个框架级工具（trigger_workflow_skill/list_workflow_skills/delegate_task/clarify）的 schema 分散在 `skill_engine.py`/`delegator.py`/`clarify.py`，由 `executor.py` 硬编码注入

这导致工具管理页面看不到这些工具，无法统一管理描述和参数。本次迁移将所有 Hermes 工具注册到 DB `tools` 表，实现统一可视可管理，同时保持框架级工具的执行逻辑不变。

## 迁移策略

| 工具分类 | tool_type | DB 存储内容 | 执行方式 |
|---------|-----------|------------|---------|
| 安全工具 (check_whitelist 等 4 个) | `code` | schema + Python 代码 | tool_runner 沙箱执行（与用户工具一致） |
| 框架级工具 (delegate_task 等 4 个) | `framework`（新增） | 仅 schema（name/description/parameters_schema） | executor.py 专属方法拦截，不走 tool_runner |

## 实施步骤

### Step 1: tool_runner.py — 补充 `ipaddress` 模块注入

**文件**: `backend/app/core/tool_runner.py:118-125`

安全工具的代码需要 `ipaddress` 标准库做 IP 解析，但沙箱命名空间未注入该模块。在 namespace 字典中补充：
```python
import ipaddress  # 顶部新增
# namespace 中新增：
"ipaddress": ipaddress,
```

### Step 2: seed.py — 新增 Hermes 工具种子数据

**文件**: `backend/app/core/seed.py`

#### 2a. 新增 `HERMES_BUILTIN_TOOLS`（4 个 code 类型工具）

将 `context_tools.py` 的 4 个函数转为 DB code 工具，代码内联（不依赖模块级常量，直接在 `run()` 内使用 `ipaddress`）：
- `check_whitelist` — IP 白名单检查（内网网段判断）
- `get_asset_info` — IP 资产归属查询（Mock）
- `get_threat_intel` — IP 威胁情报查询（Mock，内网非恶意）
- `check_subnet` — IP 所在子网信息查询（/24 网段 + 网关）

parameters_schema 使用数组格式 `[{name, type, required, description}]`，与现有 seed 工具一致。

#### 2b. 新增 `HERMES_FRAMEWORK_TOOLS`（4 个 framework 类型工具）

从 `skill_engine.py`/`delegator.py`/`clarify.py` 提取 schema，存入 DB：
- `trigger_workflow_skill` — parameters_schema 存 OpenAI parameters 对象
- `list_workflow_skills` — 无参数
- `delegate_task` — goal/context/tasks 参数
- `clarify` — question/choices 参数

字段设置：`tool_type='framework'`，`code=NULL`，`enabled=True`，`parameters_schema` 存完整 OpenAI parameters JSON（非数组格式）。

#### 2c. 新增 `ensure_hermes_tools()` 函数

幂等插入：按 `name` 查询，不存在才插入。在 `ensure_seed_data()` 末尾调用（每次启动都执行，不限于表空时）。不覆盖用户已修改的工具。

### Step 3: tool_engine.py — 移除 builtin 兜底，跳过 framework 类型

**文件**: `backend/app/agent/hermes/tool_engine.py`

- `_register_db_tools()`: 加载时跳过 `tool_type='framework'` 的工具（它们由 executor 注入，不走 tool_engine 执行）
- 删除 `_register_builtin_tools()` 方法（安全工具已转为 DB code 工具，由 `_register_db_tools()` 统一加载）
- `_build_registry()`: 移除 `self._register_builtin_tools()` 调用

### Step 4: executor.py — 从 DB 加载框架工具 schema

**文件**: `backend/app/agent/hermes/executor.py:118-136`

替换硬编码的 schema 加载：
```python
# 旧：extra_tool_defs = [skill_engine.get_trigger_tool_schema(), ...]
# 新：从 DB 查询 tool_type='framework' 且 enabled=True 的工具，构造 OpenAI schema
framework_tools = db.query(Tool).filter(
    Tool.tool_type == 'framework', Tool.enabled.is_(True)
).all()
extra_tool_defs = [
    {"type": "function", "function": {
        "name": t.name,
        "description": t.description or "",
        "parameters": t.parameters_schema or {"type": "object", "properties": {}},
    }}
    for t in framework_tools
]
```

保留 `_react_loop` 中的工具拦截逻辑（trigger_workflow_skill/list_workflow_skills/delegate_task 走专属处理）。

extra_source_map 改为从 DB 查询结果动态构建（不再硬编码 source 映射）。

### Step 5: 前端适配（最小改动）

- **工具管理页面**: framework 类型工具显示「框架内置」徽章，编辑时 parameters_schema 只读
- **AgentEditor 工具列表**: framework 工具正常显示在勾选列表中（已有逻辑兼容，无需改动）

## 不改动的部分

- `context_tools.py`: 保留文件（向后兼容），但不再被 tool_engine 导入
- `skill_engine.py`/`delegator.py`/`clarify.py` 中的 schema 定义函数: 保留（向后兼容），但 executor 不再调用
- `executor._handle_skill_call()` / `_handle_delegate_call()`: 执行逻辑不变
- LangGraph 引擎: 不受影响（framework 工具不在其加载范围）

## 验证方案

1. **启动验证**: 后端启动后检查日志 `ensure_hermes_tools` 插入了 8 个工具（或跳过已存在的）
2. **DB 验证**: `SELECT name, tool_type FROM tools WHERE tool_type IN ('framework') OR name IN ('check_whitelist','get_asset_info','get_threat_intel','check_subnet')` 确认 8 条记录
3. **工具管理页面**: 访问工具列表，确认 8 个 Hermes 工具可见，4 个 framework 工具有「框架内置」标记
4. **AgentEditor**: 新建/编辑 Hermes 引擎 Agent，工具勾选列表包含所有 Hermes 工具
5. **调试运行**: Hermes Agent 调试时，LLM 可调用 check_whitelist/get_asset_info 等工具（走 tool_runner 沙箱），可调用 delegate_task/trigger_workflow_skill（走 executor 拦截）
6. **编译验证**: `npm run build` 前端无报错；后端 `docker compose build backend` 成功
