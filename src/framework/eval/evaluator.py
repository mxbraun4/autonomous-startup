"""Evaluator: computes scorecards and gate decisions for a cycle."""

from __future__ import annotations

from typing import Any, Optional

from src.framework.contracts import CycleMetrics, EvaluationResult, GateDecision
from src.framework.eval.gates import GateThresholds, evaluate_all_gates
from src.framework.eval.scorecard import build_scorecard


_ACTION_PRIORITY = {
    "continue": 0,
    "pause": 1,
    "rollback": 2,
    "stop": 3,
}


class Evaluator:
    """Convert cycle metrics into an evaluation result with gate outputs."""

    def __init__(
        self,
        thresholds: Optional[GateThresholds] = None,
        event_emitter: Any = None,
    ) -> None:
        self._thresholds = thresholds or GateThresholds()
        self._event_emitter = event_emitter

    def evaluate(
        self,
        current_metrics: CycleMetrics,
        previous_metrics: Optional[CycleMetrics] = None,
    ) -> EvaluationResult:
        """Evaluate one cycle, optionally using the previous cycle for deltas."""
        scorecard = build_scorecard(
            current_metrics=current_metrics,
            previous_metrics=previous_metrics,
        )

        gates = evaluate_all_gates(
            scorecard=scorecard,
            thresholds=self._thresholds,
            run_id=current_metrics.run_id,
            cycle_id=current_metrics.cycle_id,
        )

        overall_status = _overall_status(gates)
        recommended_action = _recommended_action(gates)

        pass_count = sum(1 for g in gates if g.gate_status == "pass")
        warn_count = sum(1 for g in gates if g.gate_status == "warn")
        fail_count = sum(1 for g in gates if g.gate_status == "fail")

        result = EvaluationResult(
            run_id=current_metrics.run_id,
            cycle_id=current_metrics.cycle_id,
            gates=gates,
            overall_status=overall_status,
            recommended_action=recommended_action,
            summary=(
                f"Evaluation complete: pass={pass_count}, warn={warn_count}, "
                f"fail={fail_count}"
            ),
            metadata={"scorecard": scorecard.model_dump()},
        )

        self._emit("gate_decision", result)
        return result

    def _emit(self, event_type: str, payload: Any) -> None:
        if self._event_emitter is not None:
            try:
                self._event_emitter.emit(event_type, payload)
            except Exception:
                pass


def _overall_status(gates: list[GateDecision]) -> str:
    if any(g.gate_status == "fail" for g in gates):
        return "fail"
    if any(g.gate_status == "warn" for g in gates):
        return "warn"
    return "pass"


def _recommended_action(gates: list[GateDecision]) -> str:
    selected = "continue"
    for gate in gates:
        candidate = gate.recommended_action or "continue"
        if _ACTION_PRIORITY.get(candidate, 0) > _ACTION_PRIORITY.get(selected, 0):
            selected = candidate
    return selected

