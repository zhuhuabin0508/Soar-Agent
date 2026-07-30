"""Agent 工具包装模块。

将阶段二 ``app.tools.context_tools`` 中的 4 个异步查询函数包装为
LangChain ``StructuredTool``，供 LangGraph 的 ``ToolNode`` 调用。
每个工具均声明 ``args_schema``（基于 pydantic BaseModel），便于 LLM
理解参数语义并生成合法的 tool_calls。
"""
import logging
from typing import Type

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.tools.context_tools import (
    check_subnet,
    check_whitelist,
    get_asset_info,
    get_threat_intel,
)

logger = logging.getLogger(__name__)


class CheckWhitelistArgs(BaseModel):
    """check_whitelist 工具的入参 schema。"""

    ip: str = Field(..., description="待查询的源 IP 地址，例如 8.8.8.8")


class GetAssetInfoArgs(BaseModel):
    """get_asset_info 工具的入参 schema。"""

    ip: str = Field(..., description="待查询资产信息的 IP 地址")


class GetThreatIntelArgs(BaseModel):
    """get_threat_intel 工具的入参 schema。"""

    ip: str = Field(..., description="待查询威胁情报的 IP 地址")


class CheckSubnetArgs(BaseModel):
    """check_subnet 工具的入参 schema。"""

    ip: str = Field(..., description="待查询所在子网的 IP 地址")


# ---- 工具实现：包装异步函数并补充日志 ----


async def _check_whitelist_tool(ip: str) -> bool:
    """查询 IP 是否命中内网白名单。"""
    logger.info("[Tool] 调用 check_whitelist, ip=%s", ip)
    result = await check_whitelist(ip)
    logger.info("[Tool] check_whitelist 结果, ip=%s, hit=%s", ip, result)
    return result


async def _get_asset_info_tool(ip: str) -> dict:
    """查询 IP 对应的资产归属信息。"""
    logger.info("[Tool] 调用 get_asset_info, ip=%s", ip)
    result = await get_asset_info(ip)
    logger.info("[Tool] get_asset_info 结果, ip=%s, result=%s", ip, result)
    return result


async def _get_threat_intel_tool(ip: str) -> dict:
    """查询 IP 的威胁情报。"""
    logger.info("[Tool] 调用 get_threat_intel, ip=%s", ip)
    result = await get_threat_intel(ip)
    logger.info("[Tool] get_threat_intel 结果, ip=%s, result=%s", ip, result)
    return result


async def _check_subnet_tool(ip: str) -> dict:
    """查询 IP 所在子网信息。"""
    logger.info("[Tool] 调用 check_subnet, ip=%s", ip)
    result = await check_subnet(ip)
    logger.info("[Tool] check_subnet 结果, ip=%s, result=%s", ip, result)
    return result


# 构建 4 个 StructuredTool，coroutine 字段指向异步实现，
# 使其可被 LangGraph 的 ToolNode 异步执行。
check_whitelist_tool: StructuredTool = StructuredTool.from_function(
    name="check_whitelist",
    description=(
        "判断指定 IP 是否命中内网白名单（可信内网网段）。"
        "返回布尔值：True 表示可信内网，False 表示外网或非法 IP。"
    ),
    args_schema=CheckWhitelistArgs,
    coroutine=_check_whitelist_tool,
)

get_asset_info_tool: StructuredTool = StructuredTool.from_function(
    name="get_asset_info",
    description=(
        "查询指定 IP 对应的资产归属信息，包括归属部门、负责人、"
        "是否为关键资产(is_critical)。用于评估处置风险。"
    ),
    args_schema=GetAssetInfoArgs,
    coroutine=_get_asset_info_tool,
)

get_threat_intel_tool: StructuredTool = StructuredTool.from_function(
    name="get_threat_intel",
    description=(
        "查询指定 IP 的威胁情报，返回是否恶意(is_malicious)、"
        "恶意标签(tags)、置信度(confidence)。用于判断是否需要处置。"
    ),
    args_schema=GetThreatIntelArgs,
    coroutine=_get_threat_intel_tool,
)

check_subnet_tool: StructuredTool = StructuredTool.from_function(
    name="check_subnet",
    description=(
        "查询指定 IP 所在的 /24 子网信息，包括网段(network_segment)"
        "与网关(gateway)。用于定位网络位置。"
    ),
    args_schema=CheckSubnetArgs,
    coroutine=_check_subnet_tool,
)


# 对外暴露的工具列表（顺序固定，便于阅读与调试）
agent_tools: list = [
    check_whitelist_tool,
    get_asset_info_tool,
    get_threat_intel_tool,
    check_subnet_tool,
]


def get_agent_tool_by_name(name: str) -> Type[StructuredTool] | StructuredTool | None:
    """按名称查找已注册的 Agent 工具。

    Args:
        name: 工具名称，如 ``check_whitelist``。

    Returns:
        匹配到的 ``StructuredTool`` 实例，未找到时返回 ``None``。
    """
    for tool in agent_tools:
        if tool.name == name:
            return tool
    logger.warning("未找到名为 %s 的 Agent 工具", name)
    return None
