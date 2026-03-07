"""Autonomy loop orchestration for Build-Measure-Learn cycles."""

from __future__ import annotations

from time import perf_counter, sleep
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from src.framework.autonomy.checkpointing import CheckpointManager
from src.framework.autonomy.termination import (
    TerminationDecision,
    TerminationPolicy,
    TerminationState,
    evaluate_termination,
)
from src.framework.contracts import CycleMetrics, EvaluationResult, TaskSpec
from src.framework.eval.evaluator import Evaluator
from src.framework.learning.policy_updater import PolicyUpdater
from src.framework.learning.procedure_updater import ProcedureUpdater
from src.framework.safety.budget_manager import BudgetManager
from src.framework.safety.limits import BudgetLimits


class CycleOutcome(BaseModel):
    """Execution summary for one completed autonomy cycle."""

    run_id: str = ""
    cycle_id: int
    total_tasks: int = 0
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    evaluation_status: str = "pass"
    evaluation_action: str = "continue"
    termination_action: str = "continue"
    termination_reason: str = "continue"
    checkpoint_path: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LoopResult(BaseModel):
    """Result of running the autonomy loop."""

    run_id: str
    cycles: List[CycleOutcome] = Field(default_factory=list)
    final_action: str = "continue"
    final_reason: str = "continue"
    final_status: str = "running"
    last_checkpoint_path: Optional[str] = None


def default_measure_fn(
    *,
    cycle_id: int,
    execution_result: Any,
    run_id: str,
    duration_seconds: float,
) -> CycleMetrics:
    """Default domain-agnostic measure function for one cycle."""
    return CycleMetrics(
        run_id=run_id,
        cycle_id=cycle_id,
        task_count=getattr(execution_result, "total_tasks", 0),
        success_count=getattr(execution_result, "completed_count", 0),
        failure_count=getattr(execution_result, "failed_count", 0),
        duration_seconds=duration_seconds,
        tokens_used=0,
        domain_metrics={
            "skipped_count": getattr(execution_result, "skipped_count", 0),
        },
    )


