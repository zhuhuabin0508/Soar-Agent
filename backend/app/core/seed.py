"""平台默认种子数据初始化。

在容器启动时（entrypoint.sh）调用 ``ensure_seed_data``，当关键表为空时
自动种入默认工具、示例工作流等兜底数据，确保即使 ``docker compose down -v``
清空数据卷后重建，平台仍具备基础可用能力（默认工具不会丢）。

注意：仅当表为空时才种入，不会覆盖用户已保存的自定义数据。
``ensure_hermes_tools`` 例外：每次启动都幂等执行，按 name 查询后插入缺失的
Hermes 内置/框架级工具，确保升级后新工具自动出现。
``ensure_hermes_tools`` 还包含「代码修复」逻辑：若已存在的 code 工具含有
import 语句（沙箱无 ``__import__``，运行时必失败），自动用 seed 版本覆盖。
"""
import ast
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.tool import Tool
from app.models.workflow import Workflow
from app.models.skill import Skill

logger = logging.getLogger(__name__)

# 默认工具集：覆盖常见 SOAR 安全运营场景
DEFAULT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_whitelist",
        "description": "检查源 IP 是否在白名单中（白名单 IP 不触发封禁）",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待检查的 IP 地址"}
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    # 演示白名单：实际应查 DB / 配置中心\n"
            "    whitelist = ['10.0.0.1', '192.168.1.1', '127.0.0.1']\n"
            "    return {'ip': ip, 'in_whitelist': ip in whitelist}\n"
        ),
        "enabled": True,
    },
    {
        "name": "query_asset_info",
        "description": "查询 IP 对应的资产归属信息（部门/负责人/资产类型）",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待查询的 IP 地址"}
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    # 演示资产库：实际应对接 CMDB\n"
            "    assets = {\n"
            "        '10.0.0.5': {'owner': '运维部', 'type': '服务器', 'critical': True},\n"
            "        '192.168.1.100': {'owner': '研发部', 'type': '工作站', 'critical': False},\n"
            "    }\n"
            "    return {'ip': ip, 'asset': assets.get(ip, {'owner': '未知', 'type': '未知', 'critical': False})}\n"
        ),
        "enabled": True,
    },
    {
        "name": "query_threat_intel",
        "description": "查询 IP 的威胁情报（恶意评分/标签/历史攻击记录）",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待查询的 IP 地址"}
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    # 演示威胁情报：实际应对接 VirusTotal/微步等\n"
            "    malicious_ips = {'1.2.3.4', '5.6.7.8', '9.10.11.12'}\n"
            "    is_malicious = ip in malicious_ips\n"
            "    return {\n"
            "        'ip': ip,\n"
            "        'is_malicious': is_malicious,\n"
            "        'score': 95 if is_malicious else 10,\n"
            "        'tags': ['botnet', 'brute_force'] if is_malicious else [],\n"
            "    }\n"
        ),
        "enabled": True,
    },
    {
        "name": "query_ip_geo",
        "description": "查询 IP 的地理位置与运营商归属",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待查询的 IP 地址"}
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    # 演示地理库：实际应对接 IP2Region/MaxMind\n"
            "    return {'ip': ip, 'country': '中国', 'province': '北京', 'isp': '电信', 'city': '北京'}\n"
        ),
        "enabled": True,
    },
    {
        "name": "check_port_scan",
        "description": "检查 IP 是否存在端口扫描行为（基于日志统计）",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待检查的 IP 地址"},
            {"name": "threshold", "type": "Number", "required": False, "description": "扫描端口数阈值，默认 20"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    threshold = kwargs.get('threshold', 20)\n"
            "    # 演示：实际应查 SIEM 日志\n"
            "    scanned_ports = 35  # mock\n"
            "    return {'ip': ip, 'scanned_ports': scanned_ports, 'is_scanning': scanned_ports >= threshold, 'threshold': threshold}\n"
        ),
        "enabled": True,
    },
    {
        "name": "send_alert_to_siem",
        "description": "将告警事件转发至 SIEM 系统（Splunk/ELK）",
        "parameters_schema": [
            {"name": "alert_data", "type": "Object", "required": True, "description": "告警数据"},
            {"name": "siem_url", "type": "String", "required": False, "description": "SIEM 接收 URL"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    alert = kwargs.get('alert_data') or {}\n"
            "    siem_url = kwargs.get('siem_url') or 'http://siem:8080/api/alerts'\n"
            "    # 演示：实际应用 httpx.post(siem_url, json=alert)\n"
            "    return {'forwarded': True, 'siem_url': siem_url, 'alert_id': alert.get('alert_id', 'unknown')}\n"
        ),
        "enabled": True,
    },
]


