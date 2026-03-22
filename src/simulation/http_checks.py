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

# Fixed test credentials used across registration and login.
_TEST_EMAIL = "qatest@example.com"
_TEST_PASSWORD = "TestPass123!"
_TEST_USERNAME = "qatest"


def _llm_fill_form(
    fields: List[Dict[str, str]],
    form_purpose: str,
    page_html: str = "",
) -> Dict[str, str]:
    """Use an LLM to generate plausible form field values.

    The LLM sees the field names, types, any select options, and the
    surrounding page HTML so it understands the context regardless of
    app structure.  It always uses fixed email/password for consistency.
    """
    import json as _json

    # Build a compact description of each field
    field_descriptions = []
    for f in fields:
        desc = f"- name={f['name']}, type={f['type']}"
        if f.get("value"):
            desc += f", default={f['value']}"
        if f.get("options"):
            desc += f", options={f['options']}"
        field_descriptions.append(desc)

    fields_text = "\n".join(field_descriptions)

    # Truncate page HTML to give the LLM context about what the form is for
    context_html = page_html[:3000] if page_html else "(no page context)"

    prompt = f"""You are filling out a web form for automated testing of a startup-VC matching platform.

FORM PURPOSE: {form_purpose}
FIXED CREDENTIALS (you MUST use these exact values):
- For any username field: {_TEST_USERNAME}
- For any email field: {_TEST_EMAIL}
- For any password field: {_TEST_PASSWORD}

FORM FIELDS:
{fields_text}

PAGE CONTEXT (truncated):
{context_html}

Return a JSON object mapping each field name to a plausible value.
Rules:
- Use the EXACT email and password shown above
- For select/dropdown fields, pick one of the available options
- For numeric fields (funding, revenue, etc.), use realistic numbers as strings
- For text fields, use short realistic values appropriate to a startup-VC platform
- For hidden fields, keep their default value
- Every field must have a value — do not skip any

Return ONLY the JSON object, no markdown, no explanation."""

    try:
        import litellm
        from src.simulation.customer_testing import _build_litellm_kwargs, _resolve_customer_model

        model = _resolve_customer_model()
        extra_kwargs = _build_litellm_kwargs(model)

        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
            **extra_kwargs,
        )
        raw = response.choices[0].message.content or ""

        # Parse JSON — try direct, then strip fences
        result = None
        try:
            result = _json.loads(raw.strip())
        except _json.JSONDecodeError:
            # Strip markdown code fences
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned, flags=re.MULTILINE)
            try:
                result = _json.loads(cleaned.strip())
            except _json.JSONDecodeError:
                # Try to extract {...} block
                m = re.search(r"\{.*\}", cleaned, re.DOTALL)
                if m:
                    try:
                        result = _json.loads(m.group(0))
                    except _json.JSONDecodeError:
                        pass

        if isinstance(result, dict):
            # Ensure credentials are always our fixed values so
            # registration and login use the same username/email/password.
            for f in fields:
                name = f["name"]
                ftype = f["type"]
                lower = name.lower()
                if ftype == "email" or "email" in lower:
                    result[name] = _TEST_EMAIL
                if ftype == "password" or "password" in lower or "passwd" in lower:
                    result[name] = _TEST_PASSWORD
                if lower == "username" or (lower == "name" and ftype == "text"):
                    result[name] = _TEST_USERNAME
                # Preserve hidden field defaults
                if ftype == "hidden" and f.get("value") and name not in result:
                    result[name] = f["value"]

            logger.info("LLM form fill (%s): %s", form_purpose, list(result.keys()))
            return result

    except Exception as exc:
        logger.warning("LLM form fill failed: %s", exc)

    # Fallback: basic type-driven fill
    return _basic_fill_form(fields)


