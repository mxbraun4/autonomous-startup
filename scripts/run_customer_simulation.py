"""Run deterministic customer simulation scenarios and compare against baseline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repository root is on import path when executed as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.simulation.customer_environment import run_customer_environment
from src.simulation.customer_scenario_matrix import (
    build_customer_environment_input_for_scenario,
    get_customer_scenario,
    list_customer_scenarios,
)
from src.utils.config import settings
from src.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

SUMMARY_METRICS = [
    "visitor_to_tool_use",
    "tool_use_to_signup",
    "signup_to_first_match",
    "founder_interested_rate",
    "vc_interested_rate",
    "mutual_interest_rate",
    "meeting_conversion_rate",
]


def _resolve_scenarios(requested: Optional[List[str]]) -> List[str]:
    available = list_customer_scenarios()
    if not requested:
        return available

    expanded: List[str] = []
    for item in requested:
        parts = [part.strip() for part in item.split(",") if part.strip()]
        expanded.extend(parts)

    unknown = [name for name in expanded if name not in available]
    if unknown:
        available_str = ", ".join(available)
        unknown_str = ", ".join(sorted(dict.fromkeys(unknown)))
        raise ValueError(
            f"Unknown scenarios: {unknown_str}. Available scenarios: {available_str}"
        )

    deduped: List[str] = []
    seen = set()
    for name in expanded:
        if name not in seen:
            seen.add(name)
            deduped.append(name)

    if "baseline" not in seen:
        # Baseline is always required to compute deltas.
        return ["baseline", *deduped]
    return deduped


def _compute_deltas(
    metrics: Dict[str, float], baseline_metrics: Dict[str, float]
) -> Dict[str, float]:
    deltas: Dict[str, float] = {}
    for metric, value in metrics.items():
        base_value = baseline_metrics.get(metric, 0.0)
        deltas[metric] = float(value - base_value)
    return deltas


def run_scenario_matrix(
    run_id_prefix: str,
    iteration: int,
    scenario_names: List[str],
    seed_override: Optional[int] = None,
    seed_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute selected deterministic scenarios and compare to baseline."""
    scenario_results: Dict[str, Dict[str, Any]] = {}
    determinism_failures: List[str] = []

    for scenario_name in scenario_names:
        scenario = get_customer_scenario(scenario_name)
        run_id = f"{run_id_prefix}_{scenario_name}"
        environment_input = build_customer_environment_input_for_scenario(
            run_id=run_id,
            iteration=iteration,
            scenario_name=scenario_name,
            seed=seed_override,
            seed_path=seed_path,
        )

        first = run_customer_environment(environment_input)
        second = run_customer_environment(environment_input)
        deterministic = first == second
        if not deterministic:
            determinism_failures.append(scenario_name)

        scenario_results[scenario_name] = {
            "description": scenario["description"],
            "hypothesis": scenario["hypothesis"],
            "seed": environment_input["run_context"]["seed"],
            "deterministic": deterministic,
            "events_count": len(first["events"]),
            "metrics": first["metrics"],
            "diagnostics": first["diagnostics"],
        }

    if "baseline" not in scenario_results:
        raise ValueError("Baseline scenario is required for delta computation.")

    baseline_metrics = scenario_results["baseline"]["metrics"]
    for scenario_name, scenario_result in scenario_results.items():
        scenario_result["deltas_vs_baseline"] = _compute_deltas(
            scenario_result["metrics"],
            baseline_metrics,
        )

    return {
        "run_context": {
            "run_id_prefix": run_id_prefix,
            "iteration": iteration,
            "seed_override": seed_override,
            "scenario_names": scenario_names,
        },
        "baseline_scenario": "baseline",
        "determinism_failures": determinism_failures,
        "scenarios": scenario_results,
    }


def _print_summary(summary: Dict[str, Any], verbose: int) -> None:
    scenario_names: List[str] = summary["run_context"]["scenario_names"]
    failures = summary["determinism_failures"]

    print("\n" + "=" * 72)
    print("CUSTOMER SIMULATION SCENARIO MATRIX")
    print("=" * 72)
    print(f"Scenarios: {', '.join(scenario_names)}")
    print(f"Iteration: {summary['run_context']['iteration']}")
    print(f"Seed override: {summary['run_context']['seed_override']}")
    print("-" * 72)

    for scenario_name in scenario_names:
        scenario = summary["scenarios"][scenario_name]
        status = "PASS" if scenario["deterministic"] else "FAIL"
        print(f"{scenario_name:>20} | determinism={status} | events={scenario['events_count']}")

        if verbose >= 2:
            hypothesis = scenario["hypothesis"]
            print(f"  hypothesis: {hypothesis.get('id', '-')}: {hypothesis.get('summary', '-')}")

        metric_line = " | ".join(
            (
                f"{metric}={scenario['metrics'][metric]:.3f}"
                f" (d={scenario['deltas_vs_baseline'][metric]:+.3f})"
            )
            for metric in SUMMARY_METRICS
        )
        print(f"  {metric_line}")

        if verbose >= 2 and scenario["diagnostics"]["dropoff_reasons"]:
            print(f"  dropoff_reasons={scenario['diagnostics']['dropoff_reasons']}")

    print("-" * 72)
    if failures:
        print(f"Determinism check: FAILED ({', '.join(failures)})")
    else:
        print("Determinism check: PASSED")
    print("=" * 72 + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic customer simulation scenarios and report deltas "
            "against baseline."
        )
    )
    parser.add_argument(
        "--run-id-prefix",
        type=str,
        default="customer_track_d",
        help="Prefix used for scenario run IDs (default: customer_track_d).",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=1,
        help="Iteration value used in environment input (default: 1).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed override for all scenarios.",
    )
    parser.add_argument(
        "--seed-path",
        type=str,
        default=None,
        help="Optional path to customer seed cohort file.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=None,
        help=(
            "Scenario names to run. Can be space-separated or comma-separated. "
            "If omitted, all scenarios are executed."
        ),
    )
    parser.add_argument(
        "--json-out",
        type=str,
        default=None,
        help="Optional file path to write full JSON summary.",
    )
    parser.add_argument(
        "--verbose",
        type=int,
        choices=[0, 1, 2],
        default=1,
        help="Output verbosity: 0=minimal, 1=default, 2=verbose.",
    )
    parser.add_argument(
        "--allow-nondeterministic",
        action="store_true",
        help="Return success exit code even if determinism checks fail.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(settings.log_level)

    scenario_names = _resolve_scenarios(args.scenarios)
    logger.info("Running customer scenario matrix for %d scenarios", len(scenario_names))

    summary = run_scenario_matrix(
        run_id_prefix=args.run_id_prefix,
        iteration=args.iteration,
        scenario_names=scenario_names,
        seed_override=args.seed,
        seed_path=args.seed_path,
    )

    if args.verbose > 0:
        _print_summary(summary, verbose=args.verbose)

    if args.json_out:
        output_path = Path(args.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Wrote JSON summary: {output_path}")

    has_failures = bool(summary["determinism_failures"])
    if has_failures and not args.allow_nondeterministic:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