# ============================================================================
# Hermes 引擎内置工具（tool_type='code'）
#
# 从 app/tools/context_tools.py 迁移而来，转为 DB code 工具统一管理。
# 代码内联使用注入的 ipaddress 模块（tool_runner 沙箱已注入），无需 import。
# ============================================================================
HERMES_BUILTIN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_whitelist",
        "description": "检查源 IP 是否命中内网白名单（10/172.16/192.168 网段视为可信内网，不触发处置）",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待检查的 IPv4/IPv6 地址"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    whitelist_nets = [\n"
            "        ipaddress.ip_network('10.0.0.0/8'),\n"
            "        ipaddress.ip_network('172.16.0.0/12'),\n"
            "        ipaddress.ip_network('192.168.0.0/16'),\n"
            "    ]\n"
            "    try:\n"
            "        addr = ipaddress.ip_address(ip)\n"
            "    except ValueError:\n"
            "        return {'ip': ip, 'in_whitelist': False, 'error': '无效的 IP 地址'}\n"
            "    result = any(addr in net for net in whitelist_nets)\n"
            "    return {'ip': ip, 'in_whitelist': result}\n"
        ),
        "tool_type": "code",
        "category": "security",
        "enabled": True,
    },
    {
        "name": "get_asset_info",
        "description": "查询 IP 对应资产归属信息（部门/负责人/是否关键资产）。优先查询智能体勾选的知识库，未命中时返回 found=false（可转用威胁情报工具）",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待查询的 IP 地址"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    # 优先查询智能体勾选的知识库（引擎注入 enabled_kbs / search_kb）\n"
            "    kb_ids = list(enabled_kbs or [])\n"
            "    if kb_ids:\n"
            "        # 查询知识库名称映射 + 分段数（供返回标注来源 + 跳过大库避免超时）\n"
            "        kb_names = {}\n"
            "        kb_seg_counts = {}\n"
            "        try:\n"
            "            db = SessionLocal()\n"
            "            try:\n"
            "                for kb in db.query(KnowledgeBase).all():\n"
            "                    kb_names[kb.id] = kb.name\n"
            "                from sqlalchemy import func as _func\n"
            "                rows = db.query(KnowledgeSegment.kb_id, _func.count()).filter(\n"
            "                    KnowledgeSegment.kb_id.in_(kb_ids)\n"
            "                ).group_by(KnowledgeSegment.kb_id).all()\n"
            "                kb_seg_counts = {r[0]: r[1] for r in rows}\n"
            "            finally:\n"
            "                db.close()\n"
            "        except Exception:\n"
            "            pass\n"
            "        # ===== 精确 IP 匹配（直接 LIKE 查询，毫秒级）=====\n"
            "        # BM25/向量检索对 IP 地址效果差且大库超时，精确匹配优先。\n"
            "        exact_matches = []\n"
            "        try:\n"
            "            db = SessionLocal()\n"
            "            try:\n"
            "                segs = db.query(KnowledgeSegment).filter(\n"
            "                    KnowledgeSegment.kb_id.in_(kb_ids),\n"
            "                    KnowledgeSegment.content.like('%' + ip + '%')\n"
            "                ).limit(20).all()\n"
            "                for seg in segs:\n"
            "                    exact_matches.append({\n"
            "                        'kb_id': seg.kb_id,\n"
            "                        'kb_name': kb_names.get(seg.kb_id, f'知识库-{seg.kb_id}'),\n"
            "                        'title': '',\n"
            "                        'content': seg.content,\n"
            "                        'score': 1.0,\n"
            "                        'exact_match': True,\n"
            "                    })\n"
            "            finally:\n"
            "                db.close()\n"
            "        except Exception:\n"
            "            pass\n"
            "        # 精确匹配命中 → 直接返回，跳过慢速 BM25（避免大库超时）\n"
            "        if exact_matches:\n"
            "            return {'ip': ip, 'found': True, 'source': 'knowledge_base', 'count': len(exact_matches), 'matches': exact_matches[:10]}\n"
            "        # ===== BM25 / 向量检索（仅在精确匹配未命中时执行）=====\n"
            "        # 跳过分段数 > 1000 的大库（jieba 分词 + BM25 计算耗时数秒，导致超时）\n"
            "        bm25_matches = []\n"
            "        for kb_id in kb_ids:\n"
            "            if kb_seg_counts.get(kb_id, 0) > 1000:\n"
            "                continue\n"
            "            try:\n"
            "                segs = await search_kb(kb_id, ip, top_k=5)\n"
            "            except Exception:\n"
            "                segs = []\n"
            "            for s in segs:\n"
            "                if (s.get('score') or 0) > 0.1:\n"
            "                    bm25_matches.append({\n"
            "                        'kb_id': kb_id,\n"
            "                        'kb_name': kb_names.get(kb_id, f'知识库-{kb_id}'),\n"
            "                        'title': s.get('title', ''),\n"
            "                        'content': s.get('content', ''),\n"
            "                        'score': round(s.get('score', 0), 3),\n"
            "                        'exact_match': False,\n"
            "                    })\n"
            "        # 合并 + 去重 + 排序\n"
            "        all_matches = exact_matches + bm25_matches\n"
            "        seen = set()\n"
            "        deduped = []\n"
            "        for m in all_matches:\n"
            "            key = (m.get('content', '') or '')[:100]\n"
            "            if key not in seen:\n"
            "                seen.add(key)\n"
            "                deduped.append(m)\n"
            "        deduped.sort(key=lambda x: x.get('score', 0), reverse=True)\n"
            "        if deduped:\n"
            "            return {'ip': ip, 'found': True, 'source': 'knowledge_base', 'count': len(deduped), 'matches': deduped[:10]}\n"
            "        return {'ip': ip, 'found': False, 'source': 'knowledge_base', 'message': '勾选的知识库中未找到该IP，建议使用威胁情报工具查询'}\n"
            "    # 无 agent 上下文（工具测试等）：回退全库查询\n"
            "    try:\n"
            "        return await get_asset_info(ip)\n"
            "    except Exception:\n"
            "        return {'ip': ip, 'found': False, 'message': '未找到该IP的资产信息'}\n"
        ),
        "tool_type": "code",
        "category": "security",
        "enabled": True,
    },
    {
        "name": "get_threat_intel",
        "description": "查询 IP 威胁情报（恶意判定/威胁标签/威胁类型/严重程度/置信度/首次发现/最后发现/情报来源/威胁描述/地理位置/关联恶意软件/攻击模式）。内网白名单 IP 视为非恶意",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待查询的 IP 地址"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    whitelist_nets = [\n"
            "        ipaddress.ip_network('10.0.0.0/8'),\n"
            "        ipaddress.ip_network('172.16.0.0/12'),\n"
            "        ipaddress.ip_network('192.168.0.0/16'),\n"
            "    ]\n"
            "    try:\n"
            "        addr = ipaddress.ip_address(ip)\n"
            "        is_malicious = not any(addr in net for net in whitelist_nets)\n"
            "    except ValueError:\n"
            "        is_malicious = True\n"
            "    if is_malicious:\n"
            "        return {\n"
            "            'ip': ip,\n"
            "            'is_malicious': True,\n"
            "            'tags': ['Botnet', 'C2'],\n"
            "            'confidence': 0.92,\n"
            "            'threat_types': ['C2 通信', '僵尸网络节点', '暴力破解'],\n"
            "            'severity': 'high',\n"
            "            'first_seen': '2026-07-15T08:23:00',\n"
            "            'last_seen': '2026-07-29T06:45:00',\n"
            "            'source': '内部威胁情报平台 + 开源情报(OSINT)',\n"
            "            'description': f'该 IP {ip} 被多个威胁情报源标记为恶意，关联多个僵尸网络家族，持续对外发起 C2 通信和 SSH 暴力破解攻击。近期活跃度较高，建议立即封禁。',\n"
            "            'geo_info': {'country': '中国', 'region': '境外', 'city': '未知', 'isp': '未知 ISP'},\n"
            "            'related_malware': ['Mirai', 'Emotet', 'Cobalt Strike'],\n"
            "            'attack_patterns': ['T1071 - 标准应用层协议(C2通信)', 'T1110 - 暴力破解', 'T1059 - 命令与脚本解释器'],\n"
            "        }\n"
            "    else:\n"
            "        return {\n"
            "            'ip': ip,\n"
            "            'is_malicious': False,\n"
            "            'tags': [],\n"
            "            'confidence': 0.0,\n"
            "            'threat_types': [],\n"
            "            'severity': 'low',\n"
            "            'first_seen': None,\n"
            "            'last_seen': None,\n"
            "            'source': '内部威胁情报平台',\n"
            "            'description': f'该 IP {ip} 属于内网白名单网段，未发现威胁记录。',\n"
            "            'geo_info': {'country': '中国', 'region': '内网', 'city': '本地网络', 'isp': '内部网络'},\n"
            "            'related_malware': [],\n"
            "            'attack_patterns': [],\n"
            "        }\n"
        ),
        "tool_type": "code",
        "category": "security",
        "enabled": True,
    },
    {
        "name": "check_subnet",
        "description": "查询 IP 所在子网信息（/24 网段 + 网关地址）",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待查询的 IP 地址"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    try:\n"
            "        network = ipaddress.ip_network(f'{ip}/24', strict=False)\n"
            "        network_segment = str(network)\n"
            "        gateway = str(network.network_address + 1)\n"
            "    except ValueError:\n"
            "        network_segment = 'unknown'\n"
            "        gateway = 'unknown'\n"
            "    return {\n"
            "        'ip': ip,\n"
            "        'network_segment': network_segment,\n"
            "        'gateway': gateway,\n"
            "    }\n"
        ),
        "tool_type": "code",
        "category": "security",
        "enabled": True,
    },
    {
        "name": "block_ip_on_firewall",
        "description": "在防火墙上下发 IP 封禁规则（幂等：重复封禁同一 IP 不会重复下发）",
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待封禁的 IP 地址"},
            {"name": "duration", "type": "String", "required": False, "description": "封禁时长（如 24h / 1h），默认 24h"},
            {"name": "reason", "type": "String", "required": False, "description": "封禁原因说明，默认 'auto block by SOAR'"},
        ],
        # 调用 tool_runner 注入的 block_ip_on_firewall（来自 app.devices.firewall）。
        # 沙箱无 __import__，不能在工具代码内 import；函数已注入命名空间，直接调用即可。
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip', '')\n"
            "    duration = kwargs.get('duration', '24h')\n"
            "    reason = kwargs.get('reason', 'auto block by SOAR')\n"
            "    return await block_ip_on_firewall(ip, duration, reason)\n"
        ),
        "tool_type": "code",
        "category": "security",
        "enabled": True,
    },
    {
        "name": "read_document",
        "description": (
            "读取用户上传的文件内容（支持 Excel/xlsx、Word/docx、PDF、CSV、TXT、JSON、Markdown）。"
            "用户在对话中上传文件后，可调用此工具按文件名读取文件全部内容。"
            "传入 file_name 参数（用户上传时的原始文件名），返回文件文本或结构化数据。"
        ),
        "parameters_schema": [
            {"name": "file_name", "type": "String", "required": True, "description": "要读取的文件名（用户上传时的原始名，如 报表.xlsx）"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    file_name = kwargs.get('file_name') or ''\n"
            "    if not file_name:\n"
            "        return {'error': '请提供 file_name 参数（要读取的文件名）'}\n"
            "    return read_uploaded_file(file_name)\n"
        ),
        "tool_type": "code",
        "category": "file_operations",
        "enabled": True,
    },
    {
        "name": "read_xlsx",
        "description": (
            "读取用户上传的 Excel 文件（.xlsx/.xls），返回所有工作表的数据。"
            "传入 file_name 参数（用户上传时的原始文件名），返回 {sheets: {sheet_name: [[row], ...]}}。"
        ),
        "parameters_schema": [
            {"name": "file_name", "type": "String", "required": True, "description": "要读取的 Excel 文件名"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    file_name = kwargs.get('file_name') or ''\n"
            "    if not file_name:\n"
            "        return {'error': '请提供 file_name 参数'}\n"
            "    result = read_uploaded_file(file_name)\n"
            "    if 'error' in result:\n"
            "        return result\n"
            "    ft = result.get('file_type', '')\n"
            "    if ft not in ('xlsx', 'xls'):\n"
            "        return {'error': f'文件 {file_name} 不是 Excel 文件（类型: {ft}），请使用 read_docx 或 read_pdf'}\n"
            "    return {'file_name': result['file_name'], 'sheets': result.get('sheets', {})}\n"
        ),
        "tool_type": "code",
        "category": "file_operations",
        "enabled": True,
    },
    {
        "name": "read_docx",
        "description": (
            "读取用户上传的 Word 文档（.docx），返回所有段落文本。"
            "传入 file_name 参数（用户上传时的原始文件名），返回 {paragraphs: [...], content: '...'}。"
        ),
        "parameters_schema": [
            {"name": "file_name", "type": "String", "required": True, "description": "要读取的 Word 文件名"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    file_name = kwargs.get('file_name') or ''\n"
            "    if not file_name:\n"
            "        return {'error': '请提供 file_name 参数'}\n"
            "    result = read_uploaded_file(file_name)\n"
            "    if 'error' in result:\n"
            "        return result\n"
            "    ft = result.get('file_type', '')\n"
            "    if ft != 'docx':\n"
            "        return {'error': f'文件 {file_name} 不是 Word 文档（类型: {ft}）'}\n"
            "    return {'file_name': result['file_name'], 'paragraphs': result.get('paragraphs', []), 'content': result.get('content', '')}\n"
        ),
        "tool_type": "code",
        "category": "file_operations",
        "enabled": True,
    },
    {
        "name": "read_pdf",
        "description": (
            "读取用户上传的 PDF 文件，提取所有页面的文本内容。"
            "传入 file_name 参数（用户上传时的原始文件名），返回 {pages: [...], page_count: N, content: '...'}。"
        ),
        "parameters_schema": [
            {"name": "file_name", "type": "String", "required": True, "description": "要读取的 PDF 文件名"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    file_name = kwargs.get('file_name') or ''\n"
            "    if not file_name:\n"
            "        return {'error': '请提供 file_name 参数'}\n"
            "    result = read_uploaded_file(file_name)\n"
            "    if 'error' in result:\n"
            "        return result\n"
            "    ft = result.get('file_type', '')\n"
            "    if ft != 'pdf':\n"
            "        return {'error': f'文件 {file_name} 不是 PDF 文件（类型: {ft}）'}\n"
            "    return {'file_name': result['file_name'], 'pages': result.get('pages', []), 'page_count': result.get('page_count', 0), 'content': result.get('content', '')}\n"
        ),
        "tool_type": "code",
        "category": "file_operations",
        "enabled": True,
    },
    {
        "name": "save_memory",
        "description": (
            "将一条键值对信息保存到智能体长期记忆中，供后续对话或 recall_memory 工具检索。"
            "适用于记住用户偏好、任务上下文、中间结果等。"
        ),
        "parameters_schema": [
            {"name": "key", "type": "String", "required": True, "description": "记忆键名（如 user_preference_color）"},
            {"name": "value", "type": "String", "required": True, "description": "记忆值（要记住的内容）"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    key = kwargs.get('key') or ''\n"
            "    value = kwargs.get('value') or ''\n"
            "    if not key:\n"
            "        return {'error': '请提供 key 参数'}\n"
            "    return save_agent_memory(key, value)\n"
        ),
        "tool_type": "code",
        "category": "memory",
        "enabled": True,
    },
    {
        "name": "recall_memory",
        "description": (
            "从智能体长期记忆中检索之前保存的信息。传入 key 返回对应的值；"
            "不传 key 时列出所有已保存的记忆键。"
        ),
        "parameters_schema": [
            {"name": "key", "type": "String", "required": False, "description": "要检索的记忆键名（不传则列出所有键）"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    key = kwargs.get('key') or ''\n"
            "    return recall_agent_memory(key)\n"
        ),
        "tool_type": "code",
        "category": "memory",
        "enabled": True,
    },
    {
        "name": "query_banned_ip",
        "description": (
            "查询某个 IP 是否已被封禁，返回其封禁状态、等级、时长、过期时间、违规次数等。"
            "在封禁工作流中应先调用此工具判断是否已封禁，避免重复处置。"
            "数据来自 BannedIP 表（由 record_ban 工具写入，前端「已封禁 IP」页面展示）。"
        ),
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待查询的 IP 地址"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    if not ip:\n"
            "        return {'error': '请提供 ip 参数'}\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        record = db.query(BannedIP).filter(BannedIP.ip == ip).first()\n"
            "        if record is None:\n"
            "            return {'ip': ip, 'banned': False, 'message': '该 IP 未被封禁'}\n"
            "        # 自动检查是否过期：active 且已过 expired_at 视为 expired\n"
            "        # 北京时间（UTC+8）：数据库内统一存北京时间，与前端显示一致\n"
            "        now = datetime.utcnow() + timedelta(hours=8)\n"
            "        is_active = record.status == 'active' and record.expired_at > now\n"
            "        if record.status == 'active' and record.expired_at <= now:\n"
            "            record.status = 'expired'\n"
            "            db.commit()\n"
            "        return {\n"
            "            'ip': ip,\n"
            "            'banned': is_active,\n"
            "            'ban_level': record.ban_level,\n"
            "            'ban_duration': record.ban_duration,\n"
            "            'expired_at': record.expired_at.isoformat() if record.expired_at else None,\n"
            "            'region': record.region,\n"
            "            'violation_count': record.violation_count,\n"
            "            'reason': record.reason,\n"
            "            'status': record.status,\n"
            "            'created_at': record.created_at.isoformat() if record.created_at else None,\n"
            "        }\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "tool_type": "code",
        "category": "security",
        "enabled": True,
    },
    {
        "name": "calculate_ban_duration",
        "description": (
            "依据地域（深圳/国内非深圳/境外）与违规次数，按规则矩阵计算封禁等级与时长。"
            "规则：深圳[首次3天/二次7天/三次30天]；国内非深圳[首次7天/二次30天/三次365天]；"
            "境外[首次30天/二次365天/三次永久]。确认为 C2服务器/勒索软件通信/APT攻击时直接永久封禁。"
            "返回等级、时长、是否永久、过期时间，供 record_ban 使用。"
        ),
        "parameters_schema": [
            {"name": "region", "type": "String", "required": True, "description": "IP 归属地（含'深圳'/'中国'/'境外'等关键字，用于地域分类）"},
            {"name": "violation_count", "type": "Number", "required": True, "description": "历史违规次数（0=首次，1=二次，≥2=三次及以上，来自 query_banned_ip）"},
            {"name": "tags", "type": "Array", "required": False, "description": "威胁情报标签列表（含 C2/勒索/APT 时触发永久封禁）"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    region = (kwargs.get('region') or '').strip()\n"
            "    violation_count = int(kwargs.get('violation_count') or 0)\n"
            "    raw_tags = kwargs.get('tags') or []\n"
            "    tags = [str(t).lower() for t in raw_tags] if isinstance(raw_tags, list) else [str(raw_tags).lower()]\n"
            "    DAY = 86400\n"
            "    # 地域分类：深圳 / 国内（非深圳）/ 境外\n"
            "    if '深圳' in region or 'shenzhen' in region.lower():\n"
            "        area = 'shenzhen'\n"
            "    elif '境外' in region or '海外' in region or '国外' in region or 'foreign' in region.lower() or 'overseas' in region.lower():\n"
            "        area = 'overseas'\n"
            "    elif '中国' in region or '国内' in region or 'china' in region.lower() or '北京' in region or '上海' in region or '广东' in region:\n"
            "        area = 'domestic'\n"
            "    else:\n"
            "        area = 'overseas'  # 无法判断地域时按境外从严\n"
            "    # 违规次数分级：0=首次, 1=二次, >=2=三次及以上\n"
            "    if violation_count <= 0:\n"
            "        offense = 1\n"
            "    elif violation_count == 1:\n"
            "        offense = 2\n"
            "    else:\n"
            "        offense = 3\n"
            "    # 封禁时长矩阵（秒）：[首次, 二次, 三次及以上]\n"
            "    MATRIX = {\n"
            "        'shenzhen': [3 * DAY, 7 * DAY, 30 * DAY],\n"
            "        'domestic': [7 * DAY, 30 * DAY, 365 * DAY],\n"
            "        'overseas': [30 * DAY, 365 * DAY, 0],\n"
            "    }\n"
            "    duration = MATRIX[area][offense - 1]\n"
            "    # 高危标签：C2 / 勒索 / APT → 永久（无论地域）\n"
            "    is_high_risk = any(('c2' in t or 'ransom' in t or 'apt' in t or '勒索' in t) for t in tags)\n"
            "    is_permanent = False\n"
            "    if is_high_risk:\n"
            "        is_permanent = True\n"
            "    elif area == 'overseas' and offense >= 3:\n"
            "        is_permanent = True\n"
            "    if is_permanent:\n"
            "        duration = 0\n"
            "        level = 'serious'\n"
            "        desc = '永久'\n"
            "        expired_at = '9999-12-31T23:59:59'\n"
            "    else:\n"
            "        expired_at = (datetime.utcnow() + timedelta(hours=8, seconds=duration)).isoformat()\n"
            "        if duration <= DAY:\n"
            "            level = 'low'\n"
            "        elif duration <= 7 * DAY:\n"
            "            level = 'medium'\n"
            "        elif duration <= 30 * DAY:\n"
            "            level = 'high'\n"
            "        else:\n"
            "            level = 'serious'\n"
            "        def _humanize(sec):\n"
            "            if sec >= DAY:\n"
            "                return f'{sec // DAY} 天'\n"
            "            if sec >= 3600:\n"
            "                return f'{sec // 3600} 小时'\n"
            "            return f'{sec // 60} 分钟'\n"
            "        desc = _humanize(duration)\n"
            "    return {\n"
            "        'ban_level': level,\n"
            "        'ban_duration': duration,\n"
            "        'is_permanent': is_permanent,\n"
            "        'ban_duration_desc': desc,\n"
            "        'expired_at': expired_at,\n"
            "        'area': area,\n"
            "        'offense': offense,\n"
            "        'violation_count': violation_count,\n"
            "    }\n"
        ),
        "tool_type": "code",
        "category": "security",
        "enabled": True,
    },
    {
        "name": "record_ban",
        "description": (
            "将封禁处置结果写入数据库（BannedIP 表）。若该 IP 已有记录则累加违规次数并更新封禁信息，"
            "否则新建记录。写入后可由 block_ip_on_firewall 工具执行实际封禁，前端「已封禁 IP」页面会展示该记录。"
        ),
        "parameters_schema": [
            {"name": "ip", "type": "String", "required": True, "description": "待封禁的 IP 地址"},
            {"name": "ban_level", "type": "String", "required": True, "description": "封禁等级：low/medium/high/serious（由 calculate_ban_duration 计算）"},
            {"name": "ban_duration", "type": "Number", "required": True, "description": "封禁时长（秒，永久封禁时传 0，由 calculate_ban_duration 计算）"},
            {"name": "is_permanent", "type": "Boolean", "required": False, "description": "是否永久封禁（由 calculate_ban_duration 判定，True 时忽略 ban_duration 并将过期时间设为 9999-12-31）"},
            {"name": "reason", "type": "String", "required": False, "description": "封禁原因说明"},
            {"name": "region", "type": "String", "required": False, "description": "IP 归属地区（可选）"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    ip = kwargs.get('ip') or ''\n"
            "    if not ip:\n"
            "        return {'error': '请提供 ip 参数'}\n"
            "    ban_level = kwargs.get('ban_level') or 'medium'\n"
            "    ban_duration = int(kwargs.get('ban_duration') or 0)\n"
            "    is_permanent = bool(kwargs.get('is_permanent', False))\n"
            "    reason = kwargs.get('reason') or ''\n"
            "    region = kwargs.get('region') or ''\n"
            "    # 计算过期时间：永久封禁用 9999-12-31，否则按 ban_duration 计算\n"
            "    if is_permanent or ban_duration <= 0:\n"
            "        expired_at = datetime(9999, 12, 31, 23, 59, 59)\n"
            "        ban_duration = 0\n"
            "        is_permanent = True\n"
            "    else:\n"
            "        expired_at = datetime.utcnow() + timedelta(hours=8, seconds=ban_duration)\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        existing = db.query(BannedIP).filter(BannedIP.ip == ip).first()\n"
            "        if existing:\n"
            "            # 已有记录：累加违规次数，更新封禁信息\n"
            "            existing.violation_count = (existing.violation_count or 0) + 1\n"
            "            existing.ban_level = ban_level\n"
            "            existing.ban_duration = ban_duration\n"
            "            existing.expired_at = expired_at\n"
            "            if region:\n"
            "                existing.region = region\n"
            "            existing.reason = reason\n"
            "            existing.status = 'active'\n"
            "            db.commit()\n"
            "            return {\n"
            "                'ok': True, 'ip': ip, 'action': 'updated',\n"
            "                'ban_level': ban_level, 'ban_duration': ban_duration,\n"
            "                'is_permanent': is_permanent,\n"
            "                'violation_count': existing.violation_count,\n"
            "            }\n"
            "        # 新记录\n"
            "        record = BannedIP(\n"
            "            ip=ip,\n"
            "            ban_level=ban_level,\n"
            "            ban_duration=ban_duration,\n"
            "            expired_at=expired_at,\n"
            "            region=region,\n"
            "            violation_count=1,\n"
            "            reason=reason,\n"
            "            status='active',\n"
            "        )\n"
            "        db.add(record)\n"
            "        db.commit()\n"
            "        return {\n"
            "            'ok': True, 'ip': ip, 'action': 'created',\n"
            "            'ban_level': ban_level, 'ban_duration': ban_duration,\n"
            "            'is_permanent': is_permanent,\n"
            "        }\n"
            "    except Exception as exc:\n"
            "        db.rollback()\n"
            "        return {'error': f'记录封禁失败: {exc}'}\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "tool_type": "code",
        "category": "security",
        "enabled": True,
    },
    # ===== 资产管理智能体专用工具（category='asset'） =====
    # 依赖沙箱注入：current_agent_id / Asset / SessionLocal / KnowledgeBase / KnowledgeSegment / enabled_kbs
    # 注意：沙箱禁止 import / setattr / getattr，故用直接属性赋值 + SQLAlchemy | 运算符构造 OR 条件
    {
        "name": "discover_new_kbs",
        "description": (
            "发现当前资产智能体已勾选但尚未梳理到资产表的知识库。"
            "用于智能体主动检查是否有新增知识库需要录入资产。"
            "返回 discovered 列表（每个元素含 kb_id/kb_name），count 为新发现的数量。"
        ),
        "parameters_schema": [],
        "code": (
            "async def run(**kwargs):\n"
            "    agent_id = current_agent_id\n"
            "    if not agent_id:\n"
            "        return {'error': '未找到当前智能体上下文（current_agent_id 为空），无法确定资产作用域'}\n"
            "    kb_ids = list(enabled_kbs or [])\n"
            "    if not kb_ids:\n"
            "        return {'discovered': [], 'count': 0, 'message': '当前智能体未勾选任何知识库，请先在智能体配置中勾选知识库'}\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        ingested_rows = db.query(Asset.kb_id).filter(\n"
            "            Asset.agent_id == agent_id,\n"
            "            Asset.kb_id.in_(kb_ids),\n"
            "        ).distinct().all()\n"
            "        ingested_kb_ids = set(r[0] for r in ingested_rows)\n"
            "        kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(kb_ids)).all()\n"
            "        kb_name_map = {kb.id: kb.name for kb in kbs}\n"
            "        new_kbs = []\n"
            "        for kb_id in kb_ids:\n"
            "            if kb_id not in ingested_kb_ids:\n"
            "                new_kbs.append({\n"
            "                    'kb_id': kb_id,\n"
            "                    'kb_name': kb_name_map.get(kb_id, '知识库-' + str(kb_id)),\n"
            "                })\n"
            "        return {\n"
            "            'agent_id': agent_id,\n"
            "            'enabled_kbs': kb_ids,\n"
            "            'ingested_kbs': sorted(ingested_kb_ids),\n"
            "            'discovered': new_kbs,\n"
            "            'count': len(new_kbs),\n"
            "            'message': '发现 ' + str(len(new_kbs)) + ' 个尚未梳理的知识库' if new_kbs else '所有勾选的知识库均已梳理到资产表',\n"
            "        }\n"
            "    except Exception as exc:\n"
            "        return {'error': '发现新知识库失败: ' + str(exc)}\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "tool_type": "code",
        "category": "asset",
        "enabled": True,
    },
    {
        "name": "fetch_kb_content",
        "description": (
            "拉取指定知识库的全部分段文本内容，供智能体梳理资产信息。"
            "返回 segments 列表（每个元素含 id/seq/content）。"
            "建议梳理流程：先 discover_new_kbs 发现新知识库，再用本工具拉取内容，"
            "然后逐段提取资产信息调用 add_asset 录入。"
        ),
        "parameters_schema": [
            {"name": "kb_id", "type": "Number", "required": True, "description": "知识库 ID"},
            {"name": "limit", "type": "Number", "required": False, "description": "最多拉取的分段数，默认 200，最大 500"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    kb_id = kwargs.get('kb_id')\n"
            "    if not kb_id:\n"
            "        return {'error': '请提供 kb_id 参数指定要拉取的知识库'}\n"
            "    kb_id = int(kb_id)\n"
            "    limit = int(kwargs.get('limit') or 200)\n"
            "    if limit < 1:\n"
            "        limit = 1\n"
            "    if limit > 500:\n"
            "        limit = 500\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()\n"
            "        if not kb:\n"
            "            return {'error': '知识库不存在: ' + str(kb_id)}\n"
            "        segs = db.query(KnowledgeSegment).filter(\n"
            "            KnowledgeSegment.kb_id == kb_id\n"
            "        ).order_by(KnowledgeSegment.id).limit(limit).all()\n"
            "        segments = []\n"
            "        for s in segs:\n"
            "            segments.append({\n"
            "                'id': s.id,\n"
            "                'seq': s.seq,\n"
            "                'content': s.content or '',\n"
            "            })\n"
            "        return {\n"
            "            'kb_id': kb_id,\n"
            "            'kb_name': kb.name,\n"
            "            'segment_count': len(segments),\n"
            "            'truncated': len(segs) >= limit,\n"
            "            'segments': segments,\n"
            "        }\n"
            "    except Exception as exc:\n"
            "        return {'error': '拉取知识库内容失败: ' + str(exc)}\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "tool_type": "code",
        "category": "asset",
        "enabled": True,
    },
    {
        "name": "query_asset",
        "description": (
            "查询当前资产智能体资产表中是否已存在某资产。"
            "支持按 identifier（唯一标识）/ ip / name / keyword（模糊匹配 identifier+name+ip+owner）查询。"
            "返回 found/count/assets 列表。用于对话录入资产前判断是新增还是更新。"
        ),
        "parameters_schema": [
            {"name": "identifier", "type": "String", "required": False, "description": "资产唯一标识（精确匹配，如 IP/主机名/工号）"},
            {"name": "ip", "type": "String", "required": False, "description": "按 IP 地址精确匹配"},
            {"name": "name", "type": "String", "required": False, "description": "按资产名称模糊匹配"},
            {"name": "keyword", "type": "String", "required": False, "description": "关键词模糊匹配 identifier/name/ip/owner"},
            {"name": "limit", "type": "Number", "required": False, "description": "返回上限，默认 20，最大 100"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    agent_id = current_agent_id\n"
            "    if not agent_id:\n"
            "        return {'error': '未找到当前智能体上下文'}\n"
            "    identifier = (kwargs.get('identifier') or '').strip()\n"
            "    ip = (kwargs.get('ip') or '').strip()\n"
            "    name = (kwargs.get('name') or '').strip()\n"
            "    keyword = (kwargs.get('keyword') or '').strip()\n"
            "    limit = int(kwargs.get('limit') or 20)\n"
            "    if limit < 1:\n"
            "        limit = 1\n"
            "    if limit > 100:\n"
            "        limit = 100\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        q = db.query(Asset).filter(Asset.agent_id == agent_id)\n"
            "        if identifier:\n"
            "            q = q.filter(Asset.identifier == identifier)\n"
            "        elif ip:\n"
            "            q = q.filter(Asset.ip == ip)\n"
            "        elif name:\n"
            "            q = q.filter(Asset.name.like('%' + name + '%'))\n"
            "        elif keyword:\n"
            "            q = q.filter(\n"
            "                Asset.identifier.like('%' + keyword + '%') |\n"
            "                Asset.name.like('%' + keyword + '%') |\n"
            "                Asset.ip.like('%' + keyword + '%') |\n"
            "                Asset.owner.like('%' + keyword + '%')\n"
            "            )\n"
            "        else:\n"
            "            return {'error': '请提供 identifier / ip / name / keyword 之一作为查询条件'}\n"
            "        rows = q.limit(limit).all()\n"
            "        assets = []\n"
            "        for a in rows:\n"
            "            assets.append({\n"
            "                'id': a.id, 'kb_id': a.kb_id, 'kb_name': a.kb_name,\n"
            "                'identifier': a.identifier, 'identifier_type': a.identifier_type,\n"
            "                'name': a.name, 'asset_type': a.asset_type, 'department': a.department,\n"
            "                'owner': a.owner, 'location': a.location, 'ip': a.ip,\n"
            "                'criticality': a.criticality, 'extra_fields': a.extra_fields or {},\n"
            "                'source': a.source, 'raw_content': a.raw_content or '',\n"
            "                'created_at': str(a.created_at) if a.created_at else '',\n"
            "                'updated_at': str(a.updated_at) if a.updated_at else '',\n"
            "            })\n"
            "        return {\n"
            "            'agent_id': agent_id,\n"
            "            'found': len(assets) > 0,\n"
            "            'count': len(assets),\n"
            "            'assets': assets,\n"
            "        }\n"
            "    except Exception as exc:\n"
            "        return {'error': '查询资产失败: ' + str(exc)}\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "tool_type": "code",
        "category": "asset",
        "enabled": True,
    },
    {
        "name": "add_asset",
        "description": (
            "向当前资产智能体的资产表新增一条资产记录。"
            "若 identifier 已存在则拒绝新增（返回 action=exists），提示改用 update_asset。"
            "extra_fields 接收 JSON 对象，存储知识库中特有但标准字段未覆盖的属性（灵活字段）。"
            "录入来源：对话录入用 source=agent_add，KB 梳理用 source=kb_ingest。"
        ),
        "parameters_schema": [
            {"name": "identifier", "type": "String", "required": True, "description": "资产唯一标识（IP/主机名/工号/资产编号等，由智能体判断）"},
            {"name": "identifier_type", "type": "String", "required": False, "description": "标识类型：ip/hostname/asset_name/employee_id/mac/custom，默认 custom"},
            {"name": "name", "type": "String", "required": False, "description": "资产名称（展示用）"},
            {"name": "asset_type", "type": "String", "required": False, "description": "资产类型：服务器/工作站/网络设备/应用/账号等"},
            {"name": "department", "type": "String", "required": False, "description": "归属部门"},
            {"name": "owner", "type": "String", "required": False, "description": "负责人"},
            {"name": "location", "type": "String", "required": False, "description": "物理位置"},
            {"name": "ip", "type": "String", "required": False, "description": "IP 地址"},
            {"name": "criticality", "type": "String", "required": False, "description": "重要性：low/medium/high/critical，默认 medium"},
            {"name": "kb_id", "type": "Number", "required": False, "description": "来源知识库 ID（对话录入可不传）"},
            {"name": "kb_name", "type": "String", "required": False, "description": "来源知识库名称"},
            {"name": "source", "type": "String", "required": False, "description": "来源：agent_add（对话录入）/ kb_ingest（KB 梳理）/ manual（手动），默认 agent_add"},
            {"name": "raw_content", "type": "String", "required": False, "description": "LLM 提取时的原始 KB 片段（溯源审计）"},
            {"name": "extra_fields", "type": "Object", "required": False, "description": "灵活字段（JSON 对象），存储标准字段未覆盖的属性"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    agent_id = current_agent_id\n"
            "    if not agent_id:\n"
            "        return {'error': '未找到当前智能体上下文'}\n"
            "    identifier = (kwargs.get('identifier') or '').strip()\n"
            "    if not identifier:\n"
            "        return {'error': '请提供 identifier 参数（资产唯一标识，如 IP/主机名/工号/资产编号）'}\n"
            "    identifier_type = (kwargs.get('identifier_type') or 'custom').strip()\n"
            "    extra = kwargs.get('extra_fields')\n"
            "    if not isinstance(extra, dict):\n"
            "        extra = {}\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        existing = db.query(Asset).filter(\n"
            "            Asset.agent_id == agent_id,\n"
            "            Asset.identifier == identifier,\n"
            "        ).first()\n"
            "        if existing:\n"
            "            return {\n"
            "                'ok': False,\n"
            "                'action': 'exists',\n"
            "                'message': '资产已存在（identifier=' + identifier + '，id=' + str(existing.id) + '），如需修改请改用 update_asset 工具',\n"
            "                'existing_id': existing.id,\n"
            "            }\n"
            "        record = Asset(\n"
            "            agent_id=agent_id,\n"
            "            identifier=identifier,\n"
            "            identifier_type=identifier_type,\n"
            "            kb_id=int(kwargs.get('kb_id') or 0),\n"
            "            kb_name=(kwargs.get('kb_name') or '').strip(),\n"
            "            name=(kwargs.get('name') or '').strip(),\n"
            "            asset_type=(kwargs.get('asset_type') or '').strip(),\n"
            "            department=(kwargs.get('department') or '').strip(),\n"
            "            owner=(kwargs.get('owner') or '').strip(),\n"
            "            location=(kwargs.get('location') or '').strip(),\n"
            "            ip=(kwargs.get('ip') or '').strip(),\n"
            "            criticality=(kwargs.get('criticality') or 'medium').strip(),\n"
            "            source=(kwargs.get('source') or 'agent_add').strip(),\n"
            "            raw_content=kwargs.get('raw_content') or '',\n"
            "            extra_fields=extra,\n"
            "        )\n"
            "        db.add(record)\n"
            "        db.commit()\n"
            "        db.refresh(record)\n"
            "        return {\n"
            "            'ok': True,\n"
            "            'action': 'created',\n"
            "            'asset_id': record.id,\n"
            "            'identifier': identifier,\n"
            "            'message': '资产已新增: ' + identifier,\n"
            "        }\n"
            "    except Exception as exc:\n"
            "        db.rollback()\n"
            "        return {'error': '新增资产失败: ' + str(exc)}\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "tool_type": "code",
        "category": "asset",
        "enabled": True,
    },
    {
        "name": "update_asset",
        "description": (
            "更新当前资产智能体资产表中已存在的资产记录（按 identifier 定位）。"
            "若 identifier 不存在则返回 action=not_found，提示改用 add_asset。"
            "extra_fields 传入的键值会与已有 extra_fields 合并（不覆盖整个对象）。"
            "仅更新传入的非空字段，未传字段保持不变。"
        ),
        "parameters_schema": [
            {"name": "identifier", "type": "String", "required": True, "description": "要更新的资产唯一标识（定位记录）"},
            {"name": "name", "type": "String", "required": False, "description": "资产名称"},
            {"name": "asset_type", "type": "String", "required": False, "description": "资产类型"},
            {"name": "department", "type": "String", "required": False, "description": "归属部门"},
            {"name": "owner", "type": "String", "required": False, "description": "负责人"},
            {"name": "location", "type": "String", "required": False, "description": "物理位置"},
            {"name": "ip", "type": "String", "required": False, "description": "IP 地址"},
            {"name": "criticality", "type": "String", "required": False, "description": "重要性：low/medium/high/critical"},
            {"name": "identifier_type", "type": "String", "required": False, "description": "标识类型"},
            {"name": "kb_id", "type": "Number", "required": False, "description": "来源知识库 ID"},
            {"name": "kb_name", "type": "String", "required": False, "description": "来源知识库名称"},
            {"name": "raw_content", "type": "String", "required": False, "description": "原始 KB 片段"},
            {"name": "extra_fields", "type": "Object", "required": False, "description": "灵活字段（JSON 对象），与已有 extra_fields 合并"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    agent_id = current_agent_id\n"
            "    if not agent_id:\n"
            "        return {'error': '未找到当前智能体上下文'}\n"
            "    identifier = (kwargs.get('identifier') or '').strip()\n"
            "    if not identifier:\n"
            "        return {'error': '请提供 identifier 参数定位要更新的资产'}\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        record = db.query(Asset).filter(\n"
            "            Asset.agent_id == agent_id,\n"
            "            Asset.identifier == identifier,\n"
            "        ).first()\n"
            "        if not record:\n"
            "            return {\n"
            "                'ok': False,\n"
            "                'action': 'not_found',\n"
            "                'message': '未找到资产（identifier=' + identifier + '），如需新建请改用 add_asset 工具',\n"
            "            }\n"
            "        changed = []\n"
            "        v = kwargs.get('name')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.name = v; changed.append('name')\n"
            "        v = kwargs.get('asset_type')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.asset_type = v; changed.append('asset_type')\n"
            "        v = kwargs.get('department')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.department = v; changed.append('department')\n"
            "        v = kwargs.get('owner')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.owner = v; changed.append('owner')\n"
            "        v = kwargs.get('location')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.location = v; changed.append('location')\n"
            "        v = kwargs.get('ip')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.ip = v; changed.append('ip')\n"
            "        v = kwargs.get('criticality')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.criticality = v; changed.append('criticality')\n"
            "        v = kwargs.get('identifier_type')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.identifier_type = v; changed.append('identifier_type')\n"
            "        v = kwargs.get('kb_name')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.kb_name = v; changed.append('kb_name')\n"
            "        v = kwargs.get('kb_id')\n"
            "        if v is not None and v:\n"
            "            record.kb_id = int(v); changed.append('kb_id')\n"
            "        v = kwargs.get('raw_content')\n"
            "        if v is not None and str(v).strip():\n"
            "            record.raw_content = v; changed.append('raw_content')\n"
            "        extra = kwargs.get('extra_fields')\n"
            "        if extra and isinstance(extra, dict):\n"
            "            cur = dict(record.extra_fields or {})\n"
            "            cur.update(extra)\n"
            "            record.extra_fields = cur\n"
            "            changed.append('extra_fields')\n"
            "        db.commit()\n"
            "        db.refresh(record)\n"
            "        msg = '资产已更新: ' + identifier\n"
            "        if changed:\n"
            "            msg = msg + '（变更字段: ' + ', '.join(changed) + '）'\n"
            "        return {\n"
            "            'ok': True,\n"
            "            'action': 'updated',\n"
            "            'asset_id': record.id,\n"
            "            'identifier': identifier,\n"
            "            'changed_fields': changed,\n"
            "            'message': msg,\n"
            "        }\n"
            "    except Exception as exc:\n"
            "        db.rollback()\n"
            "        return {'error': '更新资产失败: ' + str(exc)}\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "tool_type": "code",
        "category": "asset",
        "enabled": True,
    },
    {
        "name": "list_assets",
        "description": (
            "列出当前资产智能体的全部资产（分页+筛选）。"
            "支持按 kb_id / asset_type / department / criticality 精确筛选，"
            "以及 keyword 模糊匹配 identifier/name/ip/owner。"
            "返回 total/count/assets 列表，按 id 倒序排列。"
        ),
        "parameters_schema": [
            {"name": "keyword", "type": "String", "required": False, "description": "模糊匹配关键词（identifier/name/ip/owner）"},
            {"name": "kb_id", "type": "Number", "required": False, "description": "按来源知识库筛选"},
            {"name": "asset_type", "type": "String", "required": False, "description": "按资产类型筛选"},
            {"name": "department", "type": "String", "required": False, "description": "按部门筛选"},
            {"name": "criticality", "type": "String", "required": False, "description": "按重要性筛选：low/medium/high/critical"},
            {"name": "page", "type": "Number", "required": False, "description": "页码，默认 1"},
            {"name": "page_size", "type": "Number", "required": False, "description": "每页条数，默认 20，最大 100"},
        ],
        "code": (
            "async def run(**kwargs):\n"
            "    agent_id = current_agent_id\n"
            "    if not agent_id:\n"
            "        return {'error': '未找到当前智能体上下文'}\n"
            "    keyword = (kwargs.get('keyword') or '').strip()\n"
            "    kb_id = kwargs.get('kb_id')\n"
            "    asset_type = (kwargs.get('asset_type') or '').strip()\n"
            "    department = (kwargs.get('department') or '').strip()\n"
            "    criticality = (kwargs.get('criticality') or '').strip()\n"
            "    page = int(kwargs.get('page') or 1)\n"
            "    if page < 1:\n"
            "        page = 1\n"
            "    page_size = int(kwargs.get('page_size') or 20)\n"
            "    if page_size < 1:\n"
            "        page_size = 1\n"
            "    if page_size > 100:\n"
            "        page_size = 100\n"
            "    db = SessionLocal()\n"
            "    try:\n"
            "        q = db.query(Asset).filter(Asset.agent_id == agent_id)\n"
            "        if kb_id:\n"
            "            q = q.filter(Asset.kb_id == int(kb_id))\n"
            "        if asset_type:\n"
            "            q = q.filter(Asset.asset_type == asset_type)\n"
            "        if department:\n"
            "            q = q.filter(Asset.department == department)\n"
            "        if criticality:\n"
            "            q = q.filter(Asset.criticality == criticality)\n"
            "        if keyword:\n"
            "            like = '%' + keyword + '%'\n"
            "            q = q.filter(\n"
            "                Asset.identifier.like(like) |\n"
            "                Asset.name.like(like) |\n"
            "                Asset.ip.like(like) |\n"
            "                Asset.owner.like(like)\n"
            "            )\n"
            "        total = q.count()\n"
            "        rows = q.order_by(Asset.id.desc()).offset((page - 1) * page_size).limit(page_size).all()\n"
            "        assets = []\n"
            "        for a in rows:\n"
            "            assets.append({\n"
            "                'id': a.id, 'kb_id': a.kb_id, 'kb_name': a.kb_name,\n"
            "                'identifier': a.identifier, 'identifier_type': a.identifier_type,\n"
            "                'name': a.name, 'asset_type': a.asset_type, 'department': a.department,\n"
            "                'owner': a.owner, 'location': a.location, 'ip': a.ip,\n"
            "                'criticality': a.criticality, 'extra_fields': a.extra_fields or {},\n"
            "                'source': a.source, 'raw_content': a.raw_content or '',\n"
            "                'created_at': str(a.created_at) if a.created_at else '',\n"
            "                'updated_at': str(a.updated_at) if a.updated_at else '',\n"
            "            })\n"
            "        return {\n"
            "            'agent_id': agent_id,\n"
            "            'page': page,\n"
            "            'page_size': page_size,\n"
            "            'total': total,\n"
            "            'count': len(assets),\n"
            "            'assets': assets,\n"
            "        }\n"
            "    except Exception as exc:\n"
            "        return {'error': '列出资产失败: ' + str(exc)}\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "tool_type": "code",
        "category": "asset",
        "enabled": True,
    },
]


# ============================================================================
# 资产管理智能体推荐系统提示词
#
# 用户创建资产管理智能体时可复制此模板作为 system_prompt。
# 该提示词定义了资产梳理流程（KB→资产表）、对话录入判断逻辑、
# 字段灵活性策略（标准字段 + extra_fields），以及去重约束。
# 前端「创建智能体」页面可在 category=asset 时自动预填此模板（待实现）。
# ============================================================================
ASSET_AGENT_SYSTEM_PROMPT: str = """你是一个资产管理智能体，负责根据勾选的知识库梳理资产信息、维护资产表，并响应用户的资产录入/查询/更新需求。

## 核心工具

1. **discover_new_kbs** —— 发现已勾选但尚未梳理到资产表的新增知识库
2. **fetch_kb_content** —— 拉取指定知识库的全部分段内容
3. **query_asset** —— 查询资产表中是否已存在某资产（按 identifier/ip/name/keyword）
4. **add_asset** —— 新增资产记录（identifier 已存在时会被拒绝）
5. **update_asset** —— 更新已有资产记录（按 identifier 定位，extra_fields 合并）
6. **list_assets** —— 分页列出资产（支持筛选和关键词搜索）

## 资产梳理流程（知识库 → 资产表）

当被要求梳理资产、或主动发现新知识库时，按以下步骤操作：
1. 调用 discover_new_kbs 检查是否有尚未梳理的知识库
2. 对每个新知识库，调用 fetch_kb_content 拉取全部分段内容
3. 逐段分析内容，提取资产信息：
   - 判断每条资产的唯一标识（identifier）：优先用 IP/主机名/工号/资产编号
   - 判断 identifier_type：ip/hostname/asset_name/employee_id/mac/custom
   - 提取标准字段（name/asset_type/department/owner/location/ip/criticality）
   - 知识库中特有但标准字段未覆盖的属性，放入 extra_fields（JSON 对象）
4. 对每条提取到的资产，先调用 query_asset 检查是否已存在：
   - 不存在 → 调用 add_asset 新增（source=kb_ingest）
   - 已存在 → 调用 update_asset 更新（合并新信息到已有记录）

## 对话录入资产

当用户在对话中提供新的资产信息时：
1. 从用户消息中提取资产标识（IP/主机名/名称等）
2. 调用 query_asset 检查该资产是否已存在
3. 不存在 → add_asset 新增（source=agent_add）
4. 已存在 → 向用户确认后 update_asset 更新

## 字段灵活性

不同知识库的资产字段可能不同：
- 标准字段（name/asset_type/department/owner/location/ip/criticality）直接填入对应参数
- 非标准字段统一放入 extra_fields（如 {"序列号": "SN001", "购入日期": "2024-01-01"}）
- 你需要根据知识库内容灵活判断哪些字段是标准字段、哪些放入 extra_fields

## 重要约束

- 每条资产必须有 identifier（唯一标识），用于去重
- 不要重复录入同一资产：录入前务必先 query_asset 检查
- 资产梳理是增量操作：只处理新知识库，已梳理的不要重复处理
- 返回结果要简洁清晰，用表格/列表形式展示资产信息
"""


# ============================================================================
# Hermes 引擎框架级工具（tool_type='framework'）
#
# 仅存储 schema（name/description/parameters_schema），无 code 字段。
# 执行逻辑在 executor.py 的 _react_loop 中拦截，走专属处理方法：
#   - trigger_workflow_skill → _handle_skill_call → skill_engine.trigger_skill
#   - list_workflow_skills → 直接返回 skill_engine.list_workflow_skills()
#   - delegate_task → _handle_delegate_call → delegator.delegate()
#   - clarify → 需 callback 机制（待完善）
#
# parameters_schema 存储 OpenAI parameters 对象（非数组格式），
# executor 直接包装为 {"type":"function","function":{...}} 注入 extra_tool_defs。
# ============================================================================
HERMES_FRAMEWORK_TOOLS: list[dict[str, Any]] = [
    {
        "name": "trigger_workflow_skill",
        "description": (
            "触发一个已配置的工作流作为复杂技能。适用于需要多步骤编排、"
            "人工审批、设备操作的场景。先调用 list_workflow_skills 获取可用技能。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "integer", "description": "工作流 ID"},
                "input": {"type": "object", "description": "技能输入参数", "additionalProperties": True},
                "resume_token": {"type": "string", "description": "恢复令牌（恢复被中断的技能时传入）"},
            },
            "required": ["workflow_id"],
        },
        "tool_type": "framework",
        "category": "task_delegation",
        "code": None,
        "enabled": True,
    },
    {
        "name": "list_workflow_skills",
        "description": "列出所有可作为技能触发的工作流（返回 id/name/description）。",
        "parameters_schema": {"type": "object", "properties": {}},
        "tool_type": "framework",
        "category": "task_delegation",
        "code": None,
        "enabled": True,
    },
    {
        "name": "delegate_task",
        "description": (
            "委派一个或多个子代理在隔离上下文中执行任务。"
            "子代理拥有独立的对话历史（看不到父代理历史）、继承的工具集（剥离部分工具）、"
            "独立的迭代预算。"
            "适用于：并行调研多个方向、把重复性子任务交给子代理、保持父上下文简洁。"
            "\n\n单任务：提供 goal（+可选 context）。"
            "批量：提供 tasks 数组 [{goal, context}, ...]（并行执行，汇总结果）。"
            "完成后返回汇总结果，父代理可继续推理。"
            "\n\n注意：子代理看不到你的对话历史，goal 必须 self-contained。"
            "子代理不能委派其他子代理（delegate_task 对子代理不可用）。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "子代理要完成的目标。必须具体且 self-contained——子代理对你的对话历史一无所知。",
                },
                "context": {
                    "type": "string",
                    "description": "子代理需要的背景信息：文件路径、错误消息、项目结构、约束。越具体，子代理表现越好。",
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "任务目标"},
                            "context": {"type": "string", "description": "任务特定背景"},
                        },
                        "required": ["goal"],
                    },
                    "description": "批量任务数组。提供时忽略顶层 goal/context，每个任务独立执行后汇总。",
                },
            },
            "required": [],
        },
        "tool_type": "framework",
        "category": "task_delegation",
        "code": None,
        "enabled": True,
    },
    {
        "name": "clarify",
        "description": (
            "当你需要澄清、反馈或决策时向用户提问。支持两种模式：\n\n"
            "1. **多选** —— 提供最多 4 个选项，用户选一个或输入'其他'。\n"
            "2. **开放式** —— 不提供选项，用户自由文本回答。\n\n"
            "关键：提供选项时，每个选项只放 ``choices`` 数组，绝不把选项写进 ``question`` 文本。"
            "UI 会渲染 choices 为可选项；写进 question 的选项会变成死文本。\n\n"
            "正确: question='封禁多长时间？', choices=['1小时', '24小时', '永久']\n"
            "错误: question='封禁多长时间？1) 1小时 2) 24小时', choices=[]\n\n"
            "使用场景：\n"
            "- 告警信息不全（IP 为空、设备未指定）\n"
            "- 设备操作目标不明确（多台设备匹配）\n"
            "- 处置策略与告警严重程度不匹配\n"
            "- 决策有重大权衡，需用户参与\n\n"
            "不要用于危险命令的简单 yes/no 确认（写工具的 verification 机制处理）。"
            "低风险决策应自行做合理默认选择。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "问题本身，且只有问题（如 '封禁多长时间？'）。不要把答案选项嵌入这里。",
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 4,
                    "description": "提供可选项时必填：每个选项是数组的一个元素（最多 4 个）。",
                },
            },
            "required": ["question"],
        },
        "tool_type": "framework",
        "category": "clarifying_question",
        "code": None,
        "enabled": True,
    },
    {
        "name": "plan",
        "description": (
            "创建结构化的任务执行计划。当任务复杂、需要多步骤编排时调用此工具，"
            "将任务分解为有序步骤并明确每步的目标和依赖关系。"
            "计划生成后可作为后续执行的蓝图，也便于用户审阅和调整。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "任务的最终目标",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "description": "步骤动作描述"},
                            "tool": {"type": "string", "description": "该步骤使用的工具名（可选）"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "依赖的前置步骤序号",
                            },
                        },
                        "required": ["action"],
                    },
                    "description": "有序步骤列表",
                },
            },
            "required": ["goal", "steps"],
        },
        "tool_type": "framework",
        "category": "task_planning",
        "code": None,
        "enabled": True,
    },
    {
        "name": "schedule_cron",
        "description": (
            "调度一个定时（cron）任务，按指定时间规则周期性执行工作流或动作。"
            "适用于定期巡检、定时报表、周期性扫描等场景。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "定时任务名称"},
                "cron_expr": {
                    "type": "string",
                    "description": "Cron 表达式（如 '0 2 * * *' 表示每天凌晨 2 点）",
                },
                "workflow_id": {"type": "integer", "description": "要触发的工作流 ID"},
                "input": {"type": "object", "description": "传给工作流的输入参数", "additionalProperties": True},
            },
            "required": ["name", "cron_expr", "workflow_id"],
        },
        "tool_type": "framework",
        "category": "cron_jobs",
        "code": None,
        "enabled": True,
    },
    {
        "name": "computer_use",
        "description": (
            "执行计算机操作（如运行命令、操作文件系统、打开浏览器等）。"
            "适用于需要与操作系统或桌面环境交互的自动化场景。"
            "注意：此工具在沙箱中执行，受安全策略限制。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "要执行的操作类型：run_command / read_file / write_file / list_dir / open_url",
                },
                "target": {
                    "type": "string",
                    "description": "操作目标（命令、文件路径、URL 等）",
                },
                "args": {
                    "type": "object",
                    "description": "附加参数",
                    "additionalProperties": True,
                },
            },
            "required": ["action", "target"],
        },
        "tool_type": "framework",
        "category": "computer_use",
        "code": None,
        "enabled": True,
    },
]

# 示例工作流：暴力破解自动封禁（含人工审批分支）
SAMPLE_WORKFLOW: dict[str, Any] = {
    "name": "【示例】暴力破解自动处置（含人工审批）",
    "graph_config": {
        "nodes": [
            {
                "id": "webhook_1",
                "type": "webhook_trigger",
                "data": {
                    "method": "POST",
                    "content_type": "application/json",
                    "query_params": [],
                    "header_params": [],
                    "body_params": [
                        {"name": "src_ip", "type": "String", "required": True},
                        {"name": "dest_ip", "type": "String", "required": True},
                        {"name": "alert_type", "type": "String", "required": True},
                        {"name": "count", "type": "Number", "required": False},
                    ],
                    "response_status": 200,
                    "response_body": '{"status": "received"}',
                },
            },
            {
                "id": "agent_1",
                "type": "ai_agent",
                "data": {
                    "model": "claude-3-5-sonnet",
                    "temperature": 0.3,
                    "max_tokens": 1024,
                    "max_iterations": 5,
                    "system_prompt": "你是一名 SOC 高级安全专家。接收到告警后，请利用工具查询源 IP 的白名单状态、资产归属、网段和威胁情报，综合判断是否需要封禁。",
                    "user_prompt": "告警数据：{{alert_data}}，请分析并给出处置建议。",
                    "enabled_tools": ["check_whitelist", "query_asset_info", "query_threat_intel", "query_ip_geo"],
                },
            },
            {
                "id": "cond_1",
                "type": "condition_branch",
                "data": {
                    "mode": "if_else",
                    "conditions": [{"variable": "decision", "operator": "==", "value": "need_human_approval"}],
                    "logic": "AND",
                    "true_label": "true",
                    "false_label": "false",
                },
            },
            {
                "id": "hr_1",
                "type": "human_review",
                "data": {
                    "title": "暴力破解封禁审批",
                    "description": "Agent 无法确定是否封禁，需人工审核",
                    "instructions": "请基于告警信息与 Agent 推理结果，判断是否需要封禁源 IP。点击「同意封禁」将继续执行下游封禁节点；点击「忽略」将终止工作流。",
                },
            },
            {
                "id": "block_1",
                "type": "block_ip",
                "data": {"action": "block", "target_ip": "{{agent_decision.target_ip}}", "value": 24, "unit": "h"},
            },
            {
                "id": "notify_1",
                "type": "send_notification",
                "data": {
                    "channel": "email",
                    "severity": "critical",
                    "subject": "【SOAR】已封禁恶意 IP {{agent_decision.target_ip}}",
                    "body": "检测到来自 {{payload.src_ip}} 的攻击行为，已自动封禁。\n处置建议：{{agent_decision.reason}}",
                    "recipients": "soc-team@example.com",
                },
            },
            {
                "id": "end_1",
                "type": "end",
                "data": {"end_type": "success"},
            },
        ],
        "edges": [
            {"source": "webhook_1", "target": "agent_1"},
            {"source": "agent_1", "target": "cond_1"},
            {"source": "cond_1", "target": "hr_1", "sourceHandle": "true"},
            {"source": "cond_1", "target": "block_1", "sourceHandle": "false"},
            {"source": "hr_1", "target": "block_1"},
            {"source": "block_1", "target": "notify_1"},
            {"source": "notify_1", "target": "end_1"},
        ],
    },
}


def _code_has_imports(code: str) -> bool:
    """检测工具代码是否含 import 语句（AST 解析）。

    沙箱通过 ``build_safe_builtins`` 移除了 ``__import__``，运行时任何
    ``import`` / ``from ... import`` 都会失败。本函数用于「代码修复」：
    若已存在的 seed 工具代码含 import，用 seed 版本覆盖。

    Args:
        code: 工具源码字符串。

    Returns:
        True 表示代码含 import 语句（或语法错误无法解析），需要修复。
    """
    if not code or not code.strip():
        return True  # 空代码也需要修复
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return True  # 语法错误，需修复
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return True
    return False


def ensure_hermes_tools() -> None:
    """幂等插入 Hermes 内置工具和框架级工具，并修复含 import 的破损代码。

    每次启动都执行（不限于表空时），按 name 查询后插入缺失的工具。
    已存在的工具不会被覆盖（保留用户可能做的修改），但会：

    1. 同步 category 字段（仅当 category 为 NULL 时填充）。
    2. **代码修复**：若已存在的 code 工具代码含 import 语句（沙箱无
       ``__import__``，运行时必失败），自动用 seed 版本覆盖。这仅修复
       确定无法运行的代码，不影响用户对无 import 代码的自定义修改。

    涵盖：
    - HERMES_BUILTIN_TOOLS: code 类型工具（check_whitelist / read_document / read_xlsx 等）
    - HERMES_FRAMEWORK_TOOLS: framework 类型工具（delegate_task / clarify / plan 等）

    注意：``tools.category`` 列由 ``security.run_lightweight_migrations`` 集中添加，
    不在此处做 DDL 操作（避免散布的 ALTER TABLE 引发多实例竞态）。
    """
    # 构建 seed code 映射：name → seed 代码（仅 code 类型工具，用于修复破损代码）
    seed_code_map: dict[str, str] = {
        t["name"]: t["code"]
        for t in HERMES_BUILTIN_TOOLS
        if t.get("tool_type", "code") != "framework" and t.get("code")
    }

    db: Session = SessionLocal()
    try:
        all_hermes = HERMES_BUILTIN_TOOLS + HERMES_FRAMEWORK_TOOLS
        inserted = 0
        categorized = 0
        repaired = 0
        for t in all_hermes:
            existing = db.query(Tool).filter(Tool.name == t["name"]).first()
            if existing is not None:
                # 同步 category（仅当为 NULL 时填充）
                if existing.category is None and t.get("category"):
                    existing.category = t["category"]
                    categorized += 1
                # 代码修复：若已存在 code 工具含 import 语句，用 seed 版本覆盖。
                # 仅对 code 类型工具生效（http 工具按设计 code 字段为空，不参与修复；
                # framework 工具无 code 字段）。仅当代码确实含 import（确定无法运行）时触发，
                # 不覆盖用户对无 import 代码的自定义修改。
                seed_code = seed_code_map.get(t["name"])
                if (
                    seed_code
                    and (existing.tool_type or "code").lower() == "code"
                    and existing.code != seed_code
                    and _code_has_imports(existing.code)
                ):
                    logger.warning(
                        "工具 %s 代码含 import 语句（沙箱禁止），自动修复为 seed 版本",
                        t["name"],
                    )
                    existing.code = seed_code
                    repaired += 1
                continue  # 不覆盖已有工具的其他字段
            db.add(Tool(**t))
            inserted += 1
        if inserted > 0 or categorized > 0 or repaired > 0:
            db.commit()
            logger.info(
                "Hermes 工具迁移: 新插入 %d 个，补充分类 %d 个，代码修复 %d 个（共 %d 个定义）",
                inserted, categorized, repaired, len(all_hermes),
            )
        else:
            logger.debug("Hermes 工具迁移: 全部 %d 个工具已存在且无需修复", len(all_hermes))
    except Exception as e:  # noqa: BLE001
        logger.exception("Hermes 工具迁移失败: %s", e)
        db.rollback()
    finally:
        db.close()


def ensure_seed_data() -> None:
    """确保关键表有兜底数据；仅当表为空时种入，不覆盖用户数据。"""
    db: Session = SessionLocal()
    try:
        # 1. 工具表为空 → 种入默认工具
        tool_count = db.query(Tool).count()
        if tool_count == 0:
            logger.info("Tools 表为空，种入 %d 个默认工具", len(DEFAULT_TOOLS))
            for t in DEFAULT_TOOLS:
                db.add(Tool(**t))
            db.commit()
            logger.info("默认工具种入完成")
        else:
            logger.info("Tools 表已有 %d 条数据，跳过 seed", tool_count)

        # 2. 工作流表为空 → 种入示例工作流
        wf_count = db.query(Workflow).count()
        if wf_count == 0:
            logger.info("Workflows 表为空，种入示例工作流")
            db.add(Workflow(**SAMPLE_WORKFLOW))
            db.commit()
            logger.info("示例工作流种入完成")
        else:
            logger.info("Workflows 表已有 %d 条数据，跳过 seed", wf_count)
    except Exception as e:  # noqa: BLE001
        logger.exception("Seed 数据初始化失败: %s", e)
        db.rollback()
    finally:
        db.close()

    # 3. Hermes 工具迁移（每次启动幂等执行，插入缺失的内置/框架级工具）
    ensure_hermes_tools()

    # 4. 内置技能种子（幂等：按 name 查询，不存在才插入）
    ensure_builtin_skills()


# ============================================================================
# 内置技能种子数据
# 将资产管理智能体提示词作为 Skill 注入，用户可在「技能」页面直接选用
# ============================================================================
BUILTIN_SKILLS: list[dict[str, Any]] = [
    {
        "name": "资产管理智能体提示词",
        "description": "资产管理智能体的系统提示词模板，定义资产梳理、录入、更新流程和字段灵活性规则",
        "content": ASSET_AGENT_SYSTEM_PROMPT,
        "category": "角色设定",
        "tags": ["资产管理", "智能体", "提示词模板"],
        "enabled": True,
        "priority": 10,
    },
]


def ensure_builtin_skills() -> None:
    """幂等插入内置技能：按 name 查询，不存在才插入，不覆盖用户编辑。"""
    db: Session = SessionLocal()
    try:
        for sk_data in BUILTIN_SKILLS:
            existing = db.query(Skill).filter(Skill.name == sk_data["name"]).first()
            if existing:
                logger.debug("技能「%s」已存在，跳过 seed", sk_data["name"])
                continue
            db.add(Skill(**sk_data))
            logger.info("种入内置技能「%s」", sk_data["name"])
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("内置技能 seed 失败: %s", e)
        db.rollback()
    finally:
        db.close()
