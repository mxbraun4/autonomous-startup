"""Tests for customer environment seed loading and validation."""
import json
from pathlib import Path

import pytest

from src.simulation.customer_environment import (
    _derive_outreach_signals_from_data,
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


def test_build_environment_input_excludes_visitors_by_default():
    """Marketplace mode should drop visitor cohort and acquisition signals by default."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [],
        "outreach_signals": [],
        "acquisition_signals": [
            {
                "visitor_id": "visitor_001",
                "article_relevance": 0.80,
                "tool_usefulness": 0.82,
                "cta_clarity": 0.75,
            }
        ],
    }

    environment_input = build_customer_environment_input(
        run_id="run_no_visitors_001",
        iteration=1,
        seed=42,
        params=params,
        signals=signals,
    )

    assert environment_input["cohorts"]["visitors"] == []
    assert environment_input["signals"]["acquisition_signals"] == []


def test_build_environment_input_can_include_visitors_when_enabled():
    """Visitor cohort and acquisition signals should be preserved when enabled."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [],
        "outreach_signals": [],
        "acquisition_signals": [
            {
                "visitor_id": "visitor_001",
                "article_relevance": 0.80,
                "tool_usefulness": 0.82,
                "cta_clarity": 0.75,
            }
        ],
    }

    environment_input = build_customer_environment_input(
        run_id="run_with_visitors_001",
        iteration=1,
        seed=42,
        params=params,
        signals=signals,
        include_visitors=True,
    )

    assert len(environment_input["cohorts"]["visitors"]) > 0
    assert len(environment_input["signals"]["acquisition_signals"]) == 1


