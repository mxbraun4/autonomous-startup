"""Tests for Track D hypothesis evaluator logic."""

from src.simulation.customer_hypothesis_evaluator import evaluate_customer_hypotheses


def _base_summary():
    return {
        "determinism_failures": [],
        "scenarios": {
            "baseline": {
                "deterministic": True,
                "deltas_vs_baseline": {
                    "founder_interested_rate": 0.0,
                    "signup_to_first_match": 0.0,
                },
            },
            "high_personalization": {
                "deterministic": True,
                "deltas_vs_baseline": {
                    "founder_interested_rate": 0.04,
                    "signup_to_first_match": -0.005,
                },
            },
        },
    }


def test_evaluator_passes_hypothesis_when_threshold_and_guardrail_hold():
    summary = _base_summary()
    hypotheses = [
        {
            "id": "H_OUTREACH_001",
            "scenario": "high_personalization",
            "metric": "founder_interested_rate",
            "direction": "increase",
            "min_delta": 0.03,
            "guardrails": [
                {
                    "metric": "signup_to_first_match",
                    "min_delta": -0.01,
                }
            ],
        }
    ]

    report = evaluate_customer_hypotheses(summary, hypotheses)
    assert report["overall_status"] == "pass"
    assert report["counts"]["pass"] == 1


def test_evaluator_fails_when_primary_threshold_not_met():
    summary = _base_summary()
    hypotheses = [
        {
            "id": "H_OUTREACH_002",
            "scenario": "high_personalization",
            "metric": "founder_interested_rate",
            "direction": "increase",
            "min_delta": 0.06,
        }
    ]

    report = evaluate_customer_hypotheses(summary, hypotheses)
    assert report["overall_status"] == "fail"
    assert report["counts"]["fail"] == 1


def test_evaluator_fails_when_guardrail_breached():
    summary = _base_summary()
    hypotheses = [
        {
            "id": "H_GUARD_001",
            "scenario": "high_personalization",
            "metric": "founder_interested_rate",
            "direction": "increase",
            "min_delta": 0.03,
            "guardrails": [
                {
                    "metric": "signup_to_first_match",
                    "min_delta": 0.0,
                }
            ],
        }
    ]

    report = evaluate_customer_hypotheses(summary, hypotheses)
    assert report["overall_status"] == "fail"
    assert report["counts"]["fail"] == 1


def test_evaluator_warns_when_no_hypotheses_defined():
    report = evaluate_customer_hypotheses(_base_summary(), [])
    assert report["overall_status"] == "warn"
    assert "No hypotheses defined" in report["notes"][0]


def test_evaluator_fails_on_determinism_failures_even_if_hypothesis_passes():
    summary = _base_summary()
    summary["determinism_failures"] = ["high_personalization"]
    summary["scenarios"]["high_personalization"]["deterministic"] = False

    hypotheses = [
        {
            "id": "H_OUTREACH_003",
            "scenario": "high_personalization",
            "metric": "founder_interested_rate",
            "direction": "increase",
            "min_delta": 0.03,
        }
    ]

    report = evaluate_customer_hypotheses(summary, hypotheses)
    assert report["overall_status"] == "fail"
