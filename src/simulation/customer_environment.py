"""Customer environment seed loading, validation, and simulation runner."""
from __future__ import annotations

import json
from pathlib import Path
from random import Random
from typing import Any, Dict, List, Optional, Tuple

from src.simulation.customer_agent import (
    FounderCustomerAgent,
    VCCustomerAgent,
    VisitorCustomerAgent,
)
from src.utils.config import settings

COHORT_KEYS = ("founders", "vcs", "visitors")
CORE_PARAM_KEYS = (
    "founder_base_interest",
    "vc_base_interest",
    "visitor_tool_click_rate",
    "signup_rate_from_tool",
    "meeting_rate_from_mutual_interest",
)

REQUIRED_FIELDS = {
    "founders": {
        "id",
        "sector",
        "stage",
        "geography",
        "fundraising_status",
        "urgency_score",
    },
    "vcs": {
        "id",
        "thesis_sectors",
        "stage_focus",
        "geography",
        "confidence_threshold",
    },
    "visitors": {
        "id",
        "intent_topic",
        "tool_need_score",
        "cta_friction",
    },
}

PROBABILITY_FIELDS = {
    "founders": {"urgency_score"},
    "vcs": {"confidence_threshold"},
    "visitors": {"tool_need_score", "cta_friction"},
}

SIGNAL_KEYS = ("match_signals", "outreach_signals", "acquisition_signals")
SIGNAL_REQUIRED_FIELDS = {
    "match_signals": {
        "founder_id",
        "vc_id",
        "match_score",
        "explanation_quality",
    },
    "outreach_signals": {
        "founder_id",
        "vc_id",
        "personalization_score",
        "timing_score",
    },
    "acquisition_signals": {
        "visitor_id",
        "article_relevance",
        "tool_usefulness",
        "cta_clarity",
    },
}

