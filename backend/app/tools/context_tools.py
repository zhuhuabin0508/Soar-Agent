"""安全上下文查询工具集合（Mock 实现）。

提供 IP 维度的安全上下文查询能力，包括白名单判断、资产信息、
威胁情报、子网信息等。所有函数均为异步实现，并使用 asyncio.sleep
模拟真实网络调用延迟，便于在开发阶段调试链路。

另提供 ``read_document`` 工具：直接读取智能体对话中上传的未分段文档原文
（``agent_files`` 存储，不做 RAG 切片），让智能体能查阅整篇文件内容。
"""
import asyncio
import ipaddress
import logging
import os
import random

logger = logging.getLogger(__name__)

# 内网白名单网段：命中视为可信资产，不触发处置
_WHITELIST_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_in_whitelist(ip: str) -> bool:
    """判断 IP 是否落在白名单网段内（内部辅助函数）。

    Args:
        ip: 待判断的 IP 地址字符串。

    Returns:
        True 表示命中白名单，False 表示外网或非法 IP。
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        logger.warning("无效的 IP 地址: %s", ip)
        return False
    return any(addr in net for net in _WHITELIST_NETWORKS)


async def check_whitelist(ip: str) -> bool:
    """判断指定 IP 是否命中内网白名单。

    Args:
        ip: 待查询的 IPv4/IPv6 地址字符串。

    Returns:
        True 表示命中白名单（可信内网），False 表示外网或非法 IP。
    """
    logger.info("查询白名单命中情况, ip=%s", ip)
    await asyncio.sleep(random.uniform(0.3, 0.8))
    result = _is_in_whitelist(ip)
    logger.debug("白名单查询完成, ip=%s, hit=%s", ip, result)
    return result


async def get_asset_info(ip: str) -> dict:
    """获取 IP 对应资产信息：查询所有知识库，返回命中的资产片段。

    不再返回 Mock 数据。遍历全部知识库做分段检索（BM25 + 向量混合），
    返回与该 IP 相关的资产归属片段（部门、负责人、是否关键资产等）。
    若所有知识库均未命中，返回 found=False，调用方（智能体）可据此转用威胁情报工具。

    Args:
        ip: 待查询的 IP 地址。

    Returns:
        资产信息字典。命中时含 found=True / source / count / matches（片段列表）；
        未命中时含 found=False / message。
    """
    logger.info("查询资产信息(知识库), ip=%s", ip)
    from app.core.kb_retriever import search_kb
    from app.database import SessionLocal
    from app.models.knowledge_base import KnowledgeBase

    db = SessionLocal()
    try:
        kbs = db.query(KnowledgeBase).all()
        matches: list[dict] = []
        for kb in kbs:
            try:
                segs = await search_kb(kb.id, ip, top_k=5)
            except Exception as exc:  # noqa: BLE001
                logger.debug("知识库 %s 检索失败: %s", kb.id, exc)
                segs = []
            for s in segs:
                if (s.get("score") or 0) > 0.1:
                    matches.append({
                        "kb_id": kb.id,
                        "kb_name": kb.name,
                        "title": s.get("title", ""),
                        "content": s.get("content", ""),
                        "score": round(s.get("score", 0), 3),
                    })
        if matches:
            result = {
                "ip": ip,
                "found": True,
                "source": "knowledge_base",
                "count": len(matches),
                "matches": matches[:5],
            }
        else:
            result = {
                "ip": ip,
                "found": False,
                "source": "knowledge_base",
                "message": "知识库中未找到该IP的资产信息，可使用威胁情报工具继续查询",
            }
        logger.debug("资产信息查询完成, ip=%s, found=%s", ip, result["found"])
        return result
    finally:
        db.close()


async def get_threat_intel(ip: str) -> dict:
    """获取 IP 威胁情报（Mock）。

    逻辑一致性：内网白名单 IP 视为非恶意，外网 IP 视为恶意。
    返回详细威胁情报，包括威胁类型、严重程度、首次/最后发现时间、
    地理位置信息、关联恶意软件、攻击模式等，供智能体生成详细研判报告。

    Args:
        ip: 待查询的 IP 地址。

    Returns:
        威胁情报字典，包含 ip、is_malicious、tags、confidence、
        threat_types、severity、first_seen、last_seen、source、
        description、geo_info、related_malware、attack_patterns 字段。
    """
    logger.info("查询威胁情报, ip=%s", ip)
    await asyncio.sleep(random.uniform(0.3, 0.8))
    is_malicious = not _is_in_whitelist(ip)

    if is_malicious:
        tags = ["Botnet", "C2"]
        confidence = 0.92
        threat_types = ["C2 通信", "僵尸网络节点", "暴力破解"]
        severity = "high"
        first_seen = "2026-07-15T08:23:00"
        last_seen = "2026-07-29T06:45:00"
        source = "内部威胁情报平台 + 开源情报(OSINT)"
        description = (
            f"该 IP {ip} 被多个威胁情报源标记为恶意，"
            "关联多个僵尸网络家族，持续对外发起 C2 通信和 SSH 暴力破解攻击。"
            "近期活跃度较高，建议立即封禁。"
        )
        geo_info = {
            "country": "中国",
            "region": "境外",
            "city": "未知",
            "isp": "未知 ISP",
            "latitude": None,
            "longitude": None,
        }
        related_malware = ["Mirai", "Emotet", "Cobalt Strike"]
        attack_patterns = [
            "T1071 - 标准应用层协议（C2 通信）",
            "T1110 - 暴力破解",
            "T1059 - 命令与脚本解释器",
        ]
    else:
        tags = []
        confidence = 0.0
        threat_types = []
        severity = "low"
        first_seen = None
        last_seen = None
        source = "内部威胁情报平台"
        description = f"该 IP {ip} 属于内网白名单网段，未发现威胁记录。"
        geo_info = {
            "country": "中国",
            "region": "内网",
            "city": "本地网络",
            "isp": "内部网络",
            "latitude": None,
            "longitude": None,
        }
        related_malware = []
        attack_patterns = []

    result = {
        "ip": ip,
        "is_malicious": is_malicious,
        "tags": tags,
        "confidence": confidence,
        "threat_types": threat_types,
        "severity": severity,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "source": source,
        "description": description,
        "geo_info": geo_info,
        "related_malware": related_malware,
        "attack_patterns": attack_patterns,
    }
    logger.debug("威胁情报查询完成, ip=%s, result=%s", ip, result)
    return result


async def check_subnet(ip: str) -> dict:
    """查询 IP 所在子网信息（Mock）。

    根据 IP 计算其所在 /24 网段作为 network_segment，
    网关取网段首个主机地址（network_address + 1）。

    Args:
        ip: 待查询的 IP 地址。

    Returns:
        子网信息字典，包含 ip、network_segment、gateway 字段。
    """
    logger.info("查询子网信息, ip=%s", ip)
    await asyncio.sleep(random.uniform(0.3, 0.8))
    try:
        network = ipaddress.ip_network(f"{ip}/24", strict=False)
        network_segment = str(network)
        gateway = str(network.network_address + 1)
    except ValueError:
        network_segment = "unknown"
        gateway = "unknown"
    result = {
        "ip": ip,
        "network_segment": network_segment,
        "gateway": gateway,
    }
    logger.debug("子网信息查询完成, ip=%s, result=%s", ip, result)
    return result


# ============ 文档读取工具（未分段原文） ============
# 复用 file_parser 解析 agent_files 上传的文件，返回纯文本原文。
# 与知识库分段检索（search_knowledge_base）互补：分段检索适合精准定位片段，
# read_document 适合让智能体通读整篇文件（如查阅完整 IP 表、整份报告）。

# 单次返回的文本上限（字符数），避免超大文件撑爆 LLM 上下文
_READ_DOC_MAX_CHARS = 20000


async def list_documents() -> dict:
    """列出智能体可读取的已上传文档（未分段原文，来自 ``agent_files``）。

    Returns:
        ``{files: [{id, original_name, file_type, file_size}], total: N}``
    """
    from app.database import SessionLocal
    from app.models.agent_file import AgentFile

    db = SessionLocal()
    try:
        records = db.query(AgentFile).order_by(AgentFile.created_at.desc()).all()
        files = [
            {
                "id": r.id,
                "original_name": r.original_name,
                "file_type": r.file_type,
                "file_size": r.file_size,
            }
            for r in records
        ]
        return {"files": files, "total": len(files)}
    finally:
        db.close()


async def read_document(file_id: int) -> dict:
    """读取一个已上传文档的**未分段原文**（按文件类型解析为纯文本）。

    与知识库分段检索不同，本工具返回整篇文件解析后的完整文本，让智能体
    能通读全文（如查阅完整 IP 地址表、整份分析报告）。

    Args:
        file_id: ``agent_files`` 上传的文件 ID。

    Returns:
        ``{file_id, original_name, file_type, content, truncated}``。
        文件不存在返回 ``{error, file_id}``。超长内容截断至
        ``_READ_DOC_MAX_CHARS`` 字符并标记 ``truncated=True``。
    """
    from app.core.file_parser import parse_file_content
    from app.database import SessionLocal
    from app.models.agent_file import AgentFile

    db = SessionLocal()
    try:
        record = db.query(AgentFile).filter(AgentFile.id == int(file_id)).first()
        if record is None:
            return {"error": f"文件不存在: file_id={file_id}", "file_id": file_id}
        if not os.path.isfile(record.file_path):
            return {
                "error": f"文件在磁盘上不存在: {record.original_name}",
                "file_id": file_id,
                "original_name": record.original_name,
            }

        logger.info("读取未分段文档: id=%s, name=%s, type=%s", file_id, record.original_name, record.file_type)
        content = await parse_file_content(record.file_path, record.file_type or "")
        truncated = False
        if content and len(content) > _READ_DOC_MAX_CHARS:
            content = content[:_READ_DOC_MAX_CHARS] + "\n\n...[内容已截断，如需完整内容请分段查询]"
            truncated = True

        return {
            "file_id": record.id,
            "original_name": record.original_name,
            "file_type": record.file_type,
            "content": content or "",
            "char_count": len(content or ""),
            "truncated": truncated,
        }
    finally:
        db.close()
