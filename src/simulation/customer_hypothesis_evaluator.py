"""Evaluate Track D hypotheses against deterministic customer simulation outputs."""
from __future__ import annotations

from typing import Any, Dict, List


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _evaluate_primary_delta(
    direction: str,
    observed_delta: float,
    min_delta: float,
) -> bool:
    if direction == "increase":
        return observed_delta >= min_delta
    if direction == "decrease":
        return observed_delta <= (-1.0 * min_delta)
    return False


def evaluate_customer_hypotheses(
    scenario_summary: Dict[str, Any],
    hypotheses: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate hypotheses against a scenario matrix summary payload."""
    scenarios = scenario_summary.get("scenarios", {})
    if not isinstance(scenarios, dict):
        raise ValueError("scenario_summary.scenarios must be a dictionary.")

    determinism_failures = scenario_summary.get("determinism_failures", [])
    if not isinstance(determinism_failures, list):
        determinism_failures = []

    results: List[Dict[str, Any]] = []
    counts = {"pass": 0, "warn": 0, "fail": 0}

    for hypothesis in hypotheses:
        hypothesis_id = str(hypothesis.get("id", "")).strip() or "unknown_hypothesis"
        scenario_name = str(hypothesis.get("scenario", "")).strip()
        metric = str(hypothesis.get("metric", "")).strip()
        direction = str(hypothesis.get("direction", "")).strip()
        min_delta = float(hypothesis.get("min_delta", 0.0))
        guardrails = hypothesis.get("guardrails", [])
        if not isinstance(guardrails, list):
            guardrails = []

        status = "pass"
        checks: List[Dict[str, Any]] = []

        scenario = scenarios.get(scenario_name)
        if not isinstance(scenario, dict):
            status = "fail"
            checks.append(
                {
                    "check": "scenario_present",
                    "status": "fail",
                    "message": f"Scenario '{scenario_name}' not present in summary.",
                }
            )
            results.append(
                {
                    "id": hypothesis_id,
                    "scenario": scenario_name,
                    "metric": metric,
                    "direction": direction,
                    "expected_min_delta": min_delta,
                    "observed_delta": None,
                    "status": status,
                    "checks": checks,
                }
            )
            counts[status] += 1
            continue

        if not bool(scenario.get("deterministic", False)):
            status = "warn"
            checks.append(
                {
                    "check": "scenario_determinism",
                    "status": "warn",
                    "message": f"Scenario '{scenario_name}' failed determinism check.",
                }
            )
        else:
            checks.append(
                {
                    "check": "scenario_determinism",
                    "status": "pass",
                    "message": f"Scenario '{scenario_name}' is deterministic.",
                }
            )

        deltas = scenario.get("deltas_vs_baseline", {})
        if not isinstance(deltas, dict):
            status = "fail"
            checks.append(
                {
                    "check": "deltas_vs_baseline",
                    "status": "fail",
                    "message": "Scenario deltas_vs_baseline is missing or invalid.",
                }
            )
            observed_delta = None
        else:
            observed_delta = deltas.get(metric)
            if not _is_number(observed_delta):
                status = "fail"
                checks.append(
                    {
                        "check": "primary_delta",
                        "status": "fail",
                        "message": f"Metric '{metric}' delta missing or non-numeric.",
                    }
                )
            else:
                observed_delta = float(observed_delta)
                primary_ok = _evaluate_primary_delta(direction, observed_delta, min_delta)
                if primary_ok:
                    checks.append(
                        {
                            "check": "primary_delta",
                            "status": "pass",
                            "message": (
                                f"Observed delta {observed_delta:+.4f} satisfied "
                                f"{direction} threshold {min_delta:.4f}."
                            ),
                        }
                    )
                else:
                    status = "fail"
                    checks.append(
                        {
                            "check": "primary_delta",
                            "status": "fail",
                            "message": (
                                f"Observed delta {observed_delta:+.4f} did not satisfy "
                                f"{direction} threshold {min_delta:.4f}."
                            ),
                        }
                    )

        if isinstance(deltas, dict):
            for guardrail in guardrails:
                guardrail_metric = str(guardrail.get("metric", "")).strip()
                guardrail_delta = deltas.get(guardrail_metric)
                guardrail_min = guardrail.get("min_delta")
                guardrail_max = guardrail.get("max_delta")

                if not _is_number(guardrail_delta):
                    status = "fail"
                    checks.append(
                        {
                            "check": f"guardrail:{guardrail_metric}",
                            "status": "fail",
                            "message": (
                                f"Guardrail metric '{guardrail_metric}' delta missing "
                                "or non-numeric."
                            ),
                        }
                    )
                    continue

                guardrail_delta = float(guardrail_delta)
                guardrail_ok = True
                guardrail_messages: List[str] = []

                if _is_number(guardrail_min):
                    min_value = float(guardrail_min)
                    if guardrail_delta < min_value:
                        guardrail_ok = False
                        guardrail_messages.append(
                            f"{guardrail_delta:+.4f} < min_delta {min_value:+.4f}"
                        )

                if _is_number(guardrail_max):
                    max_value = float(guardrail_max)
                    if guardrail_delta > max_value:
                        guardrail_ok = False
                        guardrail_messages.append(
                            f"{guardrail_delta:+.4f} > max_delta {max_value:+.4f}"
                        )

                if guardrail_ok:
                    checks.append(
                        {
                            "check": f"guardrail:{guardrail_metric}",
                            "status": "pass",
                            "message": (
                                f"Guardrail metric '{guardrail_metric}' observed "
                                f"{guardrail_delta:+.4f} within limits."
                            ),
                        }
                    )
                else:
                    status = "fail"
                    checks.append(
                        {
                            "check": f"guardrail:{guardrail_metric}",
                            "status": "fail",
                            "message": "; ".join(guardrail_messages),
                        }
                    )

        results.append(
            {
                "id": hypothesis_id,
                "scenario": scenario_name,
                "metric": metric,
                "direction": direction,
                "expected_min_delta": min_delta,
                "observed_delta": observed_delta,
                "status": status,
                "checks": checks,
            }
        )
        counts[status] += 1

    notes: List[str] = []
    if not hypotheses:
        notes.append("No hypotheses defined in hypothesis file.")

    if determinism_failures:
        notes.append(
            "Determinism failures present in scenario summary: "
            + ", ".join(str(item) for item in determinism_failures)
        )

    if determinism_failures:
        overall_status = "fail"
    elif counts["fail"] > 0:
        overall_status = "fail"
    elif not hypotheses:
        overall_status = "warn"
    elif counts["warn"] > 0:
        overall_status = "warn"
    else:
        overall_status = "pass"

    return {
        "overall_status": overall_status,
        "counts": counts,
        "determinism_failures": determinism_failures,
        "results": results,
        "notes": notes,
    }
