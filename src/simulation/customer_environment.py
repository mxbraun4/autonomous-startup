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
from src.simulation.customer_event_instrumentation import (
    derive_signup_signal_overrides_from_events,
)
from src.simulation.customer_explanation_quality import ExplanationQualityEvaluator
from src.simulation.customer_feedback import CustomerFeedbackGenerator
from src.simulation.customer_personalization_quality import PersonalizationScoreEvaluator
from src.utils.config import settings

REQUIRED_COHORT_KEYS = ("founders", "vcs")
OPTIONAL_COHORT_KEYS = ("visitors",)
COHORT_KEYS = REQUIRED_COHORT_KEYS + OPTIONAL_COHORT_KEYS
CORE_PARAM_KEYS = (
    "founder_base_interest",
    "vc_base_interest",
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
    "founders": {
        "urgency_score",
        "trust_score",
        "form_complexity_score",
        "channel_intent_fit",
        "proof_of_outcomes",
    },
    "vcs": {"confidence_threshold"},
    "visitors": {"tool_need_score", "cta_friction"},
}

REQUIRED_SIGNAL_KEYS = ()
OPTIONAL_SIGNAL_KEYS = ("match_signals", "outreach_signals", "acquisition_signals")
SIGNAL_KEYS = REQUIRED_SIGNAL_KEYS + OPTIONAL_SIGNAL_KEYS
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
    "founder_signup_base_rate": 0.70,
    "vc_signup_base_rate": 0.66,
    "founder_signup_cta_clarity": 0.72,
    "vc_signup_cta_clarity": 0.68,
    "founder_signup_friction": 0.30,
    "vc_signup_friction": 0.33,
    "founder_signup_trust_score": 1.0,
    "founder_signup_form_complexity": 0.0,
    "founder_signup_channel_intent_fit": 1.0,
    "founder_signup_proof_of_outcomes": 1.0,
    "visitor_tool_click_rate": 0.20,
    "signup_rate_from_tool": 0.10,
    "meeting_rate_from_mutual_interest": 0.35,
    "match_score_threshold": 0.50,
    "vc_match_score_threshold": 0.55,
    "shortlist_threshold": 0.55,
    "interest_threshold": 0.40,
    "derived_match_score_boost": 0.0,
    "derived_explanation_quality_boost": 0.0,
    "derived_personalization_score_boost": 0.0,
    "derived_timing_score_boost": 0.0,
    "llm_explanation_blend_weight": 0.60,
    "llm_personalization_blend_weight": 0.60,
    "max_steps_per_customer": 5,
}

_DEFAULT_MATCH_COMPONENT_WEIGHTS = {
    "sector": 0.52,
    "stage": 0.30,
    "geo": 0.13,
    "fundraising": 0.05,
}
_MATCH_COMPONENT_KEYS = ("sector", "stage", "geo", "fundraising")

_SECTOR_RELATEDNESS = {
    "fintech": {"ai_ml", "devtools"},
    "healthtech": {"biotech", "ai_ml"},
    "biotech": {"healthtech"},
    "ai_ml": {"fintech", "healthtech", "devtools", "cybersecurity"},
    "devtools": {"ai_ml", "cybersecurity", "fintech"},
    "cybersecurity": {"devtools", "ai_ml"},
    "climate": {"energy", "cleantech"},
    "energy": {"climate", "cleantech"},
    "edtech": {"future_of_work"},
    "future_of_work": {"edtech"},
}

_STAGE_ADJACENCY = {
    "seed": {"pre_seed", "series_a"},
    "series_a": {"seed", "series_b"},
    "series_b": {"series_a", "series_c"},
    "series_c": {"series_b", "growth"},
    "growth": {"series_c"},
}

_COUNTRY_TO_REGION = {
    "germany": "europe",
    "united_kingdom": "europe",
    "france": "europe",
    "spain": "europe",
    "italy": "europe",
    "netherlands": "europe",
    "sweden": "europe",
    "switzerland": "europe",
    "austria": "europe",
    "united_states": "north_america",
    "usa": "north_america",
    "us": "north_america",
    "canada": "north_america",
    "mexico": "north_america",
    "israel": "middle_east",
}

