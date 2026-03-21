"""Tests for LLM-powered customer testing module."""
import json
import sqlite3
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.simulation.customer_testing import (
    PERSONAS,
    _discover_pages,
    _fetch_page,
    _mock_feedback,
    _normalize_entry,
    _parse_feedback_response,
    _resolve_customer_model,
    run_customer_testing,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _start_test_server(directory: str):
    """Start a temporary HTTP server serving *directory*. Returns (server, base_url)."""
    import functools
    handler = functools.partial(_SilentHandler, directory=directory)
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return httpd, f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# Tests: mock mode
# ---------------------------------------------------------------------------


def test_mock_feedback_returns_three_entries():
    """Mock mode returns exactly 3 deterministic entries."""
    entries = _mock_feedback()
    assert len(entries) == 3
    names = [e["message"].split("]")[0] + "]" for e in entries]
    assert "[Sarah (Founder)]" in names
    assert "[Marcus (VC Partner)]" in names
    assert "[Priya (Casual Visitor)]" in names


def test_mock_mode_writes_to_feedback_db(tmp_path):
    """Mock mode injects feedback entries via _submit_feedback_impl."""
    # Set up workspace root so _submit_feedback_impl works
    from src.workspace_tools import file_tools
    original_root = file_tools._workspace_root
    file_tools._workspace_root = tmp_path

    # Start a minimal server (mock mode doesn't actually fetch pages,
    # but run_customer_testing still needs a base_url arg)
    try:
        result = run_customer_testing(
            base_url="http://127.0.0.1:99999",  # unused in mock mode
            workspace_root=str(tmp_path),
            mock=True,
        )
        assert result["status"] == "ok"
        assert result["feedback_count"] == 3
        assert result["personas_tested"] == 3

        # Verify entries in feedback.db
        db_path = tmp_path / "feedback.db"
        assert db_path.exists()
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute("SELECT * FROM feedback").fetchall()
        assert len(rows) == 3
    finally:
        file_tools._workspace_root = original_root


# ---------------------------------------------------------------------------
# Tests: page discovery
# ---------------------------------------------------------------------------


def test_discover_finds_linked_and_fallback_pages(tmp_path):
    """Page discovery finds pages linked from index.html + fallback names."""
    # Create workspace with index.html linking to about.html
    (tmp_path / "index.html").write_text(
        '<html><body><a href="about.html">About</a></body></html>'
    )
    (tmp_path / "about.html").write_text("<html><body>About page</body></html>")
    (tmp_path / "founders.html").write_text("<html><body>Founders</body></html>")

    httpd, base_url = _start_test_server(str(tmp_path))
    try:
        pages = _discover_pages(base_url, workspace_root=str(tmp_path))
        # Static HTML discovery uses relative paths
        found = set(pages.keys())
        assert any("index" in k for k in found)
        assert any("about" in k for k in found)
        assert any("founders" in k for k in found)
    finally:
        httpd.shutdown()


def test_discover_no_html_pages_falls_back_to_root(tmp_path):
    """When no .html files exist and no app.py, fallback fetches /."""
    (tmp_path / "empty.txt").write_text("not html")
    httpd, base_url = _start_test_server(str(tmp_path))
    try:
        pages = _discover_pages(base_url, workspace_root=str(tmp_path))
        # No .html files, but the fallback fetches "/" which returns
        # a directory listing from the test server.
        assert "/" in pages or len(pages) == 0
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------------------
# Tests: JSON parsing
# ---------------------------------------------------------------------------


def test_parse_valid_json():
    """Parse a clean JSON array response."""
    raw = json.dumps([
        {"page": "index.html", "feedback_type": "bug", "message": "Broken link"},
        {"page": "about.html", "feedback_type": "praise", "message": "Nice design"},
    ])
    entries = _parse_feedback_response(raw, "TestUser")
    assert len(entries) == 2
    assert entries[0]["message"].startswith("[TestUser]")
    assert entries[0]["feedback_type"] == "bug"


def test_parse_markdown_fenced_json():
    """Parse JSON wrapped in markdown code fences."""
    raw = '```json\n[{"page": "index.html", "feedback_type": "friction", "message": "Slow load"}]\n```'
    entries = _parse_feedback_response(raw, "Tester")
    assert len(entries) == 1
    assert "Slow load" in entries[0]["message"]


def test_parse_embedded_json():
    """Parse JSON embedded in surrounding text."""
    raw = 'Here is my feedback:\n[{"page": "index.html", "feedback_type": "praise", "message": "Good"}]\nThat is all.'
    entries = _parse_feedback_response(raw, "Tester")
    assert len(entries) == 1


def test_parse_invalid_type_normalized():
    """Invalid feedback_type is normalized to 'friction'."""
    raw = json.dumps([{"page": "x.html", "feedback_type": "suggestion", "message": "Add search"}])
    entries = _parse_feedback_response(raw, "Tester")
    assert len(entries) == 1
    assert entries[0]["feedback_type"] == "friction"


def test_parse_garbage_returns_empty():
    """Garbage input returns empty list."""
    entries = _parse_feedback_response("this is not json at all!!!", "Tester")
    assert entries == []


# ---------------------------------------------------------------------------
# Tests: full flow with mocked litellm
# ---------------------------------------------------------------------------


def test_full_flow_with_mocked_llm(tmp_path):
    """Full flow: discover pages, call LLM (mocked), write to feedback.db."""
    from src.workspace_tools import file_tools
    original_root = file_tools._workspace_root
    file_tools._workspace_root = tmp_path

    # Create a workspace page
    (tmp_path / "index.html").write_text(
        "<html><body><h1>Startup VC Match</h1><p>Find your investor</p></body></html>"
    )

    httpd, base_url = _start_test_server(str(tmp_path))
    try:
        # Mock litellm.completion to return valid JSON feedback
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            {"page": "index.html", "feedback_type": "friction", "message": "CTA not visible"},
            {"page": "index.html", "feedback_type": "praise", "message": "Clean layout"},
        ])

        with patch("litellm.completion", return_value=mock_response) as mock_completion:
            result = run_customer_testing(
                base_url=base_url,
                workspace_root=str(tmp_path),
                cycle_id=1,
            )

        assert result["status"] == "ok"
        assert result["feedback_count"] > 0
        assert result["personas_tested"] == 3

        # Verify LLM was called 3 times (once per persona)
        assert mock_completion.call_count == 3

        # Verify feedback.db has entries
        db_path = tmp_path / "feedback.db"
        assert db_path.exists()
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute("SELECT * FROM feedback").fetchall()
        assert len(rows) == 6  # 2 entries * 3 personas
    finally:
        httpd.shutdown()
        file_tools._workspace_root = original_root


