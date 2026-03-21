"""Run autonomous startup simulation using CrewAI."""

if __package__:
    from ._bootstrap import add_repo_root_to_path, configure_stdio_utf8
else:
    from _bootstrap import add_repo_root_to_path, configure_stdio_utf8

add_repo_root_to_path(__file__)
configure_stdio_utf8()

import threading
import webbrowser
from pathlib import Path

from src.crewai_agents import run_build_measure_learn_cycle  # delegates to BuildMeasureLearnFlow
from src.utils.logging import setup_logging, get_logger
from src.utils.config import settings

setup_logging(settings.log_level)
logger = get_logger(__name__)


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
        except Exception as exc:  # pragma: no cover - exercised via runtime fallback
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
    return sync_store


def _assert_writable_directory(path: Path) -> None:
    """Raise if a directory path cannot be written to."""
    probe = path / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _start_dashboard(port: int = 8765, open_browser: bool = True) -> str | None:
    """Start the live dashboard server on a daemon thread.

    Returns the dashboard URL, or None if the server fails to start.
    """
    from scripts.live_dashboard import DashboardServer, DashboardHandler

    repo_root = Path(__file__).resolve().parent.parent
    events_path = repo_root / "data" / "memory" / "web_autonomy_events.ndjson"
    workspace = repo_root / "workspace"

    try:
        server = DashboardServer(
            ("127.0.0.1", port),
            DashboardHandler,
            events_path=events_path,
            max_events=8000,
            recent_limit=80,
            refresh_ms=1200,
            workspace=workspace if workspace.is_dir() else None,
        )
    except OSError as exc:
        logger.warning("Dashboard server failed to bind port %s: %s", port, exc)
        return None

    url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
    thread.start()

    logger.info("Live dashboard started at %s", url)
    print(f"  Dashboard: {url}")

    if open_browser:
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    return url


def _start_preview_server(port: int = 8080, open_browser: bool = True) -> str | None:
    """Start the workspace preview server on a daemon thread.

    If the workspace contains ``app.py``, launches it as a Flask subprocess.
    Otherwise falls back to the static preview server.

    Returns the preview URL, or None if the server fails to start.
    """
    from scripts.serve_workspace import PreviewServer, PreviewHandler

    workspace = Path(__file__).resolve().parent.parent / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # Write Flask app placeholder so the server has something to show immediately
    app_py = workspace / "app.py"
    templates_dir = workspace / "templates"
    if not app_py.exists():
        templates_dir.mkdir(parents=True, exist_ok=True)
        app_py.write_text(
            'import os\n'
            'from flask import Flask, render_template\n'
            '\n'
            'app = Flask(__name__)\n'
            '\n'
            "@app.route('/')\n"
            'def index():\n'
            "    return render_template('index.html')\n"
            '\n'
            "if __name__ == '__main__':\n"
            "    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')\n"
            "    port = int(os.environ.get('FLASK_RUN_PORT', '5000'))\n"
            '    app.run(host=host, port=port, debug=False)\n',
            encoding="utf-8",
        )
        (templates_dir / "index.html").write_text(
            '<!DOCTYPE html>\n'
            '<html>\n'
            '<head><title>Startup-VC Matching Platform</title></head>\n'
            '<body>\n'
            '<h1>Startup-VC Matching Platform</h1>\n'
            '<p>Waiting for agents to build...</p>\n'
            '</body>\n'
            '</html>\n',
            encoding="utf-8",
        )

    try:
        server = PreviewServer(
            ("127.0.0.1", port),
            PreviewHandler,
            workspace=workspace,
        )
    except OSError as exc:
        logger.warning("Preview server failed to bind port %s: %s", port, exc)
        return None

    url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
    thread.start()

    logger.info("Workspace preview started at %s", url)
    print(f"  Preview: {url}")

    if open_browser:
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    return url


def display_results(results: dict) -> None:
    """Display simulation results.

    Args:
        results: Results from Build-Evaluate-Learn cycles
    """
    print("\n" + "="*60)
    print("CREWAI AUTONOMOUS STARTUP SIMULATION - RESULTS")
    print("="*60)

    metrics = results.get("metrics_evolution", [])
    learnings = results.get("learnings", [])

    print("\nPerformance Evolution:")
    for i, m in enumerate(metrics, 1):
        qa = "PASS" if m.get("qa_passed") else "FAIL"
        tasks = m.get("task_count", "?")
        successes = m.get("success_count", "?")
        failures = m.get("failure_count", "?")
        print(f"\n  Iteration {i}:")
        print(f"    QA gate: {qa}")
        print(f"    Tasks: {tasks} (success={successes}, fail={failures})")

    # QA pass rate
    if metrics:
        passes = sum(1 for m in metrics if m.get("qa_passed"))
        print(f"\n  QA pass rate: {passes}/{len(metrics)}")

    print("\n" + "="*60)
    print("SIMULATION COMPLETE")
    print("="*60)

    if metrics:
        print(f"\n  Iterations executed: {len(metrics)}")
    else:
        print("\n  [WARN] No iterations completed.")

    if learnings:
        print(f"  [OK] {len(learnings)} learning(s) captured")
    else:
        print("  [--] No structured learnings captured")

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
        default=400,
        help='Number of Build-Measure-Learn iterations (default: 400)'
    )
    parser.add_argument(
        '--verbose',
        type=int,
        default=2,
        choices=[0, 1, 2],
        help='Verbosity level: 0=quiet, 1=normal, 2=detailed (default: 2)'
    )
    parser.add_argument(
        '--no-preview',
        action='store_true',
        help='Disable the auto-starting workspace preview server',
    )
    parser.add_argument(
        '--no-workspace',
        action='store_true',
        help='Disable workspace file tools for agents',
    )
    parser.add_argument(
        '--preview-port',
        type=int,
        default=8080,
        help='Port for the workspace preview server (default: 8080)',
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

    # Initialise event logger for observability
    from src.framework.observability.logger import EventLogger
    from src.crewai_agents.tools import set_event_logger

    events_path = Path(__file__).resolve().parent.parent / "data" / "memory" / "web_autonomy_events.ndjson"
    event_logger = EventLogger(persist_path=str(events_path))
    set_event_logger(event_logger)
    logger.info("EventLogger initialised (persist_path=%s)", events_path)

    # Configure workspace file tools for agents
    if not args.no_workspace:
        from src.workspace_tools.file_tools import configure_workspace_root
        workspace_path = Path(__file__).resolve().parent.parent / "workspace"
        workspace_path.mkdir(parents=True, exist_ok=True)
        configure_workspace_root(str(workspace_path))
        logger.info("Workspace root configured at %s", workspace_path)

    # Start live dashboard in background
    _start_dashboard(
        port=8765,
        open_browser=not args.no_preview,
    )

    # Start workspace preview server in background
    preview_url = _start_preview_server(
        port=args.preview_port,
        open_browser=not args.no_preview,
    )

    # Run Build-Measure-Learn cycles
    results = run_build_measure_learn_cycle(
        iterations=args.iterations,
        verbose=args.verbose
    )

    # Display results
    display_results(results)


if __name__ == "__main__":
    main()
