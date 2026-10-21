"""③ Enricher 阶段：富化器插件（默认清单为空，空转保证行为等价）。

富化器协议：``enrich(norm: NormalizedEvent, db) -> None``，按
``enricher_registry`` 注册；本阶段把结果写入 ``norm.enrichments``
（不覆盖解析产出的原字段，落库时并入 extensions 由 Normalizer 决定）。

内置富化器：
- AssetEnricher（默认不启用）：按 src_ip/host_ip 关联 devices 表，
  补 asset_id 与内网标注到 enrichments。
- AssetLibEnricher（默认启用）：按 host→src→dst IP 匹配 assets 资产库
  （支持单 IP 精确 + CIDR/范围包含），命中后将关联资产写入
  relate_asset_id / relate_asset_name / relate_asset_ip 列落库。
"""
import ipaddress
import json
import logging
import threading
import time

from ..registry import _BaseRegistry, stage_registry
from .base_stage import BaseStage, PipelineData

logger = logging.getLogger(__name__)


class EnricherRegistry(_BaseRegistry):
    """富化器注册表（键 = name 属性）。"""

    def __init__(self) -> None:
        super().__init__("enricher")

    def _key_of(self, cls) -> str:
        return getattr(cls, "name", "") or getattr(cls, "__name__", "")


enricher_registry = EnricherRegistry()


class AssetEnricher:
    """资产关联富化：按事件 src_ip / host_ip 匹配 devices 表。

    命中时在 norm.enrichments["asset"] 记录 {asset_id, device_name, ip_field}，
    并在 asset_id 为空时补填 asset_id（仅补空，不覆盖）。
    """

    name = "asset"

    def enrich(self, norm, db) -> None:  # pragma: no cover - 依赖 DB，容器内验证
        try:
            ips = []
            for key in ("src_ip", "host_ip"):
                val = norm.get_field(key)
                if not val:
                    continue
                if isinstance(val, str):
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, list):
                            ips.extend(str(x) for x in parsed if x)
                            continue
                    except (ValueError, TypeError):
                        pass
                ips.append(str(val))
            if not ips:
                return
            from sqlalchemy import text as sa_text

            for ip in ips[:3]:  # 最多探测前 3 个 IP，避免大数组拖慢
                row = db.execute(
                    sa_text("SELECT id, device_name FROM devices WHERE ip_address = :ip LIMIT 1"),
                    {"ip": ip},
                ).first()
                if row:
                    norm.enrichments.setdefault("asset", {
                        "asset_id": row[0],
                        "device_name": row[1],
                        "ip_field": ip,
                    })
                    if norm.get_field("asset_id") in (None, ""):
                        norm.set_field("asset_id", str(row[0]))
                    return
        except Exception:  # noqa: BLE001
            logger.exception("资产富化异常（忽略）")


# ===== 资产库索引（内存缓存，AssetLibEnricher 使用） =====
_ASSET_INDEX_TTL_S = 600  # 10 分钟；资产写接口通过 invalidate_asset_index 主动失效
_asset_index_lock = threading.Lock()
_asset_index_cache: dict = {"built_at": 0.0, "single": {}, "nets": []}


def invalidate_asset_index() -> None:
    """资产数据变更后主动失效索引缓存（下次匹配时重建）。"""
    with _asset_index_lock:
        _asset_index_cache["built_at"] = 0.0


def _parse_ip_list(raw: str):
    """资产 ip 字段（可能是单 IP / CIDR / 起止范围 / 逗号多值）→ 可匹配条目列表。"""
    out = []
    for part in str(raw).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            try:
                out.append(("net", ipaddress.ip_network(part, strict=False)))
            except ValueError:
                continue
        elif "-" in part:
            try:
                a, b = part.split("-", 1)
                out.append(("range", ipaddress.ip_address(a), ipaddress.ip_address(b)))
            except ValueError:
                continue
        else:
            try:
                ipaddress.ip_address(part)
                out.append(("ip", part))
            except ValueError:
                continue
    return out


