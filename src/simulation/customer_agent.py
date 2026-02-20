"""Deterministic customer state machine agents for environment simulation."""
from __future__ import annotations

from random import Random
from typing import Any, Dict, List, Optional, Tuple

from src.utils.logging import get_logger

logger = get_logger(__name__)

FOUNDER_SIGNUP_REQUIRED_FIELDS: Tuple[str, ...] = (
    "sector",
    "stage",
    "geography",
    "fundraising_status",
)

VC_SIGNUP_REQUIRED_FIELDS: Tuple[str, ...] = (
    "thesis_sectors",
    "stage_focus",
    "geography",
)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp numeric values into a fixed interval."""
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _resolve_signup_payload(
    profile: Dict[str, Any],
    fallback_fields: Tuple[str, ...],
) -> Dict[str, Any]:
    fallback_payload = {
        field_name: profile.get(field_name)
        for field_name in fallback_fields
    }
    payload = profile.get("signup_payload")
    if isinstance(payload, dict):
        return dict(payload)
    return fallback_payload


def _is_signup_field_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _missing_required_signup_fields(
    payload: Dict[str, Any],
    required_fields: Tuple[str, ...],
) -> List[str]:
    missing: List[str] = []
    for field_name in required_fields:
        if not _is_signup_field_filled(payload.get(field_name)):
            missing.append(field_name)
    return missing


class FounderCustomerAgent:
    """State machine for founder-side customer behavior."""

    def __init__(self, profile: Dict[str, Any], params: Dict[str, Any], rng: Random):
        self.profile = profile
        self.params = params
        self.rng = rng
        self.state = "visit"

    def simulate(
        self,
        match_signal: Optional[Dict[str, Any]],
        outreach_signal: Optional[Dict[str, Any]],
        max_steps: int,
    ) -> Dict[str, Any]:
        """Simulate founder journey until terminal or bounded step limit."""
        transitions: List[Dict[str, Any]] = []
        interactions: List[Dict[str, Any]] = []
        dropoff_reason: Optional[str] = None

        if max_steps <= 0:
            self._record_interaction(
                interactions,
                step_id="guard_max_steps",
                interaction="system_guardrail",
                decision_mode="guardrail",
                outcome="failed",
                reason_code="max_steps_reached",
                score_snapshot={"max_steps": max_steps},
            )
            return self._result(
                transitions,
                interactions,
                "max_steps_reached",
                match_signal,
            )

        signup_payload = _resolve_signup_payload(
            self.profile,
            FOUNDER_SIGNUP_REQUIRED_FIELDS,
        )
        missing_signup_fields = _missing_required_signup_fields(
            signup_payload,
            FOUNDER_SIGNUP_REQUIRED_FIELDS,
        )
        if missing_signup_fields:
            dropoff_reason = "founder_signup_incomplete_profile"
            self._record_interaction(
                interactions,
                step_id="visit_to_signup",
                interaction="complete_signup_form",
                decision_mode="deterministic_validation",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "signup_complete": False,
                    "missing_required_fields": missing_signup_fields,
                    "required_field_count": len(FOUNDER_SIGNUP_REQUIRED_FIELDS),
                    "provided_required_field_count": (
                        len(FOUNDER_SIGNUP_REQUIRED_FIELDS) - len(missing_signup_fields)
                    ),
                },
            )
            return self._result(transitions, interactions, dropoff_reason, match_signal)

        match_score = _clamp(float((match_signal or {}).get("match_score", 0.0)))
        explanation_quality = _clamp(
            float((match_signal or {}).get("explanation_quality", 0.0))
        )
        personalization = _clamp(
            float((outreach_signal or {}).get("personalization_score", 0.0))
        )
        timing_score = _clamp(float((outreach_signal or {}).get("timing_score", 0.0)))
        urgency_score = _clamp(float(self.profile.get("urgency_score", 0.0)))
        trust_score = _clamp(
            float(
                self.profile.get(
                    "trust_score",
                    self.params.get("founder_signup_trust_score", 1.0),
                )
            )
        )
        form_complexity_score = _clamp(
            float(
                self.profile.get(
                    "form_complexity_score",
                    self.params.get("founder_signup_form_complexity", 0.0),
                )
            )
        )
        channel_intent_fit = _clamp(
            float(
                self.profile.get(
                    "channel_intent_fit",
                    self.params.get("founder_signup_channel_intent_fit", 1.0),
                )
            )
        )
        proof_of_outcomes = _clamp(
            float(
                self.profile.get(
                    "proof_of_outcomes",
                    self.params.get("founder_signup_proof_of_outcomes", 1.0),
                )
            )
        )
        signup_cta_clarity = _clamp(
            float(self.params.get("founder_signup_cta_clarity", 0.72))
        )
        signup_friction = _clamp(float(self.params.get("founder_signup_friction", 0.30)))
        signup_prob = _clamp(
            float(self.params.get("founder_signup_base_rate", 0.70))
            * (0.60 + (0.40 * signup_cta_clarity))
            * (1.0 - (0.35 * signup_friction))
            * (1.0 - (0.35 * form_complexity_score))
            * (0.60 + (0.40 * trust_score))
            * (0.60 + (0.40 * channel_intent_fit))
            * (0.60 + (0.40 * proof_of_outcomes))
            * (0.60 + (0.40 * urgency_score))
        )
        if self._coin_flip(signup_prob):
            self._record_transition(
                transitions,
                "signup",
                "founder_signed_up",
                {
                    "signup_prob": signup_prob,
                    "signup_cta_clarity": signup_cta_clarity,
                    "signup_friction": signup_friction,
                    "trust_score": trust_score,
                    "form_complexity_score": form_complexity_score,
                    "channel_intent_fit": channel_intent_fit,
                    "proof_of_outcomes": proof_of_outcomes,
                    "urgency_score": urgency_score,
                    "signup_complete": True,
                },
                max_steps,
            )
            self._record_interaction(
                interactions,
                step_id="visit_to_signup",
                interaction="complete_signup_form",
                decision_mode="probabilistic",
                outcome="passed",
                reason_code="founder_signed_up",
                score_snapshot={
                    "signup_prob": signup_prob,
                    "signup_cta_clarity": signup_cta_clarity,
                    "signup_friction": signup_friction,
                    "trust_score": trust_score,
                    "form_complexity_score": form_complexity_score,
                    "channel_intent_fit": channel_intent_fit,
                    "proof_of_outcomes": proof_of_outcomes,
                    "urgency_score": urgency_score,
                    "signup_complete": True,
                },
            )
        else:
            dropoff_reason = "founder_no_signup"
            self._record_interaction(
                interactions,
                step_id="visit_to_signup",
                interaction="complete_signup_form",
                decision_mode="probabilistic",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "signup_prob": signup_prob,
                    "signup_cta_clarity": signup_cta_clarity,
                    "signup_friction": signup_friction,
                    "trust_score": trust_score,
                    "form_complexity_score": form_complexity_score,
                    "channel_intent_fit": channel_intent_fit,
                    "proof_of_outcomes": proof_of_outcomes,
                    "urgency_score": urgency_score,
                    "signup_complete": True,
                },
            )
            return self._result(transitions, interactions, dropoff_reason, match_signal)

        engaged_prob = _clamp(0.20 + (0.45 * match_score) + (0.25 * urgency_score))
        if self._coin_flip(engaged_prob):
            self._record_transition(
                transitions,
                "engaged",
                "founder_engaged",
                {
                    "engaged_prob": engaged_prob,
                    "match_score": match_score,
                    "urgency_score": urgency_score,
                },
                max_steps,
            )
            self._record_interaction(
                interactions,
                step_id="signup_to_engaged",
                interaction="complete_onboarding",
                decision_mode="probabilistic",
                outcome="passed",
                reason_code="founder_engaged",
                score_snapshot={
                    "engaged_prob": engaged_prob,
                    "match_score": match_score,
                    "urgency_score": urgency_score,
                },
            )
        else:
            dropoff_reason = "founder_not_engaged"
            self._record_interaction(
                interactions,
                step_id="signup_to_engaged",
                interaction="complete_onboarding",
                decision_mode="probabilistic",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "engaged_prob": engaged_prob,
                    "match_score": match_score,
                    "urgency_score": urgency_score,
                },
            )
            return self._result(transitions, interactions, dropoff_reason, match_signal)

        match_threshold = _clamp(float(self.params["match_score_threshold"]))
        if match_score >= match_threshold:
            self._record_transition(
                transitions,
                "matched",
                "founder_match_threshold_passed",
                {
                    "match_score": match_score,
                    "match_score_threshold": match_threshold,
                },
                max_steps,
            )
            self._record_interaction(
                interactions,
                step_id="engaged_to_matched",
                interaction="request_match_recommendations",
                decision_mode="threshold",
                outcome="passed",
                reason_code="founder_match_threshold_passed",
                score_snapshot={
                    "match_score": match_score,
                    "match_score_threshold": match_threshold,
                },
            )
        else:
            dropoff_reason = "founder_match_below_threshold"
            self._record_interaction(
                interactions,
                step_id="engaged_to_matched",
                interaction="request_match_recommendations",
                decision_mode="threshold",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "match_score": match_score,
                    "match_score_threshold": match_threshold,
                },
            )
            return self._result(transitions, interactions, dropoff_reason, match_signal)

        interest_prob = _clamp(
            float(self.params["founder_base_interest"])
            + (0.35 * personalization)
            + (0.20 * explanation_quality)
            + (0.15 * timing_score)
            + (0.15 * urgency_score)
        )
        interest_threshold = _clamp(float(self.params["interest_threshold"]))
        if interest_prob >= interest_threshold and self._coin_flip(interest_prob):
            self._record_transition(
                transitions,
                "interested",
                "founder_interest_passed",
                {
                    "interest_prob": interest_prob,
                    "interest_threshold": interest_threshold,
                    "personalization_score": personalization,
                },
                max_steps,
            )
            self._record_interaction(
                interactions,
                step_id="matched_to_interested",
                interaction="evaluate_match_explanation",
                decision_mode="threshold_and_probabilistic",
                outcome="passed",
                reason_code="founder_interest_passed",
                score_snapshot={
                    "interest_prob": interest_prob,
                    "interest_threshold": interest_threshold,
                    "personalization_score": personalization,
                    "explanation_quality": explanation_quality,
                    "timing_score": timing_score,
                },
            )
        else:
            dropoff_reason = "founder_not_interested"
            self._record_interaction(
                interactions,
                step_id="matched_to_interested",
                interaction="evaluate_match_explanation",
                decision_mode="threshold_and_probabilistic",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "interest_prob": interest_prob,
                    "interest_threshold": interest_threshold,
                    "personalization_score": personalization,
                    "explanation_quality": explanation_quality,
                    "timing_score": timing_score,
                },
            )

        return self._result(transitions, interactions, dropoff_reason, match_signal)

    def _coin_flip(self, probability: float) -> bool:
        return self.rng.random() < _clamp(probability)

    def _record_transition(
        self,
        transitions: List[Dict[str, Any]],
        to_state: str,
        reason_code: str,
        score_snapshot: Dict[str, Any],
        max_steps: int,
    ) -> None:
        if len(transitions) >= max_steps:
            return
        from_state = self.state
        self.state = to_state
        transitions.append(
            {
                "from_state": from_state,
                "to_state": to_state,
                "reason_code": reason_code,
                "score_snapshot": score_snapshot,
            }
        )

    def _result(
        self,
        transitions: List[Dict[str, Any]],
        interaction_trace: List[Dict[str, Any]],
        dropoff_reason: Optional[str],
        match_signal: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "state": self.state,
            "transitions": transitions,
            "interaction_trace": interaction_trace,
            "dropoff_reason": dropoff_reason,
            "signed_up": self.state
            in {"signup", "engaged", "matched", "interested", "meeting"},
            "interested": self.state in {"interested", "meeting"},
            "preferred_vc_id": (match_signal or {}).get("vc_id"),
        }

    def _record_interaction(
        self,
        interactions: List[Dict[str, Any]],
        step_id: str,
        interaction: str,
        decision_mode: str,
        outcome: str,
        reason_code: str,
        score_snapshot: Dict[str, Any],
    ) -> None:
        interactions.append(
            {
                "step_id": step_id,
                "interaction": interaction,
                "decision_mode": decision_mode,
                "outcome": outcome,
                "reason_code": reason_code,
                "score_snapshot": score_snapshot,
            }
        )


class VCCustomerAgent:
    """State machine for VC-side customer behavior."""

    def __init__(self, profile: Dict[str, Any], params: Dict[str, Any], rng: Random):
        self.profile = profile
        self.params = params
        self.rng = rng
        self.state = "visit"

    def simulate(
        self,
        match_signal: Optional[Dict[str, Any]],
        outreach_signal: Optional[Dict[str, Any]],
        max_steps: int,
    ) -> Dict[str, Any]:
        """Simulate VC journey until terminal or bounded step limit."""
        transitions: List[Dict[str, Any]] = []
        interactions: List[Dict[str, Any]] = []
        dropoff_reason: Optional[str] = None

        if max_steps <= 0:
            self._record_interaction(
                interactions,
                step_id="guard_max_steps",
                interaction="system_guardrail",
                decision_mode="guardrail",
                outcome="failed",
                reason_code="max_steps_reached",
                score_snapshot={"max_steps": max_steps},
            )
            return self._result(
                transitions,
                interactions,
                "max_steps_reached",
                match_signal,
            )

        signup_payload = _resolve_signup_payload(
            self.profile,
            VC_SIGNUP_REQUIRED_FIELDS,
        )
        missing_signup_fields = _missing_required_signup_fields(
            signup_payload,
            VC_SIGNUP_REQUIRED_FIELDS,
        )
        if missing_signup_fields:
            dropoff_reason = "vc_signup_incomplete_profile"
            self._record_interaction(
                interactions,
                step_id="visit_to_signup",
                interaction="complete_signup_form",
                decision_mode="deterministic_validation",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "signup_complete": False,
                    "missing_required_fields": missing_signup_fields,
                    "required_field_count": len(VC_SIGNUP_REQUIRED_FIELDS),
                    "provided_required_field_count": (
                        len(VC_SIGNUP_REQUIRED_FIELDS) - len(missing_signup_fields)
                    ),
                },
            )
            return self._result(transitions, interactions, dropoff_reason, match_signal)

        match_score = _clamp(float((match_signal or {}).get("match_score", 0.0)))
        explanation_quality = _clamp(
            float((match_signal or {}).get("explanation_quality", 0.0))
        )
        personalization = _clamp(
            float((outreach_signal or {}).get("personalization_score", 0.0))
        )
        timing_score = _clamp(float((outreach_signal or {}).get("timing_score", 0.0)))
        confidence_threshold = _clamp(float(self.profile.get("confidence_threshold", 0.5)))
        preview_match_quality = _clamp((0.70 * match_score) + (0.30 * explanation_quality))
        signup_cta_clarity = _clamp(float(self.params.get("vc_signup_cta_clarity", 0.68)))
        signup_friction = _clamp(float(self.params.get("vc_signup_friction", 0.33)))
        confidence_factor = _clamp(1.0 - confidence_threshold)
        signup_prob = _clamp(
            float(self.params.get("vc_signup_base_rate", 0.66))
            * (0.60 + (0.40 * signup_cta_clarity))
            * (0.50 + (0.50 * preview_match_quality))
            * (1.0 - (0.35 * signup_friction))
            * (0.55 + (0.45 * confidence_factor))
        )
        if self._coin_flip(signup_prob):
            self._record_transition(
                transitions,
                "signup",
                "vc_signed_up",
                {
                    "signup_prob": signup_prob,
                    "signup_cta_clarity": signup_cta_clarity,
                    "signup_friction": signup_friction,
                    "preview_match_quality": preview_match_quality,
                    "confidence_threshold": confidence_threshold,
                    "signup_complete": True,
                },
                max_steps,
            )
            self._record_interaction(
                interactions,
                step_id="visit_to_signup",
                interaction="complete_signup_form",
                decision_mode="probabilistic",
                outcome="passed",
                reason_code="vc_signed_up",
                score_snapshot={
                    "signup_prob": signup_prob,
                    "signup_cta_clarity": signup_cta_clarity,
                    "signup_friction": signup_friction,
                    "preview_match_quality": preview_match_quality,
                    "confidence_threshold": confidence_threshold,
                    "signup_complete": True,
                },
            )
        else:
            dropoff_reason = "vc_no_signup"
            self._record_interaction(
                interactions,
                step_id="visit_to_signup",
                interaction="complete_signup_form",
                decision_mode="probabilistic",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "signup_prob": signup_prob,
                    "signup_cta_clarity": signup_cta_clarity,
                    "signup_friction": signup_friction,
                    "preview_match_quality": preview_match_quality,
                    "confidence_threshold": confidence_threshold,
                    "signup_complete": True,
                },
            )
            return self._result(transitions, interactions, dropoff_reason, match_signal)

        engaged_prob = _clamp(0.15 + (0.55 * match_score) + (0.20 * explanation_quality))
        if self._coin_flip(engaged_prob):
            self._record_transition(
                transitions,
                "engaged",
                "vc_engaged",
                {
                    "engaged_prob": engaged_prob,
                    "match_score": match_score,
                    "explanation_quality": explanation_quality,
                },
                max_steps,
            )
            self._record_interaction(
                interactions,
                step_id="signup_to_engaged",
                interaction="complete_onboarding",
                decision_mode="probabilistic",
                outcome="passed",
                reason_code="vc_engaged",
                score_snapshot={
                    "engaged_prob": engaged_prob,
                    "match_score": match_score,
                    "explanation_quality": explanation_quality,
                },
            )
        else:
            dropoff_reason = "vc_not_engaged"
            self._record_interaction(
                interactions,
                step_id="signup_to_engaged",
                interaction="complete_onboarding",
                decision_mode="probabilistic",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "engaged_prob": engaged_prob,
                    "match_score": match_score,
                    "explanation_quality": explanation_quality,
                },
            )
            return self._result(transitions, interactions, dropoff_reason, match_signal)

        vc_match_threshold = _clamp(
            float(self.params.get("vc_match_score_threshold", self.params["shortlist_threshold"]))
        )
        if match_score >= vc_match_threshold:
            self._record_transition(
                transitions,
                "matched",
                "vc_match_threshold_passed",
                {
                    "match_score": match_score,
                    "vc_match_threshold": vc_match_threshold,
                },
                max_steps,
            )
            self._record_interaction(
                interactions,
                step_id="engaged_to_matched",
                interaction="request_match_recommendations",
                decision_mode="threshold",
                outcome="passed",
                reason_code="vc_match_threshold_passed",
                score_snapshot={
                    "match_score": match_score,
                    "vc_match_threshold": vc_match_threshold,
                },
            )
        else:
            dropoff_reason = "vc_match_below_threshold"
            self._record_interaction(
                interactions,
                step_id="engaged_to_matched",
                interaction="request_match_recommendations",
                decision_mode="threshold",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "match_score": match_score,
                    "vc_match_threshold": vc_match_threshold,
                },
            )
            return self._result(transitions, interactions, dropoff_reason, match_signal)

        interest_prob = _clamp(
            float(self.params["vc_base_interest"])
            + (0.25 * match_score)
            + (0.30 * personalization)
            + (0.20 * explanation_quality)
            + (0.15 * timing_score)
        )
        gate_threshold = max(confidence_threshold, _clamp(float(self.params["interest_threshold"])))
        if interest_prob >= gate_threshold and self._coin_flip(interest_prob):
            self._record_transition(
                transitions,
                "interested",
                "vc_interest_passed",
                {
                    "interest_prob": interest_prob,
                    "gate_threshold": gate_threshold,
                    "personalization_score": personalization,
                },
                max_steps,
            )
            self._record_interaction(
                interactions,
                step_id="matched_to_interested",
                interaction="evaluate_match_explanation",
                decision_mode="threshold_and_probabilistic",
                outcome="passed",
                reason_code="vc_interest_passed",
                score_snapshot={
                    "interest_prob": interest_prob,
                    "gate_threshold": gate_threshold,
                    "personalization_score": personalization,
                    "match_score": match_score,
                    "explanation_quality": explanation_quality,
                    "timing_score": timing_score,
                },
            )
        else:
            dropoff_reason = "vc_not_interested"
            self._record_interaction(
                interactions,
                step_id="matched_to_interested",
                interaction="evaluate_match_explanation",
                decision_mode="threshold_and_probabilistic",
                outcome="failed",
                reason_code=dropoff_reason,
                score_snapshot={
                    "interest_prob": interest_prob,
                    "gate_threshold": gate_threshold,
                    "personalization_score": personalization,
                    "match_score": match_score,
                    "explanation_quality": explanation_quality,
                    "timing_score": timing_score,
                },
            )

        return self._result(transitions, interactions, dropoff_reason, match_signal)

    def _coin_flip(self, probability: float) -> bool:
        return self.rng.random() < _clamp(probability)

    def _record_transition(
        self,
        transitions: List[Dict[str, Any]],
        to_state: str,
        reason_code: str,
        score_snapshot: Dict[str, Any],
        max_steps: int,
    ) -> None:
        if len(transitions) >= max_steps:
            return
        from_state = self.state
        self.state = to_state
        transitions.append(
            {
                "from_state": from_state,
                "to_state": to_state,
                "reason_code": reason_code,
                "score_snapshot": score_snapshot,
            }
        )

    def _result(
        self,
        transitions: List[Dict[str, Any]],
        interaction_trace: List[Dict[str, Any]],
        dropoff_reason: Optional[str],
        match_signal: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "state": self.state,
            "transitions": transitions,
            "interaction_trace": interaction_trace,
            "dropoff_reason": dropoff_reason,
            "signed_up": self.state
            in {"signup", "engaged", "matched", "interested", "meeting"},
            "interested": self.state in {"interested", "meeting"},
            "preferred_founder_id": (match_signal or {}).get("founder_id"),
        }

    def _record_interaction(
        self,
        interactions: List[Dict[str, Any]],
        step_id: str,
        interaction: str,
        decision_mode: str,
        outcome: str,
        reason_code: str,
        score_snapshot: Dict[str, Any],
    ) -> None:
        interactions.append(
            {
                "step_id": step_id,
                "interaction": interaction,
                "decision_mode": decision_mode,
                "outcome": outcome,
                "reason_code": reason_code,
                "score_snapshot": score_snapshot,
            }
        )


class VisitorCustomerAgent:
    """State machine for acquisition-side visitor behavior."""

    def __init__(self, profile: Dict[str, Any], params: Dict[str, Any], rng: Random):
        self.profile = profile
        self.params = params
        self.rng = rng
        self.state = "visit"

    def simulate(
        self,
        acquisition_signal: Optional[Dict[str, Any]],
        global_match_relevance: float,
        max_steps: int,
    ) -> Dict[str, Any]:
        """Simulate visitor funnel progression."""
        transitions: List[Dict[str, Any]] = []
        dropoff_reason: Optional[str] = None

        if max_steps <= 0:
            return self._result(transitions, "max_steps_reached")

        article_relevance = _clamp(
            float((acquisition_signal or {}).get("article_relevance", 0.0))
        )
        tool_usefulness = _clamp(
            float((acquisition_signal or {}).get("tool_usefulness", 0.0))
        )
        cta_clarity = _clamp(float((acquisition_signal or {}).get("cta_clarity", 0.0)))
        cta_friction = _clamp(float(self.profile.get("cta_friction", 0.0)))

        article_prob = _clamp(0.25 + (0.55 * article_relevance) - (0.25 * cta_friction))
        if self._coin_flip(article_prob):
            self._record_transition(
                transitions,
                "article_read",
                "visitor_article_engaged",
                {"article_prob": article_prob, "article_relevance": article_relevance},
                max_steps,
            )
        else:
            dropoff_reason = "visitor_bounced"
            return self._result(transitions, dropoff_reason)

        tool_prob = _clamp(
            float(self.params["visitor_tool_click_rate"])
            * (0.50 + (0.50 * tool_usefulness))
            * (1.0 - (0.35 * cta_friction))
        )
        if self._coin_flip(tool_prob):
            self._record_transition(
                transitions,
                "tool_use",
                "visitor_used_tool",
                {
                    "tool_prob": tool_prob,
                    "tool_usefulness": tool_usefulness,
                    "cta_friction": cta_friction,
                },
                max_steps,
            )
        else:
            dropoff_reason = "visitor_no_tool_use"
            return self._result(transitions, dropoff_reason)

        signup_prob = _clamp(
            float(self.params["signup_rate_from_tool"])
            * (0.60 + (0.40 * cta_clarity))
            * (1.0 - (0.40 * cta_friction))
        )
        if self._coin_flip(signup_prob):
            self._record_transition(
                transitions,
                "signup",
                "visitor_signed_up",
                {
                    "signup_prob": signup_prob,
                    "cta_clarity": cta_clarity,
                },
                max_steps,
            )
        else:
            dropoff_reason = "visitor_tool_no_signup"
            return self._result(transitions, dropoff_reason)

        first_match_prob = _clamp(
            0.15 + (0.55 * _clamp(global_match_relevance)) + (0.20 * tool_usefulness)
        )
        if self._coin_flip(first_match_prob):
            self._record_transition(
                transitions,
                "first_match",
                "visitor_first_match",
                {
                    "first_match_prob": first_match_prob,
                    "global_match_relevance": _clamp(global_match_relevance),
                },
                max_steps,
            )
        else:
            dropoff_reason = "visitor_signup_no_match"

        return self._result(transitions, dropoff_reason)

    def _coin_flip(self, probability: float) -> bool:
        return self.rng.random() < _clamp(probability)

    def _record_transition(
        self,
        transitions: List[Dict[str, Any]],
        to_state: str,
        reason_code: str,
        score_snapshot: Dict[str, Any],
        max_steps: int,
    ) -> None:
        if len(transitions) >= max_steps:
            return
        from_state = self.state
        self.state = to_state
        transitions.append(
            {
                "from_state": from_state,
                "to_state": to_state,
                "reason_code": reason_code,
                "score_snapshot": score_snapshot,
            }
        )

    def _result(
        self,
        transitions: List[Dict[str, Any]],
        dropoff_reason: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "state": self.state,
            "transitions": transitions,
            "dropoff_reason": dropoff_reason,
            "interested": self.state in {"signup", "first_match"},
        }
