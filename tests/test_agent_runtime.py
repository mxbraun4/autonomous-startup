"""Tests for AgentRuntime: success path, errors, budget, persistence, tool calls."""

import pytest

from src.framework.contracts import RunConfig, TaskSpec
from src.framework.errors import BudgetExhaustedError
from src.framework.types import ErrorCategory, TaskStatus, ToolCallStatus
from src.framework.runtime.agent_runtime import AgentRuntime
from src.framework.runtime.capability_registry import CapabilityRegistry
from src.framework.runtime.execution_context import ExecutionContext
from src.framework.runtime.task_router import TaskRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime(
    agent_fn=None,
    caps=None,
    budget_tokens=None,
    budget_seconds=None,
    max_steps=100,
    store=None,
    policy_engine=None,
    event_emitter=None,
):
    """Build a minimal runtime with one agent and optional tool registrations."""
    caps = caps or []
    registry = CapabilityRegistry()
    for cap, fn in caps:
        registry.register(cap, f"tool_{cap}", fn)

    router = TaskRouter(registry)
    if agent_fn is None:
        agent_fn = lambda task_spec, tools, context: {"output_text": "done", "tokens_used": 10}
    router.register_agent("a1", "Worker", [c for c, _ in caps], agent_instance=agent_fn)

    rc = RunConfig(
        run_id="r1",
        seed=42,
        budget_tokens=budget_tokens,
        budget_seconds=budget_seconds,
        max_steps_per_cycle=max_steps,
    )
    ctx = ExecutionContext(rc, store=store)

    return AgentRuntime(
        registry=registry,
        router=router,
        store=store,
        context=ctx,
        policy_engine=policy_engine,
        event_emitter=event_emitter,
    )


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestAgentRuntimeSuccess:
    def test_execute_task_returns_completed(self):
        rt = _make_runtime()
        task = TaskSpec(task_id="t1", objective="Do work", agent_role="Worker")
        result = rt.execute_task(task)
        assert result.task_status == TaskStatus.COMPLETED
        assert result.task_id == "t1"
        assert result.agent_id == "a1"
        assert result.output_text == "done"
        assert result.tokens_used == 10
        assert result.duration_seconds >= 0

    def test_execute_task_with_dict_output(self):
        def agent_fn(task_spec, tools, context):
            return {"output_text": "calculated", "tokens_used": 50, "result": 42}

        rt = _make_runtime(agent_fn=agent_fn)
        task = TaskSpec(task_id="t2", agent_role="Worker")
        result = rt.execute_task(task)
        assert result.task_status == TaskStatus.COMPLETED
        assert result.output["result"] == 42

    def test_execute_task_with_non_dict_output(self):
        def agent_fn(task_spec, tools, context):
            return "simple string result"

        rt = _make_runtime(agent_fn=agent_fn)
        task = TaskSpec(task_id="t3", agent_role="Worker")
        result = rt.execute_task(task)
        assert result.task_status == TaskStatus.COMPLETED
        assert "simple string result" in result.output_text


# ---------------------------------------------------------------------------
# Unresolvable capability
# ---------------------------------------------------------------------------


class TestAgentRuntimeUnresolvable:
    def test_unresolved_capability_fails(self):
        rt = _make_runtime()
        task = TaskSpec(
            task_id="t4",
            agent_role="Worker",
            required_capabilities=["magic_power"],
        )
        result = rt.execute_task(task)
        assert result.task_status == TaskStatus.FAILED
        assert result.error_category == ErrorCategory.UNRESOLVABLE_CAPABILITY
        assert "magic_power" in result.error


# ---------------------------------------------------------------------------
# Budget exhaustion
# ---------------------------------------------------------------------------


class TestAgentRuntimeBudget:
    def test_budget_exhausted_returns_failed(self):
        def greedy_agent(task_spec, tools, context):
            return {"output_text": "greedy", "tokens_used": 999}

        rt = _make_runtime(agent_fn=greedy_agent, budget_tokens=5, max_steps=1)
        # First task will succeed (budget checked at begin_step, still has tokens)
        task1 = TaskSpec(task_id="t_first", agent_role="Worker")
        r1 = rt.execute_task(task1)
        # Now budget is exhausted, next call should fail
        task2 = TaskSpec(task_id="t_second", agent_role="Worker")
        r2 = rt.execute_task(task2)
        assert r2.task_status == TaskStatus.FAILED
        assert r2.error_category == ErrorCategory.BUDGET_EXCEEDED

    def test_step_limit_returns_failed(self):
        rt = _make_runtime(max_steps=1)
        t1 = TaskSpec(task_id="t1", agent_role="Worker")
        t2 = TaskSpec(task_id="t2", agent_role="Worker")
        r1 = rt.execute_task(t1)
        assert r1.task_status == TaskStatus.COMPLETED
        r2 = rt.execute_task(t2)
        assert r2.task_status == TaskStatus.FAILED
        assert r2.error_category == ErrorCategory.BUDGET_EXCEEDED


