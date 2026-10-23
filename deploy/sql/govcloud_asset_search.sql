-- 资产发现查询索引。与 backend/app/core/security.py 中
-- _ensure_govcloud_search_indexes 保持一致，可重复执行。
-- 启动迁移会自动建这些索引；正式环境数据量大约 30 万行时，也可单独执行本脚本。
--
-- docker cp deploy/sql/govcloud_asset_search.sql soar-postgres:/tmp/govcloud_asset_search.sql
-- docker exec soar-postgres psql -U postgres -d soar_dev -v ON_ERROR_STOP=1 -f /tmp/govcloud_asset_search.sql

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_gch_ip ON govcloud_cloud_hosts (ip_address);
CREATE INDEX IF NOT EXISTS ix_gch_fip ON govcloud_cloud_hosts (floatip_address);
CREATE INDEX IF NOT EXISTS ix_gch_inst ON govcloud_cloud_hosts (instance_id);
CREATE INDEX IF NOT EXISTS ix_gch_cmdb ON govcloud_cloud_hosts (cmdb_id);
CREATE INDEX IF NOT EXISTS ix_gbm_ip ON govcloud_bare_metals (ip_address);
CREATE INDEX IF NOT EXISTS ix_gbm_fip ON govcloud_bare_metals (floatip_address);
CREATE INDEX IF NOT EXISTS ix_gbm_inst ON govcloud_bare_metals (instance_id);
CREATE INDEX IF NOT EXISTS ix_gbm_cmdb ON govcloud_bare_metals (cmdb_id);
CREATE INDEX IF NOT EXISTS ix_gnet_ip ON govcloud_networks (ip_address);
CREATE INDEX IF NOT EXISTS ix_gnet_cidr ON govcloud_networks (cidr);
CREATE INDEX IF NOT EXISTS ix_gnet_inst ON govcloud_networks (instance_id);
CREATE INDEX IF NOT EXISTS ix_gnet_cmdb ON govcloud_networks (cmdb_id);
CREATE INDEX IF NOT EXISTS ix_geip_ip ON govcloud_elastic_ips (ip_address);
CREATE INDEX IF NOT EXISTS ix_geip_fip ON govcloud_elastic_ips (floatip_address);
CREATE INDEX IF NOT EXISTS ix_geip_inst ON govcloud_elastic_ips (instance_id);
CREATE INDEX IF NOT EXISTS ix_geip_cmdb ON govcloud_elastic_ips (cmdb_id);

CREATE INDEX IF NOT EXISTS ix_gch_extra_ip ON govcloud_cloud_hosts ((extra_excel->>'IP'));
CREATE INDEX IF NOT EXISTS ix_gbm_extra_ip ON govcloud_bare_metals ((extra_excel->>'IP'));
CREATE INDEX IF NOT EXISTS ix_gnet_extra_ip ON govcloud_networks ((extra_excel->>'IP'));
CREATE INDEX IF NOT EXISTS ix_geip_extra_ip ON govcloud_elastic_ips ((extra_excel->>'IP'));

CREATE INDEX IF NOT EXISTS ix_gch_name_trgm ON govcloud_cloud_hosts USING gin (instance_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gch_iname_trgm ON govcloud_cloud_hosts USING gin (inst_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gch_udept_trgm ON govcloud_cloud_hosts USING gin (user_department gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gch_adept_trgm ON govcloud_cloud_hosts USING gin (applicant_department gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gbm_name_trgm ON govcloud_bare_metals USING gin (instance_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gbm_iname_trgm ON govcloud_bare_metals USING gin (inst_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gbm_udept_trgm ON govcloud_bare_metals USING gin (user_department gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gbm_adept_trgm ON govcloud_bare_metals USING gin (applicant_department gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gnet_name_trgm ON govcloud_networks USING gin (instance_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gnet_iname_trgm ON govcloud_networks USING gin (inst_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gnet_label_trgm ON govcloud_networks USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gnet_udept_trgm ON govcloud_networks USING gin (user_department gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gnet_adept_trgm ON govcloud_networks USING gin (applicant_department gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_geip_name_trgm ON govcloud_elastic_ips USING gin (instance_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_geip_iname_trgm ON govcloud_elastic_ips USING gin (inst_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_geip_udept_trgm ON govcloud_elastic_ips USING gin (user_department gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_geip_adept_trgm ON govcloud_elastic_ips USING gin (applicant_department gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_gch_extra_name_trgm ON govcloud_cloud_hosts USING gin ((extra_excel->>'实例名') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gch_extra_name_trgm_ip ON govcloud_cloud_hosts USING gin ((extra_excel->>'IP') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gbm_extra_name_trgm ON govcloud_bare_metals USING gin ((extra_excel->>'实例名') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gbm_extra_name_trgm_ip ON govcloud_bare_metals USING gin ((extra_excel->>'IP') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gnet_extra_name_trgm ON govcloud_networks USING gin ((extra_excel->>'实例名') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_gnet_extra_name_trgm_ip ON govcloud_networks USING gin ((extra_excel->>'IP') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_geip_extra_name_trgm ON govcloud_elastic_ips USING gin ((extra_excel->>'实例名') gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_geip_extra_name_trgm_ip ON govcloud_elastic_ips USING gin ((extra_excel->>'IP') gin_trgm_ops);

ANALYZE govcloud_cloud_hosts;
ANALYZE govcloud_bare_metals;
ANALYZE govcloud_networks;
ANALYZE govcloud_elastic_ips;
