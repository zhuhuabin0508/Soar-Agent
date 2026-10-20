# 待外部评审：通用 Agent 与「工具级权限」的设计

> **2026-10-20 已按组内结论落地，本文保留为当时的评审请求。** 现行方案与进度见 [`模块化阶段-进度总览.md`](./模块化阶段-进度总览.md) §十四.1。
>
> 结论摘要：不建「挂全部工具」的通用壳。统一对话是只挂查询工具的普通 Agent。工具列表 = Agent 白名单，再按角色裁剪。`high` 仍由当前用户在对话里确认，但确认只签发一次性凭证；执行前网关重读契约。`critical` 不进入对话。工作流入口保持直接执行。

> 下文是一份自包含的技术评审请求。读者无需了解本项目，读完第一、二节即可理解背景。

---

## 一、系统背景

一个 SOAR（安全编排自动化响应）平台，技术栈 **Python / FastAPI / SQLAlchemy / PostgreSQL + React**。

### 1.1 Agent 是「配置驱动的场景化 Agent」

平台里没有通用 Agent，只有一批**窄场景 Agent**（处置、资产、研判……）。每个 Agent 通过白名单决定自己能挂载哪些工具：

| 白名单字段 | 决定什么 |
|---|---|
| `Agent.enabled_tools` | 挂哪些 DB 工具（`tools` 表里的 code/http/预置工具） |
| `Agent.enabled_workflows` | 哪些已发布工作流**作为工具**可调 |
| `Agent.enabled_devices` | 哪些设备的动作被投影成工具（如 `device_3_7`） |
| `Agent.enabled_kbs` | 能查哪些知识库 |

### 1.2 工具注册表是「唯一工厂」

`ToolRegistryBuilder.build()` 产出 `ToolDescriptor` 列表，是**全平台唯一装配点**。工具分六类：

| # | 类 | 来源 | 存活口径 | 受哪个白名单管 |
|---|---|---|---|---|
| 1 | DB 工具 | `tools` 表 | `enabled=True` | `enabled_tools` |
| 2 | 知识库工具 | `_register_kb_tools` | KB 启用 | `enabled_kbs` |
| 3 | 资产工具 | `_register_asset_tools`（`search_assets`） | 内置 | `enabled_tools` |
| 4 | 设备工具 | `_register_device_tools`：`list_devices` / `device_{id}_{act}` / `device_action` / `block_ip` | 设备启用+在线+动作启用 | `enabled_devices` |
| 5 | 工作流工具 | `_register_workflow_tools`：`workflow_{id}_{name}` | 工作流已发布/启用 | `enabled_workflows` |
| 6 | 框架工具 | executor 直接注入：`clarify` / `delegate_task` / `trigger_workflow_skill` | 恒在 | 不受管 |

注：`agent=None`（系统模式，供管理 API / 脚本 / 工作流节点使用）会注册**全部启用 DB 工具**，不按 Agent 过滤。

### 1.3 危险治理与「对话内确认闸」（最近刚做完）

- 每个 `ToolDescriptor` 声明 `danger_level`（low / medium / high / critical）；
- `ToolDescriptor` 还有 `required_permission: (module, action) | None` —— **目前只是埋点，从未被校验**；
- **Agent 场景**：命中 high/critical 的工具时，执行前拦截 → 建一张确认单 → 通过 SSE 推一个 `tool_confirm` 事件 → 前端在**当前对话**弹出「确认 / 拒绝」→ **当前登录用户**点确认 → 当场执行（不经过审批中心、不异步）；拒绝则不执行。两种情况都写审计（谁 / 哪个 Agent / 哪个工具 / 确认或拒绝）。
- **工作流场景**：直接执行，不走确认（SOP 保证）。

### 1.4 权限体系是 RBAC

- `Role.permissions = {模块: [动作]}`，如 `{"device": ["view"], "agent": ["view","edit","execute"]}`；
- `has_permission(permissions, module, action)` 纯函数 + `require_permission(module, action)` FastAPI 依赖；
- admin 角色自动拥有全部权限；
- 默认角色：`admin`（全部）、`analyst`（有 `agent:execute`，但 **`device` 只有 `view`**）、`viewer`（只读）；
- 对话接口要求 `agent:execute`。

---

## 二、要做的功能

**「Agent 统一对话」**：平台需要一个通用入口——用户直接提问，由一个**通用 Agent** 根据对话内容，使用各模块暴露的工具 + 知识库等「能接触到的信息」来解决问题。

我们的初步设计是：给 `Agent` 加一个 `is_general` 开关，为 true 时装配阶段**忽略四个白名单，挂载全部存活工具**（全部启用 DB 工具 + 全部 KB + 全部可投影设备 + 全部已发布工作流），安全性由 §1.3 的**对话内确认闸**兜底。

---

## 三、暴露出的问题（核心）

### 3.1 工具挂载看「Agent 配置」，不看「用户权限」

注册表装配时**没有 user 参与**。因此一个用户能用到哪些工具，只取决于：
1. 他能进入哪个 Agent（需 `agent:execute`）；
2. 那个 Agent 挂了什么。

**与用户自己所在角色的模块权限无关。**

### 3.2 具体越权路径

```
analyst 角色：agent:execute ✅、device: ["view"]（只能看设备）❌ 不能改
通用 Agent：is_general=true → 挂载了 block_ip / device_action
analyst 打开通用对话 → 说"封掉 1.2.3.4" → 弹确认 → 【analyst 自己】点"确认执行"
→ 设备真的被封禁
```

