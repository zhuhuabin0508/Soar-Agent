-- =============================================================================
-- 资产清单「关键词模糊搜索」性能支撑：pg_trgm 三元组 GIN 索引
-- =============================================================================
-- 适用：PostgreSQL 15
--
-- 【背景】
--   需求是把资产清单的搜索从「4 个字段 LIKE」扩展为「8 个字段 ILIKE」，
--   以覆盖 department（部门）等此前搜不到的字段 —— 实测 96,889 条资产中
--   有 58,155 条（60%）name 为空、只有 department 有值，属于「怎么搜都搜不到」。
--
--   但 %kw% 这种「包含匹配」无法走 B-Tree，只能全表 Seq Scan。
--   单纯扩字段后实测：apec 关键词 53.8ms → 356.8ms（慢 6.6 倍）。
--   本脚本用 pg_trgm + GIN 索引把 ILIKE 变成索引扫描。
--
-- 【实测收益】（96,889 行）
--   关键词       加索引前    加索引后
--   apec         356.8 ms     4.1 ms     执行计划: Bitmap Index Scan, 0.09 ms
--   129.211         —         5.7 ms
--   龙华区人民法院   —         3.9 ms
--
-- 【已知限制】
--   pg_trgm 需要「至少 3 个字符」才能生成三元组。因此 1~2 个字符的关键词
--   （例如中文「龙华」「福田」）仍会退化为全表扫描，耗时数百毫秒。
--   前端已加 350ms 输入防抖，避免逐字触发查询，实际体验可接受。
--   若后续要优化短词，可考虑 pg_bigm（二元组）扩展或对 department 做前缀索引。
--
-- 【执行方式】
--   docker cp deploy/sql/assets_keyword_search.sql soar-postgres:/tmp/a.sql
--   docker exec soar-postgres psql -U <user> -d <db> -v ON_ERROR_STOP=1 -f /tmp/a.sql
--
-- 幂等：全部语句可重复执行。
-- 注意：CREATE EXTENSION 需要数据库属主或超级用户权限。
-- 建索引耗时：实测约 7 秒 / 96,889 行；索引总体积约 13 MB。
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 与后端 backend/app/api/v1/assets.py 的 _KEYWORD_FIELDS 一一对应，
-- 增删搜索字段时请同步维护这里的索引。
CREATE INDEX IF NOT EXISTS ix_assets_trgm_identifier  ON assets USING gin (identifier  gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_assets_trgm_name        ON assets USING gin (name        gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_assets_trgm_ip          ON assets USING gin (ip          gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_assets_trgm_owner       ON assets USING gin (owner       gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_assets_trgm_department  ON assets USING gin (department  gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_assets_trgm_location    ON assets USING gin (location    gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_assets_trgm_asset_type  ON assets USING gin (asset_type  gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_assets_trgm_kb_name     ON assets USING gin (kb_name     gin_trgm_ops);

-- 让规划器拿到最新统计信息，否则可能仍选 Seq Scan
ANALYZE assets;


-- =============================================================================
-- 执行后自检
-- =============================================================================

-- 1) 扩展是否装上：
-- SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_trgm';

-- 2) 8 个索引是否就位（应返回 8 行）：
-- SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid)) AS size
-- FROM pg_stat_user_indexes
-- WHERE relname = 'assets' AND indexrelname LIKE 'ix_assets_trgm_%'
-- ORDER BY indexrelname;

-- 3) 确认走了索引（应出现 Bitmap Index Scan，而不是 Seq Scan）：
-- EXPLAIN (ANALYZE, COSTS OFF) SELECT id FROM assets WHERE department ILIKE '%apec%';
