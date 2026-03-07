"""Tests for Layer G evaluation components."""

import pytest

from src.framework.contracts import CycleMetrics
from src.framework.eval import Evaluator, GateThresholds, build_scorecard


def _cycle_metrics(
    *,
    run_id: str = "run_1",
    cycle_id: int = 1,
    task_count: int = 10,
    success_count: int = 10,
    failure_count: int = 0,
    duration_seconds: float = 5.0,
    tokens_used: int = 1000,
    domain_metrics: dict | None = None,
) -> CycleMetrics:
    return CycleMetrics(
        run_id=run_id,
        cycle_id=cycle_id,
        task_count=task_count,
        success_count=success_count,
        failure_count=failure_count,
        duration_seconds=duration_seconds,
        tokens_used=tokens_used,
        domain_metrics=domain_metrics or {},
    )


def test_build_scorecard_computes_rates_and_delta():
    previous = _cycle_metrics(
        cycle_id=1,
        task_count=5,
        success_count=4,
        failure_count=1,
        domain_metrics={"procedure_score": 0.60},
    )
    current = _cycle_metrics(
        cycle_id=2,
        task_count=10,
        success_count=8,
        failure_count=2,
        domain_metrics={
            "procedure_score": 0.75,
            "policy_violations": 1,
            "determinism_variance": 0.02,
        },
    )

    scorecard = build_scorecard(current, previous)
    assert scorecard.completion_rate == 0.8
    assert scorecard.failure_rate == 0.2
    assert scorecard.policy_violations == 1
    assert scorecard.determinism_variance == 0.02
    assert scorecard.procedure_score_delta == pytest.approx(0.15)


def test_evaluator_returns_pass_when_all_gates_pass():
    previous = _cycle_metrics(
        cycle_id=1,
        domain_metrics={"procedure_score": 0.70},
    )
    current = _cycle_metrics(
        cycle_id=2,
        domain_metrics={
            "procedure_score": 0.80,
            "determinism_variance": 0.01,
            "policy_violations": 0,
            "loop_denials": 0,
            "unhandled_exceptions": 0,
        },
    )

    result = Evaluator().evaluate(current_metrics=current, previous_metrics=previous)
    assert result.overall_status == "pass"
    assert result.recommended_action == "continue"
    assert len(result.gates) == 5
    assert all(g.gate_status == "pass" for g in result.gates)


def test_evaluator_safety_failure_is_advisory():
    """Gates report fail status but always recommend continue (advisory only)."""
    current = _cycle_metrics(
        domain_metrics={
            "determinism_variance": 0.01,
            "procedure_score": 0.90,
            "policy_violations": 2,
            "loop_denials": 0,
            "unhandled_exceptions": 0,
        },
    )
    previous = _cycle_metrics(cycle_id=0, domain_metrics={"procedure_score": 0.80})

    result = Evaluator().evaluate(current_metrics=current, previous_metrics=previous)
    safety_gate = next(g for g in result.gates if g.gate_name == "safety")
    assert safety_gate.gate_status == "fail"
    assert safety_gate.recommended_action == "continue"
    assert result.overall_status == "fail"
    assert result.recommended_action == "continue"


def test_evaluator_learning_failure_is_advisory():
    """Learning gate failure is informational — no forced rollback."""
    previous = _cycle_metrics(
        cycle_id=1,
        domain_metrics={"procedure_score": 0.80},
    )
    current = _cycle_metrics(
        cycle_id=2,
        domain_metrics={
            "procedure_score": 0.50,
            "determinism_variance": 0.01,
            "policy_violations": 0,
            "loop_denials": 0,
            "unhandled_exceptions": 0,
        },
    )

    result = Evaluator().evaluate(current_metrics=current, previous_metrics=previous)
    learning_gate = next(g for g in result.gates if g.gate_name == "learning")
    assert learning_gate.gate_status == "fail"
    assert learning_gate.recommended_action == "continue"
    assert result.overall_status == "fail"
    assert result.recommended_action == "continue"


def test_evaluator_efficiency_failure_is_advisory():
    """Efficiency gate failure is informational — no forced pause."""
    thresholds = GateThresholds(
        efficiency_fail_duration_seconds=10.0,
        efficiency_warn_duration_seconds=8.0,
    )
    previous = _cycle_metrics(
        cycle_id=1,
        domain_metrics={"procedure_score": 0.50},
    )
    current = _cycle_metrics(
        cycle_id=2,
        duration_seconds=12.0,
        domain_metrics={
            "procedure_score": 0.60,
            "determinism_variance": 0.01,
            "policy_violations": 0,
            "loop_denials": 0,
            "unhandled_exceptions": 0,
        },
    )

    result = Evaluator(thresholds=thresholds).evaluate(
        current_metrics=current,
        previous_metrics=previous,
    )
    efficiency_gate = next(g for g in result.gates if g.gate_name == "efficiency")
    assert efficiency_gate.gate_status == "fail"
    assert efficiency_gate.recommended_action == "continue"
    assert result.overall_status == "fail"
    assert result.recommended_action == "continue"
