"""Tests for founder/VC transition-logic metadata model."""

import pytest

from src.simulation.customer_transition_logic import (
    TRANSITION_LOGIC_VERSION,
    get_marketplace_transition_logic,
    list_actor_phases,
    list_actor_transition_parameters,
    list_marketplace_actors,
)


def test_transition_logic_version_and_actors():
    model = get_marketplace_transition_logic()

    assert TRANSITION_LOGIC_VERSION == 1
    assert model["version"] == TRANSITION_LOGIC_VERSION
    assert list_marketplace_actors() == ["founder", "vc"]


def test_founder_and_vc_phases_start_with_visit_and_signup():
    assert list_actor_phases("founder")[:2] == ["visit", "signup"]
    assert list_actor_phases("vc")[:2] == ["visit", "signup"]
    assert "matched" in list_actor_phases("vc")
    assert "shortlist" not in list_actor_phases("vc")


def test_founder_and_vc_transition_dependencies_include_signup_drivers():
    founder_params = list_actor_transition_parameters("founder")
    vc_params = list_actor_transition_parameters("vc")

    assert "founder_signup_base_rate" in founder_params["visit_to_signup"]
    assert "founder_signup_cta_clarity" in founder_params["visit_to_signup"]
    assert "founder_signup_friction" in founder_params["visit_to_signup"]
    assert "founder_signup_trust_score" in founder_params["visit_to_signup"]
    assert "founder_signup_form_complexity" in founder_params["visit_to_signup"]
    assert "founder_signup_channel_intent_fit" in founder_params["visit_to_signup"]
    assert "founder_signup_proof_of_outcomes" in founder_params["visit_to_signup"]
    assert "trust_score" in founder_params["visit_to_signup"]
    assert "form_complexity_score" in founder_params["visit_to_signup"]
    assert "channel_intent_fit" in founder_params["visit_to_signup"]
    assert "proof_of_outcomes" in founder_params["visit_to_signup"]
    assert "sector" in founder_params["visit_to_signup"]
    assert "stage" in founder_params["visit_to_signup"]
    assert "geography" in founder_params["visit_to_signup"]
    assert "fundraising_status" in founder_params["visit_to_signup"]
    assert "preview_match_quality" not in founder_params["visit_to_signup"]
    assert "match_score" not in founder_params["visit_to_signup"]
    assert "explanation_quality" not in founder_params["visit_to_signup"]

    assert "vc_signup_base_rate" in vc_params["visit_to_signup"]
    assert "vc_signup_cta_clarity" in vc_params["visit_to_signup"]
    assert "vc_signup_friction" in vc_params["visit_to_signup"]
    assert "confidence_factor" in vc_params["visit_to_signup"]
    assert "thesis_sectors" in vc_params["visit_to_signup"]
    assert "stage_focus" in vc_params["visit_to_signup"]
    assert "geography" in vc_params["visit_to_signup"]


def test_transition_logic_contains_interaction_labels():
    model = get_marketplace_transition_logic()
    founder_signup = model["actors"]["founder"]["transitions"][0]
    vc_interest = model["actors"]["vc"]["transitions"][3]

    assert founder_signup["interaction"] == "complete_signup_form"
    assert founder_signup["precheck_failure_reason_code"] == "founder_signup_incomplete_profile"
    assert vc_interest["interaction"] == "evaluate_match_explanation"


def test_transition_logic_copy_isolated():
    first = get_marketplace_transition_logic()
    first["actors"]["founder"]["states"][0] = "changed"

    second = get_marketplace_transition_logic()
    assert second["actors"]["founder"]["states"][0] == "visit"


def test_unknown_actor_raises():
    with pytest.raises(ValueError, match="Unknown actor"):
        list_actor_phases("visitor")
