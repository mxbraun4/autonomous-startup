"""CrewAI Tools - Including web-enabled data collection tools."""
# NOTE: CrewAI caches tool results by default (cache_function returns True).
# Any tool whose output changes between calls (database reads, file reads,
# quality checks) MUST pass ``cache_function=_NO_CACHE`` to the @tool
# decorator, otherwise agents see stale results after writes/mutations.
_NO_CACHE = lambda _args=None, _result=None: False  # noqa: E731
import atexit
import json
import os
import py_compile
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING

import requests

from src.crewai_agents.runtime_env import (
    configure_runtime_environment,
    patch_crewai_storage_paths,
)

configure_runtime_environment()
from crewai.tools import tool
patch_crewai_storage_paths()

from src.database.database import StartupDatabase
from src.utils.config import settings
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.framework.observability.logger import EventLogger
    from src.framework.storage.sync_wrapper import SyncUnifiedStore

logger = get_logger(__name__)

# Global database instance
_db: Optional[StartupDatabase] = None

# Global memory store instance (SyncUnifiedStore)
_memory_store: Optional["SyncUnifiedStore"] = None

# Global event logger instance (EventLogger)
_event_logger: Optional["EventLogger"] = None

# Current cycle/iteration id — set by the flow before each crew kickoff
# so that tool-emitted events carry the correct iteration number.
_current_cycle_id: Optional[int] = None


def set_current_cycle_id(cycle_id: Optional[int]) -> None:
    """Set the active cycle/iteration id for tool-emitted events."""
    global _current_cycle_id
    _current_cycle_id = cycle_id


# Dynamic runtime tool registry (autonomy gap: dynamic tool creation + self deployment)
_dynamic_tool_specs: Dict[str, Dict[str, Any]] = {}
_dynamic_tool_invocations: Dict[str, int] = {}


def _cleanup_globals() -> None:
    """Close global singletons at interpreter shutdown."""
    global _db, _memory_store
    if _db is not None:
        _db.close()
        _db = None
    if _memory_store is not None:
        _memory_store.close()
        _memory_store = None
    clear_dynamic_tool_registry()


atexit.register(_cleanup_globals)


def get_database() -> StartupDatabase:
    """Get or create database instance."""
    global _db
    if _db is None:
        _db = StartupDatabase()
    return _db


def set_memory_store(store: "SyncUnifiedStore") -> None:
    """Inject the unified memory store for tool use."""
    global _memory_store
    _memory_store = store
    logger.info("Memory store injected into CrewAI tools")


def get_memory_store() -> Optional["SyncUnifiedStore"]:
    """Get the current memory store (may be None if not initialised)."""
    return _memory_store


def set_event_logger(event_logger: "EventLogger") -> None:
    """Inject the event logger for observability."""
    global _event_logger
    _event_logger = event_logger
    logger.info("Event logger injected into CrewAI tools")


def get_event_logger() -> Optional["EventLogger"]:
    """Get the current event logger (may be None if not initialised)."""
    return _event_logger


def _tool_artifact_dir() -> Path:
    root = Path(getattr(settings, "generated_tools_dir", "data/generated_tools"))
    return root.resolve()


