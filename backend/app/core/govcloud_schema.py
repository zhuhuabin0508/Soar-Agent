"""政务云四类资产：Excel「原始数据」列与业务列定义。

Excel 表头（英文 key）一比一落成各资源独立表的列；
业务列（主键、导入批次、时间）与 Excel 列分开。
爬虫后续多出来的未知列写入 extra_excel，避免丢字段。
"""
from __future__ import annotations

# 与业务列同名时，Excel 该列改进行 extra_excel
RESERVED_COLUMNS = frozenset({
    "id", "source_id", "batch_id", "created_at", "updated_at", "extra_excel",
})

SKIP_EXCEL_HEADERS = frozenset({
    "数据统计", "统计", "占比", "占比图示", "记录数", "取值",
})

# 云主机：与 crawl 产出 JSON / 「原始数据」表头一致
CLOUD_HOST_EXCEL_FIELDS = [
    "_id",
    "instance_id",
    "inst_id",
    "instance_name",
    "inst_name",
    "ip_address",
    "floatip_address",
    "host_status",
    "operating_system",
    "cloud_env_type",
    "cloud_env_id",
    "cloud_processor_architecture",
    "computing_type",
    "vcpu",
    "memory",
    "data_disk",
    "system_disk",
    "system_disk_type",
    "biz_region_name",
    "user_department",
    "user_department_id",
    "user_department_idchain",
    "applicant_department",
    "applicant_department_id",
    "applicant_department_idchain",
    "data_status",
    "data_source",
    "create_time",
]

# 裸金属：与云主机接近，计算类型字段名为 compute_type
BARE_METAL_EXCEL_FIELDS = [
    "_id",
    "instance_id",
    "inst_id",
    "instance_name",
    "inst_name",
    "ip_address",
    "floatip_address",
    "host_status",
    "operating_system",
    "cloud_env_type",
    "cloud_env_id",
    "cloud_processor_architecture",
    "compute_type",
    "computing_type",
    "vcpu",
    "memory",
    "data_disk",
    "system_disk",
    "system_disk_type",
    "biz_region_name",
    "user_department",
    "user_department_id",
    "user_department_idchain",
    "applicant_department",
    "applicant_department_id",
    "applicant_department_idchain",
    "data_status",
    "data_source",
    "create_time",
]

# 网络资源：业务字段与主机不同
NETWORK_EXCEL_FIELDS = [
    "_id",
    "instance_id",
    "inst_id",
    "instance_name",
    "inst_name",
    "name",
    "ip_address",
    "cidr",
    "mask",
    "gateway",
    "vlan",
    "subnet",
    "vpc",
    "network_type",
    "network_level",
    "ip_version",
    "ip_type",
    "ip_ownership",
    "cloud_env_type",
    "cloud_env_id",
    "biz_region_name",
    "user_department",
    "user_department_id",
    "user_department_idchain",
    "applicant_department",
    "applicant_department_id",
    "applicant_department_idchain",
    "data_status",
    "data_source",
    "create_time",
    "description",
    "remark",
]

# 弹性 IP
ELASTIC_IP_EXCEL_FIELDS = [
    "_id",
    "instance_id",
    "inst_id",
    "instance_name",
    "inst_name",
    "ip_address",
    "floatip_address",
    "bandwidth",
    "bind_instance",
    "bind_instance_id",
    "ip_version",
    "ip_type",
    "cloud_env_type",
    "cloud_env_id",
    "biz_region_name",
    "user_department",
    "user_department_id",
    "user_department_idchain",
    "applicant_department",
    "applicant_department_id",
    "applicant_department_idchain",
    "data_status",
    "data_source",
    "create_time",
]

RESOURCE_EXCEL_FIELDS: dict[str, list[str]] = {
    "cloud_host": CLOUD_HOST_EXCEL_FIELDS,
    "bare_metal": BARE_METAL_EXCEL_FIELDS,
    "e_government_network": NETWORK_EXCEL_FIELDS,
    "elastic_ip": ELASTIC_IP_EXCEL_FIELDS,
}

FIELD_LABELS: dict[str, str] = {
    "_id": "CMDB ID",
    "instance_id": "实例 ID",
    "inst_id": "Inst ID",
    "instance_name": "实例名称",
    "inst_name": "Inst 名称",
    "name": "名称",
    "ip_address": "IP",
    "floatip_address": "弹性 IP",
    "operating_system": "操作系统",
    "host_status": "主机状态",
    "cloud_env_type": "云环境类型",
    "cloud_processor_architecture": "处理器架构",
    "computing_type": "计算类型",
    "compute_type": "计算类型",
    "applicant_department": "申请部门",
    "user_department": "使用部门",
    "user_department_id": "使用部门 ID",
    "user_department_idchain": "使用部门链路",
    "applicant_department_id": "申请部门 ID",
    "applicant_department_idchain": "申请部门链路",
    "vcpu": "vCPU",
    "memory": "内存(GB)",
    "data_disk": "数据盘",
    "system_disk": "系统盘",
    "system_disk_type": "系统盘类型",
    "biz_region_name": "业务区",
    "data_status": "数据状态",
    "data_source": "数据来源",
    "create_time": "创建时间",
    "cloud_env_id": "云环境 ID",
    "network_type": "网络类型",
    "network_level": "网络级别",
    "ip_version": "IP 版本",
    "ip_type": "IP 类型",
    "ip_ownership": "IP 归属",
    "cidr": "CIDR",
    "mask": "掩码",
    "gateway": "网关",
    "vlan": "VLAN",
    "subnet": "子网",
    "vpc": "VPC",
    "description": "描述",
    "remark": "备注",
    "bandwidth": "带宽",
    "bind_instance": "绑定实例",
    "bind_instance_id": "绑定实例 ID",
}

SOURCE_ID_KEYS = ("_id", "instance_id", "inst_id")


def excel_attr(field: str) -> str:
    """Excel 表头 → ORM 属性名（``_id`` 映射为 cmdb_id）。"""
    return "cmdb_id" if field == "_id" else field


def skip_excel_header(key: str) -> bool:
    k = (key or "").strip()
    if not k:
        return True
    if k in SKIP_EXCEL_HEADERS:
        return True
    if "数据统计" in k:
        return True
    return False
