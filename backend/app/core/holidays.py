"""中国法定节假日数据与判断逻辑。

内置 2025-2026 年法定节假日及调休安排（数据来源于国务院通知）。
支持手动覆盖：通过 duty_special_dates 表或 API 指定特殊日期的工作日/非工作日属性。

判断逻辑：
1. 先查手动覆盖（用户通过 API 标记的特殊日期）
2. 再查内置节假日表（HOLIDAYS 字典）
3. 最后按周末判断（周六/周日 = 非工作日）

``HOLIDAYS`` 字典：key = "YYYY-MM-DD"，value = "holiday"（放假）或 "workday"（调休上班）
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# ============================================================================
# 内置中国法定节假日数据（含调休安排）
# 数据来源：国务院办公厅发布的放假通知
# ============================================================================

HOLIDAYS: dict[str, str] = {
    # ==================== 2025 年 ====================
    # 元旦 1.1
    "2025-01-01": "holiday",
    # 春节 1.28-2.4（1.26 周日、2.8 周六调休上班）
    "2025-01-26": "workday",  # 周日调休上班
    "2025-01-28": "holiday",
    "2025-01-29": "holiday",
    "2025-01-30": "holiday",
    "2025-01-31": "holiday",
    "2025-02-01": "holiday",
    "2025-02-02": "holiday",
    "2025-02-03": "holiday",
    "2025-02-04": "holiday",
    "2025-02-08": "workday",  # 周六调休上班
    # 清明 4.4-4.6
    "2025-04-04": "holiday",
    "2025-04-05": "holiday",
    "2025-04-06": "holiday",
    # 劳动节 5.1-5.5（4.27 周日调休上班）
    "2025-04-27": "workday",
    "2025-05-01": "holiday",
    "2025-05-02": "holiday",
    "2025-05-03": "holiday",
    "2025-05-04": "holiday",
    "2025-05-05": "holiday",
    # 端午 5.31-6.2
    "2025-05-31": "holiday",
    "2025-06-01": "holiday",
    "2025-06-02": "holiday",
    # 中秋+国庆 10.1-10.8（9.28 周日、10.11 周六调休上班）
    "2025-09-28": "workday",
    "2025-10-01": "holiday",
    "2025-10-02": "holiday",
    "2025-10-03": "holiday",
    "2025-10-04": "holiday",
    "2025-10-05": "holiday",
    "2025-10-06": "holiday",
    "2025-10-07": "holiday",
    "2025-10-08": "holiday",
    "2025-10-11": "workday",

    # ==================== 2026 年 ====================
    # 元旦 1.1-1.3（1.1 周四，连休 3 天，无调休）
    "2026-01-01": "holiday",
    "2026-01-02": "holiday",
    "2026-01-03": "holiday",
    # 春节 2.15-2.22（2.14 周六、2.22 周日调休上班，假期 8 天）
    "2026-02-14": "workday",  # 周六调休上班
    "2026-02-15": "holiday",
    "2026-02-16": "holiday",
    "2026-02-17": "holiday",
    "2026-02-18": "holiday",
    "2026-02-19": "holiday",
    "2026-02-20": "holiday",
    "2026-02-21": "holiday",
    "2026-02-22": "holiday",
    "2026-02-28": "workday",  # 周六调休上班
    # 清明 4.4-4.6（周日-周二，4.4 周日本身就是周末）
    "2026-04-04": "holiday",
    "2026-04-05": "holiday",
    "2026-04-06": "holiday",
    # 劳动节 5.1-5.5（5.1 周五，连休 5 天，4.26 周日调休上班）
    "2026-04-26": "workday",
    "2026-05-01": "holiday",
    "2026-05-02": "holiday",
    "2026-05-03": "holiday",
    "2026-05-04": "holiday",
    "2026-05-05": "holiday",
    # 端午 6.19-6.21（周五-周日，无调休）
    "2026-06-19": "holiday",
    "2026-06-20": "holiday",
    "2026-06-21": "holiday",
    # 中秋 9.25-9.27（周五-周日，无调休）
    "2026-09-25": "holiday",
    "2026-09-26": "holiday",
    "2026-09-27": "holiday",
    # 国庆 10.1-10.8（连休 8 天，9.27 周日已为中秋假期，10.10 周六调休上班）
    "2026-10-01": "holiday",
    "2026-10-02": "holiday",
    "2026-10-03": "holiday",
    "2026-10-04": "holiday",
    "2026-10-05": "holiday",
    "2026-10-06": "holiday",
    "2026-10-07": "holiday",
    "2026-10-08": "holiday",
    "2026-10-10": "workday",  # 周六调休上班
}


def is_holiday(d: date, manual_overrides: dict[str, str] | None = None) -> bool:
    """判断给定日期是否为非工作日（节假日或周末）。

    Args:
        d: 要判断的日期
        manual_overrides: 手动覆盖字典 {"YYYY-MM-DD": "holiday"/"workday"}

    Returns:
        True = 非工作日（放假），False = 工作日（上班）
    """
    key = d.strftime("%Y-%m-%d")

    # 1. 手动覆盖优先
    if manual_overrides and key in manual_overrides:
        return manual_overrides[key] == "holiday"

    # 2. 内置节假日表
    if key in HOLIDAYS:
        return HOLIDAYS[key] == "holiday"

    # 3. 周末判断（周六=5, 周日=6）
    return d.weekday() >= 5


def get_holiday_name(d: date) -> str | None:
    """获取节假日名称（用于前端展示），非节假日返回 None。"""
    names = {
        (1, 1): "元旦",
        # 春节根据农历变化，简化处理
        (4, 4): "清明节", (4, 5): "清明节", (4, 6): "清明节",
        (5, 1): "劳动节", (5, 2): "劳动节", (5, 3): "劳动节", (5, 4): "劳动节", (5, 5): "劳动节",
        (10, 1): "国庆节", (10, 2): "国庆节", (10, 3): "国庆节",
    }
    # 端午、中秋等农历节日在 HOLIDAYS 中已标记，这里简化返回"法定节假日"
    key = d.strftime("%Y-%m-%d")
    if key in HOLIDAYS and HOLIDAYS[key] == "holiday":
        # 尝试匹配月日
        md = (d.month, d.day)
        if md in names:
            return names[md]
        if d.month == 2:
            return "春节"
        if d.month == 6 and 18 <= d.day <= 22:
            return "端午节"
        if d.month == 9 and 24 <= d.day <= 27:
            return "中秋节"
        return "法定节假日"
    if d.weekday() >= 5 and key not in HOLIDAYS:
        return "周末"
    return None
