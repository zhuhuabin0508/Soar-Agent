"""④ Translator 阶段：跨设备标准词表补填（仅当目标字段为空时生效）。

与策略级 enum_maps 的分工：策略管厂商私有词表（不变），本阶段管跨设备
标准词表（config 驱动）。默认 maps 为空 → 不补填任何值（行为等价）。

config 结构::

    {
      "maps": {
        "risk_level_name": {"0": "严重", "1": "高危", "2": "中危", "3": "低危", "4": "信息"},
        "deal_status_name": {"0": "未处置", "1": "已处置"}
      },
      "sources": {"risk_level_name": "risk_level", "deal_status_name": "deal_status"}
    }

``sources[key]`` 声明取值来源字段（默认尝试与 key 同名去掉 _name 后缀的字段）。
"""
import logging

from ..registry import stage_registry
from .base_stage import BaseStage, PipelineData

logger = logging.getLogger(__name__)


@stage_registry.register
class TranslatorStage(BaseStage):
    """标准词表补填步骤（仅补空值，不覆盖策略已翻译的字段）。"""

    name = "translator"

    def process(self, data: PipelineData, sink, db) -> None:
        maps = self.config.get("maps") or {}
        if not maps:
            return
        sources = self.config.get("sources") or {}
        for norm in data.normalized:
            for target_key, table in maps.items():
                if norm.get_field(target_key) not in (None, ""):
                    continue  # 已有值（策略翻译过）不覆盖
                src_key = sources.get(target_key) or target_key
                src_val = norm.get_field(src_key)
                if src_val in (None, ""):
                    # 默认约定：xxx_name ← xxx
                    if src_key.endswith("_name"):
                        src_key = src_key[: -len("_name")]
                        src_val = norm.get_field(src_key)
                if src_val in (None, ""):
                    continue
                translated = table.get(str(src_val))
                if translated is not None:
                    norm.set_field(target_key, translated)
