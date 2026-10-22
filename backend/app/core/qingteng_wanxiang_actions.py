"""青藤万相（v3.4.1.66）外部 API 查询类动作定义。

数据来源：《青藤万相 v3.4.1.66 外部API手册》。本模块仅收录**查询类**接口
（只读查询语义：资产/风险/入侵检测/基线/审计/快速任务/主机发现/微隔离的
列表与详情查询），明确排除创建、修改、删除、隔离、下发扫描任务等写操作。

动作结构与 DeviceAction 模型字段一一对应：
- action_type: 动作标识（全局唯一，seed 时以 device_id + action_type 为幂等键）
- name: 动作名称
- description: 功能描述（含请求方式、路径与返回概述）
- http_method / api_path: 请求方式与路径（路径参数用 {param} 占位）
- params_schema: 请求参数（JSON 数组：name/type/required/description）
- response_fields: 返回结果字段说明（seed 时写入 example_response 字段）

通用说明：
- 认证方式 auth_type 统一为 "qingteng"（登录换取 comId/jwt/signKey 后按
  青藤签名规范对每次请求做 SHA1 签名），由 action_executor 自动处理。
- 通用 GET 分页参数 page（从 0 开始）/ size / sorts（如 "+field,-field"）。
- DateRange 参数格式：yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss。
- 数组类查询参数按青藤示例以逗号分隔字符串传递（如 groups=1,2）。
"""

from typing import Any


def _p(name: str, ptype: str, required: bool, desc: str) -> dict[str, Any]:
    """构造 params_schema 条目。"""
    return {"name": name, "type": ptype, "required": required, "description": desc}


def _page() -> list[dict[str, Any]]:
    """通用 GET 分页/排序参数（page 从 0 开始）。"""
    return [
        _p("page", "integer", False, "分页页码，从 0 开始，默认 0"),
        _p("size", "integer", False, "每页数量，默认 50"),
        _p("sorts", "string", False, "排序字段，多个用逗号分隔，不加前缀为升序、加 - 为降序，如 sorts=-hostname"),
    ]


# 资产清点各资源接口的公共主机过滤参数（agentId/groups/hostname/ip）
_HOST_FILTER = [
    _p("agentId", "string", False, "唯一标识 Agent 的 ID（16 位）"),
    _p("groups", "string", False, "业务组 ID，多个用逗号分隔，如 groups=1,2"),
    _p("hostname", "string", False, "主机名（模糊查询）"),
    _p("ip", "string", False, "主机 IP（模糊查询）"),
]

# 主机信息返回字段（资产清点列表类接口的公共主机字段）
_HOST_RESP = [
    "agentId: String - agent uuid",
    "displayIp/connectionIp/internalIp/externalIp: String - 主机各 IP",
    "bizGroupId/bizGroup: 业务组 ID/名称",
    "remark: 备注；hostTagList: 标签列表",
    "hostname: 主机名",
]


def _action(
    action_type: str,
    name: str,
    method: str,
    path: str,
    desc: str,
    params: list[dict[str, Any]],
    resp: list[str],
) -> dict[str, Any]:
    """构造一个查询类动作定义。"""
    return {
        "action_type": action_type,
        "name": name,
        "description": f"{desc}（{method} {path}）",
        "http_method": method,
        "api_path": path,
        "params_schema": params,
        "response_fields": resp,
        "category": "query",
        "risk_level": "readonly",
        "auth_type": "qingteng",
    }


def _list_action(
    action_type: str,
    name: str,
    path: str,
    desc: str,
    extra_params: list[dict[str, Any]],
    resp: list[str],
) -> dict[str, Any]:
    """构造带通用分页与主机过滤参数的列表查询动作（GET）。"""
    return _action(action_type, name, "GET", path, desc, _HOST_FILTER + extra_params + _page(), resp)


# ============ 一、资产清点（assets）============

