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


def test_founder_and_vc_transition_dependencies_include_signup_drivers():
    founder_params = list_actor_transition_parameters("founder")
    vc_params = list_actor_transition_parameters("vc")

    assert "founder_signup_base_rate" in founder_params["visit_to_signup"]
    assert "founder_signup_cta_clarity" in founder_params["visit_to_signup"]
    assert "founder_signup_friction" in founder_params["visit_to_signup"]
    assert "preview_match_quality" in founder_params["visit_to_signup"]

    assert "vc_signup_base_rate" in vc_params["visit_to_signup"]
    assert "vc_signup_cta_clarity" in vc_params["visit_to_signup"]
    assert "vc_signup_friction" in vc_params["visit_to_signup"]
    assert "confidence_factor" in vc_params["visit_to_signup"]


def test_transition_logic_copy_isolated():
    first = get_marketplace_transition_logic()
    first["actors"]["founder"]["states"][0] = "changed"

    second = get_marketplace_transition_logic()
    assert second["actors"]["founder"]["states"][0] == "visit"


def test_unknown_actor_raises():
    with pytest.raises(ValueError, match="Unknown actor"):
        list_actor_phases("visitor")

