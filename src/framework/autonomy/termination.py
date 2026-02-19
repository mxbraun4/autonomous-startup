"""Termination policy and decision logic for autonomous runs."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.framework.contracts import EvaluationResult


class TerminationState(BaseModel):
    """Mutable run-level counters used by termination logic."""

    consecutive_critical_failures: int = 0


class TerminationPolicy(BaseModel):
    """Configurable stop/pause conditions for the autonomy loop."""

    max_cycles: int = 10
    critical_failure_threshold: int = 3
    stop_on_policy_violation: bool = True


class TerminationDecision(BaseModel):
    """Outcome of evaluating one termination checkpoint."""

    action: str = "continue"  # continue | pause | stop
    reason: str = ""

    @property
    def should_terminate(self) -> bool:
        return self.action in {"pause", "stop"}


def evaluate_termination(
    *,
    cycle_id: int,
    policy: TerminationPolicy,
    state: TerminationState,
    budget_ok: bool,
    evaluation_result: Optional[EvaluationResult] = None,
) -> TerminationDecision:
    """Evaluate stop conditions in deterministic priority order."""
    if not budget_ok:
        return TerminationDecision(action="stop", reason="budget_exhausted")

    if evaluation_result is not None:
        if evaluation_result.overall_status == "fail":
            state.consecutive_critical_failures += 1
        else:
            state.consecutive_critical_failures = 0

        if (
            policy.stop_on_policy_violation
            and any(
                gate.gate_name == "safety"
                and gate.gate_status == "fail"
                and gate.evidence.get("policy_violations", 0) > 0
                for gate in evaluation_result.gates
            )
        ):
            return TerminationDecision(
                action="stop",
                reason="policy_violation_manual_review",
            )

        if state.consecutive_critical_failures >= policy.critical_failure_threshold:
            return TerminationDecision(
                action="stop",
                reason="critical_failure_threshold_reached",
            )

        # Gate-directed action (explicit stop/pause takes precedence over continue).
        if evaluation_result.recommended_action == "stop":
            return TerminationDecision(action="stop", reason="gate_stop")
        if evaluation_result.recommended_action == "pause":
            return TerminationDecision(action="pause", reason="gate_pause")

    if cycle_id >= policy.max_cycles:
        return TerminationDecision(action="stop", reason="max_cycles_reached")

    return TerminationDecision(action="continue", reason="continue")

