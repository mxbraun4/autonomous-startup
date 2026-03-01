"""Lightweight HTTP server for the workspace directory."""
from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional


class _SilentHandler(SimpleHTTPRequestHandler):
    """HTTP handler that suppresses request logging."""

    def log_message(self, format, *args):
        pass  # Suppress console output


class WorkspaceServer:
    """Serves static files from a workspace directory on a background thread.

    Usage:
        server = WorkspaceServer("workspace/")
        url = server.start()   # e.g. "http://127.0.0.1:54321"
        ...
        server.stop()
    """

    def __init__(
        self,
        workspace_root: str | Path,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._host = host
        self._port = port
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    @property
    def port(self) -> Optional[int]:
        if self._httpd is None:
            return None
        return self._httpd.server_address[1]

    @property
    def base_url(self) -> Optional[str]:
        if not self.is_running:
            return None
        return f"http://{self._host}:{self.port}"

    def start(self) -> str:
        """Start the server. Returns the base URL. Idempotent."""
        if self.is_running:
            return self.base_url

        handler = functools.partial(
            _SilentHandler,
            directory=str(self._workspace_root),
        )
        self._httpd = HTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True,
        )
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        """Stop the server."""
        if self._httpd is not None:
            self._httpd.shutdown()
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._httpd.server_close()
            self._httpd = None
            self._thread = None
