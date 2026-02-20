"""Focused tests for VC customer-agent transition behavior."""

from random import Random

import pytest

from src.simulation.customer_agent import VCCustomerAgent


def test_vc_matched_to_interested_uses_personalization_score():
    profile = {
        "id": "vc_001",
        "thesis_sectors": ["fintech"],
        "stage_focus": "seed",
        "geography": "Europe",
        "confidence_threshold": 0.0,
    }
    params = {
        "vc_base_interest": 0.0,
        "vc_signup_base_rate": 1.0,
        "vc_signup_cta_clarity": 1.0,
        "vc_signup_friction": 0.0,
        "shortlist_threshold": 0.55,
        "vc_match_score_threshold": 0.0,
        "interest_threshold": 0.0,
    }
    match_signal = {
        "founder_id": "founder_001",
        "vc_id": "vc_001",
        "match_score": 1.0,
        "explanation_quality": 1.0,
    }
    low_outreach_signal = {
        "founder_id": "founder_001",
        "vc_id": "vc_001",
        "personalization_score": 0.10,
        "timing_score": 0.30,
    }
    high_outreach_signal = {
        "founder_id": "founder_001",
        "vc_id": "vc_001",
        "personalization_score": 0.90,
        "timing_score": 0.30,
    }

    low_agent = VCCustomerAgent(profile=profile, params=params, rng=Random(1))
    low_result = low_agent.simulate(
        match_signal=match_signal,
        outreach_signal=low_outreach_signal,
        max_steps=5,
    )
    high_agent = VCCustomerAgent(profile=profile, params=params, rng=Random(1))
    high_result = high_agent.simulate(
        match_signal=match_signal,
        outreach_signal=high_outreach_signal,
        max_steps=5,
    )

    low_interest_step = next(
        item
        for item in low_result["interaction_trace"]
        if item["step_id"] == "matched_to_interested"
    )
    high_interest_step = next(
        item
        for item in high_result["interaction_trace"]
        if item["step_id"] == "matched_to_interested"
    )

    assert low_interest_step["score_snapshot"]["personalization_score"] == pytest.approx(0.10)
    assert high_interest_step["score_snapshot"]["personalization_score"] == pytest.approx(0.90)
    assert (
        high_interest_step["score_snapshot"]["interest_prob"]
        > low_interest_step["score_snapshot"]["interest_prob"]
    )
    assert low_interest_step["outcome"] == "failed"
    assert high_interest_step["outcome"] == "passed"
