"""Run localhost web-product autonomy with the framework runtime stack."""

from __future__ import annotations

import argparse
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run autonomous localhost web-product iteration",
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
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--list-edit-templates", action="store_true")
    parser.add_argument("--edit-template-file", default="data/seed/web_edit_templates.json")
    edit_group = parser.add_mutually_exclusive_group()
    edit_group.add_argument("--edit-template", default="")
    edit_group.add_argument("--edit-path", default="")
    parser.add_argument("--edit-search", default="")
    parser.add_argument("--edit-replace", default="")
    parser.add_argument("--edit-dry-run", action="store_true")
    return parser.parse_args()


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


def main() -> None:
    args = _parse_args()
    if args.list_edit_templates:
        _print_edit_templates(args.edit_template_file)
        return

    setup_logging(args.log_level)

    run_id = args.run_id or f"web_autonomy_{int(time.time())}"
    try:
        edit_instruction, policy_overrides, template_name = _default_edit_instruction(
            args
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

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

    run_config = RunConfig(
        run_id=run_id,
        seed=args.seed,
        max_cycles=args.iterations,
        max_steps_per_cycle=args.max_steps_per_cycle,
        budget_seconds=args.budget_seconds,
        budget_tokens=args.budget_tokens,
        autonomy_level=args.autonomy_level,
        policies=dict(domain_policies),
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
