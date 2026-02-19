"""Tests for customer environment seed loading and validation."""
import json
from pathlib import Path

import pytest

from src.simulation.customer_environment import (
    build_customer_environment_input,
    load_customer_cohorts,
    run_customer_environment,
    validate_environment_input,
)


def test_load_customer_cohorts_has_required_groups():
    """Default customer seed file loads all required cohort groups."""
    cohorts = load_customer_cohorts()

    assert "founders" in cohorts
    assert "vcs" in cohorts
    assert "visitors" in cohorts
    assert len(cohorts["founders"]) > 0
    assert len(cohorts["vcs"]) > 0
    assert len(cohorts["visitors"]) > 0


def test_load_customer_cohorts_is_deterministic():
    """Loading cohorts twice produces identical normalized payload."""
    first = load_customer_cohorts()
    second = load_customer_cohorts()

    assert first == second


def test_build_environment_input_same_seed_same_payload():
    """Same seed and same inputs should generate identical environment inputs."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "visitor_tool_click_rate": 0.20,
        "signup_rate_from_tool": 0.10,
        "meeting_rate_from_mutual_interest": 0.35,
    }

    first = build_customer_environment_input(
        run_id="run_001",
        iteration=1,
        seed=42,
        params=params,
    )
    second = build_customer_environment_input(
        run_id="run_001",
        iteration=1,
        seed=42,
        params=params,
    )

    assert first == second


def test_load_customer_cohorts_raises_for_invalid_seed_data(tmp_path: Path):
    """Invalid seed payloads raise a readable validation error."""
    invalid_seed = {
        "founders": [{"id": "f_1", "sector": "fintech"}],
        "vcs": [],
        "visitors": [],
    }
    invalid_path = tmp_path / "invalid_customers.json"
    invalid_path.write_text(json.dumps(invalid_seed), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid customer seed data"):
        load_customer_cohorts(seed_path=str(invalid_path))


def test_run_customer_environment_returns_contract_shape():
    """Runner should return contract-compliant top-level keys and metrics."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "visitor_tool_click_rate": 0.20,
        "signup_rate_from_tool": 0.10,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 0.90,
                "explanation_quality": 0.85,
            },
            {
                "founder_id": "founder_002",
                "vc_id": "vc_002",
                "match_score": 0.82,
                "explanation_quality": 0.72,
            },
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.92,
                "timing_score": 0.81,
            },
            {
                "founder_id": "founder_002",
                "vc_id": "vc_002",
                "personalization_score": 0.75,
                "timing_score": 0.66,
            },
        ],
        "acquisition_signals": [
            {
                "visitor_id": "visitor_001",
                "article_relevance": 0.88,
                "tool_usefulness": 0.91,
                "cta_clarity": 0.78,
            },
            {
                "visitor_id": "visitor_002",
                "article_relevance": 0.65,
                "tool_usefulness": 0.70,
                "cta_clarity": 0.60,
            },
        ],
    }

    environment_input = build_customer_environment_input(
        run_id="run_shape_001",
        iteration=1,
        seed=42,
        params=params,
        signals=signals,
    )
    output = run_customer_environment(environment_input)

    assert set(output.keys()) == {"metrics", "events", "final_states", "diagnostics"}
    assert set(output["final_states"].keys()) == {"founders", "vcs", "visitors"}
    assert output["diagnostics"]["input_validation_errors"] == []

    expected_metric_keys = {
        "founder_visit_to_signup",
        "vc_visit_to_signup",
        "visitor_to_tool_use",
        "tool_use_to_signup",
        "signup_to_first_match",
        "founder_interested_rate",
        "vc_interested_rate",
        "mutual_interest_rate",
        "meeting_conversion_rate",
        "average_match_relevance",
        "explanation_coverage",
        "personalization_quality_score",
    }
    assert set(output["metrics"].keys()) == expected_metric_keys
    assert all(0.0 <= value <= 1.0 for value in output["metrics"].values())


