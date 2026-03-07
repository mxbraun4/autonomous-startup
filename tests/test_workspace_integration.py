"""Integration tests for workspace feature wired through StartupVCAdapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from src.framework.adapters.startup_vc import StartupVCAdapter


# ---------------------------------------------------------------------------
# Lightweight fakes -- no external dependencies
# ---------------------------------------------------------------------------


class _FakeContext:
    def __init__(self, run_id: str = "test_run", cycle_id: int = 1):
        self.run_id = run_id
        self.cycle_id = cycle_id


class _FakeCycleOutputs:
    def __init__(
        self, total: int = 2, completed: int = 2, failed: int = 0, skipped: int = 0
    ):
        self.total_tasks = total
        self.completed_count = completed
        self.failed_count = failed
        self.skipped_count = skipped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INDEX_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Marketplace</title></head>
<body>
<nav>
  <a href="signup.html">Sign Up</a>
</nav>
<h1>Welcome</h1>
</body>
</html>
"""

_SIGNUP_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Sign Up</title></head>
<body>
<form action="/submit" method="post">
  <input type="text" name="email" />
  <input type="text" name="sector" />
  <input type="text" name="stage" />
  <input type="text" name="geography" />
  <button type="submit">Register</button>
</form>
</body>
</html>
"""


def _create_workspace(base: Path) -> Path:
    """Create a minimal workspace directory with index.html and signup.html."""
    ws = base / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    (ws / "signup.html").write_text(_SIGNUP_HTML, encoding="utf-8")
    return ws


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAdapterWithWorkspaceCreatesCoordinatorTask:
    """When workspace_root is set, the adapter should emit a single coordinator task."""

    def test_adapter_with_workspace_creates_coordinator_task(self, tmp_path: Path) -> None:
        ws = _create_workspace(tmp_path)
        adapter = StartupVCAdapter(workspace_root=str(ws))
        ctx = _FakeContext(run_id="run_ws", cycle_id=3)

        tasks = adapter.build_cycle_tasks(ctx)

        assert len(tasks) == 1, "Expected exactly one coordinator task"
        first = tasks[0]
        assert first.agent_role == "coordinator"
        assert "coordinator" in first.task_id
        assert first.priority == 0


class TestAdapterWithoutWorkspaceNoCoordinatorTask:
    """Without workspace_root no coordinator task should appear."""

    def test_adapter_without_workspace_no_coordinator_task(self) -> None:
        adapter = StartupVCAdapter()
        ctx = _FakeContext()

        tasks = adapter.build_cycle_tasks(ctx)

        roles = [t.agent_role for t in tasks]
        assert "coordinator" not in roles, (
            "coordinator task must not appear when workspace_root is None"
        )
        assert "data_specialist" in roles
        assert len(tasks) == 1, "Expected exactly one data_specialist task"


class TestCoordinatorReceivesHTTPChecksInInputData:
    """Coordinator input_data should contain HTTP checks from previous cycle."""

    def test_coordinator_receives_http_checks(self, tmp_path: Path) -> None:
        ws = _create_workspace(tmp_path)
        adapter = StartupVCAdapter(workspace_root=str(ws))
        # Inject previous HTTP check results
        adapter._http_check_results = {
            "http_landing_score": 0.8,
            "http_navigation_score": 0.7,
        }
        ctx = _FakeContext(run_id="run_fb", cycle_id=2)

        tasks = adapter.build_cycle_tasks(ctx)
        first = tasks[0]

        assert "previous_http_checks" in first.input_data
        assert first.input_data["previous_http_checks"]["http_landing_score"] == 0.8
        assert first.input_data["previous_http_checks"]["http_navigation_score"] == 0.7


class TestHTTPChecksMergeIntoSimulation:
    """Start the workspace server, run simulate_environment, verify http_checks."""

    def test_http_checks_merge_into_simulation(self, tmp_path: Path) -> None:
        ws = _create_workspace(tmp_path)
        adapter = StartupVCAdapter(workspace_root=str(ws))
        ctx = _FakeContext(run_id="run_http", cycle_id=1)
        outputs = _FakeCycleOutputs(total=2, completed=2, failed=0, skipped=0)

        try:
            result = adapter.simulate_environment(outputs, ctx)
        finally:
            adapter.stop_workspace_server()

        assert "http_checks" in result, (
            "simulate_environment result must contain 'http_checks' when workspace is active"
        )
        checks = result["http_checks"]
        # Verify derived score keys produced by WorkspaceHTTPChecker.run_all_checks
        assert "http_landing_score" in checks
        assert "http_navigation_score" in checks


