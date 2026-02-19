"""Orchestration executor: builds a TaskGraph, schedules, executes, retries.

The Executor is the top-level entry point for running a batch of TaskSpecs
through the agent runtime. It handles the full lifecycle: graph construction,
priority scheduling, retry loops, delegation injection, output validation,
and dependent-skipping on failure.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.framework.contracts import TaskResult, TaskSpec
from src.framework.errors import DeadlockError
from src.framework.types import ErrorCategory, TaskStatus

from src.framework.orchestration.delegation import DelegationHandler
from src.framework.orchestration.retry_policy import RetryPolicy
from src.framework.orchestration.scheduler import Scheduler
from src.framework.orchestration.task_graph import TaskGraph, TaskNode

logger = logging.getLogger(__name__)


class CycleExecutionResult(BaseModel):
    """Aggregated result of executing a full task graph."""

    task_results: Dict[str, TaskResult] = Field(default_factory=dict)
    skipped_task_ids: List[str] = Field(default_factory=list)
    total_tasks: int = 0
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0

    @property
    def success(self) -> bool:
        """True when every task completed successfully (none failed/skipped)."""
        return self.failed_count == 0 and self.skipped_count == 0

    @property
    def all_finished(self) -> bool:
        """True when every task reached a terminal state."""
        return (self.completed_count + self.failed_count + self.skipped_count) == self.total_tasks


class Executor:
    """Execute a list of TaskSpecs via the agent runtime.

    Parameters
    ----------
    runtime : AgentRuntime
        The runtime used to execute individual tasks.
    context : ExecutionContext
        Manages budgets, RNG, step counting.
    retry_policy : RetryPolicy, optional
        Defaults to ``RetryPolicy()`` (2 retries, 1 s base delay).
    delegation_handler : DelegationHandler, optional
        Defaults to a handler using ``context.run_config.max_delegation_depth``.
    event_emitter : any, optional
        Layer H event emitter for structured events.
    """

    def __init__(
        self,
        runtime: Any,  # AgentRuntime — typed as Any to avoid circular import
        context: Any,   # ExecutionContext
        retry_policy: Optional[RetryPolicy] = None,
        delegation_handler: Optional[DelegationHandler] = None,
        event_emitter: Any = None,
    ) -> None:
        self._runtime = runtime
        self._context = context
        self._retry_policy = retry_policy or RetryPolicy()
        if delegation_handler is not None:
            self._delegation_handler = delegation_handler
        else:
            policies = getattr(context.run_config, "policies", {}) or {}
            self._delegation_handler = DelegationHandler(
                max_delegation_depth=context.run_config.max_delegation_depth,
                max_children_per_parent=policies.get("max_children_per_parent", 10),
                max_total_delegated_tasks=policies.get("max_total_delegated_tasks"),
                dedupe_within_parent=policies.get("dedupe_delegated_objectives", True),
            )
        self._event_emitter = event_emitter
        self._scheduler = Scheduler(rng=context.get_rng())

    def execute(self, task_specs: List[TaskSpec]) -> CycleExecutionResult:
        """Build and execute the full task DAG.

        1. Build TaskGraph and validate (may raise CycleDetectedError).
        2. Loop: pick next task, execute with retries, handle outcomes.
        3. Return aggregated CycleExecutionResult.

        Raises
        ------
        CycleDetectedError
            If the task dependency graph contains a cycle.
        DeadlockError
            If no tasks are ready but the graph is not complete.
        """
        graph = TaskGraph()
        graph.add_tasks(task_specs)

        all_results: Dict[str, TaskResult] = {}
        all_skipped: List[str] = []

        while not graph.is_complete():
            node = self._scheduler.next_task(graph)
            if node is None:
                # No ready tasks but graph is not complete => deadlock
                blocked = graph.pending_task_ids()
                raise DeadlockError(blocked_tasks=blocked)

            self._emit("task_scheduled", node.task_spec)
            self._emit("task_started", node.task_spec)
            result = self._execute_with_retries(graph, node)
            all_results[node.task_id] = result

            if result.task_status == TaskStatus.COMPLETED:
                self._handle_completed(graph, node, result)
            else:
                graph.mark_failed(node.task_id, result)
                skipped = graph.skip_dependents(node.task_id)
                all_skipped.extend(skipped)
                self._emit("task_failed", result)

        return CycleExecutionResult(
            task_results=all_results,
            skipped_task_ids=all_skipped,
            total_tasks=len(graph.nodes),
            completed_count=len(graph.completed_task_ids()),
            failed_count=len(graph.failed_task_ids()),
            skipped_count=len(graph.skipped_task_ids()),
        )

    # ------------------------------------------------------------------
    # Retry loop
    # ------------------------------------------------------------------

    def _execute_with_retries(
        self, graph: TaskGraph, node: TaskNode
    ) -> TaskResult:
        """Execute a task, retrying transient failures in a tight loop."""
        while True:
            result = self._runtime.execute_task(node.task_spec)

            if result.task_status == TaskStatus.COMPLETED:
                return result

            # Failed — decide whether to retry
            if self._retry_policy.should_retry(result, node.retry_count):
                logger.info(
                    "Retrying task %s (attempt %d)",
                    node.task_id,
                    node.retry_count + 1,
                )
                self._retry_policy.wait(node.retry_count)
                graph.reset_to_pending(node.task_id)
                # Re-transition through READY -> RUNNING
                node.status = TaskStatus.READY
                graph.mark_running(node.task_id)
                continue

            # Not retryable
            result.retries = node.retry_count
            return result

    # ------------------------------------------------------------------
    # Completion handling
    # ------------------------------------------------------------------

    def _handle_completed(
        self, graph: TaskGraph, node: TaskNode, result: TaskResult
    ) -> None:
        """Handle a successfully completed task: validate, delegate, mark."""
        # Validate output schema if specified
        schema = node.task_spec.expected_output_schema
        if schema is not None:
            error_msg = self._delegation_handler.validate_output_with_error(
                result, schema
            )
            if error_msg is not None:
                logger.warning(
                    "Output validation failed for task %s: %s",
                    node.task_id,
                    error_msg,
                )
                # Treat schema validation failure as a non-retryable failure
                result.task_status = TaskStatus.FAILED
                result.error = f"Output schema validation failed: {error_msg}"
                result.error_category = ErrorCategory.PERMANENT
                graph.mark_failed(node.task_id, result)
                graph.skip_dependents(node.task_id)
                return

        graph.mark_completed(node.task_id, result)
        self._emit("task_completed", result)

        # Handle delegation
        delegated_tasks = result.output.get("delegated_tasks")
        if delegated_tasks and isinstance(delegated_tasks, list):
            try:
                new_ids = self._delegation_handler.inject_delegated_tasks(
                    graph, node.task_id, delegated_tasks
                )
                logger.info(
                    "Task %s delegated %d sub-tasks: %s",
                    node.task_id,
                    len(new_ids),
                    new_ids,
                )
            except (ValueError, Exception) as exc:
                logger.warning(
                    "Delegation failed for task %s: %s",
                    node.task_id,
                    exc,
                )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, payload: Any) -> None:
        if self._event_emitter is not None:
            try:
                self._event_emitter.emit(event_type, payload)
            except Exception:
                pass
