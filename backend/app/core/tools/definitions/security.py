from typing import Any

from app.core.tools.types import TOOL_SOURCE_SECURITY


def _sec_tool(
    name: str,
    description: str,
    params: list[dict[str, Any]],
    category: str,
    tags: list[str],
) -> dict[str, Any]:
    """构造安全工具种子定义：run 直接透传注入的封装函数。"""
    return {
        "name": name,
        "description": description,
        "parameters_schema": params,
        "code": (
            "async def run(**kwargs):\n"
            f"    return await {name}(**kwargs)\n"
        ),
        "tool_type": "code",
        "category": category,
        "tags": tags,
        "enabled": True,
        "is_preset": True,
        "tool_source": TOOL_SOURCE_SECURITY,
    }


SECURITY_TOOLS: list[dict[str, Any]] = [
    # ---------- 第一批（核心必装）：渗透侦察 + 漏洞扫描 ----------
    _sec_tool(
        "nmap_scan",
        "Nmap 端口与服务扫描：探测开放端口、服务版本、操作系统。默认 -Pn -sV --top-ports 1000。",
        [
            {"name": "target", "type": "String", "required": True, "description": "目标 IP / CIDR / 域名，多个用空格分隔"},
            {"name": "options", "type": "String", "required": False, "description": "nmap 参数，默认 -Pn -sV --top-ports 1000"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 600"},
        ],
        "pentest_recon",
        ["Nmap", "端口扫描", "第一批"],
    ),
    _sec_tool(
        "nuclei_scan",
        "Nuclei 漏洞 PoC 扫描：基于 8000+ 模板库（CVE/指纹/弱口令/配置缺陷），输出结构化发现。",
        [
            {"name": "target", "type": "String", "required": True, "description": "目标 URL / IP，多个用逗号分隔"},
            {"name": "severity", "type": "String", "required": False, "description": "严重级别过滤，如 critical,high"},
            {"name": "templates", "type": "String", "required": False, "description": "指定模板路径/标签，如 cves/2023"},
            {"name": "extra_options", "type": "String", "required": False, "description": "附加 nuclei 参数，如 -rl 30 限速"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 900"},
        ],
        "pentest_scan",
        ["Nuclei", "漏洞扫描", "ProjectDiscovery", "第一批"],
    ),
    _sec_tool(
        "subfinder_enum",
        "Subfinder 子域名枚举：被动收集（crtsh/证书透明日志等数据源），不向目标发包。",
        [
            {"name": "domain", "type": "String", "required": True, "description": "目标根域名，如 example.com"},
            {"name": "extra_options", "type": "String", "required": False, "description": "附加 subfinder 参数"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 300"},
        ],
        "pentest_recon",
        ["Subfinder", "子域名", "ProjectDiscovery", "第一批"],
    ),
    _sec_tool(
        "httpx_probe",
        "httpx 存活探测：批量识别存活主机、标题、状态码、Web 技术栈（可配合 subfinder 结果）。",
        [
            {"name": "target", "type": "String", "required": True, "description": "目标域名 / IP / CIDR，多个用逗号分隔"},
            {"name": "ports", "type": "String", "required": False, "description": "追加探测端口，如 8080,8443"},
            {"name": "extra_options", "type": "String", "required": False, "description": "附加 httpx 参数"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 300"},
        ],
        "pentest_recon",
        ["httpx", "存活探测", "ProjectDiscovery", "第一批"],
    ),
    _sec_tool(
        "sqlmap_scan",
        "SQLMap SQL 注入检测：自动识别注入点、数据库类型、提取数据。默认 --batch 非交互模式。",
        [
            {"name": "url", "type": "String", "required": True, "description": "目标 URL（含参数），如 http://t/page?id=1"},
            {"name": "options", "type": "String", "required": False, "description": "sqlmap 参数，默认 --batch --random-agent --level 3 --risk 2"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 1800"},
        ],
        "pentest_scan",
        ["SQLMap", "SQL注入", "第一批"],
    ),
    # ---------- 第二批（深度扫描） ----------
    _sec_tool(
        "dnsx_resolve",
        "dnsx DNS 解析：A/AAAA/MX/TXT/NS/CNAME 记录查询与 IP 反查（PTR），支持自定义解析器。",
        [
            {"name": "domain", "type": "String", "required": True, "description": "目标域名（反查时传 IP）"},
            {"name": "resolver", "type": "String", "required": False, "description": "自定义 DNS 解析器，如 8.8.8.8"},
            {"name": "record_type", "type": "String", "required": False, "description": "记录类型：A/MX/TXT/NS/CNAME 等，默认 A"},
            {"name": "reverse", "type": "Boolean", "required": False, "description": "是否反查 PTR 记录"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 120"},
        ],
        "pentest_recon",
        ["dnsx", "DNS", "ProjectDiscovery", "第二批"],
    ),
    _sec_tool(
        "nikto_scan",
        "Nikto Web 服务器扫描：危险文件/目录、配置缺陷、过期软件版本检查。",
        [
            {"name": "target", "type": "String", "required": True, "description": "目标，如 http://target 或 host:port"},
            {"name": "options", "type": "String", "required": False, "description": "nikto 附加参数"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 900"},
        ],
        "pentest_scan",
        ["Nikto", "Web扫描", "第二批"],
    ),
    _sec_tool(
        "zap_baseline_scan",
        "OWASP ZAP 基线扫描：被动扫描目标站点，输出 WARN/FAIL 风险摘要（僵尸标签/泄露头/cookie 安全等）。",
        [
            {"name": "target", "type": "String", "required": True, "description": "目标完整 URL，如 https://target.com"},
            {"name": "extra_options", "type": "String", "required": False, "description": "附加 zap-baseline 参数"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 1800"},
        ],
        "pentest_scan",
        ["ZAP", "OWASP", "Web扫描", "第二批"],
    ),
    # ---------- 第三批（利用与报告） ----------
    _sec_tool(
        "msf_run_module",
        "Metasploit 模块执行（msgrpc）：自动拉起 msfrpcd，执行 exploit/auxiliary/post 模块并返回结果。",
        [
            {"name": "module_type", "type": "String", "required": False, "description": "模块类型：exploit/auxiliary/post，默认 exploit"},
            {"name": "module_name", "type": "String", "required": True, "description": "模块名，如 auxiliary/scanner/ssh/ssh_login"},
            {"name": "options", "type": "String", "required": False, "description": "参数串，如 RHOSTS=1.2.3.4 LPORT=4444"},
            {"name": "run_as_job", "type": "Boolean", "required": False, "description": "长任务以后台 job 运行"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 600"},
        ],
        "pentest_exploit",
        ["Metasploit", "msgrpc", "利用", "第三批"],
    ),
    _sec_tool(
        "msf_rpc_status",
        "检查 Metasploit RPC（msgrpc）服务状态：是否安装、是否运行。",
        [],
        "pentest_exploit",
        ["Metasploit", "状态", "第三批"],
    ),
    _sec_tool(
        "searchsploit_search",
        "SearchSploit（Exploit-DB）搜索：按关键词/CVE 查询公开漏洞利用代码。",
        [
            {"name": "query", "type": "String", "required": True, "description": "搜索关键词，如 Apache 2.4 或 CVE-2021-44228"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 60"},
        ],
        "pentest_exploit",
        ["SearchSploit", "ExploitDB", "第三批"],
    ),
    _sec_tool(
        "defectdojo_request",
        "DefectDojo 漏洞管理平台 API 透传：产品/测试/发现管理，扫描结果导入与报告生成。",
        [
            {"name": "endpoint", "type": "String", "required": True, "description": "API 路径，如 /api/v2/products/"},
            {"name": "method", "type": "String", "required": False, "description": "HTTP 方法，默认 GET"},
            {"name": "payload", "type": "Object", "required": False, "description": "JSON 请求体"},
            {"name": "api_key", "type": "String", "required": False, "description": "DefectDojo API Token"},
            {"name": "base_url", "type": "String", "required": False, "description": "服务地址，默认 http://soar-defectdojo:8080"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 60"},
        ],
        "pentest_exploit",
        ["DefectDojo", "漏洞管理", "报告", "第三批"],
    ),
    # ---------- 第四批（内网专项） ----------
    _sec_tool(
        "bloodhound_collect",
        "BloodHound AD 域信息采集：bloodhound-python 采集用户/组/ACL/会话等关系，输出可导入 BH CE 的 JSON 包。",
        [
            {"name": "domain", "type": "String", "required": True, "description": "目标域名，如 corp.local"},
            {"name": "username", "type": "String", "required": True, "description": "域用户名"},
            {"name": "password", "type": "String", "required": False, "description": "域密码"},
            {"name": "dc", "type": "String", "required": False, "description": "域控制器主机名或 IP"},
            {"name": "collection", "type": "String", "required": False, "description": "采集集合：All/DCOnly/Session/ACL/Trust，默认 All"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 1800"},
        ],
        "pentest_lateral",
        ["BloodHound", "内网", "AD", "第四批"],
    ),
    _sec_tool(
        "bloodhound_query",
        "BloodHound CE Cypher 查询：攻击路径分析（最短路径/Kerberoastable/DA 路径等）。",
        [
            {"name": "cypher", "type": "String", "required": True, "description": "Cypher 语句，如 MATCH (u:User) RETURN u.name LIMIT 10"},
            {"name": "base_url", "type": "String", "required": False, "description": "BH CE 地址，默认 http://soar-bloodhound:8080"},
            {"name": "username", "type": "String", "required": False, "description": "BH CE 登录用户名，默认 admin"},
            {"name": "password", "type": "String", "required": False, "description": "BH CE 登录密码"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 60"},
        ],
        "pentest_lateral",
        ["BloodHound", "内网", "攻击路径", "第四批"],
    ),
    _sec_tool(
        "hydra_attack",
        "Hydra 弱口令爆破：SSH/RDP/SMB/FTP/HTTP 等多协议在线口令猜测。",
        [
            {"name": "target", "type": "String", "required": True, "description": "目标 IP 或主机名"},
            {"name": "service", "type": "String", "required": False, "description": "协议：ssh/rdp/smb/ftp/http-post-form，默认 ssh"},
            {"name": "username", "type": "String", "required": False, "description": "用户名（与 username_file 二选一）"},
            {"name": "password", "type": "String", "required": False, "description": "密码（与 password_file 二选一）"},
            {"name": "username_file", "type": "String", "required": False, "description": "用户名字典路径"},
            {"name": "password_file", "type": "String", "required": False, "description": "密码字典路径"},
            {"name": "options", "type": "String", "required": False, "description": "附加参数，默认 -t 8 -w 5"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 1800"},
        ],
        "pentest_lateral",
        ["Hydra", "弱口令", "爆破", "第四批"],
    ),
    _sec_tool(
        "crackmapexec_run",
        "CrackMapExec（netexec）内网横向验证：SMB/WinRM/LDAP/SSH 凭据批量验证与信息收集。",
        [
            {"name": "protocol", "type": "String", "required": False, "description": "协议：smb/winrm/ldap/ssh/mssql，默认 smb"},
            {"name": "target", "type": "String", "required": True, "description": "目标 IP 或 CIDR 网段"},
            {"name": "username", "type": "String", "required": False, "description": "用户名（支持 user@domain）"},
            {"name": "password", "type": "String", "required": False, "description": "密码"},
            {"name": "options", "type": "String", "required": False, "description": "附加参数，如 --shares / --sam / --lsa"},
            {"name": "timeout", "type": "Integer", "required": False, "description": "超时秒数，默认 900"},
        ],
        "pentest_lateral",
        ["CrackMapExec", "netexec", "内网横向", "第四批"],
    ),
]
