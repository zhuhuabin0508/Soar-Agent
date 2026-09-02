"""枚举翻译。

按策略 ``enum_maps`` 把 int 枚举值翻译为中文，写入对应的 ``*_name`` 字段。
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def translate(
    fields: dict[str, Any],
    enum_specs: list[dict],
    enum_maps: dict[str, dict[str, str]],
) -> None:
    """就地翻译枚举字段。

    Args:
        fields: 字段映射产出的目标字段 dict（会被就地修改）。
        enum_specs: 字段映射阶段带出的枚举规格，
            ``[{"target": "risk_level", "enum_map": "RISK_LEVEL", "enum_target": "risk_level_name"}]``。
        enum_maps: 策略定义的枚举表，``{"RISK_LEVEL": {"0": "严重", ...}}``。
    """
    for spec in enum_specs or []:
        target = spec.get("target") or ""
        enum_map_name = spec.get("enum_map") or ""
        enum_target = spec.get("enum_target") or ""
        if not target or not enum_map_name or not enum_target:
            continue

        table = (enum_maps or {}).get(enum_map_name) or {}
        raw_value = fields.get(target)

        # 枚举表键统一为字符串比较
        key = str(raw_value)
        translated = table.get(key)
        if translated is None:
            # 未命中翻译表 → 空字符串（不记警告，未配置的枚举属正常情况）
            translated = ""
            logger.debug(
                "枚举翻译未命中: map=%s key=%s（字段 %s）", enum_map_name, key, target,
            )
        else:
            logger.debug("枚举翻译: %s[%s] → %s（%s）", enum_map_name, key, translated, enum_target)

        fields[enum_target] = translated
