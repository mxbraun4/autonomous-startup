"""Run startup-VC autonomy through the full framework runtime stack.

Wires the StartupVCAdapter with CrewAI-backed agents via the framework's
RunController, evaluation gates, checkpointing, adaptive policy, and
diagnostics — providing the same governance layer that run_web_autonomy.py
provides for the web-product domain.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Tuple

if __package__:
    from ._bootstrap import add_repo_root_to_path, configure_stdio_utf8
else:
    from _bootstrap import add_repo_root_to_path, configure_stdio_utf8

add_repo_root_to_path(__file__)
configure_stdio_utf8()

from src.framework.adapters import StartupVCAdapter
from src.framework.autonomy import RunController
from src.framework.contracts import RunConfig
from src.framework.eval.evaluator import Evaluator
from src.framework.observability import EventLogger, TimelineBuilder
from src.framework.orchestration.executor import Executor
from src.framework.runtime import (
    AgentRuntime,
    CapabilityRegistry,
    ExecutionContext,
    TaskRouter,
    register_startup_vc_agents,
    register_startup_vc_capabilities,
    register_workspace_capabilities,
)
from src.framework.safety import build_startup_vc_domain_policy_hook, create_action_guard
from src.utils.config import settings
from src.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Memory initialisation (mirrors run_simulation.py)
# ---------------------------------------------------------------------------

def _assert_writable_directory(path: Path) -> None:
    probe = path / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _init_memory_store():
    """Initialise the UnifiedStore and inject it into CrewAI tools."""
    from src.framework.storage.unified_store import UnifiedStore
    from src.framework.storage.sync_wrapper import SyncUnifiedStore
    from src.crewai_agents.tools import set_memory_store

    preferred_dir = Path(settings.memory_data_dir).resolve()
    fallback_dir = Path("data/memory_runtime").resolve()
    candidates = [preferred_dir]
    if fallback_dir != preferred_dir:
        candidates.append(fallback_dir)

    store = None
    selected_dir = None
    last_error = None
    for candidate in candidates:
        candidate.mkdir(parents=True, exist_ok=True)
        try:
            _assert_writable_directory(candidate)
            store = UnifiedStore(data_dir=str(candidate))
            selected_dir = candidate
            break
        except Exception as exc:
            last_error = exc
            logger.warning(
                "UnifiedStore init failed for data_dir=%s (%s)",
                candidate,
                exc,
            )
            continue

    if store is None or selected_dir is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("UnifiedStore initialisation failed for all memory directories")

    sync_store = SyncUnifiedStore(store)
    set_memory_store(sync_store)
    logger.info(
        "UnifiedStore initialised and injected into tools (data_dir=%s)",
        selected_dir,
    )
    return sync_store, selected_dir


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run startup-VC autonomy through the framework runtime stack",
    )
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--checkpoint-dir", default="data/memory/checkpoints_startup")
    parser.add_argument(
        "--events-path",
        default="data/memory/startup_autonomy_events.ndjson",
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--autonomy-level", type=int, default=1)
    parser.add_argument("--max-steps-per-cycle", type=int, default=50)
    parser.add_argument("--budget-seconds", type=float, default=None)
    parser.add_argument("--budget-tokens", type=int, default=None)
    parser.add_argument("--max-targets-per-cycle", type=int, default=5)
    parser.add_argument("--use-customer-simulation", action="store_true", default=True)
    parser.add_argument("--no-customer-simulation", dest="use_customer_simulation", action="store_false")
    parser.add_argument("--customer-seed-path", default=None)
    parser.add_argument("--include-visitors", action="store_true", default=False)
    parser.add_argument("--product-events-path", default=None)
    parser.add_argument("--product-surface-only", action="store_true", default=False)
    parser.add_argument("--match-calibration-path", default=None)
    parser.add_argument("--match-calibration-min-samples", type=int, default=20)
    parser.add_argument("--workspace-root", default="workspace")
    parser.add_argument("--no-workspace", dest="workspace_enabled", action="store_false", default=True)
    parser.add_argument("--log-level", default="INFO")
    return parser


def _parse_args() -> argparse.Namespace:
    return _build_arg_parser().parse_args()


# ---------------------------------------------------------------------------
# Controller factory (mirrors create_web_run_controller)
# ---------------------------------------------------------------------------

def create_startup_vc_run_controller(
    args: argparse.Namespace,
    store: Any = None,
) -> Tuple[RunController, EventLogger, str]:
    """Create a fully wired startup-VC run controller."""
    run_id = args.run_id or f"startup_vc_{int(time.time())}"

    workspace_enabled = getattr(args, "workspace_enabled", True)
    workspace_root = getattr(args, "workspace_root", "workspace") if workspace_enabled else None

    # Configure workspace file tools root before agent registration
    if workspace_root:
        ws_path = Path(workspace_root).resolve()
        ws_path.mkdir(parents=True, exist_ok=True)
        from src.workspace_tools.file_tools import configure_workspace_root
        configure_workspace_root(str(ws_path))

    adapter = StartupVCAdapter(
        max_targets_per_cycle=args.max_targets_per_cycle,
        use_customer_simulation=args.use_customer_simulation,
        customer_seed_path=args.customer_seed_path,
        include_visitors=args.include_visitors,
        product_events_path=args.product_events_path,
        product_surface_only=args.product_surface_only,
        simulation_seed=args.seed,
        match_calibration_path=args.match_calibration_path,
        match_calibration_min_samples=args.match_calibration_min_samples,
        workspace_root=workspace_root,
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

    event_logger = EventLogger(persist_path=args.events_path)
    context = ExecutionContext(run_config=run_config, store=store)

    registry = CapabilityRegistry()
    register_startup_vc_capabilities(registry)
    if workspace_root:
        register_workspace_capabilities(registry)

    router = TaskRouter(registry)
    domain_policy_hook = build_startup_vc_domain_policy_hook(run_config.policies)
    action_guard = create_action_guard(
        run_config, context, domain_policy_hook=domain_policy_hook
    )

    runtime = AgentRuntime(
        registry=registry,
        router=router,
        store=store,
        context=context,
        policy_engine=action_guard,
        event_emitter=event_logger,
    )

    # Allow per-role LLM selection (e.g., OpenRouter model routing) inside
    # the registered CrewAI agent wrappers.
    register_startup_vc_agents(
        router, runtime, llm=None, enable_workspace=bool(workspace_root),
    )

    executor = Executor(runtime=runtime, context=context, event_emitter=event_logger)
    controller = RunController(
        run_config=run_config,
        executor=executor,
        domain_adapter=adapter,
        evaluator=Evaluator(event_emitter=event_logger),
        store=store,
        checkpoint_dir=args.checkpoint_dir,
        event_emitter=event_logger,
        context=context,
    )
    return controller, event_logger, run_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    setup_logging(args.log_level)

    print("\n" + "=" * 60)
    print("FRAMEWORK + CREWAI STARTUP-VC SIMULATION")
    print("=" * 60)
    print(f"  Iterations: {args.iterations}")
    print(f"  Autonomy level: {args.autonomy_level}")
    print(f"  Customer simulation: {args.use_customer_simulation}")
    print(f"  Workspace: {args.workspace_root if args.workspace_enabled else 'disabled'}")
    print(f"  Mock mode: {settings.mock_mode}")
    print("=" * 60 + "\n")

    sync_store, memory_dir = _init_memory_store()

    try:
        controller, event_logger, run_id = create_startup_vc_run_controller(
            args, store=sync_store
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    logger.info("Starting framework run_id=%s cycles=%s", run_id, args.iterations)
    result = controller.run()
    timeline = TimelineBuilder.build(
        event_logger.get_events(run_id=run_id),
        run_id=run_id,
    )

    print("\n" + "=" * 60)
    print("STARTUP-VC FRAMEWORK RUN COMPLETE")
    print("=" * 60)
    print(f"Run ID: {result.run_id}")
    print(f"Cycles completed: {result.cycles_completed}")
    print(f"Final status: {result.final_status}")
    print(f"Final action: {result.final_action}")
    print(f"Final reason: {result.final_reason}")
    print(f"Last checkpoint: {result.last_checkpoint_path}")
    print(f"Total events: {timeline.total_events}")
    print(f"Memory store: {memory_dir}")
    print("Event counts:")
    for event_type, count in sorted(timeline.event_counts.items()):
        print(f"  - {event_type}: {count}")


if __name__ == "__main__":
    main()
