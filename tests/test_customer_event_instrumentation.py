"""Tests for deterministic product-event instrumentation of signup signals."""

import pytest

from src.simulation.customer_event_instrumentation import (
    derive_signup_signal_overrides_from_events,
    validate_product_events,
)


def test_validate_product_events_rejects_invalid_payload():
    errors = validate_product_events(
        [
            {
                "event_id": "",
                "timestamp": "not-a-timestamp",
                "session_id": "",
                "event_name": "",
                "actor_type": "unknown",
                "actor_id": "",
                "properties": {"channel_intent_fit": 1.5},
            }
        ]
    )
    assert errors
    assert any("event_name" in error for error in errors)
    assert any("event_id" in error for error in errors)
    assert any("timestamp" in error for error in errors)
    assert any("session_id" in error for error in errors)
    assert any("actor_type" in error for error in errors)
    assert any("actor_id" in error for error in errors)
    assert any("channel_intent_fit" in error for error in errors)


def test_validate_product_events_rejects_unknown_event_name():
    errors = validate_product_events(
        [
            {
                "event_id": "e1",
                "timestamp": "2026-02-19T10:00:00Z",
                "session_id": "s1",
                "event_name": "unknown_event",
                "actor_type": "founder",
                "actor_id": "founder_001",
                "properties": {},
            }
        ]
    )

    assert any(".event_name must be one of:" in error for error in errors)


def test_validate_product_events_landing_view_requires_channel_or_utm():
    errors = validate_product_events(
        [
            {
                "event_id": "e1",
                "timestamp": "2026-02-19T10:00:00Z",
                "session_id": "s1",
                "event_name": "landing_view",
                "actor_type": "founder",
                "actor_id": "founder_001",
                "properties": {},
            }
        ]
    )

    assert any("landing_view requires properties.channel_intent_fit or properties.utm_source" in error for error in errors)


def test_validate_product_events_rejects_duplicate_event_id():
    errors = validate_product_events(
        [
            {
                "event_id": "e1",
                "timestamp": "2026-02-19T10:00:00Z",
                "session_id": "s1",
                "event_name": "cta_impression",
                "actor_type": "founder",
                "actor_id": "founder_001",
                "properties": {},
            },
            {
                "event_id": "e1",
                "timestamp": "2026-02-19T10:00:01Z",
                "session_id": "s1",
                "event_name": "cta_click",
                "actor_type": "founder",
                "actor_id": "founder_001",
                "properties": {},
            },
        ]
    )

    assert any("event_id must be unique" in error for error in errors)


