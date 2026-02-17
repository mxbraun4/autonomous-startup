"""Comprehensive tests for Layer D — Orchestration Kernel.

Covers: RetryPolicy, TaskGraph, TaskNode, Scheduler, DelegationHandler,
Executor, CycleExecutionResult, error classes, and integration scenarios.
"""

import random
import time
from unittest.mock import MagicMock, patch

import pytest

from src.framework.contracts import RunConfig, TaskResult, TaskSpec
from src.framework.errors import (
    CycleDetectedError,
    DeadlockError,
    OrchestrationError,
)
from src.framework.types import ErrorCategory, TaskStatus

from src.framework.orchestration.retry_policy import RetryPolicy
from src.framework.orchestration.task_graph import TaskGraph, TaskNode
from src.framework.orchestration.scheduler import Scheduler
from src.framework.orchestration.delegation import DelegationHandler
from src.framework.orchestration.executor import CycleExecutionResult, Executor


# ======================================================================
# Helpers
# ======================================================================


def _make_spec(
    task_id: str,
    depends_on: list[str] | None = None,
    priority: int = 0,
    delegated_by: str | None = None,
    expected_output_schema: dict | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        objective=f"Do {task_id}",
        depends_on=depends_on or [],
        priority=priority,
        delegated_by=delegated_by,
        expected_output_schema=expected_output_schema,
    )


def _make_result(
    task_id: str,
    status: TaskStatus = TaskStatus.COMPLETED,
    error_category: ErrorCategory | None = None,
    output: dict | None = None,
) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        task_status=status,
        error_category=error_category,
        output=output or {},
    )


# ======================================================================
# Error classes
# ======================================================================


class TestOrchestrationErrors:
    def test_orchestration_error_hierarchy(self):
        e = OrchestrationError("test")
        assert isinstance(e, Exception)

    def test_cycle_detected_error_carries_path(self):
        e = CycleDetectedError(cycle_path=["a", "b", "c"])
        assert e.cycle_path == ["a", "b", "c"]
        assert "a" in str(e)
        assert "b" in str(e)

    def test_deadlock_error_carries_blocked(self):
        e = DeadlockError(blocked_tasks=["x", "y"])
        assert e.blocked_tasks == ["x", "y"]
        assert "x" in str(e)


# ======================================================================
# RetryPolicy
# ======================================================================


class TestRetryPolicy:
    def test_default_values(self):
        rp = RetryPolicy()
        assert rp.max_retries == 2
        assert rp.base_delay_seconds == 1.0
        assert rp.max_delay_seconds == 30.0

    def test_should_retry_transient_under_limit(self):
        rp = RetryPolicy(max_retries=3)
        result = _make_result("t1", TaskStatus.FAILED, ErrorCategory.TRANSIENT)
        assert rp.should_retry(result, current_retry_count=0) is True
        assert rp.should_retry(result, current_retry_count=2) is True

    def test_should_not_retry_at_limit(self):
        rp = RetryPolicy(max_retries=2)
        result = _make_result("t1", TaskStatus.FAILED, ErrorCategory.TRANSIENT)
        assert rp.should_retry(result, current_retry_count=2) is False

    def test_should_not_retry_permanent(self):
        rp = RetryPolicy()
        result = _make_result("t1", TaskStatus.FAILED, ErrorCategory.PERMANENT)
        assert rp.should_retry(result, current_retry_count=0) is False

    def test_should_not_retry_budget_exceeded(self):
        rp = RetryPolicy()
        result = _make_result("t1", TaskStatus.FAILED, ErrorCategory.BUDGET_EXCEEDED)
        assert rp.should_retry(result, current_retry_count=0) is False

    def test_should_not_retry_policy_violation(self):
        rp = RetryPolicy()
        result = _make_result("t1", TaskStatus.FAILED, ErrorCategory.POLICY_VIOLATION)
        assert rp.should_retry(result, current_retry_count=0) is False

    def test_max_retries_override(self):
        rp = RetryPolicy(max_retries=2)
        result = _make_result("t1", TaskStatus.FAILED, ErrorCategory.TRANSIENT)
        assert rp.should_retry(result, current_retry_count=0, max_retries_override=0) is False
        assert rp.should_retry(result, current_retry_count=4, max_retries_override=5) is True

    def test_compute_delay_exponential(self):
        rp = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=30.0)
        assert rp.compute_delay(0) == 1.0
        assert rp.compute_delay(1) == 2.0
        assert rp.compute_delay(2) == 4.0
        assert rp.compute_delay(3) == 8.0

    def test_compute_delay_capped(self):
        rp = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=5.0)
        assert rp.compute_delay(10) == 5.0

    def test_wait_calls_sleep(self):
        rp = RetryPolicy(base_delay_seconds=0.5)
        with patch("src.framework.orchestration.retry_policy.time.sleep") as mock_sleep:
            rp.wait(0)
            mock_sleep.assert_called_once_with(0.5)
            mock_sleep.reset_mock()
            rp.wait(1)
            mock_sleep.assert_called_once_with(1.0)


