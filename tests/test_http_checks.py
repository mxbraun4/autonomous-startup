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
        '<a href="signup.html">Sign Up</a>'
        '<a href="about.html">About</a>'  # broken link
        '</nav>'
        '<h1>Welcome</h1>'
        '</body></html>',
        encoding="utf-8",
    )
    # signup.html with valid form
    (tmp_path / "signup.html").write_text(
        '<html><body>'
        '<form action="#" method="post">'
        '<input name="email" required>'
        '<input name="sector" required>'
        '<input name="stage" required>'
        '<input name="geography" required>'
        '<button type="submit">Submit</button>'
        '</form>'
        '</body></html>',
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

    def test_signup_form_valid(self, served_workspace):
        checker, _ = served_workspace
        result = checker.check_signup_form("/signup.html")
        assert result["page_loads"] is True
        assert result["has_form"] is True
        assert result["has_submit"] is True
        assert result["fields_missing"] == []
        assert set(result["fields_present"]) == {"email", "sector", "stage", "geography"}

    def test_signup_form_missing_page(self, served_workspace):
        checker, _ = served_workspace
        result = checker.check_signup_form("/missing.html")
        assert result["page_loads"] is False
        assert result["has_form"] is False

    def test_navigation_links(self, served_workspace):
        checker, _ = served_workspace
        result = checker.check_navigation_links("/index.html")
        assert result["links_found"] == 3  # index.html, signup.html, about.html
        assert result["links_ok"] == 2     # index and signup exist
        assert result["links_broken"] == 1  # about.html is broken
        assert "about.html" in result["broken_links"]

    def test_run_all_checks(self, served_workspace):
        checker, _ = served_workspace
        result = checker.run_all_checks()
        assert result["http_landing_score"] == 1.0
        assert result["http_signup_score"] == 1.0
        assert 0.0 < result["http_navigation_score"] < 1.0  # some links broken

    def test_signup_score_partial(self, served_workspace):
        """Signup page loads but form is broken -> score 0.3."""
        checker, ws = served_workspace
        # Overwrite signup with a page that loads but has no form
        (ws / "signup.html").write_text(
            "<html><body><p>No form here</p></body></html>",
            encoding="utf-8",
        )
        result = checker.check_signup_form("/signup.html")
        assert result["page_loads"] is True
        assert result["has_form"] is False
        # Check score derivation
        all_results = checker.run_all_checks()
        assert all_results["http_signup_score"] == 0.3
