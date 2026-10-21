"""范式化流水线包：预处理插件链 + 六步可插拔组件 + Runner。

六步：Parser → Filter → Enricher → Translator → AlertRule → Normalizer
（组件均按 StageRegistry 模式注册，新增步骤零侵入）。
"""
from .alert_rule_stage import (
    RISK_LEVEL_NAMES,
    AlertRuleStage,
    invalidate_alert_rules_cache,
    load_enabled_rules,
    match_alert_rules,
    render_name_template,
)
from .base_stage import BaseStage, PipelineData
from .enricher_stage import EnricherStage, enricher_registry
from .filter_stage import FilterStage
from .normalizer_stage import NormalizerStage
from .parser_stage import ParserStage
from .preprocessors import (
    DEFAULT_PREPROCESSOR_CHAIN,
    _coerce_payload,
    _unescape_qt_value,
    parse_qingteng_syslog,
    run_preprocessor_chain,
)
from .runner import PipelineRunner, get_default_config, run_pipeline_for_event
from .sink import ReceiverSink, _bump_counts, _summarize_large_value
from .translator_stage import TranslatorStage

__all__ = [
    "BaseStage",
    "PipelineData",
    "ParserStage",
    "FilterStage",
    "EnricherStage",
    "TranslatorStage",
    "AlertRuleStage",
    "NormalizerStage",
    "invalidate_alert_rules_cache",
    "load_enabled_rules",
    "match_alert_rules",
    "render_name_template",
    "RISK_LEVEL_NAMES",
    "enricher_registry",
    "PipelineRunner",
    "run_pipeline_for_event",
    "get_default_config",
    "ReceiverSink",
    "parse_qingteng_syslog",
    "_coerce_payload",
    "_unescape_qt_value",
    "run_preprocessor_chain",
    "DEFAULT_PREPROCESSOR_CHAIN",
    "_bump_counts",
    "_summarize_large_value",
]
