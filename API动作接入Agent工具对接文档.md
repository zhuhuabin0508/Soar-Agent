# API 动作接入 Agent 工具体系 · 对接文档

> 适用场景：新增模块对接第三方 API（增删改查类，固定接口 + 传参调用），需要让 Agent 能够调用这些 API 动作。

---

## 1. 对接结论

**每个 API 动作注册成一条 `tool_type="http"` 的 Tool 记录，无需编写任何 Python 代码。**

框架已内置完整的封装与执行管线：

| 阶段 | 做什么 | 谁负责 |
|------|--------|--------|
| 定义期 | 把每个 API 动作写成 Tool 记录（契约 = `http_config` + `parameters_schema`） | **对接人（本文档要做的全部工作）** |
| 装配期 | Agent 勾选工具后自动加载、生成 LLM 可见的 function calling schema | 框架自动 |
| 运行期 | LLM 发起 tool call → 自动参数分发、鉴权注入、重试、响应提取 | 框架自动 |

---

## 2. 契约字段说明

### 2.1 Tool 记录基本字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 工具名，全局唯一。**命名前缀决定调度行为，见第 4 节** |
| `description` | 是 | 工具描述，直接影响 Agent 选工具的准确率，要求见第 5 节 |
| `tool_type` | 是 | 固定填 `"http"` |
| `http_config` | 是 | 请求配置，见 2.2 |
| `parameters_schema` | 是 | 入参契约，见 2.3 |
| `enabled` | 是 | `true` / `false` |
| `category` / `tags` | 否 | 前端分组展示用 |

### 2.2 http_config 字段

```json
{
  "method": "GET",                          // GET / POST / PUT / PATCH / DELETE
  "url": "https://api.example.com/v1/records",  // path 参数用 {id} 占位
  "headers": [{"key": "Content-Type", "value": "application/json"}],
  "body_type": "none",                      // json / form / xml / none（GET 用 none）
  "body_content": "",                       // 静态 body 模板（一般留空，参数走 schema）
  "auth_type": "api_key",                   // none / bearer / api_key / oauth2，见 2.4
  "auth_config": {},
  "timeout": 10,                            // 秒
  "retry": 1,                               // 仅针对 5xx 与网络错误重试
  "response_jsonpath": "",                  // 响应提取，见 2.5
  "error_handling": ""                      // 错误处理规则
}
```

### 2.3 parameters_schema 字段

数组，每个元素描述一个入参：

| 字段 | 说明 |
|------|------|
| `name` | 参数名，须与 API 实际参数名一致 |
| `type` | `string` / `integer` / `number` / `boolean` |
| `location` | `query` / `body` / `header` / `path`（path 参数对应 URL 中的 `{name}` 占位符） |
| `required` | 是否必填 |
| `description` | 参数说明（给 LLM 看，写清楚含义和格式） |
| `default` | 默认值（调用方未传时自动填充） |
| `enum` | 枚举值列表（约束可选值） |

规则：
- 未在任何 schema 中声明的入参默认放入 body。
- 调用时传 `null` 视为未提供，自动改用 `default`。
- URL 中的 `{placeholder}` 会按同名 path 参数自动渲染。

### 2.4 鉴权配置 auth_config

| auth_type | auth_config 结构 | 实际效果 |
|-----------|------------------|----------|
| `none` | `{}` | 不鉴权 |
| `bearer` | `{"token": "<token>"}` | 注入 `Authorization: Bearer <token>` |
| `api_key` | `{"key_name": "X-API-Key", "key_value": "<密钥>", "location": "header"}` | 注入自定义 header（location 可选 `query`） |
| `oauth2` | `{"access_token": "<token>"}` | 注入 `Authorization: Bearer <token>`（预配置 token，不走授权码流程） |

> **密钥安全提醒**：密钥只填入平台工具配置，不要在文档、聊天记录中明文传递。

### 2.5 response_jsonpath（响应裁剪）

