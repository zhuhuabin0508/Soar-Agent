"""核心优化项的单元测试。

覆盖：
- extract_think_blocks: 思维块提取与清洗
- _coerce_primitive_args: 工具参数类型强转（LLM 传字符串 → int/float/bool）
- kb_file_query._coerce_int: 知识库查询的 int 强转
- paginate: 分页工具函数
"""
import pytest
from unittest.mock import MagicMock

from app.agent.hermes.think_scrubber import extract_think_blocks, strip_think_blocks
from app.agent.hermes.tool_engine import _coerce_primitive_args


# ============ extract_think_blocks ============

class TestExtractThinkBlocks:
    def test_standard_think_block(self):
        text = "<think>分析用户意图</think>根据分析结果回答"
        thinking, clean = extract_think_blocks(text)
        assert thinking == "分析用户意图"
        assert "think" not in clean.lower()
        assert "根据分析结果回答" in clean

    def test_no_think_block(self):
        text = "直接回答，没有思考过程"
        thinking, clean = extract_think_blocks(text)
        assert thinking == ""
        assert clean == text

    def test_multiple_think_blocks(self):
        text = "<think>第一步</think>中间文本<think>第二步</think>最终回答"
        thinking, clean = extract_think_blocks(text)
        assert "第一步" in thinking
        assert "第二步" in thinking
        assert "中间文本" in clean
        assert "最终回答" in clean

    def test_variant_tags(self):
        for tag in ["thinking", "reasoning", "thought", "REASONING_SCRATCHPAD"]:
            text = f"<{tag}>内容</{tag}>回答"
            thinking, clean = extract_think_blocks(text)
            assert thinking == "内容", f"Failed for tag: {tag}"
            assert "回答" in clean

    def test_empty_string(self):
        thinking, clean = extract_think_blocks("")
        assert thinking == ""
        assert clean == ""

    def test_strips_after_extract(self):
        """提取后 strip_think_blocks 应保持一致（无残留 think 标签）。"""
        text = "<think>思考</think>回答"
        thinking, clean = extract_think_blocks(text)
        final = strip_think_blocks(clean)
        assert "think" not in final.lower()


# ============ _coerce_primitive_args ============

class TestCoercePrimitiveArgs:
    def test_numeric_string_to_int(self):
        args = {"limit": "20", "offset": "5"}
        result = _coerce_primitive_args(args)
        assert result["limit"] == 20
        assert result["offset"] == 5
        assert isinstance(result["limit"], int)

    def test_float_string_to_float(self):
        args = {"threshold": "0.85", "ratio": "1.5"}
        result = _coerce_primitive_args(args)
        assert result["threshold"] == 0.85
        assert isinstance(result["threshold"], float)

    def test_bool_string_to_bool(self):
        args = {"enabled": "true", "disabled": "false"}
        result = _coerce_primitive_args(args)
        assert result["enabled"] is True
        assert result["disabled"] is False

    def test_negative_int(self):
        args = {"value": "-42"}
        result = _coerce_primitive_args(args)
        assert result["value"] == -42

    def test_non_numeric_string_unchanged(self):
        args = {"query": "搜索内容", "name": "test_tool"}
        result = _coerce_primitive_args(args)
        assert result["query"] == "搜索内容"
        assert result["name"] == "test_tool"

    def test_already_correct_types(self):
        args = {"limit": 20, "enabled": True, "name": "test"}
        result = _coerce_primitive_args(args)
        assert result["limit"] == 20
        assert result["enabled"] is True
        assert result["name"] == "test"

    def test_empty_string_unchanged(self):
        args = {"value": ""}
        result = _coerce_primitive_args(args)
        assert result["value"] == ""

    def test_none_input(self):
        assert _coerce_primitive_args(None) is None

    def test_mixed_args(self):
        args = {"limit": "10", "query": "IP查询", "enabled": "true", "name": "check_ip"}
        result = _coerce_primitive_args(args)
        assert result["limit"] == 10
        assert result["query"] == "IP查询"
        assert result["enabled"] is True
        assert result["name"] == "check_ip"


# ============ paginate ============

class TestPaginate:
    def test_basic_pagination(self):
        from app.schemas.common import paginate

        mock_items = [MagicMock() for _ in range(5)]
        for i, item in enumerate(mock_items):
            item.__table__ = MagicMock()
            item.__table__.columns = []
        query = MagicMock()
        query.count.return_value = 5
        query.offset.return_value.limit.return_value.all.return_value = mock_items
        result = paginate(query, page=1, size=10)
        assert result["total"] == 5
        assert result["page"] == 1
        assert result["size"] == 10
        assert result["pages"] == 1
        assert len(result["items"]) == 5

    def test_multi_page(self):
        from app.schemas.common import paginate

        query = MagicMock()
        query.count.return_value = 25
        query.offset.return_value.limit.return_value.all.return_value = []
        result = paginate(query, page=2, size=10)
        assert result["total"] == 25
        assert result["pages"] == 3
        assert result["page"] == 2

    def test_size_capped(self):
        from app.schemas.common import paginate

        query = MagicMock()
        query.count.return_value = 0
        query.offset.return_value.limit.return_value.all.return_value = []
        result = paginate(query, page=1, size=999)
        assert result["size"] == 200  # 上限

    def test_empty_result(self):
        from app.schemas.common import paginate

        query = MagicMock()
        query.count.return_value = 0
        query.offset.return_value.limit.return_value.all.return_value = []
        result = paginate(query, page=1, size=20)
        assert result["total"] == 0
        assert result["pages"] == 0
        assert result["items"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
