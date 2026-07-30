"""大屏统计 Pydantic Schema。"""
from typing import Any, Optional

from pydantic import BaseModel


class DashboardKpi(BaseModel):
    """大屏 KPI 指标。"""

    today_alerts: int
    auto_block_success_rate: float
    mttr_seconds: float
    pending_approvals: int


class TrendItem(BaseModel):
    """每日趋势项。"""

    date: str
    auto_count: int
    manual_count: int


class AlertCategoryItem(BaseModel):
    """告警分类统计项。"""

    name: str
    value: int


class TopMaliciousIpItem(BaseModel):
    """高危 IP Top 项。"""

    ip: str
    count: int
    tags: list[str] = []


class DashboardStats(BaseModel):
    """大屏统计聚合结果。"""

    kpi: DashboardKpi
    trend_7d: list[TrendItem]
    alert_categories: list[AlertCategoryItem]
    top_malicious_ips: list[TopMaliciousIpItem]
