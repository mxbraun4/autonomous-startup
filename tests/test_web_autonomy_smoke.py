"""Smoke test for localhost web autonomy runtime wiring."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer

from src.framework.adapters import WebProductAdapter
from src.framework.autonomy import RunController
from src.framework.contracts import RunConfig
from src.framework.observability import EventLogger
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
from src.framework.safety import build_web_domain_policy_hook, create_action_guard


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        del format, args
        return


class _ReusableTCPServer(TCPServer):
    allow_reuse_address = True


def _serve_directory(directory: Path):
    handler = partial(_QuietHandler, directory=str(directory))
    server = _ReusableTCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    return server, thread, base_url


def test_web_autonomy_single_cycle_smoke(tmp_path):
    (tmp_path / "index.html").write_text(
        "<html><head><title>Smoke App</title></head><body>ok</body></html>",
        encoding="utf-8",
    )
    target_file = tmp_path / "page.txt"
    target_file.write_text("old value", encoding="utf-8")

    server, thread, base_url = _serve_directory(tmp_path)
    try:
        adapter = WebProductAdapter(
            target_url=base_url,
            workspace_root=str(tmp_path),
            test_command='python -c "print(\'tests_pass\')"',
            restart_command='python -c "print(\'restart_ok\')"',
            max_edits_per_cycle=1,
            default_edit_instruction={
                "path": "page.txt",
                "search": "old value",
                "replace": "new value",
                "dry_run": False,
            },
        )

        run_config = RunConfig(
            run_id="web_smoke_run",
            seed=7,
            max_cycles=1,
            max_steps_per_cycle=20,
            autonomy_level=1,
            policies=adapter.get_domain_policies(),
        )

        toolset = LocalhostAutonomyToolset(
            workspace_root=str(tmp_path),
            target_url=base_url,
            test_command='python -c "print(\'tests_pass\')"',
            restart_command='python -c "print(\'restart_ok\')"',
            max_edits_per_cycle=1,
        )
        event_logger = EventLogger()

        context = ExecutionContext(run_config=run_config, store=None)
        registry = CapabilityRegistry()
        register_web_capabilities(registry, toolset)
        router = TaskRouter(registry)
        domain_hook = build_web_domain_policy_hook(
            run_config.policies,
            toolset_state_accessor=toolset.get_state,
        )
        guard = create_action_guard(
            run_config,
            context,
            domain_policy_hook=domain_hook,
        )
        runtime = AgentRuntime(
            registry=registry,
            router=router,
            store=None,
            context=context,
            policy_engine=guard,
            event_emitter=event_logger,
        )
        register_web_agents(router, runtime, default_url=base_url)

        executor = Executor(runtime=runtime, context=context, event_emitter=event_logger)
        controller = RunController(
            run_config=run_config,
            executor=executor,
            domain_adapter=adapter,
            checkpoint_dir=str(tmp_path / "checkpoints"),
            event_emitter=event_logger,
            context=context,
        )
        result = controller.run()

        assert result.cycles_completed == 1
        assert result.final_status == "completed"
        assert target_file.read_text(encoding="utf-8") == "new value"

        event_types = {event.event_type for event in event_logger.get_events(run_id="web_smoke_run")}
        assert "run_start" in event_types
        assert "cycle_start" in event_types
        assert "cycle_end" in event_types
        assert "run_end" in event_types
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

