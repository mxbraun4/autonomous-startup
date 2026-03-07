"""Run controller entrypoint for autonomous multi-cycle execution."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from src.framework.adapters.base import BaseDomainAdapter
from src.framework.autonomy.adaptive_policy import AdaptivePolicyController
from src.framework.autonomy.checkpointing import CheckpointManager
from src.framework.autonomy.diagnostics import DiagnosticsAgent
from src.framework.autonomy.loop import AutonomyLoop, LoopResult
from src.framework.autonomy.termination import TerminationPolicy
from src.framework.contracts import CycleMetrics, RunConfig, TaskSpec
from src.framework.eval.evaluator import Evaluator
from src.framework.learning.policy_updater import PolicyUpdater
from src.framework.learning.procedure_updater import ProcedureUpdater
from src.framework.runtime.execution_context import ExecutionContext


def _resolve(value: Any) -> Any:
    """Resolve awaitables from synchronous contexts."""
    if not asyncio.iscoroutine(value):
        return value

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(value)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, value)
        return future.result()


class RunControllerResult(BaseModel):
    """Top-level result of a run controller execution."""

    run_id: str
    final_status: str
    final_action: str
    final_reason: str
    cycles_completed: int
    last_checkpoint_path: Optional[str] = None


class RunController:
    """Coordinates run lifecycle, autonomy loop, and checkpoint resume."""

    def __init__(
        self,
        *,
        run_config: RunConfig,
        executor: Any,
        task_builder: Optional[Callable[[Any], List[TaskSpec]]] = None,
        domain_adapter: Optional[BaseDomainAdapter] = None,
        store: Any = None,
        evaluator: Optional[Evaluator] = None,
        termination_policy: Optional[TerminationPolicy] = None,
        measure_fn: Optional[Callable[..., CycleMetrics]] = None,
        policy_updater: Optional[PolicyUpdater] = None,
        procedure_updater: Optional[ProcedureUpdater] = None,
        procedure_recommendations_fn: Optional[Callable[..., List[Any]]] = None,
        adaptive_policy_controller: Any = None,
        diagnostics_agent: Any = None,
        checkpoint_dir: str = "data/memory/checkpoints",
        event_emitter: Any = None,
        context: Optional[ExecutionContext] = None,
    ) -> None:
        self._run_config = run_config
        self._run_id = run_config.run_id or run_config.entity_id
        self._executor = executor
        self._domain_adapter = domain_adapter
        self._apply_domain_policies()
        if task_builder is None and self._domain_adapter is None:
            raise ValueError("RunController requires task_builder or domain_adapter")
        self._task_builder = task_builder or self._adapter_task_builder
        self._store = store
        self._evaluator = evaluator or Evaluator()
        policies = dict(getattr(run_config, "policies", {}) or {})
        self._termination_policy = termination_policy or TerminationPolicy(
            max_cycles=run_config.max_cycles,
            auto_resume_on_pause=bool(policies.get("auto_resume_on_pause", False)),
            pause_cooldown_seconds=float(policies.get("pause_cooldown_seconds", 0.0)),
        )
        if measure_fn is not None:
            self._measure_fn = measure_fn
        elif self._domain_adapter is not None:
            self._measure_fn = self._adapter_measure_fn
        else:
            self._measure_fn = None
        self._policy_updater = policy_updater
        self._procedure_updater = procedure_updater
        if (
            self._procedure_updater is None
            and self._domain_adapter is not None
            and store is not None
        ):
            self._procedure_updater = ProcedureUpdater(store)
        if procedure_recommendations_fn is not None:
            self._procedure_recommendations_fn = procedure_recommendations_fn
        elif self._domain_adapter is not None:
            self._procedure_recommendations_fn = self._adapter_procedure_recommendations
        else:
            self._procedure_recommendations_fn = None
        self._event_emitter = event_emitter

        runtime = getattr(self._executor, "_runtime", None)
        runtime_policy_engine = getattr(runtime, "_policy_engine", None)
        bounds = policies.get("policy_adjustment_bounds")
        adaptive_enabled = bool(policies.get("adaptive_policy_enabled", True))
        if adaptive_policy_controller is not None:
            self._adaptive_policy_controller = adaptive_policy_controller
        elif adaptive_enabled:
            self._adaptive_policy_controller = AdaptivePolicyController(
                run_config=run_config,
                policy_engine=runtime_policy_engine,
                event_emitter=event_emitter,
                reliability_pass_streak=int(
                    policies.get("adaptive_policy_reliability_streak", 3)
                ),
                step_adjustment_ratio=float(
                    policies.get("adaptive_policy_step_adjustment_ratio", 0.10)
                ),
                learning_improvement_threshold=float(
                    policies.get("adaptive_policy_learning_threshold", 0.05)
                ),
                bounds=dict(bounds or {}),
            )
        else:
            self._adaptive_policy_controller = None

        diagnostics_enabled = bool(policies.get("diagnostics_enabled", True))
        if diagnostics_agent is not None:
            self._diagnostics_agent = diagnostics_agent
        elif diagnostics_enabled and event_emitter is not None:
            self._diagnostics_agent = DiagnosticsAgent(
                event_source=event_emitter,
                run_config=run_config,
                adaptive_policy_controller=self._adaptive_policy_controller,
                policy_engine=runtime_policy_engine,
                event_emitter=event_emitter,
                window_size=int(policies.get("diagnostics_window_size", 100)),
                policy_violation_threshold=int(
                    policies.get("diagnostics_policy_violation_threshold", 3)
                ),
                tool_denied_threshold=int(
                    policies.get("diagnostics_tool_denied_threshold", 3)
                ),
                gate_drop_window=int(policies.get("diagnostics_gate_drop_window", 3)),
            )
        else:
            self._diagnostics_agent = None

        self._checkpoint_manager = CheckpointManager(
            checkpoint_dir=checkpoint_dir,
            store=store,
            event_emitter=event_emitter,
        )
        self._context = context or ExecutionContext(run_config=run_config, store=store)

    def run(self) -> RunControllerResult:
        """Start a run from cycle 1."""
        return self._run_internal(start_cycle=1)

    def resume(self, checkpoint_path: str) -> RunControllerResult:
        """Resume a run from an existing checkpoint."""
        loaded = self._checkpoint_manager.load(
            checkpoint_path=checkpoint_path,
            run_config=self._run_config,
        )
        self._context = loaded.context
        start_cycle = loaded.checkpoint.cycle_id + 1
        return self._run_internal(
            start_cycle=start_cycle,
            resume_from_checkpoint=checkpoint_path,
        )

    def _run_internal(
        self,
        *,
        start_cycle: int,
        resume_from_checkpoint: Optional[str] = None,
    ) -> RunControllerResult:
        self._start_run(resume_from_checkpoint)
        try:
            loop = AutonomyLoop(
                run_id=self._run_id,
                context=self._context,
                executor=self._executor,
                task_builder=self._task_builder,
                evaluator=self._evaluator,
                termination_policy=self._termination_policy,
                checkpoint_manager=self._checkpoint_manager,
                measure_fn=self._measure_fn,
                policy_updater=self._policy_updater,
                procedure_updater=self._procedure_updater,
                procedure_recommendations_fn=self._procedure_recommendations_fn,
                adaptive_policy_controller=self._adaptive_policy_controller,
                diagnostics_agent=self._diagnostics_agent,
                event_emitter=self._event_emitter,
            )
            loop_result: LoopResult = loop.run(start_cycle=start_cycle)
        finally:
            self._end_run()

        return RunControllerResult(
            run_id=self._run_id,
            final_status=loop_result.final_status,
            final_action=loop_result.final_action,
            final_reason=loop_result.final_reason,
            cycles_completed=len(loop_result.cycles),
            last_checkpoint_path=loop_result.last_checkpoint_path,
        )

    def _start_run(self, resume_from_checkpoint: Optional[str]) -> None:
        if self._store is not None and hasattr(self._store, "start_run"):
            _resolve(
                self._store.start_run(
                    self._run_id,
                    metadata={"resume_from_checkpoint": resume_from_checkpoint},
                )
            )
        self._emit(
            "run_start",
            {"run_id": self._run_id, "resume_from_checkpoint": resume_from_checkpoint},
        )

    def _end_run(self) -> None:
        if self._store is not None and hasattr(self._store, "end_run"):
            _resolve(self._store.end_run(self._run_id))
        self._emit("run_end", {"run_id": self._run_id})

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._event_emitter is not None:
            try:
                self._event_emitter.emit(event_type, payload)
            except Exception:
                pass

    def _apply_domain_policies(self) -> None:
        if self._domain_adapter is None:
            return
        domain_defaults = self._domain_adapter.get_domain_policies() or {}
        current = dict(getattr(self._run_config, "policies", {}) or {})
        # Explicit run_config policies override domain defaults.
        self._run_config.policies = {**domain_defaults, **current}

    def _adapter_task_builder(self, run_context: Any) -> List[TaskSpec]:
        if self._domain_adapter is None:
            return []
        return self._domain_adapter.build_cycle_tasks(run_context)

    def _adapter_measure_fn(
        self,
        *,
        cycle_id: int,
        execution_result: Any,
        run_id: str,
        duration_seconds: float,
    ) -> CycleMetrics:
        if self._domain_adapter is None:
            return CycleMetrics(
                run_id=run_id,
                cycle_id=cycle_id,
                task_count=getattr(execution_result, "total_tasks", 0),
                success_count=getattr(execution_result, "completed_count", 0),
                failure_count=getattr(execution_result, "failed_count", 0),
                duration_seconds=duration_seconds,
                tokens_used=0,
                domain_metrics={},
            )

        simulation_outputs = self._domain_adapter.simulate_environment(
            cycle_outputs=execution_result,
            run_context=self._context.run_context,
        )
        domain_metrics = self._domain_adapter.compute_domain_metrics(simulation_outputs)
        return CycleMetrics(
            run_id=run_id,
            cycle_id=cycle_id,
            task_count=getattr(execution_result, "total_tasks", 0),
            success_count=getattr(execution_result, "completed_count", 0),
            failure_count=getattr(execution_result, "failed_count", 0),
            duration_seconds=duration_seconds,
            tokens_used=0,
            domain_metrics=domain_metrics,
        )

    def _adapter_procedure_recommendations(
        self,
        evaluation_result: Any,
        metrics: Any,
    ) -> List[Any]:
        del metrics
        if self._domain_adapter is None:
            return []
        return self._domain_adapter.suggest_procedure_updates(evaluation_result)
