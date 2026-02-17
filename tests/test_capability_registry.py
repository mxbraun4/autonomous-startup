"""Tests for CapabilityRegistry: register, resolve, priority, list ops."""

from src.framework.runtime.capability_registry import CapabilityRegistry, RegisteredTool


def _dummy_tool_a(**kwargs):
    return "result_a"


def _dummy_tool_b(**kwargs):
    return "result_b"


def _dummy_tool_c(**kwargs):
    return "result_c"


class TestCapabilityRegistry:
    def test_register_and_resolve(self):
        reg = CapabilityRegistry()
        reg.register("web_search", "search_v1", _dummy_tool_a)
        tools = reg.resolve("web_search")
        assert len(tools) == 1
        assert tools[0].tool_name == "search_v1"
        assert tools[0].capability == "web_search"

    def test_priority_ordering(self):
        reg = CapabilityRegistry()
        reg.register("web_search", "slow_search", _dummy_tool_a, priority=10)
        reg.register("web_search", "fast_search", _dummy_tool_b, priority=1)
        reg.register("web_search", "mid_search", _dummy_tool_c, priority=5)
        tools = reg.resolve("web_search")
        assert [t.tool_name for t in tools] == ["fast_search", "mid_search", "slow_search"]

    def test_resolve_best(self):
        reg = CapabilityRegistry()
        reg.register("db_write", "tool_high", _dummy_tool_a, priority=10)
        reg.register("db_write", "tool_low", _dummy_tool_b, priority=1)
        best = reg.resolve_best("db_write")
        assert best is not None
        assert best.tool_name == "tool_low"

    def test_resolve_best_unknown(self):
        reg = CapabilityRegistry()
        assert reg.resolve_best("nonexistent") is None

    def test_resolve_unknown_returns_empty(self):
        reg = CapabilityRegistry()
        assert reg.resolve("nonexistent") == []

    def test_list_capabilities(self):
        reg = CapabilityRegistry()
        reg.register("web_search", "s1", _dummy_tool_a)
        reg.register("db_read", "s2", _dummy_tool_b)
        caps = reg.list_capabilities()
        assert set(caps) == {"web_search", "db_read"}

    def test_list_tools_all(self):
        reg = CapabilityRegistry()
        reg.register("web_search", "s1", _dummy_tool_a)
        reg.register("db_read", "s2", _dummy_tool_b)
        all_tools = reg.list_tools()
        assert len(all_tools) == 2

    def test_list_tools_by_capability(self):
        reg = CapabilityRegistry()
        reg.register("web_search", "s1", _dummy_tool_a)
        reg.register("web_search", "s2", _dummy_tool_b)
        reg.register("db_read", "s3", _dummy_tool_c)
        ws_tools = reg.list_tools("web_search")
        assert len(ws_tools) == 2
        assert reg.list_tools("db_read") == [reg.list_tools("db_read")[0]]

    def test_callable_invocation(self):
        reg = CapabilityRegistry()
        reg.register("web_search", "s1", _dummy_tool_a)
        tool = reg.resolve_best("web_search")
        assert tool is not None
        result = tool.tool_callable()
        assert result == "result_a"

    def test_metadata(self):
        reg = CapabilityRegistry()
        reg.register("web_search", "s1", _dummy_tool_a, metadata={"desc": "search tool"})
        tool = reg.resolve_best("web_search")
        assert tool is not None
        assert tool.metadata["desc"] == "search tool"

    def test_empty_registry(self):
        reg = CapabilityRegistry()
        assert reg.list_capabilities() == []
        assert reg.list_tools() == []
