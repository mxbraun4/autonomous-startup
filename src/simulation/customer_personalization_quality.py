"""Personalization-score evaluation with optional LLM enrichment."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any, Dict

from src.llm.client import LLMClient
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SCORE_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)")


def _clamp(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


class PersonalizationScoreEvaluator:
    """Evaluate personalization score with deterministic fallback."""

    _GLOBAL_SCORE_CACHE: Dict[str, Dict[str, Any]] = {}

    def __init__(
        self,
        use_llm: bool = False,
        llm_model: str = "claude-3-haiku-20240307",
        llm_temperature: float = 0.0,
        llm_blend_weight: float = 0.60,
    ) -> None:
        self.use_llm = bool(use_llm)
        self.llm_model = str(llm_model or "claude-3-haiku-20240307")
        self.llm_temperature = _clamp(llm_temperature)
        self.llm_blend_weight = _clamp(llm_blend_weight)
        self._llm_client = LLMClient() if self.use_llm else None

        self.requests = 0
        self.cache_hits = 0
        self.llm_scored = 0
        self.fallback_count = 0

    @property
    def llm_active(self) -> bool:
        return bool(self._llm_client and not self._llm_client.mock_mode)

    def evaluate(
        self,
        founder_profile: Dict[str, Any],
        vc_profile: Dict[str, Any],
        base_personalization_score: float,
        context: Dict[str, float],
    ) -> Dict[str, Any]:
        self.requests += 1
        base_score = _clamp(base_personalization_score)

        if not self.llm_active:
            self.fallback_count += 1
            return {
                "score": base_score,
                "source": "deterministic",
                "llm_score": None,
                "is_personalized": base_score >= 0.5,
            }

        cache_key = (
            f"{self.llm_model}|{self.llm_temperature}|"
            f"{self._build_cache_key(founder_profile, vc_profile, context)}"
        )
        cached = self._GLOBAL_SCORE_CACHE.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            llm_score = _clamp(cached.get("llm_score"))
            final = _clamp(
                (1.0 - self.llm_blend_weight) * base_score
                + self.llm_blend_weight * llm_score
            )
            return {
                "score": final,
                "source": "llm_blended_cached",
                "llm_score": llm_score,
                "is_personalized": bool(
                    cached.get("is_personalized", llm_score >= 0.5)
                ),
            }

        llm_result = self._score_with_llm(founder_profile, vc_profile, context)
        llm_score = llm_result.get("llm_score")
        if llm_score is None:
            self.fallback_count += 1
            return {
                "score": base_score,
                "source": "deterministic_fallback",
                "llm_score": None,
                "is_personalized": base_score >= 0.5,
            }

        llm_score = _clamp(llm_score)
        self.llm_scored += 1
        self._GLOBAL_SCORE_CACHE[cache_key] = {
            "llm_score": llm_score,
            "is_personalized": bool(
                llm_result.get("is_personalized", llm_score >= 0.5)
            ),
        }
        final = _clamp(
            (1.0 - self.llm_blend_weight) * base_score
            + self.llm_blend_weight * llm_score
        )
        return {
            "score": final,
            "source": "llm_blended",
            "llm_score": llm_score,
            "is_personalized": bool(
                llm_result.get("is_personalized", llm_score >= 0.5)
            ),
        }

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "requested": self.requests,
            "llm_active": self.llm_active,
            "llm_scored": self.llm_scored,
            "cache_hits": self.cache_hits,
            "fallback_count": self.fallback_count,
            "llm_model": self.llm_model,
            "llm_temperature": self.llm_temperature,
            "llm_blend_weight": self.llm_blend_weight,
        }

    def _score_with_llm(
        self,
        founder_profile: Dict[str, Any],
        vc_profile: Dict[str, Any],
        context: Dict[str, float],
    ) -> Dict[str, Any]:
        if self._llm_client is None:
            return {"llm_score": None, "is_personalized": None}

        prompt = (
            "Rate how personalized the investor outreach and recommendation feels.\n"
            "Return strict JSON with keys: score (0..1), is_personalized (bool), reason (max 20 words).\n"
            f"FounderProfile: {self._compact_profile(founder_profile, founder=True)}\n"
            f"VCProfile: {self._compact_profile(vc_profile, founder=False)}\n"
            f"DeterministicSignals: {context}\n"
        )
        try:
            response = self._llm_client.generate(
                prompt=prompt,
                system=(
                    "You evaluate personalization quality for startup-VC match communication. "
                    "Respond with valid JSON only."
                ),
                model=self.llm_model,
                max_tokens=120,
                temperature=self.llm_temperature,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.warning("LLM personalization scoring failed: %s", exc)
            return {"llm_score": None, "is_personalized": None}

        return self._parse_llm_response(response)

    @staticmethod
    def _compact_profile(profile: Dict[str, Any], founder: bool) -> Dict[str, Any]:
        if founder:
            return {
                "sector": profile.get("sector"),
                "stage": profile.get("stage"),
                "geography": profile.get("geography"),
                "fundraising_status": profile.get("fundraising_status"),
                "urgency_score": profile.get("urgency_score"),
                "trust_score": profile.get("trust_score"),
                "channel_intent_fit": profile.get("channel_intent_fit"),
                "proof_of_outcomes": profile.get("proof_of_outcomes"),
                "form_complexity_score": profile.get("form_complexity_score"),
            }
        return {
            "thesis_sectors": profile.get("thesis_sectors"),
            "stage_focus": profile.get("stage_focus"),
            "geography": profile.get("geography"),
            "confidence_threshold": profile.get("confidence_threshold"),
        }

    @staticmethod
    def _build_cache_key(
        founder_profile: Dict[str, Any],
        vc_profile: Dict[str, Any],
        context: Dict[str, float],
    ) -> str:
        key_payload = {
            "founder": PersonalizationScoreEvaluator._compact_profile(
                founder_profile, founder=True
            ),
            "vc": PersonalizationScoreEvaluator._compact_profile(vc_profile, founder=False),
            "context": context,
        }
        serialized = json.dumps(key_payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_llm_response(response: str) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            return {"llm_score": None, "is_personalized": None}

        try:
            payload = json.loads(text)
            score = _clamp(payload.get("score"))
            is_personalized = payload.get("is_personalized")
            if not isinstance(is_personalized, bool):
                is_personalized = score >= 0.5
            return {"llm_score": score, "is_personalized": is_personalized}
        except Exception:
            match = _SCORE_PATTERN.search(text)
            if match is None:
                return {"llm_score": None, "is_personalized": None}
            score = _clamp(float(match.group(1)))
            return {"llm_score": score, "is_personalized": score >= 0.5}
