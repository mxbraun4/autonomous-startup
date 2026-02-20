"""Tests for optional personalization-score evaluator."""

from src.simulation.customer_personalization_quality import PersonalizationScoreEvaluator


def test_personalization_score_evaluator_falls_back_to_deterministic_when_llm_disabled():
    evaluator = PersonalizationScoreEvaluator(use_llm=False)
    result = evaluator.evaluate(
        founder_profile={
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
            "urgency_score": 0.8,
            "trust_score": 0.9,
            "channel_intent_fit": 0.8,
            "proof_of_outcomes": 0.7,
            "form_complexity_score": 0.2,
        },
        vc_profile={
            "thesis_sectors": ["fintech"],
            "stage_focus": "seed",
            "geography": "Europe",
            "confidence_threshold": 0.4,
        },
        base_personalization_score=0.68,
        context={
            "product_perception_score": 0.75,
            "founder_product_perception": 0.78,
            "vc_product_perception": 0.70,
            "timing_score": 0.72,
            "match_score": 0.82,
            "explanation_quality": 0.74,
            "sector_score": 1.0,
            "stage_score": 1.0,
            "geo_score": 0.8,
            "base_personalization_score": 0.68,
        },
    )

    assert result["score"] == 0.68
    assert result["source"] == "deterministic"
    assert result["llm_score"] is None
    assert evaluator.diagnostics()["fallback_count"] == 1
