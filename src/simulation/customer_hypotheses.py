"""Loading and validating Track D customer simulation hypotheses."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.simulation.customer_scenario_matrix import list_customer_scenarios
from src.utils.config import settings

HYPOTHESIS_DIRECTIONS = {"increase", "decrease"}


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def validate_customer_hypotheses_payload(payload: Dict[str, Any]) -> List[str]:
    """Validate customer hypothesis payload and return a list of errors."""
    errors: List[str] = []

    if not isinstance(payload, dict):
        return ["Customer hypothesis payload must be a dictionary."]

    version = payload.get("version")
    if not isinstance(version, int) or version < 1:
        errors.append("version must be an integer >= 1.")

    hypotheses = payload.get("hypotheses")
    if hypotheses is None:
        errors.append("Missing required key: 'hypotheses'.")
        return errors
    if not isinstance(hypotheses, list):
        errors.append("'hypotheses' must be a list.")
        return errors

    allowed_scenarios = set(list_customer_scenarios())
    seen_ids = set()

    for idx, hypothesis in enumerate(hypotheses):
        item_path = f"hypotheses[{idx}]"
        if not isinstance(hypothesis, dict):
            errors.append(f"{item_path} must be an object.")
            continue

        hypothesis_id = hypothesis.get("id")
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            errors.append(f"{item_path}.id must be a non-empty string.")
        elif hypothesis_id in seen_ids:
            errors.append(f"Duplicate hypothesis id '{hypothesis_id}'.")
        else:
            seen_ids.add(hypothesis_id)

        scenario = hypothesis.get("scenario")
        if not isinstance(scenario, str) or not scenario.strip():
            errors.append(f"{item_path}.scenario must be a non-empty string.")
        elif scenario not in allowed_scenarios:
            options = ", ".join(sorted(allowed_scenarios))
            errors.append(
                f"{item_path}.scenario must be one of: {options}."
            )

        metric = hypothesis.get("metric")
        if not isinstance(metric, str) or not metric.strip():
            errors.append(f"{item_path}.metric must be a non-empty string.")

        direction = hypothesis.get("direction")
        if direction not in HYPOTHESIS_DIRECTIONS:
            options = ", ".join(sorted(HYPOTHESIS_DIRECTIONS))
            errors.append(f"{item_path}.direction must be one of: {options}.")

        min_delta = hypothesis.get("min_delta")
        if not _is_number(min_delta) or float(min_delta) < 0.0:
            errors.append(f"{item_path}.min_delta must be a number >= 0.0.")

        guardrails = hypothesis.get("guardrails", [])
        if not isinstance(guardrails, list):
            errors.append(f"{item_path}.guardrails must be a list.")
            continue

        for guardrail_idx, guardrail in enumerate(guardrails):
            guardrail_path = f"{item_path}.guardrails[{guardrail_idx}]"
            if not isinstance(guardrail, dict):
                errors.append(f"{guardrail_path} must be an object.")
                continue

            guardrail_metric = guardrail.get("metric")
            if not isinstance(guardrail_metric, str) or not guardrail_metric.strip():
                errors.append(f"{guardrail_path}.metric must be a non-empty string.")

            has_min = "min_delta" in guardrail
            has_max = "max_delta" in guardrail
            if not has_min and not has_max:
                errors.append(
                    f"{guardrail_path} must define min_delta and/or max_delta."
                )
                continue

            if has_min and not _is_number(guardrail["min_delta"]):
                errors.append(f"{guardrail_path}.min_delta must be numeric.")
            if has_max and not _is_number(guardrail["max_delta"]):
                errors.append(f"{guardrail_path}.max_delta must be numeric.")

            if (
                has_min
                and has_max
                and _is_number(guardrail["min_delta"])
                and _is_number(guardrail["max_delta"])
                and float(guardrail["min_delta"]) > float(guardrail["max_delta"])
            ):
                errors.append(
                    f"{guardrail_path}.min_delta cannot be greater than max_delta."
                )

    return errors


def normalize_customer_hypotheses(
    hypotheses: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Return deterministic normalized hypotheses sorted by id."""
    normalized: List[Dict[str, Any]] = []
    for hypothesis in hypotheses:
        normalized_hypothesis = dict(hypothesis)
        guardrails = normalized_hypothesis.get("guardrails", [])
        if isinstance(guardrails, list):
            normalized_hypothesis["guardrails"] = [
                dict(guardrail) for guardrail in guardrails
            ]
        else:
            normalized_hypothesis["guardrails"] = []
        normalized.append(normalized_hypothesis)

    return sorted(normalized, key=lambda item: str(item.get("id", "")))


def load_customer_hypotheses(
    hypotheses_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load and validate customer hypotheses from seed data.

    Returns an empty list when no hypotheses are defined.
    """
    resolved_path = Path(hypotheses_path or settings.customer_hypotheses_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"Customer hypothesis file not found: {resolved_path}")

    with resolved_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    errors = validate_customer_hypotheses_payload(payload)
    if errors:
        lines = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"Invalid customer hypothesis data:\n{lines}")

    hypotheses = payload.get("hypotheses", [])
    return normalize_customer_hypotheses(hypotheses)
