"""Tests for Track D customer hypothesis schema and loader."""

import json
from pathlib import Path

import pytest

from src.simulation.customer_hypotheses import (
    load_customer_hypotheses,
    normalize_customer_hypotheses,
    validate_customer_hypotheses_payload,
)


def test_validate_payload_accepts_empty_hypotheses():
    payload = {"version": 1, "hypotheses": []}
    assert validate_customer_hypotheses_payload(payload) == []


def test_load_default_hypotheses_file_contains_track_d_hypotheses():
    hypotheses = load_customer_hypotheses()
    assert hypotheses
    metrics = {str(hypothesis.get("metric", "")) for hypothesis in hypotheses}
    assert "founder_engaged_to_matched_rate" in metrics
    assert "vc_engaged_to_matched_rate" in metrics


def test_validate_payload_rejects_invalid_direction():
    payload = {
        "version": 1,
        "hypotheses": [
            {
                "id": "H_INVALID_001",
                "scenario": "baseline",
                "metric": "mutual_interest_rate",
                "direction": "upward",
                "min_delta": 0.03,
            }
        ],
    }
    errors = validate_customer_hypotheses_payload(payload)
    assert any(".direction must be one of" in error for error in errors)


def test_load_hypotheses_raises_for_invalid_file(tmp_path: Path):
    invalid_payload = {
        "version": 1,
        "hypotheses": [
            {
                "id": "H_GUARD_001",
                "scenario": "baseline",
                "metric": "tool_use_to_signup",
                "direction": "increase",
                "min_delta": 0.01,
                "guardrails": [{"metric": "signup_to_first_match"}],
            }
        ],
    }
    invalid_path = tmp_path / "customer_hypotheses_invalid.json"
    invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid customer hypothesis data"):
        load_customer_hypotheses(hypotheses_path=str(invalid_path))


def test_normalize_hypotheses_is_sorted_by_id():
    input_hypotheses = [
        {
            "id": "H_B",
            "scenario": "baseline",
            "metric": "m1",
            "direction": "increase",
            "min_delta": 0.01,
        },
        {
            "id": "H_A",
            "scenario": "baseline",
            "metric": "m2",
            "direction": "decrease",
            "min_delta": 0.02,
        },
    ]
    normalized = normalize_customer_hypotheses(input_hypotheses)
    assert normalized[0]["id"] == "H_A"
    assert normalized[1]["id"] == "H_B"
