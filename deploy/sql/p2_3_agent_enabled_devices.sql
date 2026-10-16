-- =============================================================================
-- P2-3 enabled_devices：agents 表增加设备绑定列
-- =============================================================================
-- 适用：PostgreSQL 15
--
-- 【背景】
--   P2-3（C1-5）Agent 勾选设备：新增 enabled_devices（JSON，设备 id 列表），
--   作为设备工具的主配置入口。勾选设备后，装配该设备下所有启用动作的投影
--   （device_{device_id}_{action_id}）+ 枚举工具（list_devices/list_device_actions）
--   + 门面（device_action）。
--   门面/枚举工具均按 enabled_devices 收窄作用域，防止越权操作未勾选设备。
--   项目无 Alembic，Base.metadata.create_all 不会给已存在的表加列，
--   故需本脚本一次性 ALTER TABLE 补列。
--
-- 【执行方式】
--   docker cp deploy/sql/p2_3_agent_enabled_devices.sql soar-postgres:/tmp/p23.sql
--   docker exec soar-postgres psql -U <user> -d <db> -v ON_ERROR_STOP=1 -f /tmp/p23.sql
--
-- 幂等：全部语句可重复执行（IF NOT EXISTS）。
-- 顺序：必须先跑本脚本，再部署/重启后端，否则新代码查询会报 UndefinedColumn。
-- 既有智能体不受影响：默认 '[]'，不装配任何设备工具（A-4 逐字节回归安全）。
-- =============================================================================

ALTER TABLE agents ADD COLUMN IF NOT EXISTS enabled_devices JSON NOT NULL DEFAULT '[]'::json;


-- =============================================================================
-- 执行后自检
-- =============================================================================

-- 1) 列是否就位（应返回 1 行，default '[]'）：
-- SELECT column_name, data_type, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'agents' AND column_name = 'enabled_devices';

-- 2) 既有智能体默认值检查（应全部为 [] ）：
-- SELECT id, name, enabled_devices FROM agents;