def test_build_environment_input_applies_product_event_instrumentation():
    """Product events should deterministically override founder signup pre-signals."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    product_events = [
        {
            "event_id": "evt_001",
            "timestamp": "2026-02-19T10:00:00Z",
            "session_id": "session_001",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "landing_view",
            "properties": {"utm_source": "startup_community"},
        },
        {
            "event_id": "evt_002",
            "timestamp": "2026-02-19T10:00:01Z",
            "session_id": "session_001",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "cta_impression",
            "properties": {},
        },
        {
            "event_id": "evt_003",
            "timestamp": "2026-02-19T10:00:02Z",
            "session_id": "session_001",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "cta_click",
            "properties": {},
        },
        {
            "event_id": "evt_004",
            "timestamp": "2026-02-19T10:00:03Z",
            "session_id": "session_001",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "signup_start",
            "properties": {"form_complexity_score": 0.65},
        },
        {
            "event_id": "evt_005",
            "timestamp": "2026-02-19T10:00:04Z",
            "session_id": "session_001",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "trust_block_view",
            "properties": {"trust_score": 0.82},
        },
    ]

    environment_input = build_customer_environment_input(
        run_id="run_event_instrumented_001",
        iteration=1,
        seed=42,
        params=params,
        product_events=product_events,
    )

    assert environment_input["params"]["founder_signup_cta_clarity"] == pytest.approx(1.0)
    founder_001 = next(
        founder
        for founder in environment_input["cohorts"]["founders"]
        if founder["id"] == "founder_001"
    )
    assert founder_001["channel_intent_fit"] == pytest.approx(0.90)
    assert founder_001["trust_score"] == pytest.approx(0.82)
    assert founder_001["form_complexity_score"] == pytest.approx(0.65)

    instrumentation = environment_input["run_context"]["event_instrumentation"]
    assert instrumentation["enabled"] is True
    assert instrumentation["event_count"] == len(product_events)
    assert instrumentation["scoring_formula_version"] == 1
    assert instrumentation["param_sources"]["founder_signup_cta_clarity"]["source"] == "observed_mean"
    assert instrumentation["effective_global_signup_params"]["founder_signup_cta_clarity"] == pytest.approx(
        1.0
    )


def test_product_surface_only_hides_internal_score_snapshots(tmp_path: Path):
    """Product-facing output should include only observable behavior and failure feedback."""
    seed_payload = {
        "version": 1,
        "founders": [
            {
                "id": "founder_001",
                "sector": "fintech",
                "stage": "seed",
                "geography": "Germany",
                "fundraising_status": "active",
                "urgency_score": 1.0,
            }
        ],
        "vcs": [
            {
                "id": "vc_001",
                "thesis_sectors": ["fintech"],
                "stage_focus": "seed",
                "geography": "Europe",
                "confidence_threshold": 0.0,
            }
        ],
        "visitors": [],
    }
    seed_path = tmp_path / "customers_product_surface_only.json"
    seed_path.write_text(json.dumps(seed_payload), encoding="utf-8")

    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 1.0,
        "founder_signup_cta_clarity": 1.0,
        "founder_signup_friction": 0.0,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
        "vc_signup_base_rate": 0.0,
        "match_score_threshold": 1.0,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 0.99,
                "explanation_quality": 0.60,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.50,
                "timing_score": 0.50,
            }
        ],
        "acquisition_signals": [],
    }

    environment_input = build_customer_environment_input(
        run_id="run_product_surface_only_001",
        iteration=1,
        seed=42,
        params=params,
        seed_path=str(seed_path),
        signals=signals,
        product_surface_only=True,
    )
    output = run_customer_environment(environment_input)

    assert output["diagnostics"]["product_surface_only"] is True

    assert output["events"]
    assert "score_snapshot" not in output["events"][0]

    founder_interactions = output["diagnostics"]["interaction_logs"]["founders"]["founder_001"]
    assert founder_interactions
    assert "score_snapshot" not in founder_interactions[0]
    assert "feedback_to_system" in founder_interactions[0]
    assert "feedback_category" in founder_interactions[0]
    assert "feedback_action_hint" in founder_interactions[0]
    assert founder_interactions[0]["feedback_contract_version"] == 1

    failure_feedback = output["diagnostics"]["failure_feedback"]
    assert failure_feedback
    assert "score_snapshot" not in failure_feedback[0]
    assert "feedback_to_system" in failure_feedback[0]
    assert "feedback_category" in failure_feedback[0]
    assert "feedback_action_hint" in failure_feedback[0]
    assert failure_feedback[0]["feedback_contract_version"] == 1

    assert output["diagnostics"]["product_surface"]["events"] == output["events"]
    assert output["diagnostics"]["feedback_contract_version"] == 1


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
        "founder_engaged_to_matched_rate",
        "vc_engaged_to_matched_rate",
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


def test_match_score_is_derived_from_profiles_not_input_signal(tmp_path: Path):
    """Match quality should be derived from cohort data even if input match signals are low."""
    seed_payload = {
        "version": 1,
        "founders": [
            {
                "id": "founder_001",
                "sector": "fintech",
                "stage": "seed",
                "geography": "Germany",
                "fundraising_status": "active",
                "urgency_score": 1.0,
            }
        ],
        "vcs": [
            {
                "id": "vc_001",
                "thesis_sectors": ["fintech"],
                "stage_focus": "seed",
                "geography": "Europe",
                "confidence_threshold": 0.5,
            }
        ],
        "visitors": [],
    }
    seed_path = tmp_path / "customers_match_derived.json"
    seed_path.write_text(json.dumps(seed_payload), encoding="utf-8")

    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 1.0,
        "founder_signup_cta_clarity": 1.0,
        "founder_signup_friction": 0.0,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
        "vc_signup_base_rate": 0.0,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 0.0,
                "explanation_quality": 0.0,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.5,
                "timing_score": 0.5,
            }
        ],
        "acquisition_signals": [],
    }

    environment_input = build_customer_environment_input(
        run_id="run_match_derived_001",
        iteration=1,
        seed=42,
        params=params,
        seed_path=str(seed_path),
        signals=signals,
    )
    output = run_customer_environment(environment_input)

    founder_interactions = output["diagnostics"]["interaction_logs"]["founders"]["founder_001"]
    engaged_interaction = next(
        item for item in founder_interactions if item["step_id"] == "signup_to_engaged"
    )

    assert engaged_interaction["score_snapshot"]["match_score"] > 0.5
    assert output["metrics"]["average_match_relevance"] > 0.5
    assert output["diagnostics"]["match_signal_source"] == "derived_from_cohort_data"
    assert output["diagnostics"]["input_match_signal_count"] == 1
    assert output["diagnostics"]["derived_match_signal_count"] == 1


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


def test_founder_signup_requires_complete_signup_payload(tmp_path: Path):
    """Founder visit->signup should fail deterministically when required signup fields are missing."""
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
                "signup_payload": {
                    "sector": "fintech",
                    "stage": "",
                    "geography": "Germany",
                    "fundraising_status": "active",
                },
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
    seed_path = tmp_path / "customers_founder_signup_incomplete.json"
    seed_path.write_text(json.dumps(seed_payload), encoding="utf-8")

    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 1.0,
        "founder_signup_cta_clarity": 1.0,
        "founder_signup_friction": 0.0,
        "vc_signup_base_rate": 0.0,
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
        run_id="run_founder_signup_incomplete_001",
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
    founder_interactions = output["diagnostics"]["interaction_logs"]["founders"]["founder_test_001"]

    assert founder_events == []
    assert output["final_states"]["founders"]["founder_test_001"] == "visit"
    assert founder_interactions[0]["step_id"] == "visit_to_signup"
    assert founder_interactions[0]["decision_mode"] == "deterministic_validation"
    assert founder_interactions[0]["outcome"] == "failed"
    assert founder_interactions[0]["reason_code"] == "founder_signup_incomplete_profile"
    assert founder_interactions[0]["feedback_category"] == "signup_validation"
    assert "stage" in founder_interactions[0]["score_snapshot"]["missing_required_fields"]


def test_vc_signup_requires_complete_signup_payload(tmp_path: Path):
    """VC visit->signup should fail deterministically when required signup fields are missing."""
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
                "signup_payload": {
                    "thesis_sectors": [],
                    "stage_focus": "seed",
                    "geography": "Europe",
                },
            }
        ],
        "visitors": [],
    }
    seed_path = tmp_path / "customers_vc_signup_incomplete.json"
    seed_path.write_text(json.dumps(seed_payload), encoding="utf-8")

    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 0.0,
        "vc_signup_base_rate": 1.0,
        "vc_signup_cta_clarity": 1.0,
        "vc_signup_friction": 0.0,
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
        run_id="run_vc_signup_incomplete_001",
        iteration=1,
        seed=42,
        params=params,
        seed_path=str(seed_path),
        signals=signals,
    )
    output = run_customer_environment(environment_input)

    vc_events = [
        event
        for event in output["events"]
        if event["actor_type"] == "vc" and event["actor_id"] == "vc_test_001"
    ]
    vc_interactions = output["diagnostics"]["interaction_logs"]["vcs"]["vc_test_001"]

    assert vc_events == []
    assert output["final_states"]["vcs"]["vc_test_001"] == "visit"
    assert vc_interactions[0]["step_id"] == "visit_to_signup"
    assert vc_interactions[0]["decision_mode"] == "deterministic_validation"
    assert vc_interactions[0]["outcome"] == "failed"
    assert vc_interactions[0]["reason_code"] == "vc_signup_incomplete_profile"
    assert vc_interactions[0]["feedback_category"] == "signup_validation"
    assert "thesis_sectors" in vc_interactions[0]["score_snapshot"]["missing_required_fields"]


def test_validate_environment_input_allows_missing_outreach_bucket():
    """Outreach signal bucket is optional because outreach quality is data-derived."""
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
    del environment_input["signals"]["outreach_signals"]

    errors = validate_environment_input(environment_input)
    assert not any("outreach_signals" in error for error in errors)


def test_validate_environment_input_rejects_invalid_signup_payload_type():
    """Validation should reject non-object signup payloads in cohorts."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    environment_input = build_customer_environment_input(
        run_id="run_invalid_signup_payload_001",
        iteration=1,
        seed=42,
        params=params,
    )
    environment_input["cohorts"]["founders"][0]["signup_payload"] = "invalid_payload"

    errors = validate_environment_input(environment_input)

    assert any(".signup_payload must be an object" in error for error in errors)