def test_run_customer_environment_is_deterministic():
    """Same environment input must produce identical output."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "visitor_tool_click_rate": 0.20,
        "signup_rate_from_tool": 0.10,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 0.90,
                "explanation_quality": 0.85,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.90,
                "timing_score": 0.80,
            }
        ],
        "acquisition_signals": [
            {
                "visitor_id": "visitor_001",
                "article_relevance": 0.80,
                "tool_usefulness": 0.85,
                "cta_clarity": 0.75,
            }
        ],
    }

    environment_input = build_customer_environment_input(
        run_id="run_det_001",
        iteration=1,
        seed=123,
        params=params,
        signals=signals,
    )
    first = run_customer_environment(environment_input)
    second = run_customer_environment(environment_input)

    assert first == second


def test_founder_and_vc_journeys_start_with_signup_transition(tmp_path: Path):
    """Founder/VC journeys should begin with a visit -> signup transition."""
    seed_payload = {
        "version": 1,
        "founders": [
            {
                "id": "founder_test_001",
                "sector": "fintech",
                "stage": "seed",
                "geography": "Germany",
                "fundraising_status": "active",
                "urgency_score": 1.0,
            }
        ],
        "vcs": [
            {
                "id": "vc_test_001",
                "thesis_sectors": ["fintech"],
                "stage_focus": "seed",
                "geography": "Europe",
                "confidence_threshold": 0.0,
            }
        ],
        "visitors": [],
    }
    seed_path = tmp_path / "customers_signup_flow.json"
    seed_path.write_text(json.dumps(seed_payload), encoding="utf-8")

    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 1.0,
        "vc_signup_base_rate": 1.0,
        "founder_signup_cta_clarity": 1.0,
        "vc_signup_cta_clarity": 1.0,
        "founder_signup_friction": 0.0,
        "vc_signup_friction": 0.0,
        "visitor_tool_click_rate": 0.20,
        "signup_rate_from_tool": 0.10,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [
            {
                "founder_id": "founder_test_001",
                "vc_id": "vc_test_001",
                "match_score": 1.0,
                "explanation_quality": 1.0,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_test_001",
                "vc_id": "vc_test_001",
                "personalization_score": 1.0,
                "timing_score": 1.0,
            }
        ],
        "acquisition_signals": [],
    }

    environment_input = build_customer_environment_input(
        run_id="run_signup_start_001",
        iteration=1,
        seed=42,
        params=params,
        seed_path=str(seed_path),
        signals=signals,
    )
    output = run_customer_environment(environment_input)

    founder_events = [
        event
        for event in output["events"]
        if event["actor_type"] == "founder" and event["actor_id"] == "founder_test_001"
    ]
    vc_events = [
        event
        for event in output["events"]
        if event["actor_type"] == "vc" and event["actor_id"] == "vc_test_001"
    ]

    assert founder_events[0]["from_state"] == "visit"
    assert founder_events[0]["to_state"] == "signup"
    assert founder_events[0]["reason_code"] == "founder_signed_up"

    assert vc_events[0]["from_state"] == "visit"
    assert vc_events[0]["to_state"] == "signup"
    assert vc_events[0]["reason_code"] == "vc_signed_up"


def test_validate_environment_input_flags_missing_signal_bucket():
    """Validation should catch missing required signal keys."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "visitor_tool_click_rate": 0.20,
        "signup_rate_from_tool": 0.10,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    environment_input = build_customer_environment_input(
        run_id="run_invalid_001",
        iteration=1,
        seed=42,
        params=params,
    )
    del environment_input["signals"]["match_signals"]

    errors = validate_environment_input(environment_input)
    output = run_customer_environment(environment_input)

    assert any("match_signals" in error for error in errors)
    assert output["diagnostics"]["input_validation_errors"]
    assert output["metrics"]["founder_interested_rate"] == 0.0