# ======================================================================
# TaskNode
# ======================================================================


class TestTaskNode:
    def test_defaults(self):
        spec = _make_spec("t1")
        node = TaskNode(task_spec=spec)
        assert node.status == TaskStatus.PENDING
        assert node.result is None
        assert node.retry_count == 0
        assert node.task_id == "t1"


# ======================================================================
# TaskGraph
# ======================================================================


class TestTaskGraph:
    def test_add_single_task(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        assert "a" in g.nodes

    def test_add_chain_dependencies(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
            _make_spec("c", depends_on=["b"]),
        ])
        assert len(g.nodes) == 3

    def test_cycle_detection_simple(self):
        with pytest.raises(CycleDetectedError):
            g = TaskGraph()
            g.add_tasks([
                _make_spec("a", depends_on=["b"]),
                _make_spec("b", depends_on=["a"]),
            ])

    def test_cycle_detection_three_nodes(self):
        with pytest.raises(CycleDetectedError):
            g = TaskGraph()
            g.add_tasks([
                _make_spec("a", depends_on=["c"]),
                _make_spec("b", depends_on=["a"]),
                _make_spec("c", depends_on=["b"]),
            ])

    def test_dangling_dependency(self):
        with pytest.raises(ValueError, match="unknown task"):
            g = TaskGraph()
            g.add_tasks([_make_spec("a", depends_on=["nonexistent"])])

    def test_get_ready_tasks_no_deps(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a"), _make_spec("b")])
        ready = g.get_ready_tasks()
        assert len(ready) == 2
        assert all(n.status == TaskStatus.READY for n in ready)

    def test_get_ready_tasks_with_deps(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
        ])
        ready = g.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == "a"

    def test_ready_after_dep_completed(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
        ])
        ready = g.get_ready_tasks()
        g.mark_running("a")
        g.mark_completed("a", _make_result("a"))
        ready2 = g.get_ready_tasks()
        assert len(ready2) == 1
        assert ready2[0].task_id == "b"

    def test_mark_running_from_ready(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        g.get_ready_tasks()
        g.mark_running("a")
        assert g.get_node("a").status == TaskStatus.RUNNING

    def test_mark_running_from_wrong_state_raises(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        with pytest.raises(AssertionError):
            g.mark_running("a")  # still PENDING, not READY

    def test_mark_completed(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        g.get_ready_tasks()
        g.mark_running("a")
        result = _make_result("a")
        g.mark_completed("a", result)
        node = g.get_node("a")
        assert node.status == TaskStatus.COMPLETED
        assert node.result == result

    def test_mark_failed(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        g.get_ready_tasks()
        g.mark_running("a")
        result = _make_result("a", TaskStatus.FAILED)
        g.mark_failed("a", result)
        assert g.get_node("a").status == TaskStatus.FAILED

    def test_mark_skipped(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        g.mark_skipped("a")
        assert g.get_node("a").status == TaskStatus.SKIPPED

    def test_mark_skipped_from_ready(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        g.get_ready_tasks()
        assert g.get_node("a").status == TaskStatus.READY
        g.mark_skipped("a")
        assert g.get_node("a").status == TaskStatus.SKIPPED

    def test_reset_to_pending(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        g.get_ready_tasks()
        g.mark_running("a")
        g.reset_to_pending("a")
        node = g.get_node("a")
        assert node.status == TaskStatus.PENDING
        assert node.retry_count == 1

    def test_skip_dependents_chain(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
            _make_spec("c", depends_on=["b"]),
        ])
        g.get_ready_tasks()
        g.mark_running("a")
        g.mark_failed("a", _make_result("a", TaskStatus.FAILED))
        skipped = g.skip_dependents("a")
        assert "b" in skipped
        assert "c" in skipped

    def test_skip_dependents_diamond(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
            _make_spec("c", depends_on=["a"]),
            _make_spec("d", depends_on=["b", "c"]),
        ])
        g.get_ready_tasks()
        g.mark_running("a")
        g.mark_failed("a", _make_result("a", TaskStatus.FAILED))
        skipped = g.skip_dependents("a")
        assert set(skipped) == {"b", "c", "d"}

    def test_is_complete_all_done(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a"), _make_spec("b")])
        g.get_ready_tasks()
        g.mark_running("a")
        g.mark_running("b")
        g.mark_completed("a", _make_result("a"))
        g.mark_completed("b", _make_result("b"))
        assert g.is_complete() is True

    def test_is_complete_mixed_terminal(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
        ])
        g.get_ready_tasks()
        g.mark_running("a")
        g.mark_failed("a", _make_result("a", TaskStatus.FAILED))
        g.skip_dependents("a")
        assert g.is_complete() is True

    def test_is_complete_false_while_pending(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        assert g.is_complete() is False

    def test_topological_order_chain(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("c", depends_on=["b"]),
            _make_spec("b", depends_on=["a"]),
            _make_spec("a"),
        ])
        order = g.topological_order()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_pending_completed_failed_skipped_ids(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b"),
            _make_spec("c", depends_on=["a"]),
        ])
        assert set(g.pending_task_ids()) == {"a", "b", "c"}
        g.get_ready_tasks()
        g.mark_running("a")
        g.mark_completed("a", _make_result("a"))
        g.get_ready_tasks()
        g.mark_running("b")
        g.mark_failed("b", _make_result("b", TaskStatus.FAILED))
        g.mark_skipped("c")
        assert g.completed_task_ids() == ["a"]
        assert g.failed_task_ids() == ["b"]
        assert g.skipped_task_ids() == ["c"]

    def test_empty_graph_is_complete(self):
        g = TaskGraph()
        g.add_tasks([])
        assert g.is_complete() is True


# ======================================================================
# Scheduler
# ======================================================================


class TestScheduler:
    def test_next_task_picks_highest_priority(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("low", priority=10),
            _make_spec("high", priority=1),
        ])
        s = Scheduler()
        node = s.next_task(g)
        assert node.task_id == "high"

    def test_next_task_alphabetical_tiebreak(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("b", priority=0),
            _make_spec("a", priority=0),
        ])
        s = Scheduler()
        node = s.next_task(g)
        assert node.task_id == "a"
        assert node.status == TaskStatus.RUNNING

    def test_next_task_rng_tiebreak(self):
        """With a seeded RNG, tied tasks get a deterministic random pick."""
        g1 = TaskGraph()
        g1.add_tasks([
            _make_spec("a", priority=0),
            _make_spec("b", priority=0),
            _make_spec("c", priority=0),
        ])
        g2 = TaskGraph()
        g2.add_tasks([
            _make_spec("a", priority=0),
            _make_spec("b", priority=0),
            _make_spec("c", priority=0),
        ])
        s1 = Scheduler(rng=random.Random(42))
        s2 = Scheduler(rng=random.Random(42))
        assert s1.next_task(g1).task_id == s2.next_task(g2).task_id

    def test_next_task_returns_none_when_empty(self):
        g = TaskGraph()
        g.add_tasks([])
        s = Scheduler()
        assert s.next_task(g) is None

    def test_schedule_all_does_not_mark_running(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a"), _make_spec("b")])
        s = Scheduler()
        ordered = s.schedule_all(g)
        assert len(ordered) == 2
        # After schedule_all, nodes should be READY (not RUNNING)
        assert all(n.status == TaskStatus.READY for n in ordered)

    def test_next_task_returns_none_when_all_blocked(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
        ])
        s = Scheduler()
        n1 = s.next_task(g)
        assert n1.task_id == "a"
        # b is blocked, so next should be None
        n2 = s.next_task(g)
        assert n2 is None


# ======================================================================
# DelegationHandler
# ======================================================================


class TestDelegationHandler:
    def test_depth_of_root_task(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("a")])
        dh = DelegationHandler()
        assert dh.delegation_depth(g, "a") == 0

    def test_depth_of_delegated_task(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", delegated_by="a"),
        ])
        dh = DelegationHandler()
        assert dh.delegation_depth(g, "b") == 1

    def test_depth_of_nested_delegation(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", delegated_by="a"),
            _make_spec("c", delegated_by="b"),
        ])
        dh = DelegationHandler()
        assert dh.delegation_depth(g, "c") == 2

    def test_inject_delegated_tasks(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("parent")])
        g.get_ready_tasks()
        g.mark_running("parent")
        g.mark_completed("parent", _make_result("parent"))

        dh = DelegationHandler(max_delegation_depth=3)
        new_ids = dh.inject_delegated_tasks(g, "parent", [
            {"task_id": "child1", "objective": "sub-task 1"},
            {"task_id": "child2", "objective": "sub-task 2"},
        ])
        assert set(new_ids) == {"child1", "child2"}
        assert g.get_node("child1").task_spec.delegated_by == "parent"
        assert g.get_node("child2").task_spec.delegated_by == "parent"

    def test_inject_rejects_excessive_depth(self):
        g = TaskGraph()
        g.add_tasks([
            _make_spec("a"),
            _make_spec("b", delegated_by="a"),
            _make_spec("c", delegated_by="b"),
        ])
        dh = DelegationHandler(max_delegation_depth=2)
        with pytest.raises(ValueError, match="exceeds max"):
            dh.inject_delegated_tasks(g, "c", [
                {"task_id": "d", "objective": "too deep"},
            ])

    def test_inject_rejects_too_many_children(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("parent")])
        dh = DelegationHandler(max_delegation_depth=3, max_children_per_parent=1)

        dh.inject_delegated_tasks(g, "parent", [
            {"task_id": "child1", "objective": "sub-task 1"},
        ])
        with pytest.raises(ValueError, match="child limit exceeded"):
            dh.inject_delegated_tasks(g, "parent", [
                {"task_id": "child2", "objective": "sub-task 2"},
            ])

    def test_inject_dedupes_duplicate_objectives_within_parent(self):
        g = TaskGraph()
        g.add_tasks([_make_spec("parent")])
        dh = DelegationHandler(max_delegation_depth=3, dedupe_within_parent=True)

        new_ids = dh.inject_delegated_tasks(g, "parent", [
            {"task_id": "child1", "objective": "same objective"},
            {"task_id": "child2", "objective": "same objective"},
            {"task_id": "child3", "objective": "different objective"},
        ])
        assert set(new_ids) == {"child1", "child3"}

    def test_validate_output_no_schema(self):
        result = _make_result("t1", output={"key": "value"})
        assert DelegationHandler.validate_output(result, None) is True

    def test_validate_output_with_error_no_schema(self):
        result = _make_result("t1", output={"key": "value"})
        assert DelegationHandler.validate_output_with_error(result, None) is None

    def test_validate_output_jsonschema_not_installed(self):
        result = _make_result("t1", output={"key": "value"})
        schema = {"type": "object", "required": ["key"]}
        with patch.dict("sys.modules", {"jsonschema": None}):
            # Simulate ImportError
            assert DelegationHandler.validate_output(result, schema) is True