def test_derive_signup_signal_overrides_maps_events_to_scores():
    founders = [
        {
            "id": "founder_001",
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.8,
        },
        {
            "id": "founder_002",
            "sector": "health",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.5,
        },
    ]
    default_params = {
        "founder_signup_cta_clarity": 0.72,
        "founder_signup_friction": 0.30,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
    }
    events = [
        {
            "event_id": "e1",
            "timestamp": "2026-02-19T10:00:00Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "landing_view",
            "properties": {"utm_source": "startup_community"},
        },
        {
            "event_id": "e2",
            "timestamp": "2026-02-19T10:00:01Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "cta_impression",
            "properties": {},
        },
        {
            "event_id": "e3",
            "timestamp": "2026-02-19T10:00:02Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "cta_impression",
            "properties": {},
        },
        {
            "event_id": "e4",
            "timestamp": "2026-02-19T10:00:03Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "cta_click",
            "properties": {},
        },
        {
            "event_id": "e5",
            "timestamp": "2026-02-19T10:00:04Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "signup_start",
            "properties": {"form_complexity_score": 0.70},
        },
        {
            "event_id": "e6",
            "timestamp": "2026-02-19T10:00:05Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "signup_field_error",
            "properties": {},
        },
        {
            "event_id": "e7",
            "timestamp": "2026-02-19T10:00:06Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "signup_abandon",
            "properties": {},
        },
        {
            "event_id": "e8",
            "timestamp": "2026-02-19T10:00:07Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "trust_block_view",
            "properties": {"trust_score": 0.80},
        },
        {
            "event_id": "e9",
            "timestamp": "2026-02-19T10:00:08Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "proof_block_view",
            "properties": {"proof_of_outcomes": 0.75},
        },
    ]

    derived = derive_signup_signal_overrides_from_events(
        events=events,
        founders=founders,
        default_params=default_params,
    )

    assert derived["param_overrides"]["founder_signup_cta_clarity"] == pytest.approx(0.5)
    assert derived["param_overrides"]["founder_signup_friction"] == pytest.approx(1.0)
    founder_override = derived["founder_profile_overrides"]["founder_001"]
    assert founder_override["trust_score"] == pytest.approx(0.80)
    assert founder_override["proof_of_outcomes"] == pytest.approx(0.75)
    assert founder_override["form_complexity_score"] == pytest.approx(0.70)
    assert founder_override["channel_intent_fit"] == pytest.approx(0.90)
    assert "founder_002" not in derived["founder_profile_overrides"]

    diagnostics = derived["diagnostics"]
    assert diagnostics["scoring_formula_version"] == 1
    assert diagnostics["founder_signal_sources"]["founder_001"] == {
        "founder_signup_cta_clarity": "observed_ratio",
        "founder_signup_friction": "observed_composite",
        "trust_score": "observed_value",
        "form_complexity_score": "observed_value",
        "channel_intent_fit": "observed_value",
        "proof_of_outcomes": "observed_value",
    }
    assert diagnostics["founder_signal_sources"]["founder_002"] == {
        "founder_signup_cta_clarity": "fallback_default",
        "founder_signup_friction": "fallback_default",
        "trust_score": "fallback_default",
        "form_complexity_score": "fallback_default",
        "channel_intent_fit": "fallback_default",
        "proof_of_outcomes": "fallback_default",
    }
    assert diagnostics["founder_signal_inputs"]["founder_001"]["cta_impressions"] == pytest.approx(2.0)
    assert diagnostics["founder_signal_inputs"]["founder_001"]["cta_ctr"] == pytest.approx(0.5)
    assert diagnostics["founder_signal_inputs"]["founder_001"]["signup_error_rate"] == pytest.approx(1.0)
    assert diagnostics["founder_signal_inputs"]["founder_001"]["signup_abandon_rate"] == pytest.approx(1.0)
    assert diagnostics["param_sources"]["founder_signup_cta_clarity"]["source"] == "observed_mean"
    assert diagnostics["param_sources"]["founder_signup_friction"]["source"] == "observed_mean"
    assert diagnostics["effective_global_signup_params"]["founder_signup_cta_clarity"] == pytest.approx(
        0.5
    )
    assert diagnostics["effective_global_signup_params"]["founder_signup_friction"] == pytest.approx(
        1.0
    )


def test_derive_signup_signal_overrides_is_deterministic():
    founders = [
        {
            "id": "founder_001",
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.8,
        }
    ]
    default_params = {
        "founder_signup_cta_clarity": 0.72,
        "founder_signup_friction": 0.30,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
    }
    events = [
        {
            "event_id": "e1",
            "timestamp": "2026-02-19T10:00:00Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "cta_impression",
            "properties": {},
        },
        {
            "event_id": "e2",
            "timestamp": "2026-02-19T10:00:01Z",
            "session_id": "s1",
            "actor_type": "founder",
            "actor_id": "founder_001",
            "event_name": "cta_click",
            "properties": {},
        },
    ]

    first = derive_signup_signal_overrides_from_events(
        events=events,
        founders=founders,
        default_params=default_params,
    )
    second = derive_signup_signal_overrides_from_events(
        events=events,
        founders=founders,
        default_params=default_params,
    )
    assert first == second


def test_derive_signup_signal_overrides_reports_fallback_sources_without_events():
    founders = [
        {
            "id": "founder_001",
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.8,
        }
    ]
    default_params = {
        "founder_signup_cta_clarity": 0.72,
        "founder_signup_friction": 0.30,
        "founder_signup_trust_score": 1.0,
        "founder_signup_form_complexity": 0.0,
        "founder_signup_channel_intent_fit": 1.0,
        "founder_signup_proof_of_outcomes": 1.0,
    }

    derived = derive_signup_signal_overrides_from_events(
        events=[],
        founders=founders,
        default_params=default_params,
    )
    diagnostics = derived["diagnostics"]

    assert derived["param_overrides"] == {}
    assert diagnostics["param_sources"]["founder_signup_cta_clarity"]["source"] == "fallback_default"
    assert diagnostics["param_sources"]["founder_signup_friction"]["source"] == "fallback_default"
    assert diagnostics["effective_global_signup_params"]["founder_signup_cta_clarity"] == pytest.approx(
        0.72
    )
    assert diagnostics["effective_global_signup_params"]["founder_signup_friction"] == pytest.approx(
        0.30
    )
    assert diagnostics["founder_signal_sources"]["founder_001"]["trust_score"] == "fallback_default"
    assert diagnostics["founder_signal_inputs"]["founder_001"]["signup_starts"] == pytest.approx(0.0)
