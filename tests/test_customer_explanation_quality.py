"""Tests for optional explanation-quality evaluator."""

from src.simulation.customer_explanation_quality import ExplanationQualityEvaluator


def test_explanation_quality_evaluator_falls_back_to_deterministic_when_llm_disabled():
    evaluator = ExplanationQualityEvaluator(use_llm=False)
    result = evaluator.evaluate(
        founder_profile={
            "sector": "fintech",
            "stage": "seed",
            "geography": "Germany",
            "fundraising_status": "active",
        },
        vc_profile={
            "thesis_sectors": ["fintech"],
            "stage_focus": "seed",
            "geography": "Europe",
            "confidence_threshold": 0.6,
        },
        base_explanation_quality=0.72,
        context={
            "sector_score": 1.0,
            "stage_score": 1.0,
            "geo_score": 0.8,
            "fundraising_score": 1.0,
            "confidence_factor": 0.4,
            "match_score": 0.9,
            "base_explanation_quality": 0.72,
        },
    )

    assert result["score"] == 0.72
    assert result["source"] == "deterministic"
    assert result["llm_score"] is None
    assert evaluator.diagnostics()["fallback_count"] == 1
