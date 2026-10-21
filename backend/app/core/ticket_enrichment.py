"""工单发起时自动研判：源/目的 IP 资产匹配 + 威胁情报查询。

发起工单时对首节点 ``src_ip`` / ``dst_ip`` 字段自动执行：
1. 资产匹配：复用告警资产富化（AssetLibEnricher）的资产索引
   （单 IP 精确 + CIDR/起止范围包含，内存缓存 TTL 600s，
   资产写接口 commit 后主动失效），与告警「关联资产」同一套口径；
2. 威胁情报：复用工具 ``get_threat_intel``（app.tools.context_tools），
   与智能体工具 API 调用一致。

结果写入 ``Ticket.enrichment_data``（JSON），随工单全程流转，
各节点处理人只读可见。结构::

    {
      "sources": [
        {
          "role": "src_ip",              # src_ip / dst_ip
          "label": "源IP地址",            # 快照字段显示名
          "ip": "10.144.1.2",
          "asset": {"matched": true, "asset_id": 4665,
                    "asset_name": "坪山新区内部网",
                    "asset_ip": "10.144.1.2"},   # 命中时字段；未命中 {"matched": false}
          "threat": {...get_threat_intel 原样返回...}
        }
      ],
      "enriched_at": "2026-10-20T22:30:00",
      "errors": ["..."]     # 部分失败记录（不影响工单发起）
    }

设计要点：
- 字段定位：首节点字段中 type=ip 且 key 为 src_ip / dst_ip
  （兜底 alert_field_mapping 为 src_ip / dst_ip）；
- 多值 IP（逗号/分号分隔）取第一个有效地址；
- 单个来源研判失败仅记入 errors，不阻塞工单发起。
"""
import asyncio
import ipaddress
import logging
import threading
import time
from typing import Optional

from app.core.log_receiver_manager.pipeline.enricher_stage import (
    _ASSET_INDEX_TTL_S,
    _asset_index_cache,
    _asset_index_lock,
    _build_asset_index,
    _match_asset_ip,
)
from app.core.timezone import beijing_now

logger = logging.getLogger(__name__)

# 参与自动研判的 IP 角色及兜底字段 key
_IP_ROLES = ("src_ip", "dst_ip")


def _extract_ip(value) -> Optional[str]:
    """字段值 → 首个有效 IP（支持逗号/分号分隔多值；无效返回 None）。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    for part in s.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ipaddress.ip_address(part)
            return part
        except ValueError:
            continue
    return None


def _locate_ip_fields(field_defs: list, values: dict) -> list[dict]:
    """从首节点字段定义中定位 src_ip / dst_ip 字段并提取有效 IP。

    匹配规则：字段 key 为 src_ip / dst_ip（兜底 alert_field_mapping），
    且字段值为有效 IP。返回 ``[{role, label, ip}]``。
    """
    found: list[dict] = []
    for f in field_defs or []:
        if not isinstance(f, dict):
            continue
        key = str(f.get("key") or "")
        mapping = str(f.get("alert_field_mapping") or "")
        role = key if key in _IP_ROLES else (mapping if mapping in _IP_ROLES else "")
        if not role or any(item["role"] == role for item in found):
            continue
        ip = _extract_ip(values.get(key))
        if not ip:
            continue
        found.append({"role": role, "label": f.get("label") or key, "ip": ip})
    return found


def _match_asset(db, ip: str) -> dict:
    """单 IP 匹配资产库（复用告警富化索引：单 IP 精确 + CIDR/范围包含）。"""
    with _asset_index_lock:
        if time.time() - _asset_index_cache["built_at"] > _ASSET_INDEX_TTL_S:
            _build_asset_index(db)
        index = {
            "single": _asset_index_cache["single"],
            "nets": _asset_index_cache["nets"],
        }
    hit = _match_asset_ip(ip, index)
    if hit:
        return {
            "matched": True,
            "asset_id": hit[0],
            "asset_name": hit[1] or "",
            "asset_ip": ip,
        }
    return {"matched": False}


def _query_threat_intel_batch(ips: list[str]) -> list[dict]:
    """并发调用 get_threat_intel（单事件循环跑完所有 IP，缩短发起耗时）。

    单个 IP 查询失败返回 ``{"error": "..."}``，不影响其余 IP。
    """
    from app.tools.context_tools import get_threat_intel

    async def _gather():
        async def _one(ip: str) -> dict:
            try:
                return await get_threat_intel(ip)
            except Exception as exc:  # noqa: BLE001
                logger.warning("威胁情报查询失败, ip=%s: %s", ip, exc)
                return {"error": f"查询失败: {exc}", "ip": ip}

        return await asyncio.gather(*[_one(ip) for ip in ips])

    return asyncio.run(_gather())


def build_ticket_enrichment(db, field_defs: list, values: dict) -> Optional[dict]:
    """构建工单自动研判结果（发起时调用一次）。

    无有效 src_ip / dst_ip 时返回 None（不留空结构）。
    任何整体异常均向上抛出由调用方兜底；单来源失败记入 errors。
    """
    located = _locate_ip_fields(field_defs, values)
    if not located:
        return None

    # 威胁情报批量并发查询（Mock 0.3-0.8s 延迟，并发后仅一次等待）
    threats = _query_threat_intel_batch([item["ip"] for item in located])

    sources: list[dict] = []
    errors: list[str] = []
    for item, threat in zip(located, threats):
        entry = {"role": item["role"], "label": item["label"], "ip": item["ip"]}
        try:
            entry["asset"] = _match_asset(db, item["ip"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("工单资产匹配失败, ip=%s: %s", item["ip"], exc)
            entry["asset"] = {"matched": False}
            errors.append(f"{item['label']} 资产匹配失败: {exc}")
        if isinstance(threat, dict) and not threat.get("error"):
            entry["threat"] = threat
        else:
            entry["threat"] = None
            errors.append(f"{item['label']} 威胁情报查询失败: {threat.get('error') if threat else '未知错误'}")
        sources.append(entry)

    logger.info(
        "工单自动研判完成: roles=%s, 资产命中=%s/%d, 错误=%d",
        [item["role"] for item in located],
        sum(1 for s in sources if s["asset"].get("matched")),
        len(sources),
        len(errors),
    )
    return {
        "sources": sources,
        "enriched_at": beijing_now().isoformat(),
        "errors": errors,
    }
