"""LLM-powered customer testing against workspace pages.

After QA passes, this module spins up a workspace HTTP server, discovers
HTML pages, and sends each page's content to an LLM with a persona prompt.
The LLM returns structured feedback (bug/friction/feature_request/praise)
which is written to feedback.db via the existing _submit_feedback_impl.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from src.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

PERSONAS: List[Dict[str, str]] = [
    {
        "name": "Sarah (Founder)",
        "system_prompt": (
            "You are Sarah, a first-time startup founder looking for funding. "
            "You are impatient and care deeply about clarity and trust. "
            "You have 2 minutes to decide if this platform is worth your time. "
            "Evaluate the website pages provided and give honest, actionable feedback."
        ),
    },
    {
        "name": "Marcus (VC Partner)",
        "system_prompt": (
            "You are Marcus, an experienced venture capital partner at a top-tier firm. "
            "You have high standards for professionalism and care about deal flow quality. "
            "You evaluate tools and platforms critically. "
            "Review the website pages provided and give honest, actionable feedback."
        ),
    },
    {
        "name": "Priya (Casual Visitor)",
        "system_prompt": (
            "You are Priya, a tech journalist and researcher with a 60-second attention span. "
            "You care about first impressions, visual clarity, and whether the value proposition "
            "is immediately obvious. "
            "Review the website pages provided and give honest, actionable feedback."
        ),
    },
]

# Valid feedback types accepted by _submit_feedback_impl
_VALID_TYPES = {"bug", "friction", "feature_request", "praise"}


# Maximum characters of page HTML to include in the LLM prompt
_MAX_PAGE_CHARS = 6000


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _fetch_page(base_url: str, path: str, timeout: int = 10) -> Optional[str]:
    """Fetch a page and return its body text, or None on error."""
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        with urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError):
        return None


def _discover_pages(base_url: str, workspace_root: str = "") -> Dict[str, str]:
    """Discover pages dynamically from the workspace.

    If ``app.py`` exists (Flask app), extracts routes from ``@app.route``
    decorators and fetches each.  Otherwise scans for ``.html`` files.
    Returns a dict mapping route/path to its rendered HTML content.
    """
    from pathlib import Path
    from src.simulation.http_checks import _discover_flask_routes

    pages: Dict[str, str] = {}

    if workspace_root:
        ws = Path(workspace_root)

        # Prefer Flask route discovery
        if (ws / "app.py").is_file():
            routes = _discover_flask_routes(workspace_root)
            for route in routes:
                body = _fetch_page(base_url, route)
                if body is not None:
                    pages[route] = body
        else:
            # Fallback: scan for .html files
            if ws.is_dir():
                for html_file in sorted(ws.rglob("*.html")):
                    rel_path = str(html_file.relative_to(ws)).replace("\\", "/")
                    if rel_path not in pages:
                        body = _fetch_page(base_url, rel_path)
                        if body is not None:
                            pages[rel_path] = body

    # Fallback: at least try the root
    if not pages:
        index_body = _fetch_page(base_url, "/")
        if index_body is not None:
            pages["/"] = index_body

    return pages


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


def _resolve_customer_model() -> str:
    """Resolve the LLM model string for customer testing.

    Priority: settings.customer_model > settings.openrouter_default_model >
    hardcoded cheap default.
    """
    try:
        from src.utils.config import settings

        if settings.customer_model:
            return settings.customer_model
        if settings.openrouter_default_model:
            return settings.openrouter_default_model
    except Exception:
        pass
    return "openrouter/deepseek/deepseek-v3.2"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_feedback_response(raw_text: str, persona_name: str) -> List[Dict[str, str]]:
    """Parse LLM response into a list of feedback entry dicts.

    Tries:
    1. Direct json.loads
    2. Strip markdown code fences and retry
    3. Regex-extract first [...] block
    Falls back to empty list on total failure.
    """
    entries: List[Dict[str, str]] = []
    cleaned = raw_text.strip()

    # Attempt 1: direct parse
    parsed = _try_parse_json(cleaned)
    if parsed is None:
        # Attempt 2: strip markdown fences
        defenced = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.MULTILINE)
        defenced = re.sub(r"\n?```\s*$", "", defenced, flags=re.MULTILINE)
        parsed = _try_parse_json(defenced.strip())

    if parsed is None:
        # Attempt 3: regex extract first [...]
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            parsed = _try_parse_json(m.group(0))

    if parsed is None:
        logger.warning("Could not parse LLM response for %s", persona_name)
        return []

    if not isinstance(parsed, list):
        parsed = [parsed]

    for item in parsed:
        if not isinstance(item, dict):
            continue
        entry = _normalize_entry(item, persona_name)
        if entry:
            entries.append(entry)

    return entries


def _try_parse_json(text: str) -> Any:
    """Try to parse JSON, return None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _normalize_entry(item: Dict[str, Any], persona_name: str) -> Optional[Dict[str, str]]:
    """Normalize a single feedback entry dict."""
    page = str(item.get("page", "unknown"))
    feedback_type = str(item.get("feedback_type", "friction"))
    message = str(item.get("message", ""))

    if not message:
        return None

    # Normalize invalid feedback_type
    if feedback_type not in _VALID_TYPES:
        feedback_type = "friction"

    # Prefix message with persona name for traceability
    message = f"[{persona_name}] {message}"

    return {
        "page": page,
        "feedback_type": feedback_type,
        "message": message,
    }


# ---------------------------------------------------------------------------
# LLM calling
# ---------------------------------------------------------------------------


