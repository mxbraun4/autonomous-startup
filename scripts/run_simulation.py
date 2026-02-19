"""Run autonomous startup simulation using CrewAI."""

if __package__:
    from ._bootstrap import add_repo_root_to_path, configure_stdio_utf8
else:
    from _bootstrap import add_repo_root_to_path, configure_stdio_utf8

add_repo_root_to_path(__file__)
configure_stdio_utf8()

from pathlib import Path

from src.crewai_agents import run_build_measure_learn_cycle  # delegates to BuildMeasureLearnFlow
from src.utils.logging import setup_logging, get_logger
from src.utils.config import settings

setup_logging(settings.log_level)
logger = get_logger(__name__)


def _is_writable_directory(path: Path) -> bool:
    """Return True when directory exists and supports write operations."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _resolve_non_legacy_memory_dir(preferred_data_dir: str) -> str:
    """Select a writable directory for non-legacy memory backends."""
    preferred = Path(preferred_data_dir).resolve()
    fallback_runtime = (preferred.parent / f"{preferred.name}_runtime").resolve()
    fallback_project_default = (Path("data") / "memory_runtime").resolve()

    candidates = []
    for candidate in (preferred, fallback_runtime, fallback_project_default):
        if candidate not in candidates:
            candidates.append(candidate)

    checked = []
    for candidate in candidates:
        checked.append(str(candidate))
        # Chroma backend persists under <data_dir>/chroma; both roots must be writable.
        if _is_writable_directory(candidate) and _is_writable_directory(candidate / "chroma"):
            if candidate != preferred:
                logger.warning(
                    "Configured memory directory is not writable for non-legacy storage. "
                    "Using %s (preferred: %s)",
                    candidate,
                    preferred,
                )
            return str(candidate)

    raise RuntimeError(
        "No writable non-legacy memory directory available. Checked: "
        + ", ".join(checked)
    )


def _init_memory_store():
    """Initialise the UnifiedStore and inject it into CrewAI tools."""
    use_legacy = getattr(settings, "memory_use_legacy", False)
    if use_legacy:
        raise RuntimeError(
            "Legacy memory mode is disabled for simulation runs. "
            "Set MEMORY_USE_LEGACY=false."
        )

    from src.framework.storage.unified_store import UnifiedStore
    from src.framework.storage.sync_wrapper import SyncUnifiedStore
    from src.crewai_agents.tools import set_memory_store

    configured_data_dir = getattr(settings, "memory_data_dir", "data/memory")
    data_dir = _resolve_non_legacy_memory_dir(configured_data_dir)
    store = UnifiedStore(use_legacy_stores=False, data_dir=data_dir)

    sync_store = SyncUnifiedStore(store)
    set_memory_store(sync_store)
    logger.info(
        "UnifiedStore initialised and injected into tools "
        "(legacy=False, data_dir=%s)",
        data_dir,
    )
    return sync_store


def _percentage_change(baseline: float, latest: float) -> float | None:
    """Return percent delta from baseline, or None when baseline is zero."""
    if baseline <= 0:
        return None
    return ((latest - baseline) / baseline) * 100.0


def display_results(results: dict) -> None:
    """Display simulation results.

    Args:
        results: Results from Build-Measure-Learn cycles
    """
    print("\n" + "="*60)
    print("CREWAI AUTONOMOUS STARTUP SIMULATION - RESULTS")
    print("="*60)

    print("\nPerformance Evolution:")
    for i, metrics in enumerate(results['metrics_evolution'], 1):
        print(f"\n  Iteration {i}:")
        print(f"    Response rate: {metrics['response_rate']:.1%}")
        print(f"    Meeting rate: {metrics['meeting_rate']:.1%}")
        print(f"    Total sent: {metrics['total_sent']}")
        print(f"    Responses: {metrics['responses']}")
        print(f"    Meetings: {metrics['meetings']}")

    # Calculate improvement
    if len(results['metrics_evolution']) > 1:
        first = results['metrics_evolution'][0]
        last = results['metrics_evolution'][-1]

        response_improvement = _percentage_change(
            first['response_rate'],
            last['response_rate'],
        )
        meeting_improvement = _percentage_change(
            first['meeting_rate'],
            last['meeting_rate'],
        )

        print("\n" + "="*60)
        print("IMPROVEMENT SUMMARY")
        print("="*60)

        if response_improvement is None:
            print(
                f"  Response rate: {first['response_rate']:.1%} -> {last['response_rate']:.1%} "
                "(n/a: zero baseline)"
            )
        else:
            print(
                f"  Response rate: {first['response_rate']:.1%} -> {last['response_rate']:.1%} "
                f"(+{response_improvement:.0f}%)"
            )

        if meeting_improvement is None:
            print(
                f"  Meeting rate: {first['meeting_rate']:.1%} -> {last['meeting_rate']:.1%} "
                "(n/a: zero baseline)"
            )
        else:
            print(
                f"  Meeting rate: {first['meeting_rate']:.1%} -> {last['meeting_rate']:.1%} "
                f"(+{meeting_improvement:.0f}%)"
            )

    print("\n" + "="*60)
    print("SIMULATION COMPLETE")
    print("="*60)
    print("\nKey Takeaways:")
    print("  [OK] CrewAI agents coordinated hierarchically")
    print("  [OK] Memory enabled learning across iterations")
    print("  [OK] Performance improved through adaptation")
    print("  [OK] Tools (scraper, content generator, etc.) integrated successfully")
    print()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run CrewAI autonomous startup simulation"
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=3,
        help='Number of Build-Measure-Learn iterations (default: 3)'
    )
    parser.add_argument(
        '--verbose',
        type=int,
        default=2,
        choices=[0, 1, 2],
        help='Verbosity level: 0=quiet, 1=normal, 2=detailed (default: 2)'
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print("CREWAI AUTONOMOUS STARTUP SIMULATION")
    print("="*60)
    print(f"  Iterations: {args.iterations}")
    print(f"  Verbosity: {args.verbose}")
    print(f"  Mock Mode: {settings.mock_mode}")
    print("="*60 + "\n")

    logger.info(f"Starting CrewAI simulation with {args.iterations} iterations")

    # Initialise memory system
    _init_memory_store()

    # Run Build-Measure-Learn cycles
    results = run_build_measure_learn_cycle(
        iterations=args.iterations,
        verbose=args.verbose
    )

    # Display results
    display_results(results)


if __name__ == "__main__":
    main()
