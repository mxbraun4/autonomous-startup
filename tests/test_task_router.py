"""Tests for TaskRouter: routing by role, capability overlap, error cases."""

import pytest

from src.framework.contracts import TaskSpec
from src.framework.errors import TaskRoutingError
from src.framework.runtime.capability_registry import CapabilityRegistry
from src.framework.runtime.task_router import TaskRouter


def _noop(**kw):
    return None


def _make_registry_with_caps(*caps):
    """Create a registry with dummy tools for the given capabilities."""
    reg = CapabilityRegistry()
    for cap in caps:
        reg.register(cap, f"tool_{cap}", _noop)
    return reg


class TestTaskRouterRouteByRole:
    def test_route_by_exact_role(self):
        reg = _make_registry_with_caps("web_search")
        router = TaskRouter(reg)
        router.register_agent("a1", "Data Expert", ["web_search"])
        router.register_agent("a2", "Outreach Expert", ["email_send"])

        task = TaskSpec(
            objective="Find startups",
            agent_role="Data Expert",
            required_capabilities=["web_search"],
        )
        decision = router.route(task)
        assert decision.agent_id == "a1"
        assert decision.agent_role == "Data Expert"
        assert decision.can_execute is True
        assert decision.unresolved_capabilities == []

    def test_route_picks_best_overlap_among_role_matches(self):
        reg = _make_registry_with_caps("web_search", "db_read", "db_write")
        router = TaskRouter(reg)
        router.register_agent("a1", "Data Expert", ["web_search"])
        router.register_agent("a2", "Data Expert", ["web_search", "db_read", "db_write"])

        task = TaskSpec(
            agent_role="Data Expert",
            required_capabilities=["web_search", "db_read"],
        )
        decision = router.route(task)
        assert decision.agent_id == "a2"


class TestTaskRouterRouteByCapability:
    def test_fallback_to_capability_overlap(self):
        reg = _make_registry_with_caps("analytics")
        router = TaskRouter(reg)
        router.register_agent("a1", "Data Expert", ["web_search"])
        router.register_agent("a2", "Analyst", ["analytics"])

        task = TaskSpec(
            agent_role="Unknown Role",
            required_capabilities=["analytics"],
        )
        decision = router.route(task)
        assert decision.agent_id == "a2"


class TestTaskRouterUnresolved:
    def test_unresolved_capabilities(self):
        reg = _make_registry_with_caps("web_search")  # only web_search in registry
        router = TaskRouter(reg)
        router.register_agent("a1", "Data Expert", ["web_search", "magic_power"])

        task = TaskSpec(
            agent_role="Data Expert",
            required_capabilities=["web_search", "magic_power"],
        )
        decision = router.route(task)
        assert decision.can_execute is False
        assert "magic_power" in decision.unresolved_capabilities


class TestTaskRouterNoAgents:
    def test_no_agents_raises(self):
        reg = CapabilityRegistry()
        router = TaskRouter(reg)
        task = TaskSpec(agent_role="Any", required_capabilities=[])
        with pytest.raises(TaskRoutingError, match="No agents registered"):
            router.route(task)


class TestTaskRouterListAgents:
    def test_list_agents(self):
        reg = CapabilityRegistry()
        router = TaskRouter(reg)
        router.register_agent("a1", "Expert", ["cap1"])
        router.register_agent("a2", "Manager", ["cap2"])
        agents = router.list_agents()
        assert len(agents) == 2
        ids = {a.agent_id for a in agents}
        assert ids == {"a1", "a2"}


class TestTaskRouterEmptyCapabilities:
    def test_empty_required_capabilities(self):
        reg = CapabilityRegistry()
        router = TaskRouter(reg)
        router.register_agent("a1", "Worker", [])

        task = TaskSpec(agent_role="Worker", required_capabilities=[])
        decision = router.route(task)
        assert decision.can_execute is True
        assert decision.resolved_tools == []
        assert decision.unresolved_capabilities == []
