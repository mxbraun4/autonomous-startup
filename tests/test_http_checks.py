"""Tests for HTTP workspace checks."""
import pytest
from pathlib import Path

from src.workspace_tools.server import WorkspaceServer
from src.simulation.http_checks import WorkspaceHTTPChecker


@pytest.fixture
def workspace_dir(tmp_path):
    """Create a minimal workspace for testing."""
    # index.html with nav links
    (tmp_path / "index.html").write_text(
        '<html><body>'
        '<nav>'
        '<a href="index.html">Home</a>'
        '<a href="founders.html">Founders</a>'
        '<a href="about.html">About</a>'  # broken link
        '</nav>'
        '<h1>Welcome</h1>'
        '</body></html>',
        encoding="utf-8",
    )
    # founders.html
    (tmp_path / "founders.html").write_text(
        '<html><body><h1>Founders</h1></body></html>',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def served_workspace(workspace_dir):
    """Start a server and yield (checker, workspace_dir)."""
    server = WorkspaceServer(workspace_dir)
    url = server.start()
    try:
        yield WorkspaceHTTPChecker(url), workspace_dir
    finally:
        server.stop()


class TestHTTPChecks:
    def test_page_loads_success(self, served_workspace):
        checker, _ = served_workspace
        result = checker.check_page_loads("/index.html")
        assert result["loaded"] is True
        assert result["status"] == "ok"

    def test_page_loads_missing(self, served_workspace):
        checker, _ = served_workspace
        result = checker.check_page_loads("/nonexistent.html")
        assert result["loaded"] is False

    def test_navigation_links(self, served_workspace):
        checker, _ = served_workspace
        result = checker.check_navigation_links("/index.html")
        assert result["links_found"] == 3  # index.html, founders.html, about.html
        assert result["links_ok"] == 2     # index and founders exist
        assert result["links_broken"] == 1  # about.html is broken
        assert "about.html" in result["broken_links"]

    def test_run_all_checks(self, served_workspace):
        checker, _ = served_workspace
        result = checker.run_all_checks()
        assert result["http_landing_score"] == 1.0
        assert "http_signup_score" not in result
        assert 0.0 < result["http_navigation_score"] < 1.0  # some links broken