# ======================================================================
# CycleExecutionResult
# ======================================================================


class TestCycleExecutionResult:
    def test_success_when_all_completed(self):
        r = CycleExecutionResult(
            total_tasks=3, completed_count=3, failed_count=0, skipped_count=0
        )
        assert r.success is True
        assert r.all_finished is True

    def test_not_success_when_failed(self):
        r = CycleExecutionResult(
            total_tasks=3, completed_count=2, failed_count=1, skipped_count=0
        )
        assert r.success is False
        assert r.all_finished is True

    def test_not_success_when_skipped(self):
        r = CycleExecutionResult(
            total_tasks=3, completed_count=1, failed_count=1, skipped_count=1
        )
        assert r.success is False
        assert r.all_finished is True

    def test_not_all_finished(self):
        r = CycleExecutionResult(
            total_tasks=3, completed_count=1, failed_count=0, skipped_count=0
        )
        assert r.all_finished is False


# ======================================================================
# Executor
# ======================================================================


def _make_runtime_and_context(agent_fn=None):
    """Create mock runtime + real ExecutionContext for executor tests."""
    from src.framework.runtime.execution_context import ExecutionContext

    config = RunConfig(seed=42, max_steps_per_cycle=100, max_delegation_depth=3)
    context = ExecutionContext(config)

    runtime = MagicMock()
    if agent_fn is not None:
        runtime.execute_task.side_effect = agent_fn
    else:
        # Default: all tasks succeed
        def succeed(task_spec):
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.COMPLETED,
                output={"result": "ok"},
            )
        runtime.execute_task.side_effect = succeed

    return runtime, context


