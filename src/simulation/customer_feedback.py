"""Customer interaction feedback generation with optional LLM enrichment."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set

from src.llm.client import LLMClient
from src.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_LLM_FEEDBACK_STEPS = {"matched_to_interested"}

FEEDBACK_CONTRACT_VERSION = 1

_REASON_FEEDBACK_CATALOG: Dict[str, Dict[str, str]] = {
    "founder_signup_incomplete_profile": {
        "category": "signup_validation",
        "template": "Signup aborted: required startup profile fields were missing in the signup form.",
        "action_hint": "Reduce mandatory founder fields and make required inputs explicit.",
    },
    "vc_signup_incomplete_profile": {
        "category": "signup_validation",
        "template": "Signup aborted: required VC profile fields were missing in the signup form.",
        "action_hint": "Reduce mandatory VC fields and make required inputs explicit.",
    },
    "founder_no_signup": {
        "category": "signup_conversion",
        "template": (
            "Signup aborted: expected value from onboarding was below required confidence "
            "versus perceived signup friction."
        ),
        "action_hint": "Improve signup value communication and remove friction before submit.",
    },
    "vc_no_signup": {
        "category": "signup_conversion",
        "template": (
            "Signup aborted: match preview confidence was not strong enough for current "
            "investment selectivity."
        ),
        "action_hint": "Improve pre-signup match preview and reduce signup friction.",
    },
    "founder_not_engaged": {
        "category": "engagement",
        "template": (
            "Engagement aborted: dashboard exploration did not produce enough relevance "
            "signal after signup."
        ),
        "action_hint": "Improve first-session relevance and onboarding guidance for founders.",
    },
    "vc_not_engaged": {
        "category": "engagement",
        "template": (
            "Engagement aborted: post-signup discovery did not meet minimum relevance "
            "signal for active use."
        ),
        "action_hint": "Improve first-session relevance and onboarding guidance for VCs.",
    },
    "founder_match_below_threshold": {
        "category": "match_quality",
        "template": "Match step aborted: suggested investor fit was below founder match threshold.",
        "action_hint": "Increase founder-side candidate relevance before match request.",
    },
    "vc_match_below_threshold": {
        "category": "match_quality",
        "template": "Match step aborted: suggested startup fit was below VC match threshold.",
        "action_hint": "Increase VC-side candidate relevance before match request.",
    },
    "founder_not_interested": {
        "category": "interest_gate",
        "template": (
            "Interest step aborted: personalization, explanation quality, and timing "
            "did not meet founder decision gate."
        ),
        "action_hint": "Improve explanation quality, timing, and personalization for founders.",
    },
    "vc_not_interested": {
        "category": "interest_gate",
        "template": "Interest step aborted: fit rationale and timing did not satisfy VC decision gate.",
        "action_hint": "Improve explanation quality, timing, and fit rationale for VCs.",
    },
    "founder_no_reciprocal_interest": {
        "category": "reciprocal_interest",
        "template": (
            "Meeting step aborted: founder signaled interest but no reciprocal VC interest "
            "was detected."
        ),
        "action_hint": "Increase reciprocal interest by improving bilateral fit quality.",
    },
    "vc_no_reciprocal_interest": {
        "category": "reciprocal_interest",
        "template": (
            "Meeting step aborted: VC signaled interest but no reciprocal founder interest "
            "was detected."
        ),
        "action_hint": "Increase reciprocal interest by improving bilateral fit quality.",
    },
    "mutual_interest_no_meeting": {
        "category": "meeting_conversion",
        "template": (
            "Meeting step aborted: both sides were interested but meeting conversion did "
            "not pass this run."
        ),
        "action_hint": "Improve scheduling flow and meeting conversion nudges.",
    },
    "max_steps_reached": {
        "category": "guardrail",
        "template": "Flow aborted: maximum transition limit reached before completing the journey.",
        "action_hint": "Review transition depth and guardrail limits for this run.",
    },
}


class CustomerFeedbackGenerator:
    """Build feedback messages for simulation interactions."""

    def __init__(
        self,
        use_llm: bool = False,
        llm_steps: Optional[Iterable[str]] = None,
        llm_model: str = "claude-3-haiku-20240307",
        llm_temperature: float = 0.0,
    ) -> None:
        self.use_llm = bool(use_llm)
        self.llm_steps: Set[str] = set(llm_steps or DEFAULT_LLM_FEEDBACK_STEPS)
        self.llm_model = llm_model
        self.llm_temperature = float(llm_temperature)
        self._llm_client = LLMClient() if self.use_llm else None

    @property
    def llm_active(self) -> bool:
        """Return True when real LLM feedback generation is active."""
        return bool(self._llm_client and not self._llm_client.mock_mode)

    @property
    def contract_version(self) -> int:
        """Return feedback payload contract version."""
        return FEEDBACK_CONTRACT_VERSION

    def render_feedback(
        self,
        actor_type: str,
        actor_id: str,
        interaction: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return feedback payload with message and source type."""
        reason_code = str(interaction.get("reason_code", "")).strip()
        step_id = str(interaction.get("step_id", "")).strip()
        outcome = str(interaction.get("outcome", "")).strip()
        score_snapshot = interaction.get("score_snapshot", {})
        if not isinstance(score_snapshot, dict):
            score_snapshot = {}

        reason_info = _REASON_FEEDBACK_CATALOG.get(reason_code, {})
        category = str(reason_info.get("category", "unknown"))
        action_hint = str(
            reason_info.get(
                "action_hint",
                "Inspect decision signals and refine the previous step for this transition.",
            )
        )

        if reason_info:
            base_message = _render_reason_message(
                reason_code=reason_code,
                reason_info=reason_info,
                score_snapshot=score_snapshot,
            )
        elif outcome == "passed":
            base_message = "Transition accepted and actor progressed to the next phase."
            category = "success"
            action_hint = "Continue monitoring this step for sustained performance."
        else:
            base_message = "Transition aborted because decision criteria were not satisfied."

        if self.use_llm and step_id in self.llm_steps:
            llm_message = self._llm_feedback_message(
                actor_type=actor_type,
                actor_id=actor_id,
                step_id=step_id,
                outcome=outcome,
                reason_code=reason_code,
                score_snapshot=score_snapshot,
            )
            if llm_message:
                return {
                    "message": llm_message,
                    "source": "llm",
                    "category": category,
                    "action_hint": action_hint,
                    "contract_version": FEEDBACK_CONTRACT_VERSION,
                }

        return {
            "message": base_message,
            "source": "template",
            "category": category,
            "action_hint": action_hint,
            "contract_version": FEEDBACK_CONTRACT_VERSION,
        }

    def _llm_feedback_message(
        self,
        actor_type: str,
        actor_id: str,
        step_id: str,
        outcome: str,
        reason_code: str,
        score_snapshot: Dict[str, Any],
    ) -> Optional[str]:
        if self._llm_client is None:
            return None

        # Avoid mock random fallback and preserve reproducibility in local runs.
        if self._llm_client.mock_mode:
            return None

        try:
            prompt = (
                "Provide one concise sentence of product feedback for this simulation "
                "interaction.\n"
                f"ActorType: {actor_type}\n"
                f"ActorId: {actor_id}\n"
                f"Step: {step_id}\n"
                f"Outcome: {outcome}\n"
                f"ReasonCode: {reason_code}\n"
                f"ScoreSnapshot: {score_snapshot}\n"
            )
            message = self._llm_client.generate(
                prompt=prompt,
                system=(
                    "You generate concise simulation feedback for product learning. "
                    "One sentence only. No markdown."
                ),
                model=self.llm_model,
                max_tokens=80,
                temperature=self.llm_temperature,
            )
            message = (message or "").strip()
            return message or None
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("LLM feedback generation failed for %s/%s: %s", actor_type, step_id, exc)
            return None


def _render_reason_message(
    reason_code: str,
    reason_info: Dict[str, str],
    score_snapshot: Dict[str, Any],
) -> str:
    if reason_code in {
        "founder_signup_incomplete_profile",
        "vc_signup_incomplete_profile",
    }:
        missing_fields = _missing_fields_text(score_snapshot)
        if missing_fields:
            prefix = "startup" if reason_code.startswith("founder_") else "VC"
            return (
                f"Signup aborted: required {prefix} profile fields were missing in the signup "
                f"form ({missing_fields})."
            )
    return str(reason_info.get("template", "Transition aborted because decision criteria were not satisfied."))


def _missing_fields_text(score_snapshot: Dict[str, Any]) -> str:
    fields = score_snapshot.get("missing_required_fields")
    if not isinstance(fields, list):
        return ""

    cleaned = [
        str(field).strip()
        for field in fields
        if isinstance(field, str) and str(field).strip()
    ]
    if not cleaned:
        return ""

    deduped = sorted(dict.fromkeys(cleaned))
    return ", ".join(deduped)
