"""Lightweight HTTP server for the workspace directory."""
from __future__ import annotations

import datetime
import functools
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import urlopen

# ---------------------------------------------------------------------------
# SQLite helpers for the feedback database
# ---------------------------------------------------------------------------

_feedback_db_lock = threading.Lock()


def _init_feedback_db(db_path: str) -> None:
    """Create the feedback table if it does not exist."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS feedback ("
            "  id TEXT PRIMARY KEY,"
            "  timestamp TEXT NOT NULL,"
            "  page TEXT NOT NULL,"
            "  feedback_type TEXT NOT NULL,"
            "  message TEXT NOT NULL"
            ")"
        )
        conn.commit()


class _SilentHandler(SimpleHTTPRequestHandler):
    """HTTP handler that suppresses request logging."""

    def log_message(self, format, *args):
        pass  # Suppress console output


class _FeedbackHandler(_SilentHandler):
    """HTTP handler that serves static files and accepts POST /api/feedback.

    Feedback is stored in a SQLite database (``feedback_db_path``) rather than
    a flat JSON file.  The path is injected via ``functools.partial``.
    """

    def __init__(self, *args, feedback_db_path: str = "", **kwargs):
        self.feedback_db_path = feedback_db_path
        super().__init__(*args, **kwargs)

    def do_POST(self):
        if self.path != "/api/feedback":
            self.send_error(404, "Not Found")
            return

        # Read and validate Content-Length
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error(400, "Empty body")
            return

        try:
            body = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "Invalid JSON")
            return

        # Validate required fields
        valid_types = {"bug", "friction", "feature_request", "praise"}
        page = body.get("page")
        feedback_type = body.get("feedback_type")
        message = body.get("message")

        if not page or not isinstance(page, str):
            self.send_error(400, "Missing or invalid 'page' field")
            return
        if feedback_type not in valid_types:
            self.send_error(400, f"'feedback_type' must be one of {sorted(valid_types)}")
            return
        if not message or not isinstance(message, str):
            self.send_error(400, "Missing or invalid 'message' field")
            return

        # Build entry
        feedback_id = uuid.uuid4().hex[:16]
        timestamp = datetime.datetime.utcnow().isoformat() + "Z"

        # Insert into SQLite (thread-safe via lock)
        with _feedback_db_lock:
            with sqlite3.connect(self.feedback_db_path) as conn:
                conn.execute(
                    "INSERT INTO feedback (id, timestamp, page, feedback_type, message) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (feedback_id, timestamp, page, feedback_type, message),
                )
                conn.commit()

        entry = {
            "feedback_id": feedback_id,
            "timestamp": timestamp,
            "page": page,
            "feedback_type": feedback_type,
            "message": message,
        }

        # Respond 201 Created
        response_body = json.dumps(entry).encode("utf-8")
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response_body)

    def do_OPTIONS(self):
        """Handle CORS preflight requests for the feedback endpoint."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


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

        feedback_db = str(self._workspace_root / "feedback.db")
        _init_feedback_db(feedback_db)
        handler = functools.partial(
            _FeedbackHandler,
            directory=str(self._workspace_root),
            feedback_db_path=feedback_db,
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


class FlaskAppServer:
    """Runs an agent-built Flask app from the workspace as a subprocess.

    The agents write ``app.py`` in the workspace directory.  This class
    launches it as a child process, waits for it to start serving, and
    exposes the same ``start() -> url`` / ``stop()`` interface as
    :class:`WorkspaceServer`.

    Usage:
        server = FlaskAppServer("workspace/")
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
        self._port = port or self._find_free_port()
        self._process: Optional[subprocess.Popen] = None

    @staticmethod
    def _find_free_port() -> int:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def port(self) -> Optional[int]:
        if not self.is_running:
            return None
        return self._port

    @property
    def base_url(self) -> Optional[str]:
        if not self.is_running:
            return None
        return f"http://{self._host}:{self._port}"

    def has_flask_app(self) -> bool:
        """Return True if workspace/app.py exists."""
        return (self._workspace_root / "app.py").is_file()

    def start(self, timeout: float = 30.0) -> str:
        """Start the Flask app subprocess. Returns the base URL.

        The app.py must honour ``FLASK_RUN_HOST`` / ``FLASK_RUN_PORT``
        environment variables (the placeholder does).
        """
        if self.is_running:
            return self.base_url

        app_py = self._workspace_root / "app.py"
        if not app_py.exists():
            raise FileNotFoundError(f"No app.py in {self._workspace_root}")

        env = os.environ.copy()
        env["FLASK_RUN_HOST"] = self._host
        env["FLASK_RUN_PORT"] = str(self._port)

        # Run with -c to inject debug=False override, preventing the
        # werkzeug reloader from spawning a child process (slow on Windows).
        bootstrap = (
            f"import runpy, flask; "
            f"flask.Flask.run = (lambda _orig: lambda self, *a, **kw: "
            f"_orig(self, *a, **{{**kw, 'debug': False}}))(flask.Flask.run); "
            f"runpy.run_path({str(app_py)!r}, run_name='__main__')"
        )

        self._process = subprocess.Popen(
            [sys.executable, "-c", bootstrap],
            cwd=str(self._workspace_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Poll until the server responds or the process dies
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                stderr = ""
                if self._process.stderr:
                    stderr = self._process.stderr.read().decode(errors="replace")[:500]
                raise RuntimeError(f"Flask app exited immediately: {stderr}")
            try:
                with urlopen(f"http://{self._host}:{self._port}/", timeout=1):
                    pass
                return self.base_url
            except (URLError, OSError):
                time.sleep(0.3)

        self.stop()
        raise TimeoutError(f"Flask app did not start within {timeout}s")

    def stop(self) -> None:
        """Terminate the Flask app subprocess."""
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
            self._process = None
