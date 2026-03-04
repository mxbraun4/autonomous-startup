"""Tests for the workspace HTTP server."""
from __future__ import annotations

import urllib.request
import urllib.error
from pathlib import Path

import pytest

from src.workspace_tools.server import WorkspaceServer


class TestWorkspaceServer:
    """Tests for WorkspaceServer."""

    def test_start_stop(self, tmp_path: Path) -> None:
        """Server reports is_running correctly after start and stop."""
        server = WorkspaceServer(tmp_path)
        try:
            assert not server.is_running
            server.start()
            assert server.is_running
        finally:
            server.stop()
        assert not server.is_running

    def test_serves_files(self, tmp_path: Path) -> None:
        """Server serves files from the workspace directory."""
        index = tmp_path / "index.html"
        index.write_text("<h1>hello</h1>", encoding="utf-8")

        server = WorkspaceServer(tmp_path)
        try:
            url = server.start()
            with urllib.request.urlopen(f"{url}/index.html") as resp:
                body = resp.read().decode("utf-8")
            assert "<h1>hello</h1>" in body
        finally:
            server.stop()

    def test_port_auto_assign(self, tmp_path: Path) -> None:
        """When port=0, the OS assigns a free port (> 0)."""
        server = WorkspaceServer(tmp_path, port=0)
        try:
            server.start()
            assert server.port is not None
            assert server.port > 0
        finally:
            server.stop()

    def test_base_url_format(self, tmp_path: Path) -> None:
        """base_url matches http://127.0.0.1:{port}."""
        server = WorkspaceServer(tmp_path)
        try:
            server.start()
            expected = f"http://127.0.0.1:{server.port}"
            assert server.base_url == expected
        finally:
            server.stop()

    def test_idempotent_start(self, tmp_path: Path) -> None:
        """Calling start() twice returns the same URL."""
        server = WorkspaceServer(tmp_path)
        try:
            url1 = server.start()
            url2 = server.start()
            assert url1 == url2
        finally:
            server.stop()

    def test_404_for_missing(self, tmp_path: Path) -> None:
        """Fetching a nonexistent path returns a 404 status."""
        server = WorkspaceServer(tmp_path)
        try:
            url = server.start()
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"{url}/nonexistent.html")
            assert exc_info.value.code == 404
        finally:
            server.stop()
