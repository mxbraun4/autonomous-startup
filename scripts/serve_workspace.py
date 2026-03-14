"""Standalone workspace preview server with live-reload.

Serves the agent-built website from ``workspace/`` on a fixed port,
injecting a small script that auto-refreshes the browser whenever the
underlying files change.

Usage:
    python scripts/serve_workspace.py                     # default port 8080
    python scripts/serve_workspace.py --port 3000         # custom port
    python scripts/serve_workspace.py --open-browser      # open in browser
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

if __package__:
    from ._bootstrap import add_repo_root_to_path
else:
    from _bootstrap import add_repo_root_to_path

REPO_ROOT = add_repo_root_to_path(__file__)

DEFAULT_WORKSPACE = REPO_ROOT / "workspace"
DEFAULT_PORT = 8080
REFRESH_INTERVAL_MS = 1500

# Injected into every HTML response so the browser polls for changes.
LIVE_RELOAD_SNIPPET = f"""
<script data-live-reload>
(function() {{
  let _hash = "";
  async function poll() {{
    try {{
      const r = await fetch("/__reload_hash", {{cache: "no-store"}});
      const h = await r.text();
      if (_hash && h !== _hash) location.reload();
      _hash = h;
    }} catch(_) {{}}
  }}
  setInterval(poll, {REFRESH_INTERVAL_MS});
  poll();
}})();
</script>
"""


def _workspace_hash(workspace: Path) -> str:
    """Fast content-hash of all workspace files (mtime + size)."""
    parts: list[str] = []
    for p in sorted(workspace.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            try:
                stat = p.stat()
                parts.append(f"{p.relative_to(workspace)}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                continue
    return hashlib.md5("|".join(parts).encode()).hexdigest()


class PreviewServer(ThreadingHTTPServer):
    """HTTP server that serves workspace files with live-reload."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        workspace: Path,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.workspace = workspace


class PreviewHandler(BaseHTTPRequestHandler):
    """Serve workspace files, inject live-reload, expose reload hash."""

    server: PreviewServer

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].split("#")[0]

        if path == "/__reload_hash":
            self._send_text(_workspace_hash(self.server.workspace))
            return
        if path == "/healthz":
            self._send_json({"status": "ok"})
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        # Resolve file path
        rel = path.lstrip("/") or "index.html"
        file_path = (self.server.workspace / rel).resolve()

        # Safety: prevent path traversal
        try:
            file_path.relative_to(self.server.workspace)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN, "forbidden")
            return

        # Directory -> index.html
        if file_path.is_dir():
            file_path = file_path / "index.html"

        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return

        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        # Inject live-reload into HTML responses
        if content_type.startswith("text/html"):
            text = content.decode("utf-8", errors="replace")
            if "</body>" in text:
                text = text.replace("</body>", LIVE_RELOAD_SNIPPET + "</body>")
            elif "</html>" in text:
                text = text.replace("</html>", LIVE_RELOAD_SNIPPET + "</html>")
            else:
                text += LIVE_RELOAD_SNIPPET
            content = text.encode("utf-8")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, fmt: str, *args: Any) -> None:
        del fmt, args  # suppress default logging

    def _send_text(self, text: str) -> None:
        raw = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_json(self, data: Dict[str, Any]) -> None:
        raw = json.dumps(data).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve workspace with live-reload preview.")
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE), help="Workspace directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open-browser", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    workspace = Path(args.workspace).resolve()

    if not workspace.is_dir():
        print(f"ERROR: workspace directory not found: {workspace}")
        raise SystemExit(1)

    # If workspace has a Flask app.py, run it directly instead of static serving
    if (workspace / "app.py").is_file():
        from src.workspace_tools.server import FlaskAppServer

        flask_server = FlaskAppServer(workspace, host=args.host, port=args.port)
        try:
            url = flask_server.start()
        except Exception as exc:
            print(f"ERROR: Failed to start Flask app: {exc}")
            raise SystemExit(1)

        print("=" * 64)
        print("FLASK APP PREVIEW")
        print("=" * 64)
        print(f"URL:       {url}")
        print(f"Workspace: {workspace}")
        print("Press Ctrl+C to stop.")
        print("=" * 64)

        if args.open_browser:
            try:
                webbrowser.open(url, new=2)
            except Exception:
                pass

        try:
            import time
            while flask_server.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping Flask app...")
        finally:
            flask_server.stop()
        return

    # Static file preview (fallback when no app.py exists)
    server = PreviewServer(
        (args.host, args.port),
        PreviewHandler,
        workspace=workspace,
    )
    url = f"http://{args.host}:{args.port}"
    print("=" * 64)
    print("WORKSPACE LIVE PREVIEW")
    print("=" * 64)
    print(f"URL:       {url}")
    print(f"Workspace: {workspace}")
    print(f"Reload:    every {REFRESH_INTERVAL_MS}ms")
    print("Press Ctrl+C to stop.")
    print("=" * 64)

    if args.open_browser:
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping preview server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
