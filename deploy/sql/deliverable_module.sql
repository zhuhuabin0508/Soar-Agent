-- =============================================================================
-- 材料管理模块（资源管理 → 材料管理）部署脚本
-- =============================================================================
-- 适用：PostgreSQL 15
--
-- 【重要结论】
--   本次「材料/目录批量迁移」功能**没有新增表、没有新增/修改字段**。
--   它只复用已有的两张表：service_categories（目录树）、deliverables（材料文件），
--   移动操作只更新索引字段（category_id / parent_id / level），不触碰落盘文件。
--
-- 【本脚本做什么】
--   1) 幂等建表（IF NOT EXISTS）—— 全新环境可直接执行；已存在的库不做任何改动
--   2) 幂等补索引 —— 其中 ix_service_categories_name 在现网库中是**缺失**的，
--      建议补上（目录重名校验与批量移动会按 name 查询）
--   3) 可选的数据修复：把 service_categories.level 按 parent_id 重算
--
-- 【执行方式】
--   psql -h <host> -U <user> -d <db> -f deliverable_module.sql
--   或在容器内：
--   docker exec -i soar-postgres psql -U postgres -d soar < deliverable_module.sql
--
-- 幂等性：全部语句可重复执行，不会报错、不会重复建对象。
-- =============================================================================


-- =============================================================================
-- 第 0 步（建议先跑）：现状核对
-- 期望：两张表都返回 exists = true；全新环境返回 false，走第 1 步建表。
-- =============================================================================
-- SELECT 'service_categories' AS table_name, to_regclass('public.service_categories') IS NOT NULL AS exists
-- UNION ALL
-- SELECT 'deliverables', to_regclass('public.deliverables') IS NOT NULL;


-- =============================================================================
-- 第 1 步：目录树表 service_categories
--   说明：level 表示层级（根=1，最深 10）；parent_id 为 NULL 表示根目录。
--   注：level / sort_order 的默认值在 ORM 侧（SQLAlchemy default=），
--       这里额外补上 DB 端 DEFAULT，让手工 INSERT 也不会因 NOT NULL 失败。
-- =============================================================================
CREATE TABLE IF NOT EXISTS service_categories (
    id          SERIAL       NOT NULL,
    name        VARCHAR(100) NOT NULL,
    parent_id   INTEGER,
    level       INTEGER      NOT NULL DEFAULT 1,
    description VARCHAR(500),
    sort_order  INTEGER      NOT NULL DEFAULT 0,
    created_by  INTEGER      NOT NULL,
    created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);

-- 目录重名校验、批量移动的同级重名检查都会按 name 查询；现网库缺此索引，务必补上
CREATE INDEX IF NOT EXISTS ix_service_categories_name      ON service_categories (name);
CREATE INDEX IF NOT EXISTS ix_service_categories_parent_id ON service_categories (parent_id);


-- =============================================================================
-- 第 2 步：材料文件表 deliverables
--   说明：stored_name 是落盘文件名（uuid + 扩展名），与目录结构无关；
--         移动目录只改 category_id，磁盘文件不需要搬动。
-- =============================================================================
CREATE TABLE IF NOT EXISTS deliverables (
    id          SERIAL       NOT NULL,
    category_id INTEGER      NOT NULL,
    name        VARCHAR(200) NOT NULL,
    version     VARCHAR(50),
    description TEXT,
    filename    VARCHAR(300) NOT NULL,
    stored_name VARCHAR(100) NOT NULL,
    file_size   INTEGER      NOT NULL DEFAULT 0,
    file_ext    VARCHAR(10)  NOT NULL,
    created_by  INTEGER      NOT NULL,
    created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_deliverables_category_id ON deliverables (category_id);
CREATE INDEX IF NOT EXISTS ix_deliverables_created_at  ON deliverables (created_at);


-- =============================================================================
-- 第 3 步：其它相关索引（可选）
--   批量下载 / 列表分页按 category_id + created_at 倒序，数据量大时可加复合索引。
-- =============================================================================
-- CREATE INDEX IF NOT EXISTS ix_deliverables_cat_created ON deliverables (category_id, created_at DESC);


-- =============================================================================
-- 第 4 步（可选）：修复 service_categories.level 失真
--   背景：早期「移动目录」只更新被移动目录自身的 level，其后代 level 未同步，
--         导致深层子目录 level 偏小。此处的递归重算与后端脚本
--         backend/scripts/fix_category_levels.py 等价。
--   幂等：只会更新确实不一致的行；执行后可重复运行，第二次影响 0 行。
--   如不需要修复存量数据，可整段跳过。
-- =============================================================================

-- 4.1 从根目录自顶向下重算 level
WITH RECURSIVE tree AS (
    SELECT id, 1 AS lvl
    FROM service_categories
    WHERE parent_id IS NULL
    UNION ALL
    SELECT c.id, t.lvl + 1
    FROM service_categories c
    JOIN tree t ON c.parent_id = t.id
)
UPDATE service_categories sc
SET level = t.lvl
FROM tree t
WHERE sc.id = t.id
  AND sc.level IS DISTINCT FROM t.lvl;

-- 4.2 父级已不存在（脏数据）的目录，按根级处理，避免上一步漏掉整棵子树
UPDATE service_categories sc
SET level = 1
WHERE sc.parent_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM service_categories p WHERE p.id = sc.parent_id)
  AND sc.level IS DISTINCT FROM 1;


-- =============================================================================
-- 第 5 步：执行后自检
--   期望：mismatch_count = 0，说明全树 level 与 parent_id 完全自洽。
-- =============================================================================
-- SELECT count(*) AS mismatch_count
-- FROM service_categories c
-- LEFT JOIN service_categories p ON p.id = c.parent_id
-- WHERE c.level IS DISTINCT FROM COALESCE(p.level + 1, 1);
--
-- 索引自检（应列出 4 个索引）：
-- SELECT tablename, indexname FROM pg_indexes
-- WHERE tablename IN ('service_categories','deliverables') ORDER BY tablename, indexname;


-- =============================================================================
-- 备注：无需触发器
--   updated_at 的自动更新由 SQLAlchemy 的 onupdate=func.now() 在应用侧完成，
--   数据库端不需要建 trigger；如需纯 DB 侧保证，可自行补一个触发器。
-- =============================================================================