def test_founder_visit_to_signup_ignores_match_preview_signal(tmp_path: Path):
    """Founder signup should not depend on pre-signup match/explanation preview signals."""
    seed_payload = {
        "version": 1,
        "founders": [
            {
                "id": "founder_001",
                "sector": "fintech",
                "stage": "seed",
                "geography": "Germany",
                "fundraising_status": "active",
                "urgency_score": 1.0,
            }
        ],
        "vcs": [
            {
                "id": "vc_001",
                "thesis_sectors": ["fintech"],
                "stage_focus": "seed",
                "geography": "Europe",
                "confidence_threshold": 0.0,
            }
        ],
        "visitors": [],
    }
    seed_path = tmp_path / "customers_founder_signup_preview.json"
    seed_path.write_text(json.dumps(seed_payload), encoding="utf-8")

    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 0.50,
        "founder_signup_cta_clarity": 1.0,
        "founder_signup_friction": 0.0,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
        "vc_signup_base_rate": 0.0,
        "meeting_rate_from_mutual_interest": 0.35,
    }

    low_preview_signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 0.0,
                "explanation_quality": 0.0,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.0,
                "timing_score": 0.0,
            }
        ],
        "acquisition_signals": [],
    }
    high_preview_signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 1.0,
                "explanation_quality": 1.0,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.0,
                "timing_score": 0.0,
            }
        ],
        "acquisition_signals": [],
    }

    low_preview_input = build_customer_environment_input(
        run_id="run_founder_signup_low_preview",
        iteration=1,
        seed=7,
        params=params,
        seed_path=str(seed_path),
        signals=low_preview_signals,
    )
    high_preview_input = build_customer_environment_input(
        run_id="run_founder_signup_high_preview",
        iteration=1,
        seed=7,
        params=params,
        seed_path=str(seed_path),
        signals=high_preview_signals,
    )

    low_preview_output = run_customer_environment(low_preview_input)
    high_preview_output = run_customer_environment(high_preview_input)

    low_signup = low_preview_output["diagnostics"]["interaction_logs"]["founders"]["founder_001"][0]
    high_signup = high_preview_output["diagnostics"]["interaction_logs"]["founders"]["founder_001"][0]

    assert low_signup["step_id"] == "visit_to_signup"
    assert high_signup["step_id"] == "visit_to_signup"
    assert low_signup["outcome"] == high_signup["outcome"]
    assert low_signup["reason_code"] == high_signup["reason_code"]
    assert low_signup["score_snapshot"]["signup_prob"] == high_signup["score_snapshot"]["signup_prob"]
    assert "preview_match_quality" not in low_signup["score_snapshot"]
    assert "preview_match_quality" not in high_signup["score_snapshot"]


