"""Core agent execution engine.

Receives a :class:`TaskSpec`, routes to an agent, executes under budget
and policy constraints, persists outcomes, and returns a typed
:class:`TaskResult`.
"""

import time
from typing import Any, Callable, Dict, Optional

from src.framework.contracts import (
    Episode,
    TaskResult,
    TaskSpec,
    ToolCall,
)
from src.framework.errors import BudgetExhaustedError
from src.framework.types import (
    EpisodeType,
    ErrorCategory,
    TaskStatus,
    ToolCallStatus,
)
from src.framework.runtime.capability_registry import CapabilityRegistry
from src.framework.runtime.execution_context import ExecutionContext
from src.framework.runtime.task_router import TaskRouter


class AgentRuntime:
    """The single entry-point for all agent work.

    Wraps routing, capability resolution, budget tracking, persistence,
    and event emission into one lifecycle.

    Parameters
    ----------
    registry : CapabilityRegistry
        Tool registry for capability resolution.
    router : TaskRouter
        Agent router for task-to-agent mapping.
    store : any
        A ``SyncUnifiedStore`` (or compatible) for memory persistence.
        May be ``None`` for lightweight / test usage.
    context : ExecutionContext
        Manages budgets, step counting, RNG.
    policy_engine : optional
        Layer F policy engine. When present, tool calls are checked
        against it before execution.
    event_emitter : optional
        Layer H event emitter. When present, structured events are
        emitted at key lifecycle points.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        router: TaskRouter,
        store: Any = None,
        context: Optional[ExecutionContext] = None,
        policy_engine: Any = None,
        event_emitter: Any = None,
    ) -> None:
        self._registry = registry
        self._router = router
        self._store = store
        self._context = context
        self._policy_engine = policy_engine
        self._event_emitter = event_emitter

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------

    def execute_task(self, task_spec: TaskSpec) -> TaskResult:
        """Run a single task through the full agent lifecycle.

        Steps:
        1. Route to agent.
        2. Check delegation depth.
        3. Begin step (budget check).
        4. Execute agent callable.
        5. End step (budget accounting).
        6. Persist episode.
        7. Emit event.
        8. Return TaskResult.

        Catches :class:`BudgetExhaustedError` and general exceptions,
        mapping them to appropriate :class:`TaskResult` failure states.
        """
        start = time.monotonic()
        tool_call_ids: list[str] = []

        try:
            # 1. Route
            decision = self._router.route(task_spec)
            if not decision.can_execute:
                return TaskResult(
                    task_id=task_spec.task_id,
                    agent_id=decision.agent_id,
                    task_status=TaskStatus.FAILED,
                    error=f"Unresolved capabilities: {decision.unresolved_capabilities}",
                    error_category=ErrorCategory.UNRESOLVABLE_CAPABILITY,
                    duration_seconds=time.monotonic() - start,
                )

            agent = self._get_agent_instance(decision.agent_id)

            # 2. Check delegation depth
            if task_spec.delegated_by is not None and self._context is not None:
                max_depth = self._context.run_config.max_delegation_depth
                depth = self._delegation_depth(task_spec)
                if depth > max_depth:
                    return TaskResult(
                        task_id=task_spec.task_id,
                        agent_id=decision.agent_id,
                        task_status=TaskStatus.FAILED,
                        error=f"Delegation depth {depth} exceeds max {max_depth}",
                        error_category=ErrorCategory.POLICY_VIOLATION,
                        duration_seconds=time.monotonic() - start,
                    )

            # 3. Begin step (budget check)
            if self._context is not None:
                self._context.begin_step(decision.agent_id)

            # 4. Execute agent
            output: Dict[str, Any] = {}
            output_text = ""
            tokens_used = 0

            if callable(agent):
                result = agent(
                    task_spec=task_spec,
                    tools=decision.resolved_tools,
                    context=self._context,
                )
                if isinstance(result, dict):
                    output = result
                    output_text = result.get("output_text", "")
                    tokens_used = result.get("tokens_used", 0)
                    tool_call_ids = result.get("tool_calls", [])
                else:
                    output_text = str(result) if result is not None else ""
                    output = {"raw": output_text}

            # 5. End step
            duration = time.monotonic() - start
            if self._context is not None:
                self._context.end_step(tokens_used=tokens_used, duration_seconds=duration)

            # 6. Persist episode
            task_result = TaskResult(
                task_id=task_spec.task_id,
                agent_id=decision.agent_id,
                task_status=TaskStatus.COMPLETED,
                output=output,
                output_text=output_text,
                tool_calls=tool_call_ids,
                duration_seconds=duration,
                tokens_used=tokens_used,
            )
            self._persist_episode(task_spec, task_result, decision.agent_id)

            # 7. Emit event
            self._emit("task_completed", task_result)

            return task_result

        except BudgetExhaustedError as exc:
            duration = time.monotonic() - start
            result = TaskResult(
                task_id=task_spec.task_id,
                agent_id=getattr(exc, "run_id", ""),
                task_status=TaskStatus.FAILED,
                error=str(exc),
                error_category=ErrorCategory.BUDGET_EXCEEDED,
                duration_seconds=duration,
            )
            self._emit("task_failed", result)
            return result

        except Exception as exc:
            duration = time.monotonic() - start
            result = TaskResult(
                task_id=task_spec.task_id,
                task_status=TaskStatus.FAILED,
                error=str(exc),
                error_category=ErrorCategory.TRANSIENT,
                duration_seconds=duration,
            )
            self._emit("task_failed", result)
            return result

    # ------------------------------------------------------------------
    # Tool call execution
    # ------------------------------------------------------------------

    def execute_tool_call(
        self,
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
        agent_id: str,
        task_id: str,
    ) -> ToolCall:
        """Execute a single tool call with policy checking and recording.

        Returns a :class:`ToolCall` record regardless of outcome.
        """
        start = time.monotonic()

        # 1. Policy check
        if self._policy_engine is not None:
            allowed = self._policy_engine.check(tool_name, capability, arguments)
            if not allowed:
                # Structured reason when check_detailed is available
                reason = "Denied by policy engine"
                if hasattr(self._policy_engine, "check_detailed"):
                    detail = self._policy_engine.check_detailed(
                        tool_name, capability, arguments
                    )
                    if getattr(detail, "denied_reason", None):
                        reason = detail.denied_reason
                tc = ToolCall(
                    tool_name=tool_name,
                    capability=capability,
                    caller_agent_id=agent_id,
                    caller_task_id=task_id,
                    arguments=arguments,
                    call_status=ToolCallStatus.DENIED,
                    policy_check_passed=False,
                    denied_reason=reason,
                    duration_ms=(time.monotonic() - start) * 1000,
                )
                self._emit("tool_denied", tc)
                return tc

        # 2. Budget check
        if self._context is not None and not self._context.check_budget():
            tc = ToolCall(
                tool_name=tool_name,
                capability=capability,
                caller_agent_id=agent_id,
                caller_task_id=task_id,
                arguments=arguments,
                call_status=ToolCallStatus.BUDGET_EXCEEDED,
                policy_check_passed=True,
                duration_ms=(time.monotonic() - start) * 1000,
            )
            return tc

        # 3. Resolve tool
        tool = self._registry.resolve_best(capability)
        if tool is None:
            tc = ToolCall(
                tool_name=tool_name,
                capability=capability,
                caller_agent_id=agent_id,
                caller_task_id=task_id,
                arguments=arguments,
                call_status=ToolCallStatus.ERROR,
                error_message=f"No tool found for capability: {capability}",
                policy_check_passed=True,
                duration_ms=(time.monotonic() - start) * 1000,
            )
            return tc

        # 4. Execute
        try:
            result = tool.tool_callable(**arguments)
            duration_ms = (time.monotonic() - start) * 1000
            tc = ToolCall(
                tool_name=tool_name,
                capability=capability,
                caller_agent_id=agent_id,
                caller_task_id=task_id,
                arguments=arguments,
                call_status=ToolCallStatus.SUCCESS,
                result=result,
                policy_check_passed=True,
                duration_ms=duration_ms,
            )
            self._emit("tool_called", tc)
            return tc

        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            tc = ToolCall(
                tool_name=tool_name,
                capability=capability,
                caller_agent_id=agent_id,
                caller_task_id=task_id,
                arguments=arguments,
                call_status=ToolCallStatus.ERROR,
                error_message=str(exc),
                policy_check_passed=True,
                duration_ms=duration_ms,
            )
            self._emit("tool_error", tc)
            return tc

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_agent_instance(self, agent_id: str) -> Any:
        """Return the agent callable/instance from the router."""
        for agent in self._router.list_agents():
            if agent.agent_id == agent_id:
                return agent.agent_instance
        return None

    def _delegation_depth(self, task_spec: TaskSpec, depth: int = 0) -> int:
        """Compute delegation depth (simplified: counts delegated_by chain length)."""
        # In a full implementation this would walk the task graph.
        # For now, count the presence of delegated_by as depth=1.
        if task_spec.delegated_by is not None:
            return depth + 1
        return depth

    def _persist_episode(
        self, task_spec: TaskSpec, task_result: TaskResult, agent_id: str
    ) -> None:
        """Write an Episode to episodic memory if a store is available."""
        if self._store is None:
            return
        try:
            episode = Episode(
                agent_id=agent_id,
                episode_type=EpisodeType.GENERAL,
                run_id=self._context.run_context.run_id if self._context else None,
                cycle_id=self._context.run_context.cycle_id if self._context else None,
                context={"task_id": task_spec.task_id, "objective": task_spec.objective},
                action=task_spec.objective,
                outcome={
                    "status": task_result.task_status.value,
                    "output_text": task_result.output_text,
                },
                success=task_result.task_status == TaskStatus.COMPLETED,
                summary_text=f"Task {task_spec.task_id}: {task_result.task_status.value}",
            )
            self._store.ep_record(episode)
        except Exception:
            # Persistence failure should not break the runtime
            pass

    def _emit(self, event_type: str, payload: Any) -> None:
        """Emit a structured event if an emitter is available."""
        if self._event_emitter is not None:
            try:
                self._event_emitter.emit(event_type, payload)
            except Exception:
                pass
