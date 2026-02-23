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


class TestAdapterWithWorkspaceCreatesBuilderTask:
    """When workspace_root is set, the first task should be website_builder."""

    def test_adapter_with_workspace_creates_builder_task(self, tmp_path: Path) -> None:
        ws = _create_workspace(tmp_path)
        adapter = StartupVCAdapter(
            workspace_root=str(ws),
            use_customer_simulation=False,
        )
        ctx = _FakeContext(run_id="run_ws", cycle_id=3)

        tasks = adapter.build_cycle_tasks(ctx)

        assert len(tasks) >= 1, "Expected at least one task"
        first = tasks[0]
        assert first.agent_role == "website_builder"
        assert first.priority == 0


class TestAdapterWithoutWorkspaceNoBuilderTask:
    """Without workspace_root no website_builder task should appear."""

    def test_adapter_without_workspace_no_builder_task(self) -> None:
        adapter = StartupVCAdapter(use_customer_simulation=False)
        ctx = _FakeContext()

        tasks = adapter.build_cycle_tasks(ctx)

        roles = [t.agent_role for t in tasks]
        assert "website_builder" not in roles, (
            "website_builder task must not appear when workspace_root is None"
        )


class TestHTTPChecksMergeIntoSimulation:
    """Start the workspace server, run simulate_environment, verify http_checks."""

    def test_http_checks_merge_into_simulation(self, tmp_path: Path) -> None:
        ws = _create_workspace(tmp_path)
        adapter = StartupVCAdapter(
            workspace_root=str(ws),
            use_customer_simulation=False,
        )
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
        assert "http_signup_score" in checks
        assert "http_navigation_score" in checks


class TestVersioningThroughAdapter:
    """snapshot_workspace should create a versioned copy."""

    def test_versioning_through_adapter(self, tmp_path: Path) -> None:
        ws = _create_workspace(tmp_path)
        adapter = StartupVCAdapter(
            workspace_root=str(ws),
            use_customer_simulation=False,
        )

        snap = adapter.snapshot_workspace(1)

        assert snap is not None, "snapshot_workspace must return a dict"
        assert snap["cycle_id"] == 1
        snapshot_path = Path(snap["path"])
        assert snapshot_path.exists(), "Snapshot directory must exist on disk"
        assert snap["file_count"] >= 2, (
            "Snapshot should contain at least index.html and signup.html"
        )


class TestCustomerParamsBoostedByHTTPChecks:
    """With HTTP check results set, _customer_params should return higher values."""

    def test_customer_params_boosted_by_http_checks(self, tmp_path: Path) -> None:
        ws = _create_workspace(tmp_path)
        adapter = StartupVCAdapter(
            workspace_root=str(ws),
            use_customer_simulation=False,
        )

        # Baseline params (no HTTP checks)
        baseline = adapter._customer_params(success_rate=0.5)

        # Inject known HTTP check scores
        adapter._http_check_results = {
            "http_signup_score": 1.0,
            "http_navigation_score": 1.0,
            "http_landing_score": 1.0,
        }
        boosted = adapter._customer_params(success_rate=0.5)

        # The boost logic adds positive deltas for three specific keys:
        #   derived_personalization_score_boost  += signup_score * 0.15
        #   founder_base_interest               += nav_score   * 0.10
        #   vc_base_interest                    += landing_score* 0.10
        assert boosted["derived_personalization_score_boost"] > baseline["derived_personalization_score_boost"], (
            "Personalization boost must increase with signup_score"
        )
        assert boosted["founder_base_interest"] > baseline["founder_base_interest"], (
            "Founder interest must increase with nav_score"
        )
        assert boosted["vc_base_interest"] > baseline["vc_base_interest"], (
            "VC interest must increase with landing_score"
        )