第三方 API 返回的 JSON 如果很大，用 JSONPath 提取需要的部分，缩减返回给 LLM 的内容（降低 token 消耗）。支持子集语法：

- `$.data.records` — 字段访问
- `$.list[0].name` — 索引访问
- `$.records[*].name` — 通配（返回列表）

示例：API 返回 `{"code":0, "msg":"ok", "data":{"records":[...]}}`，填 `$.data.records` 则 LLM 只收到 records 数组。

---

## 3. 接入方式（二选一）

### 方式一：OpenAPI 导入（推荐，有 Swagger/OpenAPI 文档时）

1. `POST /api/v1/tools/import-openapi`，传 `{"spec": "<OpenAPI JSON>"}` 或 `{"url": "<spec 地址>"}`，返回操作列表。
2. 前端选定操作后，`POST /api/v1/tools/build-from-operation`，传 `{"operation": {...}, "base_url": "..."}`，自动生成 `http_config + parameters_schema`。
3. 微调工具命名（对齐第 4 节前缀规范）和描述后保存。

### 方式二：手动创建

调 `POST /api/v1/tools` 创建（需 `tool.edit` 权限），模板见第 6 节。

创建后可用辅助接口：
- `POST /api/v1/tools/optimize-description` — LLM 帮你润色工具描述
- `POST /api/v1/tools/extract-parameters` — LLM 帮你从 API 文档提取参数 schema
- `POST /api/v1/tools/{tool_id}/test` — 直接测试工具调用，不经过 Agent

---

## 4. 命名规范（重要：前缀决定调度行为）

框架按工具名前缀决定并行/顺序调度，**不需要配置任何并行标志，命名即契约**：

| 命名前缀 | 调度行为 | 适用 |
|----------|----------|------|
| `query_` / `get_` / `list_` / `search_` | 并行安全，Agent 可并发调用 | **读操作**（查） |
| 其他前缀（`create_` / `update_` / `delete_` / `block_` 等） | 顺序屏障（barrier），逐个串行执行 | **写操作**（增/改/删），天然避免并发冲突 |

示例：`list_firewall_rules`（并行）、`create_firewall_rule`（串行）。

---

## 5. description 撰写要求

描述是 Agent 选工具的唯一依据，按以下要求写：

1. **写明功能**：一句话说清这个动作做什么。
2. **写明读/写属性**：写操作必须标注"（写操作）"。
3. **写明适用场景**：什么情况下应该用 / 不应该用，降低 LLM 选错率。
4. **写明风险等级**：高危操作（如删除、封禁）明确标注。

示例：

> 查询防火墙规则列表，支持按 IP 与状态过滤。适用于排查访问控制策略、核对资产暴露面。
>
> 在防火墙创建一条拦截规则（**写操作，风险等级：高**）。仅在确认 IP 为恶意来源后调用，优先使用封禁类专用工具。

---

## 6. CRUD 四类模板

### 6.1 查（GET + query 参数）

```json
{
  "name": "list_xxx_records",
  "description": "查询 XXX 系统的记录列表，支持分页与关键字过滤。适用于排查与核对场景。",
  "tool_type": "http",
  "enabled": true,
  "http_config": {
    "method": "GET",
    "url": "https://api.example.com/v1/records",
    "headers": [],
    "body_type": "none",
    "auth_type": "api_key",
    "auth_config": {"key_name": "X-API-Key", "key_value": "<密钥>", "location": "header"},
    "timeout": 10,
    "retry": 1,
    "response_jsonpath": "$.data.records",
    "error_handling": ""
  },
  "parameters_schema": [
    {"name": "page", "type": "integer", "location": "query", "required": false, "description": "页码，默认 1", "default": 1},
    {"name": "keyword", "type": "string", "location": "query", "required": false, "description": "关键字过滤"}
  ]
}
```

### 6.2 增（POST + body 参数）