def test_founder_signup_reflects_new_presignup_signal_drivers(tmp_path: Path):
    """Founder signup should respond to trust, form complexity, channel fit, and proof signals."""
    seed_payload = {
        "version": 1,
        "founders": [
            {
                "id": "founder_001",
                "sector": "fintech",
                "stage": "seed",
                "geography": "Germany",
                "fundraising_status": "active",
                "urgency_score": 1.0,
            }
        ],
        "vcs": [
            {
                "id": "vc_001",
                "thesis_sectors": ["fintech"],
                "stage_focus": "seed",
                "geography": "Europe",
                "confidence_threshold": 0.0,
            }
        ],
        "visitors": [],
    }
    seed_path = tmp_path / "customers_founder_signup_presignals.json"
    seed_path.write_text(json.dumps(seed_payload), encoding="utf-8")

    shared_params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 0.75,
        "founder_signup_cta_clarity": 1.0,
        "founder_signup_friction": 0.0,
        "vc_signup_base_rate": 0.0,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    high_signal_params = {
        **shared_params,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
    }
    low_signal_params = {
        **shared_params,
        "founder_signup_trust_score": 0.0,
        "founder_signup_form_complexity": 1.0,
        "founder_signup_channel_intent_fit": 0.0,
        "founder_signup_proof_of_outcomes": 0.0,
    }

    signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 0.50,
                "explanation_quality": 0.50,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.50,
                "timing_score": 0.50,
            }
        ],
        "acquisition_signals": [],
    }

    high_signal_input = build_customer_environment_input(
        run_id="run_founder_signup_presignals_high",
        iteration=1,
        seed=42,
        params=high_signal_params,
        seed_path=str(seed_path),
        signals=signals,
    )
    low_signal_input = build_customer_environment_input(
        run_id="run_founder_signup_presignals_low",
        iteration=1,
        seed=42,
        params=low_signal_params,
        seed_path=str(seed_path),
        signals=signals,
    )

    high_signal_output = run_customer_environment(high_signal_input)
    low_signal_output = run_customer_environment(low_signal_input)

    high_signup = high_signal_output["diagnostics"]["interaction_logs"]["founders"]["founder_001"][0]
    low_signup = low_signal_output["diagnostics"]["interaction_logs"]["founders"]["founder_001"][0]

    assert high_signup["step_id"] == "visit_to_signup"
    assert low_signup["step_id"] == "visit_to_signup"
    assert high_signup["score_snapshot"]["signup_prob"] > low_signup["score_snapshot"]["signup_prob"]
    assert high_signup["outcome"] == "passed"
    assert low_signup["outcome"] == "failed"


