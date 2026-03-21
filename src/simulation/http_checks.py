"""HTTP validation checks against a served workspace."""
from __future__ import annotations

import re
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
    urlopen,
)

from src.utils.logging import get_logger

logger = get_logger(__name__)


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
    # Deduplicate while preserving order, skip parameterized routes
    seen: set[str] = set()
    unique: List[str] = []
    for r in routes:
        if r not in seen and "<" not in r:
            seen.add(r)
            unique.append(r)

    return unique or ["/"]


# ---------------------------------------------------------------------------
# Dynamic authentication helper
# ---------------------------------------------------------------------------

# Common field-name patterns mapped to sensible test values.
_FIELD_VALUE_MAP: Dict[str, str] = {
    "email": "testuser@example.com",
    "password": "TestPass123!",
    "confirm_password": "TestPass123!",
    "password_confirm": "TestPass123!",
    "password2": "TestPass123!",
    "confirm": "TestPass123!",
    "username": "testuser",
    "name": "Test User",
    "full_name": "Test User",
    "fullname": "Test User",
    "first_name": "Test",
    "last_name": "User",
    "firstname": "Test",
    "lastname": "User",
    "company": "TestCo Inc.",
    "company_name": "TestCo Inc.",
    "startup_name": "TestCo Inc.",
    "firm_name": "TestVC Capital",
    "organization": "TestOrg",
    "title": "CEO",
    "job_title": "CEO",
    "role": "founder",
    "user_type": "startup",
    "type": "startup",
    "phone": "+1-555-0100",
    "location": "San Francisco, CA",
    "city": "San Francisco",
    "country": "US",
    "website": "https://testco.example.com",
    "url": "https://testco.example.com",
    "bio": "A test user for automated QA.",
    "description": "An innovative startup disrupting the market.",
    "pitch": "We build next-gen solutions for enterprise.",
    "industry": "Technology",
    "industries": "Technology",
    "sector": "Technology",
    "stage": "Seed",
    "funding_stage": "Seed",
    "funding_amount": "500000",
    "investment_min": "100000",
    "investment_max": "1000000",
    "min_investment": "100000",
    "max_investment": "1000000",
    "founded": "2024",
    "founded_year": "2024",
    "team_size": "5",
    "employees": "5",
    "revenue": "100000",
}


def _guess_field_value(field_name: str) -> str:
    """Return a plausible test value for *field_name* by fuzzy-matching."""
    lower = field_name.lower().strip()
    # Direct match
    if lower in _FIELD_VALUE_MAP:
        return _FIELD_VALUE_MAP[lower]
    # Substring/partial match
    for key, val in _FIELD_VALUE_MAP.items():
        if key in lower or lower in key:
            return val
    # Fallback
    return "test"


def _extract_form_fields(html: str) -> List[Dict[str, str]]:
    """Extract ``<input>`` and ``<select>``/``<textarea>`` fields from HTML forms.

    Returns a list of dicts with ``name``, ``type``, and ``value`` keys.
    """
    fields: List[Dict[str, str]] = []
    seen_names: set[str] = set()

    # <input> tags
    for m in re.finditer(
        r"<input\b([^>]*)>", html, re.IGNORECASE | re.DOTALL
    ):
        attrs = m.group(1)
        name_m = re.search(r'name\s*=\s*["\']([^"\']+)', attrs, re.IGNORECASE)
        if not name_m:
            continue
        name = name_m.group(1)
        if name in seen_names:
            continue
        seen_names.add(name)

        type_m = re.search(r'type\s*=\s*["\']([^"\']+)', attrs, re.IGNORECASE)
        input_type = (type_m.group(1).lower() if type_m else "text")

        # Skip submit/hidden/button/file inputs
        if input_type in ("submit", "button", "image", "file", "reset"):
            continue

        value_m = re.search(r'value\s*=\s*["\']([^"\']*)', attrs, re.IGNORECASE)
        value = value_m.group(1) if value_m else ""

        fields.append({"name": name, "type": input_type, "value": value})

    # <select> tags
    for m in re.finditer(
        r"<select\b([^>]*)>(.*?)</select>", html, re.IGNORECASE | re.DOTALL
    ):
        attrs = m.group(1)
        inner = m.group(2)
        name_m = re.search(r'name\s*=\s*["\']([^"\']+)', attrs, re.IGNORECASE)
        if not name_m:
            continue
        name = name_m.group(1)
        if name in seen_names:
            continue
        seen_names.add(name)
        # Pick the first non-empty <option> value
        options = re.findall(
            r'<option\b[^>]*value\s*=\s*["\']([^"\']+)', inner, re.IGNORECASE
        )
        value = options[0] if options else _guess_field_value(name)
        fields.append({"name": name, "type": "select", "value": value})

    # <textarea> tags
    for m in re.finditer(
        r"<textarea\b([^>]*)>(.*?)</textarea>", html, re.IGNORECASE | re.DOTALL
    ):
        attrs = m.group(1)
        name_m = re.search(r'name\s*=\s*["\']([^"\']+)', attrs, re.IGNORECASE)
        if not name_m:
            continue
        name = name_m.group(1)
        if name in seen_names:
            continue
        seen_names.add(name)
        fields.append({"name": name, "type": "textarea", "value": ""})

    return fields


