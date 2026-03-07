"""Run localhost web-product autonomy with the framework runtime stack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time
from typing import Dict, Optional, Tuple

if __package__:
    from ._bootstrap import add_repo_root_to_path
else:
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path(__file__)

from src.framework.adapters import WebProductAdapter
from src.framework.autonomy import RunController
from src.framework.contracts import RunConfig
from src.framework.eval.evaluator import Evaluator
from src.framework.observability import EventLogger, TimelineBuilder
from src.framework.orchestration.executor import Executor
from src.framework.runtime import (
    AgentRuntime,
    CapabilityRegistry,
    ExecutionContext,
    LocalhostAutonomyToolset,
    TaskRouter,
    register_web_agents,
    register_web_capabilities,
)
from src.framework.runtime.web_edit_templates import (
    list_edit_templates,
    resolve_edit_template,
)
from src.framework.safety import build_web_domain_policy_hook, create_action_guard
from src.framework.web_constants import (
    POLICY_ALLOWED_EDIT_PATH_PATTERNS,
    POLICY_ALLOWED_EDIT_SEARCH_PATTERNS,
)
from src.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def build_web_arg_parser(*, add_help: bool = True) -> argparse.ArgumentParser:
    """Build argument parser shared by web run + scheduler scripts."""
    parser = argparse.ArgumentParser(
        description="Run autonomous localhost web-product iteration",
        add_help=add_help,
    )
    parser.add_argument("--target-url", default="http://localhost:3000")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--test-command", default="pytest -q")
    parser.add_argument("--restart-command", default="")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--max-edits-per-cycle", type=int, default=2)
    parser.add_argument("--checkpoint-dir", default="data/memory/checkpoints_web")
    parser.add_argument("--events-path", default="data/memory/web_autonomy_events.ndjson")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps-per-cycle", type=int, default=50)
    parser.add_argument("--budget-seconds", type=float, default=None)
    parser.add_argument("--budget-tokens", type=int, default=None)
    parser.add_argument("--autonomy-level", type=int, default=1)
    parser.add_argument("--auto-resume-on-pause", action="store_true")
    parser.add_argument("--pause-cooldown-seconds", type=float, default=None)
    parser.add_argument("--disable-adaptive-policy", action="store_true")
    parser.add_argument("--disable-diagnostics", action="store_true")
    parser.add_argument("--adaptive-policy-reliability-streak", type=int, default=None)
    parser.add_argument(
        "--adaptive-policy-step-adjustment-ratio",
        type=float,
        default=None,
    )
    parser.add_argument("--adaptive-policy-learning-threshold", type=float, default=None)
    parser.add_argument("--policy-adjustment-bounds-json", default="")
    parser.add_argument("--diagnostics-window-size", type=int, default=None)
    parser.add_argument(
        "--diagnostics-policy-violation-threshold",
        type=int,
        default=None,
    )
    parser.add_argument("--diagnostics-tool-denied-threshold", type=int, default=None)
    parser.add_argument("--diagnostics-gate-drop-window", type=int, default=None)
    parser.add_argument("--exploratory-task-limit", type=int, default=None)
    parser.add_argument("--budget-critical-threshold-pct", type=float, default=None)
    parser.add_argument("--schedule-json", action="append", default=[])
    parser.add_argument("--schedules-file", default="")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--list-edit-templates", action="store_true")
    parser.add_argument("--edit-template-file", default="data/seed/web_edit_templates.json")
    edit_group = parser.add_mutually_exclusive_group()
    edit_group.add_argument("--edit-template", default="")
    edit_group.add_argument("--edit-path", default="")
    parser.add_argument("--edit-search", default="")
    parser.add_argument("--edit-replace", default="")
    parser.add_argument("--edit-dry-run", action="store_true")
    return parser


def _parse_args() -> argparse.Namespace:
    return build_web_arg_parser(add_help=True).parse_args()


def _default_edit_instruction(
    args: argparse.Namespace,
) -> Tuple[Optional[dict], Dict[str, list[str]], Optional[str]]:
    if args.edit_template:
        resolved = resolve_edit_template(
            args.edit_template,
            template_file=args.edit_template_file or None,
            dry_run=bool(args.edit_dry_run),
            replace_override=args.edit_replace or None,
        )
        return (
            dict(resolved["instruction"]),
            dict(resolved["policy_overrides"]),
            str(resolved.get("template_name") or args.edit_template),
        )

    if not args.edit_path:
        return None, {}, None

    instruction = {
        "path": args.edit_path,
        "search": args.edit_search,
        "replace": args.edit_replace,
        "dry_run": bool(args.edit_dry_run),
        "max_replacements": 1,
    }
    policy_overrides: Dict[str, list[str]] = {
        POLICY_ALLOWED_EDIT_PATH_PATTERNS: [
            Path(str(args.edit_path)).as_posix(),
        ]
    }
    if args.edit_search:
        policy_overrides[POLICY_ALLOWED_EDIT_SEARCH_PATTERNS] = [
            f"^{re.escape(str(args.edit_search))}$"
        ]
    return instruction, policy_overrides, None


def _print_edit_templates(template_file: str) -> None:
    rows = list_edit_templates(template_file or None)
    if not rows:
        print("No edit templates available.")
        return
    print("Available edit templates:")
    for row in rows:
        print(
            f"  - {row['name']}: {row['description']} "
            f"[path={row['path']}]"
        )


def _parse_schedules_from_args(args: argparse.Namespace) -> list[dict]:
    schedules: list[dict] = []

    schedules_file = str(getattr(args, "schedules_file", "") or "").strip()
    if schedules_file:
        schedules.extend(_load_schedules_file(Path(schedules_file)))

    for raw in getattr(args, "schedule_json", []) or []:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Each --schedule-json value must decode to an object")
        schedules.append(parsed)

    explicit = getattr(args, "run_schedules", None)
    if explicit:
        schedules.extend([dict(item) for item in explicit if isinstance(item, dict)])

    return schedules


def _load_schedules_file(path: Path) -> list[dict]:
    if not path.exists():
        raise ValueError(f"Schedules file not found: {path}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Schedules file is not valid JSON: {path}") from exc

    if isinstance(parsed, list):
        raw_items = parsed
    elif isinstance(parsed, dict):
        raw_items = parsed.get("schedules")
    else:
        raise ValueError(f"Schedules file must be a list or object with 'schedules': {path}")

    if not isinstance(raw_items, list):
        raise ValueError(f"Schedules file missing list 'schedules': {path}")

    schedules: list[dict] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid schedule entry in {path}: {entry!r}")
        schedules.append(dict(entry))
    return schedules


def _policy_overrides_from_args(args: argparse.Namespace) -> dict:
    policies: dict = {}

    if args.auto_resume_on_pause:
        policies["auto_resume_on_pause"] = True
    if args.pause_cooldown_seconds is not None:
        policies["pause_cooldown_seconds"] = max(0.0, float(args.pause_cooldown_seconds))
    if args.disable_adaptive_policy:
        policies["adaptive_policy_enabled"] = False
    if args.disable_diagnostics:
        policies["diagnostics_enabled"] = False
    if args.adaptive_policy_reliability_streak is not None:
        policies["adaptive_policy_reliability_streak"] = max(
            1, int(args.adaptive_policy_reliability_streak)
        )
    if args.adaptive_policy_step_adjustment_ratio is not None:
        policies["adaptive_policy_step_adjustment_ratio"] = max(
            0.0, float(args.adaptive_policy_step_adjustment_ratio)
        )
    if args.adaptive_policy_learning_threshold is not None:
        policies["adaptive_policy_learning_threshold"] = float(
            args.adaptive_policy_learning_threshold
        )
    if args.diagnostics_window_size is not None:
        policies["diagnostics_window_size"] = max(1, int(args.diagnostics_window_size))
    if args.diagnostics_policy_violation_threshold is not None:
        policies["diagnostics_policy_violation_threshold"] = max(
            1,
            int(args.diagnostics_policy_violation_threshold),
        )
    if args.diagnostics_tool_denied_threshold is not None:
        policies["diagnostics_tool_denied_threshold"] = max(
            1,
            int(args.diagnostics_tool_denied_threshold),
        )
    if args.diagnostics_gate_drop_window is not None:
        policies["diagnostics_gate_drop_window"] = max(
            2,
            int(args.diagnostics_gate_drop_window),
        )
    if args.exploratory_task_limit is not None:
        policies["exploratory_task_limit"] = max(1, int(args.exploratory_task_limit))
    if args.budget_critical_threshold_pct is not None:
        policies["budget_critical_threshold_pct"] = max(
            0.0, float(args.budget_critical_threshold_pct)
        )

    raw_bounds = str(args.policy_adjustment_bounds_json or "").strip()
    if raw_bounds:
        parsed_bounds = json.loads(raw_bounds)
        if not isinstance(parsed_bounds, dict):
            raise ValueError("--policy-adjustment-bounds-json must decode to an object")
        policies["policy_adjustment_bounds"] = parsed_bounds

    return policies


def create_web_run_controller(
    args: argparse.Namespace,
) -> Tuple[RunController, EventLogger, str, Optional[str]]:
    """Create a fully wired web-autonomy run controller."""
    run_id = args.run_id or f"web_autonomy_{int(time.time())}"
    edit_instruction, policy_overrides, template_name = _default_edit_instruction(args)

    adapter = WebProductAdapter(
        target_url=args.target_url,
        workspace_root=args.workspace,
        test_command=args.test_command,
        restart_command=args.restart_command,
        max_edits_per_cycle=args.max_edits_per_cycle,
        default_edit_instruction=edit_instruction,
        allowed_edit_path_patterns=policy_overrides.get(
            POLICY_ALLOWED_EDIT_PATH_PATTERNS
        ),
        allowed_edit_search_patterns=policy_overrides.get(
            POLICY_ALLOWED_EDIT_SEARCH_PATTERNS
        ),
    )
    domain_policies = adapter.get_domain_policies()
    policy_overrides = _policy_overrides_from_args(args)
    schedules = _parse_schedules_from_args(args)

    run_config = RunConfig(
        run_id=run_id,
        seed=args.seed,
        max_cycles=args.iterations,
        max_steps_per_cycle=args.max_steps_per_cycle,
        budget_seconds=args.budget_seconds,
        budget_tokens=args.budget_tokens,
        autonomy_level=args.autonomy_level,
        policies={**dict(domain_policies), **policy_overrides},
        schedules=schedules,
    )

    toolset = LocalhostAutonomyToolset(
        workspace_root=args.workspace,
        target_url=args.target_url,
        test_command=args.test_command,
        restart_command=args.restart_command,
        max_edits_per_cycle=args.max_edits_per_cycle,
    )
    event_logger = EventLogger(persist_path=args.events_path)

    context = ExecutionContext(run_config=run_config, store=None)
    registry = CapabilityRegistry()
    register_web_capabilities(registry, toolset)

    router = TaskRouter(registry)
    domain_policy_hook = build_web_domain_policy_hook(
        run_config.policies,
        toolset_state_accessor=toolset.get_state,
    )
    action_guard = create_action_guard(
        run_config,
        context,
        domain_policy_hook=domain_policy_hook,
    )
    runtime = AgentRuntime(
        registry=registry,
        router=router,
        store=None,
        context=context,
        policy_engine=action_guard,
        event_emitter=event_logger,
    )
    register_web_agents(router, runtime, default_url=args.target_url)

    executor = Executor(runtime=runtime, context=context, event_emitter=event_logger)
    controller = RunController(
        run_config=run_config,
        executor=executor,
        domain_adapter=adapter,
        evaluator=Evaluator(event_emitter=event_logger),
        store=None,
        checkpoint_dir=args.checkpoint_dir,
        event_emitter=event_logger,
        context=context,
    )
    return controller, event_logger, run_id, template_name


def main() -> None:
    args = _parse_args()
    if args.list_edit_templates:
        _print_edit_templates(args.edit_template_file)
        return

    setup_logging(args.log_level)
    try:
        controller, event_logger, run_id, template_name = create_web_run_controller(
            args
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if template_name:
        logger.info("Using edit template: %s", template_name)

    logger.info("Starting web autonomy run_id=%s cycles=%s", run_id, args.iterations)
    result = controller.run()
    timeline = TimelineBuilder.build(event_logger.get_events(run_id=run_id), run_id=run_id)

    print("\n" + "=" * 60)
    print("WEB AUTONOMY RUN COMPLETE")
    print("=" * 60)
    print(f"Run ID: {result.run_id}")
    print(f"Cycles completed: {result.cycles_completed}")
    print(f"Final status: {result.final_status}")
    print(f"Final action: {result.final_action}")
    print(f"Final reason: {result.final_reason}")
    print(f"Last checkpoint: {result.last_checkpoint_path}")
    print(f"Total events: {timeline.total_events}")
    print("Event counts:")
    for event_type, count in sorted(timeline.event_counts.items()):
        print(f"  - {event_type}: {count}")


if __name__ == "__main__":
    main()
