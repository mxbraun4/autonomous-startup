"""Tests for deterministic customer simulation runner script helpers."""

import json

import pytest

from scripts.run_customer_simulation import (
    _load_product_events,
    _resolve_scenarios,
    run_scenario_matrix,
)


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
    assert summary["run_context"]["use_llm_explanation_quality"] is False
    assert summary["run_context"]["use_llm_personalization_score"] is False
    assert summary["run_context"]["match_calibration_path"] is None
    assert summary["run_context"]["match_calibration_min_samples"] == 20


def test_load_product_events_rejects_non_object_items(tmp_path):
    events_path = tmp_path / "invalid_product_events.json"
    events_path.write_text(json.dumps([{"event_name": "landing_view"}, 1]), encoding="utf-8")

    with pytest.raises(ValueError, match="only objects"):
        _load_product_events(str(events_path))


def test_load_product_events_rejects_invalid_event_schema(tmp_path):
    events_path = tmp_path / "invalid_product_events_schema.json"
    events_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "evt_001",
                    "timestamp": "2026-02-19T10:00:00Z",
                    "session_id": "session_001",
                    "actor_type": "founder",
                    "actor_id": "founder_001",
                    "event_name": "landing_view",
                    "properties": {},
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid product events"):
        _load_product_events(str(events_path))
