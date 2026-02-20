"""Tests for deterministic customer simulation scenario matrix."""

import pytest

from src.simulation.customer_environment import (
    run_customer_environment,
    validate_environment_input,
)
from src.simulation.customer_scenario_matrix import (
    SCENARIO_MATRIX_VERSION,
    build_customer_environment_input_for_scenario,
    get_customer_scenario,
    get_customer_scenario_matrix,
    list_customer_scenarios,
)


def test_scenario_matrix_has_expected_variants():
    assert SCENARIO_MATRIX_VERSION == 1
    assert list_customer_scenarios() == [
        "baseline",
        "high_personalization",
        "better_matching",
        "acquisition_push",
    ]


def test_get_customer_scenario_matrix_returns_copy():
    first = get_customer_scenario_matrix()
    first["baseline"]["params"]["founder_base_interest"] = 0.99

    second = get_customer_scenario_matrix()
    assert second["baseline"]["params"]["founder_base_interest"] == 0.15


def test_unknown_scenario_raises():
    with pytest.raises(ValueError, match="Unknown customer scenario"):
        get_customer_scenario("not_a_scenario")


def test_all_scenarios_build_contract_valid_inputs():
    for scenario_name in list_customer_scenarios():
        environment_input = build_customer_environment_input_for_scenario(
            run_id=f"run_{scenario_name}",
            iteration=1,
            scenario_name=scenario_name,
        )
        errors = validate_environment_input(environment_input)
        assert errors == []


def test_scenario_outputs_are_deterministic():
    for scenario_name in list_customer_scenarios():
        environment_input = build_customer_environment_input_for_scenario(
            run_id=f"run_{scenario_name}",
            iteration=1,
            scenario_name=scenario_name,
        )

        first = run_customer_environment(environment_input)
        second = run_customer_environment(environment_input)

        assert first == second


def test_scenario_builder_passes_llm_feedback_options():
    environment_input = build_customer_environment_input_for_scenario(
        run_id="run_baseline_llm_feedback",
        iteration=1,
        scenario_name="baseline",
        use_llm_feedback=True,
        llm_feedback_steps=["matched_to_interested"],
        use_llm_explanation_quality=True,
        llm_explanation_model="claude-3-haiku-20240307",
        llm_explanation_temperature=0.0,
        use_llm_personalization_score=True,
        llm_personalization_model="claude-3-haiku-20240307",
        llm_personalization_temperature=0.0,
        match_calibration_path="data/seed/match_outcomes_sample.json",
        match_calibration_min_samples=5,
        product_surface_only=True,
    )

    assert environment_input["run_context"]["use_llm_feedback"] is True
    assert environment_input["run_context"]["llm_feedback_steps"] == [
        "matched_to_interested"
    ]
    assert environment_input["run_context"]["use_llm_explanation_quality"] is True
    assert (
        environment_input["run_context"]["llm_explanation_model"]
        == "claude-3-haiku-20240307"
    )
    assert environment_input["run_context"]["llm_explanation_temperature"] == pytest.approx(0.0)
    assert environment_input["run_context"]["use_llm_personalization_score"] is True
    assert (
        environment_input["run_context"]["llm_personalization_model"]
        == "claude-3-haiku-20240307"
    )
    assert environment_input["run_context"]["llm_personalization_temperature"] == pytest.approx(0.0)
    assert (
        environment_input["run_context"]["match_calibration_path"]
        == "data/seed/match_outcomes_sample.json"
    )
    assert environment_input["run_context"]["match_calibration_min_samples"] == 5
    assert environment_input["run_context"]["product_surface_only"] is True


def test_scenario_builder_applies_product_events():
    environment_input = build_customer_environment_input_for_scenario(
        run_id="run_baseline_product_events",
        iteration=1,
        scenario_name="baseline",
        product_events=[
            {
                "event_id": "evt_001",
                "timestamp": "2026-02-19T10:00:00Z",
                "session_id": "session_001",
                "actor_type": "founder",
                "actor_id": "founder_001",
                "event_name": "cta_impression",
                "properties": {},
            },
            {
                "event_id": "evt_002",
                "timestamp": "2026-02-19T10:00:01Z",
                "session_id": "session_001",
                "actor_type": "founder",
                "actor_id": "founder_001",
                "event_name": "cta_click",
                "properties": {},
            },
        ],
    )

    assert environment_input["params"]["founder_signup_cta_clarity"] == pytest.approx(1.0)
    assert environment_input["run_context"]["event_instrumentation"]["enabled"] is True