class TestExecutor:
    def test_single_task_success(self):
        runtime, ctx = _make_runtime_and_context()
        executor = Executor(runtime, ctx)
        result = executor.execute([_make_spec("a")])
        assert result.success is True
        assert result.completed_count == 1
        assert "a" in result.task_results

    def test_chain_execution_order(self):
        executed_order = []

        def track(task_spec):
            executed_order.append(task_spec.task_id)
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.COMPLETED,
                output={},
            )

        runtime, ctx = _make_runtime_and_context(track)
        executor = Executor(runtime, ctx)
        result = executor.execute([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
            _make_spec("c", depends_on=["b"]),
        ])
        assert result.success is True
        assert executed_order.index("a") < executed_order.index("b")
        assert executed_order.index("b") < executed_order.index("c")

    def test_fail_skips_dependents(self):
        def fail_a(task_spec):
            if task_spec.task_id == "a":
                return TaskResult(
                    task_id="a",
                    task_status=TaskStatus.FAILED,
                    error="boom",
                    error_category=ErrorCategory.PERMANENT,
                )
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.COMPLETED,
                output={},
            )

        runtime, ctx = _make_runtime_and_context(fail_a)
        executor = Executor(runtime, ctx, retry_policy=RetryPolicy(max_retries=0))
        result = executor.execute([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
            _make_spec("c", depends_on=["b"]),
        ])
        assert result.failed_count == 1
        assert result.skipped_count == 2
        assert "b" in result.skipped_task_ids
        assert "c" in result.skipped_task_ids

    def test_retry_transient_failure(self):
        call_count = {"a": 0}

        def flaky(task_spec):
            if task_spec.task_id == "a":
                call_count["a"] += 1
                if call_count["a"] <= 2:
                    return TaskResult(
                        task_id="a",
                        task_status=TaskStatus.FAILED,
                        error="transient",
                        error_category=ErrorCategory.TRANSIENT,
                    )
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.COMPLETED,
                output={},
            )

        runtime, ctx = _make_runtime_and_context(flaky)
        # Use zero-delay retry for fast tests
        rp = RetryPolicy(max_retries=3, base_delay_seconds=0.0)
        executor = Executor(runtime, ctx, retry_policy=rp)
        result = executor.execute([_make_spec("a")])
        assert result.success is True
        assert call_count["a"] == 3  # 2 failures + 1 success

    def test_retry_exhaustion_fails(self):
        def always_fail(task_spec):
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.FAILED,
                error="transient",
                error_category=ErrorCategory.TRANSIENT,
            )

        runtime, ctx = _make_runtime_and_context(always_fail)
        rp = RetryPolicy(max_retries=2, base_delay_seconds=0.0)
        executor = Executor(runtime, ctx, retry_policy=rp)
        result = executor.execute([_make_spec("a")])
        assert result.failed_count == 1
        assert result.success is False

    def test_empty_task_list(self):
        runtime, ctx = _make_runtime_and_context()
        executor = Executor(runtime, ctx)
        result = executor.execute([])
        assert result.success is True
        assert result.total_tasks == 0

    def test_priority_ordering(self):
        executed_order = []

        def track(task_spec):
            executed_order.append(task_spec.task_id)
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.COMPLETED,
                output={},
            )

        runtime, ctx = _make_runtime_and_context(track)
        executor = Executor(runtime, ctx)
        result = executor.execute([
            _make_spec("low", priority=10),
            _make_spec("high", priority=1),
            _make_spec("mid", priority=5),
        ])
        assert result.success is True
        # high (1) should be first
        assert executed_order[0] == "high"

    def test_cycle_detection_raises(self):
        runtime, ctx = _make_runtime_and_context()
        executor = Executor(runtime, ctx)
        with pytest.raises(CycleDetectedError):
            executor.execute([
                _make_spec("a", depends_on=["b"]),
                _make_spec("b", depends_on=["a"]),
            ])

    def test_delegation_injects_subtasks(self):
        call_count = {"n": 0}

        def delegating_agent(task_spec):
            call_count["n"] += 1
            if task_spec.task_id == "parent":
                return TaskResult(
                    task_id="parent",
                    task_status=TaskStatus.COMPLETED,
                    output={
                        "delegated_tasks": [
                            {"task_id": "child1", "objective": "sub 1"},
                            {"task_id": "child2", "objective": "sub 2"},
                        ]
                    },
                )
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.COMPLETED,
                output={"done": True},
            )

        runtime, ctx = _make_runtime_and_context(delegating_agent)
        rp = RetryPolicy(max_retries=0, base_delay_seconds=0.0)
        executor = Executor(runtime, ctx, retry_policy=rp)
        result = executor.execute([_make_spec("parent")])
        assert result.completed_count == 3  # parent + 2 children
        assert result.success is True

    def test_deterministic_replay(self):
        """Same seed + same tasks = same execution order."""
        order1 = []
        order2 = []

        def track_factory(order_list):
            def track(task_spec):
                order_list.append(task_spec.task_id)
                return TaskResult(
                    task_id=task_spec.task_id,
                    task_status=TaskStatus.COMPLETED,
                    output={},
                )
            return track

        specs = [
            _make_spec("a", priority=0),
            _make_spec("b", priority=0),
            _make_spec("c", priority=0),
        ]

        for order_list in [order1, order2]:
            runtime, ctx = _make_runtime_and_context(track_factory(order_list))
            executor = Executor(runtime, ctx)
            executor.execute(list(specs))

        assert order1 == order2

    def test_parallel_independent_tasks(self):
        """Independent tasks all execute (order may vary by priority/rng)."""
        runtime, ctx = _make_runtime_and_context()
        executor = Executor(runtime, ctx)
        result = executor.execute([
            _make_spec("a"),
            _make_spec("b"),
            _make_spec("c"),
        ])
        assert result.success is True
        assert result.completed_count == 3

    def test_diamond_dependency(self):
        executed = []

        def track(task_spec):
            executed.append(task_spec.task_id)
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.COMPLETED,
                output={},
            )

        runtime, ctx = _make_runtime_and_context(track)
        executor = Executor(runtime, ctx)
        result = executor.execute([
            _make_spec("a"),
            _make_spec("b", depends_on=["a"]),
            _make_spec("c", depends_on=["a"]),
            _make_spec("d", depends_on=["b", "c"]),
        ])
        assert result.success is True
        assert executed.index("a") < executed.index("b")
        assert executed.index("a") < executed.index("c")
        assert executed.index("b") < executed.index("d")
        assert executed.index("c") < executed.index("d")

    def test_partial_failure_independent(self):
        """When one independent task fails, others still complete."""
        def fail_b(task_spec):
            if task_spec.task_id == "b":
                return TaskResult(
                    task_id="b",
                    task_status=TaskStatus.FAILED,
                    error="permanent",
                    error_category=ErrorCategory.PERMANENT,
                )
            return TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.COMPLETED,
                output={},
            )

        runtime, ctx = _make_runtime_and_context(fail_b)
        rp = RetryPolicy(max_retries=0, base_delay_seconds=0.0)
        executor = Executor(runtime, ctx, retry_policy=rp)
        result = executor.execute([
            _make_spec("a"),
            _make_spec("b"),
            _make_spec("c"),
        ])
        assert result.completed_count == 2
        assert result.failed_count == 1

    def test_event_emitter_called(self):
        emitter = MagicMock()
        runtime, ctx = _make_runtime_and_context()
        executor = Executor(runtime, ctx, event_emitter=emitter)
        executor.execute([_make_spec("a")])
        assert emitter.emit.called

    def test_all_finished_property(self):
        runtime, ctx = _make_runtime_and_context()
        executor = Executor(runtime, ctx)
        result = executor.execute([_make_spec("a"), _make_spec("b")])
        assert result.all_finished is True


