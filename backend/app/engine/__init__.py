"""策略驱动的安全告警解析入库引擎。

引擎本身不针对任何具体设备，通过「解析策略」描述不同设备/厂商的告警日志格式。
新增设备时只需创建新策略，不需要修改引擎代码。

模块划分：
- strategy_loader：策略加载与路由匹配（内存缓存，策略变更时刷新）
- field_mapper：字段映射与类型转换
- enum_translator：枚举翻译
- validator：校验规则执行
- parser_engine：解析流水线调度（入库通过依赖注入，可脱离数据库独立运行）
"""
from app.engine.parser_engine import ParseEngine, ParseResult
from app.engine.strategy_loader import StrategyLoader

__all__ = ["ParseEngine", "ParseResult", "StrategyLoader"]
