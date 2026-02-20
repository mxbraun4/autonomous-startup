"""Structured transition logic metadata for founder/VC customer journeys."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

TRANSITION_LOGIC_VERSION = 1

_MARKETPLACE_TRANSITION_LOGIC: Dict[str, Any] = {
    "version": TRANSITION_LOGIC_VERSION,
    "actors": {
        "founder": {
            "states": ["visit", "signup", "engaged", "matched", "interested", "meeting"],
            "transitions": [
                {
                    "id": "visit_to_signup",
                    "from_state": "visit",
                    "to_state": "signup",
                    "mode": "probabilistic",
                    "interaction": "complete_signup_form",
                    "success_reason_code": "founder_signed_up",
                    "failure_reason_code": "founder_no_signup",
                    "precheck_failure_reason_code": "founder_signup_incomplete_profile",
                    "signals": [],
                    "profile_fields": [
                        "urgency_score",
                        "trust_score",
                        "form_complexity_score",
                        "channel_intent_fit",
                        "proof_of_outcomes",
                    ],
                    "required_signup_fields": [
                        "sector",
                        "stage",
                        "geography",
                        "fundraising_status",
                    ],
                    "params": [
                        "founder_signup_base_rate",
                        "founder_signup_cta_clarity",
                        "founder_signup_friction",
                        "founder_signup_trust_score",
                        "founder_signup_form_complexity",
                        "founder_signup_channel_intent_fit",
                        "founder_signup_proof_of_outcomes",
                    ],
                    "formulas": {
                        "signup_complete": "all(required_signup_fields are non-empty)",
                        "probability": (
                            "clamp(founder_signup_base_rate "
                            "* (0.60 + 0.40 * founder_signup_cta_clarity) "
                            "* (1.00 - 0.35 * founder_signup_friction) "
                            "* (1.00 - 0.35 * form_complexity_score) "
                            "* (0.60 + 0.40 * trust_score) "
                            "* (0.60 + 0.40 * channel_intent_fit) "
                            "* (0.60 + 0.40 * proof_of_outcomes) "
                            "* (0.60 + 0.40 * urgency_score))"
                        ),
                        "decision": "signup_complete and (rng.random() < probability)",
                    },
                },
                {
                    "id": "signup_to_engaged",
                    "from_state": "signup",
                    "to_state": "engaged",
                    "mode": "probabilistic",
                    "interaction": "complete_onboarding",
                    "success_reason_code": "founder_engaged",
                    "failure_reason_code": "founder_not_engaged",
                    "signals": ["match_score"],
                    "profile_fields": ["urgency_score"],
                    "params": [],
                    "formulas": {
                        "probability": "clamp(0.20 + 0.45 * match_score + 0.25 * urgency_score)",
                        "decision": "rng.random() < probability",
                    },
                },
                {
                    "id": "engaged_to_matched",
                    "from_state": "engaged",
                    "to_state": "matched",
                    "mode": "threshold",
                    "interaction": "request_match_recommendations",
                    "success_reason_code": "founder_match_threshold_passed",
                    "failure_reason_code": "founder_match_below_threshold",
                    "signals": ["match_score"],
                    "profile_fields": [],
                    "params": ["match_score_threshold"],
                    "formulas": {
                        "decision": "match_score >= match_score_threshold",
                    },
                },
                {
                    "id": "matched_to_interested",
                    "from_state": "matched",
                    "to_state": "interested",
                    "mode": "threshold_and_probabilistic",
                    "interaction": "evaluate_match_explanation",
                    "llm_capable": True,
                    "success_reason_code": "founder_interest_passed",
                    "failure_reason_code": "founder_not_interested",
                    "signals": [
                        "personalization_score",
                        "explanation_quality",
                        "timing_score",
                    ],
                    "profile_fields": ["urgency_score"],
                    "params": ["founder_base_interest", "interest_threshold"],
                    "formulas": {
                        "probability": (
                            "clamp(founder_base_interest "
                            "+ 0.35 * personalization_score "
                            "+ 0.20 * explanation_quality "
                            "+ 0.15 * timing_score "
                            "+ 0.15 * urgency_score)"
                        ),
                        "gate": "probability >= interest_threshold",
                        "decision": "gate and (rng.random() < probability)",
                    },
                },
                {
                    "id": "interested_to_meeting",
                    "from_state": "interested",
                    "to_state": "meeting",
                    "mode": "cross_actor_probabilistic",
                    "interaction": "confirm_intro_meeting",
                    "success_reason_code": "mutual_interest_meeting",
                    "failure_reason_code": "mutual_interest_no_meeting",
                    "signals": [],
                    "profile_fields": [],
                    "params": ["meeting_rate_from_mutual_interest"],
                    "cross_actor_requirements": [
                        "founder.interested == True",
                        "vc.interested == True",
                    ],
                    "formulas": {
                        "decision": "rng.random() < meeting_rate_from_mutual_interest",
                    },
                },
            ],
        },
        "vc": {
            "states": ["visit", "signup", "engaged", "matched", "interested", "meeting"],
            "transitions": [
                {
                    "id": "visit_to_signup",
                    "from_state": "visit",
                    "to_state": "signup",
                    "mode": "probabilistic",
                    "interaction": "complete_signup_form",
                    "success_reason_code": "vc_signed_up",
                    "failure_reason_code": "vc_no_signup",
                    "precheck_failure_reason_code": "vc_signup_incomplete_profile",
                    "derived_inputs": ["preview_match_quality", "confidence_factor"],
                    "signals": ["match_score", "explanation_quality"],
                    "profile_fields": ["confidence_threshold"],
                    "required_signup_fields": [
                        "thesis_sectors",
                        "stage_focus",
                        "geography",
                    ],
                    "params": [
                        "vc_signup_base_rate",
                        "vc_signup_cta_clarity",
                        "vc_signup_friction",
                    ],
                    "formulas": {
                        "signup_complete": "all(required_signup_fields are non-empty)",
                        "preview_match_quality": (
                            "clamp(0.70 * match_score + 0.30 * explanation_quality)"
                        ),
                        "confidence_factor": "clamp(1.00 - confidence_threshold)",
                        "probability": (
                            "clamp(vc_signup_base_rate "
                            "* (0.60 + 0.40 * vc_signup_cta_clarity) "
                            "* (0.50 + 0.50 * preview_match_quality) "
                            "* (1.00 - 0.35 * vc_signup_friction) "
                            "* (0.55 + 0.45 * confidence_factor))"
                        ),
                        "decision": "signup_complete and (rng.random() < probability)",
                    },
                },
                {
                    "id": "signup_to_engaged",
                    "from_state": "signup",
                    "to_state": "engaged",
                    "mode": "probabilistic",
                    "interaction": "complete_onboarding",
                    "success_reason_code": "vc_engaged",
                    "failure_reason_code": "vc_not_engaged",
                    "signals": ["match_score", "explanation_quality"],
                    "profile_fields": [],
                    "params": [],
                    "formulas": {
                        "probability": "clamp(0.15 + 0.55 * match_score + 0.20 * explanation_quality)",
                        "decision": "rng.random() < probability",
                    },
                },
                {
                    "id": "engaged_to_matched",
                    "from_state": "engaged",
                    "to_state": "matched",
                    "mode": "threshold",
                    "interaction": "request_match_recommendations",
                    "success_reason_code": "vc_match_threshold_passed",
                    "failure_reason_code": "vc_match_below_threshold",
                    "signals": ["match_score"],
                    "profile_fields": [],
                    "params": ["vc_match_score_threshold", "shortlist_threshold"],
                    "formulas": {
                        "decision": (
                            "match_score >= vc_match_score_threshold "
                            "(fallback: shortlist_threshold)"
                        ),
                    },
                },
                {
                    "id": "matched_to_interested",
                    "from_state": "matched",
                    "to_state": "interested",
                    "mode": "threshold_and_probabilistic",
                    "interaction": "evaluate_match_explanation",
                    "llm_capable": True,
                    "success_reason_code": "vc_interest_passed",
                    "failure_reason_code": "vc_not_interested",
                    "signals": [
                        "match_score",
                        "personalization_score",
                        "explanation_quality",
                        "timing_score",
                    ],
                    "profile_fields": ["confidence_threshold"],
                    "params": ["vc_base_interest", "interest_threshold"],
                    "derived_inputs": ["gate_threshold"],
                    "formulas": {
                        "probability": (
                            "clamp(vc_base_interest "
                            "+ 0.25 * match_score "
                            "+ 0.30 * personalization_score "
                            "+ 0.20 * explanation_quality "
                            "+ 0.15 * timing_score)"
                        ),
                        "gate_threshold": "max(confidence_threshold, interest_threshold)",
                        "gate": "probability >= gate_threshold",
                        "decision": "gate and (rng.random() < probability)",
                    },
                },
                {
                    "id": "interested_to_meeting",
                    "from_state": "interested",
                    "to_state": "meeting",
                    "mode": "cross_actor_probabilistic",
                    "interaction": "confirm_intro_meeting",
                    "success_reason_code": "mutual_interest_meeting",
                    "failure_reason_code": "mutual_interest_no_meeting",
                    "signals": [],
                    "profile_fields": [],
                    "params": ["meeting_rate_from_mutual_interest"],
                    "cross_actor_requirements": [
                        "founder.interested == True",
                        "vc.interested == True",
                    ],
                    "formulas": {
                        "decision": "rng.random() < meeting_rate_from_mutual_interest",
                    },
                },
            ],
        },
    },
}


def get_marketplace_transition_logic() -> Dict[str, Any]:
    """Return founder/VC transition model metadata as a deep copy."""
    return deepcopy(_MARKETPLACE_TRANSITION_LOGIC)


def list_marketplace_actors() -> List[str]:
    """Return actor names represented by the transition model."""
    return sorted(_MARKETPLACE_TRANSITION_LOGIC["actors"].keys())


def list_actor_phases(actor_type: str) -> List[str]:
    """Return ordered states for an actor journey."""
    actors = _MARKETPLACE_TRANSITION_LOGIC["actors"]
    actor = actors.get(actor_type)
    if actor is None:
        available = ", ".join(sorted(actors.keys()))
        raise ValueError(f"Unknown actor '{actor_type}'. Available actors: {available}")
    return list(actor["states"])


def list_actor_transition_parameters(actor_type: str) -> Dict[str, List[str]]:
    """Return transition-wise parameter and signal dependencies for an actor."""
    actors = _MARKETPLACE_TRANSITION_LOGIC["actors"]
    actor = actors.get(actor_type)
    if actor is None:
        available = ", ".join(sorted(actors.keys()))
        raise ValueError(f"Unknown actor '{actor_type}'. Available actors: {available}")

    transition_params: Dict[str, List[str]] = {}
    for transition in actor["transitions"]:
        field_values: List[str] = []
        interaction_label = transition.get("interaction")
        if isinstance(interaction_label, str) and interaction_label:
            field_values.append(interaction_label)

        for field in (
            "params",
            "signals",
            "profile_fields",
            "required_signup_fields",
            "derived_inputs",
            "cross_actor_requirements",
        ):
            values = transition.get(field, [])
            if isinstance(values, list):
                field_values.extend(str(value) for value in values)

        transition_params[str(transition["id"])] = sorted(dict.fromkeys(field_values))

    return transition_params