def _basic_fill_form(fields: List[Dict[str, str]]) -> Dict[str, str]:
    """Minimal type-driven form fill as fallback when LLM is unavailable."""
    data: Dict[str, str] = {}
    for f in fields:
        name = f["name"]
        ftype = f["type"]
        lower = name.lower()

        if ftype == "hidden" and f.get("value"):
            data[name] = f["value"]
        elif ftype == "select" and f.get("value"):
            data[name] = f["value"]
        elif ftype == "email" or "email" in lower:
            data[name] = _TEST_EMAIL
        elif ftype == "password" or "password" in lower:
            data[name] = _TEST_PASSWORD
        elif ftype in ("number", "range"):
            data[name] = "500000"
        elif ftype == "url" or "url" in lower:
            data[name] = "https://example.com"
        elif ftype == "tel":
            data[name] = "+1-555-0100"
        else:
            data[name] = "Test"
    return data


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
        # Collect all option values so the LLM knows valid choices
        options = re.findall(
            r'<option\b[^>]*value\s*=\s*["\']([^"\']+)', inner, re.IGNORECASE
        )
        value = options[0] if options else ""
        fields.append({"name": name, "type": "select", "value": value,
                        "options": options})

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

    Only matches routes whose **path** contains auth keywords — does NOT
    scan surrounding code context, which caused false positives (e.g.
    ``/dashboard/startup`` matched because nearby code used ``session``).
    """
    auth_routes: Dict[str, List[str]] = {"login": [], "register": [], "logout": []}

    routes = re.findall(r"""@app\.route\(\s*['"]([^'"]+)['"]""", source)
    for route in routes:
        lower_route = route.lower()
        # Skip parameterized routes
        if "<" in route:
            continue

        if any(kw in lower_route for kw in ("login", "signin", "sign_in", "sign-in")):
            if "logout" not in lower_route and "signout" not in lower_route:
                auth_routes["login"].append(route)
        if any(kw in lower_route for kw in ("register", "signup", "sign_up", "sign-up")):
            auth_routes["register"].append(route)
        if any(kw in lower_route for kw in ("logout", "signout", "sign_out", "sign-out")):
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

    def _post_form(url: str, data: Dict[str, str]) -> Any:
        """POST form data and return the response."""
        encoded = urlencode(data).encode("utf-8")
        req = Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        return opener.open(req, timeout=timeout)

    # --- Step 1: Try to register a test user ---
    # The LLM fills the form dynamically.  We remember ALL the values
    # it chose so we can reuse the same credentials for login.
    reg_data: Dict[str, str] = {}
    registered = False

    for reg_route in register_routes:
        try:
            url = f"{base}/{reg_route.lstrip('/')}"
            resp = opener.open(url, timeout=timeout)
            html = resp.read().decode("utf-8", errors="replace")
            fields = _extract_form_fields(html)
            if not fields:
                continue

            post_data = _llm_fill_form(
                fields,
                form_purpose=f"User registration at {reg_route}",
                page_html=html,
            )
            reg_data = dict(post_data)  # remember for login

            resp = _post_form(url, post_data)
            body = resp.read().decode("utf-8", errors="replace")
            final_url = resp.url or ""

            back_on_register = reg_route.rstrip("/") in final_url.rstrip("/")
            has_error = any(kw in body.lower() for kw in (
                "already exists", "already registered", "error", "invalid",
                "try again", "failed",
            ))
            if back_on_register and has_error:
                logger.debug("Auth session: registration at %s likely failed (error in response)", reg_route)
                continue

            registered = True
            logger.info("Auth session: registered test user via %s", reg_route)
            break
        except Exception as exc:
            logger.debug("Auth session: registration via %s failed: %s", reg_route, exc)
            continue

    if not registered:
        logger.info("Auth session: registration did not succeed, trying login with registration credentials")

    # --- Step 2: Log in ---
    # Reuse the EXACT values from registration (username, email, password)
    # so credentials always match, even if the login form uses different
    # field names than the registration form.
    for login_route in login_routes:
        try:
            url = f"{base}/{login_route.lstrip('/')}"
            resp = opener.open(url, timeout=timeout)
            html = resp.read().decode("utf-8", errors="replace")
            fields = _extract_form_fields(html)
            if not fields:
                continue

            post_data = _llm_fill_form(
                fields,
                form_purpose=f"User login at {login_route}",
                page_html=html,
            )

            # Override login fields with registration values so they match.
            # The login form might use "username" while registration used
            # "username" too — reuse the exact same value.
            if reg_data:
                for field in fields:
                    name = field["name"]
                    lower = name.lower()
                    ftype = field["type"]
                    # Match by type or name pattern
                    if ftype == "password" or "password" in lower:
                        post_data[name] = reg_data.get(
                            name, _TEST_PASSWORD)
                    elif ftype == "email" or "email" in lower:
                        post_data[name] = reg_data.get(
                            name, _TEST_EMAIL)
                    elif "user" in lower and "name" in lower or lower == "username":
                        # Find the username from registration data
                        for rk, rv in reg_data.items():
                            rk_lower = rk.lower()
                            if "user" in rk_lower and "name" in rk_lower or rk_lower == "username":
                                post_data[name] = rv
                                break

            logger.debug("Auth session: login POST data: %s", list(post_data.keys()))
            resp = _post_form(url, post_data)
            body = resp.read().decode("utf-8", errors="replace")

            has_cookies = len(jar) > 0
            final_url = (resp.url or "").lower()
            landed_elsewhere = login_route.lower() not in final_url

            if has_cookies or landed_elsewhere:
                logger.info("Auth session: logged in via %s (cookies: %d)",
                            login_route, len(jar))
                return opener, True

            # Log why login failed
            error_hints = [kw for kw in ("invalid", "incorrect", "wrong", "error", "failed")
                           if kw in body.lower()]
            logger.info("Auth session: login via %s failed (cookies=%d, landed=%s, errors=%s)",
                        login_route, len(jar), final_url, error_hints or "none detected")
        except Exception as exc:
            logger.debug("Auth session: login via %s failed: %s", login_route, exc)
            continue

    # Last resort: try a simple POST with just the fixed credentials
    # to every login route, in case the LLM filled extra fields that
    # confused the app.
    for login_route in login_routes:
        for creds in [
            {"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
            {"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
            {"email": _TEST_EMAIL, "password": _TEST_PASSWORD, "role": "startup"},
        ]:
            try:
                url = f"{base}/{login_route.lstrip('/')}"
                resp = _post_form(url, creds)
                resp.read()
                if len(jar) > 0 or login_route.lower() not in (resp.url or "").lower():
                    logger.info("Auth session: logged in via %s (fallback, cookies: %d)",
                                login_route, len(jar))
                    return opener, True
            except Exception:
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
