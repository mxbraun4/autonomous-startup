"""HTTP validation checks against a served workspace."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def _discover_flask_routes(workspace_root: str) -> List[str]:
    """Parse ``app.py`` for ``@app.route(...)`` decorators and return paths.

    Falls back to ``["/"]`` if no routes can be extracted.
    """
    ws = Path(workspace_root)
    app_py = ws / "app.py"
    if not app_py.is_file():
        return []

    try:
        source = app_py.read_text(encoding="utf-8")
    except Exception:
        return ["/"]

    routes = re.findall(r"""@app\.route\(\s*['"]([^'"]+)['"]""", source)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: List[str] = []
    for r in routes:
        if r not in seen:
            seen.add(r)
            unique.append(r)

    return unique or ["/"]


class WorkspaceHTTPChecker:
    """Validates workspace pages via HTTP requests."""

    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def _fetch(self, path: str) -> Optional[str]:
        """Fetch a page and return body text, or None on error."""
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            with urlopen(url, timeout=self._timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, OSError):
            return None

    def check_page_loads(self, path: str) -> Dict[str, Any]:
        """GET a path and verify it returns 200."""
        body = self._fetch(path)
        if body is not None:
            return {"path": path, "status": "ok", "loaded": True}
        return {"path": path, "status": "error", "loaded": False}

    def check_navigation_links(self, path: str = "/") -> Dict[str, Any]:
        """Extract href links from a page and verify each resolves."""
        body = self._fetch(path)
        if body is None:
            return {
                "path": path,
                "status": "error",
                "links_found": 0,
                "links_ok": 0,
                "links_broken": 0,
                "broken_links": [],
            }

        # Extract href values from anchor tags
        hrefs = re.findall(r'<a[^>]+href\s*=\s*["\']([^"\'#][^"\']*)', body, re.IGNORECASE)
        # Filter to relative links only (internal navigation)
        internal_links = [h for h in hrefs if not h.startswith(("http://", "https://", "mailto:", "javascript:"))]
        # Deduplicate
        internal_links = list(dict.fromkeys(internal_links))

        links_ok = 0
        broken_links: List[str] = []
        for link in internal_links:
            check = self._fetch(link)
            if check is not None:
                links_ok += 1
            else:
                broken_links.append(link)

        return {
            "path": path,
            "status": "ok",
            "links_found": len(internal_links),
            "links_ok": links_ok,
            "links_broken": len(broken_links),
            "broken_links": broken_links,
        }

    def run_all_checks(self, workspace_root: str = "") -> Dict[str, Any]:
        """Run all checks and return consolidated results with derived scores.

        If the workspace contains ``app.py``, discovers Flask routes and checks
        each one.  Otherwise falls back to scanning ``.html`` files.
        """
        # Discover pages/routes to check
        pages_to_check: List[str] = []

        if workspace_root:
            ws = Path(workspace_root)
            # Prefer Flask route discovery
            if (ws / "app.py").is_file():
                pages_to_check = _discover_flask_routes(workspace_root)
            else:
                # Fallback: scan for .html files
                if ws.is_dir():
                    pages_to_check = sorted(
                        "/" + str(f.relative_to(ws)).replace("\\", "/")
                        for f in ws.rglob("*.html")
                    )

        if not pages_to_check:
            pages_to_check = ["/"]

        # Check that every page/route loads
        page_results: Dict[str, Any] = {}
        pages_loaded = 0
        for page in pages_to_check:
            result = self.check_page_loads(page)
            page_results[page] = result
            if result.get("loaded"):
                pages_loaded += 1

        http_landing_score = pages_loaded / len(pages_to_check) if pages_to_check else 0.0

        # Check navigation links on all loaded pages
        total_links = 0
        ok_links = 0
        all_broken: List[str] = []
        for page in pages_to_check:
            if page_results.get(page, {}).get("loaded"):
                nav = self.check_navigation_links(page)
                total_links += nav.get("links_found", 0)
                ok_links += nav.get("links_ok", 0)
                all_broken.extend(nav.get("broken_links", []))

        # Deduplicate broken links
        all_broken = list(dict.fromkeys(all_broken))
        http_navigation_score = (ok_links / total_links) if total_links > 0 else 0.0

        return {
            "pages_checked": pages_to_check,
            "pages_loaded": pages_loaded,
            "page_results": page_results,
            "broken_links": all_broken,
            "http_landing_score": http_landing_score,
            "http_navigation_score": http_navigation_score,
        }