ASSET_ACTIONS: list[dict[str, Any]] = [
    _action(
        "qt_assets_refreshjob_get",
        "资产扫描状态查询",
        "GET",
        "/external/api/assets/refreshjob/{jobId}",
        "查询资产信息扫描任务的状态（各资产 refresh 扫描接口返回的 jobId 轮询使用），返回 id 与 status(Running/Success/Failed)",
        [_p("jobId", "string", True, "扫描任务 ID（路径参数，资产 refresh 接口返回的 id）")],
        ["id: String - 扫描任务 ID", "status: String - 扫描状态 Running/Success/Failed"],
    ),
    _list_action(
        "qt_assets_host_list_linux",
        "主机信息查询-Linux",
        "/external/api/assets/host/linux",
        "查询 Linux 主机资产清单（每台主机一条，含在线状态与最后在线时间）",
        [
            _p("platform", "string", False, "操作系统（模糊查询）"),
            _p("agentStatus", "string", False, "Agent 在线状态，多个用逗号分隔，如 agentStatus=0,1"),
            _p("lastOnlineTime", "string", False, "最后在线时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
            _p("serialNumber", "string", False, "序列号"),
        ],
        _HOST_RESP + ["platform: 操作系统", "agentStatus: 在线状态", "lastOnlineTime: 最后在线时间"],
    ),
    _list_action(
        "qt_assets_host_list_win",
        "主机信息查询-Windows",
        "/external/api/assets/host/win",
        "查询 Windows 主机资产清单（每台主机一条，含在线状态与最后在线时间）",
        [
            _p("platform", "string", False, "操作系统（模糊查询）"),
            _p("agentStatus", "string", False, "Agent 在线状态，多个用逗号分隔"),
            _p("lastOnlineTime", "string", False, "最后在线时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
            _p("serialNumber", "string", False, "序列号"),
        ],
        _HOST_RESP + ["platform: 操作系统", "agentStatus: 在线状态", "lastOnlineTime: 最后在线时间"],
    ),
    _list_action(
        "qt_assets_process_list_linux",
        "进程信息查询-Linux",
        "/external/api/assets/process/linux",
        "查询 Linux 主机进程清单（每台主机每个进程一条）",
        [
            _p("name", "string", False, "进程名（模糊查询）"),
            _p("path", "string", False, "进程路径（模糊查询）"),
            _p("uname", "string", False, "启动用户（模糊查询）"),
            _p("state", "string", False, "进程状态，多个用逗号分隔"),
            _p("startTime", "string", False, "启动时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
            _p("tty", "string", False, "终端（模糊查询）"),
        ],
        _HOST_RESP + ["pid/name/path/uname/tty/state: 进程信息", "startArgs: 启动参数", "startTime: 启动时间"],
    ),
    _list_action(
        "qt_assets_process_list_win",
        "进程信息查询-Windows",
        "/external/api/assets/process/win",
        "查询 Windows 主机进程清单（每台主机每个进程一条）",
        [
            _p("name", "string", False, "进程名（模糊查询）"),
            _p("path", "string", False, "进程路径（模糊查询）"),
            _p("uname", "string", False, "启动用户（模糊查询）"),
            _p("state", "string", False, "进程状态，多个用逗号分隔"),
            _p("startTime", "string", False, "启动时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
        ],
        _HOST_RESP + ["pid/name/path/uname/state: 进程信息", "startArgs: 启动参数", "startTime: 启动时间"],
    ),
    _list_action(
        "qt_assets_account_list_linux",
        "系统账号查询-Linux",
        "/external/api/assets/account/linux",
        "查询 Linux 主机系统账号清单（每台主机每个账号一条）",
        [
            _p("name", "string", False, "账号名（模糊查询）"),
            _p("status", "string", False, "账号状态，多个用逗号分隔"),
            _p("home", "string", False, "家目录（模糊查询）"),
            _p("uid", "string", False, "用户 ID"),
            _p("gid", "string", False, "组 ID"),
            _p("lastLoginTime", "string", False, "最后登录时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
        ],
        _HOST_RESP + ["name: 账号名", "status: 账号状态", "home: 家目录", "uid/gid: 用户/组 ID", "lastLoginTime: 最后登录时间"],
    ),
    _list_action(
        "qt_assets_account_list_win",
        "系统账号查询-Windows",
        "/external/api/assets/account/win",
        "查询 Windows 主机系统账号清单（每台主机每个账号一条）",
        [
            _p("name", "string", False, "账号名（模糊查询）"),
            _p("status", "string", False, "账号状态，多个用逗号分隔"),
            _p("home", "string", False, "家目录（模糊查询）"),
            _p("uid", "string", False, "用户 ID"),
            _p("gid", "string", False, "组 ID"),
            _p("lastLoginTime", "string", False, "最后登录时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
        ],
        _HOST_RESP + ["name: 账号名", "status: 账号状态", "home: 家目录", "uid/gid: 用户/组 ID", "lastLoginTime: 最后登录时间"],
    ),
    _list_action(
        "qt_assets_accountgroup_list_linux",
        "用户组信息查询-Linux",
        "/external/api/assets/accountgroup/linux",
        "查询 Linux 主机用户组清单（每台主机每个用户组一条）",
        [
            _p("name", "string", False, "用户组名（模糊查询）"),
            _p("gid", "string", False, "组 ID"),
        ],
        _HOST_RESP + ["name: 用户组名", "gid: 组 ID"],
    ),
    _list_action(
        "qt_assets_accountgroup_list_win",
        "用户组信息查询-Windows",
        "/external/api/assets/accountgroup/win",
        "查询 Windows 主机用户组清单（每台主机每个用户组一条）",
        [
            _p("name", "string", False, "用户组名（模糊查询）"),
            _p("gid", "string", False, "组 ID"),
        ],
        _HOST_RESP + ["name: 用户组名", "gid: 组 ID"],
    ),
    _list_action(
        "qt_assets_port_list_linux",
        "端口信息查询-Linux",
        "/external/api/assets/port/linux",
        "查询 Linux 主机监听端口清单（每台主机每个监听端口一条）",
        [
            _p("proto", "string", False, "协议（tcp/udp），多个用逗号分隔"),
            _p("port", "string", False, "监听端口"),
            _p("bindIp", "string", False, "绑定 IP（模糊查询）"),
            _p("processName", "string", False, "进程名（模糊查询）"),
        ],
        _HOST_RESP + ["proto: 协议", "port: 监听端口", "bindIp: 绑定 IP", "processName: 进程名"],
    ),
    _list_action(
        "qt_assets_port_list_win",
        "端口信息查询-Windows",
        "/external/api/assets/port/win",
        "查询 Windows 主机监听端口清单（每台主机每个监听端口一条）",
        [
            _p("proto", "string", False, "协议（tcp/udp），多个用逗号分隔"),
            _p("port", "string", False, "监听端口"),
            _p("bindIp", "string", False, "绑定 IP（模糊查询）"),
            _p("processName", "string", False, "进程名（模糊查询）"),
        ],
        _HOST_RESP + ["proto: 协议", "port: 监听端口", "bindIp: 绑定 IP", "processName: 进程名"],
    ),
    _list_action(
        "qt_assets_webapp_list_linux",
        "Web应用信息查询-Linux",
        "/external/api/assets/webapp/linux",
        "查询 Linux 主机 Web 应用清单（每台主机每个 Web 应用一条）",
        [
            _p("appName", "string", False, "Web 应用名（模糊查询）"),
            _p("version", "string", False, "应用版本，多个用逗号分隔"),
            _p("rootPath", "string", False, "根路径（模糊查询）"),
            _p("webRoot", "string", False, "应用路径（模糊查询）"),
            _p("serverName", "string", False, "服务名（模糊查询）"),
            _p("domainName", "string", False, "域名（模糊查询）"),
        ],
        _HOST_RESP + ["appName: Web 应用名", "version: 版本", "rootPath/webRoot: 根路径/应用路径", "serverName: 服务名", "domainName: 域名"],
    ),
    _list_action(
        "qt_assets_webapp_list_win",
        "Web应用信息查询-Windows",
        "/external/api/assets/webapp/win",
        "查询 Windows 主机 Web 应用清单（每台主机每个 Web 应用一条）",
        [
            _p("appName", "string", False, "Web 应用名（模糊查询）"),
            _p("version", "string", False, "应用版本，多个用逗号分隔"),
            _p("rootPath", "string", False, "根路径（模糊查询）"),
            _p("webRoot", "string", False, "应用路径（模糊查询）"),
            _p("serverName", "string", False, "服务名（模糊查询）"),
            _p("domainName", "string", False, "域名（模糊查询）"),
        ],
        _HOST_RESP + ["appName: Web 应用名", "version: 版本", "rootPath/webRoot: 根路径/应用路径", "serverName: 服务名", "domainName: 域名"],
    ),
    _list_action(
        "qt_assets_website_list_linux",
        "Web站点信息查询-Linux",
        "/external/api/assets/website/linux",
        "查询 Linux 主机 Web 站点清单（每台主机每个站点一条）",
        [
            _p("port", "string", False, "站点端口"),
            _p("proto", "string", False, "协议，多个用逗号分隔"),
            _p("type", "string", False, "站点类型，多个用逗号分隔"),
            _p("rootPath", "string", False, "根路径（模糊查询）"),
        ],
        _HOST_RESP + ["port: 端口", "proto: 协议", "type: 站点类型", "rootPath: 根路径"],
    ),
    _list_action(
        "qt_assets_website_list_win",
        "Web站点信息查询-Windows",
        "/external/api/assets/website/win",
        "查询 Windows 主机 Web 站点清单（每台主机每个站点一条）",
        [
            _p("port", "string", False, "站点端口"),
            _p("proto", "string", False, "协议，多个用逗号分隔"),
            _p("type", "string", False, "站点类型，多个用逗号分隔"),
            _p("rootPath", "string", False, "根路径（模糊查询）"),
        ],
        _HOST_RESP + ["port: 端口", "proto: 协议", "type: 站点类型", "rootPath: 根路径"],
    ),
    _list_action(
        "qt_assets_app_list_linux",
        "软件应用信息查询-Linux",
        "/external/api/assets/app/linux",
        "查询 Linux 主机软件应用清单（每台主机每个软件应用一条，含关联进程）",
        [
            _p("name", "string", False, "软件应用名称（模糊查询）"),
            _p("version", "string", False, "软件应用版本，多个用逗号分隔"),
            _p("binPath", "string", False, "二进制路径（模糊查询）"),
            _p("configPath", "string", False, "配置文件路径（模糊查询）"),
        ],
        _HOST_RESP + ["name: 软件应用名", "version: 版本", "uname: 启动用户", "binPath: 二进制路径", "configPath: 配置文件路径", "processes: 关联进程列表(pid/name/uname)"],
    ),
    _list_action(
        "qt_assets_app_list_win",
        "软件应用信息查询-Windows",
        "/external/api/assets/app/win",
        "查询 Windows 主机软件应用清单（每台主机每个软件应用一条，含关联进程）",
        [
            _p("name", "string", False, "软件应用名称（模糊查询）"),
            _p("version", "string", False, "软件应用版本，多个用逗号分隔"),
            _p("binPath", "string", False, "安装路径（模糊查询）"),
            _p("configPath", "string", False, "配置文件路径（模糊查询）"),
        ],
        _HOST_RESP + ["name: 软件应用名", "version: 版本", "uname: 启动用户", "binPath: 安装路径", "configPath: 配置文件路径", "processes: 关联进程列表(pid/name/uname)"],
    ),
    _list_action(
        "qt_assets_webframe_list_linux",
        "Web应用框架信息查询-Linux",
        "/external/api/assets/webframe/linux",
        "查询 Linux 主机 Web 应用框架清单（每台主机每个框架一条）",
        [
            _p("name", "string", False, "Web 应用框架名称（模糊查询）"),
            _p("version", "string", False, "框架版本，多个用逗号分隔"),
            _p("type", "string", False, "框架语言，多个用逗号分隔"),
            _p("serverName", "string", False, "服务类型，多个用逗号分隔"),
        ],
        _HOST_RESP + ["name: 框架名", "version: 版本", "type: 框架语言", "serverName: 服务类型", "domainName: 站点域名", "webAppDir: 框架绝对路径"],
    ),
    _list_action(
        "qt_assets_webframe_list_win",
        "Web应用框架信息查询-Windows",
        "/external/api/assets/webframe/win",
        "查询 Windows 主机 Web 应用框架清单（每台主机每个框架一条）",
        [
            _p("name", "string", False, "Web 应用框架名称（模糊查询）"),
            _p("version", "string", False, "框架版本，多个用逗号分隔"),
            _p("type", "string", False, "框架语言，多个用逗号分隔"),
            _p("serverName", "string", False, "服务类型，多个用逗号分隔"),
        ],
        _HOST_RESP + ["name: 框架名", "version: 版本", "type: 框架语言", "serverName: 服务类型", "domainName: 站点域名", "webAppDir: 框架绝对路径"],
    ),
    _list_action(
        "qt_assets_dbinfo_list_linux",
        "数据库信息查询-Linux",
        "/external/api/assets/dbinfo/linux",
        "查询 Linux 主机数据库清单（每台主机每个数据库一条）",
        [
            _p("name", "string", False, "数据库类型（模糊查询）"),
            _p("versions", "string", False, "数据库版本，多个用逗号分隔"),
            _p("port", "integer", False, "监听端口"),
            _p("confPath", "string", False, "配置文件路径（模糊查询）"),
            _p("logPath", "string", False, "日志文件路径（模糊查询）"),
            _p("dataDir", "string", False, "数据路径（模糊查询）"),
        ],
        _HOST_RESP + ["name: 数据库类型", "version: 版本", "port/protoType: 监听端口/协议", "user: 运行用户", "bindIp: 绑定 IP", "confPath/logPath/dataDir: 配置/日志/数据路径"],
    ),
    _list_action(
        "qt_assets_dbinfo_list_win",
        "数据库信息查询-Windows",
        "/external/api/assets/dbinfo/win",
        "查询 Windows 主机数据库清单（每台主机每个数据库一条）",
        [
            _p("name", "string", False, "数据库类型（模糊查询）"),
            _p("versions", "string", False, "数据库版本，多个用逗号分隔"),
            _p("port", "integer", False, "监听端口"),
            _p("confPath", "string", False, "配置文件路径（模糊查询）"),
            _p("logPath", "string", False, "日志文件路径（模糊查询）"),
            _p("dataDir", "string", False, "数据路径（模糊查询）"),
        ],
        _HOST_RESP + ["name: 数据库类型", "version: 版本", "port/protoType: 监听端口/协议", "user: 运行用户", "bindIp: 绑定 IP", "dbName: 数据库实例名(仅windows)"],
    ),
    _list_action(
        "qt_assets_service_list_linux",
        "启动项信息查询-Linux",
        "/external/api/assets/service/linux",
        "查询 Linux 主机启动项清单（每台主机每个启动项一条）",
        [
            _p("name", "string", False, "启动项名（模糊查询）"),
            _p("initLevel", "string", False, "默认启动模式，多个用逗号分隔"),
            _p("defaultOpen", "string", False, "默认模式启用状态，多个用逗号分隔（true/false）"),
            _p("isXinetd", "string", False, "启动方式，多个用逗号分隔（true/false）"),
        ],
        _HOST_RESP + ["name: 启动项名", "initLevel: 默认启动模式", "defaultOpen: 默认模式启用状态", "rc0~rc7: 各运行级别状态", "xinetd: 启动方式"],
    ),
    _list_action(
        "qt_assets_service_list_win",
        "启动项信息查询-Windows",
        "/external/api/assets/service/win",
        "查询 Windows 主机启动项/服务清单（每台主机每个启动项一条）",
        [
            _p("name", "string", False, "启动项名（模糊查询）"),
            _p("showName", "string", False, "启动项显示名（模糊查询，仅 windows）"),
            _p("user", "string", False, "服务启动用户（仅 windows）"),
            _p("enable", "string", False, "服务状态（true/false，仅 windows）"),
            _p("startType", "string", False, "启动类型，多个用逗号分隔（仅 windows）"),
            _p("publisher", "string", False, "发布者（仅 windows）"),
        ],
        _HOST_RESP + ["name/showName: 启动项名/显示名", "user: 服务启动用户", "enable: 服务状态", "startType: 启动类型", "publisher: 发布者"],
    ),
    _list_action(
        "qt_assets_task_list_linux",
        "计划任务信息查询-Linux",
        "/external/api/assets/task/linux",
        "查询 Linux 主机计划任务清单（每台主机每个计划任务一条）",
        [
            _p("user", "string", False, "执行用户，多个用逗号分隔"),
            _p("execPath", "string", False, "执行命令或脚本（模糊查询）"),
            _p("conf", "string", False, "配置文件（模糊查询）"),
            _p("taskTime", "string", False, "执行时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
            _p("taskType", "string", False, "任务类型（仅 CRONTAB/AT/BATCH 三类）"),
        ],
        _HOST_RESP + ["user: 执行用户", "execTime: 执行周期", "execPath: 执行命令或脚本", "conf: 配置文件", "taskTime: 执行时间", "taskType: 任务类型", "crondOpen: 启用状态"],
    ),
    _list_action(
        "qt_assets_env_list_linux",
        "环境变量信息查询-Linux",
        "/external/api/assets/env/linux",
        "查询 Linux 主机环境变量清单（每台主机每个环境变量一条）",
        [
            _p("key", "string", False, "环境变量名"),
            _p("value", "string", False, "环境变量值"),
            _p("user", "string", False, "用户"),
            _p("sysEnv", "string", False, "环境变量类型，多个用逗号分隔（true/false）"),
        ],
        _HOST_RESP + ["key: 环境变量名", "value: 环境变量值", "user: 用户", "sysEnv: 环境变量类型"],
    ),
    _list_action(
        "qt_assets_kernelmodule_list_linux",
        "内核模块信息查询-Linux",
        "/external/api/assets/kernelmodule/linux",
        "查询 Linux 主机内核模块清单（每台主机每个内核模块一条）",
        [
            _p("moduleName", "string", False, "模块名称（模糊查询）"),
            _p("path", "string", False, "模块路径（模糊查询）"),
            _p("version", "string", False, "模块版本，多个用逗号分隔"),
        ],
        _HOST_RESP + ["moduleName: 模块名称", "path: 模块路径", "version: 模块版本"],
    ),
    _list_action(
        "qt_assets_pkg_list_linux",
        "安装包信息查询-Linux",
        "/external/api/assets/pkg/linux",
        "查询 Linux 主机安装包清单（每台主机每个安装包一条）",
        [
            _p("name", "string", False, "安装包名（模糊查询）"),
            _p("type", "string", False, "安装类型，多个用逗号分隔（仅 Linux，如 rpm/dpkg）"),
            _p("installTime", "string", False, "安装时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
        ],
        _HOST_RESP + ["name: 安装包名", "version: 版本", "type: 安装类型", "installTime: 安装时间", "summary: 总述(仅linux)"],
    ),
    _list_action(
        "qt_assets_pkg_list_win",
        "安装包信息查询-Windows",
        "/external/api/assets/pkg/win",
        "查询 Windows 主机安装包清单（每台主机每个安装包一条）",
        [
            _p("name", "string", False, "安装包名（模糊查询）"),
            _p("publisher", "string", False, "软件发布者（仅 windows）"),
            _p("path", "string", False, "安装路径（仅 windows）"),
            _p("productVersion", "string", False, "安装版本（仅 windows）"),
            _p("psize", "integer", False, "软件大小档位 1~5（仅 windows，对应 [0,1MB]/[1,10MB]/[10,100MB]/[100,1024MB]/[1024MB+]）"),
            _p("installTime", "string", False, "安装时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
        ],
        _HOST_RESP + ["name: 安装包名", "version: 版本", "publisher: 发布者", "path: 安装路径", "productVersion: 安装版本", "pkgSize: 软件大小"],
    ),
    _list_action(
        "qt_assets_jarpkg_list_linux",
        "jar包信息查询-Linux",
        "/external/api/assets/jar_pkg/linux",
        "查询 Linux 主机 jar 包清单（每台主机每个 jar 包一条）",
        [
            _p("name", "string", False, "包名（模糊查询）"),
            _p("version", "string", False, "版本，多个用逗号分隔"),
            _p("type", "string", False, "类型，多个用逗号分隔（1:应用程序 2:系统类库 3:web服务自带库 8:其他依赖包）"),
            _p("executable", "string", False, "是否可执行，多个用逗号分隔（true/false）"),
            _p("path", "string", False, "绝对路径（模糊查询）"),
        ],
        _HOST_RESP + ["name: 包名", "version: 版本", "type: 类型", "executable: 是否可执行", "path: 绝对路径"],
    ),
    _action(
        "qt_assets_group_list_linux",
        "业务组查询-Linux",
        "GET",
        "/external/api/assets/group/linux",
        "查询全部 Linux 业务组（含层级关系），无请求参数",
        [],
        ["id: 业务组 ID", "parent: 父业务组 ID（0 表示第一层）", "name: 业务组名", "relationshipName: 业务组全路径名", "platform: 平台（1:linux 2:windows）", "description: 描述"],
    ),
    _action(
        "qt_assets_group_list_win",
        "业务组查询-Windows",
        "GET",
        "/external/api/assets/group/win",
        "查询全部 Windows 业务组（含层级关系），无请求参数",
        [],
        ["id: 业务组 ID", "parent: 父业务组 ID（0 表示第一层）", "name: 业务组名", "relationshipName: 业务组全路径名", "platform: 平台（1:linux 2:windows）", "description: 描述"],
    ),
]


# ============ 二、风险发现（vul / websecurity）============

# 补丁/漏洞/弱密码列表类接口的公共返回字段（扫描结果行）
_VUL_ROW_RESP = [
    "id: String - 本条扫描结果唯一标识",
    "agentId/hostname/displayIp/internalIp/externalIp: 主机标识",
    "bizGroupId/bizGroup/remark/hostTags: 业务组与标签",
    "vulId/patchId: 风险/补丁 ID",
    "whiteRuleEffect: 是否匹配白名单",
    "updatedTime: 最后更新时间",
]

# 漏洞检测作业（poc/job）POST 查询类接口的公共入参
_JOB_PARAMS = [
    _p("jobId", "string", True, "作业 ID"),
    _p("jobType", "integer", True, "作业类型：1-全局作业 2-用户作业"),
]


def _vul_status_action(at: str, name: str, path: str) -> dict[str, Any]:
    """构造扫描状态查询动作（无入参，返回 status）。"""
    return _action(
        at, name, "GET", path,
        "查询最近一次扫描任务的执行状态，无请求参数",
        [],
        ["status: String - Running(执行中)/Success(成功)/Failed(失败)；从未执行过时为 Success"],
    )


def _poc_job_action(at: str, name: str, op: str, desc: str, resp: list[str],
                    extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """构造漏洞检测作业 POST 查询动作（查询语义的 POST，参数走 JSON body）。"""
    return _action(
        at, name, "POST", f"/external/api/vul/poc/job/{{os}}/{op}",
        desc,
        (_JOB_PARAMS + (extra or []) + _page()),
        resp,
    )


VUL_ACTIONS: list[dict[str, Any]] = [
    # ---- 安全补丁（patch）----
    _vul_status_action("qt_vul_patch_status_linux", "补丁扫描状态查询-Linux",
                       "/external/api/vul/patch/linux/check/status"),
    _vul_status_action("qt_vul_patch_status_win", "补丁扫描状态查询-Windows",
                       "/external/api/vul/patch/win/check/status"),
    _list_action(
        "qt_vul_patch_list_linux",
        "补丁检测结果查询-Linux",
        "/external/api/vul/patch/linux/list",
        "查询 Linux 主机补丁检测结果（每台主机每个待修复补丁一条）",
        [],
        _VUL_ROW_RESP + ["patchId: 补丁 ID", "businessImpact: 是否存在进程影响 0/1（仅 linux）"],
    ),
    _list_action(
        "qt_vul_patch_list_win",
        "补丁检测结果查询-Windows",
        "/external/api/vul/patch/win/list",
        "查询 Windows 主机补丁检测结果（每台主机每个待修复补丁一条）",
        [],
        _VUL_ROW_RESP + ["patchId: 补丁 ID", "kbNum/bulletId: KB 号/公告号（仅 windows）"],
    ),
    _action(
        "qt_vul_patch_detail_linux",
        "补丁详情查询-Linux",
        "GET",
        "/external/api/vul/patch/linux/{id}",
        "查询单条 Linux 补丁扫描结果的详情（补丁描述、CVSS、修复建议等）",
        [_p("id", "string", True, "扫描结果唯一标识（路径参数，list 接口返回的 id）")],
        ["patchId/patchName: 补丁 ID/名", "severity: 危险程度", "publishTime: 发布时间", "desc: 补丁描述", "remedDesc/remedCmd: 修复建议/修复命令（仅 linux）", "cvssScore/cvssDetail: CVSS 分值/详情", "ref: CVE 链接", "restartOpts: 修复影响 0-可能重启/1-不需要重启/2-服务重启/3-系统重启", "hasExp/isKernel/isLocalEscalation/isRemote/hasPoc: 漏洞特征（仅 linux）", "impacts: 补丁特征（仅 windows）"],
    ),
    _action(
        "qt_vul_patch_detail_win",
        "补丁详情查询-Windows",
        "GET",
        "/external/api/vul/patch/win/{id}",
        "查询单条 Windows 补丁扫描结果的详情（补丁描述、CVSS、修复建议等）",
        [_p("id", "string", True, "扫描结果唯一标识（路径参数，list 接口返回的 id）")],
        ["patchId/patchName: 补丁 ID/名", "kbNum/bulletId: KB 号/公告号（仅 windows）", "severity: 危险程度", "publishTime: 发布时间", "desc: 补丁描述", "installPackage: 安装包地址（仅 windows）", "cvssScore/cvssDetail: CVSS 分值/详情", "ref: CVE 链接", "restartOpts: 修复影响", "impacts: 补丁特征（仅 windows）"],
    ),
    _vul_status_action("qt_vul_patch_impact_status_linux", "补丁进程影响任务状态查询-Linux",
                        "/external/api/vul/patch/linux/business_impact/check/status"),
    _action(
        "qt_vul_patch_impact_detail_linux",
        "补丁进程影响查询-Linux",
        "GET",
        "/external/api/vul/patch/linux/business_impact/{patchId}",
        "查询某个 Linux 补丁的进程影响（受影响进程列表）",
        [_p("patchId", "string", True, "补丁 ID（路径参数，如 QT012016000970）")],
        ["patchId: 补丁 ID", "processes: 受影响进程列表"],
    ),
]

# ---- Linux 应用风险/系统风险/对外访问性/账号风险（vul/{app|system|access|account}）----
_VUL_KINDS = [
    ("app", "应用风险", "SSH/数据库等应用配置类风险"),
    ("system", "系统风险", "内核与系统配置类风险"),
    ("access", "对外访问性", "主机端口暴露面风险"),
    ("account", "账号风险", "账号安全配置类风险"),
]
for _kind, _label, _tip in _VUL_KINDS:
    VUL_ACTIONS.extend([
        _vul_status_action(
            f"qt_vul_{_kind}_status_linux",
            f"{_label}扫描状态查询-Linux",
            f"/external/api/vul/{_kind}/linux/check/status",
        ),
        _list_action(
            f"qt_vul_{_kind}_list_linux",
            f"{_label}检测结果查询-Linux",
            f"/external/api/vul/{_kind}/linux/list",
            f"查询 Linux 主机{_label}（{_tip}）检测结果",
            [],
            _VUL_ROW_RESP,
        ),
        _action(
            f"qt_vul_{_kind}_detail_linux",
            f"{_label}详情查询-Linux",
            "GET",
            f"/external/api/vul/{_kind}/linux/{{id}}",
            f"查询单条 Linux {_label}扫描结果详情",
            [_p("id", "string", True, "扫描结果唯一标识（路径参数，list 接口返回的 id）")],
            ["vulId/vulName: 风险 ID/名", "severity: 危险程度 0-信息/1-低危/2-中危/3-高危/4-危急", "apps: 影响的应用", "desc: 风险描述", "checkInfo/checkResult: 验证信息/结果", "remedDesc: 修复建议", "refs: 引用信息", "firstCheckTime: 首次检测时间"],
        ),
    ])

VUL_ACTIONS.extend([
    # ---- 弱密码（weakpwd）----
    _vul_status_action("qt_vul_weakpwd_status_linux", "弱密码扫描状态查询-Linux",
                       "/external/api/vul/weakpwd/linux/check/status"),
    _vul_status_action("qt_vul_weakpwd_status_win", "弱密码扫描状态查询-Windows",
                       "/external/api/vul/weakpwd/win/check/status"),
    _list_action(
        "qt_vul_weakpwd_list_linux",
        "弱密码检测结果查询-Linux",
        "/external/api/vul/weakpwd/linux/list",
        "查询 Linux 主机弱密码风险检测结果",
        [],
        _VUL_ROW_RESP,
    ),
    _list_action(
        "qt_vul_weakpwd_list_win",
        "弱密码检测结果查询-Windows",
        "/external/api/vul/weakpwd/win/list",
        "查询 Windows 主机弱密码风险检测结果",
        [],
        _VUL_ROW_RESP,
    ),
    _action(
        "qt_vul_weakpwd_detail_linux",
        "弱密码风险详情查询-Linux",
        "GET",
        "/external/api/vul/weakpwd/linux/{id}",
        "查询单条 Linux 弱密码扫描结果详情",
        [_p("id", "string", True, "扫描结果唯一标识（路径参数，list 接口返回的 id）")],
        ["vulId/vulName: 风险 ID/名", "app/uname/version/binPath: 弱密码应用/用户名/版本/路径", "weakType: 弱密码类型 1-空密码/2-默认弱密码/3-跟用户名相同/4-常见弱密码", "accountStatus: 账号状态", "port/bindIp/pid: 端口/绑定IP/进程", "remedDesc: 修复建议"],
    ),
    _action(
        "qt_vul_weakpwd_detail_win",
        "弱密码风险详情查询-Windows",
        "GET",
        "/external/api/vul/weakpwd/win/{id}",
        "查询单条 Windows 弱密码扫描结果详情",
        [_p("id", "string", True, "扫描结果唯一标识（路径参数，list 接口返回的 id）")],
        ["vulId/vulName: 风险 ID/名", "uname: 用户名", "weakType: 弱密码类型 1-空密码/2-默认弱密码/3-跟用户名相同/4-常见弱密码", "accountStatus: 账号状态 0-正常/1-锁定/2-禁用", "remedDesc: 修复建议"],
    ),
    # ---- Web 风险文件（weakfile）----
    _list_action(
        "qt_weakfile_list_linux",
        "Web风险文件查询-Linux",
        "/external/api/websecurity/weakfile/linux",
        "查询 Linux 主机 Web 风险文件（泄露的敏感文件）检测结果",
        [
            _p("filePath", "string", False, "文件名（模糊查询）"),
            _p("serverName", "string", False, "域名（模糊查询）"),
            _p("serverNameEq", "string", False, "域名（精确查找）"),
            _p("regexTypes", "string", False, "风险文件类型，多个用逗号分隔（1-临时文件 2-压缩文件 3-备份文件泄露 4-数据文件泄露 5-配置文件泄露 6-日志泄露 7-脚本泄露 8-Office文档 9-源代码泄露 10-系统文件 11-phpinfo文件）"),
            _p("port", "integer", False, "主机端口"),
            _p("portStatus", "string", False, "端口访问性，多个用逗号分隔（-1-未知 0-关闭 1-打开）"),
            _p("translate", "string", False, "解析方式，多个用逗号分隔（0-host解析 1-dns解析）"),
        ],
        _HOST_RESP + ["id: 记录 ID", "port/portStatus: 端口/访问性", "serverName/filePath: 域名/文件路径", "regexLevel: 危险等级 1-低危/2-中危/3-高危", "regexType/regexTypeDesc: 类型/描述", "checkUrl: 验证路径", "modifyTime: 最后修改时间(时间戳)", "download: 是否可下载", "whiteRuleEffect: 是否命中白名单"],
    ),
    _list_action(
        "qt_weakfile_list_win",
        "Web风险文件查询-Windows",
        "/external/api/websecurity/weakfile/win",
        "查询 Windows 主机 Web 风险文件（泄露的敏感文件）检测结果",
        [
            _p("filePath", "string", False, "文件名（模糊查询）"),
            _p("serverName", "string", False, "域名（模糊查询）"),
            _p("serverNameEq", "string", False, "域名（精确查找）"),
            _p("regexTypes", "string", False, "风险文件类型，多个用逗号分隔（1-临时文件 2-压缩文件 3-备份文件泄露 4-数据文件泄露 5-配置文件泄露 6-日志泄露 7-脚本泄露 8-Office文档 9-源代码泄露 10-系统文件 11-phpinfo文件）"),
            _p("port", "integer", False, "主机端口"),
            _p("portStatus", "string", False, "端口访问性，多个用逗号分隔（-1-未知 0-关闭 1-打开）"),
            _p("translate", "string", False, "解析方式，多个用逗号分隔（0-host解析 1-dns解析）"),
        ],
        _HOST_RESP + ["id: 记录 ID", "port/portStatus: 端口/访问性", "serverName/filePath: 域名/文件路径", "regexLevel: 危险等级 1-低危/2-中危/3-高危", "regexType/regexTypeDesc: 类型/描述", "checkUrl: 验证路径", "modifyTime: 最后修改时间(时间戳)", "download: 是否可下载", "whiteRuleEffect: 是否命中白名单"],
    ),
    _action(
        "qt_weakfile_status_linux",
        "Web风险文件扫描状态查询-Linux",
        "GET",
        "/external/api/websecurity/weakfile/linux/check/status",
        "查询 Web 风险文件扫描任务状态，无请求参数",
        [],
        ["retcode: Integer - -1-无任务 0-未开始执行 1-排队执行 2-正在执行 3-执行成功 4-执行失败"],
    ),
    _action(
        "qt_weakfile_status_win",
        "Web风险文件扫描状态查询-Windows",
        "GET",
        "/external/api/websecurity/weakfile/win/check/status",
        "查询 Web 风险文件扫描任务状态，无请求参数",
        [],
        ["retcode: Integer - -1-无任务 0-未开始执行 1-排队执行 2-正在执行 3-执行成功 4-执行失败"],
    ),
    # ---- 漏洞检测（poc）----
    _vul_status_action("qt_vul_poc_status_linux", "漏洞检测状态查询-Linux",
                       "/external/api/vul/poc/linux/check/status"),
    _vul_status_action("qt_vul_poc_status_win", "漏洞检测状态查询-Windows",
                       "/external/api/vul/poc/win/check/status"),
    _list_action(
        "qt_vul_poc_list_linux",
        "漏洞检测结果查询-Linux",
        "/external/api/vul/poc/linux/list",
        "查询 Linux 主机漏洞（POC/版本比对）检测结果",
        [],
        _VUL_ROW_RESP,
    ),
    _list_action(
        "qt_vul_poc_list_win",
        "漏洞检测结果查询-Windows",
        "/external/api/vul/poc/win/list",
        "查询 Windows 主机漏洞（POC/版本比对）检测结果",
        [],
        _VUL_ROW_RESP,
    ),
    _action(
        "qt_vul_poc_detail_linux",
        "漏洞风险详情查询-Linux",
        "GET",
        "/external/api/vul/poc/linux/{recordId}",
        "查询单条 Linux 漏洞检测结果详情（检测原理、CVSS、修复建议等）",
        [_p("recordId", "string", True, "扫描结果唯一标识（路径参数，list 接口返回的 id）")],
        ["vulId/vulName: 漏洞 ID/名", "severity: 危险程度 0-信息/1-低危/2-中危/3-高危/4-危急", "apps: 影响的应用", "desc: 漏洞描述", "checkInfo/pocCheckInfo: 版本比对/POC 检测信息", "data: 检测原始数据", "remedDescription: 修复建议", "cvss/cvssScore: CVSS 详情/分值", "cves/expRefs/pocRefs: CVE 编号/参考链接", "kernel/remote/localEscalation/hasExp/hasPoc: 漏洞特征"],
    ),
    _action(
        "qt_vul_poc_detail_win",
        "漏洞风险详情查询-Windows",
        "GET",
        "/external/api/vul/poc/win/{recordId}",
        "查询单条 Windows 漏洞检测结果详情（检测原理、CVSS、修复建议等）",
        [_p("recordId", "string", True, "扫描结果唯一标识（路径参数，list 接口返回的 id）")],
        ["vulId/vulName: 漏洞 ID/名", "severity: 危险程度", "apps: 影响的应用", "desc: 漏洞描述", "checkInfo: 检测信息", "data: 检测原始数据", "remedDescription: 修复建议", "cvss/cvssScore: CVSS 详情/分值", "cves/expRefs/pocRefs: CVE 编号/参考链接"],
    ),
    _action(
        "qt_vul_poc_rule_list_linux",
        "漏洞检测项列表查询-Linux",
        "GET",
        "/external/api/vul/poc/job/rule_list",
        "查询 Linux 全部可用漏洞检测项（含检测方式、执行风险、输入参数定义）",
        [],
        ["vulId/title: 检测项 ID/名", "description: 风险描述", "category: 类别", "remedDescription: 修复建议", "permitExecuteTypes: 允许的检测方式 1-版本对比 2-POC检测", "executeSeverity/executeSeverityTip: 检测脚本执行风险/提示", "updateTime: 更新时间", "inputSchemas: 输入参数定义列表"],
    ),
    _action(
        "qt_vul_poc_rule_list_win",
        "漏洞检测项列表查询-Windows",
        "GET",
        "/external/api/vul/poc/job/win/rule_list",
        "查询 Windows 全部可用漏洞检测项（含检测方式、执行风险、输入参数定义）",
        [],
        ["vulId/title: 检测项 ID/名", "description: 风险描述", "category: 类别", "remedDescription: 修复建议", "permitExecuteTypes: 允许的检测方式 1-版本对比 2-POC检测", "executeSeverity/executeSeverityTip: 检测脚本执行风险/提示", "updateTime: 更新时间", "inputSchemas: 输入参数定义列表"],
    ),
])

# ---- 漏洞检测作业（poc/job，POST 查询语义）----
for _os, _os_label in (("linux", "Linux"), ("win", "Windows")):
    VUL_ACTIONS.extend([
        _poc_job_action(
            f"qt_vul_pocjob_status_{_os}",
            f"漏洞检测作业状态查询-{_os_label}",
            "status",
            f"查询 {_os_label} 漏洞检测作业的执行状态（查询语义 POST，参数走 JSON body）",
            ["id: 扫描任务 ID", "status: Running/Success/Failed"],
        ),
        _poc_job_action(
            f"qt_vul_pocjob_errorhost_{_os}",
            f"漏洞检测作业失败主机查询-{_os_label}",
            "error_host",
            f"查询 {_os_label} 漏洞检测作业执行失败的主机列表（查询语义 POST，参数走 JSON body）",
            ["agentId/hostname/displayIp: 主机标识", "vulId/title: 检测项", "code: 失败码", "description: 失败描述"],
        ),
        _poc_job_action(
            f"qt_vul_pocjob_list_{_os}",
            f"漏洞检测作业列表查询-{_os_label}",
            "list",
            f"查询 {_os_label} 用户的全部漏洞检测作业（查询语义 POST，参数走 JSON body；jobType 必传）",
            ["jobId/name: 作业 ID/名", "jobType: 作业类型", "status: 是否启用", "realmName: 执行范围名", "lastExecuteTime: 最后执行时间", "taskCount: 检测项数", "executeStatus: 执行状态"],
            extra=[_p("jobName", "string", False, "作业名（可选过滤）")],
        ),
        _poc_job_action(
            f"qt_vul_pocjob_tasks_{_os}",
            f"漏洞检测作业检测项查询-{_os_label}",
            "tasks",
            f"查询 {_os_label} 漏洞检测作业下包含的检测项列表（查询语义 POST，参数走 JSON body）",
            ["id/vulId: 检测项 ID", "title: 检测项名", "executeTypes/permitExecuteTypes: 检测方式", "category: 类别", "executeSeverity: 执行风险", "inputSchemas: 输入参数定义"],
        ),
        _poc_job_action(
            f"qt_vul_pocjob_stats_{_os}",
            f"漏洞检测作业执行统计查询-{_os_label}",
            "stats",
            f"查询 {_os_label} 漏洞检测作业执行的基本统计信息（查询语义 POST，参数走 JSON body）",
            ["jobId/jobName: 作业 ID/名", "executeStatus: 执行状态 0-未开始 1-排队 2-正在执行 3-成功 4-失败", "lastExecuteTime: 最后执行时间", "duration: 执行耗时(秒)", "vulCount/hostCount/taskCount: 漏洞/主机/检测项数", "successHostCount/failedHostCount: 成功/失败主机数"],
        ),
        _poc_job_action(
            f"qt_vul_pocjob_resultdetail_{_os}",
            f"漏洞检测作业结果查询-{_os_label}",
            "result_detail",
            f"查询 {_os_label} 漏洞检测作业执行的漏洞结果明细（查询语义 POST，参数走 JSON body）",
            ["vulId/vulName: 漏洞 ID/名", "severity: 危险程度", "apps/desc: 影响应用/描述", "checkInfo/pocCheckInfo: 检测信息", "remedDescription: 修复建议", "cvss/cvssScore: CVSS", "agentId/hostname/displayIp: 主机标识"],
        ),
    ])

VUL_ACTIONS.append(
    _action(
        "qt_vul_linux_check_status",
        "Linux全部风险扫描状态查询",
        "GET",
        "/external/api/vul/linux/check/status",
        "查询 Linux 全部风险（除风险文件外）扫描任务的执行状态，无请求参数",
        [],
        ["status: String - Running/Success/Failed"],
    ),
)


# ============ 三、入侵检测（detect / websecurity）============

# 入侵检测事件行公共返回字段
_DETECT_ROW_RESP = _HOST_RESP + [
    "发现时间字段（logTime/loginTime/createTime/time，时间戳秒级）",
]

DETECT_ACTIONS: list[dict[str, Any]] = [
    _list_action(
        "qt_detect_shelllog_list_linux",
        "可疑操作查询-Linux",
        "/external/api/detect/shelllog/linux",
        "查询 Linux 主机可疑操作（bash 命令执行）上报日志，可按审核状态与可疑操作类型过滤",
        [
            _p("logTime", "string", False, "上报时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
            _p("auditStatus", "string", False, "审核状态，多个用逗号分隔：1-未审核 2-审核通过 3-审核未通过"),
            _p("status", "string", False, "可疑操作类型，多个用逗号分隔（0-未命中规则 1-bash危险命令执行 2~6-各类下载黑客工具 7/8-数据库明文密码显示 9~11-外部上传下载 12-赋危险权限）"),
            _p("cmd", "string", False, "命令内容"),
            _p("loginIp", "string", False, "登录主机 IP"),
            _p("loginUser", "string", False, "登录用户"),
        ],
        _DETECT_ROW_RESP + ["cmd/cmdNoHightLight: 操作内容(带/不带tag)", "hitRuleName: 命中规则", "status: 可疑操作类型", "loginUser/loginIp: 登录用户/IP", "auditStatus: 审核状态"],
    ),
]

# ---- 暴力破解（brutecrack，linux/win 同构）----
for _os, _os_label in (("linux", "Linux"), ("win", "Windows")):
    DETECT_ACTIONS.extend([
        _list_action(
            f"qt_detect_brutecrack_list_{_os}",
            f"暴力破解查询-{_os_label}",
            f"/external/api/detect/brutecrack/{_os}",
            f"查询 {_os_label} 主机暴力破解攻击事件（攻击来源、服务类型、封停状态）",
            [
                _p("loginTime", "string", False, "攻击时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
                _p("serviceType", "string", False, "服务类型，多个用逗号分隔：Linux 1-SSHD 2-VSFTPD；Windows 100-RDP 101-WINRM 102-SSH"),
                _p("block", "string", False, "封停状态，多个用逗号分隔：0-未处理 1-自动封停 2-自动解封 3-手动封停 4-手动解封 5-解封中 6-封停中 -1-封停失败 -2-解封失败"),
                _p("clientIp", "string", False, "攻击来源 IP"),
            ],
            _DETECT_ROW_RESP + ["id: 记录 ID", "serviceType/serverName: 服务类型/名", "clientIp: 攻击来源 IP", "block: 封停状态"],
        ),
        _list_action(
            f"qt_detect_brutecrack_log_{_os}",
            f"暴力破解攻击记录查询-{_os_label}",
            f"/external/api/detect/brutecrack/{_os}/log",
            f"查询 {_os_label} 某次暴力破解攻击的上报事件明细（每次登录尝试）",
            [_p("crackId", "string", True, "攻击 ID（必填，查询结果接口返回的 id 字段）")],
            ["loginTime: 攻击时间(时间戳)", "reason: 登录失败原因，1-用户名不存在", "uname: 尝试的用户名列表", "status: 状态", "block: 封停状态", "blockDuration: 封停时长(秒)"],
        ),
    ])

# ---- 异常登录（abnormallogin，linux/win 同构）----
for _os, _os_label in (("linux", "Linux"), ("win", "Windows")):
    DETECT_ACTIONS.extend([
        _list_action(
            f"qt_detect_abnormallogin_list_{_os}",
            f"异常登录查询-{_os_label}",
            f"/external/api/detect/abnormallogin/{_os}",
            f"查询 {_os_label} 主机异常登录上报事件（异常 IP/区域/时间）",
            [
                _p("loginTime", "string", False, "登录时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
                _p("flag", "string", False, "异常登录类型，多个用逗号分隔：2-异常IP 3-异常区域 4-异常时间"),
                _p("uname", "string", False, "用户名"),
                _p("clientIp", "string", False, "来源 IP"),
            ],
            _DETECT_ROW_RESP + ["uname/clientIp/clientLocation: 用户名/来源IP/登录区域", "evilIpDb: 是否恶意IP库 0-否 1-是", "crackSuccess: 是否暴力破解成功 0-否 1-是", "abnormalIp/abnormalLocation/abnormalTime: 不在常用IP段/区域/时间登录 0-否 1-是", "whiteRuleEffect: 是否命中白名单"],
        ),
        _list_action(
            f"qt_detect_abnormallogin_rule_list_{_os}",
            f"正常登录规则列表查询-{_os_label}",
            f"/external/api/detect/abnormallogin/{_os}/rule",
            f"查询 {_os_label} 异常登录正常规则（白名单规则）列表",
            [
                _p("loginIp", "string", False, "登录 IP"),
                _p("loginLocation", "string", False, "登录区域"),
            ],
            ["id: 规则 ID", "osType: 系统类型 1-linux 2-windows", "realmKind: 主机范围 0-全部主机 1-主机 2-业务组", "realmGroup/realmAgentId/realmAgentGroup: 业务组/主机/主机所在业务组", "condition: 规则详情（loginIps/loginTimes/loginLocations/combineType 组合方式）"],
        ),
        _action(
            f"qt_detect_abnormallogin_rule_detail_{_os}",
            f"正常登录规则详情查询-{_os_label}",
            "GET",
            f"/external/api/detect/abnormallogin/{_os}/rule/{{id}}",
            f"查询单条 {_os_label} 正常登录规则详情",
            [_p("id", "string", True, "规则 ID（路径参数，规则列表接口返回的 id）")],
            ["id: 规则 ID", "osType: 系统类型 1-linux 2-windows", "realmKind: 主机范围 0-全部主机 1-主机 2-业务组", "realmGroup/realmAgentId/realmAgentGroup: 业务组/主机/主机所在业务组", "condition: 规则详情（loginIps/loginTimes/loginLocations/combineType 组合方式）"],
        ),
    ])

# ---- Web 后门（webshell，linux/win 同构）----
for _os, _os_label in (("linux", "Linux"), ("win", "Windows")):
    DETECT_ACTIONS.extend([
        _list_action(
            f"qt_detect_webshell_list_{_os}",
            f"Web后门查询-{_os_label}",
            f"/external/api/websecurity/webshell/{_os}",
            f"查询 {_os_label} 主机 Web 后门（webshell）扫描结果",
            [
                _p("types", "string", False, "类型，多个用逗号分隔"),
                _p("serverName", "string", False, "域名"),
                _p("filePath", "string", False, "文件路径"),
            ],
            _DETECT_ROW_RESP + ["id: 记录 ID", "type/typeDesc: 类型/描述（如已知后门）", "serverName/filePath/fileMd5/fileSize: 域名/文件路径/MD5/大小", "regexDesc: 特征码说明", "matchCount: 命中规则数", "modifyTime: 最后修改时间(时间戳)", "whiteRuleEffect: 是否命中白名单"],
        ),
        _action(
            f"qt_detect_webshell_check_status_{_os}",
            f"Web后门扫描状态查询-{_os_label}",
            "GET",
            f"/external/api/websecurity/webshell/{_os}/check/status",
            f"查询 {_os_label} Web 后门扫描任务的执行状态，无请求参数",
            [],
            ["retcode: 扫描状态 -1-无任务 0-未开始 1-排队 2-正在执行 3-执行成功 4-执行失败"],
        ),
    ])

# ---- 反弹 shell（bounceshell，linux/win 同构）----
for _os, _os_label in (("linux", "Linux"), ("win", "Windows")):
    DETECT_ACTIONS.append(
        _list_action(
            f"qt_detect_bounceshell_list_{_os}",
            f"反弹Shell查询-{_os_label}",
            f"/external/api/detect/bounceshell/{_os}",
            f"查询 {_os_label} 主机反弹 Shell 上报事件（含进程树）",
            [
                _p("createTime", "string", False, "发现时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
                _p("processName", "string", False, "连接进程"),
                _p("targetIpLike", "string", False, "目标主机（模糊查询）"),
                _p("targetPort", "integer", False, "目标端口"),
            ],
            _DETECT_ROW_RESP + ["createTime: 发现时间(时间戳)", "pid/processName: 连接进程ID/名", "targetIp/targetPort: 目标主机/端口", "userName/currentPath: 进程启动用户/路径", "parentPid/parentName/parentPath: 父进程ID/名/路径", "stdInfo: 标准I/O信息", "processTree: 进程树（父至子）", "whiteRuleEffect: 是否匹配白名单"],
        ),
    )

# ---- 本地提权（localrights，仅 Linux）----
DETECT_ACTIONS.append(
    _list_action(
        "qt_detect_localrights_list_linux",
        "本地提权查询-Linux",
        "/external/api/detect/localrights/linux",
        "查询 Linux 主机本地提权上报事件（含进程树）",
        [
            _p("time", "string", False, "发现时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
            _p("procName", "string", False, "提权进程"),
            _p("procUserName", "string", False, "提权用户"),
        ],
        _DETECT_ROW_RESP + ["time: 发现时间(时间戳)", "procPid/procName/procPath: 提权进程ID/名/路径", "procUserName/procGroupName/procFileMode: 提权用户/组/文件权限", "parentProcPid/parentProcName/parentProcPath: 父进程ID/名/路径", "processTreeList: 进程树（父至子）", "whiteRuleEffect: 是否匹配白名单"],
    ),
)

# ---- 后门检测（backdoor，linux/win 参数不同）----
DETECT_ACTIONS.append(
    _list_action(
        "qt_detect_backdoor_list_linux",
        "后门检测查询-Linux",
        "/external/api/detect/backdoor/linux",
        "查询 Linux 主机后门检测扫描结果（应用后门/Bootkit/Rootkit）",
        [
            _p("backDoorTypes", "string", False, "后门类型，多个用逗号分隔（应用后门、Bootkit、Rootkit）"),
            _p("backDoorCheckNames", "string", False, "检查功能，多个用逗号分隔（如 RPM-based应用后门检查、磁盘MBR检查、已知rootkit检查等）"),
            _p("backDoorName", "string", False, "检查项"),
        ],
        _DETECT_ROW_RESP + ["createTime: 发现时间(时间戳)", "backDoorType: 后门类型（应用后门/Bootkit/Rootkit）", "backDoorName: 检查项", "backDoorCheckName: 检查功能", "description: 检查说明", "detail: 检查结果详情", "instruct: 修复方法", "whiteRuleEffect: 是否匹配白名单"],
    ),
)
DETECT_ACTIONS.append(
    _list_action(
        "qt_detect_backdoor_list_win",
        "后门检测查询-Windows",
        "/external/api/detect/backdoor/win",
        "查询 Windows 主机后门检测扫描结果（可疑进程/线程/模块/启动项等）",
        [
            _p("backDoorTypeIds", "string", False, "后门类型，多个用逗号分隔：0-未知 1-可疑进程 2-可疑线程 3-可疑模块 4-可疑启动项 5-映像劫持 1000-恶意进程"),
            _p("name", "string", False, "问题摘要"),
        ],
        _DETECT_ROW_RESP + ["createTime: 发现时间(时间戳)", "name: 问题摘要", "backDoorTypeId: 后门类型", "reason: 异常原因", "data: 详情（进程/线程信息）", "whiteRuleEffect: 是否匹配白名单"],
    ),
)
for _os, _os_label in (("linux", "Linux"), ("win", "Windows")):
    DETECT_ACTIONS.append(
        _action(
            f"qt_detect_backdoor_check_status_{_os}",
            f"后门检测扫描状态查询-{_os_label}",
            "GET",
            f"/external/api/detect/backdoor/{_os}/check/status",
            f"查询 {_os_label} 后门检测当前正在执行的扫描任务状态，无请求参数",
            [],
            ["retcode: 扫描状态 2-正在执行 3-执行成功 4-执行失败", "status: 状态字符串 running/success/failed"],
        ),
    )

# ---- 网络蜜罐（honeypot，linux/win 同构）----
for _os, _os_label in (("linux", "Linux"), ("win", "Windows")):
    DETECT_ACTIONS.extend([
        _list_action(
            f"qt_detect_honeypot_list_{_os}",
            f"网络蜜罐查询-{_os_label}",
            f"/external/api/detect/honeypot/{_os}",
            f"查询 {_os_label} 主机网络蜜罐上报事件（源 IP 访问蜜罐端口）",
            [
                _p("time", "string", False, "发现时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
                _p("clientIp", "string", False, "源 IP"),
                _p("port", "integer", False, "主机端口"),
            ],
            _DETECT_ROW_RESP + ["time: 发现时间(时间戳)", "clientIp: 源 IP", "port: 主机端口", "whiteRuleEffect: 是否匹配白名单"],
        ),
        _list_action(
            f"qt_detect_honeypot_rule_list_{_os}",
            f"蜜罐规则列表查询-{_os_label}",
            f"/external/api/detect/honeypot/{_os}/rule",
            f"查询 {_os_label} 网络蜜罐主机规则列表（含端口同步状态）",
            [],
            _HOST_RESP + ["status: 规则状态 0-启用 1-禁用", "verifyStatus: 同步状态 0-规则同步中 1-同步完毕", "ports: 规则端口列表（port/status 端口状态）"],
        ),
        _action(
            f"qt_detect_honeypot_rule_detail_{_os}",
            f"蜜罐规则详情查询-{_os_label}",
            "GET",
            f"/external/api/detect/honeypot/{_os}/rule/{{id}}",
            f"查询单条 {_os_label} 网络蜜罐主机规则详情",
            [_p("id", "string", True, "主机 ID（路径参数，16 位 agentId）")],
            _HOST_RESP + ["status: 规则状态 0-启用 1-禁用", "verifyStatus: 同步状态 0-同步中 1-同步完毕", "ports: 规则端口列表（port/status 端口状态）"],
        ),
    ])


# ============ 四、合规基线（baseline）============

BASELINE_ACTIONS: list[dict[str, Any]] = []

for _os, _os_label in (("linux", "Linux"), ("win", "Windows")):
    BASELINE_ACTIONS.extend([
        _action(
            f"qt_baseline_job_list_{_os}",
            f"基线任务列表查询-{_os_label}",
            "GET",
            f"/external/api/baseline/job/{_os}",
            f"查询 {_os_label} 基线检查任务列表（含进度/通过率/主机数统计；接口暂不支持分页）",
            [
                _p("osType", "integer", True, "操作系统：1-linux 2-windows（必填）"),
                _p("specName", "string", False, "任务名"),
                _p("ruleIds", "string", False, "规则 id 列表，多个用逗号分隔"),
                _p("ip", "string", False, "主机 IP"),
                _p("hostName", "string", False, "主机名称"),
            ],
            ["specId/jobId: 任务规格ID/最后一次任务ID", "specName: 任务规格名", "descroption: 任务描述", "ruleId/ruleName: 基线规则ID/名", "checkTime: 检查时间", "duration: 持续时间", "hostCount/failedHostCount/successHostCount: 主机/失败/成功主机数", "progress: 进度", "passRate: 通过率", "status: 状态 0-Pending 1-Running 2-Done"],
        ),
        _action(
            f"qt_baseline_job_status_{_os}",
            f"基线任务执行状态查询-{_os_label}",
            "GET",
            f"/external/api/baseline/job/{_os}/getStatus/{{specId}}",
            f"查询 {_os_label} 基线检查任务的执行状态",
            [_p("specId", "string", True, "任务规格 ID（路径参数，任务列表返回的 specId）")],
            ["id: 任务 ID（jobId）", "status: 执行结果"],
        ),
        _action(
            f"qt_baseline_spec_rule_{_os}",
            f"基线规则查询-{_os_label}",
            "GET",
            f"/external/api/baseline/spec/rule/{_os}",
            f"查询 {_os_label} 基线规则及检查项明细（数据量较大，注意接口性能）",
            [
                _p("osType", "integer", True, "操作系统：1-linux 2-windows（必填）"),
                _p("family", "integer", True, "基线类别：1-系统基线 2-应用基线（必填）"),
                _p("platform", "string", False, "使用系统（系统基线时过滤，如 centos-7）"),
                _p("appId", "string", False, "应用 ID（应用基线时过滤）"),
            ],
            ["id: 规则 ID", "name: 规则名（如 CIS Centos 7 Level 2）", "userRule: 是否用户规则", "osTag: 适用平台", "family: 基线类别 1-系统 2-应用", "appRule: 是否应用基线", "needAuthCount: 应用基线需授权检查项数", "checkTotal: 检查项条数", "rows: 检查项明细（id/name/category/description/content/reference/needAuth）"],
        ),
        _action(
            f"qt_baseline_checkresult_{_os}",
            f"基线检查结果查询-{_os_label}",
            "GET",
            f"/external/api/baseline/spec/checkResult/{_os}",
            f"查询 {_os_label} 基线检查任务的检查结果明细",
            [
                _p("jobId", "string", True, "本次任务 ID（必填，任务状态接口返回的 id）"),
                _p("checkId", "string", False, "检查项的 checkId"),
                _p("group", "integer", False, "业务组"),
                _p("flag", "integer", False, "检查状态：0-未通过 1-通过 -1-失败"),
                _p("ip", "string", False, "主机 IP"),
                _p("hostname", "string", False, "主机名"),
            ],
            ["specId/ruleId: 任务ID/规则ID", "id: 检查结果 ID", "internalIp/hostname/groupName: 内网IP/主机名/业务组", "flag: 检查结果 -1失败/0未通过/1通过", "category/content/description/reference: 检查类型/内容/描述/引用", "results: 应用基线多实例明细（version/pid/port/result/kb_name/bin_path/conf_path/msg）", "level: 风险级别", "remedDes: 修复建议"],
        ),
        _action(
            f"qt_baseline_failedhost_{_os}",
            f"基线检查失败主机查询-{_os_label}",
            "GET",
            f"/external/api/baseline/spec/failedHost/{_os}",
            f"查询 {_os_label} 基线检查任务执行失败的主机列表及失败原因",
            [
                _p("jobId", "string", True, "任务 ID（必填）"),
                _p("ip", "string", False, "主机 IP"),
                _p("hostname", "string", False, "主机名"),
                _p("code", "string", False, "失败原因码，多个用逗号分隔"),
            ],
            ["agentId: agentID", "displayIp/internalIp/externalIp: 主机/内网/外网 IP", "hostname: 主机名", "group: 业务组", "code: 失败码", "description: 失败描述"],
        ),
        _action(
            f"qt_baseline_auth_login_{_os}",
            f"应用基线登录请求-{_os_label}",
            "GET",
            f"/external/api/baseline/auth/login/{_os}",
            f"{_os_label} 应用基线（MySQL/WebLogic）授权前的密码验证登录请求，返回授权 authToken（30 分钟失效）",
            [
                _p("comId", "string", True, "公司 ID（必填，青藤登录接口返回的 comId）"),
                _p("uuid", "string", True, "用户 ID（必填，青藤登录接口返回的 jwt 载荷中的 uuid）"),
                _p("password", "string", True, "密码（必填）"),
            ],
            ["flag: 验证状态", "authToken: 登录产生的 token，30 分钟失效"],
        ),
        _action(
            f"qt_baseline_auth_list_{_os}",
            f"应用基线授权列表查询-{_os_label}",
            "GET",
            f"/external/api/baseline/auth/list/{_os}",
            f"查询 {_os_label} 应用基线（MySQL/WebLogic）的授权列表",
            [
                _p("authToken", "string", True, "授权 token（必填，登录请求接口返回）"),
                _p("osType", "integer", False, "操作系统：1-linux 2-windows"),
                _p("appName", "string", False, "应用名：MySQL/WebLogic"),
            ],
            ["id: 授权记录 ID", "realmKind: 范围类型 0-全部主机 1-主机维度 2-业务组", "group/groupName: 业务组", "agentId: 主机 ID", "appName/userName/port: 应用名/用户名/端口", "displayIp/internalIp/externalIp: 主机各 IP", "hostname: 主机名", "remark: 备注"],
        ),
    ])


# ============ 五、系统审计（system）============

SYSTEM_ACTIONS: list[dict[str, Any]] = [
    _list_action(
        "qt_system_audit_list",
        "系统审计日志查询",
        "/external/api/system/audit",
        "查询青藤系统自身的审计日志（操作事件/来源/请求参数/响应码）",
        [
            _p("eventName", "string", False, "操作名称（模糊查询）"),
            _p("userName", "string", False, "操作的账号名（模糊查询）"),
        ],
        ["eventId: 事件 ID", "eventType: 事件类型（新建/修改/删除/查看/认证/文件/执行）", "eventName: 操作名称", "eventSource: 事件来源（Console/外部api/系统内部）", "osType: 操作系统 1-linux 2-windows 0-通用", "resourceFunction/resourceSubFunction: 所属主/子功能", "requestIp/location: 请求IP/来源区域", "requestId/requestParam: 请求ID/请求参数(JSON串)", "userName/userType: 操作账号名/类型 1-主账号 2-子账号", "responseCode/errorInfo: 响应码/错误描述", "eventTime: 发生时间(秒级时间戳)"],
    ),
]


# ============ 六、快速任务（fastjob）============

FASTJOB_ACTIONS: list[dict[str, Any]] = [
    _list_action(
        "qt_fastjob_task_list",
        "快速任务检测项列表查询",
        "/external/api/fastjob/task/list",
        "查询快速任务（安全检测/应急响应脚本）检测项列表",
        [
            _p("osType", "integer", True, "操作系统：1-linux 2-windows（必填）"),
            _p("ids", "string", False, "任务 id，多个用逗号分隔"),
            _p("name", "string", False, "任务名"),
            _p("categories", "string", False, "类别，多个用逗号分隔（如 安全检测、应急响应）"),
            _p("updatedTimeRange", "string", False, "更新时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
        ],
        ["id: 快速任务 ID", "name: 快速任务名称", "category: 快速任务类型", "description: 任务概述", "riskInfo: 风险提示", "updatedTime: 更新时间"],
    ),
    _action(
        "qt_fastjob_task_detail",
        "快速任务详情查询",
        "GET",
        "/external/api/fastjob/task/{taskId}",
        "查询单个快速任务的详细信息（含输入/输出参数定义）",
        [_p("taskId", "string", True, "任务 ID（路径参数，检测项列表返回的 id）")],
        ["id: 快速任务 ID", "name/category/description/riskInfo: 名称/类型/概述/风险提示", "createdTime/updatedTime: 创建/更新时间", "inputSchemas: 输入参数定义（field/caption/required/defaultValue/name/example）", "outputSchemas: 输出参数定义（field/displayName/displayOrder/caption/example）"],
    ),
    _list_action(
        "qt_fastjob_job_list",
        "快速作业列表查询",
        "/external/api/fastjob/job",
        "查询快速作业（快速任务下发的作业）列表",
        [
            _p("osType", "integer", True, "操作系统：1-linux 2-windows（必填）"),
            _p("jobName", "string", False, "作业名"),
            _p("updateTimeRange", "string", False, "更新时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
            _p("cronEnables", "string", False, "是否开启定时，多个用逗号分隔（true/false）"),
        ],
        ["id: 作业 ID", "name: 快速作业名", "description: 作业描述", "cronEnable/cron: 是否定时/定时表达式", "realm/realmName: 作业范围/范围描述", "updatedTime/createdTime: 更新/创建时间", "lastExecuteTime: 上次执行时间", "lastExecuteTaskRecordId: 最近执行记录 ID", "task: 关联任务详情（taskType/taskId/params）"],
    ),
    _list_action(
        "qt_fastjob_job_execute_list",
        "快速作业执行记录查询",
        "/external/api/fastjob/job/execute",
        "查询快速作业的执行记录列表（状态/耗时/执行范围）",
        [
            _p("osType", "integer", True, "操作系统：1-linux 2-windows（必填）"),
            _p("jobName", "string", False, "作业名"),
            _p("startDateRange", "string", False, "作业执行起始时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
            _p("durations", "string", False, "执行时间范围，多个用逗号分隔：0/1/2/3/4/5（1分钟内/1~3分钟/3~5分钟/5~10分钟/10~30分钟/超出30分钟）"),
            _p("statuses", "string", False, "扫描状态，多个用逗号分隔：1-准备执行 2-正在执行 3-执行成功 4-执行失败"),
        ],
        ["id: 作业执行记录 ID", "jobId/name: 作业ID/名", "taskRecordId: 任务执行记录 ID", "realm: 作业执行范围", "cronEnable/cron: 是否定时/表达式", "startTime: 开始时间", "duration: 耗时(秒)", "status: 状态 1-准备 2-执行中 3-成功 4-失败"],
    ),
    _action(
        "qt_fastjob_task_result",
        "快速作业执行结果查询",
        "GET",
        "/external/api/fastjob/job/task/result/{taskRecordId}",
        "查询快速作业某次执行的结果明细（字段由 fields 动态定义）",
        [
            _p("taskRecordId", "string", True, "任务执行记录 ID（路径参数，执行记录返回的 taskRecordId）"),
            _p("searchKeys", "string", False, "搜索字段名数组，与 searchValues 顺序对应，多个用逗号分隔"),
            _p("searchValues", "string", False, "搜索值数组，与 searchKeys 顺序对应，多个用逗号分隔"),
        ],
        ["fields: 结果字段定义（field/displayName）", "rows: 结果行（字段名从 fields 获取，含 host.* 主机信息与 data.* 检测数据）", "total: 总数"],
    ),
    _action(
        "qt_fastjob_task_error",
        "快速作业失败主机查询",
        "GET",
        "/external/api/fastjob/job/task/error/{taskRecordId}",
        "查询快速作业某次执行失败的主机列表及错误原因",
        [_p("taskRecordId", "string", True, "任务执行记录 ID（路径参数，执行记录返回的 taskRecordId）")],
        ["id: 记录 ID", "agentId: 主机 ID", "displayIp/internalIp/externalIp: 主机各 IP", "hostName: 主机名", "group/groupName: 业务组", "remark/hostTags: 备注/标签", "code: 错误码", "error: 错误信息（如主机不在线）"],
    ),
]


# ============ 七、主机发现（discoveredhost / assetdiscovery）============

DISCOVERY_ACTIONS: list[dict[str, Any]] = [
    _action(
        "qt_discovery_host_list",
        "主机发现结果查询",
        "GET",
        "/external/api/discoveredhost/list",
        "查询主机发现功能发现的所有主机（含发现方式与首次/最近发现时间），无请求参数",
        [],
        ["id: 被发现主机 ID", "macAddr/ipAddr: MAC/IP 地址", "deviceType: 设备类型", "osFamily: 操作系统类型", "agentId/discoveryIp: 执行发现任务的主机 agentId/IP", "agentStatus: 执行主机 agent 状态 0-在线 1-离线 2-挂起 3-删除", "scanMethods: 发现该主机的扫描方法", "firstDiscoverTime/lastDiscoverTime: 首次/最近发现时间(时间戳)", "osType: 执行主机操作系统 1-linux 2-windows"],
    ),
    _action(
        "qt_discovery_job_find",
        "主机发现任务详情查询",
        "POST",
        "/external/api/assetdiscovery/job/find",
        "查询主机发现扫描任务的配置详情（查询语义 POST，参数走 JSON body）",
        [_p("specId", "string", True, "任务 ID（必填，任务列表返回的 specId）")],
        ["id: 任务 ID", "name: 任务名", "kind: 任务发起主机类型 0-自定义主机 1-自定义业务组 2-全部主机", "values: 发起主机/业务组值", "osType: 操作系统", "cronExpression: 定时表达式", "osDetection: 是否获取操作系统", "ipList: 扫描网段", "advanceConfigs: 扫描方式（scanType 0-ARP缓存 1-Ping 2-Nmap，含 tcpPort/udpPort）", "maxParallelism/maxRate/taskInterval: 并发数/发包速率/下发间隔"],
    ),
    _action(
        "qt_discovery_job_list",
        "主机发现任务列表查询",
        "POST",
        "/external/api/assetdiscovery/job/list",
        "查询主机发现扫描任务列表（查询语义 POST，参数走 JSON body，全部条件选填）",
        [
            _p("name", "string", False, "任务名称（模糊查询）"),
            _p("scanType", "string", False, "扫描方式，多个用逗号分隔：0-ARP缓存 1-Ping 2-Nmap"),
        ],
        ["specId/jobId: 任务ID/执行jobId", "name: 任务名", "progress: 进度", "kind: 发起主机类型", "scanType: 扫描方式列表", "status: 任务状态 0-待执行 1-执行中 2-执行完成", "lastScanTime: 上一次执行时间(毫秒时间戳)"],
    ),
]


# ============ 八、微隔离（ms-srv）============

# 微隔离统一响应包装说明（ms-srv 接口返回多为 {success, errorCode, errorDesc, data} 结构）
_MS_RESP = ["success: 是否成功", "errorCode: 状态码 0-成功", "errorDesc: 异常描述"]

MS_ACTIONS: list[dict[str, Any]] = [
    _list_action(
        "qt_ms_segmentation_list",
        "一键隔离列表查询",
        "/external/api/ms-srv/api/segmentation/list",
        "查询微隔离一键隔离任务列表（隔离状态/放行 IP 端口）",
        [
            _p("ip", "string", False, "主机 IP"),
            _p("direction", "string", False, "隔离方向，多个用逗号分隔：in-入站 out-出站 all-全部"),
            _p("status", "string", False, "隔离状态，多个用逗号分隔：1-隔离中 2-隔离成功 3-隔离失败 4-修改中 5-修改失败 6-解除中 7-解除失败"),
        ],
        ["id: 记录 ID", "agentId: 主机 ID", "updatedTime: 修改时间(时间戳)", "remark: 备注", "remoteLoginEnabled: 远程登录 0-关 1-开", "displayIp/hostname/groupName: 主机IP/名/业务组", "onlineStatus: 在线状态 0-离线 1-在线", "ipList/portList: 放行 IP/端口", "status: 任务状态 1~7（隔离中/成功/失败/修改中/修改失败/解除中/解除失败）", "operation: 操作类型（新增/修改/删除）", "error: 错误描述", "direction: 隔离方向"],
    ),
    _list_action(
        "qt_ms_segmentation_detail",
        "一键隔离详情查询",
        "/external/api/ms-srv/api/segmentation/detail",
        "查询某主机的微隔离一键隔离详情（放行 IP/端口/协议）",
        [_p("agentId", "string", True, "主机 ID（必填）")],
        _MS_RESP + ["id: 记录 ID", "agentId: 主机 ID", "comId: 公司 ID", "ipList/portList: 放行 IP/端口", "protocol: 协议（* 表示 tcp/udp 都支持）", "updatedTime: 修改时间(时间戳)", "remark: 备注", "operation: 操作类型", "status: 任务状态 1~7", "error: 错误描述", "direction: 隔离方向"],
    ),
    _list_action(
        "qt_ms_hosts_list",
        "微隔离主机列表查询",
        "/external/api/ms-srv/api/hosts/list",
        "查询微隔离模块的主机列表（微隔离开关/运行状态/访问控制模式等）",
        [
            _p("ip", "string", False, "主机 IP"),
            _p("hostname", "string", False, "主机名"),
            _p("tags", "string", False, "主机标签 id，多个用逗号分隔"),
            _p("msEnabled", "string", False, "微隔离插件开关：null-全部 0-关闭 1-开启，多个用逗号分隔"),
            _p("accessControlMode", "string", False, "访问控制模式：null-全部 0-服务控制 1-主机控制，多个用逗号分隔"),
            _p("agentId", "string", False, "主机 ID"),
            _p("agentIds", "string", False, "主机 ID 数组，多个用逗号分隔"),
            _p("onlineStatus", "string", False, "在线状态：0-离线 1-在线，多个用逗号分隔"),
            _p("available", "string", False, "是否可用：no-不可用"),
            _p("runStatus", "string", False, "运行状态：warn-告警 monitor-监控 protect-防护，多个用逗号分隔"),
            _p("limitOut", "integer", False, "出站限制：0-不允许出站 1-允许出站"),
            _p("platform", "string", False, "操作系统"),
            _p("runLevel", "string", False, "运行级别：0-正常 1-降级 2-停用，多个用逗号分隔"),
            _p("agentTypes", "string", False, "agent 类型：0-纯主机 1-超融合 2-K8s 3-docker，多个用逗号分隔"),
            _p("clusterIds", "string", False, "集群 ID，多个用逗号分隔"),
        ],
        ["agentId: 主机 ID", "onlineStatus: 在线状态 0-离线 1-在线", "displayIp/ips: 主机 IP/所有 IP", "hostname/group/groupName: 主机名/业务组ID/名称", "tags: 主机标签", "msEnabled: 微隔离开关 0-关 1-开", "dcSyncNum/dcNotSyncNum: 策略已/未同步数量", "accessControlMode: 访问控制模式 0-服务控制 1-主机控制", "platform: 操作系统", "runStatus: 运行状态 warn/monitor/protect", "limitOut: 出站限制", "available/availableReason: 是否可用/不可用原因", "osType: 操作系统类型 1-linux 2-windows", "runLevel: 运行级别 0-正常 1-降级 2-停用 3-自动降级", "blackStrategyEnable: 黑名单策略开关状态"],
    ),
    _list_action(
        "qt_ms_black_strategy_list",
        "黑名单策略列表查询",
        "/external/api/ms-srv/api/black-strategy/list",
        "查询微隔离黑名单策略列表（访问者/被访问者范围、端口协议）",
        [
            _p("id", "string", False, "策略 ID"),
            _p("ids", "string", False, "策略 ID 集合，多个用逗号分隔"),
            _p("strategyName", "string", False, "策略名称"),
            _p("dstGroupIds", "string", False, "被访问业务组，多个用逗号分隔"),
            _p("dstTagIds", "string", False, "被访问主机标签，多个用逗号分隔"),
            _p("dstIp", "string", False, "被访问者 IP"),
            _p("srcGroupIds", "string", False, "访问业务组，多个用逗号分隔"),
            _p("srcTagIds", "string", False, "访问主机标签，多个用逗号分隔"),
            _p("srcIp", "string", False, "访问者 IP"),
            _p("protos", "string", False, "协议，多个用逗号分隔"),
            _p("port", "string", False, "端口"),
            _p("switchStatuses", "string", False, "开关状态：0-关闭 1-打开，多个用逗号分隔"),
            _p("username", "string", False, "操作人"),
            _p("updateTime", "string", False, "修改时间范围，格式 yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss"),
        ],
        _MS_RESP + ["id: 策略 ID", "strategyName: 策略名称", "dstRealmType: 被访问者范围 1-业务组标签 2-自定义主机 3-自定义ip", "dstGroups/dstTags/dstIpRanges/dstAgentIds: 被访问业务组/标签/IP范围/主机", "srcRealmType/srcGroups/srcTags/srcIpRanges/srcAgentIds: 访问者各范围字段", "dstAgentSize/srcAgentSize: 被访问/访问主机数量", "ports/protos: 端口/协议", "status: 策略状态 0-新建 1-待同步 2-已同步 3-删除", "updateTime: 修改时间(毫秒时间戳)", "optUsername: 操作用户", "switchStatus: 开关状态 0-关 1-开", "operation: 是否有操作权限"],
    ),
    _list_action(
        "qt_ms_black_strategy_host_list",
        "黑名单策略主机列表查询",
        "/external/api/ms-srv/api/black-strategy/strategy-host-list",
        "查询某黑名单策略的访问者/被访问者主机列表",
        [
            _p("strategyId", "string", True, "策略 ID（必填）"),
            _p("strategyHostType", "string", True, "查询数据类型（必填）：0-被访问者类型 1-访问者类型"),
            _p("ip", "string", False, "主机 IP"),
            _p("msSwitchStatus", "string", False, "微隔离插件状态：0-关闭"),
        ],
        _MS_RESP + ["ip/matchIp: 主机IP/匹配IP", "hostname/groupName: 主机名/业务组", "tags: 主机标签", "agentId: 主机 ID", "onlineStatus: 在线状态 0-离线 1-在线", "msSwitchStatus: 微隔离开关 0-关 1-开", "available: 是否可用 yes/no", "status: 策略状态 0-新建 1-待同步 2-已同步 3-删除", "osType: 操作系统类型 1-linux 2-windows"],
    ),
    _list_action(
        "qt_ms_black_strategy_detail",
        "黑名单策略详情查询",
        "/external/api/ms-srv/api/black-strategy/detail",
        "查询单条微隔离黑名单策略详情",
        [_p("id", "string", True, "策略 ID（必填）")],
        ["id: 策略 ID", "strategyName: 策略名称", "dstRealmType/srcRealmType: 被访问者/访问者范围类型", "dstGroups/dstTags/dstIpRanges/dstAgentIds: 被访问业务组/标签/IP范围/主机", "srcGroups/srcTags/srcIpRanges/srcAgentIds: 访问者各范围字段", "dstAgentSize/srcAgentSize: 被访问/访问主机数量", "ports/protos: 端口/协议", "status: 策略状态 0-新建 1-待同步 2-已同步 3-删除", "updateTime: 修改时间(毫秒时间戳)", "optUsername: 操作用户", "switchStatus: 开关状态 0-关 1-开", "operation: 是否有操作权限"],
    ),
    _list_action(
        "qt_ms_strategy_set_list",
        "策略集列表查询",
        "/external/api/ms-srv/api/strategy-set/list",
        "查询微隔离白名单策略集列表（下发状态/策略计数）",
        [
            _p("strategySetName", "string", False, "策略集名称"),
            _p("statusList", "string", False, "策略集状态，多个用逗号分隔：-1-待同步 0-已同步"),
            _p("existsFailHost", "boolean", False, "是否存在失败的主机：true-存在 false-不存在"),
            _p("groups", "string", False, "适用业务组范围，0 表示全部业务组，多个用逗号分隔"),
            _p("switchStatus", "integer", False, "开关状态：0-关闭 1-打开"),
        ],
        _MS_RESP + ["id: 策略集 ID", "strategySetName: 策略集名称", "issueStatus: 下发状态 -1-未同步 0-已同步", "issueDateTime: 下发日期", "strategyCount/unIssueStrategyCount: 策略总数/未下发数", "realmName/groupInfos: 适用范围/业务组信息", "operation/createStrategyPermission: 操作/创建权限", "updateUsername: 更新操作人", "updateTime/createTime: 更新/创建时间", "switchStatus: 开关状态 0-关 1-开", "enableCount/disableCount: 启用/禁用策略数"],
    ),
    _list_action(
        "qt_ms_strategy_set_detail",
        "策略集详情查询",
        "/external/api/ms-srv/api/strategy-set/detail",
        "查询单个微隔离策略集详情",
        [_p("id", "string", True, "策略集 ID（必填）")],
        _MS_RESP + ["id: 策略集 ID", "strategySetName: 策略集名称", "issueStatus: 下发状态 -1-未同步 0-已同步", "issueSuccessAgentCount/issueFailAgentCount: 下发成功/失败主机数", "issueDateTime: 下发日期", "strategyCount/unIssueStrategyCount: 策略总数/未下发数", "realmName/groupInfos: 适用范围/业务组信息", "operation/createStrategyPermission: 操作/创建权限", "switchStatus: 开关状态 0-关 1-开", "enableCount/disableCount: 启用/禁用策略数"],
    ),
    _list_action(
        "qt_ms_strategy_list",
        "白名单策略列表查询",
        "/external/api/ms-srv/api/strategy/list",
        "查询微隔离白名单策略列表（访问者/被访问者范围、端口协议、容器维度）",
        [
            _p("strategySetId", "string", False, "策略集 ID"),
            _p("id", "string", False, "策略 ID"),
            _p("strategyName", "string", False, "策略名称"),
            _p("dstGroupIds", "string", False, "被访问业务组，多个用逗号分隔"),
            _p("dstTagIds", "string", False, "被访问主机标签，多个用逗号分隔"),
            _p("dstIp", "string", False, "被访问者 IP"),
            _p("srcGroupIds", "string", False, "访问业务组，多个用逗号分隔"),
            _p("srcTagIds", "string", False, "访问主机标签，多个用逗号分隔"),
            _p("srcIp", "string", False, "访问者 IP"),
            _p("protos", "string", False, "协议，多个用逗号分隔（TCP/UDP）"),
            _p("status", "string", False, "策略状态，多个用逗号分隔：0-新增 1-待同步 2-已同步 3-删除"),
            _p("displayPort", "string", False, "端口搜索字段"),
            _p("switchStatus", "integer", False, "开关状态：0-关闭 1-打开"),
            _p("ipGroupIds", "string", False, "访问者/被访问者 IP 组 id，多个用逗号分隔"),
            _p("dstRealmTypes", "string", False, "被访问者类型，多个用逗号分隔：1-业务组标签 2-主机 3-自定义ip 4-ip组 5-容器"),
            _p("srcRealmTypes", "string", False, "访问者类型，多个用逗号分隔：1-业务组标签 2-主机 3-自定义ip 4-ip组 5-容器"),
        ],
        _MS_RESP + ["id: 策略 ID", "strategyName: 策略名称", "strategySetId/strategySetName: 所属策略集 ID/名称", "dstRealmType/srcRealmType: 被访问者/访问者范围类型（1-业务组标签 2-主机 3-自定义ip 4-IP组 5-容器）", "dstGroups/dstTags/dstIpRanges/dstHosts/dstIpGroups: 被访问者各范围字段", "srcGroups/srcTags/srcIpRanges/srcHosts/srcIpGroups: 访问者各范围字段", "dstAgentSize/srcAgentSize: 被访问/访问主机数量", "ports/protos: 端口/协议", "status: 策略状态 0-新增 1-待同步 2-已同步 3-删除", "updateTime/createTime: 更新/创建时间(毫秒时间戳)", "optUsername: 操作用户", "switchStatus: 开关状态 0-关 1-开", "sceneType: 场景类型", "operation: 是否有操作权限"],
    ),
    _list_action(
        "qt_ms_strategy_detail",
        "白名单策略详情查询",
        "/external/api/ms-srv/api/strategy/detail",
        "查询单条微隔离白名单策略详情",
        [_p("id", "string", True, "策略 ID（必填）")],
        _MS_RESP + ["id: 策略 ID", "strategyName: 策略名称", "strategySetId/strategySetName: 所属策略集 ID/名称", "dstRealmType/srcRealmType: 被访问者/访问者范围类型", "dstGroups/dstTags/dstIpRanges/dstHosts/dstIpGroups: 被访问者各范围字段", "srcGroups/srcTags/srcIpRanges/srcHosts/srcIpGroups: 访问者各范围字段", "ports/protos: 端口/协议", "status: 策略状态", "updateTime: 更新时间(毫秒时间戳)", "optUsername: 操作用户", "switchStatus: 开关状态"],
    ),
]


# ============ 汇总导出 ============

# 青藤万相全部查询类动作（seed 脚本以此列表为准写入 DeviceAction）
QINGTENG_WANXIANG_ACTIONS: list[dict[str, Any]] = (
    ASSET_ACTIONS
    + VUL_ACTIONS
    + DETECT_ACTIONS
    + BASELINE_ACTIONS
    + SYSTEM_ACTIONS
    + FASTJOB_ACTIONS
    + DISCOVERY_ACTIONS
    + MS_ACTIONS
)