def test_validate_environment_input_allows_missing_acquisition_signals():
    """Acquisition signal bucket is optional in founder/VC-focused mode."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    environment_input = build_customer_environment_input(
        run_id="run_optional_acq_001",
        iteration=1,
        seed=42,
        params=params,
    )
    del environment_input["signals"]["acquisition_signals"]

    errors = validate_environment_input(environment_input)
    assert not any("acquisition_signals" in error for error in errors)


def test_validate_environment_input_allows_missing_match_signals():
    """Match signal bucket is optional because match quality is data-derived."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    environment_input = build_customer_environment_input(
        run_id="run_optional_match_001",
        iteration=1,
        seed=42,
        params=params,
    )
    del environment_input["signals"]["match_signals"]

    errors = validate_environment_input(environment_input)
    assert not any("match_signals" in error for error in errors)


def test_validate_environment_input_rejects_invalid_llm_explanation_controls():
    """Validation should reject invalid LLM explanation-quality control types."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    environment_input = build_customer_environment_input(
        run_id="run_invalid_llm_expl_001",
        iteration=1,
        seed=42,
        params=params,
    )
    environment_input["run_context"]["use_llm_explanation_quality"] = "yes"
    environment_input["run_context"]["llm_explanation_model"] = ""
    environment_input["run_context"]["llm_explanation_temperature"] = 1.5

    errors = validate_environment_input(environment_input)

    assert any("use_llm_explanation_quality" in error for error in errors)
    assert any("llm_explanation_model" in error for error in errors)
    assert any("llm_explanation_temperature" in error for error in errors)


def test_validate_environment_input_rejects_invalid_llm_personalization_controls():
    """Validation should reject invalid LLM personalization control types."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    environment_input = build_customer_environment_input(
        run_id="run_invalid_llm_personalization_001",
        iteration=1,
        seed=42,
        params=params,
    )
    environment_input["run_context"]["use_llm_personalization_score"] = "yes"
    environment_input["run_context"]["llm_personalization_model"] = ""
    environment_input["run_context"]["llm_personalization_temperature"] = 1.5

    errors = validate_environment_input(environment_input)

    assert any("use_llm_personalization_score" in error for error in errors)
    assert any("llm_personalization_model" in error for error in errors)
    assert any("llm_personalization_temperature" in error for error in errors)


