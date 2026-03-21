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
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING

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


def _cleanup_globals() -> None:
    """Close global singletons at interpreter shutdown."""
    global _db, _memory_store
    if _db is not None:
        _db.close()
        _db = None
    if _memory_store is not None:
        _memory_store.close()
        _memory_store = None


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
# ENVIRONMENT TOOLS
# =============================================================================

@tool("List Installed Packages")
def list_installed_packages() -> str:
    """List all Python packages available in the environment.

    Use this to check what you can import before writing code.
    You CANNOT install new packages — only use what is already listed here.

    Returns:
        JSON list of installed package names
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if proc.returncode == 0:
            pkgs = [p["name"] for p in json.loads(proc.stdout)]
        else:
            pkgs = ["(could not list packages)"]
    except Exception as exc:
        pkgs = [f"(error: {exc})"]
    return json.dumps({"installed_packages": pkgs, "note": "You CANNOT install new packages. Only use what is listed here. Do NOT create requirements.txt or install_deps.py."})


# =============================================================================
# DATA RETRIEVAL TOOLS
# =============================================================================

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

# =============================================================================
# CONSENSUS MEMORY TOOLS
# =============================================================================


@tool("Share Insight")
def share_insight(key: str, value: str, evidence: str = "") -> str:
    """Store an insight so other agents can access it in future iterations.

    Args:
        key: Namespaced key (e.g. "product.plan", "data.top_gap")
        value: The insight or finding to share
        evidence: Supporting reasoning (optional)
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
        el.emit("agent_exchange", {
            "exchange_type": "share_insight",
            "from_agent": source_agent,
            "key": key,
            "value_summary": value,
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
        """Store an insight so other agents can access it in future iterations.

        Args:
            key: Namespaced key (e.g. "product.plan", "data.top_gap")
            value: The insight or finding to share
            evidence: Supporting reasoning (optional)
        """
        return _share_insight_impl(key, value, evidence, source_agent=role)

    return _share_insight_for_role


@tool("Get Team Insights")
def get_team_insights(topic: str = "") -> str:
    """Read insights shared by other agents from prior iterations.

    Args:
        topic: Key prefix to filter (e.g. "product", "data"). Empty string returns all.
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
        # Include actual insight keys so the dashboard shows meaningful content
        insight_keys = [i["key"] for i in insights]
        el.emit("agent_exchange", {
            "exchange_type": "get_insights",
            "from_agent": "crewai_agent",
            "topic": topic or "all",
            "count": len(insights),
            "value_summary": f"Retrieved {len(insights)} insights: {', '.join(insight_keys)}" if insights else "No insights found",
            "cycle_id": _current_cycle_id,
        })

    return json.dumps({
        "status": "success",
        "count": len(insights),
        "topic": topic or "all",
        "insights": insights,
    }, indent=2)


@tool("Get Cycle History")
def get_cycle_history(limit: int = 10) -> str:
    """Get results from previous Build-Measure-Learn iterations, including what agents did and customer feedback.

    Args:
        limit: Max number of past cycles to return (default 10)
    """
    store = get_memory_store()
    if store is None:
        return json.dumps({
            "status": "skipped",
            "reason": "Memory store not initialised",
            "cycles": [],
        })

    from src.framework.types import EpisodeType as _EpType

    try:
        episodes = store.ep_search_structured(
            episode_type=_EpType.LEARNING,
            limit=max(1, min(limit, 50)),
        )
    except Exception as exc:
        return json.dumps({"status": "error", "reason": str(exc), "cycles": []})

    cycles = []
    for ep in episodes:
        m = ep.outcome or {}
        cycles.append({
            "iteration": ep.iteration,
            "qa_passed": m.get("qa_passed", False),
            "task_count": m.get("task_count", 0),
            "success_count": m.get("success_count", 0),
            "failure_count": m.get("failure_count", 0),
            "summary": ep.summary_text or "",
        })

    el = get_event_logger()
    if el is not None:
        el.emit("agent_exchange", {
            "exchange_type": "get_cycle_history",
            "from_agent": "crewai_agent",
            "count": len(cycles),
            "value_summary": f"Retrieved {len(cycles)} cycle(s)" if cycles else "No cycle history",
            "cycle_id": _current_cycle_id,
        })

    return json.dumps({
        "status": "success",
        "count": len(cycles),
        "cycles": cycles,
    }, indent=2)


get_cycle_history.cache_function = _NO_CACHE


@tool("Mark Feedback Addressed")
def mark_feedback_addressed_tool(feedback_ids: str) -> str:
    """Mark customer feedback items as resolved after fixing them.

    Args:
        feedback_ids: Comma-separated IDs from the feedback list (e.g. "ab12,cd34,ef56")
    """
    from src.workspace_tools.file_tools import _mark_feedback_addressed

    ids = [fid.strip() for fid in feedback_ids.split(",") if fid.strip()]
    if not ids:
        return json.dumps({"status": "error", "reason": "No feedback IDs provided"})

    cycle_id = _current_cycle_id or 0
    count = _mark_feedback_addressed(ids, addressed_in_cycle=cycle_id)

    el = get_event_logger()
    if el is not None:
        el.emit("agent_exchange", {
            "exchange_type": "feedback_addressed",
            "from_agent": "coordinator",
            "feedback_ids": ids,
            "count": count,
            "cycle_id": cycle_id,
        })

    return json.dumps({
        "status": "success",
        "marked_count": count,
        "feedback_ids": ids,
        "message": f"Marked {count} feedback item(s) as addressed",
    }, indent=2)


mark_feedback_addressed_tool.cache_function = _NO_CACHE


# =============================================================================
# DISPATCH TASK TOOL — coordinator-driven dynamic agent orchestration
# =============================================================================


def make_dispatch_task_tool(
    agent_registry: Dict[str, Dict[str, Any]],
    emit_fn,
    *,
    max_dispatches: int = 8,
    result_truncation: int = 3000,
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
            "You own the workspace. Your job is to WRITE code, not just read it.\n"
            "Tech stack: Flask (app.py), Jinja2 templates (templates/), static files (static/), SQLite (.db).\n"
            "You can also pull in any CDN-hosted libraries (CSS frameworks, JS libraries, icon sets, etc.) via script/link tags — no installation required.\n"
            "Call ONE tool at a time. After reading context, start writing files immediately.\n"
            "Do NOT loop on reading — if the workspace is empty, start building from scratch.\n"
            "Use run_workspace_sql to create/seed SQLite tables. app.py must read host/port from env vars.\n"
        ),
        "reviewer": (
            "You have tools to review workspace files (Python, HTML, CSS, JS), run HTTP checks, and share findings.\n"
            "The app is Flask-based: check app.py for routes, templates/ for HTML, static/ for assets.\n"
        ),
        "product_strategist": (
            "You have tools to inspect workspace files, read team insights, and share your plan.\n"
            "The product is a Flask web app: plan routes, database tables, templates, and features.\n"
            "The team can use any CDN-hosted libraries — feel free to recommend them in your plans.\n"
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

        # Prepend role-specific instructions + context from prior iterations.
        # The extra_context has already been summarized by the strategist LLM
        # at the coordinator level, so we pass it through as-is.
        original_task_description = task_description
        role_instructions = _ROLE_INSTRUCTIONS.get(agent_role, "")
        if role_instructions:
            task_description = role_instructions + "\n" + task_description
        if extra_context:
            task_description += f"\n\n[Context from prior iterations]\n{extra_context}"

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
            expected_output="Summary of actions taken and their outcomes.",
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
                    expected_output="Summary of actions taken and their outcomes.",
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

        # Detect empty/trivial results
        stripped = result_text.strip()
        is_empty = len(stripped) < 20 or stripped.lower() in ("", "none", "n/a", "final answer")

        # Truncate
        truncated = len(result_text) > result_truncation
        result_text = result_text[:result_truncation]

        # Record in history
        _dispatch_history.append({
            "dispatch_number": dispatch_number,
            "agent_role": agent_role,
            "task_summary": original_task_description[:120],
            "result_snippet": result_text[:200],
            "truncated": truncated,
            "empty_result": is_empty,
        })

        # Emit result event
        try:
            emit_fn("agent_exchange", {
                "exchange_type": "dispatch_result",
                "from_agent": agent_role,
                "to_agent": "BUILD Coordinator",
                "value_summary": result_text,
                "dispatch_number": dispatch_number,
                "truncated": truncated,
            })
        except Exception:
            pass

        result_dict = {
            "status": "success",
            "agent_role": agent_role,
            "result": result_text,
            "truncated": truncated,
            "dispatch_number": dispatch_number,
        }

        if is_empty:
            result_dict["warning"] = (
                f"Agent '{agent_role}' returned an empty or trivial result. "
                f"Do NOT retry the same task — the agent could not produce output. "
                f"Try a different approach or skip this agent."
            )

        return result_dict

    # ------------------------------------------------------------------
    # Sequential dispatch tool (existing behaviour, refactored)
    # ------------------------------------------------------------------
    @tool("Dispatch Task to Agent")
    def dispatch_task(agent_role: str, task_description: str) -> str:
        """Dispatch a task to a specialist agent and wait for its result.

        Args:
            agent_role: One of "product_strategist", "developer", "reviewer"
            task_description: Detailed description of what the agent should do
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
        role_1: str,
        task_1: str,
        role_2: str,
        task_2: str,
        role_3: str = "",
        task_3: str = "",
    ) -> str:
        """Dispatch 2-3 independent tasks to agents in parallel. Use dispatch_task_to_agent instead for sequential/dependent work.

        Args:
            role_1/task_1: First agent role and task
            role_2/task_2: Second agent role and task
            role_3/task_3: Optional third agent role and task
        """
        import concurrent.futures

        # Build task list from positional parameters
        tasks = [
            {"agent_role": role_1, "task_description": task_1},
            {"agent_role": role_2, "task_description": task_2},
        ]
        if role_3 and task_3:
            tasks.append({"agent_role": role_3, "task_description": task_3})

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
# Standalone fallback dispatch — used by idle-cycle guardrail when the
# coordinator fails to dispatch any agent on its own.
# ---------------------------------------------------------------------------

def _execute_dispatch_fallback(
    agent_registry: Dict[str, Dict[str, Any]],
    emit_fn,
    agent_role: str,
    task_description: str,
    extra_context: str = "",
) -> str:
    """Run a single agent dispatch outside of the coordinator loop.

    This is intentionally simple: one agent, one task, no budget tracking.
    Used as a safety net when the coordinator completes without dispatching.
    """
    from crewai import Crew as _Crew, Task as _Task, Process as _Process

    entry = agent_registry.get(agent_role)
    if not entry:
        logger.warning("Fallback dispatch: unknown role '%s'", agent_role)
        return ""

    factory = entry["factory"]
    agent = factory(
        llm=entry.get("llm"),
        prompt_override=entry.get("prompt_override"),
        extra_tools=entry.get("extra_tools"),
    )

    _ROLE_INSTRUCTIONS = {
        "developer": (
            "You own the workspace. Your job is to WRITE code, not just read it.\n"
            "Tech stack: Flask (app.py), Jinja2 templates (templates/), static files (static/), SQLite (.db).\n"
            "Call ONE tool at a time. After reading context, start writing files immediately.\n"
        ),
    }
    role_instructions = _ROLE_INSTRUCTIONS.get(agent_role, "")
    full_desc = (role_instructions + "\n" + task_description) if role_instructions else task_description

    single_task = _Task(
        description=full_desc,
        agent=agent,
        expected_output="Summary of actions taken and their outcomes.",
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
        emit_fn("agent_exchange", {
            "exchange_type": "idle_cycle_fallback_dispatch",
            "from_agent": "system",
            "to_agent": agent_role,
            "task_summary": task_description[:200],
        })
    except Exception:
        pass

    crew_output = mini_crew.kickoff()
    return str(crew_output)


# ---------------------------------------------------------------------------
# Disable CrewAI's per-tool result cache for every tool whose output can
# change between calls (file reads after writes, DB queries after inserts,
# quality checks, team insights after new shares, etc.).
# The default cache_function returns True which causes stale results.
# ---------------------------------------------------------------------------
for _t in (
    run_quality_checks_tool,
    get_database_stats,
    get_team_insights,
):
    _t.cache_function = _NO_CACHE
