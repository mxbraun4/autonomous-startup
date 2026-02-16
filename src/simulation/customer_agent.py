"""Deterministic customer state machine agents for environment simulation."""
from __future__ import annotations

from random import Random
from typing import Any, Dict, List, Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp numeric values into a fixed interval."""
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


class FounderCustomerAgent:
    """State machine for founder-side customer behavior."""

    def __init__(self, profile: Dict[str, Any], params: Dict[str, Any], rng: Random):
        self.profile = profile
        self.params = params
        self.rng = rng
        self.state = "unaware"

    def simulate(
        self,
        match_signal: Optional[Dict[str, Any]],
        outreach_signal: Optional[Dict[str, Any]],
        max_steps: int,
    ) -> Dict[str, Any]:
        """Simulate founder journey until terminal or bounded step limit."""
        transitions: List[Dict[str, Any]] = []
        dropoff_reason: Optional[str] = None

        if max_steps <= 0:
            return self._result(transitions, "max_steps_reached", match_signal)

        match_score = _clamp(float((match_signal or {}).get("match_score", 0.0)))
        explanation_quality = _clamp(
            float((match_signal or {}).get("explanation_quality", 0.0))
        )
        personalization = _clamp(
            float((outreach_signal or {}).get("personalization_score", 0.0))
        )
        timing_score = _clamp(float((outreach_signal or {}).get("timing_score", 0.0)))
        urgency_score = _clamp(float(self.profile.get("urgency_score", 0.0)))

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
        else:
            dropoff_reason = "founder_not_engaged"
            return self._result(transitions, dropoff_reason, match_signal)

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
        else:
            dropoff_reason = "founder_match_below_threshold"
            return self._result(transitions, dropoff_reason, match_signal)

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
        else:
            dropoff_reason = "founder_not_interested"

        return self._result(transitions, dropoff_reason, match_signal)

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
        match_signal: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "state": self.state,
            "transitions": transitions,
            "dropoff_reason": dropoff_reason,
            "interested": self.state in {"interested", "meeting"},
            "preferred_vc_id": (match_signal or {}).get("vc_id"),
        }


class VCCustomerAgent:
    """State machine for VC-side customer behavior."""

    def __init__(self, profile: Dict[str, Any], params: Dict[str, Any], rng: Random):
        self.profile = profile
        self.params = params
        self.rng = rng
        self.state = "unaware"

    def simulate(
        self,
        match_signal: Optional[Dict[str, Any]],
        outreach_signal: Optional[Dict[str, Any]],
        max_steps: int,
    ) -> Dict[str, Any]:
        """Simulate VC journey until terminal or bounded step limit."""
        transitions: List[Dict[str, Any]] = []
        dropoff_reason: Optional[str] = None

        if max_steps <= 0:
            return self._result(transitions, "max_steps_reached", match_signal)

        match_score = _clamp(float((match_signal or {}).get("match_score", 0.0)))
        explanation_quality = _clamp(
            float((match_signal or {}).get("explanation_quality", 0.0))
        )
        timing_score = _clamp(float((outreach_signal or {}).get("timing_score", 0.0)))

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
        else:
            dropoff_reason = "vc_not_engaged"
            return self._result(transitions, dropoff_reason, match_signal)

        shortlist_threshold = _clamp(float(self.params["shortlist_threshold"]))
        if match_score >= shortlist_threshold:
            self._record_transition(
                transitions,
                "shortlist",
                "vc_shortlist_threshold_passed",
                {
                    "match_score": match_score,
                    "shortlist_threshold": shortlist_threshold,
                },
                max_steps,
            )
        else:
            dropoff_reason = "vc_not_shortlisted"
            return self._result(transitions, dropoff_reason, match_signal)

        confidence_threshold = _clamp(float(self.profile.get("confidence_threshold", 0.5)))
        interest_prob = _clamp(
            float(self.params["vc_base_interest"])
            + (0.40 * match_score)
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
                },
                max_steps,
            )
        else:
            dropoff_reason = "vc_not_interested"

        return self._result(transitions, dropoff_reason, match_signal)

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
        match_signal: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "state": self.state,
            "transitions": transitions,
            "dropoff_reason": dropoff_reason,
            "interested": self.state in {"interested", "meeting"},
            "preferred_founder_id": (match_signal or {}).get("founder_id"),
        }


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