# ---------------------------------------------------------------------------
# Tests: no-pages early return
# ---------------------------------------------------------------------------


def test_no_pages_early_return(tmp_path):
    """When no pages are discovered, returns early with 0 feedback."""
    from src.workspace_tools import file_tools
    original_root = file_tools._workspace_root
    file_tools._workspace_root = tmp_path

    # Use an unreachable URL so page discovery genuinely finds nothing
    try:
        result = run_customer_testing(
            base_url="http://127.0.0.1:0",
            workspace_root=str(tmp_path),
        )
        assert result["status"] == "ok"
        assert result["feedback_count"] == 0
        assert result["personas_tested"] == 0
    finally:
        file_tools._workspace_root = original_root


# ---------------------------------------------------------------------------
# Tests: event emission
# ---------------------------------------------------------------------------


def test_event_emission(tmp_path):
    """Events are emitted during customer testing."""
    from src.workspace_tools import file_tools
    original_root = file_tools._workspace_root
    file_tools._workspace_root = tmp_path

    events = []

    def capture_event(event_type, payload):
        events.append((event_type, payload))

    try:
        result = run_customer_testing(
            base_url="http://127.0.0.1:99999",
            workspace_root=str(tmp_path),
            emit_fn=capture_event,
            mock=True,
        )
        event_types = [e[0] for e in events]
        assert "customer_testing_start" in event_types
        assert "customer_testing_end" in event_types
    finally:
        file_tools._workspace_root = original_root


# ---------------------------------------------------------------------------
# Tests: model resolution
# ---------------------------------------------------------------------------


def test_model_resolution_priority():
    """customer_model setting takes priority over default."""
    with patch("src.utils.config.settings") as mock_settings:
        mock_settings.customer_model = "my-custom-model"
        mock_settings.openrouter_default_model = "fallback-model"
        assert _resolve_customer_model() == "my-custom-model"


def test_model_resolution_fallback():
    """Falls back to openrouter_default_model when customer_model is empty."""
    with patch("src.utils.config.settings") as mock_settings:
        mock_settings.customer_model = ""
        mock_settings.openrouter_default_model = "fallback-model"
        assert _resolve_customer_model() == "fallback-model"