DEFAULT_ENV_PARAMS = {
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


def run_customer_environment(environment_input: Dict[str, Any]) -> Dict[str, Any]:
    """Run deterministic customer environment simulation for one iteration."""
    validation_errors = validate_environment_input(environment_input)
    if validation_errors:
        iteration = _safe_int(
            (environment_input.get("run_context") or {}).get("iteration"), default=1
        )
        return _empty_environment_output(iteration, validation_errors)

    run_context = environment_input["run_context"]
    params = merge_environment_params(environment_input["params"])
    cohorts = environment_input["cohorts"]
    signals = environment_input["signals"]

    match_signals = [dict(item) for item in signals["match_signals"]]
    outreach_signals = [dict(item) for item in signals["outreach_signals"]]
    acquisition_signals = [dict(item) for item in signals["acquisition_signals"]]

    founders = sorted(cohorts["founders"], key=lambda item: str(item.get("id", "")))
    vcs = sorted(cohorts["vcs"], key=lambda item: str(item.get("id", "")))
    visitors = sorted(cohorts["visitors"], key=lambda item: str(item.get("id", "")))

    rng = Random(int(run_context["seed"]))
    max_steps = int(params["max_steps_per_customer"])

    match_by_founder = _best_signals_by_actor(
        match_signals,
        actor_key="founder_id",
        quality_keys=("match_score", "explanation_quality"),
    )
    match_by_vc = _best_signals_by_actor(
        match_signals,
        actor_key="vc_id",
        quality_keys=("match_score", "explanation_quality"),
    )
    outreach_by_pair = _signals_by_pair(outreach_signals)
    outreach_by_founder = _best_signals_by_actor(
        outreach_signals,
        actor_key="founder_id",
        quality_keys=("personalization_score", "timing_score"),
    )
    outreach_by_vc = _best_signals_by_actor(
        outreach_signals,
        actor_key="vc_id",
        quality_keys=("personalization_score", "timing_score"),
    )
    acquisition_by_visitor = _best_signals_by_actor(
        acquisition_signals,
        actor_key="visitor_id",
        quality_keys=("tool_usefulness", "article_relevance", "cta_clarity"),
    )

    event_counter = 0
    events: List[Dict[str, Any]] = []
    dropoff_reasons: Dict[str, int] = {}

    final_states = {"founders": {}, "vcs": {}, "visitors": {}}
    founder_results: Dict[str, Dict[str, Any]] = {}
    vc_results: Dict[str, Dict[str, Any]] = {}

    iteration = int(run_context["iteration"])

    for founder in founders:
        founder_id = str(founder["id"])
        match_signal = match_by_founder.get(founder_id)
        preferred_vc_id = (match_signal or {}).get("vc_id")
        outreach_signal = _select_pair_signal(
            outreach_by_pair,
            founder_id,
            str(preferred_vc_id) if preferred_vc_id else None,
            fallback_signal=outreach_by_founder.get(founder_id),
        )

        agent = FounderCustomerAgent(founder, params, rng)
        result = agent.simulate(match_signal, outreach_signal, max_steps=max_steps)
        founder_results[founder_id] = result
        final_states["founders"][founder_id] = result["state"]

        for transition in result["transitions"]:
            event_counter += 1
            events.append(
                _build_event(
                    event_counter=event_counter,
                    iteration=iteration,
                    actor_type="founder",
                    actor_id=founder_id,
                    transition=transition,
                )
            )

        if result["dropoff_reason"]:
            _increment_counter(dropoff_reasons, result["dropoff_reason"])

    for vc in vcs:
        vc_id = str(vc["id"])
        match_signal = match_by_vc.get(vc_id)
        preferred_founder_id = (match_signal or {}).get("founder_id")
        outreach_signal = _select_pair_signal(
            outreach_by_pair,
            str(preferred_founder_id) if preferred_founder_id else None,
            vc_id,
            fallback_signal=outreach_by_vc.get(vc_id),
        )

        agent = VCCustomerAgent(vc, params, rng)
        result = agent.simulate(match_signal, outreach_signal, max_steps=max_steps)
        vc_results[vc_id] = result
        final_states["vcs"][vc_id] = result["state"]

        for transition in result["transitions"]:
            event_counter += 1
            events.append(
                _build_event(
                    event_counter=event_counter,
                    iteration=iteration,
                    actor_type="vc",
                    actor_id=vc_id,
                    transition=transition,
                )
            )

        if result["dropoff_reason"]:
            _increment_counter(dropoff_reasons, result["dropoff_reason"])

    candidate_pairs = _candidate_pairs(match_signals)
    mutual_interest_pairs: List[Tuple[str, str]] = []
    for founder_id, vc_id in candidate_pairs:
        founder_interested = founder_results.get(founder_id, {}).get("interested", False)
        vc_interested = vc_results.get(vc_id, {}).get("interested", False)
        if founder_interested and vc_interested:
            mutual_interest_pairs.append((founder_id, vc_id))

    meeting_pairs: List[Tuple[str, str]] = []
    meeting_rate = float(params["meeting_rate_from_mutual_interest"])
    for founder_id, vc_id in mutual_interest_pairs:
        if rng.random() < meeting_rate:
            meeting_pairs.append((founder_id, vc_id))
            if final_states["founders"].get(founder_id) == "interested":
                transition = {
                    "from_state": "interested",
                    "to_state": "meeting",
                    "reason_code": "mutual_interest_meeting",
                    "score_snapshot": {
                        "meeting_rate_from_mutual_interest": meeting_rate,
                    },
                }
                event_counter += 1
                events.append(
                    _build_event(
                        event_counter=event_counter,
                        iteration=iteration,
                        actor_type="founder",
                        actor_id=founder_id,
                        transition=transition,
                    )
                )
                final_states["founders"][founder_id] = "meeting"

            if final_states["vcs"].get(vc_id) == "interested":
                transition = {
                    "from_state": "interested",
                    "to_state": "meeting",
                    "reason_code": "mutual_interest_meeting",
                    "score_snapshot": {
                        "meeting_rate_from_mutual_interest": meeting_rate,
                    },
                }
                event_counter += 1
                events.append(
                    _build_event(
                        event_counter=event_counter,
                        iteration=iteration,
                        actor_type="vc",
                        actor_id=vc_id,
                        transition=transition,
                    )
                )
                final_states["vcs"][vc_id] = "meeting"
        else:
            _increment_counter(dropoff_reasons, "mutual_interest_no_meeting")

    founders_in_mutual = {pair[0] for pair in mutual_interest_pairs}
    vcs_in_mutual = {pair[1] for pair in mutual_interest_pairs}
    for founder_id, state in final_states["founders"].items():
        if state == "interested" and founder_id not in founders_in_mutual:
            _increment_counter(dropoff_reasons, "founder_no_reciprocal_interest")
    for vc_id, state in final_states["vcs"].items():
        if state == "interested" and vc_id not in vcs_in_mutual:
            _increment_counter(dropoff_reasons, "vc_no_reciprocal_interest")

    global_match_relevance = _mean(
        [_clamp_signal_value(item.get("match_score")) for item in match_signals]
    )
    for visitor in visitors:
        visitor_id = str(visitor["id"])
        acquisition_signal = acquisition_by_visitor.get(visitor_id)
        agent = VisitorCustomerAgent(visitor, params, rng)
        result = agent.simulate(
            acquisition_signal=acquisition_signal,
            global_match_relevance=global_match_relevance,
            max_steps=max_steps,
        )
        final_states["visitors"][visitor_id] = result["state"]

        for transition in result["transitions"]:
            event_counter += 1
            events.append(
                _build_event(
                    event_counter=event_counter,
                    iteration=iteration,
                    actor_type="visitor",
                    actor_id=visitor_id,
                    transition=transition,
                )
            )

        if result["dropoff_reason"]:
            _increment_counter(dropoff_reasons, result["dropoff_reason"])

    metrics = _compute_environment_metrics(
        final_states=final_states,
        match_signals=match_signals,
        outreach_signals=outreach_signals,
        candidate_pairs=candidate_pairs,
        mutual_interest_pairs=mutual_interest_pairs,
        meeting_pairs=meeting_pairs,
    )

    return {
        "metrics": metrics,
        "events": events,
        "final_states": final_states,
        "diagnostics": {
            "dropoff_reasons": dict(sorted(dropoff_reasons.items())),
            "input_validation_errors": [],
        },
    }


def validate_customer_cohorts(payload: Dict[str, Any]) -> List[str]:
    """Validate customer seed cohorts and return a list of errors."""
    errors: List[str] = []

    if not isinstance(payload, dict):
        return ["Customer cohort payload must be a dictionary."]

    for cohort_key in COHORT_KEYS:
        cohort = payload.get(cohort_key)
        if cohort is None:
            errors.append(f"Missing required cohort key: '{cohort_key}'.")
            continue
        if not isinstance(cohort, list):
            errors.append(f"Cohort '{cohort_key}' must be a list.")
            continue

        seen_ids = set()
        required_fields = REQUIRED_FIELDS[cohort_key]

        for idx, profile in enumerate(cohort):
            item_path = f"{cohort_key}[{idx}]"
            if not isinstance(profile, dict):
                errors.append(f"{item_path} must be an object.")
                continue

            missing = sorted(required_fields.difference(profile.keys()))
            if missing:
                missing_str = ", ".join(missing)
                errors.append(f"{item_path} missing required fields: {missing_str}.")

            profile_id = profile.get("id")
            if not isinstance(profile_id, str) or not profile_id.strip():
                errors.append(f"{item_path}.id must be a non-empty string.")
            elif profile_id in seen_ids:
                errors.append(
                    f"Duplicate id '{profile_id}' in cohort '{cohort_key}'."
                )
            else:
                seen_ids.add(profile_id)

            if cohort_key == "vcs" and "thesis_sectors" in profile:
                thesis_sectors = profile.get("thesis_sectors")
                if not isinstance(thesis_sectors, list) or not thesis_sectors:
                    errors.append(
                        f"{item_path}.thesis_sectors must be a non-empty list."
                    )
                elif not all(
                    isinstance(sector, str) and sector.strip()
                    for sector in thesis_sectors
                ):
                    errors.append(
                        f"{item_path}.thesis_sectors must contain non-empty strings."
                    )

            for field in PROBABILITY_FIELDS[cohort_key]:
                if field not in profile:
                    continue
                value = profile[field]
                if not _is_probability(value):
                    errors.append(
                        f"{item_path}.{field} must be in [0.0, 1.0]."
                    )

    return errors


def load_customer_cohorts(seed_path: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Load, validate, and normalize customer cohorts from seed data."""
    resolved_path = Path(seed_path or settings.customer_seed_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"Customer seed file not found: {resolved_path}")

    with resolved_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    errors = validate_customer_cohorts(payload)
    if errors:
        error_lines = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"Invalid customer seed data:\n{error_lines}")

    return normalize_customer_cohorts(payload)


def normalize_customer_cohorts(payload: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Return a deterministic cohort representation sorted by profile id."""
    normalized: Dict[str, List[Dict[str, Any]]] = {}
    for cohort_key in COHORT_KEYS:
        cohort_list = payload.get(cohort_key, [])
        normalized_profiles: List[Dict[str, Any]] = []

        for profile in cohort_list:
            normalized_profile = dict(profile)
            if cohort_key == "vcs":
                thesis = normalized_profile.get("thesis_sectors", [])
                if isinstance(thesis, list):
                    normalized_profile["thesis_sectors"] = sorted(
                        dict.fromkeys(thesis)
                    )
            normalized_profiles.append(normalized_profile)

        normalized[cohort_key] = sorted(
            normalized_profiles,
            key=lambda profile: str(profile.get("id", "")),
        )

    return normalized


def build_customer_environment_input(
    run_id: str,
    iteration: int,
    seed: int,
    params: Dict[str, Any],
    seed_path: Optional[str] = None,
    signals: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Build a contract-compliant environment input object."""
    if iteration < 1:
        raise ValueError("iteration must be >= 1")

    cohorts = load_customer_cohorts(seed_path=seed_path)
    merged_signals: Dict[str, List[Dict[str, Any]]] = {key: [] for key in SIGNAL_KEYS}
    if signals:
        for key in SIGNAL_KEYS:
            value = signals.get(key, [])
            merged_signals[key] = list(value) if isinstance(value, list) else []

    return {
        "run_context": {
            "run_id": run_id,
            "iteration": iteration,
            "seed": seed,
        },
        "params": dict(params),
        "cohorts": cohorts,
        "signals": merged_signals,
    }


def merge_environment_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge runtime params over defaults and normalize value types."""
    merged = dict(DEFAULT_ENV_PARAMS)
    if params:
        for key, value in params.items():
            merged[key] = value

    normalized: Dict[str, Any] = {}
    for key, value in merged.items():
        if key == "max_steps_per_customer":
            normalized[key] = int(value)
        else:
            normalized[key] = float(value)

    return normalized


def validate_environment_input(environment_input: Dict[str, Any]) -> List[str]:
    """Validate full environment input object against the contract."""
    errors: List[str] = []

    if not isinstance(environment_input, dict):
        return ["Environment input must be a dictionary."]

    run_context = environment_input.get("run_context")
    if not isinstance(run_context, dict):
        errors.append("Missing or invalid 'run_context'.")
    else:
        run_id = run_context.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            errors.append("run_context.run_id must be a non-empty string.")

        iteration = run_context.get("iteration")
        if not isinstance(iteration, int) or iteration < 1:
            errors.append("run_context.iteration must be an integer >= 1.")

        seed = run_context.get("seed")
        if not isinstance(seed, int):
            errors.append("run_context.seed must be an integer.")

    params = environment_input.get("params")
    if not isinstance(params, dict):
        errors.append("Missing or invalid 'params'.")
    else:
        for key in CORE_PARAM_KEYS:
            if key not in params:
                errors.append(f"Missing required param: '{key}'.")

        numeric_params = dict(DEFAULT_ENV_PARAMS)
        numeric_params.update(params)
        for key, value in numeric_params.items():
            if key == "max_steps_per_customer":
                if not isinstance(value, int) or value < 1:
                    errors.append("params.max_steps_per_customer must be integer >= 1.")
                continue
            if not _is_probability(value):
                errors.append(f"params.{key} must be in [0.0, 1.0].")

    cohorts = environment_input.get("cohorts")
    if not isinstance(cohorts, dict):
        errors.append("Missing or invalid 'cohorts'.")
    else:
        errors.extend(validate_customer_cohorts(cohorts))

    signals = environment_input.get("signals")
    if not isinstance(signals, dict):
        errors.append("Missing or invalid 'signals'.")
    else:
        for key in SIGNAL_KEYS:
            value = signals.get(key)
            if value is None:
                errors.append(f"Missing signal bucket: '{key}'.")
                continue
            if not isinstance(value, list):
                errors.append(f"signals.{key} must be a list.")
                continue

            required_fields = SIGNAL_REQUIRED_FIELDS[key]
            for idx, signal in enumerate(value):
                signal_path = f"signals.{key}[{idx}]"
                if not isinstance(signal, dict):
                    errors.append(f"{signal_path} must be an object.")
                    continue
                missing_fields = sorted(required_fields.difference(signal.keys()))
                if missing_fields:
                    missing_str = ", ".join(missing_fields)
                    errors.append(
                        f"{signal_path} missing required fields: {missing_str}."
                    )
                    continue

                for field_name, field_value in signal.items():
                    if field_name.endswith("_id"):
                        if not isinstance(field_value, str) or not field_value.strip():
                            errors.append(
                                f"{signal_path}.{field_name} must be non-empty string."
                            )
                    elif field_name in {"match_score", "explanation_quality", "personalization_score",
                                        "timing_score", "article_relevance", "tool_usefulness", "cta_clarity"}:
                        if not _is_probability(field_value):
                            errors.append(
                                f"{signal_path}.{field_name} must be in [0.0, 1.0]."
                            )

    return errors


def _is_probability(value: Any) -> bool:
    """Return True when value is a valid probability in [0.0, 1.0]."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return 0.0 <= float(value) <= 1.0


def _safe_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    return default


def _empty_environment_output(iteration: int, errors: List[str]) -> Dict[str, Any]:
    return {
        "metrics": {
            "visitor_to_tool_use": 0.0,
            "tool_use_to_signup": 0.0,
            "signup_to_first_match": 0.0,
            "founder_interested_rate": 0.0,
            "vc_interested_rate": 0.0,
            "mutual_interest_rate": 0.0,
            "meeting_conversion_rate": 0.0,
            "average_match_relevance": 0.0,
            "explanation_coverage": 0.0,
            "personalization_quality_score": 0.0,
        },
        "events": [],
        "final_states": {"founders": {}, "vcs": {}, "visitors": {}},
        "diagnostics": {
            "dropoff_reasons": {},
            "input_validation_errors": sorted(errors),
        },
    }


def _build_event(
    event_counter: int,
    iteration: int,
    actor_type: str,
    actor_id: str,
    transition: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "event_id": f"event_{event_counter:06d}",
        "iteration": iteration,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "from_state": transition["from_state"],
        "to_state": transition["to_state"],
        "reason_code": transition["reason_code"],
        "score_snapshot": transition["score_snapshot"],
    }


def _best_signals_by_actor(
    signals: List[Dict[str, Any]],
    actor_key: str,
    quality_keys: Tuple[str, ...],
) -> Dict[str, Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}

    def ranking(signal: Dict[str, Any]) -> Tuple[Any, ...]:
        scores: List[float] = []
        for key in quality_keys:
            scores.append(_clamp_signal_value(signal.get(key)))
        # Secondary sort values ensure deterministic tie-breaks.
        founder_id = str(signal.get("founder_id", ""))
        vc_id = str(signal.get("vc_id", ""))
        return tuple(scores + [founder_id, vc_id])

    for signal in signals:
        actor_id = signal.get(actor_key)
        if not isinstance(actor_id, str) or not actor_id:
            continue
        current = best.get(actor_id)
        if current is None or ranking(signal) > ranking(current):
            best[actor_id] = signal

    return best


def _signals_by_pair(
    signals: List[Dict[str, Any]],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    pair_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for signal in signals:
        founder_id = signal.get("founder_id")
        vc_id = signal.get("vc_id")
        if not isinstance(founder_id, str) or not isinstance(vc_id, str):
            continue
        key = (founder_id, vc_id)
        existing = pair_map.get(key)
        if existing is None:
            pair_map[key] = signal
            continue

        current_quality = (
            _clamp_signal_value(existing.get("personalization_score")),
            _clamp_signal_value(existing.get("timing_score")),
        )
        new_quality = (
            _clamp_signal_value(signal.get("personalization_score")),
            _clamp_signal_value(signal.get("timing_score")),
        )
        if new_quality > current_quality:
            pair_map[key] = signal

    return pair_map


def _select_pair_signal(
    pair_map: Dict[Tuple[str, str], Dict[str, Any]],
    founder_id: Optional[str],
    vc_id: Optional[str],
    fallback_signal: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if founder_id and vc_id and (founder_id, vc_id) in pair_map:
        return pair_map[(founder_id, vc_id)]
    return fallback_signal


def _candidate_pairs(match_signals: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    pair_set = set()
    for signal in match_signals:
        founder_id = signal.get("founder_id")
        vc_id = signal.get("vc_id")
        if isinstance(founder_id, str) and isinstance(vc_id, str):
            pair_set.add((founder_id, vc_id))
    return sorted(pair_set)


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _clamp_signal_value(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return 0.0


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator / denominator)


def _increment_counter(counter: Dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _compute_environment_metrics(
    final_states: Dict[str, Dict[str, str]],
    match_signals: List[Dict[str, Any]],
    outreach_signals: List[Dict[str, Any]],
    candidate_pairs: List[Tuple[str, str]],
    mutual_interest_pairs: List[Tuple[str, str]],
    meeting_pairs: List[Tuple[str, str]],
) -> Dict[str, float]:
    visitor_states = list(final_states["visitors"].values())
    founder_states = list(final_states["founders"].values())
    vc_states = list(final_states["vcs"].values())

    tool_use_count = sum(
        state in {"tool_use", "signup", "first_match"} for state in visitor_states
    )
    signup_count = sum(state in {"signup", "first_match"} for state in visitor_states)
    first_match_count = sum(state == "first_match" for state in visitor_states)

    founder_interested = sum(
        state in {"interested", "meeting"} for state in founder_states
    )
    vc_interested = sum(state in {"interested", "meeting"} for state in vc_states)

    match_scores = [_clamp_signal_value(item.get("match_score")) for item in match_signals]
    explanation_scores = [
        _clamp_signal_value(item.get("explanation_quality")) for item in match_signals
    ]
    personalization_scores = [
        _clamp_signal_value(item.get("personalization_score")) for item in outreach_signals
    ]

    explanation_covered = sum(score > 0.0 for score in explanation_scores)

    return {
        "visitor_to_tool_use": _safe_rate(tool_use_count, len(visitor_states)),
        "tool_use_to_signup": _safe_rate(signup_count, tool_use_count),
        "signup_to_first_match": _safe_rate(first_match_count, signup_count),
        "founder_interested_rate": _safe_rate(founder_interested, len(founder_states)),
        "vc_interested_rate": _safe_rate(vc_interested, len(vc_states)),
        "mutual_interest_rate": _safe_rate(
            len(mutual_interest_pairs), len(candidate_pairs)
        ),
        "meeting_conversion_rate": _safe_rate(
            len(meeting_pairs), len(mutual_interest_pairs)
        ),
        "average_match_relevance": _mean(match_scores),
        "explanation_coverage": _safe_rate(explanation_covered, len(match_signals)),
        "personalization_quality_score": _mean(personalization_scores),
    }