# ======================================================================
# Integration tests
# ======================================================================


class TestIntegration:
    def test_full_lifecycle_with_runtime(self):
        """End-to-end: build runtime, register agent, execute via orchestrator."""
        from src.framework.runtime.capability_registry import CapabilityRegistry
        from src.framework.runtime.execution_context import ExecutionContext
        from src.framework.runtime.task_router import TaskRouter
        from src.framework.runtime.agent_runtime import AgentRuntime

        def echo_agent(task_spec, tools, context):
            return {"output_text": f"Done: {task_spec.objective}", "tokens_used": 10}

        registry = CapabilityRegistry()
        router = TaskRouter(registry)
        router.register_agent("echo", "worker", ["general"], echo_agent)

        config = RunConfig(seed=42, max_steps_per_cycle=100)
        context = ExecutionContext(config)
        runtime = AgentRuntime(registry, router, context=context)

        executor = Executor(runtime, context)
        result = executor.execute([
            _make_spec("t1"),
            _make_spec("t2", depends_on=["t1"]),
        ])
        assert result.success is True
        assert result.completed_count == 2

    def test_retry_then_succeed_integration(self):
        """Transient failure retried and eventually succeeds."""
        from src.framework.runtime.capability_registry import CapabilityRegistry
        from src.framework.runtime.execution_context import ExecutionContext
        from src.framework.runtime.task_router import TaskRouter
        from src.framework.runtime.agent_runtime import AgentRuntime

        call_count = {"n": 0}

        def flaky_agent(task_spec, tools, context):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                raise RuntimeError("transient network error")
            return {"output_text": "ok", "tokens_used": 5}

        registry = CapabilityRegistry()
        router = TaskRouter(registry)
        router.register_agent("flaky", "worker", ["general"], flaky_agent)

        config = RunConfig(seed=42, max_steps_per_cycle=100)
        context = ExecutionContext(config)
        runtime = AgentRuntime(registry, router, context=context)

        rp = RetryPolicy(max_retries=3, base_delay_seconds=0.0)
        executor = Executor(runtime, context, retry_policy=rp)
        result = executor.execute([_make_spec("t1")])
        assert result.success is True

    def test_delegation_depth_enforced_integration(self):
        """Deep delegation chain is properly tracked."""
        g = TaskGraph()
        g.add_tasks([
            _make_spec("root"),
            _make_spec("d1", delegated_by="root"),
            _make_spec("d2", delegated_by="d1"),
        ])
        dh = DelegationHandler(max_delegation_depth=3)
        assert dh.delegation_depth(g, "d2") == 2

        # Should allow one more level
        dh.inject_delegated_tasks(g, "d2", [
            {"task_id": "d3", "objective": "level 3"},
        ])
        assert dh.delegation_depth(g, "d3") == 3

        # Should reject further nesting
        with pytest.raises(ValueError, match="exceeds max"):
            dh.inject_delegated_tasks(g, "d3", [
                {"task_id": "d4", "objective": "too deep"},
            ])

    def test_deterministic_replay_integration(self):
        """Two runs with same seed produce same order."""
        from src.framework.runtime.execution_context import ExecutionContext

        orders = []
        for _ in range(2):
            executed = []

            def track(task_spec, _executed=executed):
                _executed.append(task_spec.task_id)
                return TaskResult(
                    task_id=task_spec.task_id,
                    task_status=TaskStatus.COMPLETED,
                    output={},
                )

            runtime = MagicMock()
            runtime.execute_task.side_effect = track
            config = RunConfig(seed=99, max_steps_per_cycle=100)
            ctx = ExecutionContext(config)
            executor = Executor(runtime, ctx)
            executor.execute([
                _make_spec("x", priority=0),
                _make_spec("y", priority=0),
                _make_spec("z", priority=0),
            ])
            orders.append(list(executed))

        assert orders[0] == orders[1]
