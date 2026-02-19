"""Deterministic event instrumentation for founder signup signal scoring."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

_VALID_ACTOR_TYPES = {"founder", "vc", "visitor"}

_EVENT_CTA_IMPRESSION = "cta_impression"
_EVENT_CTA_CLICK = "cta_click"
_EVENT_SIGNUP_START = "signup_start"
_EVENT_SIGNUP_SUBMIT = "signup_submit"
_EVENT_SIGNUP_FIELD_ERROR = "signup_field_error"
_EVENT_SIGNUP_ABANDON = "signup_abandon"
_EVENT_TRUST_VIEW = "trust_block_view"
_EVENT_PROOF_VIEW = "proof_block_view"
_EVENT_LANDING_VIEW = "landing_view"

_TRACKED_EVENT_NAMES = {
    _EVENT_CTA_IMPRESSION,
    _EVENT_CTA_CLICK,
    _EVENT_SIGNUP_START,
    _EVENT_SIGNUP_SUBMIT,
    _EVENT_SIGNUP_FIELD_ERROR,
    _EVENT_SIGNUP_ABANDON,
    _EVENT_TRUST_VIEW,
    _EVENT_PROOF_VIEW,
    _EVENT_LANDING_VIEW,
}

_REQUIRED_EVENT_FIELDS = (
    "event_id",
    "timestamp",
    "session_id",
    "actor_type",
    "actor_id",
    "event_name",
    "properties",
)

_UTM_SOURCE_INTENT_FIT = {
    "startup_community": 0.90,
    "accelerator": 0.88,
    "founder_newsletter": 0.85,
    "linkedin_founders": 0.82,
    "organic_search": 0.70,
    "direct": 0.68,
    "generic_ads": 0.55,
    "broad_social": 0.50,
}

_SIGNUP_SIGNAL_FORMULA_VERSION = 1


def validate_product_events(events: Any) -> List[str]:
    """Validate product-event payload for deterministic signup instrumentation."""
    errors: List[str] = []
    if not isinstance(events, list):
        return ["product_events must be a list."]

    seen_event_ids = set()
    for idx, event in enumerate(events):
        path = f"product_events[{idx}]"
        if not isinstance(event, dict):
            errors.append(f"{path} must be an object.")
            continue

        missing_fields = [field for field in _REQUIRED_EVENT_FIELDS if field not in event]
        if missing_fields:
            missing_str = ", ".join(missing_fields)
            errors.append(f"{path} missing required fields: {missing_str}.")

        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            errors.append(f"{path}.event_id must be a non-empty string.")
        elif event_id in seen_event_ids:
            errors.append(f"{path}.event_id must be unique within product_events.")
        else:
            seen_event_ids.add(event_id)

        timestamp = event.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            errors.append(f"{path}.timestamp must be a non-empty ISO-8601 string.")
        elif not _is_iso8601_timestamp(timestamp):
            errors.append(f"{path}.timestamp must be a valid ISO-8601 string.")

        session_id = event.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            errors.append(f"{path}.session_id must be a non-empty string.")

        event_name = event.get("event_name")
        if not isinstance(event_name, str) or not event_name.strip():
            errors.append(f"{path}.event_name must be a non-empty string.")
        elif event_name not in _TRACKED_EVENT_NAMES:
            allowed = ", ".join(sorted(_TRACKED_EVENT_NAMES))
            errors.append(
                f"{path}.event_name must be one of: {allowed}."
            )
        actor_type = event.get("actor_type")
        if not isinstance(actor_type, str) or actor_type not in _VALID_ACTOR_TYPES:
            errors.append(
                f"{path}.actor_type must be one of: {', '.join(sorted(_VALID_ACTOR_TYPES))}."
            )
        actor_id = event.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id.strip():
            errors.append(f"{path}.actor_id must be a non-empty string.")

        page_id = event.get("page_id")
        if page_id is not None and (not isinstance(page_id, str) or not page_id.strip()):
            errors.append(f"{path}.page_id must be a non-empty string when provided.")

        properties = event.get("properties")
        if not isinstance(properties, dict):
            errors.append(f"{path}.properties must be an object.")
            continue

        normalized_event_name = str(event_name).strip() if isinstance(event_name, str) else ""

        for field in (
            "channel_intent_fit",
            "form_complexity_score",
            "trust_score",
            "proof_of_outcomes",
        ):
            value = properties.get(field)
            if value is None:
                continue
            if not _is_probability(value):
                errors.append(f"{path}.properties.{field} must be in [0.0, 1.0].")

        utm_source = properties.get("utm_source")
        if utm_source is not None and not isinstance(utm_source, str):
            errors.append(f"{path}.properties.utm_source must be a string when provided.")
        if isinstance(utm_source, str) and not utm_source.strip():
            errors.append(f"{path}.properties.utm_source must be non-empty when provided.")

        field_name = properties.get("field_name")
        if field_name is not None and (not isinstance(field_name, str) or not field_name.strip()):
            errors.append(f"{path}.properties.field_name must be a non-empty string when provided.")

        abandon_reason = properties.get("abandon_reason")
        if abandon_reason is not None and (
            not isinstance(abandon_reason, str) or not abandon_reason.strip()
        ):
            errors.append(
                f"{path}.properties.abandon_reason must be a non-empty string when provided."
            )

        if normalized_event_name == _EVENT_LANDING_VIEW:
            has_channel_intent_fit = _is_probability(properties.get("channel_intent_fit"))
            has_utm_source = isinstance(utm_source, str) and bool(utm_source.strip())
            if not has_channel_intent_fit and not has_utm_source:
                errors.append(
                    f"{path}.landing_view requires properties.channel_intent_fit or "
                    "properties.utm_source."
                )

    return errors


def derive_signup_signal_overrides_from_events(
    events: List[Dict[str, Any]],
    founders: List[Dict[str, Any]],
    default_params: Mapping[str, Any],
) -> Dict[str, Any]:
    """Map product events to deterministic founder-signup signal overrides."""
    errors = validate_product_events(events)
    if errors:
        lines = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"Invalid product events:\n{lines}")

    founder_ids = {
        str(profile.get("id", ""))
        for profile in founders
        if isinstance(profile, dict) and isinstance(profile.get("id"), str)
    }
    founder_ids.discard("")

    default_cta = _probability_with_fallback(default_params.get("founder_signup_cta_clarity"), 0.72)
    default_friction = _probability_with_fallback(
        default_params.get("founder_signup_friction"),
        0.30,
    )
    default_trust = _probability_with_fallback(default_params.get("founder_signup_trust_score"), 1.0)
    default_form = _probability_with_fallback(
        default_params.get("founder_signup_form_complexity"),
        0.0,
    )
    default_channel_fit = _probability_with_fallback(
        default_params.get("founder_signup_channel_intent_fit"),
        1.0,
    )
    default_proof = _probability_with_fallback(
        default_params.get("founder_signup_proof_of_outcomes"),
        1.0,
    )

    founder_stats = {
        founder_id: {
            "cta_impressions": 0,
            "cta_clicks": 0,
            "signup_starts": 0,
            "signup_submits": 0,
            "signup_field_errors": 0,
            "signup_abandons": 0,
            "trust_views": 0,
            "proof_views": 0,
            "channel_intent_fit_values": [],
            "form_complexity_values": [],
            "trust_score_values": [],
            "proof_score_values": [],
        }
        for founder_id in founder_ids
    }

    sorted_events = sorted(
        [dict(event) for event in events],
        key=lambda event: (
            str(event.get("timestamp", "")),
            str(event.get("session_id", "")),
            str(event.get("event_id", "")),
            str(event.get("actor_id", "")),
            str(event.get("event_name", "")),
        ),
    )

    event_type_counts: Counter[str] = Counter()
    founder_event_count = 0

    for event in sorted_events:
        event_name = str(event.get("event_name", "")).strip()
        event_type_counts[event_name] += 1

        actor_type = str(event.get("actor_type", "")).strip()
        if actor_type != "founder":
            continue
        actor_id = str(event.get("actor_id", "")).strip()
        if actor_id not in founder_stats:
            continue
        founder_event_count += 1
        stats = founder_stats[actor_id]
        properties = event.get("properties")
        if not isinstance(properties, dict):
            properties = {}

        if event_name == _EVENT_CTA_IMPRESSION:
            stats["cta_impressions"] += 1
        elif event_name == _EVENT_CTA_CLICK:
            stats["cta_clicks"] += 1
        elif event_name == _EVENT_SIGNUP_START:
            stats["signup_starts"] += 1
            form_complexity = properties.get("form_complexity_score")
            if _is_probability(form_complexity):
                stats["form_complexity_values"].append(float(form_complexity))
        elif event_name == _EVENT_SIGNUP_SUBMIT:
            stats["signup_submits"] += 1
        elif event_name == _EVENT_SIGNUP_FIELD_ERROR:
            stats["signup_field_errors"] += 1
        elif event_name == _EVENT_SIGNUP_ABANDON:
            stats["signup_abandons"] += 1
        elif event_name == _EVENT_TRUST_VIEW:
            stats["trust_views"] += 1
            trust_score = properties.get("trust_score")
            if _is_probability(trust_score):
                stats["trust_score_values"].append(float(trust_score))
        elif event_name == _EVENT_PROOF_VIEW:
            stats["proof_views"] += 1
            proof_score = properties.get("proof_of_outcomes")
            if _is_probability(proof_score):
                stats["proof_score_values"].append(float(proof_score))
        elif event_name == _EVENT_LANDING_VIEW:
            channel_intent_fit = properties.get("channel_intent_fit")
            if _is_probability(channel_intent_fit):
                stats["channel_intent_fit_values"].append(float(channel_intent_fit))
            else:
                utm_source = properties.get("utm_source")
                if isinstance(utm_source, str):
                    mapped = _UTM_SOURCE_INTENT_FIT.get(utm_source.strip().lower())
                    if mapped is not None:
                        stats["channel_intent_fit_values"].append(float(mapped))

    founder_profile_overrides: Dict[str, Dict[str, float]] = {}
    founder_signal_coverage: Dict[str, Dict[str, bool]] = {}
    founder_score_summary: Dict[str, Dict[str, float]] = {}
    founder_signal_sources: Dict[str, Dict[str, str]] = {}
    founder_signal_inputs: Dict[str, Dict[str, float]] = {}
    cta_values: List[float] = []
    friction_values: List[float] = []

    for founder_id, stats in founder_stats.items():
        impressions = int(stats["cta_impressions"])
        clicks = int(stats["cta_clicks"])
        starts = int(stats["signup_starts"])
        submits = int(stats["signup_submits"])
        errors_count = int(stats["signup_field_errors"])
        abandons = int(stats["signup_abandons"])

        has_cta = impressions > 0
        has_friction = starts > 0
        has_trust = bool(stats["trust_score_values"] or stats["trust_views"] > 0)
        has_form = bool(stats["form_complexity_values"])
        has_channel_fit = bool(stats["channel_intent_fit_values"])
        has_proof = bool(stats["proof_score_values"] or stats["proof_views"] > 0)

        cta_clarity = default_cta
        cta_source = "fallback_default"
        cta_ctr = 0.0
        if impressions > 0:
            cta_ctr = _clamp(clicks / impressions)
            cta_clarity = cta_ctr
            cta_source = "observed_ratio"

        friction = default_friction
        friction_source = "fallback_default"
        error_rate = 0.0
        abandon_rate = 0.0
        incomplete_rate = 0.0
        if starts > 0:
            error_rate = errors_count / starts
            abandon_rate = abandons / starts
            incomplete_rate = max(starts - submits, 0) / starts
            friction = _clamp(
                0.15 + (0.35 * error_rate) + (0.35 * abandon_rate) + (0.15 * incomplete_rate)
            )
            friction_source = "observed_composite"

        trust_score = default_trust
        trust_source = "fallback_default"
        trust_values = stats["trust_score_values"]
        if trust_values:
            trust_score = _clamp(_mean(trust_values))
            trust_source = "observed_value"
        elif int(stats["trust_views"]) > 0:
            trust_score = _clamp(0.55 + (0.15 * int(stats["trust_views"])))
            trust_source = "derived_from_view_count"

        proof_score = default_proof
        proof_source = "fallback_default"
        proof_values = stats["proof_score_values"]
        if proof_values:
            proof_score = _clamp(_mean(proof_values))
            proof_source = "observed_value"
        elif int(stats["proof_views"]) > 0:
            proof_score = _clamp(0.55 + (0.15 * int(stats["proof_views"])))
            proof_source = "derived_from_view_count"

        form_complexity = default_form
        form_source = "fallback_default"
        form_values = stats["form_complexity_values"]
        if form_values:
            form_complexity = _clamp(_mean(form_values))
            form_source = "observed_value"

        channel_fit = default_channel_fit
        channel_source = "fallback_default"
        channel_values = stats["channel_intent_fit_values"]
        if channel_values:
            channel_fit = _clamp(_mean(channel_values))
            channel_source = "observed_value"

        founder_score_summary[founder_id] = {
            "founder_signup_cta_clarity": cta_clarity,
            "founder_signup_friction": friction,
            "trust_score": trust_score,
            "form_complexity_score": form_complexity,
            "channel_intent_fit": channel_fit,
            "proof_of_outcomes": proof_score,
        }
        founder_signal_sources[founder_id] = {
            "founder_signup_cta_clarity": cta_source,
            "founder_signup_friction": friction_source,
            "trust_score": trust_source,
            "form_complexity_score": form_source,
            "channel_intent_fit": channel_source,
            "proof_of_outcomes": proof_source,
        }
        founder_signal_inputs[founder_id] = {
            "cta_impressions": float(impressions),
            "cta_clicks": float(clicks),
            "cta_ctr": cta_ctr,
            "signup_starts": float(starts),
            "signup_submits": float(submits),
            "signup_field_errors": float(errors_count),
            "signup_abandons": float(abandons),
            "signup_error_rate": _safe_rate(errors_count, starts),
            "signup_abandon_rate": _safe_rate(abandons, starts),
            "signup_incomplete_rate": _safe_rate(max(starts - submits, 0), starts),
            "trust_views": float(int(stats["trust_views"])),
            "proof_views": float(int(stats["proof_views"])),
        }
        founder_signal_coverage[founder_id] = {
            "cta_clarity_observed": has_cta,
            "signup_friction_observed": has_friction,
            "trust_observed": has_trust,
            "form_complexity_observed": has_form,
            "channel_intent_fit_observed": has_channel_fit,
            "proof_of_outcomes_observed": has_proof,
        }

        if has_cta:
            cta_values.append(cta_clarity)
        if has_friction:
            friction_values.append(friction)

        profile_override: Dict[str, float] = {}
        if has_trust:
            profile_override["trust_score"] = trust_score
        if has_form:
            profile_override["form_complexity_score"] = form_complexity
        if has_channel_fit:
            profile_override["channel_intent_fit"] = channel_fit
        if has_proof:
            profile_override["proof_of_outcomes"] = proof_score
        if profile_override:
            founder_profile_overrides[founder_id] = profile_override

    param_overrides: Dict[str, float] = {}
    if cta_values:
        param_overrides["founder_signup_cta_clarity"] = _clamp(_mean(cta_values))
    if friction_values:
        param_overrides["founder_signup_friction"] = _clamp(_mean(friction_values))

    effective_global_signup_params = {
        "founder_signup_cta_clarity": _clamp(
            float(param_overrides.get("founder_signup_cta_clarity", default_cta))
        ),
        "founder_signup_friction": _clamp(
            float(param_overrides.get("founder_signup_friction", default_friction))
        ),
    }
    param_sources = {
        "founder_signup_cta_clarity": {
            "source": "observed_mean" if cta_values else "fallback_default",
            "observed_count": len(cta_values),
            "default_value": default_cta,
            "effective_value": effective_global_signup_params["founder_signup_cta_clarity"],
        },
        "founder_signup_friction": {
            "source": "observed_mean" if friction_values else "fallback_default",
            "observed_count": len(friction_values),
            "default_value": default_friction,
            "effective_value": effective_global_signup_params["founder_signup_friction"],
        },
    }

    diagnostics = {
        "scoring_formula_version": _SIGNUP_SIGNAL_FORMULA_VERSION,
        "event_count": len(sorted_events),
        "founder_event_count": founder_event_count,
        "tracked_event_count": int(
            sum(count for name, count in event_type_counts.items() if name in _TRACKED_EVENT_NAMES)
        ),
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "founder_signal_coverage": founder_signal_coverage,
        "founder_scores": founder_score_summary,
        "founder_signal_sources": founder_signal_sources,
        "founder_signal_inputs": founder_signal_inputs,
        "param_overrides": param_overrides,
        "param_sources": param_sources,
        "effective_global_signup_params": effective_global_signup_params,
    }

    return {
        "param_overrides": param_overrides,
        "founder_profile_overrides": founder_profile_overrides,
        "diagnostics": diagnostics,
    }


def _is_probability(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return 0.0 <= float(value) <= 1.0


def _clamp(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _probability_with_fallback(value: Any, fallback: float) -> float:
    if _is_probability(value):
        return float(value)
    return fallback


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator / denominator)


def _is_iso8601_timestamp(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True
