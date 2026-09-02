"""设备类型模板库。

提供各厂商安全设备的官方模板，包含：
- 厂商信息与 Logo 图标
- 默认 API 地址格式
- 认证方式
- 常见动作（封禁 IP、解封 IP、查询黑名单等）

前端用于：
- 新建设备时选择模板自动填充
- 动作市场展示
"""
from typing import Any


# 设备类型图标
DEVICE_TYPE_ICONS = {
    "firewall": "🛡️",
    "waf": "🌐",
    "ips": "🚨",
    "ids": "📡",
    "edr": "💻",
    "soar": "🤖",
    "switch": "🔀",
    "cloud": "☁️",
    "custom": "⚙️",
}


# 设备模板：按「类型-厂商」组织
DEVICE_TEMPLATES: dict[str, dict[str, Any]] = {
    "firewall_paloalto": {
        "label": "Palo Alto 防火墙",
        "type": "firewall",
        "vendor": "Palo Alto",
        "icon": "🛡️",
        "api_url_format": "https://{host}/api",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/restapi/v9.1/policies/security/rules",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP 地址"},{"name":"zone","type":"string","required":false,"default":"untrust","description":"源安全区域"}]',
                "description": "在安全策略中添加拒绝规则封禁指定 IP",
            },
            {
                "name": "解封 IP",
                "action_type": "unblock_ip",
                "category": "dispose",
                "risk_level": "readonly",
                "http_method": "DELETE",
                "api_path": "/restapi/v9.1/policies/security/rules",
                "params_schema": '[{"name":"rule_name","type":"string","required":true,"description":"要删除的规则名称"}]',
                "description": "删除安全策略中的封禁规则",
            },
            {
                "name": "查询安全策略",
                "action_type": "custom",
                "category": "query",
                "risk_level": "readonly",
                "http_method": "GET",
                "api_path": "/restapi/v9.1/policies/security/rules",
                "params_schema": "[]",
                "description": "查询当前所有安全策略规则",
            },
        ],
    },
    "firewall_fortinet": {
        "label": "Fortinet 防火墙",
        "type": "firewall",
        "vendor": "Fortinet",
        "icon": "🛡️",
        "api_url_format": "https://{host}/api/v2/cmdb",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/firewall/address",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP 地址"},{"name":"name","type":"string","required":true,"description":"地址对象名称"}]',
                "description": "添加防火墙地址对象实现 IP 封禁",
            },
            {
                "name": "解封 IP",
                "action_type": "unblock_ip",
                "category": "dispose",
                "risk_level": "readonly",
                "http_method": "DELETE",
                "api_path": "/firewall/address",
                "params_schema": '[{"name":"name","type":"string","required":true,"description":"要删除的地址对象名称"}]',
                "description": "删除防火墙地址对象解封 IP",
            },
        ],
    },
    "firewall_h3c": {
        "label": "H3C 防火墙",
        "type": "firewall",
        "vendor": "H3C",
        "icon": "🛡️",
        "api_url_format": "https://{host}/api",
        "auth_type": "basic",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/rest/security-policy",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"}]',
                "description": "添加安全策略封禁指定 IP",
            },
        ],
    },
    "firewall_huawei": {
        "label": "华为防火墙",
        "type": "firewall",
        "vendor": "Huawei",
        "icon": "🛡️",
        "api_url_format": "https://{host}/api/cgvm",
        "auth_type": "basic",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/security-policy/rule",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"}]',
                "description": "添加安全策略规则封禁 IP",
            },
        ],
    },
    "firewall_sangfor": {
        "label": "深信服防火墙",
        "type": "firewall",
        "vendor": "深信服",
        "icon": "🛡️",
        "api_url_format": "https://{host}/api/v1",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/security/block_ip",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"}]',
                "description": "封禁指定 IP 地址",
            },
            {
                "name": "解封 IP",
                "action_type": "unblock_ip",
                "category": "dispose",
                "risk_level": "readonly",
                "http_method": "POST",
                "api_path": "/security/unblock_ip",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要解封的 IP"}]',
                "description": "解封指定 IP 地址",
            },
        ],
    },
    "firewall_nsfocus": {
        "label": "绿盟防火墙",
        "type": "firewall",
        "vendor": "绿盟",
        "icon": "🛡️",
        "api_url_format": "https://{host}/api",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/v1/blacklist/ip",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"}]',
                "description": "将 IP 加入黑名单",
            },
            {
                "name": "查询黑名单",
                "action_type": "custom",
                "category": "query",
                "risk_level": "readonly",
                "http_method": "GET",
                "api_path": "/v1/blacklist/ip",
                "params_schema": "[]",
                "description": "查询当前 IP 黑名单列表",
            },
        ],
    },
    "waf_aliyun": {
        "label": "阿里云 WAF",
        "type": "waf",
        "vendor": "阿里云",
        "icon": "🌐",
        "api_url_format": "https://waf.aliyuncs.com",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/CreateProtectionRule",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"},{"name":"instance_id","type":"string","required":true,"description":"WAF 实例 ID"}]',
                "description": "添加 WAF 黑名单规则封禁 IP",
            },
        ],
    },
    "waf_tencent": {
        "label": "腾讯云 WAF",
        "type": "waf",
        "vendor": "腾讯云",
        "icon": "🌐",
        "api_url_format": "https://waf.tencentcloudapi.com",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/ModifyIpAccessControl",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"},{"name":"domain","type":"string","required":true,"description":"域名"}]',
                "description": "添加 WAF IP 黑名单",
            },
        ],
    },
    "waf_imperva": {
        "label": "Imperva WAF",
        "type": "waf",
        "vendor": "Imperva",
        "icon": "🌐",
        "api_url_format": "https://{host}/api/v1",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "封禁 IP",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/sites/{site_id}/blacklist",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"}]',
                "description": "添加站点 IP 黑名单",
            },
        ],
    },
    "edr_crowdstrike": {
        "label": "CrowdStrike EDR",
        "type": "edr",
        "vendor": "CrowdStrike",
        "icon": "💻",
        "api_url_format": "https://api.crowdstrike.com",
        "auth_type": "bearer",
        "actions": [
            {
                "name": "隔离主机",
                "action_type": "quarantine_host",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/devices/entities/devices-actions",
                "params_schema": '[{"name":"device_id","type":"string","required":true,"description":"设备 ID"},{"name":"action","type":"enum","required":false,"default":"contain","options":["contain","lift_contain"],"description":"操作类型"}]',
                "description": "隔离指定终端设备",
            },
            {
                "name": "查询设备",
                "action_type": "custom",
                "category": "query",
                "risk_level": "readonly",
                "http_method": "GET",
                "api_path": "/devices/queries/devices",
                "params_schema": '[{"name":"filter","type":"string","required":false,"description":"查询过滤条件"}]',
                "description": "查询终端设备列表",
            },
        ],
    },
    "edr_360": {
        "label": "360 EDR",
        "type": "edr",
        "vendor": "360",
        "icon": "💻",
        "api_url_format": "https://{host}/api",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "隔离终端",
                "action_type": "isolate_endpoint",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/endpoint/isolate",
                "params_schema": '[{"name":"endpoint_id","type":"string","required":true,"description":"终端 ID"}]',
                "description": "隔离指定终端",
            },
        ],
    },
    "edr_qianxin": {
        "label": "奇安信 EDR",
        "type": "edr",
        "vendor": "奇安信",
        "icon": "💻",
        "api_url_format": "https://{host}/api",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "隔离终端",
                "action_type": "isolate_endpoint",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/v1/endpoint/isolate",
                "params_schema": '[{"name":"endpoint_id","type":"string","required":true,"description":"终端 ID"}]',
                "description": "隔离指定终端",
            },
            {
                "name": "查询告警",
                "action_type": "custom",
                "category": "query",
                "risk_level": "readonly",
                "http_method": "GET",
                "api_path": "/v1/alerts",
                "params_schema": '[{"name":"start_time","type":"string","required":false,"description":"开始时间"}]',
                "description": "查询 EDR 告警列表",
            },
        ],
    },
    "cloud_aws": {
        "label": "AWS 云平台",
        "type": "cloud",
        "vendor": "AWS",
        "icon": "☁️",
        "api_url_format": "https://ec2.amazonaws.com",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "封禁 IP (WAF)",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/UpdateIPSet",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"},{"name":"ip_set_id","type":"string","required":true,"description":"IP 集合 ID"}]',
                "description": "更新 AWS WAF IP 集合封禁 IP",
            },
        ],
    },
    "cloud_aliyun": {
        "label": "阿里云平台",
        "type": "cloud",
        "vendor": "阿里云",
        "icon": "☁️",
        "api_url_format": "https://ecs.aliyuncs.com",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "查询安全组",
                "action_type": "custom",
                "category": "query",
                "risk_level": "readonly",
                "http_method": "GET",
                "api_path": "/DescribeSecurityGroups",
                "params_schema": "[]",
                "description": "查询 ECS 安全组列表",
            },
            {
                "name": "封禁 IP (安全组)",
                "action_type": "block_ip",
                "category": "block",
                "risk_level": "high_risk",
                "http_method": "POST",
                "api_path": "/AuthorizeSecurityGroup",
                "params_schema": '[{"name":"ip","type":"ip","required":true,"description":"要封禁的 IP"},{"name":"security_group_id","type":"string","required":true,"description":"安全组 ID"}]',
                "description": "在安全组中添加拒绝规则封禁 IP",
            },
        ],
    },
    "cloud_tencent": {
        "label": "腾讯云平台",
        "type": "cloud",
        "vendor": "腾讯云",
        "icon": "☁️",
        "api_url_format": "https://cvm.tencentcloudapi.com",
        "auth_type": "api_key",
        "actions": [
            {
                "name": "查询安全组",
                "action_type": "custom",
                "category": "query",
                "risk_level": "readonly",
                "http_method": "GET",
                "api_path": "/DescribeSecurityGroups",
                "params_schema": "[]",
                "description": "查询 CVM 安全组列表",
            },
        ],
    },
}


def get_device_templates() -> dict[str, dict[str, Any]]:
    """返回所有设备模板。"""
    return DEVICE_TEMPLATES


def get_device_template(template_key: str) -> dict[str, Any] | None:
    """获取指定模板。"""
    return DEVICE_TEMPLATES.get(template_key)


def get_icon_for_type(device_type: str) -> str:
    """根据设备类型返回图标。"""
    return DEVICE_TYPE_ICONS.get(device_type, "⚙️")