def _build_litellm_kwargs(model: str) -> Dict[str, Any]:
    """Build extra kwargs (api_key, api_base) for litellm.completion."""
    from src.utils.config import settings

    kwargs: Dict[str, Any] = {}
    if settings.openrouter_api_key and model.startswith("openrouter/"):
        kwargs["api_key"] = settings.openrouter_api_key
        kwargs["api_base"] = settings.openrouter_base_url
    elif settings.anthropic_api_key and "anthropic" in model:
        kwargs["api_key"] = settings.anthropic_api_key
    elif settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key
    return kwargs


def _call_llm_for_persona(
    persona: Dict[str, str],
    pages: Dict[str, str],
    model: str,
) -> List[Dict[str, str]]:
    """Make one litellm call for a persona and return parsed feedback entries."""
    import litellm

    # Build page content section
    page_sections = []
    for path, html in pages.items():
        truncated = html[:_MAX_PAGE_CHARS]
        page_sections.append(f"--- PAGE: {path} ---\n{truncated}\n")

    pages_text = "\n".join(page_sections)

    user_prompt = f"""Review the following website pages and provide feedback as a JSON array.

Each entry must have these fields:
- "page": the page filename (e.g. "index.html")
- "feedback_type": one of "bug", "friction", "feature_request", "praise"
- "message": your specific, actionable feedback

Return 1-2 entries as a JSON array. Focus on the single most important issue you found. Be specific and constructive.

{pages_text}"""

    try:
        extra_kwargs = _build_litellm_kwargs(model)
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": persona["system_prompt"]},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            **extra_kwargs,
        )
        raw_text = response.choices[0].message.content or ""
        return _parse_feedback_response(raw_text, persona["name"])
    except Exception as exc:
        logger.warning("LLM call failed for %s: %s", persona["name"], exc)
        return []


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------


def _mock_feedback() -> List[Dict[str, str]]:
    """Return deterministic mock feedback (one per persona archetype)."""
    return [
        {
            "page": "index.html",
            "feedback_type": "friction",
            "message": "[Sarah (Founder)] The sign-up process is not immediately visible on the landing page.",
        },
        {
            "page": "index.html",
            "feedback_type": "feature_request",
            "message": "[Marcus (VC Partner)] Add a deal flow dashboard showing recent startup submissions.",
        },
        {
            "page": "index.html",
            "feedback_type": "praise",
            "message": "[Priya (Casual Visitor)] Clean landing page design with a clear value proposition.",
        },
    ]


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


def run_customer_testing(
    base_url: str,
    workspace_root: str,
    emit_fn: Optional[Callable] = None,
    cycle_id: int = 0,
    mock: bool = False,
) -> Dict[str, Any]:
    """Run LLM-powered customer testing against workspace pages.

    Parameters
    ----------
    base_url:
        URL of the running workspace server (e.g. ``http://127.0.0.1:12345``).
    workspace_root:
        Path to the workspace directory (for feedback.db writes).
    emit_fn:
        Optional event emitter callback ``(event_type, payload)``.
    cycle_id:
        Current BML cycle iteration number.
    mock:
        If True, inject deterministic feedback without LLM calls.

    Returns
    -------
    dict with ``status``, ``feedback_count``, ``personas_tested``.
    """
    from src.workspace_tools.file_tools import _submit_feedback_impl

    def _emit(event_type: str, payload: dict) -> None:
        if emit_fn is not None:
            try:
                payload.setdefault("cycle_id", cycle_id)
                emit_fn(event_type, payload)
            except Exception:
                pass

    _emit("customer_testing_start", {"base_url": base_url, "mock": mock})

    # Mock mode: inject deterministic feedback, skip LLM + page discovery
    if mock:
        entries = _mock_feedback()
        submitted = 0
        for entry in entries:
            result = _submit_feedback_impl(
                entry["page"], entry["feedback_type"], entry["message"],
            )
            if result.get("status") == "ok":
                submitted += 1
        _emit("customer_testing_end", {"feedback_count": submitted, "mock": True})
        return {"status": "ok", "feedback_count": submitted, "personas_tested": 3}

    # Discover pages dynamically from workspace directory
    pages = _discover_pages(base_url, workspace_root)
    if not pages:
        logger.info("Customer testing: no pages discovered, skipping.")
        _emit("customer_testing_end", {"feedback_count": 0, "reason": "no_pages"})
        return {"status": "ok", "feedback_count": 0, "personas_tested": 0}

    logger.info("Customer testing: discovered %d pages: %s", len(pages), list(pages.keys()))

    # Resolve model
    model = _resolve_customer_model()
    logger.info("Customer testing: using model %s", model)

    # Call LLM for each persona
    total_submitted = 0
    personas_tested = 0

    for persona in PERSONAS:
        entries = _call_llm_for_persona(persona, pages, model)
        if entries:
            personas_tested += 1
            for entry in entries:
                result = _submit_feedback_impl(
                    entry["page"], entry["feedback_type"], entry["message"],
                )
                if result.get("status") == "ok":
                    total_submitted += 1
                else:
                    logger.warning(
                        "Failed to submit feedback for %s: %s",
                        persona["name"], result,
                    )
        _emit("customer_persona_done", {
            "persona": persona["name"],
            "entries": len(entries),
        })

    logger.info(
        "Customer testing complete: %d entries from %d personas",
        total_submitted, personas_tested,
    )
    _emit("customer_testing_end", {
        "feedback_count": total_submitted,
        "personas_tested": personas_tested,
    })

    return {
        "status": "ok",
        "feedback_count": total_submitted,
        "personas_tested": personas_tested,
    }