def _build_asset_index(db) -> None:
    """（重）构建资产索引：单 IP 精确 dict + CIDR/范围列表。"""
    from sqlalchemy import text as sa_text

    single: dict = {}
    nets: list = []
    rows = db.execute(
        sa_text("SELECT id, name, ip FROM assets WHERE ip IS NOT NULL AND ip != ''")
    ).fetchall()
    for aid, name, ip in rows:
        for item in _parse_ip_list(ip or ""):
            if item[0] == "ip":
                single.setdefault(item[1], (aid, name))
            else:
                nets.append((item, aid, name))
    # 网段按网络地址/起始地址排序（IPv4 与 IPv6 不兼容比较，按字符串分组排序）
    nets.sort(key=lambda x: str(x[0][1]))
    _asset_index_cache["single"] = single
    _asset_index_cache["nets"] = nets
    _asset_index_cache["built_at"] = time.time()
    logger.info("资产库索引已构建: 单IP=%d 网段/范围=%d", len(single), len(nets))


def _match_asset_ip(ip: str, index: dict):
    """单个 IP 匹配资产索引：单 IP 精确优先，再 CIDR/范围包含。"""
    hit = index["single"].get(ip)
    if hit:
        return hit
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    for item, aid, name in index["nets"]:
        if item[0] == "net":
            if addr.version == item[1].version and addr in item[1]:
                return (aid, name)
        else:  # range
            if addr.version == item[1].version and item[1] <= addr <= item[2]:
                return (aid, name)
    return None


class AssetLibEnricher:
    """本地资产库关联富化：按 host_ip → src_ip → dst_ip 逐级匹配 assets 表。

    - IP 值支持 JSON 数组字符串（如 XDR host_ip），过滤 fe80:: 链路本地地址；
    - 单 IP 精确匹配优先，未命中再 CIDR / 起止范围包含判断；
    - 命中即停，写 relate_asset_id / relate_asset_name / relate_asset_ip
      （仅补空不覆盖），经 NormalizedEvent.to_alert_fields 落入 alert_events。
    """

    name = "asset_lib"

    def enrich(self, norm, db) -> None:
        try:
            if norm.get_field("relate_asset_id"):
                return  # 已有关联资产，跳过
            with _asset_index_lock:
                if time.time() - _asset_index_cache["built_at"] > _ASSET_INDEX_TTL_S:
                    _build_asset_index(db)
                index = {
                    "single": _asset_index_cache["single"],
                    "nets": _asset_index_cache["nets"],
                }
            for field in ("host_ip", "src_ip", "dst_ip"):
                val = norm.get_field(field)
                if not val:
                    continue
                ips = []
                s = str(val)
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        ips = [str(x) for x in parsed if x]
                    else:
                        ips = [s]
                except (ValueError, TypeError):
                    ips = [s]
                ips = [ip for ip in ips if not ip.startswith("fe80::")][:5]
                for ip in ips:
                    hit = _match_asset_ip(ip, index)
                    if hit:
                        norm.set_field("relate_asset_id", hit[0])
                        norm.set_field("relate_asset_name", hit[1] or "")
                        norm.set_field("relate_asset_ip", ip)
                        return
        except Exception:  # noqa: BLE001
            logger.exception("资产库富化异常（忽略）")


enricher_registry.register(AssetEnricher)
enricher_registry.register(AssetLibEnricher)


@stage_registry.register
class EnricherStage(BaseStage):
    """富化步骤（config.enrichers = 启用的富化器 name 列表，默认空）。"""

    name = "enricher"

    def process(self, data: PipelineData, sink, db) -> None:
        names = self.config.get("enrichers") or []
        if not names:
            return
        enrichers = []
        for name in names:
            cls = enricher_registry.get(name)
            if cls is None:
                logger.warning("富化器未注册，已跳过: %s", name)
                continue
            try:
                enrichers.append(cls() if isinstance(cls, type) else cls)
            except Exception:  # noqa: BLE001
                logger.exception("富化器实例化失败: %s", name)
        if not enrichers:
            return
        for norm in data.normalized:
            for en in enrichers:
                try:
                    enrich_fn = getattr(en, "enrich", None) or en
                    enrich_fn(norm, db)
                except Exception:  # noqa: BLE001
                    logger.exception("富化器 %s 执行异常（忽略）", getattr(en, "name", en))