class AutonomyLoop:
    """Runs autonomous cycles with evaluation, learning, termination, checkpointing."""

    def __init__(
        self,
        *,
        run_id: str,
        context: Any,
        executor: Any,
        task_builder: Callable[[Any], List[TaskSpec]],
        evaluator: Evaluator,
        termination_policy: TerminationPolicy,
        checkpoint_manager: Optional[CheckpointManager] = None,
        measure_fn: Optional[Callable[..., CycleMetrics]] = None,
        policy_updater: Optional[PolicyUpdater] = None,
        procedure_updater: Optional[ProcedureUpdater] = None,
        procedure_recommendations_fn: Optional[
            Callable[[EvaluationResult, CycleMetrics], List[Any]]
        ] = None,
        adaptive_policy_controller: Any = None,
        diagnostics_agent: Any = None,
        event_emitter: Any = None,
    ) -> None:
        self._run_id = run_id
        self._context = context
        self._executor = executor
        self._task_builder = task_builder
        self._evaluator = evaluator
        self._termination_policy = termination_policy
        self._checkpoint_manager = checkpoint_manager
        self._measure_fn = measure_fn or default_measure_fn
        self._policy_updater = policy_updater
        self._procedure_updater = procedure_updater
        self._procedure_recommendations_fn = procedure_recommendations_fn
        self._adaptive_policy_controller = adaptive_policy_controller
        self._diagnostics_agent = diagnostics_agent
        self._event_emitter = event_emitter

    def run(
        self,
        *,
        start_cycle: int = 1,
        previous_metrics: Optional[CycleMetrics] = None,
    ) -> LoopResult:
        """Execute cycles until termination action is pause/stop."""
        result = LoopResult(run_id=self._run_id)
        term_state = TerminationState()
        prior_metrics = previous_metrics

        cycle_id = start_cycle
        while True:
            budget_manager = BudgetManager(
                self._context,
                limits=_budget_limits_for_context(self._context),
            )
            if cycle_id > self._termination_policy.max_cycles:
                result.final_action = "stop"
                result.final_reason = "max_cycles_reached"
                result.final_status = "completed"
                return result

            self._context.begin_cycle(cycle_id)
            self._emit(
                "cycle_start",
                {
                    "run_id": self._run_id,
                    "cycle_id": cycle_id,
                },
            )
            if not budget_manager.check_budget():
                decision = evaluate_termination(
                    cycle_id=cycle_id,
                    policy=self._termination_policy,
                    state=term_state,
                    budget_ok=False,
                    evaluation_result=None,
                )
                result.final_action = decision.action
                result.final_reason = decision.reason
                result.final_status = _final_status(decision.action, decision.reason)
                return result

            tasks = self._task_builder(self._context.run_context)
            budget_critical = budget_manager.is_critical()
            if budget_critical:
                tasks = self._build_exploratory_tasks(tasks)
                self._emit(
                    "budget.warning",
                    {
                        "run_id": self._run_id,
                        "cycle_id": cycle_id,
                        "reason": "critical_budget_utilization",
                        "task_count_after_scope_reduction": len(tasks),
                    },
                )
            start = perf_counter()
            execution_result = self._executor.execute(tasks)
            elapsed = perf_counter() - start

            metrics = self._measure_fn(
                cycle_id=cycle_id,
                execution_result=execution_result,
                run_id=self._run_id,
                duration_seconds=elapsed,
            )
            metrics.run_id = self._run_id
            metrics.cycle_id = cycle_id

            evaluation = self._evaluator.evaluate(
                current_metrics=metrics,
                previous_metrics=prior_metrics,
            )

            self._apply_learning(evaluation, metrics)
            adaptive_adjustments = []
            if self._adaptive_policy_controller is not None:
                adaptive_adjustments = self._adaptive_policy_controller.apply(evaluation)

            decision = evaluate_termination(
                cycle_id=cycle_id,
                policy=self._termination_policy,
                state=term_state,
                budget_ok=budget_manager.check_budget(),
                evaluation_result=evaluation,
            )

            completed_tasks = list(getattr(execution_result, "task_results", {}).keys())
            checkpoint_path = None
            if self._checkpoint_manager is not None:
                checkpoint_path = self._checkpoint_manager.save(
                    context=self._context,
                    pending_tasks=[],
                    completed_tasks=completed_tasks,
                )
                result.last_checkpoint_path = checkpoint_path

            cycle_outcome = CycleOutcome(
                run_id=self._run_id,
                cycle_id=cycle_id,
                total_tasks=getattr(execution_result, "total_tasks", 0),
                completed_count=getattr(execution_result, "completed_count", 0),
                failed_count=getattr(execution_result, "failed_count", 0),
                skipped_count=getattr(execution_result, "skipped_count", 0),
                evaluation_status=evaluation.overall_status,
                evaluation_action=evaluation.recommended_action,
                termination_action=decision.action,
                termination_reason=decision.reason,
                checkpoint_path=checkpoint_path,
                metadata={
                    "evaluation_result_id": evaluation.entity_id,
                    "adaptive_adjustments": [
                        item.model_dump(mode="json") for item in adaptive_adjustments
                    ],
                    "budget_critical": budget_critical,
                },
            )
            result.cycles.append(cycle_outcome)
            self._emit("cycle_end", cycle_outcome)

            if self._diagnostics_agent is not None:
                self._diagnostics_agent.scan_and_act(
                    run_id=self._run_id,
                    cycle_id=cycle_id,
                )

            if decision.action == "pause" and self._termination_policy.auto_resume_on_pause:
                cooldown = max(0.0, self._termination_policy.pause_cooldown_seconds)
                self._emit(
                    "run.pause_cooldown",
                    {
                        "run_id": self._run_id,
                        "cycle_id": cycle_id,
                        "cooldown_seconds": cooldown,
                    },
                )
                if cooldown > 0:
                    sleep(cooldown)
                if checkpoint_path and self._checkpoint_manager is not None:
                    loaded = self._checkpoint_manager.load(
                        checkpoint_path=checkpoint_path,
                        run_config=self._context.run_config,
                    )
                    self._context = loaded.context
                continue

            prior_metrics = metrics

            if decision.should_terminate:
                result.final_action = decision.action
                result.final_reason = decision.reason
                result.final_status = _final_status(decision.action, decision.reason)
                return result

            cycle_id += 1

    def _apply_learning(
        self,
        evaluation: EvaluationResult,
        metrics: CycleMetrics,
    ) -> None:
        if self._policy_updater is not None:
            current_policies = dict(getattr(self._context.run_config, "policies", {}) or {})
            patches = self._policy_updater.propose_patches(
                evaluation_result=evaluation,
                current_policies=current_policies,
            )
            if patches:
                self._emit(
                    "policy_patch_applied",
                    {
                        "run_id": self._run_id,
                        "cycle_id": metrics.cycle_id,
                        "patches": [p.model_dump(mode="json") for p in patches],
                        "source_evidence": {"evaluation_result_id": evaluation.entity_id},
                    },
                )

        if (
            self._procedure_updater is not None
            and self._procedure_recommendations_fn is not None
        ):
            proposals = self._procedure_recommendations_fn(evaluation, metrics)
            for proposal in proposals:
                procedure = self._procedure_updater.apply_update(proposal)
                task_type = str(getattr(procedure, "task_type", "") or "")
                current_version = int(getattr(procedure, "current_version", 1))
                self._emit(
                    "procedure_updated",
                    {
                        "run_id": self._run_id,
                        "cycle_id": metrics.cycle_id,
                        "task_type": task_type,
                        "version": current_version,
                        "workflow": getattr(proposal, "workflow", None),
                        "score": getattr(proposal, "score", None),
                        "provenance": getattr(proposal, "provenance", None),
                        "created_by": getattr(proposal, "created_by", None),
                        "source_evidence": getattr(proposal, "source_evidence", None),
                    },
                )

    def _build_exploratory_tasks(self, tasks: List[TaskSpec]) -> List[TaskSpec]:
        policies = dict(getattr(self._context.run_config, "policies", {}) or {})
        task_limit = policies.get("exploratory_task_limit", 1)
        try:
            limit = max(1, int(task_limit))
        except (TypeError, ValueError):
            limit = 1
        return list(tasks[:limit])

    def _emit(self, event_type: str, payload: Any) -> None:
        if self._event_emitter is not None:
            try:
                self._event_emitter.emit(event_type, payload)
            except Exception:
                pass


def _final_status(action: str, reason: str) -> str:
    if action == "pause":
        return "paused"
    if action == "stop":
        if reason == "max_cycles_reached":
            return "completed"
        return "stopped"
    return "running"


def _budget_limits_for_context(context: Any) -> BudgetLimits:
    run_config = context.run_config
    policies = dict(getattr(run_config, "policies", {}) or {})
    return BudgetLimits(
        max_tokens=getattr(run_config, "budget_tokens", None),
        max_seconds=getattr(run_config, "budget_seconds", None),
        max_steps=policies.get("max_steps_total"),
        max_wall_seconds=policies.get("max_wall_seconds"),
        critical_threshold_pct=_safe_float(
            policies.get("budget_critical_threshold_pct"),
            fallback=10.0,
        ),
    )


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)