即：**`device:view` 的用户，通过 Agent 完成了 `device:edit` 的操作。**

### 3.3 确认闸不能承担授权职责

确认闸的设计是「当前对话用户自己点确认」——它解决的是「危险操作别让 AI 自作主张」，**不是**「谁能做这个操作」。按确认的人就是发起的人，**没有职责分离**。

### 3.4 现状的影响面

- 窄 Agent 时代这个口子已存在，但每个 Agent 只挂少数工具，**爆炸半径有限**；
- 一旦上「通用 Agent（挂全部工具）」，就变成**全模块越权**——任何有 `agent:execute` 的人都能操作所有模块。

### 3.5 已有但未启用的钩子

`ToolDescriptor.required_permission` 已存在（如设备写操作可标 `("device","edit")`），但：
- 并非所有工具都填了；
- 没有任何地方校验它。

---

## 四、我们的初步方案

### 4.1 三道防线

| # | 层 | 做什么 |
|---|---|---|
| 1 | **装配期（主）** | `ToolRegistryBuilder.build()` 接收当前 `user`，按 `required_permission` 过滤，**没权限的工具根本不挂载**（LLM 看不到、也不会去调） |
| 2 | **执行期（兜底）** | `tool_engine._execute_one` 调用前再校验一次 `required_permission`，防注册表漏改 / 工具名伪造 / 其他旁路 |
| 3 | **确认闸（不变）** | 继续只负责「危险操作需人确认」，不再承担权限职责 |

### 4.2 前置：权限解析助手

`require_permission` 只在 FastAPI 依赖里可用，需要补一个纯函数：

```python
def resolve_user_permissions(user, db) -> dict[str, list[str]]:
    """admin → 全量；role_id → Role.permissions；
    否则 fallback DEFAULT_ROLES[user.role]。"""
```

### 4.3 `required_permission` 的填充规则

| 工具类 | required_permission |
|---|---|
| 设备读（`list_devices` / `list_device_actions`） | `("device", "view")` |
| 设备写（`device_{id}_{act}` / `device_action` / `block_ip`） | `("device", "edit")` |
| 工作流工具 | `("workflow_list", "execute")` |
| 知识库工具 | `("knowledge_base", "view")` |
| 资产只读 / 写 | `("asset_list", "view")` / `("asset_list", "edit")` |
| DB 预置工具 | 默认 `("tool", "execute")`；敏感项用**覆盖表**（如 `block_ip_on_firewall` → `("device","edit")`） |
| 框架工具（`clarify` / `delegate_task`） | `None`（不校验） |

### 4.4 分阶段落地

| 步 | 内容 |
|---|---|
| P1 | `resolve_user_permissions()` + `has_tool_permission()` 助手 |
| P2 | `ToolRegistryBuilder` 接 `user`，装配期过滤 |
| P3 | `tool_engine._execute_one` 执行期兜底校验 |
| P4 | 补全 `required_permission` + 单测 + 文档 |

### 4.5 过渡期兜底

在 P1~P4 落地前，「通用 Agent」**只对 admin 开放**。

---

## 五、请评审的问题

1. **分层是否合理？** 装配期过滤（不挂载）vs 执行期拦截（挂了但拒绝），哪个做主力更合适？两者都做是否过度？
2. **`required_permission` 的建模**：代码内映射表 vs `tools` 表加列（可由管理员配置）vs 独立策略表？
3. **通用 Agent 该不该存在？** 备选：
   - (a) 通用 Agent 挂全部工具（本文的问题源）；
   - (b) 通用 Agent **只读 + 委派**（把处置交给窄 Agent，窄 Agent 各自白名单）；
   - (c) 不建通用 Agent，只做**意图路由**（分类后落到某个窄 Agent）。
   哪种更符合「一个入口解决所有问题」且安全？
4. **有没有更成熟的模式**可以替代「工具级权限」这套自研方案？例如：策略引擎（OPA/Casbin）、capability token、工具级 ACL 表、多租户 scope 等。在 Python/FastAPI + RBAC 的现状下，哪个性价比最高？
5. **职责分离**：高危操作由「发起人自己确认」是否可接受？在不引入重型审批中心的前提下，有没有轻量的「第二人复核」模式？
6. **UX**：按权限过滤后，用户会看到「工具变少了」甚至「这个 Agent 对我没有可用工具」——怎么提示才不让人以为系统坏了？
7. **回归风险**：过滤上线后，`analyst` 会失去一批原本能用的工具（这是有意修复，但属于行为变更）。有没有更平缓的迁移方式（灰度 / 开关 / 只对新 Agent 生效）？

---

## 六、约束与评价标准

**约束**
- 不能改变 `admin` 的现有行为（全权限，工具一个不少）；
- 增量改造，不重写；每个阶段独立可提交、可回滚；
- 保留「对话内确认闸」的交互（不做审批中心、不做异步 Celery 审批）；
- 工作流路径继续「直接执行」，不走人工确认；
- 尽量不引入新的外部服务（最好不部署 OPA 之类）。

**评价标准**
- 安全正确性（越权路径是否真正消失，而非只是变难）；
- 可维护性（新增一个工具时，权限是否容易声明且不易漏）；
- 性能与成本（注册表按用户构建，是否有缓存问题）；
- 迁移风险（现有 Agent/用户行为变化是否可控）。