# ---------------------------------------------------------------------------
# Agent exceptions
# ---------------------------------------------------------------------------


class TestAgentRuntimeExceptions:
    def test_agent_exception_returns_transient(self):
        def failing_agent(task_spec, tools, context):
            raise ValueError("something broke")

        rt = _make_runtime(agent_fn=failing_agent)
        task = TaskSpec(task_id="t5", agent_role="Worker")
        result = rt.execute_task(task)
        assert result.task_status == TaskStatus.FAILED
        assert result.error_category == ErrorCategory.TRANSIENT
        assert "something broke" in result.error


# ---------------------------------------------------------------------------
# Tool call execution
# ---------------------------------------------------------------------------


class TestAgentRuntimeToolCall:
    def test_tool_call_success(self):
        def search_tool(query=""):
            return {"results": [query]}

        rt = _make_runtime(caps=[("web_search", search_tool)])
        tc = rt.execute_tool_call(
            tool_name="search_v1",
            capability="web_search",
            arguments={"query": "fintech"},
            agent_id="a1",
            task_id="t1",
        )
        assert tc.call_status == ToolCallStatus.SUCCESS
        assert tc.result == {"results": ["fintech"]}
        assert tc.policy_check_passed is True
        assert tc.duration_ms >= 0

    def test_tool_call_error(self):
        def broken_tool(**kwargs):
            raise RuntimeError("tool broke")

        rt = _make_runtime(caps=[("broken_cap", broken_tool)])
        tc = rt.execute_tool_call(
            tool_name="broken",
            capability="broken_cap",
            arguments={},
            agent_id="a1",
            task_id="t1",
        )
        assert tc.call_status == ToolCallStatus.ERROR
        assert "tool broke" in tc.error_message

    def test_tool_call_no_tool_found(self):
        rt = _make_runtime()
        tc = rt.execute_tool_call(
            tool_name="unknown",
            capability="nonexistent_cap",
            arguments={},
            agent_id="a1",
            task_id="t1",
        )
        assert tc.call_status == ToolCallStatus.ERROR
        assert "No tool found" in tc.error_message

    def test_tool_call_budget_exceeded(self):
        def dummy_tool(**kw):
            return "ok"

        rt = _make_runtime(caps=[("cap", dummy_tool)], budget_tokens=10)
        # Exhaust the budget
        rt._context.run_context.budget_remaining_tokens = 0
        tc = rt.execute_tool_call(
            tool_name="t",
            capability="cap",
            arguments={},
            agent_id="a1",
            task_id="t1",
        )
        assert tc.call_status == ToolCallStatus.BUDGET_EXCEEDED


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------


class TestAgentRuntimePolicy:
    def test_tool_denied_by_policy(self):
        class DenyAll:
            def check(self, tool_name, capability, arguments):
                return False

        def dummy_tool(**kw):
            return "ok"

        rt = _make_runtime(caps=[("cap", dummy_tool)], policy_engine=DenyAll())
        tc = rt.execute_tool_call(
            tool_name="t",
            capability="cap",
            arguments={},
            agent_id="a1",
            task_id="t1",
        )
        assert tc.call_status == ToolCallStatus.DENIED
        assert tc.policy_check_passed is False
        assert tc.denied_reason is not None


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


class TestAgentRuntimeEvents:
    def test_events_emitted_on_success(self):
        events = []

        class Collector:
            def emit(self, event_type, payload):
                events.append((event_type, payload))

        rt = _make_runtime(event_emitter=Collector())
        task = TaskSpec(task_id="t1", agent_role="Worker")
        rt.execute_task(task)
        assert any(e[0] == "task_completed" for e in events)

    def test_events_emitted_on_failure(self):
        events = []

        class Collector:
            def emit(self, event_type, payload):
                events.append((event_type, payload))

        def failing(task_spec, tools, context):
            raise ValueError("oops")

        rt = _make_runtime(agent_fn=failing, event_emitter=Collector())
        task = TaskSpec(task_id="t1", agent_role="Worker")
        rt.execute_task(task)
        assert any(e[0] == "task_failed" for e in events)


