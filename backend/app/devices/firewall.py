"""防火墙设备适配层（Mock 实现）。

提供 IP 封禁能力，支持幂等调用：重复对同一 IP 发起封禁不会
产生副作用，仅返回已封禁提示。封禁状态维护在进程内存态集合中，
适用于开发调试与单实例场景。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# 模拟防火墙已封禁 IP 列表（内存态）
_blocked_ips: set[str] = set()


async def block_ip_on_firewall(ip: str, duration: str, reason: str) -> dict:
    """在防火墙上下发 IP 封禁规则（幂等）。

    若该 IP 已在封禁列表中，则跳过下发并返回已封禁提示；
    否则模拟下发延迟后将其加入封禁列表。

    Args:
        ip: 待封禁的 IP 地址。
        duration: 封禁时长描述（如 "1h"、"24h"）。
        reason: 封禁原因说明。

    Returns:
        封禁结果字典，包含 status、rule_id、ip 等字段。
    """
    logger.info("收到封禁请求, ip=%s, duration=%s, reason=%s", ip, duration, reason)
    if ip in _blocked_ips:
        logger.info("IP already blocked, skip, ip=%s", ip)
        return {
            "status": "success",
            "rule_id": "existing",
            "ip": ip,
            "message": "already blocked",
        }
    await asyncio.sleep(0.5)
    _blocked_ips.add(ip)
    result = {
        "status": "success",
        "rule_id": "rule_123",
        "ip": ip,
        "duration": duration,
        "reason": reason,
    }
    logger.info("封禁下发完成, ip=%s, rule_id=rule_123", ip)
    logger.debug("封禁结果详情, ip=%s, result=%s", ip, result)
    return result


async def is_ip_blocked(ip: str) -> bool:
    """查询指定 IP 是否已被封禁。

    Args:
        ip: 待查询的 IP 地址。

    Returns:
        True 表示已封禁，False 表示未封禁。
    """
    blocked = ip in _blocked_ips
    logger.debug("查询封禁状态, ip=%s, blocked=%s", ip, blocked)
    return blocked
