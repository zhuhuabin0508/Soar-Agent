"""安全工具 subprocess 封装（供工具沙箱命名空间注入）。

封装 13 个主流安全工具，统一通过 ``asyncio.create_subprocess_exec`` 调用
（无 shell 注入面），并做超时控制、输出截断与结果结构化解析：

第一批（核心必装）：
- nmap_scan          端口/服务扫描
- nuclei_scan        漏洞 PoC 扫描（ProjectDiscovery nuclei）
- subfinder_enum     子域名枚举（ProjectDiscovery subfinder）
- httpx_probe        存活/标题/状态码探测（ProjectDiscovery httpx）
- sqlmap_scan        SQL 注入检测（sqlmap --batch 非交互）

第二批（深度扫描）：
- zap_baseline_scan  OWASP ZAP 被动基线扫描（zap-baseline.py）
- dnsx_resolve       DNS 解析 / 反查 / 记录查询（ProjectDiscovery dnsx）
- nikto_scan         Web 服务器配置漏洞扫描

第三批（利用与报告）：
- msf_run_module     Metasploit 模块执行（msgrpc，自动拉起 msfrpcd）
- msf_rpc_status     Metasploit RPC 服务状态
- searchsploit_search  Exploit-DB 漏洞利用搜索
- defectdojo_request   DefectDojo REST API 透传（漏洞管理平台）

第四批（内网专项）：
- bloodhound_collect   BloodHound AD 域信息采集（bloodhound-python）
- bloodhound_query     BloodHound CE Cypher 查询
- hydra_attack         弱口令爆破（hydra）
- crackmapexec_run     内网横向验证（crackmapexec / netexec）

安装位置约定（见 scripts/install-security-tools.sh）：
- Go 单二进制 / git 仓库 → /opt/security-tools（宿主机持久化卷）
- apt / pip / MSF deb → 容器层（容器重建后重跑安装脚本）
"""
import asyncio
import json
import logging
import os
import shutil
import shlex
import socket
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------- 安装位置常量 ----------
_TOOLS_DIR = Path("/opt/security-tools")
_BIN_DIR = _TOOLS_DIR / "bin"
_SRC_DIR = _TOOLS_DIR / "src"
_MSF_DIR = Path("/opt/metasploit-framework")
_ZAP_DIR = _SRC_DIR / "zap"

# Metasploit RPC 服务配置（msfrpcd 按需拉起）
MSF_RPC_HOST = "127.0.0.1"
MSF_RPC_PORT = 55553
MSF_RPC_USER = "msf"
MSF_RPC_PASS = "soar-msf-2024"

# DefectDojo / BloodHound CE 默认地址（可通过参数覆盖）
DEFECTDOJO_DEFAULT_URL = os.environ.get("DEFECTDOJO_URL", "http://soar-defectdojo:8080")
BLOODHOUND_DEFAULT_URL = os.environ.get("BLOODHOUND_URL", "http://soar-bloodhound:8080")

# stdout/stderr 最大保留长度（超长截断，防止撑爆 JSON 响应）
_MAX_OUTPUT = 120_000

# 危险参数黑名单（防误伤：拒绝明显的破坏性 nmap/hydra 参数由调用侧控制，
# 这里仅做最基本的二进制存在性检查）


def _find_bin(name: str, extra_paths: list[str] | None = None) -> str:
    """按优先级查找工具二进制：卷目录 → 额外路径 → PATH。"""
    candidates = [_BIN_DIR / name] + [Path(p) for p in (extra_paths or [])]
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"工具 {name} 未安装。请在容器内执行：sh /opt/security-tools/install-security-tools.sh all"
    )


