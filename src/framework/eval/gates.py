"""Gate evaluation rules.

Gates collect signals and report status (pass/warn/fail) as informational
evidence.  All gates recommend "continue" — the evaluator and agents decide
what action to take based on the evidence, not hardcoded rules.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from src.framework.contracts import GateDecision
from src.framework.eval.scorecard import Scorecard


class GateThresholds(BaseModel):
    """Thresholds for pass/warn/fail gate decisions."""

    reliability_warn_completion_rate: float = 0.90
    reliability_fail_completion_rate: float = 0.80
    reliability_warn_unhandled_exceptions: int = 0
    reliability_fail_unhandled_exceptions: int = 1

    stability_warn_determinism_variance: float = 0.05
    stability_fail_determinism_variance: float = 0.10

    learning_warn_min_procedure_delta: float = 0.00
    learning_fail_min_procedure_delta: float = -0.05

    safety_warn_policy_violations: int = 0
    safety_fail_policy_violations: int = 1
    safety_warn_loop_denials: int = 0
    safety_fail_loop_denials: int = 3

    efficiency_warn_duration_seconds: Optional[float] = None
    efficiency_fail_duration_seconds: Optional[float] = None
    efficiency_warn_tokens_used: Optional[int] = None
    efficiency_fail_tokens_used: Optional[int] = None


def _new_gate(
    gate_name: str,
    gate_status: str,
    evidence: dict,
    run_id: Optional[str],
    cycle_id: Optional[int],
) -> GateDecision:
    return GateDecision(
        gate_name=gate_name,
        gate_status=gate_status,
        evidence=evidence,
        recommended_action="continue",
        run_id=run_id,
        cycle_id=cycle_id,
    )


def evaluate_reliability(
    scorecard: Scorecard,
    thresholds: GateThresholds,
    run_id: Optional[str] = None,
    cycle_id: Optional[int] = None,
) -> GateDecision:
    status = "pass"

    if (
        scorecard.completion_rate < thresholds.reliability_fail_completion_rate
        or scorecard.unhandled_exceptions > thresholds.reliability_fail_unhandled_exceptions
    ):
        status = "fail"
    elif (
        scorecard.completion_rate < thresholds.reliability_warn_completion_rate
        or scorecard.unhandled_exceptions > thresholds.reliability_warn_unhandled_exceptions
    ):
        status = "warn"

    return _new_gate(
        gate_name="reliability",
        gate_status=status,
        evidence={
            "completion_rate": scorecard.completion_rate,
            "unhandled_exceptions": scorecard.unhandled_exceptions,
            "warn_completion_rate": thresholds.reliability_warn_completion_rate,
            "fail_completion_rate": thresholds.reliability_fail_completion_rate,
            "warn_unhandled_exceptions": thresholds.reliability_warn_unhandled_exceptions,
            "fail_unhandled_exceptions": thresholds.reliability_fail_unhandled_exceptions,
        },
        run_id=run_id,
        cycle_id=cycle_id,
    )


def evaluate_stability(
    scorecard: Scorecard,
    thresholds: GateThresholds,
    run_id: Optional[str] = None,
    cycle_id: Optional[int] = None,
) -> GateDecision:
    variance = scorecard.determinism_variance

    if variance is None:
        return _new_gate(
            gate_name="stability",
            gate_status="warn",
            evidence={"determinism_variance": None, "reason": "missing_determinism_signal"},
            run_id=run_id,
            cycle_id=cycle_id,
        )

    status = "pass"
    if variance > thresholds.stability_fail_determinism_variance:
        status = "fail"
    elif variance > thresholds.stability_warn_determinism_variance:
        status = "warn"

    return _new_gate(
        gate_name="stability",
        gate_status=status,
        evidence={
            "determinism_variance": variance,
            "warn_threshold": thresholds.stability_warn_determinism_variance,
            "fail_threshold": thresholds.stability_fail_determinism_variance,
        },
        run_id=run_id,
        cycle_id=cycle_id,
    )


def evaluate_learning(
    scorecard: Scorecard,
    thresholds: GateThresholds,
    run_id: Optional[str] = None,
    cycle_id: Optional[int] = None,
) -> GateDecision:
    delta = scorecard.procedure_score_delta
    if delta is None:
        return _new_gate(
            gate_name="learning",
            gate_status="warn",
            evidence={"procedure_score_delta": None, "reason": "missing_procedure_baseline"},
            run_id=run_id,
            cycle_id=cycle_id,
        )

    status = "pass"
    if delta < thresholds.learning_fail_min_procedure_delta:
        status = "fail"
    elif delta < thresholds.learning_warn_min_procedure_delta:
        status = "warn"

    return _new_gate(
        gate_name="learning",
        gate_status=status,
        evidence={
            "procedure_score_delta": delta,
            "warn_min_delta": thresholds.learning_warn_min_procedure_delta,
            "fail_min_delta": thresholds.learning_fail_min_procedure_delta,
        },
        run_id=run_id,
        cycle_id=cycle_id,
    )


def evaluate_safety(
    scorecard: Scorecard,
    thresholds: GateThresholds,
    run_id: Optional[str] = None,
    cycle_id: Optional[int] = None,
) -> GateDecision:
    status = "pass"

    if (
        scorecard.policy_violations > thresholds.safety_fail_policy_violations
        or scorecard.loop_denials > thresholds.safety_fail_loop_denials
    ):
        status = "fail"
    elif (
        scorecard.policy_violations > thresholds.safety_warn_policy_violations
        or scorecard.loop_denials > thresholds.safety_warn_loop_denials
    ):
        status = "warn"

    return _new_gate(
        gate_name="safety",
        gate_status=status,
        evidence={
            "policy_violations": scorecard.policy_violations,
            "loop_denials": scorecard.loop_denials,
            "warn_policy_violations": thresholds.safety_warn_policy_violations,
            "fail_policy_violations": thresholds.safety_fail_policy_violations,
            "warn_loop_denials": thresholds.safety_warn_loop_denials,
            "fail_loop_denials": thresholds.safety_fail_loop_denials,
        },
        run_id=run_id,
        cycle_id=cycle_id,
    )


def evaluate_efficiency(
    scorecard: Scorecard,
    thresholds: GateThresholds,
    run_id: Optional[str] = None,
    cycle_id: Optional[int] = None,
) -> GateDecision:
    status = "pass"

    fail_duration = (
        thresholds.efficiency_fail_duration_seconds is not None
        and scorecard.duration_seconds > thresholds.efficiency_fail_duration_seconds
    )
    fail_tokens = (
        thresholds.efficiency_fail_tokens_used is not None
        and scorecard.tokens_used > thresholds.efficiency_fail_tokens_used
    )
    warn_duration = (
        thresholds.efficiency_warn_duration_seconds is not None
        and scorecard.duration_seconds > thresholds.efficiency_warn_duration_seconds
    )
    warn_tokens = (
        thresholds.efficiency_warn_tokens_used is not None
        and scorecard.tokens_used > thresholds.efficiency_warn_tokens_used
    )

    if fail_duration or fail_tokens:
        status = "fail"
    elif warn_duration or warn_tokens:
        status = "warn"

    return _new_gate(
        gate_name="efficiency",
        gate_status=status,
        evidence={
            "duration_seconds": scorecard.duration_seconds,
            "tokens_used": scorecard.tokens_used,
            "warn_duration_seconds": thresholds.efficiency_warn_duration_seconds,
            "fail_duration_seconds": thresholds.efficiency_fail_duration_seconds,
            "warn_tokens_used": thresholds.efficiency_warn_tokens_used,
            "fail_tokens_used": thresholds.efficiency_fail_tokens_used,
        },
        run_id=run_id,
        cycle_id=cycle_id,
    )


def evaluate_all_gates(
    scorecard: Scorecard,
    thresholds: Optional[GateThresholds] = None,
    run_id: Optional[str] = None,
    cycle_id: Optional[int] = None,
) -> List[GateDecision]:
    """Evaluate all default gates in a fixed order."""
    t = thresholds or GateThresholds()
    return [
        evaluate_reliability(scorecard, t, run_id=run_id, cycle_id=cycle_id),
        evaluate_stability(scorecard, t, run_id=run_id, cycle_id=cycle_id),
        evaluate_learning(scorecard, t, run_id=run_id, cycle_id=cycle_id),
        evaluate_safety(scorecard, t, run_id=run_id, cycle_id=cycle_id),
        evaluate_efficiency(scorecard, t, run_id=run_id, cycle_id=cycle_id),
    ]
