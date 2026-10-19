# 部署 SQL 清单与执行说明

> **定位**：`deploy/sql/` 存放**部署期需要手工执行的 SQL**（加列、索引、扩展等）。
> **为什么有这套**：项目**不用 Alembic**，`Base.metadata.create_all` 只建缺失的表、**不会给已存在的表加列/加索引**。因此凡是「给存量表补结构」的变更，都必须落一个 `.sql` 文件到本目录，并在部署时手工执行。
> **维护规则**：新增结构变更 → 在此目录加 `.sql` + 在本文件 §二 登记一行 + 提交信息里注明「部署需执行本 SQL」。
> **本分支的完整部署步骤**（SQL 只是其中一步）见 [`docs/architecture/模块化阶段-部署手册.md`](../../docs/architecture/模块化阶段-部署手册.md)。

---

## 一、执行方式（通用）

```bash
# 1) 拷进 postgres 容器
docker cp deploy/sql/<文件名>.sql soar-postgres:/tmp/mig.sql

# 2) 执行（ON_ERROR_STOP=1：任一句失败即中止）
docker exec soar-postgres psql -U <user> -d <db> -v ON_ERROR_STOP=1 -f /tmp/mig.sql
```

**约定**：
- 所有语句**幂等**（`IF NOT EXISTS`），可重复执行；
- **先执行 SQL，再部署/重启后端**——顺序反了，新代码查新列会报 `UndefinedColumn`；
- 每个文件末尾附「执行后自检」注释（查列/索引是否就位）。

---

## 二、SQL 清单

| 文件 | 作用 | 关联变更 | 状态 |
|---|---|---|---|
| `assets_keyword_search.sql` | 资产清单 8 字段模糊搜索：`pg_trgm` + GIN 索引 | 资产搜索性能优化 | 已发布 |
| `deliverable_module.sql` | 交付物模块建表 | 交付物模块 | 已发布 |
| `p2_gateway_columns.sql` | `device_call_logs` 加 `idempotency_key` / `correlation_id` 两列 + 索引 | **P2-1 DeviceGateway** | 本次新增 |
| `p2_3_agent_enabled_devices.sql` | `agents` 加 `enabled_devices` JSON 列（设备 id 列表，默认 `[]`） | **P2-3 enabled_devices + 接线** | 本次新增 |
| `p2_agent_approval_columns.sql` | `approval_tickets` 加 Agent 高危工具确认字段（kind/tool_name 等 8 列 + 索引） | **P2 阶段 6a 审批单承载** | 本次新增 |

---

## 三、新增 SQL 的约定

1. 文件名用小写下划线，语义清晰（如 `p2_gateway_columns.sql`）；
2. 文件头写清：**背景 / 执行方式 / 幂等说明 / 执行顺序**；
3. 文件尾附**执行后自检** SQL（注释形式）；
4. 同步在本文件 §二 登记一行；
5. 提交信息里加一行 `[!] 部署需先执行 DB 迁移：deploy/sql/<文件名>.sql`。
