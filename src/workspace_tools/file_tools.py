"""Sandboxed file tools for workspace-scoped reads, writes, and listings."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from crewai.tools import tool

# ---------------------------------------------------------------------------
# Module-level workspace root
# ---------------------------------------------------------------------------

_workspace_root: Optional[Path] = None

# ---------------------------------------------------------------------------
# Per-cycle read cache — avoids redundant file reads by agents within a
# single cycle.  The cache is keyed by relative file path and invalidated
# per-file on writes.  Call ``reset_read_cache()`` at the start of each
# cycle to ensure fresh data.
# ---------------------------------------------------------------------------
_read_cache: dict[str, dict] = {}
_read_cache_enabled: bool = True
_read_cache_hits: int = 0


def reset_read_cache() -> None:
    """Clear the read cache.  Call at the start of each cycle."""
    global _read_cache, _read_cache_hits
    _read_cache = {}
    _read_cache_hits = 0


def _invalidate_cache_entry(file_path: str) -> None:
    """Remove a single file from the read cache (called after writes)."""
    _read_cache.pop(file_path, None)


def configure_workspace_root(path: Union[str, Path]) -> None:
    """Set the module-level workspace root directory."""
    global _workspace_root
    _workspace_root = Path(path).resolve()
    reset_read_cache()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_safe_path(relative_path: str) -> Path:
    """Resolve *relative_path* inside the workspace root and validate it.

    Raises
    ------
    RuntimeError
        If the workspace root has not been configured yet.
    ValueError
        If the resolved path escapes the workspace root.
    """
    if _workspace_root is None:
        raise RuntimeError("Workspace root is not configured. Call configure_workspace_root first.")

    candidate = (_workspace_root / relative_path).resolve()
    # .relative_to raises ValueError when candidate is not under root
    candidate.relative_to(_workspace_root)
    return candidate


# ---------------------------------------------------------------------------
# Implementation functions (plain helpers — easy to test directly)
# ---------------------------------------------------------------------------


def _read_impl(file_path: str) -> dict:
    """Return a dict with the result of reading *file_path*."""
    try:
        resolved = _resolve_safe_path(file_path)
    except ValueError:
        return {"status": "denied", "reason": "Path escapes workspace. Use relative paths like 'index.html' or 'backend/main.py', not absolute or '../' paths."}
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}

    try:
        content = resolved.read_text(encoding="utf-8")
        return {"status": "ok", "path": str(resolved), "content": content}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _write_impl(file_path: str, content: str) -> dict:
    """Return a dict with the result of writing *content* to *file_path*."""
    try:
        resolved = _resolve_safe_path(file_path)
    except ValueError:
        return {"status": "denied", "reason": "Path escapes workspace. Use relative paths like 'index.html' or 'backend/main.py', not absolute or '../' paths."}
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return {"status": "ok", "path": str(resolved), "bytes_written": len(content.encode("utf-8"))}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _list_impl(subdirectory: str = "") -> dict:
    """Return a dict with a recursive listing of workspace files."""
    try:
        resolved = _resolve_safe_path(subdirectory) if subdirectory else _resolve_safe_path(".")
    except ValueError:
        return {"status": "denied", "reason": "Path escapes workspace. Use relative paths like 'index.html' or 'backend/main.py', not absolute or '../' paths."}
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}

    try:
        files: list[str] = []
        for entry in resolved.rglob("*"):
            if entry.is_file():
                rel = entry.relative_to(_workspace_root)
                # Exclude anything under a .versions directory and feedback.json
                if ".versions" in rel.parts:
                    continue
                if rel.name == "feedback.db":
                    continue
                files.append(str(rel))
        return {"status": "ok", "files": sorted(files)}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# SQL safety regexes
# ---------------------------------------------------------------------------

# Block ATTACH/DETACH/LOAD_EXTENSION — these can escape the sandbox.
_BLOCKED_SQL_RE = re.compile(
    r"\b(ATTACH|DETACH|LOAD_EXTENSION)\b",
    re.IGNORECASE,
)

# Block dangerous PRAGMAs that could leak keys or attach databases.
_BLOCKED_PRAGMA_RE = re.compile(
    r"\bPRAGMA\s+(key|rekey|cipher|kdf_iter|cipher_page_size|"
    r"cipher_use_hmac|cipher_hmac_algorithm|attach_key)\b",
    re.IGNORECASE,
)

_MAX_SELECT_ROWS = 200


def _run_sql_impl(db_name: str, query: str, params: str = "[]") -> dict:
    """Execute a SQL query against a workspace SQLite database.

    Parameters
    ----------
    db_name:
        Relative path to the ``.db`` file inside the workspace (e.g.
        ``feedback.db`` or ``sub/nested.db``).
    query:
        SQL statement to execute.
    params:
        JSON-encoded list of bind parameters (default ``"[]"``).

    Returns
    -------
    dict
        ``{"status": "ok", "rows": [...]}`` for SELECT, or
        ``{"status": "ok", "rowcount": N}`` for DML/DDL.
    """
    # Validate .db extension
    if not db_name.endswith(".db"):
        return {"status": "error", "reason": "db_name must end with .db"}

    # Resolve and sandbox-check the path
    try:
        resolved = _resolve_safe_path(db_name)
    except ValueError:
        return {"status": "denied", "reason": "Path escapes workspace. Use relative paths like 'index.html' or 'backend/main.py', not absolute or '../' paths."}
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}

    # Block dangerous SQL
    if _BLOCKED_SQL_RE.search(query):
        return {"status": "denied", "reason": "blocked_sql: ATTACH/DETACH/LOAD_EXTENSION not allowed"}
    if _BLOCKED_PRAGMA_RE.search(query):
        return {"status": "denied", "reason": "blocked_sql: dangerous PRAGMA not allowed"}

    # Parse params
    try:
        param_list = json.loads(params)
        if not isinstance(param_list, list):
            return {"status": "error", "reason": "params must be a JSON list"}
    except (json.JSONDecodeError, TypeError) as exc:
        return {"status": "error", "reason": f"invalid params JSON: {exc}"}

    # Ensure parent directory exists
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}

    # Execute
    try:
        conn = sqlite3.connect(str(resolved))
        try:
            cursor = conn.execute(query, param_list)
            # Determine if this is a SELECT-like query
            if cursor.description is not None:
                rows = cursor.fetchmany(_MAX_SELECT_ROWS)
                col_names = [desc[0] for desc in cursor.description]
                result_rows = [dict(zip(col_names, row)) for row in rows]
                conn.commit()
                return {"status": "ok", "rows": result_rows}
            else:
                conn.commit()
                return {"status": "ok", "rowcount": cursor.rowcount}
        finally:
            conn.close()
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# HTTP check helpers
# ---------------------------------------------------------------------------


def _check_http_impl(pages: str = "") -> dict:
    """Start a temporary server, run HTTP checks, and return results.

    If the workspace contains ``app.py`` (Flask app), launches it as a
    subprocess via :class:`FlaskAppServer`.  Otherwise falls back to the
    static-file :class:`WorkspaceServer`.

    Parameters
    ----------
    pages:
        Comma-separated list of routes/pages to check (e.g.
        ``"/,/startups,/investors"`` for Flask or ``"index.html"`` for static).
        If empty, runs the full standard check suite.
    """
    if _workspace_root is None:
        return {"status": "error", "reason": "Workspace root is not configured. Call configure_workspace_root first."}

    # Lazy imports to avoid circular dependencies
    from src.workspace_tools.server import FlaskAppServer, WorkspaceServer
    from src.simulation.http_checks import WorkspaceHTTPChecker

    # Prefer Flask app if workspace/app.py exists
    flask_server = FlaskAppServer(str(_workspace_root), port=0)
    use_flask = flask_server.has_flask_app()

    server = flask_server if use_flask else WorkspaceServer(str(_workspace_root), port=0)
    try:
        base_url = server.start()
        checker = WorkspaceHTTPChecker(base_url)

        if pages.strip():
            # Check specific pages/routes
            results: dict = {}
            for page in [p.strip() for p in pages.split(",") if p.strip()]:
                results[page] = checker.check_page_loads(page)
            return {"status": "ok", "pages": results}
        else:
            # Full standard suite
            all_checks = checker.run_all_checks(workspace_root=str(_workspace_root))
            return {"status": "ok", **all_checks}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Test feedback helper
# ---------------------------------------------------------------------------

_VALID_FEEDBACK_TYPES = {"bug", "friction", "feature_request", "praise"}


def _ensure_feedback_schema() -> dict:
    """Ensure the feedback table exists with the latest schema (including cycle_id, status).

    Handles migration from the old schema (no cycle_id/status columns) by
    adding missing columns via ALTER TABLE.
    """
    create_result = _run_sql_impl(
        "feedback.db",
        "CREATE TABLE IF NOT EXISTS feedback ("
        "  id TEXT PRIMARY KEY,"
        "  timestamp TEXT NOT NULL,"
        "  page TEXT NOT NULL,"
        "  feedback_type TEXT NOT NULL,"
        "  message TEXT NOT NULL,"
        "  cycle_id INTEGER DEFAULT 0,"
        "  status TEXT DEFAULT 'open'"
        ")",
    )
    if create_result.get("status") != "ok":
        return create_result

    # Migrate old tables missing the new columns
    for col, col_def in [("cycle_id", "INTEGER DEFAULT 0"), ("status", "TEXT DEFAULT 'open'")]:
        _run_sql_impl(
            "feedback.db",
            f"ALTER TABLE feedback ADD COLUMN {col} {col_def}",
        )
        # ALTER TABLE will fail silently if column already exists — that's fine

    return {"status": "ok"}


def _submit_feedback_impl(
    page: str,
    feedback_type: str,
    message: str,
    cycle_id: int = 0,
) -> dict:
    """Insert a feedback entry into workspace/feedback.db.

    Creates the feedback table if it does not exist.  Each entry is tagged
    with ``cycle_id`` so feedback persists across cycles and can be queried
    by iteration.
    """
    if feedback_type not in _VALID_FEEDBACK_TYPES:
        return {
            "status": "error",
            "reason": f"feedback_type must be one of {sorted(_VALID_FEEDBACK_TYPES)}",
        }
    if not page or not message:
        return {"status": "error", "reason": "page and message are required"}

    schema_result = _ensure_feedback_schema()
    if schema_result.get("status") != "ok":
        return schema_result

    feedback_id = uuid.uuid4().hex[:16]
    timestamp = datetime.now(timezone.utc).isoformat()

    insert_result = _run_sql_impl(
        "feedback.db",
        "INSERT INTO feedback (id, timestamp, page, feedback_type, message, cycle_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        json.dumps([feedback_id, timestamp, page, feedback_type, message, cycle_id, "open"]),
    )
    if insert_result.get("status") != "ok":
        return insert_result

    return {
        "status": "ok",
        "feedback_id": feedback_id,
        "timestamp": timestamp,
        "cycle_id": cycle_id,
    }


def _get_open_feedback(exclude_cycle: int = 0) -> list:
    """Return all feedback entries with status='open' from prior cycles.

    Args:
        exclude_cycle: Cycle to exclude (typically the current one, whose
            feedback hasn't been generated yet).

    Returns:
        List of feedback dicts with id, cycle_id, page, feedback_type, message.
    """
    import sqlite3 as _sqlite3

    if _workspace_root is None:
        return []

    db_path = _workspace_root / "feedback.db"
    if not db_path.exists():
        return []

    try:
        with _sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                "SELECT id, cycle_id, page, feedback_type, message "
                "FROM feedback WHERE status = 'open' AND cycle_id != ? "
                "ORDER BY cycle_id, feedback_type",
                (exclude_cycle,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _mark_feedback_addressed(feedback_ids: list, addressed_in_cycle: int) -> int:
    """Mark specific feedback entries as addressed.

    Args:
        feedback_ids: List of feedback id strings to mark.
        addressed_in_cycle: The cycle that addressed these items.

    Returns:
        Number of rows updated.
    """
    import sqlite3 as _sqlite3

    if not feedback_ids or _workspace_root is None:
        return 0

    db_path = _workspace_root / "feedback.db"
    if not db_path.exists():
        return 0

    try:
        placeholders = ",".join("?" for _ in feedback_ids)
        with _sqlite3.connect(str(db_path)) as conn:
            cur = conn.execute(
                f"UPDATE feedback SET status = 'addressed' "
                f"WHERE id IN ({placeholders})",
                feedback_ids,
            )
            return cur.rowcount
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# CrewAI @tool decorated functions
# ---------------------------------------------------------------------------

@tool
def read_workspace_file(file_path: str) -> str:
    """Read a file from the workspace directory.

    Args:
        file_path: Relative path to the file, e.g. "index.html" or "css/styles.css"

    Returns:
        JSON with the file content
    """
    global _read_cache_hits
    # Per-cycle cache: return cached result if this file was already read
    # and not written to since.
    if _read_cache_enabled and file_path in _read_cache:
        _read_cache_hits += 1
        return json.dumps(_read_cache[file_path])

    result = _read_impl(file_path)

    # Cache successful reads
    if _read_cache_enabled and result.get("status") == "ok":
        _read_cache[file_path] = result

    return json.dumps(result)


@tool
def write_workspace_file(file_path: str, content: str) -> str:
    """Write or overwrite a file inside the workspace directory.

    Args:
        file_path: Relative path to write, e.g. "index.html" or "styles.css"
        content: The full file content to write

    Returns:
        JSON confirmation with the written path
    """
    result = _write_impl(file_path, content)
    # Invalidate the read cache for this file so subsequent reads see
    # the new content instead of stale cached data.
    _invalidate_cache_entry(file_path)
    return json.dumps(result)


@tool
def list_workspace_files(subdirectory: str = "") -> str:
    """Recursively list all files in the workspace (excluding .versions/).

    Args:
        subdirectory: Optional subdirectory to list, e.g. "css". Empty string lists all files.

    Returns:
        JSON with a list of file paths
    """
    return json.dumps(_list_impl(subdirectory))


@tool
def review_workspace_files() -> str:
    """List all workspace files and read every source file (.py, .html, .css, .js) in one call.

    Returns a JSON object with ``files`` (full listing) and ``source_contents``
    (a dict mapping each source filename to its content).  Use this for QA
    review so you can inspect everything in a single tool call.
    """
    listing = _list_impl("")
    if listing.get("status") != "ok":
        return json.dumps(listing)
    _SOURCE_EXTS = {".py", ".html", ".css", ".js", ".json"}
    source_contents: dict[str, str] = {}
    for fname in listing.get("files", []):
        if any(fname.endswith(ext) for ext in _SOURCE_EXTS):
            result = _read_impl(fname)
            if result.get("status") == "ok":
                source_contents[fname] = result["content"]
    return json.dumps({
        "status": "ok",
        "files": listing["files"],
        "source_contents": source_contents,
    })


# Disable CrewAI's per-tool result cache for workspace tools.  The default
# cache_function returns True (= always cache), which causes reads after
# writes to return stale content for the same file_path argument.
_NO_CACHE = lambda _args=None, _result=None: False  # noqa: E731
@tool("Run Workspace SQL")
def run_workspace_sql(db_name: str, query: str, params: str = "[]") -> str:
    """Execute a SQL query against a SQLite database in the workspace directory.

    Use this to CREATE TABLE, INSERT, SELECT, UPDATE, DELETE on any .db file
    in the workspace.  The database file is created automatically if it does
    not exist.  Pass bind parameters as a JSON list in *params*.

    Examples:
        run_workspace_sql("feedback.db",
                          "CREATE TABLE IF NOT EXISTS feedback (id TEXT, msg TEXT)")
        run_workspace_sql("feedback.db",
                          "INSERT INTO feedback VALUES (?, ?)",
                          '["1", "Great site!"]')
        run_workspace_sql("feedback.db", "SELECT * FROM feedback")
    """
    return json.dumps(_run_sql_impl(db_name, query, params))


@tool("Check Workspace HTTP")
def check_workspace_http(pages: str = "") -> str:
    """Start the Flask app (or static server) and run HTTP validation checks.

    With no arguments, runs the full check suite: landing page load
    and navigation link verification against discovered Flask routes.
    Pass a comma-separated list of routes (e.g. ``"/,/startups,/investors"``)
    to check only those specific routes.

    Returns JSON with scores: ``http_landing_score``,
    ``http_navigation_score`` (each 0.0–1.0).
    """
    return json.dumps(_check_http_impl(pages))


@tool("Submit Test Feedback")
def submit_test_feedback(page: str, feedback_type: str, message: str) -> str:
    """Submit a test feedback entry to workspace/feedback.db.

    Use this to validate that the feedback pipeline works end-to-end.
    Valid ``feedback_type`` values: bug, friction, feature_request, praise.
    """
    return json.dumps(_submit_feedback_impl(page, feedback_type, message))


read_workspace_file.cache_function = _NO_CACHE
write_workspace_file.cache_function = _NO_CACHE
list_workspace_files.cache_function = _NO_CACHE
review_workspace_files.cache_function = _NO_CACHE
run_workspace_sql.cache_function = _NO_CACHE
check_workspace_http.cache_function = _NO_CACHE
submit_test_feedback.cache_function = _NO_CACHE
