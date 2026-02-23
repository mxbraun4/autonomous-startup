"""Core agent execution engine.

Receives a :class:`TaskSpec`, routes to an agent, executes under budget
and policy constraints, persists outcomes, and returns a typed
:class:`TaskResult`.
"""

import time
import json
from typing import Any, Dict, Optional

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
        self._tool_call_signatures: list[str] = []

        policies: Dict[str, Any] = {}
        if self._context is not None:
            policies = getattr(self._context.run_config, "policies", {}) or {}
        self._tool_loop_window = int(policies.get("tool_loop_window", 8))
        self._tool_loop_max_repeats = int(policies.get("tool_loop_max_repeats", 3))

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

            # 7b. Emit agent reasoning if present
            reasoning = output.get("reasoning", "")
            if reasoning:
                self._emit(
                    "agent_reasoning",
                    {
                        "run_id": self._context.run_context.run_id if self._context else None,
                        "cycle_id": self._context.run_context.cycle_id if self._context else None,
                        "task_id": task_spec.task_id,
                        "agent_id": decision.agent_id,
                        "reasoning": reasoning,
                    },
                )

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

        # 1. Loop detection circuit breaker
        if self._is_tool_call_loop(tool_name, capability, arguments):
            tc = ToolCall(
                tool_name=tool_name,
                capability=capability,
                caller_agent_id=agent_id,
                caller_task_id=task_id,
                arguments=arguments,
                call_status=ToolCallStatus.DENIED,
                policy_check_passed=False,
                denied_reason=(
                    "Tool-call loop detected: repeated identical call signature"
                ),
                duration_ms=(time.monotonic() - start) * 1000,
                metadata={
                    "tool_loop_window": self._tool_loop_window,
                    "tool_loop_max_repeats": self._tool_loop_max_repeats,
                },
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

        # 3. Resolve candidate tools (cooldown-aware), with preferred tool first
        candidates = self._registry.resolve(capability)
        if tool_name:
            preferred = [t for t in candidates if t.tool_name == tool_name]
            non_preferred = [t for t in candidates if t.tool_name != tool_name]
            candidates = preferred + non_preferred

        if not candidates:
            tc = ToolCall(
                tool_name=tool_name,
                capability=capability,
                caller_agent_id=agent_id,
                caller_task_id=task_id,
                arguments=arguments,
                call_status=ToolCallStatus.ERROR,
                error_message=f"No available tool found for capability: {capability}",
                policy_check_passed=True,
                duration_ms=(time.monotonic() - start) * 1000,
                metadata={"resolution_trace": self._registry.resolution_trace(capability)},
            )
            self._emit("tool_error", tc)
            return tc

        # 4. Execute with fallback chain
        attempts: list[Dict[str, Any]] = []
        policy_denials: list[str] = []
        execution_errors: list[str] = []

        for candidate in candidates:
            # Per-tool policy check before execution
            denied_reason = self._policy_denied_reason(
                candidate.tool_name, capability, arguments
            )
            if denied_reason is not None:
                attempts.append(
                    {
                        "tool_name": candidate.tool_name,
                        "status": ToolCallStatus.DENIED.value,
                        "reason": denied_reason,
                    }
                )
                policy_denials.append(
                    f"{candidate.tool_name}: {denied_reason}"
                )
                continue

            try:
                result = candidate.tool_callable(**arguments)
                self._registry.mark_tool_success(capability, candidate.tool_name)

                duration_ms = (time.monotonic() - start) * 1000
                attempts.append(
                    {
                        "tool_name": candidate.tool_name,
                        "status": ToolCallStatus.SUCCESS.value,
                    }
                )
                tc = ToolCall(
                    tool_name=candidate.tool_name,
                    capability=capability,
                    caller_agent_id=agent_id,
                    caller_task_id=task_id,
                    arguments=arguments,
                    call_status=ToolCallStatus.SUCCESS,
                    result=result,
                    policy_check_passed=True,
                    duration_ms=duration_ms,
                    metadata={
                        "attempts": attempts,
                        "fallback_used": len(attempts) > 1,
                    },
                )
                self._emit("tool_called", tc)
                return tc
            except Exception as exc:
                self._registry.mark_tool_failure(capability, candidate.tool_name)
                attempts.append(
                    {
                        "tool_name": candidate.tool_name,
                        "status": ToolCallStatus.ERROR.value,
                        "error": str(exc),
                    }
                )
                execution_errors.append(f"{candidate.tool_name}: {exc}")
                continue

        # 5. Final failure after fallback attempts
        duration_ms = (time.monotonic() - start) * 1000
        if policy_denials and not execution_errors:
            denied = "; ".join(policy_denials)
            tc = ToolCall(
                tool_name=tool_name,
                capability=capability,
                caller_agent_id=agent_id,
                caller_task_id=task_id,
                arguments=arguments,
                call_status=ToolCallStatus.DENIED,
                policy_check_passed=False,
                denied_reason=denied,
                duration_ms=duration_ms,
                metadata={"attempts": attempts},
            )
            self._emit("tool_denied", tc)
            return tc

        error_message = "; ".join(execution_errors) or "All candidate tools failed"
        if policy_denials:
            error_message += f"; policy denials: {'; '.join(policy_denials)}"

        tc = ToolCall(
            tool_name=tool_name,
            capability=capability,
            caller_agent_id=agent_id,
            caller_task_id=task_id,
            arguments=arguments,
            call_status=ToolCallStatus.ERROR,
            error_message=error_message,
            policy_check_passed=not policy_denials,
            duration_ms=duration_ms,
            metadata={"attempts": attempts},
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

    def _policy_denied_reason(
        self,
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
    ) -> Optional[str]:
        """Return policy denial reason, or ``None`` when call is allowed."""
        if self._policy_engine is None:
            return None

        allowed = self._policy_engine.check(tool_name, capability, arguments)
        if allowed:
            return None

        reason = "Denied by policy engine"
        if hasattr(self._policy_engine, "check_detailed"):
            detail = self._policy_engine.check_detailed(tool_name, capability, arguments)
            if getattr(detail, "denied_reason", None):
                reason = detail.denied_reason
        return reason

    def _is_tool_call_loop(
        self,
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
    ) -> bool:
        """Detect repeated identical tool-call signatures in a sliding window."""
        if self._tool_loop_window <= 0 or self._tool_loop_max_repeats <= 0:
            return False

        signature = self._tool_call_signature(tool_name, capability, arguments)
        recent = self._tool_call_signatures[-self._tool_loop_window:]
        repeat_count = sum(1 for item in recent if item == signature)

        self._tool_call_signatures.append(signature)
        keep = max(50, self._tool_loop_window * 3)
        if len(self._tool_call_signatures) > keep:
            self._tool_call_signatures = self._tool_call_signatures[-keep:]

        return repeat_count >= self._tool_loop_max_repeats

    @staticmethod
    def _tool_call_signature(
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
    ) -> str:
        try:
            arg_sig = json.dumps(arguments, sort_keys=True, default=str)
        except Exception:
            arg_sig = str(arguments)
        return f"{tool_name}|{capability}|{arg_sig}"

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
