"""Tests for localhost web-autonomy tool implementations."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer

from src.framework.runtime.localhost_tools import LocalhostAutonomyToolset


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


def test_browser_navigate_allows_localhost_and_blocks_external(tmp_path):
    (tmp_path / "index.html").write_text(
        "<html><head><title>Local App</title></head><body>Hello</body></html>",
        encoding="utf-8",
    )
    server, thread, base_url = _serve_directory(tmp_path)
    try:
        toolset = LocalhostAutonomyToolset(
            workspace_root=str(tmp_path),
            target_url=base_url,
        )
        success = toolset.browser_navigate(url=base_url, cycle_id=1)
        assert success["status"] == "success"
        assert "Local App" in success.get("title", "")

        denied = toolset.browser_navigate(url="https://example.com", cycle_id=1)
        assert denied["status"] == "denied"
        assert denied["reason"] == "non_localhost_url"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_code_edit_enforces_workspace_and_cycle_limits(tmp_path):
    file_path = tmp_path / "app.txt"
    file_path.write_text("hello world", encoding="utf-8")
    outside = tmp_path.parent / "outside_edit.txt"
    outside.write_text("outside", encoding="utf-8")

    toolset = LocalhostAutonomyToolset(
        workspace_root=str(tmp_path),
        target_url="http://localhost:3000",
        max_edits_per_cycle=1,
    )

    first = toolset.code_edit(
        path="app.txt",
        search="world",
        replace="agent",
        cycle_id=1,
    )
    assert first["status"] == "success"
    assert file_path.read_text(encoding="utf-8") == "hello agent"

    second = toolset.code_edit(
        path="app.txt",
        search="agent",
        replace="team",
        cycle_id=1,
    )
    assert second["status"] == "denied"
    assert second["reason"] == "edit_limit_exceeded"

    denied_path = toolset.code_edit(
        path=str(outside),
        search="outside",
        replace="blocked",
        cycle_id=2,
    )
    assert denied_path["status"] == "denied"
    assert denied_path["reason"] == "path_outside_workspace"


def test_run_tests_and_restart_requirements(tmp_path):
    toolset = LocalhostAutonomyToolset(
        workspace_root=str(tmp_path),
        target_url="http://localhost:3000",
        test_command='python -c "print(\'ok\')"',
        restart_command='python -c "print(\'restart\')"',
    )

    failed = toolset.run_tests(
        command='python -c "import sys; sys.exit(1)"',
        cycle_id=1,
    )
    assert failed["status"] == "failed"
    denied_restart = toolset.restart_service(cycle_id=1)
    assert denied_restart["status"] == "denied"
    assert denied_restart["reason"] == "tests_not_passed_in_cycle"

    passed = toolset.run_tests(
        command='python -c "print(\'tests_passed\')"',
        cycle_id=1,
    )
    assert passed["status"] == "success"
    allowed_restart = toolset.restart_service(cycle_id=1)
    assert allowed_restart["status"] == "success"