# ---------------------------------------------------------------------------
# Episode persistence (integration with store)
# ---------------------------------------------------------------------------


class TestAgentRuntimePersistence:
    def test_episode_persisted_to_store(self):
        recorded = []

        class FakeStore:
            def ep_record(self, episode):
                recorded.append(episode)
                return episode.entity_id

        store = FakeStore()
        rt = _make_runtime(store=store)
        task = TaskSpec(task_id="t1", objective="Test persistence", agent_role="Worker")
        result = rt.execute_task(task)
        assert result.task_status == TaskStatus.COMPLETED
        assert len(recorded) == 1
        ep = recorded[0]
        assert ep.agent_id == "a1"
        assert ep.success is True
        assert ep.context["task_id"] == "t1"

    def test_store_failure_does_not_break_runtime(self):
        class BrokenStore:
            def ep_record(self, episode):
                raise RuntimeError("store is down")

        rt = _make_runtime(store=BrokenStore())
        task = TaskSpec(task_id="t1", agent_role="Worker")
        result = rt.execute_task(task)
        # Should still return success — persistence failure is non-fatal
        assert result.task_status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Full integration test (no real store, but end-to-end runtime)
# ---------------------------------------------------------------------------


class TestAgentRuntimeIntegration:
    def test_full_lifecycle(self):
        """End-to-end: register tools, register agent, execute task, verify result."""
        episodes = []

        class MockStore:
            def ep_record(self, episode):
                episodes.append(episode)
                return episode.entity_id

        events = []

        class EventCollector:
            def emit(self, event_type, payload):
                events.append((event_type, payload))

        def search_tool(query=""):
            return {"urls": ["http://example.com"]}

        def save_tool(data=None):
            return {"saved": True}

        def my_agent(task_spec, tools, context):
            return {
                "output_text": f"Found results for {task_spec.objective}",
                "tokens_used": 100,
                "result": {"count": 5},
            }

        registry = CapabilityRegistry()
        registry.register("web_search", "search_startups", search_tool)
        registry.register("database_write", "save_startup", save_tool)

        router = TaskRouter(registry)
        router.register_agent(
            "data_expert",
            "Data Strategy Expert",
            ["web_search", "database_write"],
            agent_instance=my_agent,
        )

        rc = RunConfig(run_id="integration_test", seed=42, budget_tokens=10000, max_steps_per_cycle=50)
        ctx = ExecutionContext(rc, store=MockStore())

        runtime = AgentRuntime(
            registry=registry,
            router=router,
            store=MockStore(),
            context=ctx,
            event_emitter=EventCollector(),
        )

        task = TaskSpec(
            task_id="find_startups",
            objective="Find fintech startups",
            agent_role="Data Strategy Expert",
            required_capabilities=["web_search", "database_write"],
        )

        result = runtime.execute_task(task)

        # Verify result
        assert result.task_status == TaskStatus.COMPLETED
        assert result.agent_id == "data_expert"
        assert result.tokens_used == 100
        assert "Found results" in result.output_text

        # Verify context updated
        assert ctx.run_context.step_count == 1

        # Verify event emitted
        assert len(events) >= 1
        assert events[-1][0] == "task_completed"

    def test_delegation_depth_exceeded(self):
        rt = _make_runtime()
        task = TaskSpec(
            task_id="t1",
            agent_role="Worker",
            delegated_by="parent_task",
        )
        # Default max_delegation_depth is 3, depth of 1 should be fine
        result = rt.execute_task(task)
        assert result.task_status == TaskStatus.COMPLETED

    def test_delegation_depth_exceeded_fails(self):
        """When delegation depth > max_delegation_depth, task should fail."""
        registry = CapabilityRegistry()
        router = TaskRouter(registry)
        router.register_agent(
            "a1", "Worker", [],
            agent_instance=lambda task_spec, tools, context: {"output_text": "ok"},
        )
        rc = RunConfig(run_id="r1", seed=1, max_delegation_depth=0)  # no delegation allowed
        ctx = ExecutionContext(rc)
        runtime = AgentRuntime(registry=registry, router=router, context=ctx)

        task = TaskSpec(
            task_id="t1",
            agent_role="Worker",
            delegated_by="parent",
        )
        result = runtime.execute_task(task)
        assert result.task_status == TaskStatus.FAILED
        assert result.error_category == ErrorCategory.POLICY_VIOLATION
        assert "Delegation depth" in result.error