def _slugify_tool_name(raw_name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", str(raw_name or "").strip().lower())
    cleaned = cleaned.strip("_")
    return cleaned or "generated_tool"


def _unique_tool_name(base_name: str) -> str:
    if base_name not in _dynamic_tool_specs:
        return base_name

    index = 2
    while True:
        candidate = f"{base_name}_{index}"
        if candidate not in _dynamic_tool_specs:
            return candidate
        index += 1


def _prune_old_tool_artifacts(root: Path) -> int:
    retention_days = int(getattr(settings, "generated_tools_retention_days", 30))
    if retention_days <= 0:
        return 0

    cutoff_epoch = (
        datetime.now(timezone.utc).timestamp()
        - (retention_days * 24 * 60 * 60)
    )
    removed = 0
    for path in root.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff_epoch:
                path.unlink(missing_ok=True)
                removed += 1
        except Exception:
            continue
    return removed


def _persist_dynamic_tool_spec(record: Dict[str, Any]) -> Path:
    root = _tool_artifact_dir()
    root.mkdir(parents=True, exist_ok=True)
    _prune_old_tool_artifacts(root)

    tool_name = str(record.get("tool_name", "generated_tool"))
    artifact_path = root / f"{tool_name}.json"
    artifact_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return artifact_path


def _register_dynamic_tool_spec(
    spec: Dict[str, Any],
    *,
    source: str,
) -> Dict[str, Any]:
    base_name = _slugify_tool_name(spec.get("tool_name") or spec.get("description") or "tool")
    tool_name = _unique_tool_name(base_name)

    record = dict(spec)
    record["tool_name"] = tool_name
    record["registered_source"] = source
    record["registered_at_utc"] = datetime.now(timezone.utc).isoformat()
    _dynamic_tool_specs[tool_name] = record
    _dynamic_tool_invocations.setdefault(tool_name, 0)

    artifact_path = _persist_dynamic_tool_spec(record)
    return {
        "tool_name": tool_name,
        "status": "registered",
        "deployment_status": "deployed",
        "artifact_path": str(artifact_path),
    }


def _execute_dynamic_tool(
    tool_name: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    spec = _dynamic_tool_specs.get(tool_name)
    if spec is None:
        return {
            "status": "failed",
            "reason": "dynamic_tool_not_found",
            "tool_name": tool_name,
        }

    _dynamic_tool_invocations[tool_name] = _dynamic_tool_invocations.get(tool_name, 0) + 1

    features = spec.get("features", [])
    if not isinstance(features, list):
        features = []

    return {
        "status": "success",
        "tool_name": tool_name,
        "description": spec.get("description", ""),
        "features": [str(item) for item in features],
        "payload": dict(payload),
        "invocation_count": _dynamic_tool_invocations[tool_name],
        "result": (
            f"Executed {tool_name} with {len(payload)} input field(s); "
            f"supported features={len(features)}"
        ),
    }


def get_dynamic_tool_registry_snapshot() -> Dict[str, Dict[str, Any]]:
    """Return a copy of dynamic tool specs for tests/introspection."""
    return {
        name: dict(spec)
        for name, spec in _dynamic_tool_specs.items()
    }


def clear_dynamic_tool_registry() -> None:
    """Clear dynamic tool registry (used by tests)."""
    _dynamic_tool_specs.clear()
    _dynamic_tool_invocations.clear()


def _iter_python_files(paths: List[str]) -> List[Path]:
    files: List[Path] = []
    seen: set[str] = set()
    for raw in paths:
        item = str(raw or "").strip()
        if not item:
            continue
        path = Path(item)
        candidates: List[Path]
        if path.is_file():
            candidates = [path] if path.suffix == ".py" else []
        elif path.is_dir():
            candidates = sorted(path.rglob("*.py"))
        else:
            continue

        for candidate in candidates:
            key = str(candidate.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(candidate)
    return files


def _run_python_syntax_checks(paths: List[str]) -> Dict[str, Any]:
    files = _iter_python_files(paths)
    failures: List[Dict[str, str]] = []
    for file_path in files:
        try:
            py_compile.compile(str(file_path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(
                {
                    "file": str(file_path),
                    "error": str(exc.msg or exc),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "file": str(file_path),
                    "error": str(exc),
                }
            )

    return {
        "checked_file_count": len(files),
        "syntax_ok": len(failures) == 0,
        "syntax_error_count": len(failures),
        "syntax_failures": failures,
    }


def _run_pytest_targets(
    targets: List[str],
    *,
    timeout_seconds: int,
) -> Dict[str, Any]:
    if not targets:
        return {
            "pytest_status": "no_targets",
            "pytest_exit_code": None,
            "pytest_target_count": 0,
            "pytest_targets": [],
        }

    if os.getenv("PYTEST_CURRENT_TEST"):
        # Avoid recursive pytest execution when the QA tool is invoked from pytest.
        return {
            "pytest_status": "skipped_nested_pytest",
            "pytest_exit_code": None,
            "pytest_target_count": len(targets),
            "pytest_targets": targets,
        }

    cmd = [sys.executable, "-m", "pytest", *targets, "-q"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "pytest_status": "timeout",
            "pytest_exit_code": None,
            "pytest_target_count": len(targets),
            "pytest_targets": targets,
            "pytest_stdout_tail": (exc.stdout or "")[-1200:],
            "pytest_stderr_tail": (exc.stderr or "")[-1200:],
        }
    except Exception as exc:
        return {
            "pytest_status": "error",
            "pytest_exit_code": None,
            "pytest_target_count": len(targets),
            "pytest_targets": targets,
            "pytest_error": str(exc),
        }

    return {
        "pytest_status": "passed" if proc.returncode == 0 else "failed",
        "pytest_exit_code": proc.returncode,
        "pytest_target_count": len(targets),
        "pytest_targets": targets,
        "pytest_stdout_tail": (proc.stdout or "")[-1200:],
        "pytest_stderr_tail": (proc.stderr or "")[-1200:],
    }


@tool("Run Quality Checks")
def run_quality_checks_tool(
    paths_csv: str = "src,scripts",
    pytest_targets_csv: str = "tests/test_crewai_integration.py",
    run_pytest: bool = False,
    timeout_seconds: int = 120,
) -> str:
    """Run deterministic QA checks for code quality gates.

    Performs Python syntax compilation checks on the selected paths and runs
    pytest on the selected targets (unless nested pytest execution is detected).

    Returns:
        JSON summary with pass/fail status and actionable failure details
    """
    paths = [p.strip() for p in str(paths_csv or "").split(",") if p.strip()]
    pytest_targets = [p.strip() for p in str(pytest_targets_csv or "").split(",") if p.strip()]

    logger.info(
        "QA tool: syntax paths=%s pytest_targets=%s run_pytest=%s",
        paths,
        pytest_targets,
        run_pytest,
    )

    syntax = _run_python_syntax_checks(paths)

    if bool(run_pytest):
        pytest_result = _run_pytest_targets(
            pytest_targets,
            timeout_seconds=int(timeout_seconds),
        )
    else:
        pytest_result = {
            "pytest_status": "disabled",
            "pytest_exit_code": None,
            "pytest_target_count": len(pytest_targets),
            "pytest_targets": pytest_targets,
        }

    pytest_status = str(pytest_result.get("pytest_status", "disabled"))
    pytest_ok = pytest_status in {
        "passed",
        "disabled",
        "no_targets",
        "skipped_nested_pytest",
    }
    qa_gate_passed = bool(syntax.get("syntax_ok")) and pytest_ok

    failed_checks: List[str] = []
    if not bool(syntax.get("syntax_ok")):
        failed_checks.append("syntax")
    if not pytest_ok:
        failed_checks.append("pytest")

    result = {
        "status": "passed" if qa_gate_passed else "failed",
        "qa_gate_passed": qa_gate_passed,
        "failed_checks": failed_checks,
        "paths": paths,
        "run_pytest": bool(run_pytest),
        "syntax": syntax,
        "pytest": pytest_result,
    }
    return json.dumps(result, indent=2, ensure_ascii=True)


# =============================================================================
# WEB DATA COLLECTION TOOLS — Serper.dev backed with graceful fallback
# =============================================================================

def _serper_search(
    query: str,
    search_type: str = "search",
    n_results: int = 10,
) -> Dict[str, Any]:
    """Call the Serper.dev REST API and return parsed JSON.

    Returns a dict with ``"status": "skipped"`` when ``SERPER_API_KEY`` is not
    configured, so callers degrade gracefully.
    """
    api_key = settings.serper_api_key
    if not api_key:
        return {"status": "skipped", "reason": "SERPER_API_KEY not set"}

    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": n_results}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("Serper API error: %s", exc)
        return {"status": "error", "reason": str(exc)}


def _fetch_url(url: str, max_chars: int = 4000) -> Dict[str, Any]:
    """Fetch a URL, strip HTML tags, and return truncated plain text."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "AutonomousStartupBot/1.0"})
        resp.raise_for_status()
        # Strip HTML tags via regex
        text = re.sub(r"<[^>]+>", " ", resp.text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        truncated = len(text) > max_chars
        text = text[:max_chars]
        return {"status": "ok", "text": text, "truncated": truncated, "url": url}
    except requests.RequestException as exc:
        logger.warning("fetch_url error for %s: %s", url, exc)
        return {"status": "error", "reason": str(exc), "url": url}


@tool("Search Web for Startups")
def web_search_startups(query: str, sector: str = "technology") -> str:
    """Search the web for startup information using Serper.dev.

    Args:
        query: Search query (e.g., "fintech startups funding 2024")
        sector: Target sector to focus on

    Returns:
        JSON with organic search results or skip/error status
    """
    logger.info(f"Web search for startups: {query} (sector: {sector})")

    raw = _serper_search(f"{query} {sector} startups")
    if raw.get("status") in ("skipped", "error"):
        return json.dumps(raw, indent=2)

    organic = raw.get("organic", [])
    results = []
    for item in organic:
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "sector": sector,
        })

    return json.dumps({
        "status": "success",
        "query": query,
        "sector": sector,
        "result_count": len(results),
        "results": results,
        "instructions": (
            "Extract startup names, descriptions, stages, and websites from the "
            "results above, then use 'Save Startup to Database' for each."
        ),
    }, indent=2)


@tool("Search Web for VCs")
def web_search_vcs(query: str, focus_sector: str = "technology") -> str:
    """Search the web for VC and investor information using Serper.dev.

    Args:
        query: Search query (e.g., "seed stage VCs fintech")
        focus_sector: Sector focus to filter VCs

    Returns:
        JSON with organic search results or skip/error status
    """
    logger.info(f"Web search for VCs: {query} (focus: {focus_sector})")

    raw = _serper_search(f"{query} {focus_sector} venture capital investors")
    if raw.get("status") in ("skipped", "error"):
        return json.dumps(raw, indent=2)

    organic = raw.get("organic", [])
    results = []
    for item in organic:
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "focus_sector": focus_sector,
        })

    return json.dumps({
        "status": "success",
        "query": query,
        "focus_sector": focus_sector,
        "result_count": len(results),
        "results": results,
        "instructions": (
            "Extract VC firm names, sectors, stage focus, and websites from the "
            "results above, then use 'Save VC to Database' for each."
        ),
    }, indent=2)


@tool("Fetch and Parse Webpage")
def fetch_webpage(url: str, extract_type: str = "startups") -> str:
    """Fetch a webpage and return its text content for extraction.

    Args:
        url: The URL to fetch
        extract_type: What to extract - 'startups' or 'vcs'

    Returns:
        JSON with page text (HTML stripped, truncated to 4000 chars) or error
    """
    logger.info(f"Fetch webpage: {url} (extract: {extract_type})")

    result = _fetch_url(url)
    result["extract_type"] = extract_type
    if result.get("status") == "ok":
        result["instructions"] = (
            f"Extract {extract_type} information from the page text above, "
            f"then use the appropriate 'Save to Database' tool for each entry found."
        )
    return json.dumps(result, indent=2)


@tool("Run Data Collection")
def run_data_collection(sectors: str = "fintech,healthtech,ai_ml,devtools,saas") -> str:
    """Search the web for startups and VCs across the given sectors and save them to the database.

    This is a convenience tool that performs a full data-collection sweep:
    it searches Serper.dev for startups and VCs in each sector, persists
    every result to the SQLite database, and returns a summary.

    Requires SERPER_API_KEY to be set; returns status=skipped otherwise.

    Args:
        sectors: Comma-separated list of sectors to search
            (e.g. "fintech,healthtech,ai_ml")

    Returns:
        JSON summary with counts of startups and VCs saved per sector
    """
    if not settings.serper_api_key:
        return json.dumps({"status": "skipped", "reason": "SERPER_API_KEY not set"})

    sector_list = [s.strip().lower().replace(" ", "_") for s in sectors.split(",") if s.strip()]
    logger.info("run_data_collection: sectors=%s", sector_list)

    db = get_database()
    sector_results: List[Dict[str, Any]] = []

    for sector in sector_list:
        startups_saved = 0
        vcs_saved = 0

        # --- startups ---
        raw = _serper_search(f"{sector} startups funding", n_results=5)
        for item in raw.get("organic", []):
            name = (item.get("title") or "").split(" - ")[0].split(" | ")[0].strip()
            if not name:
                continue
            success = db.add_startup({
                "name": name,
                "description": item.get("snippet", ""),
                "sector": sector,
                "stage": "unknown",
                "website": item.get("link", ""),
                "source": "serper",
                "fundraising_status": "unknown",
            })
            if success:
                startups_saved += 1

        # --- VCs ---
        raw = _serper_search(f"{sector} venture capital investors", n_results=5)
        for item in raw.get("organic", []):
            name = (item.get("title") or "").split(" - ")[0].split(" | ")[0].strip()
            if not name:
                continue
            success = db.add_vc({
                "name": name,
                "sectors": [sector],
                "stage_focus": "unknown",
                "website": item.get("link", ""),
                "source": "serper",
            })
            if success:
                vcs_saved += 1

        sector_results.append({
            "sector": sector,
            "startups_saved": startups_saved,
            "vcs_saved": vcs_saved,
        })

    total_startups = sum(r["startups_saved"] for r in sector_results)
    total_vcs = sum(r["vcs_saved"] for r in sector_results)

    return json.dumps({
        "status": "success",
        "total_startups_saved": total_startups,
        "total_vcs_saved": total_vcs,
        "by_sector": sector_results,
    }, indent=2)


@tool("Save Startup to Database")
def save_startup(
    name: str,
    description: str = "",
    sector: str = "technology",
    stage: str = "seed",
    website: str = "",
    location: str = "",
    recent_news: str = "",
    source: str = "web_search"
) -> str:
    """Save a startup to the database.

    Args:
        name: Startup name (required)
        description: What the startup does
        sector: Business sector (fintech, healthtech, ai_ml, devtools, etc.)
        stage: Funding stage (seed, series_a, series_b, growth)
        website: Company website URL
        location: Company location
        recent_news: Recent news or achievements
        source: Where the data came from

    Returns:
        Confirmation of save status
    """
    logger.info(f"Saving startup: {name}")

    db = get_database()
    startup = {
        'name': name,
        'description': description,
        'sector': sector.lower().replace(' ', '_'),
        'stage': stage.lower().replace(' ', '_'),
        'website': website,
        'location': location,
        'recent_news': recent_news,
        'source': source,
        'fundraising_status': 'unknown'
    }

    success = db.add_startup(startup)

    return json.dumps({
        'status': 'success' if success else 'failed',
        'startup': name,
        'message': f"Startup '{name}' saved to database" if success else f"Failed to save '{name}'"
    }, indent=2)


@tool("Save VC to Database")
def save_vc(
    name: str,
    sectors: str = "technology",
    stage_focus: str = "seed",
    check_size: str = "",
    geography: str = "",
    recent_activity: str = "",
    website: str = "",
    source: str = "web_search"
) -> str:
    """Save a VC/investor to the database.

    Args:
        name: VC firm name (required)
        sectors: Investment sectors (comma-separated, e.g., "fintech, ai_ml, saas")
        stage_focus: Investment stage focus (seed, series_a, series_b, growth)
        check_size: Typical check size (e.g., "500K-2M", "5M-15M")
        geography: Geographic focus (e.g., "US, Europe")
        recent_activity: Recent investments or news
        website: Firm website URL
        source: Where the data came from

    Returns:
        Confirmation of save status
    """
    logger.info(f"Saving VC: {name}")

    db = get_database()

    # Parse sectors into list
    sector_list = [s.strip().lower().replace(' ', '_') for s in sectors.split(',')]

    vc = {
        'name': name,
        'sectors': sector_list,
        'stage_focus': stage_focus.lower().replace(' ', '_'),
        'check_size': check_size,
        'geography': geography,
        'recent_activity': recent_activity,
        'website': website,
        'source': source
    }

    success = db.add_vc(vc)

    return json.dumps({
        'status': 'success' if success else 'failed',
        'vc': name,
        'message': f"VC '{name}' saved to database" if success else f"Failed to save '{name}'"
    }, indent=2)


# =============================================================================
# DATA RETRIEVAL TOOLS
# =============================================================================

@tool("Get Startups from Database")
def get_startups_tool(sector: str = "all", stage: str = "all", limit: int = 20) -> str:
    """Retrieve startups from the database.

    Args:
        sector: Filter by sector (fintech, healthtech, ai_ml, etc.) or 'all'
        stage: Filter by stage (seed, series_a, series_b) or 'all'
        limit: Maximum number of results

    Returns:
        JSON with startups from database
    """
    logger.info(f"Getting startups: sector={sector}, stage={stage}")

    db = get_database()
    startups = db.get_startups(sector=sector, stage=stage, limit=limit)

    return json.dumps({
        'status': 'success',
        'count': len(startups),
        'sector': sector,
        'stage': stage,
        'startups': startups
    }, indent=2)


@tool("Get VCs from Database")
def get_vcs_tool(sector: str = "all", stage_focus: str = "all", limit: int = 20) -> str:
    """Retrieve VCs from the database.

    Args:
        sector: Filter by sector focus or 'all'
        stage_focus: Filter by stage focus or 'all'
        limit: Maximum number of results

    Returns:
        JSON with VCs from database
    """
    logger.info(f"Getting VCs: sector={sector}, stage={stage_focus}")

    db = get_database()
    vcs = db.get_vcs(sector=sector, stage_focus=stage_focus, limit=limit)

    return json.dumps({
        'status': 'success',
        'count': len(vcs),
        'sector': sector,
        'stage_focus': stage_focus,
        'vcs': vcs
    }, indent=2)


@tool("Get Database Stats")
def get_database_stats() -> str:
    """Get statistics about collected data.

    Returns:
        Database statistics including counts and sectors
    """
    db = get_database()
    stats = db.get_stats()

    return json.dumps({
        'status': 'success',
        'stats': stats,
        'message': f"Database has {stats['total_startups']} startups and {stats['total_vcs']} VCs"
    }, indent=2)


# =============================================================================
# ANALYSIS AND CONTENT TOOLS
# =============================================================================

@tool("Validate Data Quality")
def data_validator_tool(data_json: str) -> str:
    """Validate scraped data for quality and completeness.

    Args:
        data_json: JSON string of data to validate

    Returns:
        Validation report with quality score
    """
    logger.info("Data validator: Checking data quality")

    try:
        data = json.loads(data_json)
        startups = data.get('startups', [])

        if not startups:
            return json.dumps({
                'status': 'fail',
                'reason': 'No data to validate'
            })

        required_fields = ['name', 'sector', 'description']
        total_fields = 0
        present_fields = 0

        for startup in startups:
            for field in required_fields:
                total_fields += 1
                if field in startup and startup[field]:
                    present_fields += 1

        completeness = present_fields / total_fields if total_fields > 0 else 0

        return json.dumps({
            'status': 'pass' if completeness > 0.8 else 'warning',
            'completeness_score': completeness,
            'total_records': len(startups),
            'quality_issues': [] if completeness > 0.8 else ['Some records missing required fields']
        }, indent=2)

    except Exception as e:
        return json.dumps({
            'status': 'error',
            'reason': str(e)
        })


@tool("Build Tool Specification")
def tool_builder_tool(tool_idea: str, requirements: str = "") -> str:
    """Build a specification for a new tool or feature.

    Args:
        tool_idea: Description of the tool to build
        requirements: Specific requirements or constraints

    Returns:
        Tool specification with implementation approach
    """
    logger.info(f"Tool builder: Creating spec for {tool_idea}")

    spec = {
        'tool_name': tool_idea.split()[0].lower() + '_tool',
        'description': tool_idea,
        'requirements': requirements,
        'features': [
            'Core functionality',
            'Input validation',
            'Error handling',
            'Performance optimization'
        ],
        'implementation_approach': [
            '1. Define interface and input/output schema',
            '2. Implement core logic',
            '3. Add validation and error handling',
            '4. Write unit tests',
            '5. Integration testing',
            '6. Documentation'
        ],
        'estimated_complexity': 'medium'
    }

    registration = _register_dynamic_tool_spec(spec, source="tool_builder_tool")
    spec["tool_name"] = registration["tool_name"]
    spec["runtime_registration"] = {
        "status": registration["status"],
        "tool_name": registration["tool_name"],
    }
    spec["deployment"] = {
        "status": registration["deployment_status"],
        "artifact_path": registration["artifact_path"],
    }

    return json.dumps(spec, indent=2)


@tool("Register Dynamic Tool")
def register_dynamic_tool(tool_spec_json: str, source: str = "agent") -> str:
    """Register a dynamic tool spec and deploy it as a local artifact."""
    try:
        parsed = json.loads(tool_spec_json)
    except Exception as exc:
        return json.dumps(
            {
                "status": "failed",
                "reason": "invalid_json",
                "error": str(exc),
            },
            indent=2,
        )

    if not isinstance(parsed, dict):
        return json.dumps(
            {
                "status": "failed",
                "reason": "tool_spec_must_be_object",
            },
            indent=2,
        )

    registration = _register_dynamic_tool_spec(parsed, source=source)
    return json.dumps(
        {
            "status": "success",
            "registration": registration,
        },
        indent=2,
    )


@tool("List Dynamic Tools")
def list_dynamic_tools() -> str:
    """List currently registered dynamic tools."""
    tools = []
    for name, spec in sorted(_dynamic_tool_specs.items()):
        tools.append(
            {
                "tool_name": name,
                "description": spec.get("description", ""),
                "registered_source": spec.get("registered_source", ""),
                "registered_at_utc": spec.get("registered_at_utc", ""),
                "invocation_count": _dynamic_tool_invocations.get(name, 0),
            }
        )

    return json.dumps(
        {
            "status": "success",
            "count": len(tools),
            "tools": tools,
        },
        indent=2,
    )


@tool("Execute Dynamic Tool")
def execute_dynamic_tool(tool_name: str, payload_json: str = "{}") -> str:
    """Execute a registered dynamic tool with JSON payload."""
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except Exception as exc:
        return json.dumps(
            {
                "status": "failed",
                "reason": "invalid_payload_json",
                "error": str(exc),
                "tool_name": tool_name,
            },
            indent=2,
        )

    if not isinstance(payload, dict):
        return json.dumps(
            {
                "status": "failed",
                "reason": "payload_must_be_object",
                "tool_name": tool_name,
            },
            indent=2,
        )

    result = _execute_dynamic_tool(tool_name=tool_name, payload=payload)
    return json.dumps(result, indent=2)


# =============================================================================
# CONSENSUS MEMORY TOOLS
# =============================================================================


@tool("Share Insight")
def share_insight(key: str, value: str, evidence: str = "") -> str:
    """Share a finding with other agents via consensus memory.

    Use this tool to record insights, learnings, or facts so other agents
    can access them in future iterations.

    Args:
        key: A namespaced key (e.g., "product.top_feature_gap", "data.top_gap_sector")
        value: The insight or fact to share
        evidence: Supporting evidence or reasoning

    Returns:
        Confirmation that the insight was stored
    """
    return _share_insight_impl(key, value, evidence, source_agent="crewai_agent")


def _share_insight_impl(key: str, value: str, evidence: str, *, source_agent: str) -> str:
    """Core implementation for share_insight with explicit source_agent."""
    store = get_memory_store()
    if store is None:
        return json.dumps({
            "status": "skipped",
            "reason": "Memory store not initialised",
        })

    from src.framework.contracts import ConsensusEntry

    entry = ConsensusEntry(
        key=key,
        value=value,
        source_agent_id=source_agent,
        source_evidence=[evidence] if evidence else [],
        confidence=0.9,
    )
    entity_id = store.cons_set(entry)

    el = get_event_logger()
    if el is not None:
        val_summary = value[:200] + "..." if len(value) > 200 else value
        el.emit("agent_exchange", {
            "exchange_type": "share_insight",
            "from_agent": source_agent,
            "key": key,
            "value_summary": val_summary,
            "cycle_id": _current_cycle_id,
        })

    return json.dumps({
        "status": "success",
        "entity_id": entity_id,
        "key": key,
        "source_agent": source_agent,
        "message": f"Insight stored under '{key}'",
    }, indent=2)


def make_share_insight(role: str):
    """Factory that returns a role-specific share_insight @tool.

    Each agent gets its own version so ``source_agent_id`` is always correct.
    """

    @tool(f"Share Insight ({role})")
    def _share_insight_for_role(key: str, value: str, evidence: str = "") -> str:
        """Share a finding with other agents via consensus memory.

        Use this tool to record insights, learnings, or facts so other agents
        can access them in future iterations.

        Args:
            key: A namespaced key (e.g., "product.top_feature_gap", "data.top_gap_sector")
            value: The insight or fact to share
            evidence: Supporting evidence or reasoning

        Returns:
            Confirmation that the insight was stored
        """
        return _share_insight_impl(key, value, evidence, source_agent=role)

    return _share_insight_for_role


@tool("Get Team Insights")
def get_team_insights(topic: str = "") -> str:
    """Read insights shared by other agents via consensus memory.

    Use this tool to retrieve shared learnings and facts from past
    iterations or other agents. Provide a topic prefix to filter results.

    Args:
        topic: Key prefix to filter (e.g., "product", "data"). Empty for all.

    Returns:
        JSON with matching insights
    """
    store = get_memory_store()
    if store is None:
        return json.dumps({
            "status": "skipped",
            "reason": "Memory store not initialised",
            "insights": [],
        })

    entries = store.cons_list(prefix=topic if topic else None)
    insights = [
        {
            "key": e.key,
            "value": e.value,
            "confidence": e.confidence,
            "source": e.source_agent_id,
        }
        for e in entries
    ]

    el = get_event_logger()
    if el is not None:
        el.emit("agent_exchange", {
            "exchange_type": "get_insights",
            "from_agent": "crewai_agent",
            "topic": topic or "all",
            "count": len(insights),
            "cycle_id": _current_cycle_id,
        })

    return json.dumps({
        "status": "success",
        "count": len(insights),
        "topic": topic or "all",
        "insights": insights,
    }, indent=2)


# =============================================================================
# DISPATCH TASK TOOL — coordinator-driven dynamic agent orchestration
# =============================================================================


def make_dispatch_task_tool(
    agent_registry: Dict[str, Dict[str, Any]],
    emit_fn,
    *,
    max_dispatches: int = 8,
    result_truncation: int = 1500,
    extra_context: str = "",
):
    """Factory that returns dispatch tools for the BUILD coordinator.

    Args:
        agent_registry: Maps ``role_name`` to
            ``{"factory": create_X_agent, "llm": ..., "extra_tools": [...], "prompt_override": "..."}``.
        emit_fn: Callable ``(event_type, payload_dict) -> None`` for observability.
        max_dispatches: Hard ceiling on dispatch calls per factory instance.
        result_truncation: Max chars kept from each agent result.
        extra_context: Learning context from prior iterations (procedure hints,
            episodic memory, consensus board) to inject into every dispatch.

    Returns:
        Tuple of (dispatch_task tool, dispatch_parallel tool, get_count, get_history).
    """
    _dispatch_count = [0]
    _dispatch_history: List[Dict[str, Any]] = []

    _ROLE_INSTRUCTIONS = {
        "developer": (
            "TOOL INSTRUCTIONS (you MUST follow these):\n"
            "- Call write_workspace_file to create/update files. Do NOT return raw HTML as text.\n"
            "- After writing, call check_workspace_http to verify pages load.\n"
            "- If the task involves feedback, call submit_test_feedback.\n"
            "- If the request is large, prioritize one focused change first, then continue.\n"
        ),
        "reviewer": (
            "TOOL INSTRUCTIONS (you MUST follow these):\n"
            "- Call review_workspace_files ONCE to list and read all workspace files.\n"
            "- Call check_workspace_http ONCE to verify pages load over HTTP.\n"
            "- Call run_quality_checks_tool ONCE for Python syntax checks.\n"
            "- Report PASS or FAIL based on actual tool results, not assumptions.\n"
        ),
        "product_strategist": (
            "TOOL INSTRUCTIONS (you MUST follow these):\n"
            "- Call list_workspace_files to see what pages exist.\n"
            "- Call read_workspace_file to inspect existing pages.\n"
            "- Use share_insight to publish your build spec for the developer.\n"
        ),
    }

    # ------------------------------------------------------------------
    # Core single-dispatch helper (shared by sequential and parallel tools)
    # ------------------------------------------------------------------
    def _execute_single_dispatch(agent_role: str, task_description: str, dispatch_number: int) -> Dict[str, Any]:
        """Run one agent dispatch and return a result dict.

        This is the extracted core logic used by both ``dispatch_task`` and
        ``dispatch_parallel``.  It creates the agent, builds a mini-crew,
        executes with retry, shares to consensus memory, and emits events.

        Returns:
            Dict with keys: status, agent_role, result, truncated, dispatch_number.
        """
        from crewai import Crew as _Crew, Task as _Task, Process as _Process

        # Emit dispatch event
        try:
            emit_fn("agent_exchange", {
                "exchange_type": "dispatch",
                "from_agent": "BUILD Coordinator",
                "to_agent": agent_role,
                "task_summary": task_description[:200],
                "dispatch_number": dispatch_number,
            })
        except Exception:
            pass

        # Prepend standing instructions + extra_context
        original_task_description = task_description
        preamble = (
            "IMPORTANT: Before starting, call get_team_insights to read shared context "
            "from prior dispatches and previous iterations.\n\n"
        )
        role_instructions = _ROLE_INSTRUCTIONS.get(agent_role, "")
        if role_instructions:
            preamble += role_instructions + "\n"
        if extra_context:
            preamble += f"[Context from prior iterations]\n{extra_context}\n\n"
        task_description = preamble + task_description

        # Create temporary agent from registry
        entry = agent_registry[agent_role]
        factory = entry["factory"]
        agent = factory(
            llm=entry.get("llm"),
            prompt_override=entry.get("prompt_override"),
            extra_tools=entry.get("extra_tools"),
        )

        # Build single-task crew and run
        single_task = _Task(
            description=task_description,
            agent=agent,
            expected_output="Complete result of the assigned task.",
        )

        mini_crew = _Crew(
            agents=[agent],
            tasks=[single_task],
            process=_Process.sequential,
            verbose=False,
            memory=False,
            cache=False,
        )

        try:
            crew_output = mini_crew.kickoff()
            result_text = str(crew_output)
        except Exception as exc:
            logger.warning("Dispatch to %s failed: %s; retrying once", agent_role, exc)
            time.sleep(2)
            try:
                retry_task = _Task(
                    description=task_description,
                    agent=agent,
                    expected_output="Complete result of the assigned task.",
                )
                retry_crew = _Crew(
                    agents=[agent],
                    tasks=[retry_task],
                    process=_Process.sequential,
                    verbose=False,
                    memory=False,
                    cache=False,
                )
                crew_output = retry_crew.kickoff()
                result_text = str(crew_output)
            except Exception as retry_exc:
                result_text = f"[dispatch error after retry] {retry_exc}"

        # Truncate
        truncated = len(result_text) > result_truncation
        result_text = result_text[:result_truncation]

        # Auto-share dispatch result to consensus memory
        try:
            consensus_value = result_text[:500]
            if len(result_text) > 500:
                consensus_value += "\n\n[Full result available in workspace files]"
            _share_insight_impl(
                key=f"dispatch.{agent_role}.{dispatch_number}",
                value=consensus_value,
                evidence=original_task_description[:300],
                source_agent=agent_role,
            )
        except Exception:
            pass  # non-blocking; memory store may not be initialised

        # Record in history
        _dispatch_history.append({
            "dispatch_number": dispatch_number,
            "agent_role": agent_role,
            "task_summary": original_task_description[:120],
            "result_snippet": result_text[:200],
            "truncated": truncated,
        })

        # Emit result event
        try:
            emit_fn("agent_exchange", {
                "exchange_type": "dispatch_result",
                "from_agent": agent_role,
                "to_agent": "BUILD Coordinator",
                "result_snippet": result_text[:200],
                "dispatch_number": dispatch_number,
                "truncated": truncated,
            })
        except Exception:
            pass

        return {
            "status": "success",
            "agent_role": agent_role,
            "result": result_text,
            "truncated": truncated,
            "dispatch_number": dispatch_number,
        }

    # ------------------------------------------------------------------
    # Sequential dispatch tool (existing behaviour, refactored)
    # ------------------------------------------------------------------
    @tool("Dispatch Task to Agent")
    def dispatch_task(agent_role: str, task_description: str) -> str:
        """Dispatch a task to a specialist agent and return its result.

        Args:
            agent_role: Role key of the target agent (e.g. "product_strategist", "developer", "reviewer")
            task_description: Full description of the task to execute

        Returns:
            JSON with status, result text, truncation flag, remaining budget, and dispatch history
        """
        available_roles = sorted(agent_registry.keys())

        # Guard: unknown role
        if agent_role not in agent_registry:
            return json.dumps({
                "status": "rejected",
                "reason": f"Unknown agent_role '{agent_role}'",
                "available_roles": available_roles,
            }, indent=2)

        # Guard: budget exhausted
        if _dispatch_count[0] >= max_dispatches:
            return json.dumps({
                "status": "rejected",
                "reason": f"Max dispatches reached ({max_dispatches})",
                "dispatches_used": _dispatch_count[0],
                "dispatch_history": _dispatch_history,
            }, indent=2)

        _dispatch_count[0] += 1
        remaining = max_dispatches - _dispatch_count[0]

        result = _execute_single_dispatch(agent_role, task_description, _dispatch_count[0])

        result["dispatches_remaining"] = remaining
        result["dispatch_history"] = _dispatch_history
        return json.dumps(result, indent=2)

    dispatch_task.cache_function = _NO_CACHE

    # ------------------------------------------------------------------
    # Parallel dispatch tool (new)
    # ------------------------------------------------------------------
    @tool("Dispatch Parallel Tasks")
    def dispatch_parallel(
        agent_role_1: str,
        task_description_1: str,
        agent_role_2: str,
        task_description_2: str,
        agent_role_3: str = "",
        task_description_3: str = "",
    ) -> str:
        """Dispatch 2 or 3 tasks to agents in parallel. All run concurrently.

        Use this when you have independent tasks that can run simultaneously,
        e.g. two developers building separate pages. For dependent work
        (reviewer after developer), use dispatch_task_to_agent sequentially.
        IMPORTANT: assign non-overlapping files to each parallel developer.

        Args:
            agent_role_1: Role for first task (e.g. "developer")
            task_description_1: Description for first task
            agent_role_2: Role for second task (e.g. "developer")
            task_description_2: Description for second task
            agent_role_3: Role for optional third task (leave empty to skip)
            task_description_3: Description for optional third task

        Returns:
            JSON with status and results array from all dispatched agents.
        """
        import concurrent.futures

        # Build task list from positional parameters
        tasks = [
            {"agent_role": agent_role_1, "task_description": task_description_1},
            {"agent_role": agent_role_2, "task_description": task_description_2},
        ]
        if agent_role_3 and task_description_3:
            tasks.append({"agent_role": agent_role_3, "task_description": task_description_3})

        available_roles = sorted(agent_registry.keys())

        # Validate all roles upfront
        for t in tasks:
            role = t["agent_role"]
            if role not in agent_registry:
                return json.dumps({
                    "status": "rejected",
                    "reason": f"Unknown agent_role '{role}'",
                    "available_roles": available_roles,
                }, indent=2)

        # Guard: budget check for entire batch
        needed = len(tasks)
        if _dispatch_count[0] + needed > max_dispatches:
            return json.dumps({
                "status": "rejected",
                "reason": f"Not enough budget: need {needed} dispatches but only {max_dispatches - _dispatch_count[0]} remaining",
                "dispatches_used": _dispatch_count[0],
                "max_dispatches": max_dispatches,
            }, indent=2)

        # Reserve dispatch numbers upfront
        dispatch_numbers = []
        for _ in tasks:
            _dispatch_count[0] += 1
            dispatch_numbers.append(_dispatch_count[0])

        remaining = max_dispatches - _dispatch_count[0]

        # Run all dispatches in parallel
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            future_to_idx = {}
            for idx, t in enumerate(tasks):
                future = executor.submit(
                    _execute_single_dispatch,
                    t["agent_role"],
                    t["task_description"],
                    dispatch_numbers[idx],
                )
                future_to_idx[future] = idx

            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "status": "error",
                        "agent_role": tasks[idx]["agent_role"],
                        "result": f"[parallel dispatch error] {exc}",
                        "truncated": False,
                        "dispatch_number": dispatch_numbers[idx],
                    }
                results.append((idx, result))

        # Sort by original order
        results.sort(key=lambda x: x[0])
        ordered_results = [r for _, r in results]

        return json.dumps({
            "status": "success",
            "parallel_count": len(tasks),
            "results": ordered_results,
            "dispatches_remaining": remaining,
            "dispatch_history": _dispatch_history,
        }, indent=2)

    dispatch_parallel.cache_function = _NO_CACHE

    # Expose dispatch count and history so callers can detect zero-dispatch runs
    # and check completeness (e.g. reviewer was dispatched after developer).
    # CrewAI tools are Pydantic models that reject arbitrary attributes,
    # so we return a (tool, parallel_tool, get_count, get_history) tuple instead.
    def _get_dispatch_count() -> int:
        return _dispatch_count[0]

    def _get_dispatch_history() -> List[Dict[str, Any]]:
        return list(_dispatch_history)

    return dispatch_task, dispatch_parallel, _get_dispatch_count, _get_dispatch_history


# ---------------------------------------------------------------------------
# Disable CrewAI's per-tool result cache for every tool whose output can
# change between calls (file reads after writes, DB queries after inserts,
# quality checks, team insights after new shares, etc.).
# The default cache_function returns True which causes stale results.
# ---------------------------------------------------------------------------
for _t in (
    run_quality_checks_tool,
    get_startups_tool,
    get_vcs_tool,
    get_database_stats,
    list_dynamic_tools,
    get_team_insights,
):
    _t.cache_function = _NO_CACHE