_REGION_ALIASES = {
    "eu": "europe",
    "europe": "europe",
    "european_union": "europe",
    "north_america": "north_america",
    "middle_east": "middle_east",
    "global": "global",
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
    llm_feedback_enabled = _safe_bool(run_context.get("use_llm_feedback"), default=False)
    llm_feedback_steps = _safe_string_list(run_context.get("llm_feedback_steps"))
    llm_feedback_model = str(run_context.get("llm_feedback_model", "claude-3-haiku-20240307"))
    llm_feedback_temperature = _safe_float(
        run_context.get("llm_feedback_temperature"),
        default=0.0,
    )
    use_llm_explanation_quality = _safe_bool(
        run_context.get("use_llm_explanation_quality"),
        default=False,
    )
    llm_explanation_model = str(
        run_context.get("llm_explanation_model", llm_feedback_model)
    )
    llm_explanation_temperature = _safe_float(
        run_context.get("llm_explanation_temperature"),
        default=0.0,
    )
    use_llm_personalization_score = _safe_bool(
        run_context.get("use_llm_personalization_score"),
        default=False,
    )
    llm_personalization_model = str(
        run_context.get("llm_personalization_model", llm_feedback_model)
    )
    llm_personalization_temperature = _safe_float(
        run_context.get("llm_personalization_temperature"),
        default=0.0,
    )
    match_calibration_path = run_context.get("match_calibration_path")
    match_calibration_min_samples = _safe_int(
        run_context.get("match_calibration_min_samples"),
        default=20,
    )
    product_surface_only = _safe_bool(
        run_context.get("product_surface_only"),
        default=False,
    )
    feedback_generator = CustomerFeedbackGenerator(
        use_llm=llm_feedback_enabled,
        llm_steps=llm_feedback_steps,
        llm_model=llm_feedback_model,
        llm_temperature=llm_feedback_temperature,
    )

    input_match_signals = [dict(item) for item in signals.get("match_signals", [])]
    input_outreach_signals = [dict(item) for item in signals.get("outreach_signals", [])]
    acquisition_signals = [dict(item) for item in signals.get("acquisition_signals", [])]

    founders = sorted(cohorts["founders"], key=lambda item: str(item.get("id", "")))
    vcs = sorted(cohorts["vcs"], key=lambda item: str(item.get("id", "")))
    visitors = sorted(cohorts["visitors"], key=lambda item: str(item.get("id", "")))
    explanation_quality_evaluator = ExplanationQualityEvaluator(
        use_llm=use_llm_explanation_quality,
        llm_model=llm_explanation_model,
        llm_temperature=llm_explanation_temperature,
        llm_blend_weight=_clamp_signal_value(params.get("llm_explanation_blend_weight")),
    )
    match_component_weights, match_calibration_diagnostics = _resolve_match_component_weights(
        calibration_path=match_calibration_path,
        min_samples=match_calibration_min_samples,
    )
    match_signals = _derive_match_signals_from_data(
        founders,
        vcs,
        params,
        match_component_weights=match_component_weights,
        explanation_quality_evaluator=explanation_quality_evaluator,
    )
    personalization_score_evaluator = PersonalizationScoreEvaluator(
        use_llm=use_llm_personalization_score,
        llm_model=llm_personalization_model,
        llm_temperature=llm_personalization_temperature,
        llm_blend_weight=_clamp_signal_value(params.get("llm_personalization_blend_weight")),
    )
    outreach_signals = _derive_outreach_signals_from_data(
        founders=founders,
        vcs=vcs,
        params=params,
        match_signals=match_signals,
        personalization_score_evaluator=personalization_score_evaluator,
    )

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
    failure_feedback: List[Dict[str, Any]] = []
    interaction_logs: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        "founders": {},
        "vcs": {},
        "visitors": {},
    }

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
        _append_actor_interactions(
            actor_type="founder",
            actor_id=founder_id,
            interactions=result.get("interaction_trace", []),
            iteration=iteration,
            interaction_logs=interaction_logs,
            failure_feedback=failure_feedback,
            feedback_generator=feedback_generator,
        )

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
        _append_actor_interactions(
            actor_type="vc",
            actor_id=vc_id,
            interactions=result.get("interaction_trace", []),
            iteration=iteration,
            interaction_logs=interaction_logs,
            failure_feedback=failure_feedback,
            feedback_generator=feedback_generator,
        )

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
                _append_actor_interactions(
                    actor_type="founder",
                    actor_id=founder_id,
                    interactions=[
                        {
                            "step_id": "interested_to_meeting",
                            "interaction": "confirm_intro_meeting",
                            "decision_mode": "cross_actor_probabilistic",
                            "outcome": "passed",
                            "reason_code": "mutual_interest_meeting",
                            "score_snapshot": {
                                "meeting_rate_from_mutual_interest": meeting_rate,
                            },
                        }
                    ],
                    iteration=iteration,
                    interaction_logs=interaction_logs,
                    failure_feedback=failure_feedback,
                    feedback_generator=feedback_generator,
                )

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
                _append_actor_interactions(
                    actor_type="vc",
                    actor_id=vc_id,
                    interactions=[
                        {
                            "step_id": "interested_to_meeting",
                            "interaction": "confirm_intro_meeting",
                            "decision_mode": "cross_actor_probabilistic",
                            "outcome": "passed",
                            "reason_code": "mutual_interest_meeting",
                            "score_snapshot": {
                                "meeting_rate_from_mutual_interest": meeting_rate,
                            },
                        }
                    ],
                    iteration=iteration,
                    interaction_logs=interaction_logs,
                    failure_feedback=failure_feedback,
                    feedback_generator=feedback_generator,
                )
        else:
            _increment_counter(dropoff_reasons, "mutual_interest_no_meeting")
            _append_actor_interactions(
                actor_type="founder",
                actor_id=founder_id,
                interactions=[
                    {
                        "step_id": "interested_to_meeting",
                        "interaction": "confirm_intro_meeting",
                        "decision_mode": "cross_actor_probabilistic",
                        "outcome": "failed",
                        "reason_code": "mutual_interest_no_meeting",
                        "score_snapshot": {
                            "meeting_rate_from_mutual_interest": meeting_rate,
                        },
                    }
                ],
                iteration=iteration,
                interaction_logs=interaction_logs,
                failure_feedback=failure_feedback,
                feedback_generator=feedback_generator,
            )
            _append_actor_interactions(
                actor_type="vc",
                actor_id=vc_id,
                interactions=[
                    {
                        "step_id": "interested_to_meeting",
                        "interaction": "confirm_intro_meeting",
                        "decision_mode": "cross_actor_probabilistic",
                        "outcome": "failed",
                        "reason_code": "mutual_interest_no_meeting",
                        "score_snapshot": {
                            "meeting_rate_from_mutual_interest": meeting_rate,
                        },
                    }
                ],
                iteration=iteration,
                interaction_logs=interaction_logs,
                failure_feedback=failure_feedback,
                feedback_generator=feedback_generator,
            )

    founders_in_mutual = {pair[0] for pair in mutual_interest_pairs}
    vcs_in_mutual = {pair[1] for pair in mutual_interest_pairs}
    for founder_id, state in final_states["founders"].items():
        if state == "interested" and founder_id not in founders_in_mutual:
            _increment_counter(dropoff_reasons, "founder_no_reciprocal_interest")
            _append_actor_interactions(
                actor_type="founder",
                actor_id=founder_id,
                interactions=[
                    {
                        "step_id": "interested_to_meeting",
                        "interaction": "confirm_intro_meeting",
                        "decision_mode": "cross_actor_gate",
                        "outcome": "failed",
                        "reason_code": "founder_no_reciprocal_interest",
                        "score_snapshot": {
                            "mutual_interest_candidates": len(mutual_interest_pairs),
                        },
                    }
                ],
                iteration=iteration,
                interaction_logs=interaction_logs,
                failure_feedback=failure_feedback,
                feedback_generator=feedback_generator,
            )
    for vc_id, state in final_states["vcs"].items():
        if state == "interested" and vc_id not in vcs_in_mutual:
            _increment_counter(dropoff_reasons, "vc_no_reciprocal_interest")
            _append_actor_interactions(
                actor_type="vc",
                actor_id=vc_id,
                interactions=[
                    {
                        "step_id": "interested_to_meeting",
                        "interaction": "confirm_intro_meeting",
                        "decision_mode": "cross_actor_gate",
                        "outcome": "failed",
                        "reason_code": "vc_no_reciprocal_interest",
                        "score_snapshot": {
                            "mutual_interest_candidates": len(mutual_interest_pairs),
                        },
                    }
                ],
                iteration=iteration,
                interaction_logs=interaction_logs,
                failure_feedback=failure_feedback,
                feedback_generator=feedback_generator,
            )

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
        interaction_logs["visitors"][visitor_id] = []

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

    product_surface = {
        "events": _sanitize_events_for_product_surface(events),
        "interaction_logs": _sanitize_interaction_logs_for_product_surface(interaction_logs),
        "failure_feedback": _sanitize_failure_feedback_for_product_surface(failure_feedback),
    }
    output_events = events if not product_surface_only else product_surface["events"]
    output_interaction_logs = (
        interaction_logs if not product_surface_only else product_surface["interaction_logs"]
    )
    output_failure_feedback = (
        failure_feedback if not product_surface_only else product_surface["failure_feedback"]
    )
    event_instrumentation = run_context.get("event_instrumentation", {})
    if product_surface_only:
        event_instrumentation = _sanitize_event_instrumentation_for_product_surface(
            event_instrumentation
        )

    return {
        "metrics": metrics,
        "events": output_events,
        "final_states": final_states,
        "diagnostics": {
            "dropoff_reasons": dict(sorted(dropoff_reasons.items())),
            "input_validation_errors": [],
            "interaction_logs": output_interaction_logs,
            "failure_feedback": output_failure_feedback,
            "llm_feedback_requested": llm_feedback_enabled,
            "llm_feedback_active": feedback_generator.llm_active,
            "llm_feedback_steps": sorted(feedback_generator.llm_steps),
            "llm_explanation_quality_requested": use_llm_explanation_quality,
            "llm_explanation_quality_active": explanation_quality_evaluator.llm_active,
            "llm_explanation_quality": explanation_quality_evaluator.diagnostics(),
            "llm_personalization_score_requested": use_llm_personalization_score,
            "llm_personalization_score_active": personalization_score_evaluator.llm_active,
            "llm_personalization_score": personalization_score_evaluator.diagnostics(),
            "match_signal_source": "derived_from_cohort_data",
            "input_match_signal_count": len(input_match_signals),
            "derived_match_signal_count": len(match_signals),
            "outreach_signal_source": "derived_from_product_perception",
            "input_outreach_signal_count": len(input_outreach_signals),
            "derived_outreach_signal_count": len(outreach_signals),
            "match_calibration": match_calibration_diagnostics,
            "feedback_contract_version": feedback_generator.contract_version,
            "event_instrumentation": event_instrumentation,
            "product_surface_only": product_surface_only,
            "product_surface": product_surface,
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
            if cohort_key in REQUIRED_COHORT_KEYS:
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

            signup_payload = profile.get("signup_payload")
            if signup_payload is not None:
                if not isinstance(signup_payload, dict):
                    errors.append(f"{item_path}.signup_payload must be an object when provided.")
                else:
                    for field_name in signup_payload.keys():
                        if not isinstance(field_name, str) or not field_name.strip():
                            errors.append(
                                f"{item_path}.signup_payload contains an invalid field name."
                            )
                            break

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
    include_visitors: bool = False,
    use_llm_feedback: bool = False,
    llm_feedback_steps: Optional[List[str]] = None,
    use_llm_explanation_quality: bool = False,
    llm_explanation_model: str = "claude-3-haiku-20240307",
    llm_explanation_temperature: float = 0.0,
    use_llm_personalization_score: bool = False,
    llm_personalization_model: str = "claude-3-haiku-20240307",
    llm_personalization_temperature: float = 0.0,
    match_calibration_path: Optional[str] = None,
    match_calibration_min_samples: int = 20,
    product_events: Optional[List[Dict[str, Any]]] = None,
    product_surface_only: bool = False,
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

    if not include_visitors:
        cohorts["visitors"] = []
        merged_signals["acquisition_signals"] = []

    resolved_params = dict(params)
    instrumentation_summary: Dict[str, Any] = {
        "enabled": False,
        "scoring_formula_version": 0,
        "event_count": 0,
        "founder_event_count": 0,
        "tracked_event_count": 0,
        "event_type_counts": {},
        "founder_signal_coverage": {},
        "founder_scores": {},
        "founder_signal_sources": {},
        "founder_signal_inputs": {},
        "param_overrides": {},
        "param_sources": {},
        "effective_global_signup_params": {},
    }
    if product_events is not None:
        defaulted_params = dict(DEFAULT_ENV_PARAMS)
        defaulted_params.update(resolved_params)
        instrumentation = derive_signup_signal_overrides_from_events(
            events=product_events,
            founders=cohorts.get("founders", []),
            default_params=defaulted_params,
        )

        resolved_params.update(instrumentation["param_overrides"])
        founder_profile_overrides = instrumentation["founder_profile_overrides"]
        for founder in cohorts.get("founders", []):
            founder_id = founder.get("id")
            if not isinstance(founder_id, str):
                continue
            profile_override = founder_profile_overrides.get(founder_id)
            if isinstance(profile_override, dict):
                founder.update(profile_override)

        instrumentation_summary = {
            "enabled": True,
            **instrumentation["diagnostics"],
        }

    return {
        "run_context": {
            "run_id": run_id,
            "iteration": iteration,
            "seed": seed,
            "use_llm_feedback": bool(use_llm_feedback),
            "llm_feedback_steps": list(llm_feedback_steps or []),
            "use_llm_explanation_quality": bool(use_llm_explanation_quality),
            "llm_explanation_model": str(llm_explanation_model),
            "llm_explanation_temperature": float(llm_explanation_temperature),
            "use_llm_personalization_score": bool(use_llm_personalization_score),
            "llm_personalization_model": str(llm_personalization_model),
            "llm_personalization_temperature": float(llm_personalization_temperature),
            "match_calibration_path": (
                str(match_calibration_path)
                if isinstance(match_calibration_path, str) and match_calibration_path.strip()
                else None
            ),
            "match_calibration_min_samples": (
                int(match_calibration_min_samples)
                if isinstance(match_calibration_min_samples, int)
                else 20
            ),
            "product_surface_only": bool(product_surface_only),
            "event_instrumentation": instrumentation_summary,
        },
        "params": resolved_params,
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

        use_llm_feedback = run_context.get("use_llm_feedback")
        if use_llm_feedback is not None and not isinstance(use_llm_feedback, bool):
            errors.append("run_context.use_llm_feedback must be boolean when provided.")

        llm_feedback_steps = run_context.get("llm_feedback_steps")
        if llm_feedback_steps is not None:
            if not isinstance(llm_feedback_steps, list) or not all(
                isinstance(step, str) and step.strip() for step in llm_feedback_steps
            ):
                errors.append(
                    "run_context.llm_feedback_steps must be a list of non-empty strings."
                )

        product_surface_only = run_context.get("product_surface_only")
        if product_surface_only is not None and not isinstance(product_surface_only, bool):
            errors.append(
                "run_context.product_surface_only must be boolean when provided."
            )

        llm_feedback_temperature = run_context.get("llm_feedback_temperature")
        if llm_feedback_temperature is not None and not _is_probability(
            llm_feedback_temperature
        ):
            errors.append(
                "run_context.llm_feedback_temperature must be in [0.0, 1.0] when provided."
            )

        use_llm_explanation_quality = run_context.get("use_llm_explanation_quality")
        if use_llm_explanation_quality is not None and not isinstance(
            use_llm_explanation_quality, bool
        ):
            errors.append(
                "run_context.use_llm_explanation_quality must be boolean when provided."
            )

        llm_explanation_model = run_context.get("llm_explanation_model")
        if llm_explanation_model is not None and (
            not isinstance(llm_explanation_model, str) or not llm_explanation_model.strip()
        ):
            errors.append(
                "run_context.llm_explanation_model must be a non-empty string when provided."
            )

        llm_explanation_temperature = run_context.get("llm_explanation_temperature")
        if llm_explanation_temperature is not None and not _is_probability(
            llm_explanation_temperature
        ):
            errors.append(
                "run_context.llm_explanation_temperature must be in [0.0, 1.0] when provided."
            )

        use_llm_personalization_score = run_context.get("use_llm_personalization_score")
        if use_llm_personalization_score is not None and not isinstance(
            use_llm_personalization_score, bool
        ):
            errors.append(
                "run_context.use_llm_personalization_score must be boolean when provided."
            )

        llm_personalization_model = run_context.get("llm_personalization_model")
        if llm_personalization_model is not None and (
            not isinstance(llm_personalization_model, str)
            or not llm_personalization_model.strip()
        ):
            errors.append(
                "run_context.llm_personalization_model must be a non-empty string when provided."
            )

        llm_personalization_temperature = run_context.get(
            "llm_personalization_temperature"
        )
        if llm_personalization_temperature is not None and not _is_probability(
            llm_personalization_temperature
        ):
            errors.append(
                "run_context.llm_personalization_temperature must be in [0.0, 1.0] when provided."
            )

        match_calibration_path = run_context.get("match_calibration_path")
        if match_calibration_path is not None and (
            not isinstance(match_calibration_path, str) or not match_calibration_path.strip()
        ):
            errors.append(
                "run_context.match_calibration_path must be a non-empty string when provided."
            )

        match_calibration_min_samples = run_context.get("match_calibration_min_samples")
        if match_calibration_min_samples is not None and (
            not isinstance(match_calibration_min_samples, int)
            or match_calibration_min_samples < 1
        ):
            errors.append(
                "run_context.match_calibration_min_samples must be an integer >= 1 when provided."
            )

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
                if key in REQUIRED_SIGNAL_KEYS:
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


def _safe_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _safe_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    cleaned: List[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                cleaned.append(text)
    return cleaned


def _interaction_bucket_key(actor_type: str) -> str:
    if actor_type == "founder":
        return "founders"
    if actor_type == "vc":
        return "vcs"
    return "visitors"


def _append_actor_interactions(
    actor_type: str,
    actor_id: str,
    interactions: Any,
    iteration: int,
    interaction_logs: Dict[str, Dict[str, List[Dict[str, Any]]]],
    failure_feedback: List[Dict[str, Any]],
    feedback_generator: CustomerFeedbackGenerator,
) -> None:
    if not isinstance(interactions, list):
        return

    bucket = _interaction_bucket_key(actor_type)
    actor_log = interaction_logs[bucket].setdefault(actor_id, [])

    for item in interactions:
        if not isinstance(item, dict):
            continue

        interaction = dict(item)
        feedback = feedback_generator.render_feedback(actor_type, actor_id, interaction)
        interaction["feedback_to_system"] = feedback["message"]
        interaction["feedback_source"] = feedback["source"]
        interaction["feedback_category"] = feedback.get("category")
        interaction["feedback_action_hint"] = feedback.get("action_hint")
        interaction["feedback_contract_version"] = feedback.get("contract_version")
        actor_log.append(interaction)

        if interaction.get("outcome") != "failed":
            continue

        failure_feedback.append(
            {
                "iteration": iteration,
                "actor_type": actor_type,
                "actor_id": actor_id,
                "step_id": interaction.get("step_id"),
                "reason_code": interaction.get("reason_code"),
                "feedback_to_system": interaction["feedback_to_system"],
                "feedback_source": interaction["feedback_source"],
                "feedback_category": interaction.get("feedback_category"),
                "feedback_action_hint": interaction.get("feedback_action_hint"),
                "feedback_contract_version": interaction.get("feedback_contract_version"),
                "score_snapshot": interaction.get("score_snapshot", {}),
            }
        )


def _sanitize_events_for_product_surface(events: Any) -> List[Dict[str, Any]]:
    if not isinstance(events, list):
        return []
    sanitized: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        sanitized.append(
            {
                "event_id": event.get("event_id"),
                "iteration": event.get("iteration"),
                "actor_type": event.get("actor_type"),
                "actor_id": event.get("actor_id"),
                "from_state": event.get("from_state"),
                "to_state": event.get("to_state"),
                "reason_code": event.get("reason_code"),
            }
        )
    return sanitized


def _sanitize_interaction_logs_for_product_surface(
    interaction_logs: Any,
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    empty = {"founders": {}, "vcs": {}, "visitors": {}}
    if not isinstance(interaction_logs, dict):
        return empty

    sanitized: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for bucket in ("founders", "vcs", "visitors"):
        actors = interaction_logs.get(bucket)
        if not isinstance(actors, dict):
            sanitized[bucket] = {}
            continue

        actor_payload: Dict[str, List[Dict[str, Any]]] = {}
        for actor_id, entries in actors.items():
            if not isinstance(actor_id, str):
                continue
            if not isinstance(entries, list):
                continue

            clean_entries: List[Dict[str, Any]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                clean_entries.append(
                    {
                        "step_id": entry.get("step_id"),
                        "interaction": entry.get("interaction"),
                        "decision_mode": entry.get("decision_mode"),
                        "outcome": entry.get("outcome"),
                        "reason_code": entry.get("reason_code"),
                        "feedback_to_system": entry.get("feedback_to_system"),
                        "feedback_source": entry.get("feedback_source"),
                        "feedback_category": entry.get("feedback_category"),
                        "feedback_action_hint": entry.get("feedback_action_hint"),
                        "feedback_contract_version": entry.get("feedback_contract_version"),
                    }
                )
            actor_payload[actor_id] = clean_entries
        sanitized[bucket] = actor_payload

    return sanitized


def _sanitize_failure_feedback_for_product_surface(
    failure_feedback: Any,
) -> List[Dict[str, Any]]:
    if not isinstance(failure_feedback, list):
        return []
    sanitized: List[Dict[str, Any]] = []
    for item in failure_feedback:
        if not isinstance(item, dict):
            continue
        sanitized.append(
            {
                "iteration": item.get("iteration"),
                "actor_type": item.get("actor_type"),
                "actor_id": item.get("actor_id"),
                "step_id": item.get("step_id"),
                "reason_code": item.get("reason_code"),
                "feedback_to_system": item.get("feedback_to_system"),
                "feedback_source": item.get("feedback_source"),
                "feedback_category": item.get("feedback_category"),
                "feedback_action_hint": item.get("feedback_action_hint"),
                "feedback_contract_version": item.get("feedback_contract_version"),
            }
        )
    return sanitized


def _sanitize_event_instrumentation_for_product_surface(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "enabled": False,
            "event_count": 0,
            "founder_event_count": 0,
            "tracked_event_count": 0,
            "event_type_counts": {},
        }

    event_type_counts = payload.get("event_type_counts")
    if not isinstance(event_type_counts, dict):
        event_type_counts = {}

    return {
        "enabled": bool(payload.get("enabled", False)),
        "event_count": _safe_int(payload.get("event_count"), 0),
        "founder_event_count": _safe_int(payload.get("founder_event_count"), 0),
        "tracked_event_count": _safe_int(payload.get("tracked_event_count"), 0),
        "scoring_formula_version": _safe_int(payload.get("scoring_formula_version"), 0),
        "event_type_counts": dict(event_type_counts),
    }


def _empty_environment_output(iteration: int, errors: List[str]) -> Dict[str, Any]:
    return {
        "metrics": {
            "founder_visit_to_signup": 0.0,
            "vc_visit_to_signup": 0.0,
            "founder_engaged_to_matched_rate": 0.0,
            "vc_engaged_to_matched_rate": 0.0,
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
            "interaction_logs": {"founders": {}, "vcs": {}, "visitors": {}},
            "failure_feedback": [],
            "llm_feedback_requested": False,
            "llm_feedback_active": False,
            "llm_feedback_steps": [],
            "llm_explanation_quality_requested": False,
            "llm_explanation_quality_active": False,
            "llm_explanation_quality": {},
            "llm_personalization_score_requested": False,
            "llm_personalization_score_active": False,
            "llm_personalization_score": {},
            "match_signal_source": "derived_from_cohort_data",
            "input_match_signal_count": 0,
            "derived_match_signal_count": 0,
            "outreach_signal_source": "derived_from_product_perception",
            "input_outreach_signal_count": 0,
            "derived_outreach_signal_count": 0,
            "match_calibration": {
                "requested": False,
                "active": False,
                "path": None,
                "min_samples": 0,
                "valid_samples": 0,
                "invalid_samples": 0,
                "weights_before": dict(_DEFAULT_MATCH_COMPONENT_WEIGHTS),
                "weights_after": dict(_DEFAULT_MATCH_COMPONENT_WEIGHTS),
                "loss_before": None,
                "loss_after": None,
                "reason": "not_requested",
            },
            "feedback_contract_version": 0,
            "product_surface_only": False,
            "event_instrumentation": {
                "enabled": False,
                "scoring_formula_version": 0,
                "event_count": 0,
                "founder_event_count": 0,
                "tracked_event_count": 0,
                "event_type_counts": {},
                "founder_signal_coverage": {},
                "founder_scores": {},
                "founder_signal_sources": {},
                "founder_signal_inputs": {},
                "param_overrides": {},
                "param_sources": {},
                "effective_global_signup_params": {},
            },
            "product_surface": {
                "events": [],
                "interaction_logs": {"founders": {}, "vcs": {}, "visitors": {}},
                "failure_feedback": [],
            },
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


def _normalize_match_component_weights(
    weights: Optional[Dict[str, Any]]
) -> Dict[str, float]:
    """Return non-negative normalized component weights that sum to 1.0."""
    base = dict(_DEFAULT_MATCH_COMPONENT_WEIGHTS)
    if not isinstance(weights, dict):
        return base

    resolved: Dict[str, float] = {}
    for key in _MATCH_COMPONENT_KEYS:
        value = _clamp_signal_value(weights.get(key))
        resolved[key] = max(0.0, float(value))

    total = sum(resolved.values())
    if total <= 0.0:
        return base

    return {key: resolved[key] / total for key in _MATCH_COMPONENT_KEYS}


def _resolve_match_component_weights(
    calibration_path: Any,
    min_samples: int,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Load optional labeled outcomes and calibrate match component weights."""
    default_weights = dict(_DEFAULT_MATCH_COMPONENT_WEIGHTS)
    normalized_defaults = _normalize_match_component_weights(default_weights)

    requested = isinstance(calibration_path, str) and bool(calibration_path.strip())
    resolved_min_samples = max(1, int(min_samples))
    diagnostics: Dict[str, Any] = {
        "requested": requested,
        "active": False,
        "path": calibration_path if isinstance(calibration_path, str) else None,
        "min_samples": resolved_min_samples,
        "valid_samples": 0,
        "invalid_samples": 0,
        "weights_before": normalized_defaults,
        "weights_after": normalized_defaults,
        "loss_before": None,
        "loss_after": None,
        "reason": "not_requested",
    }

    if not requested:
        return normalized_defaults, diagnostics

    path_text = str(calibration_path).strip()
    diagnostics["path"] = path_text
    path = Path(path_text)
    if not path.exists():
        diagnostics["reason"] = "file_not_found"
        return normalized_defaults, diagnostics

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        diagnostics["reason"] = "invalid_json"
        return normalized_defaults, diagnostics

    rows, labels, invalid_samples = _load_match_calibration_samples(payload)
    diagnostics["valid_samples"] = len(rows)
    diagnostics["invalid_samples"] = invalid_samples
    if len(rows) < resolved_min_samples:
        diagnostics["reason"] = "insufficient_samples"
        return normalized_defaults, diagnostics

    learned, loss_before, loss_after = _fit_match_component_weights(
        rows=rows,
        labels=labels,
        default_weights=normalized_defaults,
        l2_strength=0.10,
        learning_rate=0.20,
        steps=350,
    )
    learned = _normalize_match_component_weights(learned)

    diagnostics["active"] = True
    diagnostics["reason"] = "calibrated_from_labeled_outcomes"
    diagnostics["weights_after"] = learned
    diagnostics["loss_before"] = loss_before
    diagnostics["loss_after"] = loss_after
    return learned, diagnostics


def _load_match_calibration_samples(
    payload: Any,
) -> Tuple[List[Tuple[float, float, float, float]], List[float], int]:
    """Return model rows and labels from calibration payload."""
    samples: Any
    if isinstance(payload, dict):
        samples = payload.get("samples", [])
    elif isinstance(payload, list):
        samples = payload
    else:
        return [], [], 0

    if not isinstance(samples, list):
        return [], [], 0

    rows: List[Tuple[float, float, float, float]] = []
    labels: List[float] = []
    invalid_samples = 0
    for sample in samples:
        row, label = _extract_match_calibration_row(sample)
        if row is None or label is None:
            invalid_samples += 1
            continue
        rows.append(row)
        labels.append(label)

    return rows, labels, invalid_samples


def _extract_match_calibration_row(
    sample: Any,
) -> Tuple[Optional[Tuple[float, float, float, float]], Optional[float]]:
    if not isinstance(sample, dict):
        return None, None

    label = _extract_match_calibration_outcome(sample)
    if label is None:
        return None, None

    feature_scores = sample.get("feature_scores")
    if isinstance(feature_scores, dict):
        row = (
            _clamp_signal_value(feature_scores.get("sector_score")),
            _clamp_signal_value(feature_scores.get("stage_score")),
            _clamp_signal_value(feature_scores.get("geo_score")),
            _clamp_signal_value(feature_scores.get("fundraising_score")),
        )
        return row, label

    founder = sample.get("founder")
    vc = sample.get("vc")
    if not isinstance(founder, dict) or not isinstance(vc, dict):
        return None, None

    row = (
        _sector_alignment_score(
            founder_sector=founder.get("sector"),
            vc_sectors=vc.get("thesis_sectors"),
        ),
        _stage_alignment_score(
            founder_stage=founder.get("stage"),
            vc_stage=vc.get("stage_focus"),
        ),
        _geography_alignment_score(
            founder_geo=founder.get("geography"),
            vc_geo=vc.get("geography"),
        ),
        _fundraising_readiness_score(founder.get("fundraising_status")),
    )
    return row, label


def _extract_match_calibration_outcome(sample: Dict[str, Any]) -> Optional[float]:
    score_value = sample.get("outcome_score")
    if _is_probability(score_value):
        return float(score_value)

    label_value = sample.get("outcome_label")
    if isinstance(label_value, bool):
        return 1.0 if label_value else 0.0
    if _is_probability(label_value):
        return float(label_value)

    success_value = sample.get("successful_match")
    if isinstance(success_value, bool):
        return 1.0 if success_value else 0.0

    return None


def _fit_match_component_weights(
    rows: List[Tuple[float, float, float, float]],
    labels: List[float],
    default_weights: Dict[str, float],
    l2_strength: float,
    learning_rate: float,
    steps: int,
) -> Tuple[Dict[str, float], float, float]:
    default_vector = [float(default_weights[key]) for key in _MATCH_COMPONENT_KEYS]
    weight_vector = list(default_vector)

    loss_before = _mean_squared_error(rows, labels, default_vector)
    sample_count = float(len(rows))

    for _ in range(max(1, int(steps))):
        predictions = [
            sum(weight_vector[idx] * row[idx] for idx in range(len(_MATCH_COMPONENT_KEYS)))
            for row in rows
        ]
        gradients = [0.0 for _ in _MATCH_COMPONENT_KEYS]
        for idx in range(len(_MATCH_COMPONENT_KEYS)):
            grad = 0.0
            for row_idx, row in enumerate(rows):
                grad += (predictions[row_idx] - labels[row_idx]) * row[idx]
            grad = (2.0 / sample_count) * grad
            grad += 2.0 * float(l2_strength) * (weight_vector[idx] - default_vector[idx])
            gradients[idx] = grad

        for idx in range(len(_MATCH_COMPONENT_KEYS)):
            weight_vector[idx] = weight_vector[idx] - (float(learning_rate) * gradients[idx])

        weight_vector = _project_to_simplex(weight_vector)

    loss_after = _mean_squared_error(rows, labels, weight_vector)
    return (
        {
            key: float(weight_vector[idx])
            for idx, key in enumerate(_MATCH_COMPONENT_KEYS)
        },
        float(loss_before),
        float(loss_after),
    )


def _mean_squared_error(
    rows: List[Tuple[float, float, float, float]],
    labels: List[float],
    weight_vector: List[float],
) -> float:
    if not rows:
        return 0.0
    errors = []
    for idx, row in enumerate(rows):
        prediction = sum(weight_vector[j] * row[j] for j in range(len(weight_vector)))
        errors.append((prediction - labels[idx]) ** 2)
    return float(sum(errors) / len(errors))


def _project_to_simplex(values: List[float]) -> List[float]:
    """Project vector onto the probability simplex."""
    if not values:
        return values

    sorted_values = sorted(values, reverse=True)
    cumulative = 0.0
    rho = -1
    for idx, value in enumerate(sorted_values):
        cumulative += value
        threshold = (cumulative - 1.0) / float(idx + 1)
        if value - threshold > 0.0:
            rho = idx

    if rho == -1:
        return [1.0 / float(len(values)) for _ in values]

    theta = (sum(sorted_values[: rho + 1]) - 1.0) / float(rho + 1)
    projected = [max(value - theta, 0.0) for value in values]
    projected_sum = sum(projected)
    if projected_sum <= 0.0:
        return [1.0 / float(len(values)) for _ in values]
    return [value / projected_sum for value in projected]


def _founder_product_perception_score(
    founder_profile: Dict[str, Any],
    params: Dict[str, Any],
) -> float:
    trust_score = _clamp_signal_value(
        founder_profile.get("trust_score", params.get("founder_signup_trust_score", 1.0))
    )
    channel_intent_fit = _clamp_signal_value(
        founder_profile.get(
            "channel_intent_fit", params.get("founder_signup_channel_intent_fit", 1.0)
        )
    )
    proof_of_outcomes = _clamp_signal_value(
        founder_profile.get(
            "proof_of_outcomes", params.get("founder_signup_proof_of_outcomes", 1.0)
        )
    )
    form_complexity = _clamp_signal_value(
        founder_profile.get(
            "form_complexity_score",
            params.get("founder_signup_form_complexity", 0.0),
        )
    )
    signup_cta_clarity = _clamp_signal_value(params.get("founder_signup_cta_clarity", 0.72))
    signup_friction = _clamp_signal_value(params.get("founder_signup_friction", 0.30))
    return _clamp_signal_value(
        (0.28 * trust_score)
        + (0.22 * channel_intent_fit)
        + (0.20 * proof_of_outcomes)
        + (0.15 * (1.0 - form_complexity))
        + (0.10 * signup_cta_clarity)
        + (0.05 * (1.0 - signup_friction))
    )


def _vc_product_perception_score(
    vc_profile: Dict[str, Any],
    params: Dict[str, Any],
) -> float:
    confidence_factor = _clamp_signal_value(
        1.0 - _clamp_signal_value(vc_profile.get("confidence_threshold"))
    )
    signup_cta_clarity = _clamp_signal_value(params.get("vc_signup_cta_clarity", 0.68))
    signup_friction = _clamp_signal_value(params.get("vc_signup_friction", 0.33))
    return _clamp_signal_value(
        (0.45 * confidence_factor)
        + (0.30 * signup_cta_clarity)
        + (0.25 * (1.0 - signup_friction))
    )


def _derive_outreach_signals_from_data(
    founders: List[Dict[str, Any]],
    vcs: List[Dict[str, Any]],
    params: Dict[str, Any],
    match_signals: List[Dict[str, Any]],
    personalization_score_evaluator: Optional[PersonalizationScoreEvaluator] = None,
) -> List[Dict[str, Any]]:
    """Build deterministic outreach quality from product-perception and pair fit."""
    signals: List[Dict[str, Any]] = []
    personalization_boost = _clamp_signal_value(
        params.get("derived_personalization_score_boost", 0.0)
    )
    timing_boost = _clamp_signal_value(params.get("derived_timing_score_boost", 0.0))

    match_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for match_signal in match_signals:
        founder_id = match_signal.get("founder_id")
        vc_id = match_signal.get("vc_id")
        if not isinstance(founder_id, str) or not isinstance(vc_id, str):
            continue
        match_by_pair[(founder_id, vc_id)] = match_signal

    for founder in founders:
        founder_id = founder.get("id")
        if not isinstance(founder_id, str) or not founder_id.strip():
            continue

        founder_perception = _founder_product_perception_score(founder, params)
        urgency_score = _clamp_signal_value(founder.get("urgency_score"))
        fundraising_score = _fundraising_readiness_score(founder.get("fundraising_status"))

        for vc in vcs:
            vc_id = vc.get("id")
            if not isinstance(vc_id, str) or not vc_id.strip():
                continue

            vc_perception = _vc_product_perception_score(vc, params)
            confidence_factor = _clamp_signal_value(
                1.0 - _clamp_signal_value(vc.get("confidence_threshold"))
            )
            product_perception = _clamp_signal_value(
                (0.60 * founder_perception) + (0.40 * vc_perception)
            )
            timing_score = _clamp_signal_value(
                (0.45 * product_perception)
                + (0.25 * urgency_score)
                + (0.20 * fundraising_score)
                + (0.10 * confidence_factor)
                + timing_boost
            )

            match_signal = match_by_pair.get((founder_id, vc_id), {})
            match_score = _clamp_signal_value(match_signal.get("match_score"))
            explanation_quality = _clamp_signal_value(
                match_signal.get("explanation_quality")
            )
            sector_score = _sector_alignment_score(
                founder_sector=founder.get("sector"),
                vc_sectors=vc.get("thesis_sectors"),
            )
            stage_score = _stage_alignment_score(
                founder_stage=founder.get("stage"),
                vc_stage=vc.get("stage_focus"),
            )
            geo_score = _geography_alignment_score(
                founder_geo=founder.get("geography"),
                vc_geo=vc.get("geography"),
            )

            base_personalization_score = _clamp_signal_value(
                (0.35 * product_perception)
                + (0.30 * match_score)
                + (0.15 * explanation_quality)
                + (0.10 * sector_score)
                + (0.05 * stage_score)
                + (0.05 * geo_score)
                + personalization_boost
            )
            personalization_eval = (
                personalization_score_evaluator.evaluate(
                    founder_profile=founder,
                    vc_profile=vc,
                    base_personalization_score=base_personalization_score,
                    context={
                        "product_perception_score": product_perception,
                        "founder_product_perception": founder_perception,
                        "vc_product_perception": vc_perception,
                        "timing_score": timing_score,
                        "match_score": match_score,
                        "explanation_quality": explanation_quality,
                        "sector_score": sector_score,
                        "stage_score": stage_score,
                        "geo_score": geo_score,
                        "base_personalization_score": base_personalization_score,
                    },
                )
                if personalization_score_evaluator is not None
                else {
                    "score": base_personalization_score,
                    "source": "deterministic",
                    "llm_score": None,
                    "is_personalized": base_personalization_score >= 0.5,
                }
            )
            personalization_score = _clamp_signal_value(personalization_eval["score"])

            signals.append(
                {
                    "founder_id": founder_id,
                    "vc_id": vc_id,
                    "personalization_score": personalization_score,
                    "timing_score": timing_score,
                    "product_perception_score": product_perception,
                    "timing_score_source": "product_perception",
                    "personalization_score_base": base_personalization_score,
                    "personalization_score_source": personalization_eval.get(
                        "source", "deterministic"
                    ),
                    "personalization_score_llm_score": personalization_eval.get(
                        "llm_score"
                    ),
                    "personalization_is_personalized": personalization_eval.get(
                        "is_personalized", False
                    ),
                }
            )

    return sorted(signals, key=lambda item: (item["founder_id"], item["vc_id"]))


def _derive_match_signals_from_data(
    founders: List[Dict[str, Any]],
    vcs: List[Dict[str, Any]],
    params: Dict[str, Any],
    match_component_weights: Optional[Dict[str, float]] = None,
    explanation_quality_evaluator: Optional[ExplanationQualityEvaluator] = None,
) -> List[Dict[str, Any]]:
    """Build deterministic founder/VC match signals from cohort profiles."""
    signals: List[Dict[str, Any]] = []
    resolved_weights = _normalize_match_component_weights(match_component_weights)
    match_score_boost = _clamp_signal_value(params.get("derived_match_score_boost", 0.0))
    explanation_boost = _clamp_signal_value(
        params.get("derived_explanation_quality_boost", 0.0)
    )

    for founder in founders:
        founder_id = founder.get("id")
        if not isinstance(founder_id, str) or not founder_id.strip():
            continue
        for vc in vcs:
            vc_id = vc.get("id")
            if not isinstance(vc_id, str) or not vc_id.strip():
                continue

            sector_score = _sector_alignment_score(
                founder_sector=founder.get("sector"),
                vc_sectors=vc.get("thesis_sectors"),
            )
            stage_score = _stage_alignment_score(
                founder_stage=founder.get("stage"),
                vc_stage=vc.get("stage_focus"),
            )
            geo_score = _geography_alignment_score(
                founder_geo=founder.get("geography"),
                vc_geo=vc.get("geography"),
            )
            fundraising_score = _fundraising_readiness_score(
                founder.get("fundraising_status")
            )
            confidence_factor = _clamp_signal_value(
                1.0 - _clamp_signal_value(vc.get("confidence_threshold"))
            )

            match_score = _clamp_signal_value(
                (resolved_weights["sector"] * sector_score)
                + (resolved_weights["stage"] * stage_score)
                + (resolved_weights["geo"] * geo_score)
                + (resolved_weights["fundraising"] * fundraising_score)
                + match_score_boost
            )
            base_explanation_quality = _clamp_signal_value(
                (0.50 * sector_score)
                + (0.20 * stage_score)
                + (0.15 * geo_score)
                + (0.15 * confidence_factor)
                + explanation_boost
            )
            explanation_eval = (
                explanation_quality_evaluator.evaluate(
                    founder_profile=founder,
                    vc_profile=vc,
                    base_explanation_quality=base_explanation_quality,
                    context={
                        "sector_score": sector_score,
                        "stage_score": stage_score,
                        "geo_score": geo_score,
                        "fundraising_score": fundraising_score,
                        "confidence_factor": confidence_factor,
                        "match_score": match_score,
                        "base_explanation_quality": base_explanation_quality,
                    },
                )
                if explanation_quality_evaluator is not None
                else {
                    "score": base_explanation_quality,
                    "source": "deterministic",
                    "llm_score": None,
                    "makes_sense": base_explanation_quality >= 0.5,
                }
            )
            explanation_quality = _clamp_signal_value(explanation_eval["score"])

            signals.append(
                {
                    "founder_id": founder_id,
                    "vc_id": vc_id,
                    "match_score": match_score,
                    "explanation_quality": explanation_quality,
                    "explanation_quality_base": base_explanation_quality,
                    "explanation_quality_source": explanation_eval.get("source", "deterministic"),
                    "explanation_quality_llm_score": explanation_eval.get("llm_score"),
                    "explanation_makes_sense": explanation_eval.get("makes_sense", False),
                }
            )

    return sorted(signals, key=lambda item: (item["founder_id"], item["vc_id"]))


def _sector_alignment_score(founder_sector: Any, vc_sectors: Any) -> float:
    founder_key = _normalize_label(founder_sector)
    if not founder_key:
        return 0.0

    sector_values = []
    if isinstance(vc_sectors, list):
        sector_values = [_normalize_label(item) for item in vc_sectors]
    else:
        one_value = _normalize_label(vc_sectors)
        if one_value:
            sector_values = [one_value]

    sector_set = {item for item in sector_values if item}
    if founder_key in sector_set:
        return 1.0

    related = _SECTOR_RELATEDNESS.get(founder_key, set())
    if any(sector in related for sector in sector_set):
        return 0.65

    if any(founder_key in _SECTOR_RELATEDNESS.get(sector, set()) for sector in sector_set):
        return 0.65

    return 0.0


def _stage_alignment_score(founder_stage: Any, vc_stage: Any) -> float:
    founder_key = _normalize_label(founder_stage)
    vc_key = _normalize_label(vc_stage)
    if not founder_key or not vc_key:
        return 0.0
    if founder_key == vc_key:
        return 1.0
    if vc_key in _STAGE_ADJACENCY.get(founder_key, set()):
        return 0.60
    return 0.0


def _geography_alignment_score(founder_geo: Any, vc_geo: Any) -> float:
    founder_key = _normalize_label(founder_geo)
    vc_key = _normalize_label(vc_geo)
    if not founder_key or not vc_key:
        return 0.0
    if vc_key == "global":
        return 1.0
    if founder_key == vc_key:
        return 1.0

    founder_region = _resolve_region(founder_key)
    vc_region = _resolve_region(vc_key)
    if founder_region and vc_region and founder_region == vc_region:
        return 0.80

    return 0.0


def _fundraising_readiness_score(status: Any) -> float:
    value = _normalize_label(status)
    if value == "active":
        return 1.0
    if value == "preparing":
        return 0.75
    if value == "paused":
        return 0.30
    return 0.50


def _resolve_region(geo_value: str) -> str:
    if geo_value in _REGION_ALIASES:
        return _REGION_ALIASES[geo_value]
    return _COUNTRY_TO_REGION.get(geo_value, "")


def _normalize_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


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

    founder_signup_count = sum(
        state in {"signup", "engaged", "matched", "interested", "meeting"}
        for state in founder_states
    )
    vc_signup_count = sum(
        state in {"signup", "engaged", "matched", "interested", "meeting"}
        for state in vc_states
    )
    founder_engaged_count = sum(
        state in {"engaged", "matched", "interested", "meeting"}
        for state in founder_states
    )
    founder_matched_count = sum(
        state in {"matched", "interested", "meeting"}
        for state in founder_states
    )
    vc_engaged_count = sum(
        state in {"engaged", "matched", "interested", "meeting"}
        for state in vc_states
    )
    vc_matched_count = sum(
        state in {"matched", "interested", "meeting"}
        for state in vc_states
    )

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
        "founder_visit_to_signup": _safe_rate(founder_signup_count, len(founder_states)),
        "vc_visit_to_signup": _safe_rate(vc_signup_count, len(vc_states)),
        "founder_engaged_to_matched_rate": _safe_rate(
            founder_matched_count,
            founder_engaged_count,
        ),
        "vc_engaged_to_matched_rate": _safe_rate(
            vc_matched_count,
            vc_engaged_count,
        ),
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
