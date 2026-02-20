"""Tests for adaptive policy controller auto-adjustments."""

from __future__ import annotations

from src.framework.autonomy.adaptive_policy import AdaptivePolicyController
from src.framework.contracts import EvaluationResult, GateDecision, RunConfig


class _FakePolicyEngine:
    def __init__(self) -> None:
        self.autonomy_level = None
        self.denylist: list[str] = []

    def set_autonomy_level(self, level: int) -> None:
        self.autonomy_level = int(level)

    def add_to_denylist(self, tool_name: str) -> None:
        self.denylist.append(tool_name)


def _evaluation(*gates: GateDecision) -> EvaluationResult:
    return EvaluationResult(
        run_id="run_policy",
        cycle_id=1,
        gates=list(gates),
        overall_status="pass",
        recommended_action="continue",
        summary="ok",
    )


def test_reliability_streak_raises_autonomy_level():
    run_config = RunConfig(run_id="run_policy", autonomy_level=1, max_steps_per_cycle=100)
    engine = _FakePolicyEngine()
    controller = AdaptivePolicyController(
        run_config=run_config,
        policy_engine=engine,
        reliability_pass_streak=2,
        bounds={"autonomy_level": {"min": 0, "max": 3}},
    )

    gate = GateDecision(gate_name="reliability", gate_status="pass", recommended_action="continue")
    controller.apply(_evaluation(gate))
    assert run_config.autonomy_level == 1

    adjustments = controller.apply(_evaluation(gate))
    assert run_config.autonomy_level == 2
    assert engine.autonomy_level == 2
    assert any(item.key == "autonomy_level" for item in adjustments)


def test_safety_failure_drops_autonomy_and_denylists_offending_tool():
    run_config = RunConfig(
        run_id="run_policy",
        autonomy_level=2,
        max_steps_per_cycle=100,
        policies={"denylist": []},
    )
    engine = _FakePolicyEngine()
    controller = AdaptivePolicyController(
        run_config=run_config,
        policy_engine=engine,
        bounds={"autonomy_level": {"min": 0, "max": 3}},
    )

    safety_gate = GateDecision(
        gate_name="safety",
        gate_status="fail",
        evidence={"offending_tools": ["dangerous_tool"]},
        recommended_action="stop",
    )
    adjustments = controller.apply(_evaluation(safety_gate))

    assert run_config.autonomy_level == 1
    assert "dangerous_tool" in (run_config.policies.get("denylist") or [])
    assert "dangerous_tool" in engine.denylist
    keys = {item.key for item in adjustments}
    assert "autonomy_level" in keys
    assert "denylist" in keys


def test_efficiency_and_learning_adjust_max_steps_with_bounds():
    run_config = RunConfig(run_id="run_policy", autonomy_level=1, max_steps_per_cycle=100)
    controller = AdaptivePolicyController(
        run_config=run_config,
        step_adjustment_ratio=0.10,
        learning_improvement_threshold=0.05,
        bounds={"max_steps_per_cycle": {"min": 50, "max": 120}},
    )

    efficiency_gate = GateDecision(
        gate_name="efficiency",
        gate_status="fail",
        recommended_action="pause",
    )
    controller.apply(_evaluation(efficiency_gate))
    assert run_config.max_steps_per_cycle == 90

    learning_gate = GateDecision(
        gate_name="learning",
        gate_status="pass",
        evidence={"procedure_score_delta": 0.25},
        recommended_action="continue",
    )
    controller.apply(_evaluation(learning_gate))
    assert run_config.max_steps_per_cycle == 99
