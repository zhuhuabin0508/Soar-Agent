-- =============================================================================
-- P2-1 设备网关：device_call_logs 增加幂等键 / 关联键
-- =============================================================================
-- 适用：PostgreSQL 15
--
-- 【背景】
--   P2-1 DeviceGateway 需要两个新列：
--     - idempotency_key：幂等键，重复调用去重（5 分钟窗口）
--     - correlation_id ：关联键，串起 agent/workflow 调用链
--   项目无 Alembic，Base.metadata.create_all 不会给已存在的表加列，
--   故需本脚本一次性 ALTER TABLE 补列 + 建索引。
--
-- 【执行方式】
--   docker cp deploy/sql/p2_gateway_columns.sql soar-postgres:/tmp/p2.sql
--   docker exec soar-postgres psql -U <user> -d <db> -v ON_ERROR_STOP=1 -f /tmp/p2.sql
--
-- 幂等：全部语句可重复执行（IF NOT EXISTS）。
-- 顺序：必须先跑本脚本，再部署/重启后端，否则新代码查询会报 UndefinedColumn。
-- =============================================================================

ALTER TABLE device_call_logs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);
ALTER TABLE device_call_logs ADD COLUMN IF NOT EXISTS correlation_id  VARCHAR(128);

CREATE INDEX IF NOT EXISTS ix_device_call_logs_idempotency_key ON device_call_logs (idempotency_key);
CREATE INDEX IF NOT EXISTS ix_device_call_logs_correlation_id  ON device_call_logs (correlation_id);


-- =============================================================================
-- 执行后自检
-- =============================================================================

-- 1) 两列是否就位（应返回 2 行）：
-- SELECT column_name, data_type, character_maximum_length
-- FROM information_schema.columns
-- WHERE table_name = 'device_call_logs'
--   AND column_name IN ('idempotency_key', 'correlation_id');

-- 2) 两个索引是否就位（应返回 2 行）：
-- SELECT indexrelname FROM pg_stat_user_indexes
-- WHERE relname = 'device_call_logs'
--   AND indexrelname IN ('ix_device_call_logs_idempotency_key',
--                        'ix_device_call_logs_correlation_id');
