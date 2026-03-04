"""HTTP validation checks against a served workspace."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


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

    def run_all_checks(self) -> Dict[str, Any]:
        """Run all checks and return consolidated results with derived scores."""
        landing = self.check_page_loads("/index.html")
        navigation = self.check_navigation_links("/index.html")

        http_landing_score = 1.0 if landing.get("loaded") else 0.0

        total_links = navigation.get("links_found", 0)
        ok_links = navigation.get("links_ok", 0)
        http_navigation_score = (ok_links / total_links) if total_links > 0 else 0.0

        return {
            "landing": landing,
            "navigation": navigation,
            "http_landing_score": http_landing_score,
            "http_navigation_score": http_navigation_score,
        }