def _discover_auth_routes(source: str) -> Dict[str, List[str]]:
    """Analyse Flask app source for authentication-related routes.

    Returns dict with keys ``login``, ``register``, ``logout`` each mapping
    to a list of route paths that look auth-related.
    """
    auth_routes: Dict[str, List[str]] = {"login": [], "register": [], "logout": []}

    # Find all @app.route blocks with the function name that follows
    for m in re.finditer(
        r"""@app\.route\(\s*['"]([^'"]+)['"]""", source
    ):
        route = m.group(1)
        # Look at surrounding context (route path + next ~200 chars for function name)
        start = m.start()
        context = source[max(0, start - 20): start + 300].lower()

        if any(kw in route.lower() or kw in context for kw in ("login", "signin", "sign_in", "sign-in")):
            if "logout" not in route.lower() and "signout" not in route.lower():
                auth_routes["login"].append(route)
        if any(kw in route.lower() or kw in context for kw in ("register", "signup", "sign_up", "sign-up")):
            auth_routes["register"].append(route)
        if any(kw in route.lower() or kw in context for kw in ("logout", "signout", "sign_out", "sign-out")):
            auth_routes["logout"].append(route)

    return auth_routes


def _has_auth_protection(source: str) -> bool:
    """Check whether the Flask app uses any form of route protection."""
    indicators = [
        "login_required",
        "@login_required",
        "session[",
        "session.get(",
        "current_user",
        "flask_login",
        "flask_security",
        "is_authenticated",
        "redirect(url_for",
    ]
    lower = source.lower()
    return any(ind.lower() in lower for ind in indicators)


def create_authenticated_opener(
    base_url: str,
    workspace_root: str,
    timeout: int = 10,
) -> Any:
    """Create a urllib opener with an authenticated session if possible.

    Dynamically inspects ``app.py`` to discover registration and login
    routes, parses form fields, registers a test user, and logs in.

    Returns a tuple ``(opener, auth_succeeded)`` where *opener* is a
    ``urllib.request.OpenerDirector`` with cookie support and
    *auth_succeeded* indicates whether login was established.
    """
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    base = base_url.rstrip("/")

    ws = Path(workspace_root)
    app_py = ws / "app.py"
    if not app_py.is_file():
        return opener, False

    try:
        source = app_py.read_text(encoding="utf-8")
    except Exception:
        return opener, False

    if not _has_auth_protection(source):
        logger.info("Auth session: no auth protection detected, skipping login")
        return opener, False

    auth_routes = _discover_auth_routes(source)
    register_routes = auth_routes["register"]
    login_routes = auth_routes["login"]

    if not login_routes:
        logger.info("Auth session: no login routes found, skipping")
        return opener, False

    # --- Step 1: Try to register a test user ---
    registered = False
    for reg_route in register_routes:
        try:
            url = f"{base}/{reg_route.lstrip('/')}"
            # Fetch the registration page to discover form fields
            resp = opener.open(url, timeout=timeout)
            html = resp.read().decode("utf-8", errors="replace")
            fields = _extract_form_fields(html)

            if not fields:
                logger.debug("Auth session: no form fields at %s", reg_route)
                continue

            # Build POST data from discovered fields
            post_data: Dict[str, str] = {}
            for field in fields:
                name = field["name"]
                if field["type"] == "hidden" and field["value"]:
                    # Preserve hidden fields (CSRF tokens, etc.)
                    post_data[name] = field["value"]
                elif field["value"] and field["type"] == "select":
                    post_data[name] = field["value"]
                else:
                    post_data[name] = _guess_field_value(name)

            encoded = urlencode(post_data).encode("utf-8")
            req = Request(url, data=encoded, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            resp = opener.open(req, timeout=timeout)
            resp.read()  # consume body
            registered = True
            logger.info("Auth session: registered test user via %s (fields: %s)",
                        reg_route, list(post_data.keys()))
            break
        except Exception as exc:
            logger.debug("Auth session: registration via %s failed: %s", reg_route, exc)
            continue

    if not registered:
        logger.info("Auth session: no registration routes available, trying login directly")

    # --- Step 2: Log in ---
    for login_route in login_routes:
        try:
            url = f"{base}/{login_route.lstrip('/')}"
            # Fetch login page to discover form fields
            resp = opener.open(url, timeout=timeout)
            html = resp.read().decode("utf-8", errors="replace")
            fields = _extract_form_fields(html)

            if not fields:
                logger.debug("Auth session: no form fields at %s", login_route)
                continue

            post_data = {}
            for field in fields:
                name = field["name"]
                if field["type"] == "hidden" and field["value"]:
                    post_data[name] = field["value"]
                else:
                    post_data[name] = _guess_field_value(name)

            encoded = urlencode(post_data).encode("utf-8")
            req = Request(url, data=encoded, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            resp = opener.open(req, timeout=timeout)
            resp.read()

            # Verify login succeeded by checking cookies or fetching a protected page
            has_session = any("session" in c.name.lower() for c in jar)
            if has_session or len(jar) > 0:
                logger.info("Auth session: logged in via %s (cookies: %d)",
                            login_route, len(jar))
                return opener, True

            logger.debug("Auth session: login via %s produced no cookies", login_route)
        except Exception as exc:
            logger.debug("Auth session: login via %s failed: %s", login_route, exc)
            continue

    logger.info("Auth session: could not establish authenticated session")
    return opener, False


class WorkspaceHTTPChecker:
    """Validates workspace pages via HTTP requests."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 10,
        opener: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._opener = opener

    def _fetch(self, path: str) -> Optional[str]:
        """Fetch a page and return body text, or None on error."""
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            if self._opener is not None:
                resp = self._opener.open(url, timeout=self._timeout)
                return resp.read().decode("utf-8", errors="replace")
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
