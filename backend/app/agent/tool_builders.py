"""工具入参与知识库、资产检索工具构造。"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "String": str,
    "Number": float,
    "Boolean": bool,
    "Object": dict,
    "Array": list,
}

def _build_args_model(tool_name: str, parameters_schema: list[dict] | None):
    """根据 parameters_schema 动态构造 pydantic 入参模型。

    schema 元素结构：``{name, type, required, description}``。
    """
    fields: dict[str, Any] = {}
    for param in parameters_schema or []:
        name = param.get("name")
        if not name:
            continue
        ptype = param.get("type", "String")
        py_type = _TYPE_MAP.get(ptype, str)
        required = bool(param.get("required", False))
        desc = param.get("description", "")
        if required:
            fields[name] = (py_type, Field(..., description=desc))
        else:
            fields[name] = (Optional[py_type], Field(None, description=desc))
    safe_name = "".join(c if c.isalnum() else "_" for c in tool_name) or "Tool"
    return create_model(f"{safe_name}Args", **fields)


def _build_db_tools(db, enabled_tools: list[str]) -> list:
    """把启用的 DB 工具加载为 LangChain StructuredTool。

    Args:
        db: 数据库会话。
        enabled_tools: 工具名称列表。

    Returns:
        StructuredTool 实例列表（加载失败的工具被跳过并记录日志）。
    """
    from langchain_core.tools import StructuredTool

    from app.core.tool_runner import load_tool_function
    from app.models.tool import Tool

    tools: list = []
    if not enabled_tools:
        return tools
    for name in enabled_tools:
        # search_assets 由 _build_asset_tool 注册，避免与 DB code 工具重复挂载
        if name == "search_assets":
            continue
        tool = db.query(Tool).filter(Tool.name == name, Tool.enabled.is_(True)).first()
        if tool is None:
            logger.warning("DB 工具未找到或未启用: %s", name)
            continue
        try:
            run_fn = load_tool_function(tool)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DB 工具加载失败: %s, error=%s", name, exc)
            continue
        args_model = _build_args_model(tool.name, tool.parameters_schema)

        # 用工厂绑定每次迭代的 run_fn/name，避免闭包延迟捕获导致全部工具共用最后一份引用
        def _make_coroutine(rfn, tname):
            async def _coroutine(**kwargs):
                try:
                    return await rfn(**kwargs)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("工具 %s 执行异常: %s", tname, exc)
                    return {"error": str(exc)}
            return _coroutine

        structured = StructuredTool.from_function(
            name=tool.name,
            description=tool.description or f"DB 工具 {tool.name}",
            args_schema=args_model,
            coroutine=_make_coroutine(run_fn, name),
        )
        tools.append(structured)
        logger.info("已加载 DB 工具为 StructuredTool: %s", name)
    return tools


def _build_kb_tool(enabled_kbs: list[int]):
    """构造知识库检索工具（搜索所有启用知识库）。"""
    if not enabled_kbs:
        return None
    from langchain_core.tools import StructuredTool

    class SearchKBArgs(BaseModel):
        query: str = Field(..., description="检索查询字符串")
        kb_id: Optional[int] = Field(None, description="指定知识库 id；不传则检索所有启用知识库")

    kb_ids = list(enabled_kbs)

    async def _coroutine(query: str, kb_id: Optional[int] = None):
        from app.core.kb_retriever import search_kb

        targets = list(kb_ids)
        if kb_id is not None:
            # 指定库优先；若该库已删或不在启用列表，改搜全部启用库
            if kb_id in kb_ids:
                hits = await search_kb(kb_id, query)
                if hits:
                    return hits
            targets = [kid for kid in kb_ids if kid != kb_id]
        results: list = []
        for kid in targets:
            results.extend(await search_kb(kid, query))
        return results

    return StructuredTool.from_function(
        name="search_knowledge_base",
        description="在已启用的知识库中检索相关文档。可指定 kb_id，不传则检索所有启用知识库。",
        args_schema=SearchKBArgs,
        coroutine=_coroutine,
    )


def _build_file_query_tool(enabled_kbs: list[int]):
    """构造知识库文件查询工具（读取原始 Excel/CSV 文件，按条件精确查询）。

    与 ``search_knowledge_base``（语义检索）互补：本工具返回结构化表格行列数据，
    适合精确查询 Excel 中的特定 IP、部门、资产等字段值。
    """
    if not enabled_kbs:
        return None
    from langchain_core.tools import StructuredTool

    class FileQueryArgs(BaseModel):
        query: str = Field(
            "",
            description="查询条件。支持关键词（任意列包含即命中）或 '列名=值' 精确过滤。"
            "例如 '203.0.113.1' 或 '部门=研发部'。留空则返回前几行预览。",
        )
        doc_id: Optional[int] = Field(
            None, description="指定文档 id（优先级最高）。不传则在所有启用知识库中搜索。"
        )
        kb_id: Optional[int] = Field(
            None, description="指定知识库 id。不传则搜索所有启用知识库。"
        )
        sheet: Optional[str] = Field(
            None, description="Excel sheet 名（不传则读第一个 sheet）"
        )
        limit: Optional[int] = Field(
            20, description="返回行数上限，默认 20，最大 200"
        )

    kb_ids = list(enabled_kbs)

    async def _coroutine(
        query: str = "",
        doc_id: Optional[int] = None,
        kb_id: Optional[int] = None,
        sheet: Optional[str] = None,
        limit: int = 20,
    ):
        from app.core.kb_file_query import query_kb_file

        return query_kb_file(
            query=query,
            kb_id=kb_id,
            doc_id=doc_id,
            sheet=sheet,
            limit=limit,
            enabled_kbs=kb_ids,
        )

    return StructuredTool.from_function(
        name="query_kb_file",
        description=(
            "查询知识库中的表格文件（Excel/CSV），返回结构化行列数据。"
            "适合精确查询 IP 列表、资产台账、人员信息等结构化数据。"
            "支持按列名=值过滤，或关键词模糊匹配。"
            "与 search_knowledge_base（语义检索）互补：本工具返回原始表格行数据。"
        ),
        args_schema=FileQueryArgs,
        coroutine=_coroutine,
    )


def _all_asset_type_codes() -> list[str]:
    """读取全部资产类型 code；无模板时返回空列表。"""
    return list(_asset_type_labels().keys())


def _asset_type_labels() -> dict[str, str]:
    """资产类型 code → 中文显示名（来自 AssetTypeTemplate）。"""
    from app.database import SessionLocal
    from app.models.asset import AssetTypeTemplate

    db = SessionLocal()
    try:
        rows = db.query(AssetTypeTemplate.code, AssetTypeTemplate.name).order_by(
            AssetTypeTemplate.sort_order.asc(), AssetTypeTemplate.id.asc()
        ).all()
        return {code: name for code, name in rows}
    except Exception:  # noqa: BLE001
        logger.warning("读取资产类型模板失败，search_assets 无类型名称映射")
        return {}
    finally:
        db.close()


def _should_attach_search_assets(
    enabled_tools: list[str] | None,
    enabled_asset_types: list[str] | None,
) -> bool:
    """未勾选任何资产类型时不注册 search_assets。"""
    return bool(enabled_asset_types)


async def execute_search_assets(
    keyword: str = "",
    department: str = "",
    type_code: str | None = None,
    limit: int = 20,
    type_codes: list[str] | None = None,
):
    """供工具沙箱 / 测试页调用的资产检索入口。"""
    tool = _build_asset_tool(list(type_codes or []))
    if tool is None:
        return {"error": "未勾选资产类型，search_assets 不可用", "count": 0}
    result = await tool.coroutine(
        keyword=keyword or "",
        department=department or "",
        type_code=type_code,
        limit=limit,
    )
    return result if isinstance(result, dict) else {"count": len(result or []), "assets": result or []}


def _build_asset_tool(enabled_asset_types: list[str]):
    """构造资产检索工具（在关联的资产类型范围内检索）。

    检索范围由智能体勾选的 ``enabled_asset_types`` 决定：
    - 未勾选：不注册本工具
    - 勾选部分类型：只查这些 ``type_code``
    - 勾选全部类型：不按类型过滤（同一 IP 在主机/网段/出口等多类下都会返回）

    IP 匹配策略（ip 列可能存储单 IP / IP 范围 / CIDR 三种格式）：
    - keyword 为单个 IPv4 时：做 **IP 包含判断**（查询 IP 是否落在存储值的
      网段/范围内），而非子串匹配。例：查 ``113.108.60.240`` 会命中
      ``113.108.60.224-113.108.60.254`` 的网段资产。
    - keyword 为 CIDR（如 ``198.51.100.0/24``）时：做网段重叠判断。
    - keyword 非 IP 时：走 ilike 子串匹配（IP/名称/标识/负责人）。
    """
    type_codes_in = list(dict.fromkeys(enabled_asset_types or []))
    if not type_codes_in:
        return None
    import ipaddress
    from langchain_core.tools import StructuredTool
    from sqlalchemy import or_

    class SearchAssetsArgs(BaseModel):
        keyword: str = Field(
            "",
            description="按 IP/名称/标识/负责人模糊搜索。传入单个 IP（如 198.51.100.1）"
            "会自动匹配包含该 IP 的网段/CIDR/范围资产。",
        )
        department: str = Field("", description="按使用单位/部门精确筛选")
        type_code: Optional[str] = Field(
            None,
            description="忽略。检索范围由智能体勾选的资产类型决定，同一 IP 会返回所有类型下的命中。",
        )
        limit: int = Field(20, description="非 IP 查询的条数上限，默认20。按 IP 查询会跨类型返回全部命中。")

    type_codes = list(type_codes_in)
    all_template_codes = set(_all_asset_type_codes())
    # 全选（勾选覆盖当前全部模板）时不按 type_code 过滤，避免漏掉未分类或同 IP 多类型记录
    filter_by_types = None if (all_template_codes and set(type_codes) >= all_template_codes) else type_codes

    # ---- IP 解析辅助函数 ----
    def _parse_single_ip(s: str):
        """尝试解析为单个 IPv4 地址，失败返回 None。"""
        s = (s or "").strip()
        if not s:
            return None
        try:
            return ipaddress.IPv4Address(s)
        except (ipaddress.AddressValueError, ValueError):
            return None

    def _complete_ip(s: str):
        """对不完整 IP 字符串补 .0 后解析（如 ``198.51.100`` → ``198.51.100.0``）。

        资产数据存在质量问题（如 ``198.51.100-198.51.100.254`` 起始 IP 缺最后一段），
        这里做防御性补全。
        """
        s = (s or "").strip()
        if not s:
            return None
        octets = s.split(".")
        while len(octets) < 4:
            octets.append("0")
        if len(octets) > 4:
            return None
        return _parse_single_ip(".".join(octets))

    def _ip_in_value(target, stored: str) -> bool:
        """判断 target IP 是否包含在 stored（单 IP / IP 范围 / CIDR / 逗号分隔多值）中。

        Args:
            target: ``ipaddress.IPv4Address`` 查询目标 IP
            stored: 资产 ip 列的原始字符串（可能是逗号分隔的多个 IP/范围/CIDR）

        Returns:
            True 表示 target 落在 stored 描述的范围内

        支持的格式：
        - 逗号分隔多值: ``203.0.113.1,203.0.113.2``（逐个判断，任一命中即 True）
        - 完整范围: ``113.108.60.224-113.108.60.254``
        - 末段简写: ``61.144.224.185-187``（仅最后一位变化，等价 185-187）
        - 不完整 IP（数据质量）: ``198.51.100-198.51.100.254``（起始缺段自动补 .0）
        """
        stored = (stored or "").strip()
        if not stored:
            return False

        # 方案 A：逗号分隔的多 IP 值，逐个判断（如 "203.0.113.1,203.0.113.2"）
        if "," in stored:
            for part in stored.split(","):
                part = part.strip()
                if part and _ip_in_value_single(target, part):
                    return True
            return False

        return _ip_in_value_single(target, stored)

    def _ip_in_value_single(target, stored: str) -> bool:
        """判断 target IP 是否包含在单个 stored 值（单 IP / IP 范围 / CIDR）中。"""
        stored = (stored or "").strip()
        if not stored:
            return False

        # 1. CIDR 格式 (198.51.100.0/24)
        if "/" in stored:
            try:
                net = ipaddress.IPv4Network(stored, strict=False)
                return target in net
            except (ipaddress.NetmaskValueError, ipaddress.AddressValueError, ValueError):
                return False

        # 2. IP 范围格式 (start-end)
        if "-" in stored:
            parts = stored.split("-", 1)
            if len(parts) == 2:
                start_str = parts[0].strip()
                end_str = parts[1].strip()
                start_ip = _parse_single_ip(start_str) or _complete_ip(start_str)
                if start_ip is None:
                    return False
                # 末段简写：end_str 无点且为纯数字（如 "187"）时，替换 start 的最后一段
                # 例：61.144.224.185-187 → end = 61.144.224.187
                # 必须先于 _complete_ip 判断，否则 "187" 会被补成 187.0.0.0 产生超大范围
                if "." not in end_str and end_str.isdigit():
                    octets = str(start_ip).split(".")
                    last = int(end_str)
                    if 0 <= last <= 255:
                        octets[3] = str(last)
                        end_ip = _parse_single_ip(".".join(octets))
                    else:
                        end_ip = _complete_ip(end_str)
                else:
                    end_ip = _parse_single_ip(end_str) or _complete_ip(end_str)
                if end_ip is not None:
                    return start_ip <= target <= end_ip
            return False

        # 3. 单 IP 精确匹配 (58.250.157.1)
        single = _parse_single_ip(stored)
        if single is not None:
            return target == single

        return False

    def _network_overlaps(query_net, stored: str) -> bool:
        """判断 query_net (IPv4Network) 是否与 stored（单 IP/范围/CIDR/逗号分隔多值）重叠。"""
        stored = (stored or "").strip()
        if not stored:
            return False

        # 方案 A：逗号分隔的多 IP 值，逐个判断
        if "," in stored:
            for part in stored.split(","):
                part = part.strip()
                if part and _network_overlaps_single(query_net, part):
                    return True
            return False

        return _network_overlaps_single(query_net, stored)

    def _network_overlaps_single(query_net, stored: str) -> bool:
        """判断 query_net (IPv4Network) 是否与单个 stored 值（单 IP/范围/CIDR）重叠。"""
        stored = (stored or "").strip()
        if not stored:
            return False

        # CIDR
        if "/" in stored:
            try:
                net = ipaddress.IPv4Network(stored, strict=False)
                return query_net.overlaps(net)
            except (ipaddress.NetmaskValueError, ipaddress.AddressValueError, ValueError):
                return False

        # IP 范围
        if "-" in stored:
            parts = stored.split("-", 1)
            if len(parts) == 2:
                start_str = parts[0].strip()
                end_str = parts[1].strip()
                start_ip = _parse_single_ip(start_str) or _complete_ip(start_str)
                if start_ip is None:
                    return False
                # 末段简写（同 _ip_in_value_single 逻辑）
                if "." not in end_str and end_str.isdigit():
                    octets = str(start_ip).split(".")
                    last = int(end_str)
                    if 0 <= last <= 255:
                        octets[3] = str(last)
                        end_ip = _parse_single_ip(".".join(octets))
                    else:
                        end_ip = _complete_ip(end_str)
                else:
                    end_ip = _parse_single_ip(end_str) or _complete_ip(end_str)
                if start_ip is not None and end_ip is not None:
                    # 检查 query_net 是否与 [start, end] 区间有交集
                    net_start = query_net.network_address
                    net_end = query_net.broadcast_address
                    return net_start <= end_ip and start_ip <= net_end
            return False

        # 单 IP
        single = _parse_single_ip(stored)
        if single is not None:
            return single in query_net

        return False

    def _ip_field_values(r) -> list[str]:
        """资产上可能存放 IP 的字段：标准 ip、identifier、extra_fields 中的 IP/EIP。"""
        values = [r.ip or "", r.identifier or ""]
        extra = r.extra_fields if isinstance(r.extra_fields, dict) else {}
        for key, val in extra.items():
            if not val:
                continue
            lk = str(key).lower()
            if lk in ("eip", "ip", "cidr", "public_ip", "wan_ip", "nat_ip") or "ip" in lk or "cidr" in lk:
                values.append(str(val))
        return values

    def _record_has_ip(r, query_ip) -> bool:
        return any(_ip_in_value(query_ip, v) for v in _ip_field_values(r) if v)

    def _record_overlaps_net(r, query_net) -> bool:
        return any(_network_overlaps(query_net, v) for v in _ip_field_values(r) if v)

    type_labels = _asset_type_labels()

    def _serialize(r) -> dict:
        extra = r.extra_fields if isinstance(r.extra_fields, dict) else {}
        code = r.type_code or "(uncategorized)"
        return {
            "id": r.id, "name": r.name, "ip": r.ip, "identifier": r.identifier,
            "department": r.department, "owner": r.owner,
            "type_code": code,
            "type_name": type_labels.get(code, code),
            "status": r.status, "criticality": r.criticality,
            "eip": extra.get("eip") or extra.get("EIP"),
            "extra_fields": extra or None,
        }

    def _pack(rows) -> dict:
        """按资产类型分组返回，顶层 key 为类型中文名（如 出口地址 / 主机资产）。"""
        bucket_codes = list(type_labels.keys()) if filter_by_types is None else list(type_codes)
        if not bucket_codes:
            bucket_codes = list(dict.fromkeys(
                [(r.type_code or "(uncategorized)") for r in rows]
            ))
        grouped: dict[str, list] = {code: [] for code in bucket_codes}
        for r in rows:
            code = r.type_code or "(uncategorized)"
            if code not in grouped:
                grouped[code] = []
            grouped[code].append(_serialize(r))

        result: dict = {"count": len(rows)}
        for code in bucket_codes:
            label = type_labels.get(code, code)
            result[label] = grouped.get(code, [])
        return result

    async def _coroutine(keyword="", department="", type_code=None, limit=20):
        from app.database import SessionLocal
        from app.models.asset import Asset
        db = SessionLocal()
        try:
            q = db.query(Asset)
            if filter_by_types is not None:
                q = q.filter(Asset.type_code.in_(filter_by_types))
            if department:
                q = q.filter(Asset.department == department)

            max_limit = min(max(limit, 1), 50)
            ip_hit_cap = 500

            query_ip = _parse_single_ip(keyword) if keyword else None
            query_net = None
            if query_ip is None and keyword and "/" in keyword:
                try:
                    query_net = ipaddress.IPv4Network(keyword.strip(), strict=False)
                except (ipaddress.NetmaskValueError, ipaddress.AddressValueError, ValueError):
                    query_net = None

            if query_ip is not None:
                candidates = q.order_by(Asset.id.desc()).limit(50000).all()
                rows = [r for r in candidates if _record_has_ip(r, query_ip)][:ip_hit_cap]
            elif query_net is not None:
                candidates = q.order_by(Asset.id.desc()).limit(50000).all()
                rows = [r for r in candidates if _record_overlaps_net(r, query_net)][:ip_hit_cap]
            else:
                if keyword:
                    kw = f"%{keyword}%"
                    q = q.filter(or_(Asset.ip.ilike(kw), Asset.name.ilike(kw),
                                     Asset.identifier.ilike(kw), Asset.owner.ilike(kw)))
                rows = q.order_by(Asset.id.desc()).limit(max_limit).all()

            return _pack(rows)
        finally:
            db.close()

    scope_desc = (
        "已勾选全部资产类型，不按类型过滤；同一 IP 在主机资产/网段/出口地址等类型下的记录都会返回。"
        if filter_by_types is None
        else f"仅检索已勾选类型 {type_codes}；同一 IP 在这些类型下的记录都会返回。"
    )
    return StructuredTool.from_function(
        name="search_assets",
        description=(
            f"检索资产清单。{scope_desc}"
            "传入单个 IP 会匹配包含该 IP 的网段/CIDR/范围/EIP；"
            "传入 CIDR 会匹配重叠网段。"
        ),
        args_schema=SearchAssetsArgs,
        coroutine=_coroutine,
    )
