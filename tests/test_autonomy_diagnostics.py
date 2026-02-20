"""Tests for diagnostics agent event-pattern actions."""

from __future__ import annotations

from src.framework.autonomy.diagnostics import DiagnosticsAgent
from src.framework.contracts import RunConfig
from src.framework.observability import EventLogger


class _FakeAdaptiveController:
    def __init__(self) -> None:
        self.calls = 0

    def force_tighten(self, *, run_id, cycle_id, reason):
        self.calls += 1
        return [
            {
                "key": "max_steps_per_cycle",
                "before": 100,
                "after": 90,
                "reason": reason,
                "run_id": run_id,
                "cycle_id": cycle_id,
            }
        ]


def test_tool_denial_burst_adds_tool_to_denylist():
    logger = EventLogger()
    for _ in range(3):
        logger.emit(
            "tool_denied",
            {
                "run_id": "run_diag",
                "cycle_id": 1,
                "tool_name": "unstable_tool",
                "denied_reason": "policy deny",
            },
        )

    run_config = RunConfig(run_id="run_diag", policies={"denylist": []})
    agent = DiagnosticsAgent(
        event_source=logger,
        run_config=run_config,
        policy_violation_threshold=99,
        tool_denied_threshold=3,
    )
    actions = agent.scan_and_act(run_id="run_diag", cycle_id=1)

    assert any(action.action == "tool_disabled" for action in actions)
    assert "unstable_tool" in (run_config.policies.get("denylist") or [])


def test_policy_violation_burst_tightens_via_adaptive_controller():
    logger = EventLogger()
    for _ in range(3):
        logger.emit(
            "policy_violation",
            {"run_id": "run_diag", "cycle_id": 2, "reason": "violation"},
        )

    run_config = RunConfig(run_id="run_diag", max_steps_per_cycle=100)
    adaptive = _FakeAdaptiveController()
    agent = DiagnosticsAgent(
        event_source=logger,
        run_config=run_config,
        adaptive_policy_controller=adaptive,
        policy_violation_threshold=3,
        tool_denied_threshold=99,
    )
    actions = agent.scan_and_act(run_id="run_diag", cycle_id=2)

    assert adaptive.calls == 1
    assert any(action.action == "policy_tightened" for action in actions)


def test_monotonic_gate_regression_requests_strategy_shift():
    logger = EventLogger()
    logger.emit(
        "gate_decision",
        {
            "run_id": "run_diag",
            "cycle_id": 1,
            "metadata": {"scorecard": {"completion_rate": 0.92}},
        },
    )
    logger.emit(
        "gate_decision",
        {
            "run_id": "run_diag",
            "cycle_id": 2,
            "metadata": {"scorecard": {"completion_rate": 0.81}},
        },
    )
    logger.emit(
        "gate_decision",
        {
            "run_id": "run_diag",
            "cycle_id": 3,
            "metadata": {"scorecard": {"completion_rate": 0.70}},
        },
    )

    run_config = RunConfig(run_id="run_diag", policies={})
    agent = DiagnosticsAgent(
        event_source=logger,
        run_config=run_config,
        policy_violation_threshold=99,
        tool_denied_threshold=99,
        gate_drop_window=3,
    )
    actions = agent.scan_and_act(run_id="run_diag", cycle_id=3)

    assert any(action.action == "strategy_shift" for action in actions)
    assert run_config.policies.get("strategy_shift_requested") is True
