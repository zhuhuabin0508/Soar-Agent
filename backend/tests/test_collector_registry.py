"""采集子系统注册表单测：适配器注册/查找/校验（不依赖 DB）。

运行：docker exec soar-backend-dev python -m pytest /app/tests/test_collector_registry.py -v
"""
import os
import sys

sys.path.insert(0, "/app" if os.path.isdir("/app") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.log_receiver_manager import adapter_registry, preprocessor_registry, stage_registry
from app.core.log_receiver_manager.adapters.syslog_adapter import SyslogAdapter
from app.core.log_receiver_manager.adapters.kafka_adapter import KafkaAdapter
from app.core.log_receiver_manager.pipeline.filter_stage import FilterStage
from app.core.log_receiver_manager.pipeline.parser_stage import ParserStage


class TestAdapterRegistry:
    def test_syslog_kafka_registered(self):
        assert adapter_registry.get("syslog") is SyslogAdapter
        assert adapter_registry.get("kafka") is KafkaAdapter

    def test_get_unknown_returns_none(self):
        assert adapter_registry.get("no_such_type") is None
        assert adapter_registry.get(None) is None
        assert adapter_registry.get("") is None

    def test_source_types_metadata(self):
        types = {t["value"]: t for t in adapter_registry.source_types()}
        assert set(types) >= {"syslog", "kafka"}
        assert types["syslog"]["label"] == "Syslog 监听"
        assert isinstance(types["syslog"]["required_config_keys"], list)

    def test_ready_timeout_semantics(self):
        # syslog=绑定等待 3s，kafka=连接等待 8s（与原常量语义一致）
        assert SyslogAdapter.default_ready_timeout_s == 3.0
        assert KafkaAdapter.default_ready_timeout_s == 8.0

    def test_validate_config_unknown_protocol(self):
        errs = adapter_registry.validate_config("xxx", {})
        assert errs and "不支持的接收协议" in errs[0]

    def test_validate_config_declared_keys(self):
        class _FakeAdapter:
            source_type = "_fake"
            display_name = "fake"
            required_config_keys = [("url", "服务地址"), "token"]

        adapter_registry.register(_FakeAdapter)
        try:
            errs = adapter_registry.validate_config("_fake", {})
            assert len(errs) == 2
            assert "服务地址（url）未配置" in errs[0]
            assert "token 未配置" in errs[1]
            assert adapter_registry.validate_config("_fake", {"url": "http://x", "token": "t"}) == []
        finally:
            adapter_registry._items.pop("_fake", None)


class TestStageAndPreprocessorRegistry:
    def test_stages_registered(self):
        assert stage_registry.get("parser") is ParserStage
        assert stage_registry.get("filter") is FilterStage

    def test_preprocessors_registered(self):
        for name in ("json", "qingteng_syslog", "plain_message"):
            assert preprocessor_registry.get_callable(name) is not None
        assert preprocessor_registry.get_callable("nope") is None