def test_validate_environment_input_rejects_invalid_match_calibration_controls():
    """Validation should reject invalid match-calibration control types."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    environment_input = build_customer_environment_input(
        run_id="run_invalid_match_calibration_001",
        iteration=1,
        seed=42,
        params=params,
    )
    environment_input["run_context"]["match_calibration_path"] = 123
    environment_input["run_context"]["match_calibration_min_samples"] = 0

    errors = validate_environment_input(environment_input)

    assert any("match_calibration_path" in error for error in errors)
    assert any("match_calibration_min_samples" in error for error in errors)


def test_match_score_can_be_calibrated_from_labeled_outcomes(tmp_path: Path):
    """Labeled outcomes should update match component weights and affect scores."""
    seed_payload = {
        "version": 1,
        "founders": [
            {
                "id": "founder_001",
                "sector": "fintech",
                "stage": "seed",
                "geography": "Germany",
                "fundraising_status": "active",
                "urgency_score": 1.0,
            }
        ],
        "vcs": [
            {
                "id": "vc_001",
                "thesis_sectors": ["fintech"],
                "stage_focus": "series_c",
                "geography": "Israel",
                "confidence_threshold": 0.5,
            }
        ],
        "visitors": [],
    }
    seed_path = tmp_path / "customers_match_calibration.json"
    seed_path.write_text(json.dumps(seed_payload), encoding="utf-8")

    labeled_outcomes = {
        "version": 1,
        "samples": [
            {
                "feature_scores": {
                    "sector_score": 1.0,
                    "stage_score": 0.0,
                    "geo_score": 0.0,
                    "fundraising_score": 1.0,
                },
                "outcome_label": 0.0,
            },
            {
                "feature_scores": {
                    "sector_score": 0.0,
                    "stage_score": 1.0,
                    "geo_score": 1.0,
                    "fundraising_score": 1.0,
                },
                "outcome_label": 1.0,
            },
            {
                "feature_scores": {
                    "sector_score": 1.0,
                    "stage_score": 0.0,
                    "geo_score": 0.0,
                    "fundraising_score": 0.0,
                },
                "outcome_label": 0.0,
            },
            {
                "feature_scores": {
                    "sector_score": 0.0,
                    "stage_score": 1.0,
                    "geo_score": 1.0,
                    "fundraising_score": 0.0,
                },
                "outcome_label": 1.0,
            },
        ],
    }
    outcomes_path = tmp_path / "match_outcomes.json"
    outcomes_path.write_text(json.dumps(labeled_outcomes), encoding="utf-8")

    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 1.0,
        "founder_signup_cta_clarity": 1.0,
        "founder_signup_friction": 0.0,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
        "vc_signup_base_rate": 0.0,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.5,
                "timing_score": 0.5,
            }
        ],
        "acquisition_signals": [],
    }

    baseline_input = build_customer_environment_input(
        run_id="run_match_calibration_baseline",
        iteration=1,
        seed=42,
        params=params,
        seed_path=str(seed_path),
        signals=signals,
    )
    calibrated_input = build_customer_environment_input(
        run_id="run_match_calibration_active",
        iteration=1,
        seed=42,
        params=params,
        seed_path=str(seed_path),
        signals=signals,
        match_calibration_path=str(outcomes_path),
        match_calibration_min_samples=2,
    )

    baseline_output = run_customer_environment(baseline_input)
    calibrated_output = run_customer_environment(calibrated_input)

    baseline_step = next(
        item
        for item in baseline_output["diagnostics"]["interaction_logs"]["founders"]["founder_001"]
        if item["step_id"] == "signup_to_engaged"
    )
    calibrated_step = next(
        item
        for item in calibrated_output["diagnostics"]["interaction_logs"]["founders"]["founder_001"]
        if item["step_id"] == "signup_to_engaged"
    )

    calibration = calibrated_output["diagnostics"]["match_calibration"]
    assert calibration["active"] is True
    assert calibration["valid_samples"] == 4
    assert calibration["reason"] == "calibrated_from_labeled_outcomes"
    assert (
        calibration["weights_after"]["sector"]
        < calibration["weights_before"]["sector"]
    )
    assert (
        calibrated_step["score_snapshot"]["match_score"]
        < baseline_step["score_snapshot"]["match_score"]
    )


def test_timing_score_is_derived_from_product_perception():
    """Timing should increase when product perception is stronger for the founder."""
    founders = [
        {
            "id": "founder_high",
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.6,
            "trust_score": 1.0,
            "channel_intent_fit": 1.0,
            "proof_of_outcomes": 1.0,
            "form_complexity_score": 0.0,
        },
        {
            "id": "founder_low",
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.6,
            "trust_score": 0.0,
            "channel_intent_fit": 0.0,
            "proof_of_outcomes": 0.0,
            "form_complexity_score": 1.0,
        },
    ]
    vcs = [
        {
            "id": "vc_001",
            "thesis_sectors": ["fintech"],
            "stage_focus": "seed",
            "geography": "Europe",
            "confidence_threshold": 0.4,
        }
    ]
    params = {
        "founder_signup_cta_clarity": 0.72,
        "founder_signup_friction": 0.30,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
        "vc_signup_cta_clarity": 0.68,
        "vc_signup_friction": 0.33,
        "derived_personalization_score_boost": 0.0,
        "derived_timing_score_boost": 0.0,
    }
    match_signals = [
        {
            "founder_id": "founder_high",
            "vc_id": "vc_001",
            "match_score": 0.80,
            "explanation_quality": 0.75,
        },
        {
            "founder_id": "founder_low",
            "vc_id": "vc_001",
            "match_score": 0.80,
            "explanation_quality": 0.75,
        },
    ]

    outreach = _derive_outreach_signals_from_data(
        founders=founders,
        vcs=vcs,
        params=params,
        match_signals=match_signals,
        personalization_score_evaluator=None,
    )
    by_founder = {item["founder_id"]: item for item in outreach}
    high = by_founder["founder_high"]
    low = by_founder["founder_low"]

    assert high["timing_score_source"] == "product_perception"
    assert high["product_perception_score"] > low["product_perception_score"]
    assert high["timing_score"] > low["timing_score"]


def test_personalization_score_is_derived_from_product_perception_context():
    """Personalization should increase when product perception is stronger."""
    founders = [
        {
            "id": "founder_high",
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.6,
            "trust_score": 1.0,
            "channel_intent_fit": 1.0,
            "proof_of_outcomes": 1.0,
            "form_complexity_score": 0.0,
        },
        {
            "id": "founder_low",
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.6,
            "trust_score": 0.0,
            "channel_intent_fit": 0.0,
            "proof_of_outcomes": 0.0,
            "form_complexity_score": 1.0,
        },
    ]
    vcs = [
        {
            "id": "vc_001",
            "thesis_sectors": ["fintech"],
            "stage_focus": "seed",
            "geography": "Europe",
            "confidence_threshold": 0.4,
        }
    ]
    params = {
        "founder_signup_cta_clarity": 0.72,
        "founder_signup_friction": 0.30,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
        "vc_signup_cta_clarity": 0.68,
        "vc_signup_friction": 0.33,
        "derived_personalization_score_boost": 0.0,
        "derived_timing_score_boost": 0.0,
    }
    match_signals = [
        {
            "founder_id": "founder_high",
            "vc_id": "vc_001",
            "match_score": 0.80,
            "explanation_quality": 0.75,
        },
        {
            "founder_id": "founder_low",
            "vc_id": "vc_001",
            "match_score": 0.80,
            "explanation_quality": 0.75,
        },
    ]

    outreach = _derive_outreach_signals_from_data(
        founders=founders,
        vcs=vcs,
        params=params,
        match_signals=match_signals,
        personalization_score_evaluator=None,
    )
    by_founder = {item["founder_id"]: item for item in outreach}
    high = by_founder["founder_high"]
    low = by_founder["founder_low"]

    assert high["personalization_score_source"] == "deterministic"
    assert high["product_perception_score"] > low["product_perception_score"]
    assert high["personalization_score"] > low["personalization_score"]


def test_vc_journey_uses_matched_state_transition():
    """VC flow should use matched transition instead of shortlist."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 1.0,
        "vc_signup_base_rate": 1.0,
        "founder_signup_cta_clarity": 1.0,
        "vc_signup_cta_clarity": 1.0,
        "founder_signup_friction": 0.0,
        "vc_signup_friction": 0.0,
        "match_score_threshold": 0.5,
        "vc_match_score_threshold": 0.5,
        "interest_threshold": 0.0,
        "meeting_rate_from_mutual_interest": 0.0,
    }
    signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 0.95,
                "explanation_quality": 0.90,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.92,
                "timing_score": 0.88,
            }
        ],
        "acquisition_signals": [],
    }

    environment_input = build_customer_environment_input(
        run_id="run_vc_matched_001",
        iteration=1,
        seed=42,
        params=params,
        signals=signals,
    )
    output = run_customer_environment(environment_input)

    vc_events = [
        event
        for event in output["events"]
        if event["actor_type"] == "vc" and event["actor_id"] == "vc_001"
    ]
    assert any(event["to_state"] == "matched" for event in vc_events)
    assert not any(event["to_state"] == "shortlist" for event in vc_events)


