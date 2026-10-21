"""流水线组件基类与流转对象。

范式化流水线五步（每步可插拔组件，按 config 构造）：
    预处理插件链 → ①Parser → ②Filter → ③Enricher → ④Translator → ⑤Normalizer

- ``PipelineData``：单条 RawEvent 在流水线中的累积状态；
- ``BaseStage``：步骤抽象，``process(data, sink, db)`` 原地更新 data。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional

from ..events import NormalizedEvent, RawEvent


@dataclass
class PipelineData:
    """流水线流转对象（一条原始事件的完整处理上下文）。"""

    event: RawEvent
    # 预处理器输出（dict 或 list[dict]）
    payload: Any = None
    # 预处理展开后的逐条 dict（Parser 的输入）
    items: list[dict] = field(default_factory=list)
    # Parser 产出（成功/部分成功的 ParseResult，与 normalized 一一对应）
    results: list = field(default_factory=list)
    # 与 results 平行的一一对应 NormalizedEvent（Filter/Enricher/Translator 操作对象）
    normalized: list[NormalizedEvent] = field(default_factory=list)
    # Filter 累计丢弃条数（写指标用）
    dropped: int = 0
    # Parser 阶段挂载的引擎句柄与统计上下文（Normalizer 复用）
    engine: Any = None
    stat_hour: str = ""
    pinned_strategy: Optional[dict] = None


class BaseStage(ABC):
    """流水线步骤基类（config 驱动构造）。"""

    # 步骤名（StageRegistry 注册键）
    name: ClassVar[str] = ""

    def __init__(self, config: dict) -> None:
        self.config = config or {}

    @abstractmethod
    def process(self, data: PipelineData, sink, db) -> None:
        """原地更新 data（不可变约定：不返回新对象）。"""
