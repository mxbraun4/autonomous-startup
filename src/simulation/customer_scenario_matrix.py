"""Deterministic scenario matrix for constrained customer simulation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from src.simulation.customer_environment import build_customer_environment_input

SCENARIO_MATRIX_VERSION = 1

_SCENARIO_ORDER = [
    "baseline",
    "high_personalization",
    "better_matching",
    "acquisition_push",
]

_BASELINE_PARAMS: Dict[str, Any] = {
    "founder_base_interest": 0.15,
    "vc_base_interest": 0.12,
    "visitor_tool_click_rate": 0.20,
    "signup_rate_from_tool": 0.10,
    "meeting_rate_from_mutual_interest": 0.35,
    "match_score_threshold": 0.50,
    "shortlist_threshold": 0.55,
    "interest_threshold": 0.40,
    "max_steps_per_customer": 5,
}

_BASELINE_SIGNALS: Dict[str, List[Dict[str, Any]]] = {
    "match_signals": [
        {
            "founder_id": "founder_001",
            "vc_id": "vc_001",
            "match_score": 0.86,
            "explanation_quality": 0.76,
        },
        {
            "founder_id": "founder_002",
            "vc_id": "vc_002",
            "match_score": 0.81,
            "explanation_quality": 0.73,
        },
        {
            "founder_id": "founder_003",
            "vc_id": "vc_003",
            "match_score": 0.74,
            "explanation_quality": 0.66,
        },
        {
            "founder_id": "founder_004",
            "vc_id": "vc_004",
            "match_score": 0.79,
            "explanation_quality": 0.70,
        },
        {
            "founder_id": "founder_005",
            "vc_id": "vc_003",
            "match_score": 0.68,
            "explanation_quality": 0.62,
        },
        {
            "founder_id": "founder_006",
            "vc_id": "vc_002",
            "match_score": 0.83,
            "explanation_quality": 0.75,
        },
        {
            "founder_id": "founder_007",
            "vc_id": "vc_005",
            "match_score": 0.60,
            "explanation_quality": 0.58,
        },
        {
            "founder_id": "founder_008",
            "vc_id": "vc_003",
            "match_score": 0.77,
            "explanation_quality": 0.69,
        },
    ],
    "outreach_signals": [
        {
            "founder_id": "founder_001",
            "vc_id": "vc_001",
            "personalization_score": 0.82,
            "timing_score": 0.74,
        },
        {
            "founder_id": "founder_002",
            "vc_id": "vc_002",
            "personalization_score": 0.78,
            "timing_score": 0.70,
        },
        {
            "founder_id": "founder_003",
            "vc_id": "vc_003",
            "personalization_score": 0.67,
            "timing_score": 0.63,
        },
        {
            "founder_id": "founder_004",
            "vc_id": "vc_004",
            "personalization_score": 0.75,
            "timing_score": 0.68,
        },
        {
            "founder_id": "founder_005",
            "vc_id": "vc_003",
            "personalization_score": 0.64,
            "timing_score": 0.59,
        },
        {
            "founder_id": "founder_006",
            "vc_id": "vc_002",
            "personalization_score": 0.80,
            "timing_score": 0.72,
        },
        {
            "founder_id": "founder_007",
            "vc_id": "vc_005",
            "personalization_score": 0.58,
            "timing_score": 0.55,
        },
        {
            "founder_id": "founder_008",
            "vc_id": "vc_003",
            "personalization_score": 0.73,
            "timing_score": 0.67,
        },
    ],
    "acquisition_signals": [
        {
            "visitor_id": "visitor_001",
            "article_relevance": 0.84,
            "tool_usefulness": 0.86,
            "cta_clarity": 0.74,
        },
        {
            "visitor_id": "visitor_002",
            "article_relevance": 0.76,
            "tool_usefulness": 0.79,
            "cta_clarity": 0.70,
        },
        {
            "visitor_id": "visitor_003",
            "article_relevance": 0.71,
            "tool_usefulness": 0.74,
            "cta_clarity": 0.67,
        },
        {
            "visitor_id": "visitor_004",
            "article_relevance": 0.83,
            "tool_usefulness": 0.88,
            "cta_clarity": 0.76,
        },
        {
            "visitor_id": "visitor_005",
            "article_relevance": 0.66,
            "tool_usefulness": 0.69,
            "cta_clarity": 0.62,
        },
        {
            "visitor_id": "visitor_006",
            "article_relevance": 0.75,
            "tool_usefulness": 0.80,
            "cta_clarity": 0.71,
        },
        {
            "visitor_id": "visitor_007",
            "article_relevance": 0.79,
            "tool_usefulness": 0.84,
            "cta_clarity": 0.73,
        },
        {
            "visitor_id": "visitor_008",
            "article_relevance": 0.67,
            "tool_usefulness": 0.71,
            "cta_clarity": 0.64,
        },
        {
            "visitor_id": "visitor_009",
            "article_relevance": 0.74,
            "tool_usefulness": 0.78,
            "cta_clarity": 0.69,
        },
        {
            "visitor_id": "visitor_010",
            "article_relevance": 0.62,
            "tool_usefulness": 0.66,
            "cta_clarity": 0.58,
        },
    ],
}


def _clamp_probability(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _clone_signals(
    signals: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    return {bucket: [dict(item) for item in entries] for bucket, entries in signals.items()}


def _boost_signal_fields(
    signals: List[Dict[str, Any]],
    fields: List[str],
    delta: float,
) -> List[Dict[str, Any]]:
    boosted: List[Dict[str, Any]] = []
    for signal in signals:
        updated = dict(signal)
        for field in fields:
            updated[field] = _clamp_probability(float(updated.get(field, 0.0)) + delta)
        boosted.append(updated)
    return boosted


def _build_scenario_matrix() -> Dict[str, Dict[str, Any]]:
    baseline_signals = _clone_signals(_BASELINE_SIGNALS)

    high_personalization_signals = _clone_signals(_BASELINE_SIGNALS)
    high_personalization_signals["outreach_signals"] = _boost_signal_fields(
        high_personalization_signals["outreach_signals"],
        ["personalization_score", "timing_score"],
        delta=0.12,
    )

    better_matching_signals = _clone_signals(_BASELINE_SIGNALS)
    better_matching_signals["match_signals"] = _boost_signal_fields(
        better_matching_signals["match_signals"],
        ["match_score", "explanation_quality"],
        delta=0.10,
    )

    acquisition_push_signals = _clone_signals(_BASELINE_SIGNALS)
    acquisition_push_signals["acquisition_signals"] = _boost_signal_fields(
        acquisition_push_signals["acquisition_signals"],
        ["article_relevance", "tool_usefulness", "cta_clarity"],
        delta=0.11,
    )

    return {
        "baseline": {
            "description": "Reference scenario for Track D comparisons.",
            "seed": 42,
            "hypothesis": {
                "id": "H_BASELINE_001",
                "summary": "Baseline used as control for downstream deltas.",
            },
            "params": dict(_BASELINE_PARAMS),
            "signals": baseline_signals,
        },
        "high_personalization": {
            "description": "Improved outreach quality while keeping other signals fixed.",
            "seed": 42,
            "hypothesis": {
                "id": "H_OUTREACH_001",
                "summary": (
                    "Higher personalization and timing should increase "
                    "founder_interested_rate."
                ),
                "metric": "founder_interested_rate",
                "direction": "increase",
            },
            "params": dict(_BASELINE_PARAMS),
            "signals": high_personalization_signals,
        },
        "better_matching": {
            "description": "Improved match and explanation quality with same funnel params.",
            "seed": 42,
            "hypothesis": {
                "id": "H_MATCH_001",
                "summary": (
                    "Higher match and explanation quality should increase "
                    "mutual_interest_rate."
                ),
                "metric": "mutual_interest_rate",
                "direction": "increase",
            },
            "params": {
                **_BASELINE_PARAMS,
                "match_score_threshold": 0.55,
                "shortlist_threshold": 0.60,
            },
            "signals": better_matching_signals,
        },
        "acquisition_push": {
            "description": "Improved acquisition quality and funnel propensities.",
            "seed": 42,
            "hypothesis": {
                "id": "H_ACQ_001",
                "summary": (
                    "Stronger acquisition signals should increase tool_use_to_signup "
                    "and signup_to_first_match."
                ),
                "metric": "tool_use_to_signup",
                "direction": "increase",
            },
            "params": {
                **_BASELINE_PARAMS,
                "visitor_tool_click_rate": 0.28,
                "signup_rate_from_tool": 0.16,
            },
            "signals": acquisition_push_signals,
        },
    }


_SCENARIO_MATRIX = _build_scenario_matrix()


def list_customer_scenarios() -> List[str]:
    """Return deterministic scenario names in canonical order."""
    return list(_SCENARIO_ORDER)


def get_customer_scenario_matrix() -> Dict[str, Dict[str, Any]]:
    """Return a copy of the full deterministic scenario matrix."""
    return deepcopy(_SCENARIO_MATRIX)


def get_customer_scenario(scenario_name: str) -> Dict[str, Any]:
    """Return one scenario definition by name."""
    scenario = _SCENARIO_MATRIX.get(scenario_name)
    if scenario is None:
        available = ", ".join(_SCENARIO_ORDER)
        raise ValueError(
            f"Unknown customer scenario '{scenario_name}'. Available: {available}"
        )
    return deepcopy(scenario)


def build_customer_environment_input_for_scenario(
    run_id: str,
    iteration: int,
    scenario_name: str,
    seed: Optional[int] = None,
    seed_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a contract-compliant environment input from a scenario row."""
    scenario = get_customer_scenario(scenario_name)
    resolved_seed = int(scenario["seed"] if seed is None else seed)

    return build_customer_environment_input(
        run_id=run_id,
        iteration=iteration,
        seed=resolved_seed,
        params=scenario["params"],
        seed_path=seed_path,
        signals=scenario["signals"],
    )