```json
{
  "name": "create_xxx_record",
  "description": "在 XXX 系统创建一条记录（写操作）。仅在明确需要新增时调用。",
  "tool_type": "http",
  "enabled": true,
  "http_config": {
    "method": "POST",
    "url": "https://api.example.com/v1/records",
    "headers": [{"key": "Content-Type", "value": "application/json"}],
    "body_type": "json",
    "auth_type": "bearer",
    "auth_config": {"token": "<token>"},
    "timeout": 10,
    "retry": 0,
    "response_jsonpath": "",
    "error_handling": ""
  },
  "parameters_schema": [
    {"name": "name", "type": "string", "location": "body", "required": true, "description": "记录名称"},
    {"name": "level", "type": "string", "location": "body", "required": false, "description": "级别", "enum": ["low", "high"]}
  ]
}
```

### 6.3 改（PUT + path + body 参数）

```json
{
  "name": "update_xxx_record",
  "description": "更新 XXX 系统指定 ID 的记录（写操作）。仅更新传入的字段。",
  "tool_type": "http",
  "enabled": true,
  "http_config": {
    "method": "PUT",
    "url": "https://api.example.com/v1/records/{id}",
    "headers": [{"key": "Content-Type", "value": "application/json"}],
    "body_type": "json",
    "auth_type": "bearer",
    "auth_config": {"token": "<token>"},
    "timeout": 10,
    "retry": 0,
    "response_jsonpath": "",
    "error_handling": ""
  },
  "parameters_schema": [
    {"name": "id", "type": "integer", "location": "path", "required": true, "description": "记录 ID"},
    {"name": "name", "type": "string", "location": "body", "required": false, "description": "新名称"},
    {"name": "level", "type": "string", "location": "body", "required": false, "description": "新级别", "enum": ["low", "high"]}
  ]
}
```

### 6.4 删（DELETE + path 参数）

```json
{
  "name": "delete_xxx_record",
  "description": "删除 XXX 系统指定 ID 的记录（写操作，风险等级：高，不可恢复）。仅在明确确认后调用。",
  "tool_type": "http",
  "enabled": true,
  "http_config": {
    "method": "DELETE",
    "url": "https://api.example.com/v1/records/{id}",
    "headers": [],
    "body_type": "none",
    "auth_type": "bearer",
    "auth_config": {"token": "<token>"},
    "timeout": 10,
    "retry": 0,
    "response_jsonpath": "",
    "error_handling": ""
  },
  "parameters_schema": [
    {"name": "id", "type": "integer", "location": "path", "required": true, "description": "要删除的记录 ID"}
  ]
}
```

---

## 7. 接入后配置与验证

1. **勾选工具**：在目标 Agent 配置的 `enabled_tools` 中加入这些工具名。装配与执行全自动。
2. **测试**：先用 `POST /api/v1/tools/{tool_id}/test` 直接验证工具本身返回正常，再通过 Agent 对话验证 LLM 能正确选中和传参。
3. **工具数量较多时**：框架会在工具数/token 超阈值时自动把可延迟工具替换为 `tool_search / tool_describe / tool_call` 桥接工具，Agent 按需检索调用，无需额外配置。

---

## 8. 约束与注意事项

1. **不要另造执行路径**：所有工具调用必须收敛到框架统一的工具执行入口，新模块不得在 Agent 内直接塞私有执行入口。
2. **读操作务必用并行前缀命名**（`query_/get_/list_/search_`），否则读查询也会被串行化，影响并发效率。
3. **写操作切勿使用并行前缀**，保证顺序执行避免并发冲突。
4. **enum 校验只告警不阻断**：参数值不在枚举内时会记录 warning 但仍发出请求，枚举主要用于引导 LLM 传值。
5. **重试仅针对 5xx 与网络错误**：4xx（参数错误、鉴权失败）不会重试，写操作建议 `retry: 0` 避免重复写入。
6. **超时默认 10 秒**：慢接口适当调大，但注意过大会阻塞 Agent 的工具执行段。
7. **本文档场景边界**：声明式 http 工具覆盖"一次请求一个动作"。如动作需要 token 动态刷新、多步编排、状态管理，不在本文档范围，需另行评估（Gateway 模式或 code 工具）。
