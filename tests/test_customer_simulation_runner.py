"""Tests for deterministic customer simulation runner script helpers."""

from scripts.run_customer_simulation import _resolve_scenarios, run_scenario_matrix


def test_resolve_scenarios_injects_baseline():
    selected = _resolve_scenarios(["better_matching"])
    assert selected[0] == "baseline"
    assert "better_matching" in selected


def test_run_scenario_matrix_returns_deltas_vs_baseline():
    summary = run_scenario_matrix(
        run_id_prefix="test_matrix",
        iteration=1,
        scenario_names=["baseline", "high_personalization"],
        seed_override=42,
    )

    assert summary["baseline_scenario"] == "baseline"
    assert summary["determinism_failures"] == []
    assert "baseline" in summary["scenarios"]
    assert "high_personalization" in summary["scenarios"]
    assert (
        summary["scenarios"]["baseline"]["deltas_vs_baseline"][
            "founder_interested_rate"
        ]
        == 0.0
    )