def _to_int(value: Any, default: int) -> int:
    """容错转换超时等数值参数（前端可能传字符串）。"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


async def _run_cmd(
    args: list[str],
    timeout: int = 600,
    cwd: str | None = None,
    env_extra: dict[str, str] | None = None,
    max_output: int = _MAX_OUTPUT,
    stdin_data: str | None = None,
) -> dict[str, Any]:
    """异步执行外部命令（无 shell），返回结构化结果。"""
    timeout = _to_int(timeout, 600)
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    logger.info("security_tools exec: %s (timeout=%ss)", " ".join(args[:6]) + (" ..." if len(args) > 6 else ""), timeout)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as exc:
        return {"error": f"命令不存在: {exc}"}
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data.encode() if stdin_data is not None else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return {
            "error": f"执行超时（{timeout} 秒），已终止进程。可增大 timeout 参数后重试。",
            "timeout": True,
            "command": args[:4],
        }
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    truncated = len(out) > max_output
    return {
        "exit_code": proc.returncode,
        "stdout": out[:max_output] + ("\n...[输出过长已截断]" if truncated else ""),
        "stderr": err[:max_output],
        "command": args,
    }


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    """解析 JSON Lines 输出（nuclei/httpx/dnsx 的 -json 输出）。"""
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return results


# ============================================================================
# 第一批（核心必装）
# ============================================================================

async def nmap_scan(
    target: str = "",
    options: str = "-Pn -sV --top-ports 1000",
    timeout: int = 600,
) -> dict[str, Any]:
    """Nmap 端口/服务扫描。

    Args:
        target: 目标 IP / CIDR / 域名（多个目标用空格分隔）
        options: nmap 参数（默认 -Pn -sV --top-ports 1000，加 -T4 提速）
        timeout: 超时秒数
    """
    if not target:
        return {"error": "请提供 target 参数（IP / 网段 / 域名）"}
    binary = _find_bin("nmap")
    args = [binary] + shlex.split(options) + shlex.split(target)
    result = await _run_cmd(args, timeout=timeout)
    if "error" in result:
        return result
    return {
        "tool": "nmap",
        "target": target,
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


async def nuclei_scan(
    target: str = "",
    severity: str = "",
    templates: str = "",
    extra_options: str = "",
    timeout: int = 900,
) -> dict[str, Any]:
    """Nuclei 漏洞 PoC 扫描（基于 nuclei-templates 模板库）。

    Args:
        target: 目标 URL / IP（多个用逗号分隔）
        severity: 严重级别过滤，如 critical,high 或 medium,high,critical
        templates: 指定模板路径/标签，如 cves/2023（空则用全部模板）
        extra_options: 附加 nuclei 参数，如 "-rl 30 -c 25"
        timeout: 超时秒数
    """
    if not target:
        return {"error": "请提供 target 参数（URL 或 IP）"}
    binary = _find_bin("nuclei")
    args = [binary, "-target", target, "-json", "-silent", "-nc"]
    # 模板目录：优先使用持久化卷中的完整模板库
    tpl_dir = _SRC_DIR / "nuclei-templates"
    if templates:
        args += ["-t", templates]
    elif tpl_dir.is_dir():
        args += ["-t", str(tpl_dir)]
    if severity:
        args += ["-severity", severity]
    if extra_options:
        args += shlex.split(extra_options)
    result = await _run_cmd(args, timeout=timeout)
    if "error" in result:
        return result
    findings = _parse_jsonl(result["stdout"])
    return {
        "tool": "nuclei",
        "target": target,
        "total_findings": len(findings),
        "findings": findings[:500],
        "exit_code": result["exit_code"],
        "raw_output": result["stdout"][:20_000] if not findings else "",
        "stderr": result["stderr"][:5_000],
    }


async def subfinder_enum(
    domain: str = "",
    extra_options: str = "",
    timeout: int = 300,
) -> dict[str, Any]:
    """Subfinder 子域名枚举（被动收集，支持多数据源）。

    Args:
        domain: 目标根域名，如 example.com
        extra_options: 附加 subfinder 参数，如 "-sources crtsh,subfinder"
        timeout: 超时秒数
    """
    if not domain:
        return {"error": "请提供 domain 参数（根域名）"}
    binary = _find_bin("subfinder")
    args = [binary, "-d", domain, "-silent"]
    if extra_options:
        args += shlex.split(extra_options)
    result = await _run_cmd(args, timeout=timeout)
    if "error" in result:
        return result
    subdomains = [l.strip() for l in result["stdout"].splitlines() if l.strip()]
    return {
        "tool": "subfinder",
        "domain": domain,
        "total": len(subdomains),
        "subdomains": subdomains[:2000],
        "exit_code": result["exit_code"],
        "stderr": result["stderr"][:5_000],
    }


async def httpx_probe(
    target: str = "",
    ports: str = "",
    extra_options: str = "",
    timeout: int = 300,
) -> dict[str, Any]:
    """httpx 存活探测（标题 / 状态码 / 技术栈 / CDN 识别）。

    Args:
        target: 目标，支持域名 / IP / CIDR / URL（多个用逗号分隔）
        ports: 追加探测端口，如 8080,8443
        extra_options: 附加 httpx 参数，如 "-tech-detect -follow-redirects"
        timeout: 超时秒数
    """
    if not target:
        return {"error": "请提供 target 参数（域名 / IP / 网段）"}
    binary = _find_bin("httpx")
    args = [binary, "-u", target, "-json", "-silent", "-title", "-status-code", "-tech-detect"]
    if ports:
        args += ["-ports", ports]
    if extra_options:
        args += shlex.split(extra_options)
    result = await _run_cmd(args, timeout=timeout)
    if "error" in result:
        return result
    hosts = _parse_jsonl(result["stdout"])
    return {
        "tool": "httpx",
        "target": target,
        "total_alive": len(hosts),
        "hosts": hosts[:1000],
        "exit_code": result["exit_code"],
        "stderr": result["stderr"][:5_000],
    }


async def sqlmap_scan(
    url: str = "",
    options: str = "--batch --random-agent --level 3 --risk 2",
    timeout: int = 1800,
) -> dict[str, Any]:
    """SQLMap SQL 注入检测（默认 --batch 非交互模式）。

    Args:
        url: 目标 URL，含参数，如 http://target/page?id=1
        options: sqlmap 参数（务必保留 --batch 避免交互卡死）
        timeout: 超时秒数（注入检测较慢，建议 1800）
    """
    if not url:
        return {"error": "请提供 url 参数（含参数的完整 URL）"}
    if "--batch" not in options:
        options += " --batch"
    binary = _find_bin("sqlmap")
    args = [binary] + shlex.split(options) + ["-u", url]
    result = await _run_cmd(args, timeout=timeout)
    if "error" in result:
        return result
    # 判定注入结果
    vulnerable = "is vulnerable" in result["stdout"].lower() or "might be injectable" in result["stdout"].lower()
    return {
        "tool": "sqlmap",
        "url": url,
        "vulnerable": vulnerable,
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"][:10_000],
    }


# ============================================================================
# 第二批（深度扫描）
# ============================================================================

async def zap_baseline_scan(
    target: str = "",
    timeout: int = 1800,
    extra_options: str = "",
) -> dict[str, Any]:
    """OWASP ZAP 基线（被动）扫描：Web 安全基线检查，输出风险摘要。

    Args:
        target: 目标 URL，如 https://target.example.com
        timeout: 超时秒数
        extra_options: 附加 zap-baseline.py 参数，如 "-c config" / "-I"（仅扫描，无告警）
    """
    if not target:
        return {"error": "请提供 target 参数（完整 URL）"}
    script = _ZAP_DIR / "zap-baseline.py"
    if not script.is_file():
        return {"error": "ZAP 未安装。请在容器内执行安装脚本 batch2 后重试。"}
    if not shutil.which("java"):
        return {"error": "Java 运行时未安装（ZAP 依赖）。请执行安装脚本 batch2。"}
    args = ["python3", str(script), "-t", target, "-I"] + shlex.split(extra_options)
    result = await _run_cmd(args, timeout=timeout, cwd=str(_ZAP_DIR))
    if "error" in result:
        return result
    # zap-baseline 退出码: 0=无告警 1=有 WARN 2=有 FAIL 3=连接失败
    code = result["exit_code"]
    summary = {0: "未发现告警", 1: "发现 WARN 级告警", 2: "发现 FAIL 级告警", 3: "目标连接失败"}.get(code, f"退出码 {code}")
    return {
        "tool": "zap-baseline",
        "target": target,
        "summary": summary,
        "exit_code": code,
        "stdout": result["stdout"],
        "stderr": result["stderr"][:10_000],
    }


async def dnsx_resolve(
    domain: str = "",
    resolver: str = "",
    record_type: str = "",
    reverse: bool = False,
    extra_options: str = "",
    timeout: int = 120,
) -> dict[str, Any]:
    """dnsx DNS 解析：A/AAAA/MX/TXT/NS 等记录查询与反查。

    Args:
        domain: 目标域名或 IP（反查时传 IP）
        resolver: 自定义解析器，如 8.8.8.8
        record_type: 记录类型，如 A / MX / TXT / NS（空则默认 A）
        reverse: 是否反查（PTR）
        extra_options: 附加 dnsx 参数
        timeout: 超时秒数
    """
    if not domain:
        return {"error": "请提供 domain 参数"}
    binary = _find_bin("dnsx")
    # 域名走 stdin 输入（-d/-domain 是枚举模式，需要 wordlist）
    stdin_lines = domain
    args = [binary, "-json", "-silent", "-resp"]
    if record_type:
        args += ["-t", record_type]
    else:
        args += ["-a"]
    if reverse:
        args += ["-ptr"]
    if resolver:
        args += ["-r", resolver]
    if extra_options:
        args += shlex.split(extra_options)
    result = await _run_cmd(args, timeout=timeout, stdin_data=stdin_lines)
    if "error" in result:
        return result
    records = _parse_jsonl(result["stdout"])
    return {
        "tool": "dnsx",
        "domain": domain,
        "total": len(records),
        "records": records[:1000],
        "exit_code": result["exit_code"],
        "stderr": result["stderr"][:5_000],
    }


async def nikto_scan(
    target: str = "",
    options: str = "-Format json",
    timeout: int = 900,
) -> dict[str, Any]:
    """Nikto Web 服务器扫描：危险文件/配置/软件版本检查。

    Args:
        target: 目标（http://host 或 host:port）
        options: nikto 参数（默认 -Format json）
        timeout: 超时秒数
    """
    if not target:
        return {"error": "请提供 target 参数"}
    binary = _find_bin("nikto")
    tmpdir = tempfile.mkdtemp(prefix="soar_nikto_")
    out_file = os.path.join(tmpdir, "result.json")
    args = [binary, "-h", target, "-o", out_file, "-Format", "json"]
    if options and "-Format" not in options:
        args += shlex.split(options)
    result = await _run_cmd(args, timeout=timeout, cwd=tmpdir)
    if "error" in result:
        return result
    findings: list = []
    if os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            vulns = data.get("vulnerabilities", []) if isinstance(data, dict) else []
            findings = vulns[:500]
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "tool": "nikto",
        "target": target,
        "total_findings": len(findings),
        "findings": findings,
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][:20_000],
        "stderr": result["stderr"][:5_000],
    }


# ============================================================================
# 第三批（利用与报告）
# ============================================================================

def _msfrpcd_running() -> bool:
    """检查 msfrpcd 端口是否可连。"""
    try:
        with socket.create_connection((MSF_RPC_HOST, MSF_RPC_PORT), timeout=2):
            return True
    except OSError:
        return False


async def _ensure_msfrpcd() -> str | None:
    """确保 msfrpcd 已运行（未运行则后台拉起，等待就绪）。返回错误信息或 None。"""
    if _msfrpcd_running():
        return None
    msfrpcd = _MSF_DIR / "bin" / "msfrpcd"
    if not msfrpcd.is_file():
        return "Metasploit 未安装（msfrpcd 不存在）。请执行安装脚本 batch3。"
    try:
        proc = await asyncio.create_subprocess_exec(
            str(msfrpcd),
            "-P", MSF_RPC_PASS,
            "-U", MSF_RPC_USER,
            "-a", MSF_RPC_HOST,
            "-p", str(MSF_RPC_PORT),
            "-S",  # 禁用 SSL（容器内回环通信）
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return "msfrpcd 启动失败：可执行文件不存在"
    # 最多等 60 秒就绪
    for _ in range(30):
        await asyncio.sleep(2)
        if _msfrpcd_running():
            return None
    if proc.returncode is not None:
        return f"msfrpcd 启动后异常退出（exit={proc.returncode}）"
    return None


async def msf_rpc_status() -> dict[str, Any]:
    """检查 Metasploit RPC（msgrpc）服务状态。"""
    installed = (_MSF_DIR / "bin" / "msfrpcd").is_file()
    return {
        "tool": "msfrpc",
        "metasploit_installed": installed,
        "rpc_host": MSF_RPC_HOST,
        "rpc_port": MSF_RPC_PORT,
        "rpc_running": _msfrpcd_running(),
    }


async def msf_run_module(
    module_type: str = "exploit",
    module_name: str = "",
    options: str = "",
    datastore: dict[str, str] | None = None,
    run_as_job: bool = False,
    timeout: int = 600,
) -> dict[str, Any]:
    """通过 msgrpc 执行 Metasploit 模块（自动拉起 msfrpcd）。

    Args:
        module_type: 模块类型 exploit / auxiliary / post / payload / encoder
        module_name: 模块名，如 unix/webapp/wp_plugin_reflexgallery_upload
        options: msfconsole 风格的设置串，如 "RHOSTS=1.2.3.4 LPORT=4444"
        datastore: 模块参数字典（与 options 二选一，优先级更高）
        run_as_job: 是否以后台 job 方式运行（长任务用）
        timeout: 超时秒数
    """
    if not module_name:
        return {"error": "请提供 module_name 参数（Metasploit 模块名）"}
    timeout = _to_int(timeout, 600)
    err = await _ensure_msfrpcd()
    if err:
        return {"error": err}

    def _run_sync() -> dict[str, Any]:
        from pymetasploit3.msfrpc import MsfRpcClient  # 延迟导入

        client = MsfRpcClient(
            MSF_RPC_PASS,
            server=MSF_RPC_HOST,
            port=MSF_RPC_PORT,
            username=MSF_RPC_USER,
            ssl=False,
        )
        mod = client.modules.use(module_type, module_name)
        # datastore 覆盖 options
        ds = {}
        for kv in shlex.split(options or ""):
            if "=" in kv:
                k, v = kv.split("=", 1)
                ds[k] = v
        if datastore:
            ds.update({str(k): str(v) for k, v in datastore.items()})
        for k, v in ds.items():
            try:
                mod[k] = v
            except Exception:  # noqa: BLE001
                pass
        if run_as_job:
            job_id = mod.execute()
            return {"tool": "msf", "module": f"{module_type}/{module_name}", "job_id": job_id, "started": True}
        result = mod.execute()
        return {"tool": "msf", "module": f"{module_type}/{module_name}", "result": str(result), "started": True}

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run_sync), timeout=timeout)
    except asyncio.TimeoutError:
        return {"error": f"Metasploit 模块执行超时（{timeout} 秒）", "timeout": True}
    except ImportError:
        return {"error": "pymetasploit3 未安装。请在容器内执行安装脚本 batch3。"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Metasploit 调用失败: {exc}"}


async def searchsploit_search(
    query: str = "",
    timeout: int = 60,
) -> dict[str, Any]:
    """SearchSploit（Exploit-DB）漏洞利用代码搜索。

    Args:
        query: 搜索关键词，如 "Apache 2.4" / "CVE-2021-44228"
        timeout: 超时秒数
    """
    if not query:
        return {"error": "请提供 query 参数（搜索关键词）"}
    binary = _find_bin("searchsploit")
    args = [binary, "-j", query]
    # searchsploit -j 全量 JSON 可能很大（宽关键词 >1MB），放大截断上限避免 JSON 被截断解析失败
    result = await _run_cmd(args, timeout=timeout, max_output=4_000_000)
    if "error" in result:
        return result
    # searchsploit -j 输出 JSON：{"RESULTS_EXPLOIT": [...], ...}
    exploits: list = []
    raw = result["stdout"]
    start = raw.find("{")
    if start >= 0:
        try:
            data = json.loads(raw[start:])
            exploits = data.get("RESULTS_EXPLOIT", [])
        except (json.JSONDecodeError, ValueError):
            # 输出被截断：逐行修复——丢弃最后一个不完整对象，补 ]} 结尾
            lines = raw[start:].splitlines()
            fixed: list[str] = []
            for ln in lines:
                if ln.strip().startswith("{") and not ln.rstrip().endswith("},"):
                    break  # 最后一条被拦腰截断，丢弃
                fixed.append(ln)
            text = "\n".join(fixed)
            if text.rstrip().endswith("},"):
                text = text.rstrip()[:-1]  # 去掉末尾逗号
            try:
                data = json.loads(text + "\n]}")
                exploits = data.get("RESULTS_EXPLOIT", [])
            except (json.JSONDecodeError, ValueError):
                pass
    return {
        "tool": "searchsploit",
        "query": query,
        "total": len(exploits),
        "exploits": exploits[:300],
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][:10_000] if not exploits else "",
        "stderr": result["stderr"][:5_000],
    }


async def defectdojo_request(
    endpoint: str = "",
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    api_key: str = "",
    base_url: str = "",
    timeout: int = 60,
) -> dict[str, Any]:
    """DefectDojo REST API v2 透传（漏洞管理平台：产品/发现/报告管理）。

    Args:
        endpoint: API 路径，如 /api/v2/products/ 或 /api/v2/findings/
        method: HTTP 方法 GET / POST / PUT / PATCH / DELETE
        payload: JSON 请求体（POST/PUT 时）
        api_key: DefectDojo API Token（v2 Token 认证）
        base_url: DefectDojo 服务地址（默认 http://soar-defectdojo-uwsgi:8080）
        timeout: 超时秒数
    """
    if not endpoint:
        return {"error": "请提供 endpoint 参数（如 /api/v2/products/）"}
    timeout = _to_int(timeout, 60)
    import httpx

    base = (base_url or DEFECTDOJO_DEFAULT_URL).rstrip("/")
    url = base + endpoint if endpoint.startswith("/") else f"{base}/{endpoint}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Token {api_key}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method.upper(),
                url,
                json=payload if payload is not None else None,
                headers=headers,
            )
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text[:20_000]}
        return {
            "tool": "defectdojo",
            "url": url,
            "status_code": resp.status_code,
            "ok": resp.is_success,
            "body": body,
        }
    except httpx.HTTPError as exc:
        return {"error": f"DefectDojo 连接失败: {exc}"}


# ============================================================================
# 第四批（内网专项）
# ============================================================================

async def bloodhound_collect(
    domain: str = "",
    username: str = "",
    password: str = "",
    dc: str = "",
    collection: str = "All",
    extra_options: str = "",
    timeout: int = 1800,
) -> dict[str, Any]:
    """BloodHound AD 域信息采集（bloodhound-python 采集器）。

    采集结果为 JSON 压缩包，可导入 BloodHound CE 进行攻击路径分析。

    Args:
        domain: 目标域名，如 corp.local
        username: 域用户名
        password: 域密码
        dc: 域控制器主机名或 IP（空则自动解析）
        collection: 采集集合：All / Default / DCOnly / Session / ACL / Trust ...
        extra_options: 附加参数，如 "--no-pass -k"
        timeout: 超时秒数
    """
    if not domain or not username:
        return {"error": "请提供 domain 与 username 参数"}
    binary = _find_bin("bloodhound-python")
    args = [
        binary, "-d", domain, "-u", username,
        "-c", collection, "--zip", "--silent",
    ]
    if password:
        args += ["-p", password]
    if dc:
        args += ["-dc", dc]
    if extra_options:
        args += shlex.split(extra_options)
    tmpdir = tempfile.mkdtemp(prefix="soar_bh_")
    result = await _run_cmd(args, timeout=timeout, cwd=tmpdir, max_output=40_000)
    if "error" in result:
        return result
    files = sorted(os.listdir(tmpdir)) if os.path.isdir(tmpdir) else []
    zips = [f for f in files if f.endswith(".zip")]
    return {
        "tool": "bloodhound-python",
        "domain": domain,
        "output_dir": tmpdir,
        "files": files[:100],
        "zip_files": zips,
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][:20_000],
        "stderr": result["stderr"][:5_000],
    }


async def bloodhound_query(
    cypher: str = "",
    base_url: str = "",
    username: str = "",
    password: str = "",
    api_key: str = "",
    timeout: int = 60,
) -> dict[str, Any]:
    """BloodHound CE Cypher 图查询（攻击路径分析）。

    Args:
        cypher: Cypher 查询语句，如 MATCH (u:User) RETURN u.name LIMIT 10
        base_url: BloodHound CE 地址（默认 http://soar-bloodhound:8080）
        username/password: BH CE 登录账号（默认 admin）
        api_key: 已有 API Token（与账密二选一）
        timeout: 超时秒数
    """
    if not cypher:
        return {"error": "请提供 cypher 参数（Cypher 查询语句）"}
    timeout = _to_int(timeout, 60)
    import httpx

    base = (base_url or BLOODHOUND_DEFAULT_URL).rstrip("/")
    headers = {"Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            else:
                # 账密登录换 token（BH CE v2 API：login_method=secret）
                resp = await client.post(
                    f"{base}/api/v2/login",
                    json={
                        "login_method": "secret",
                        "secret": password or "BloodHound@2024",
                        "username": username or "admin",
                    },
                )
                token = (resp.json().get("data") or {}).get("session_token", "")
                if not token:
                    return {
                        "error": "BloodHound 登录失败，请检查账号密码或服务状态",
                        "login_status": resp.status_code,
                        "detail": str(resp.json())[:500],
                    }
                headers["Authorization"] = f"Bearer {token}"
            resp = await client.post(
                f"{base}/api/v2/graphs/cypher",
                json={"query": cypher},
                headers=headers,
            )
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text[:20_000]}
        return {
            "tool": "bloodhound",
            "status_code": resp.status_code,
            "ok": resp.is_success,
            "data": body,
        }
    except httpx.HTTPError as exc:
        return {"error": f"BloodHound 连接失败: {exc}"}


async def hydra_attack(
    target: str = "",
    service: str = "ssh",
    username: str = "",
    password: str = "",
    username_file: str = "",
    password_file: str = "",
    options: str = "-t 8 -w 5",
    timeout: int = 1800,
) -> dict[str, Any]:
    """Hydra 弱口令爆破（支持 ssh/rdp/smb/ftp/http 等多种协议）。

    Args:
        target: 目标 IP 或主机名
        service: 协议服务，如 ssh / rdp / smb / ftp / http-post-form
        username: 单用户名（与 username_file 二选一）
        password: 单密码（与 password_file 二选一）
        username_file: 用户名字典路径
        password_file: 密码字典路径
        options: 附加参数（默认 -t 8 并发 -w 5 超时）
        timeout: 超时秒数
    """
    if not target or not service:
        return {"error": "请提供 target 与 service 参数"}
    if not (username or username_file):
        return {"error": "请提供 username 或 username_file 参数"}
    if not (password or password_file):
        return {"error": "请提供 password 或 password_file 参数"}
    binary = _find_bin("hydra")
    args = [binary] + shlex.split(options)
    if username:
        args += ["-l", username]
    if username_file:
        args += ["-L", username_file]
    if password:
        args += ["-p", password]
    if password_file:
        args += ["-P", password_file]
    args += [target, service]
    result = await _run_cmd(args, timeout=timeout)
    if "error" in result:
        return result
    # hydra: [target][service] host: login: password 行为命中
    hits = [
        l for l in result["stdout"].splitlines()
        if "login:" in l and "password:" in l
    ]
    return {
        "tool": "hydra",
        "target": target,
        "service": service,
        "valid_credentials": hits,
        "total_hits": len(hits),
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"][:10_000],
    }


async def crackmapexec_run(
    protocol: str = "smb",
    target: str = "",
    username: str = "",
    password: str = "",
    options: str = "",
    timeout: int = 900,
) -> dict[str, Any]:
    """CrackMapExec（netexec）内网横向验证：SMB/WinRM/LDAP/SSH/MSSQL 等。

    Args:
        protocol: 协议 smb / winrm / ldap / ssh / mssql / ftp
        target: 目标 IP / CIDR（如 192.168.1.0/24）
        username: 用户名（支持 user@domain）
        password: 密码（空则尝试空密码）
        options: 附加参数，如 "--sam" / "--shares" / "--lsa"
        timeout: 超时秒数
    """
    if not target:
        return {"error": "请提供 target 参数（IP 或网段）"}
    binary = None
    try:
        binary = _find_bin("crackmapexec")
    except FileNotFoundError:
        try:
            binary = _find_bin("cme")
        except FileNotFoundError:
            try:
                binary = _find_bin("nxc")  # netexec 后继命令
            except FileNotFoundError:
                return {
                    "error": "crackmapexec / netexec 未安装。请执行安装脚本 batch4。"
                }
    args = [binary, protocol, target]
    if username:
        args += ["-u", username]
    if password:
        args += ["-p", password]
    if options:
        args += shlex.split(options)
    result = await _run_cmd(args, timeout=timeout)
    if "error" in result:
        return result
    # CME 命中行含 [+] 标记
    success_lines = [l for l in result["stdout"].splitlines() if l.strip().startswith("[+]")]
    return {
        "tool": "crackmapexec",
        "protocol": protocol,
        "target": target,
        "success_lines": success_lines[:200],
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"][:10_000],
    }