def test_transition_failures_emit_feedback_to_system():
    """Failed transitions should include structured feedback to the system."""
    params = {
        "founder_base_interest": 0.15,
        "vc_base_interest": 0.12,
        "founder_signup_base_rate": 0.0,
        "vc_signup_base_rate": 1.0,
        "meeting_rate_from_mutual_interest": 0.35,
    }
    signals = {
        "match_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "match_score": 0.70,
                "explanation_quality": 0.65,
            }
        ],
        "outreach_signals": [
            {
                "founder_id": "founder_001",
                "vc_id": "vc_001",
                "personalization_score": 0.60,
                "timing_score": 0.55,
            }
        ],
        "acquisition_signals": [],
    }

    environment_input = build_customer_environment_input(
        run_id="run_feedback_001",
        iteration=1,
        seed=42,
        params=params,
        signals=signals,
    )
    output = run_customer_environment(environment_input)

    founder_interactions = output["diagnostics"]["interaction_logs"]["founders"]["founder_001"]
    assert founder_interactions
    assert founder_interactions[0]["step_id"] == "visit_to_signup"
    assert founder_interactions[0]["outcome"] == "failed"
    assert founder_interactions[0]["reason_code"] == "founder_no_signup"
    assert founder_interactions[0]["feedback_to_system"]
    assert founder_interactions[0]["feedback_category"] == "signup_conversion"
    assert founder_interactions[0]["feedback_contract_version"] == 1

    failure_feedback = output["diagnostics"]["failure_feedback"]
    assert any(item["reason_code"] == "founder_no_signup" for item in failure_feedback)
    founder_failure = next(
        item for item in failure_feedback if item["reason_code"] == "founder_no_signup"
    )
    assert founder_failure["feedback_category"] == "signup_conversion"
    assert founder_failure["feedback_contract_version"] == 1
