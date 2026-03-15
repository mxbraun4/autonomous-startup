"""CrewAI Crews - Orchestration of agents and tasks.

Provides both the public ``run_build_measure_learn_cycle`` function and the
``BuildMeasureLearnFlow`` (CrewAI Flows) for typed, event-driven
Build -> Evaluate -> Learn execution with evaluation gates and learning feedback.
"""

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.crewai_agents.runtime_env import (
    configure_runtime_environment,
    patch_crewai_storage_paths,
)

configure_runtime_environment()
from crewai import Crew, Task, Process, LLM
from crewai.flow.flow import Flow, start, listen, router

patch_crewai_storage_paths()

from src.crewai_agents.agents import (
    create_master_coordinator,
    create_build_coordinator,
    create_developer_agent,
    create_reviewer_agent,
    create_product_strategist,
    ensure_litellm_tracing,
    set_current_cycle_id as _set_agent_cycle_id,
    get_llm,
)
from src.crewai_agents.tools import (
    set_current_cycle_id as _set_tools_cycle_id,
    make_dispatch_task_tool,
    mark_feedback_addressed_tool,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Structured output models (CrewAI v1.9 output_pydantic)
# ---------------------------------------------------------------------------


class BuildPhaseOutput(BaseModel):
    """Structured output returned by each BUILD-phase crew kickoff."""

    data_gaps_identified: int = 0
    data_collected_count: int = 0
    data_quality_score: float = 0.0
    product_feature_name: str = ""
    product_impact_summary: str = ""
    summary: str = ""


class LearnPhaseOutput(BaseModel):
    """Structured output from the LEARN phase."""

    successes: List[str] = Field(default_factory=list)
    failures: List[str] = Field(default_factory=list)
    insights: List[str] = Field(default_factory=list)
    recommendations: Dict[str, str] = Field(default_factory=dict)
    predicted_improvement: float = 0.0
    summary: str = ""


# ---------------------------------------------------------------------------


def create_learn_phase_task(coordinator, build_results: str) -> Task:
    """Create task for the LEARN phase.

    Args:
        coordinator: Master coordinator agent
        build_results: Results from BUILD phase (includes QA gate output)

    Returns:
        LEARN phase task
    """
    return Task(
        description=f'''Analyze results from this Build-Evaluate-Learn iteration and extract learnings.

        BUILD Phase Results (including QA gate):
        {build_results}

        Identify what worked, what failed, and why. Extract actionable insights
        and formulate recommendations for each team. If USER_FEEDBACK is present,
        factor usability issues and feature requests into your recommendations.
        ''',
        agent=coordinator,
        expected_output="Insights and recommendations for the next iteration.",
    )


def _verbose_flag(verbose: int) -> bool:
    """Convert integer verbosity to CrewAI v1.9 boolean flag."""
    return verbose > 0


def _parse_learn_text(raw: str) -> tuple:
    """Extract insights and recommendations from unstructured learn output.

    Returns (insights: List[str], recommendations: Dict[str, str]).
    """
    import re

    insights: List[str] = []
    recommendations: Dict[str, str] = {}

    # Extract bullet-point lines (- or * prefixed) as insights
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "â€¢ ")):
            text = stripped.lstrip("-*â€¢ ").strip()
            if text:
                insights.append(text)

    # Look for role-specific recommendation patterns like "developer: ..." or
    # "Recommendation for product: ..."
    role_pattern = re.compile(
        r"(?:recommendation\s+for\s+)?(\w+)\s*:\s*(.+)",
        re.IGNORECASE,
    )
    known_roles = {"coordinator", "developer", "product", "reviewer", "data"}
    for line in raw.splitlines():
        m = role_pattern.match(line.strip().lstrip("-*â€¢ "))
        if m:
            role = m.group(1).lower()
            if role in known_roles:
                recommendations[role] = m.group(2).strip()

    # Cap insights to avoid bloat
    insights = insights[:10]

    return insights, recommendations


def create_autonomous_startup_crew(
    llm: LLM = None,
    verbose: int = 2,
) -> Crew:
    """Create the autonomous startup crew.

    Args:
        llm: LLM instance to use
        verbose: Verbosity level (0-2)

    Returns:
        Configured Crew instance
    """
    logger.info("Creating autonomous startup crew...")

    # Create agents
    if llm is None:
        coordinator_llm = get_llm("coordinator")
        developer_llm = get_llm("developer")
        reviewer_llm = get_llm("reviewer")
        product_llm = get_llm("product")
    else:
        coordinator_llm = llm
        developer_llm = llm
        reviewer_llm = llm
        product_llm = llm

    coordinator = create_master_coordinator(coordinator_llm)
    developer_agent = create_developer_agent(developer_llm)
    reviewer_agent = create_reviewer_agent(reviewer_llm)
    product_strategist = create_product_strategist(product_llm)

    build_task = Task(
        description="Build and improve the startup-VC matching website.",
        agent=coordinator,
        expected_output="Summary of what was built or improved.",
    )

    # NOTE: memory=False because we use our own five-tier UnifiedStore rather
    # than CrewAI's built-in memory (which requires an OpenAI API key for
    # embeddings). Our memory is injected into tools via set_memory_store().
    crew = Crew(
        agents=[coordinator, product_strategist, developer_agent, reviewer_agent],
        tasks=[build_task],
        process=Process.hierarchical,
        manager_llm=coordinator_llm,
        verbose=_verbose_flag(verbose),
        memory=False,
        cache=False,
        max_rpm=10,
    )

    logger.info("Crew created successfully")
    return crew


def run_build_measure_learn_cycle(
    iterations: int = 10,
    verbose: int = 2,
) -> Dict[str, Any]:
    """Run multiple Build-Measure-Learn iterations.

    Delegates to :class:`BuildMeasureLearnFlow` which provides typed state
    passing between phases, evaluation-gate routing, and learning feedback.

    Args:
        iterations: Number of iterations to run
        verbose: Verbosity level (0-2)

    Returns:
        Results from all iterations
    """
    flow = BuildMeasureLearnFlow(
        max_iterations=iterations,
        verbose=verbose,
    )
    return flow.run()


def _create_coordinator_build_task(
    coordinator_agent,
    iteration: int,
    available_roles: List[str],
    extra_context: str = "",
) -> Task:
    """Create a single Task for the BUILD coordinator.

    The description tells the coordinator about the product scope, lists
    available agent roles, explains dispatch_task usage, and appends any
    learning context from previous iterations.
    """
    description = f'''[Iteration {iteration}] Build and continuously improve a startup-VC matching platform using Flask + SQLite + Jinja templates.

    The tech stack is: Python Flask backend (app.py), Jinja2 HTML templates (templates/), static assets (static/css, static/js), and SQLite databases (.db files).

    Available agents to dispatch: {", ".join(available_roles)}.
    1. Gather context: check workspace files and team insights (2-3 tool calls max).
    2. Dispatch agents with specific tasks. Developer tasks must tell it what to BUILD or FIX — the developer reads files on its own, you don't need to ask it to read for you.
    3. Review dispatch results and dispatch follow-up tasks if needed.
    '''

    if extra_context:
        description += f"\n{extra_context}"

    return Task(
        description=description,
        agent=coordinator_agent,
        expected_output="Summary of actions taken and their outcomes.",
    )


# ---------------------------------------------------------------------------
# CrewAI Flow: Build-Measure-Learn with evaluation gates & learning feedback
# ---------------------------------------------------------------------------

class _FlowState(BaseModel):
    """Mutable state threaded through the BML Flow."""

    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:16])

    iteration: int = 0
    max_iterations: int = 10
    verbose: int = 2
    llm: Any = None
    enable_dynamic_agent_factory: bool = True
    max_agents_per_cycle: int = 6
    workspace_enabled: bool = True

    # Per-iteration outputs
    build_result_text: str = ""
    build_output: Optional[BuildPhaseOutput] = None
    build_task_count: int = 0
    build_success_count: int = 0
    build_failure_count: int = 0
    qa_passed: bool = True
    qa_result: Dict[str, Any] = Field(default_factory=dict)
    user_feedback: Dict[str, Any] = Field(default_factory=dict)
    learn_output: Optional[LearnPhaseOutput] = None
    # Gate recommendation from the EVALUATE phase
    gate_recommendation: str = "continue"  # continue / pause / rollback / stop

    # Accumulated results across all iterations
    iterations_results: List[Dict[str, Any]] = Field(default_factory=list)
    metrics_evolution: List[Dict[str, Any]] = Field(default_factory=list)
    learnings: List[str] = Field(default_factory=list)
    prompt_overrides: Dict[str, str] = Field(default_factory=dict)

    # Learning feedback: procedure hints injected into next BUILD
    procedure_hints: str = ""

    # User feedback collected from workspace/feedback.db (before remediation)
    user_feedback_summary: str = ""

    # Active policies from PolicyUpdater, persisted across iterations
    active_policies: Dict[str, Any] = Field(default_factory=dict)

    # Previous cycle metrics for evaluator trend analysis
    previous_cycle_metrics: Optional[Dict[str, Any]] = None

    model_config = {"arbitrary_types_allowed": True}


class BuildMeasureLearnFlow(Flow[_FlowState]):
    """Event-driven Build-Evaluate-Learn cycle using CrewAI Flows.

    Each call to :meth:`kickoff` runs one complete BUILD -> EVALUATE -> LEARN
    pipeline.  :meth:`run` loops over multiple iterations, feeding learnings
    from one iteration into the next.
    """

    def __init__(
        self,
        max_iterations: int = 10,
        verbose: int = 2,
        enable_dynamic_agent_factory: bool = True,
        max_agents_per_cycle: int = 6,
    ) -> None:
        super().__init__(
            max_iterations=max_iterations,
            verbose=verbose,
            llm=None,
            enable_dynamic_agent_factory=enable_dynamic_agent_factory,
            max_agents_per_cycle=max_agents_per_cycle,
        )

    # -- helpers ----------------------------------------------------------

    def _emit(self, event_type: str, payload: dict) -> None:
        """Emit an observability event if the event logger is available."""
        try:
            from src.crewai_agents.tools import get_event_logger

            el = get_event_logger()
            if el is not None:
                payload.setdefault("run_id", self.state.id)
                payload.setdefault("cycle_id", self.state.iteration)
                el.emit(event_type, payload)
        except Exception:
            pass

    def _get_evaluator(self):
        """Lazy import of the framework Evaluator."""
        from src.framework.eval import Evaluator
        return Evaluator()

    def _get_procedure_updater(self):
        """Lazy import of ProcedureUpdater with the active memory store."""
        from src.framework.learning import ProcedureUpdater
        from src.crewai_agents.tools import get_memory_store

        store = get_memory_store()
        if store is None:
            return None
        return ProcedureUpdater(store)

    def _get_policy_updater(self):
        """Lazy import of PolicyUpdater, reused across iterations."""
        if getattr(self, "_policy_updater", None) is None:
            from src.framework.learning import PolicyUpdater
            self._policy_updater = PolicyUpdater()
        return self._policy_updater

    def _prompt_override(self, key: str) -> str:
        overrides = dict(self.state.prompt_overrides or {})
        return str(overrides.get(key, "")).strip()

    def _run_quality_gate(self) -> Dict[str, Any]:
        """Run informational QA checks and return parsed JSON output.

        Collects signals (syntax, workspace content, HTTP) but does NOT
        make a blocking pass/fail decision — that is left to the evaluate
        phase so agents retain control over iteration flow.
        """
        from src.crewai_agents.tools import run_quality_checks_tool

        result: Dict[str, Any] = {}

        # 1. Python syntax check
        try:
            raw = run_quality_checks_tool.run(
                paths_csv="src,scripts,workspace",
                pytest_targets_csv="",
                run_pytest=False,
                timeout_seconds=60,
            )
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                result = parsed
            else:
                result = {"status": "unknown", "raw": raw}
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}

        # 2. Workspace content inventory
        workspace_info: Dict[str, Any] = {}
        try:
            from src.workspace_tools.file_tools import _read_impl, _list_impl

            listing = _list_impl()
            files = listing.get("files", [])
            py_files = [f for f in files if f.endswith(".py")]
            html_files = [f for f in files if f.endswith(".html")]
            workspace_info["file_count"] = len(files)
            workspace_info["py_files"] = py_files
            workspace_info["html_files"] = html_files
            workspace_info["has_flask_app"] = "app.py" in py_files

            # Check for non-placeholder source files (app.py or templates)
            non_placeholder_count = 0

            # Check app.py
            app_result = _read_impl("app.py")
            if app_result.get("status") == "ok":
                content = (app_result.get("content") or "").lower()
                is_placeholder = "waiting for agents to build" in content
                if not is_placeholder and len(content.strip()) > 100:
                    non_placeholder_count += 1

            # Check HTML templates
            for html_file in html_files:
                content_result = _read_impl(html_file)
                if content_result.get("status") == "ok":
                    content = (content_result.get("content") or "").lower()
                    is_placeholder = "waiting for agents to build" in content
                    if not is_placeholder and len(content.strip()) > 100:
                        non_placeholder_count += 1

            workspace_info["non_placeholder_count"] = non_placeholder_count
        except Exception as ws_exc:
            workspace_info["error"] = str(ws_exc)

        result["workspace"] = workspace_info

        # 3. HTTP checks
        http_info: Dict[str, Any] = {}
        try:
            from src.workspace_tools.file_tools import _check_http_impl

            http_result = _check_http_impl()
            if http_result.get("status") == "ok":
                http_info = http_result
            else:
                http_info = http_result
        except Exception as http_exc:
            http_info["error"] = str(http_exc)

        result["http_checks"] = http_info

        # 4. Architecture quality checks (DRY, broken links, shared assets)
        arch_info: Dict[str, Any] = {}
        try:
            from src.workspace_tools.file_tools import _read_impl, _list_impl
            import re as _re

            listing_arch = _list_impl()
            all_files_arch = listing_arch.get("files", [])
            html_files_arch = [f for f in all_files_arch if f.endswith(".html")]
            has_shared_css = any(f.endswith(".css") for f in all_files_arch)
            arch_info["has_shared_css"] = has_shared_css

            # Detect inline CSS duplication
            style_block_sizes = {}
            placeholder_links = []
            for html_file in html_files_arch:
                content_result = _read_impl(html_file)
                if content_result.get("status") != "ok":
                    continue
                content = content_result.get("content", "")
                # Measure inline <style> block size
                style_matches = _re.findall(r"<style[^>]*>(.*?)</style>", content, _re.DOTALL)
                total_style_chars = sum(len(s) for s in style_matches)
                if total_style_chars > 500:
                    style_block_sizes[html_file] = total_style_chars
                # Detect placeholder href="#" links (excluding anchor-only links)
                href_hash = _re.findall(r'href=["\']#["\']', content)
                if href_hash:
                    placeholder_links.append({"file": html_file, "count": len(href_hash)})

            # Flag DRY violation if 2+ files have large inline style blocks
            # and no shared CSS file exists
            duplicated_css = len(style_block_sizes) >= 2 and not has_shared_css
            arch_info["inline_css_files"] = style_block_sizes
            arch_info["duplicated_css"] = duplicated_css
            arch_info["placeholder_links"] = placeholder_links
            arch_info["placeholder_link_count"] = sum(p["count"] for p in placeholder_links)
        except Exception as arch_exc:
            arch_info["error"] = str(arch_exc)

        result["architecture"] = arch_info

        # Informational flag — the evaluate phase decides what to do with it
        syntax_ok = bool((result.get("syntax") or {}).get("syntax_ok", True))
        has_content = workspace_info.get("non_placeholder_count", 0) > 0
        landing_score = float(http_info.get("http_landing_score", 0.0))
        result["qa_gate_passed"] = syntax_ok and has_content and landing_score >= 1.0

        return result

    def _run_customer_testing(self) -> None:
        """Run LLM-powered customer testing against the workspace.

        Starts a temporary HTTP server (Flask subprocess if ``app.py``
        exists, otherwise static file server), runs customer personas
        against discovered pages, and writes feedback to feedback.db.
        Failures are logged but never block the pipeline.
        """
        try:
            from src.workspace_tools.file_tools import _workspace_root
            from src.workspace_tools.server import FlaskAppServer, WorkspaceServer
            from src.simulation.customer_testing import run_customer_testing
            from src.utils.config import settings

            if _workspace_root is None:
                return

            flask_server = FlaskAppServer(str(_workspace_root), port=0)
            server = flask_server if flask_server.has_flask_app() else WorkspaceServer(str(_workspace_root), port=0)
            try:
                base_url = server.start()
                result = run_customer_testing(
                    base_url=base_url,
                    workspace_root=str(_workspace_root),
                    emit_fn=self._emit,
                    cycle_id=self.state.iteration,
                    mock=settings.mock_mode,
                )
                logger.info(
                    "Customer testing: %d feedback entries from %d personas",
                    result.get("feedback_count", 0),
                    result.get("personas_tested", 0),
                )
            finally:
                server.stop()
        except Exception as exc:
            logger.warning("Customer testing skipped: %s", exc)

    def _take_workspace_snapshot(self) -> str:
        """Read all workspace files once and return a combined snapshot string.

        This avoids redundant read_workspace_file calls by agents during
        the BUILD phase.  The snapshot is injected into the coordinator
        task description so agents already have full context.
        """
        try:
            from src.workspace_tools.file_tools import _list_impl, _read_impl

            listing = _list_impl()
            files = listing.get("files", [])
            if not files:
                return "[Workspace is empty — no files yet]"

            # Skip binary/compiled files that waste tokens
            _SKIP_EXTS = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3",
                          ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}
            readable_files = [
                f for f in files
                if not any(f.lower().endswith(ext) for ext in _SKIP_EXTS)
                and "__pycache__" not in f
            ]

            sections: List[str] = []
            total_chars = 0
            _MAX_SNAPSHOT_CHARS = 20_000  # cap total snapshot size

            for fpath in sorted(readable_files):
                if total_chars >= _MAX_SNAPSHOT_CHARS:
                    sections.append(f"\n--- {fpath} ---\n[truncated: snapshot size limit reached]")
                    break
                result = _read_impl(fpath)
                if result.get("status") != "ok":
                    continue
                content = result.get("content", "")
                remaining = _MAX_SNAPSHOT_CHARS - total_chars
                if len(content) > remaining:
                    content = content[:remaining] + "\n[... truncated]"
                sections.append(f"--- {fpath} ---\n{content}")
                total_chars += len(content)

            return "\n\n".join(sections)
        except Exception as exc:
            logger.warning("Workspace snapshot failed: %s", exc)
            return "[Workspace snapshot unavailable]"

    def _get_unresolved_feedback(self) -> str:
        """Collect open feedback from prior cycles as a formatted summary.

        Returns a string listing unresolved feedback items with their IDs
        so the BUILD coordinator can address them and mark them resolved
        via the mark_feedback_addressed tool.
        """
        try:
            from src.workspace_tools.file_tools import _get_open_feedback

            open_items = _get_open_feedback(exclude_cycle=self.state.iteration)
            if not open_items:
                return ""

            lines = [
                f"UNRESOLVED FEEDBACK FROM PRIOR CYCLES ({len(open_items)} items):",
                "After fixing these issues, call mark_feedback_addressed with the IDs.",
            ]
            for item in open_items[:10]:  # cap to avoid prompt bloat
                fid = item.get("id", "?")
                cycle = item.get("cycle_id", "?")
                ftype = item.get("feedback_type", "?")
                msg = item.get("message", "")
                lines.append(f"  [{fid}] [cycle {cycle}][{ftype}] {msg}")

            if len(open_items) > 10:
                lines.append(f"  ... and {len(open_items) - 10} more")

            return "\n".join(lines)
        except Exception:
            return ""

    def _collect_user_feedback(self) -> str:
        """Collect user feedback from workspace/feedback.db (SQLite).

        Queries feedback for the current cycle, stores entries in
        ``self.state.user_feedback``, and returns a formatted summary
        that includes both current-cycle feedback and a count of open
        items from prior cycles.
        """
        import sqlite3 as _sqlite3
        from src.workspace_tools.file_tools import _workspace_root

        try:
            if _workspace_root is None:
                self.state.user_feedback = {}
                return "  No user feedback received this iteration."

            db_path = _workspace_root / "feedback.db"
            if not db_path.exists():
                self.state.user_feedback = {}
                return "  No user feedback received this iteration."

            current_cycle = self.state.iteration

            with _sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = _sqlite3.Row

                # Current cycle's feedback
                try:
                    rows = conn.execute(
                        "SELECT id, timestamp, page, feedback_type, message, cycle_id "
                        "FROM feedback WHERE cycle_id = ?",
                        (current_cycle,),
                    ).fetchall()
                except _sqlite3.OperationalError:
                    # Fallback for old schema without cycle_id column
                    rows = conn.execute(
                        "SELECT id, timestamp, page, feedback_type, message FROM feedback"
                    ).fetchall()

                # Count of open items from prior cycles
                try:
                    prior_open = conn.execute(
                        "SELECT COUNT(*) as cnt FROM feedback "
                        "WHERE status = 'open' AND cycle_id < ?",
                        (current_cycle,),
                    ).fetchone()
                    prior_open_count = prior_open["cnt"] if prior_open else 0
                except _sqlite3.OperationalError:
                    prior_open_count = 0

            if not rows:
                self.state.user_feedback = {}
                return "  No user feedback received this iteration."

            entries = [dict(r) for r in rows]
            self.state.user_feedback = {"entries": entries, "count": len(entries)}

            # Group by feedback_type
            grouped: Dict[str, List[str]] = {}
            for entry in entries:
                ftype = entry.get("feedback_type", "general")
                msg = entry.get("message", "")
                page = entry.get("page", "unknown")
                grouped.setdefault(ftype, []).append(f"[{page}] {msg}")

            # Cap to top 6 entries to keep coordinator context focused
            _MAX_FEEDBACK_ENTRIES = 6
            lines = [f"  Cycle {current_cycle} feedback: {len(entries)} entries"]
            if prior_open_count > 0:
                lines.append(f"  Open items from prior cycles: {prior_open_count}")
            shown = 0
            for ftype, messages in grouped.items():
                if shown >= _MAX_FEEDBACK_ENTRIES:
                    break
                remaining = _MAX_FEEDBACK_ENTRIES - shown
                display = messages[:remaining]
                lines.append(f"  {ftype} ({len(messages)}):")
                for msg in display:
                    lines.append(f"    - {msg}")
                shown += len(display)

            summary = "\n".join(lines)
            logger.info("USER FEEDBACK: Collected %d entries for cycle %d (%d prior open).",
                        len(entries), current_cycle, prior_open_count)
            return summary
        except Exception as exc:
            logger.warning("USER FEEDBACK: Failed to collect: %s", exc)
            self.state.user_feedback = {}
            return f"  Failed to collect user feedback: {exc}"

    def _qa_passed(self) -> bool:
        return bool((self.state.qa_result or {}).get("qa_gate_passed"))

    def _format_qa_failures(self, qa_result: dict) -> str:
        """Decompose QA result into a numbered, human-readable failure report."""
        if not qa_result:
            return "No QA results available."

        sections: List[str] = []
        failure_num = 0

        # 1. Syntax failures (highest priority)
        syntax = qa_result.get("syntax") or {}
        if not syntax.get("syntax_ok", True):
            failure_num += 1
            lines = [f"{failure_num}. SYNTAX ERRORS"]
            for entry in syntax.get("syntax_failures", []):
                f_path = entry.get("file", "unknown")
                error = entry.get("error", "unknown error")
                lines.append(f"   - {f_path}: {error}")
            lines.append("   Fix: correct the Python syntax errors above and re-check.")
            sections.append("\n".join(lines))

        # 2. Workspace validation failures
        if not qa_result.get("workspace_ok", True):
            failure_num += 1
            ws = qa_result.get("workspace") or {}
            py_count = len(ws.get("py_files", []))
            html_count = len(ws.get("html_files", []))
            non_placeholder = ws.get("non_placeholder_count", 0)
            lines = [f"{failure_num}. WORKSPACE CONTENT MISSING"]
            lines.append(f"   Python files found: {py_count}")
            lines.append(f"   HTML template files found: {html_count}")
            lines.append(f"   Non-placeholder source files: {non_placeholder}")
            lines.append("   Fix: create or update app.py with Flask routes and templates/ with real content.")
            sections.append("\n".join(lines))

        # 3. HTTP check failures
        if not qa_result.get("http_ok", True):
            failure_num += 1
            http = qa_result.get("http_checks") or {}
            lines = [f"{failure_num}. HTTP CHECK FAILURES"]
            for key in ("http_landing_score", "http_navigation_score"):
                if key in http:
                    lines.append(f"   - {key}: {http[key]}")
            lines.append("   Fix: ensure the landing page loads correctly over HTTP (score >= 1.0).")
            sections.append("\n".join(lines))

        if not sections:
            return "QA gate passed - no failures detected."

        return f"QA FAILURE REPORT ({failure_num} issue(s)):\n\n" + "\n\n".join(sections)

    # -- BUILD phase ------------------------------------------------------

    def _build_extra_context(self) -> str:
        """Collect learning context from prior iterations and memory stores.

        Gathers procedure hints, procedural memory, episodic memory, and
        consensus memory into a single string appended to BUILD task
        descriptions.  Pure extraction from what was previously inline in
        ``build()``.
        """
        extra_context = ""

        # Inject learning hints from previous iteration
        if self.state.procedure_hints:
            extra_context = (
                f"\n\n[Previous iteration learnings]\n{self.state.procedure_hints}\n"
            )

        # Inject procedural memory (best workflow from prior runs)
        try:
            from src.crewai_agents.tools import get_memory_store as _get_store_proc
            _proc_store = _get_store_proc()
            if _proc_store is not None:
                _proc = _proc_store.proc_get("bml_cycle")
                if _proc is not None and _proc.versions:
                    _latest = _proc.versions[-1]
                    wf = _latest.workflow or {}
                    parts = []
                    if wf.get("insights"):
                        parts.append("Past insights: " + "; ".join(str(x) for x in wf["insights"]))
                    if wf.get("recommendations"):
                        for _team, _rec in wf["recommendations"].items():
                            parts.append(f"  {_team}: {_rec}")
                    if wf.get("successes"):
                        parts.append("What worked: " + "; ".join(str(x) for x in wf["successes"]))
                    if wf.get("failures"):
                        parts.append("What failed: " + "; ".join(str(x) for x in wf["failures"]))
                    if parts:
                        extra_context += (
                            f"\n\n[Procedural Memory — best workflow v{_latest.version}, "
                            f"score {_latest.score:.0%}]\n"
                            + "\n".join(parts)
                            + "\n"
                        )
        except Exception as _proc_exc:
            logger.debug(f"Procedural memory read skipped: {_proc_exc}")

        # Inject episodic memory (metrics history from prior cycles/runs)
        try:
            from src.crewai_agents.tools import get_memory_store as _get_store_ep
            from src.framework.types import EpisodeType as _EpType
            _ep_store = _get_store_ep()
            if _ep_store is not None:
                _episodes = _ep_store.ep_search_structured(
                    episode_type=_EpType.LEARNING,
                    limit=10,
                )
                if _episodes:
                    ep_lines = []
                    for _ep in _episodes:
                        m = _ep.outcome or {}
                        it = _ep.iteration or "?"
                        qa = "PASS" if m.get("qa_passed") else "FAIL"
                        ep_lines.append(
                            f"- Cycle {it}: QA={qa}, "
                            f"tasks={m.get('task_count', '?')}, "
                            f"successes={m.get('success_count', '?')}, "
                            f"failures={m.get('failure_count', '?')}"
                        )
                    extra_context += (
                        "\n\n[Episodic Memory — recent cycle history]\n"
                        + "\n".join(ep_lines)
                        + "\n"
                    )
        except Exception as _ep_exc:
            logger.debug(f"Episodic memory read skipped: {_ep_exc}")

        # Inject consensus memory (team knowledge board)
        try:
            from src.crewai_agents.tools import get_memory_store
            _cons_store = get_memory_store()
            if _cons_store is not None:
                _cons_entries = _cons_store.cons_list()
                # Cap to most recent 20 entries to prevent prompt bloat
                _cons_entries = _cons_entries[-20:] if len(_cons_entries) > 20 else _cons_entries
                if _cons_entries:
                    board_lines = []
                    for _ce in _cons_entries:
                        val = str(_ce.value or "")
                        if len(val) > 200:
                            val = val[:200] + "..."
                        board_lines.append(f"- [{_ce.source_agent_id}] {_ce.key}: {val}")
                    extra_context += (
                        "\n\n[Team Knowledge Board]\n"
                        + "\n".join(board_lines)
                        + "\n"
                    )
        except Exception as _cons_exc:
            logger.debug(f"Consensus injection skipped: {_cons_exc}")

        # Inject customer feedback from previous iteration
        if self.state.user_feedback_summary:
            extra_context += (
                f"\n\n[Customer Feedback from Previous Iteration]\n"
                f"{self.state.user_feedback_summary}\n"
            )

        # Inject architecture issues from previous QA gate
        arch = (self.state.qa_result or {}).get("architecture", {})
        if arch:
            arch_issues = []
            if arch.get("duplicated_css"):
                files = list(arch.get("inline_css_files", {}).keys())
                arch_issues.append(
                    f"DRY: {len(files)} files have large inline CSS with no shared stylesheet"
                )
            pl_count = arch.get("placeholder_link_count", 0)
            if pl_count > 0:
                arch_issues.append(
                    f"BROKEN LINKS: {pl_count} href=\"#\" placeholder links found"
                )
            if arch_issues:
                extra_context += (
                    "\n\n[Architecture Issues to Fix]\n"
                    + "\n".join(f"- {i}" for i in arch_issues)
                    + "\n"
                )

        return extra_context

    def _build_workspace_tools(self):
        """Load workspace tools and return (ws_dev_tools, ws_product_tools, ws_ro_tools)."""
        ws_dev_tools: list = []
        ws_product_tools: list = []
        ws_ro_tools: list = []
        if self.state.workspace_enabled:
            try:
                from src.workspace_tools.file_tools import (
                    read_workspace_file,
                    write_workspace_file,
                    list_workspace_files,
                    review_workspace_files,
                    check_workspace_http,
                    run_workspace_sql,
                )
                ws_dev_tools = [
                    read_workspace_file, write_workspace_file,
                    list_workspace_files,
                    check_workspace_http,
                    run_workspace_sql,
                ]
                ws_product_tools = [
                    read_workspace_file, list_workspace_files,
                ]
                ws_ro_tools = [review_workspace_files, check_workspace_http]
            except Exception as _ws_exc:
                logger.warning("Workspace tools unavailable: %s", _ws_exc)
        return ws_dev_tools, ws_product_tools, ws_ro_tools

    def _run_coordinator_remediation(
        self,
        i: int,
        coordinator_llm,
        ws_product_tools: list,
    ) -> None:
        """Run coordinator-driven remediation after QA gate failure.

        Creates a fresh dispatch tool (budget=4), a fresh build coordinator,
        and a remediation task with QA findings.
        """
        qa_report = self._format_qa_failures(self.state.qa_result)

        # Use stored registry from build(); fall back if unavailable
        registry = getattr(self, "_agent_registry", None)
        if not registry:
            logger.warning("No agent registry for remediation; skipping coordinator remediation")
            return

        remediation_dispatch, remediation_parallel, _get_remediation_count, _get_remediation_history = make_dispatch_task_tool(
            registry, self._emit, max_dispatches=6, result_truncation=4000,
            extra_context="",
        )

        remediation_coordinator = create_build_coordinator(
            coordinator_llm,
            prompt_override=self._prompt_override("coordinator"),
            extra_tools=[remediation_dispatch, remediation_parallel] + (ws_product_tools or []),
        )

        description = f'''[Iteration {i}] QA failed. Fix the issues below by dispatching agents.

            {qa_report}

            Available agents: {sorted(registry.keys())}
            Act through tool calls, not text-only responses.
            '''

        if self.state.user_feedback_summary:
            description += f"\n\n[USER FEEDBACK]\n{self.state.user_feedback_summary}"

        remediation_task = Task(
            description=description,
            agent=remediation_coordinator,
            expected_output='''QA remediation summary including:
            - Root cause(s) identified
            - Fixes applied
            - Final QA status after remediation
            '''
        )

        remediation_crew = Crew(
            agents=[remediation_coordinator],
            tasks=[remediation_task],
            process=Process.sequential,
            verbose=_verbose_flag(self.state.verbose),
            memory=False,
            cache=False,
        )

        try:
            ensure_litellm_tracing()
            remediation_output = remediation_crew.kickoff()

            if _get_remediation_count() == 0:
                logger.info("Remediation coordinator completed without dispatching any agents")

            if remediation_output:
                extra = str(remediation_output)
                self.state.build_result_text = (
                    f"{self.state.build_result_text}\n\n[QA_REMEDIATION]\n{extra}"
                    if self.state.build_result_text
                    else f"[QA_REMEDIATION]\n{extra}"
                )

        except Exception as exc:
            logger.warning(f"Coordinator remediation failed: {exc}")

    @start()
    def build(self):
        """Execute the BUILD phase via coordinator-driven dispatch loop.

        The coordinator dispatches tasks to product_strategist, developer,
        and reviewer agents, reading results and deciding whether to loop.
        Falls back to the legacy sequential pipeline on failure.
        """
        self.state.iteration += 1
        i = self.state.iteration
        _set_agent_cycle_id(i)
        _set_tools_cycle_id(i)
        self._emit("cycle_start", {"cycle_id": i})
        shared_llm = self.state.llm
        coordinator_llm = shared_llm or get_llm("coordinator")
        developer_llm = shared_llm or get_llm("developer")
        reviewer_llm = shared_llm or get_llm("reviewer")
        product_llm = shared_llm or get_llm("product")
        self.state.qa_passed = True
        self.state.qa_result = {}
        # NOTE: user_feedback_summary is NOT cleared here — it carries
        # forward from the previous iteration so _build_extra_context can
        # inject it into the next build task.  It gets replaced when new
        # feedback is collected later in this iteration.
        self.state.build_result_text = ""

        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {i}/{self.state.max_iterations}")
        logger.info(f"{'='*60}\n")
        logger.info("BUILD PHASE: Creating coordinator dispatch loop...")

        # Build workspace tool lists per role
        ws_dev_tools, ws_product_tools, ws_ro_tools = self._build_workspace_tools()

        # Collect learning context from prior iterations
        extra_context = self._build_extra_context()

        # Workspace snapshot: read all files once to avoid redundant reads
        if self.state.workspace_enabled:
            snapshot = self._take_workspace_snapshot()
            extra_context += f"\n\n[Current workspace snapshot]\n{snapshot}\n"

        # Unresolved feedback from prior cycles
        unresolved = self._get_unresolved_feedback()
        if unresolved:
            extra_context += f"\n\n{unresolved}\n"

        # Build agent registry for dispatch tool
        agent_registry = {
            "product_strategist": {
                "factory": create_product_strategist,
                "llm": product_llm,
                "extra_tools": ws_product_tools or None,
                "prompt_override": self._prompt_override("product"),
            },
            "developer": {
                "factory": create_developer_agent,
                "llm": developer_llm,
                "extra_tools": ws_dev_tools or None,
                "prompt_override": self._prompt_override("developer"),
            },
            "reviewer": {
                "factory": create_reviewer_agent,
                "llm": reviewer_llm,
                "extra_tools": ws_ro_tools or None,
                "prompt_override": self._prompt_override("reviewer"),
            },
        }
        self._agent_registry = agent_registry

        # Create dispatch tool and coordinator
        max_dispatches = int(self.state.active_policies.get("max_total_delegated_tasks", 12))
        dispatch_tool, dispatch_parallel_tool, _get_dispatch_count, _get_dispatch_history = make_dispatch_task_tool(
            agent_registry, self._emit, max_dispatches=max_dispatches, result_truncation=4000,
            extra_context=extra_context,
        )
        build_coordinator = create_build_coordinator(
            coordinator_llm,
            prompt_override=self._prompt_override("coordinator"),
            extra_tools=[dispatch_tool, dispatch_parallel_tool, mark_feedback_addressed_tool] + (ws_product_tools or []),
        )

        # Create coordinator task
        coordinator_task = _create_coordinator_build_task(
            build_coordinator,
            iteration=i,
            available_roles=sorted(agent_registry.keys()),
            extra_context=extra_context,
        )

        build_crew = Crew(
            agents=[build_coordinator],
            tasks=[coordinator_task],
            process=Process.sequential,
            verbose=_verbose_flag(self.state.verbose),
            memory=False,
            cache=False,
        )

        logger.info("BUILD PHASE: Executing coordinator dispatch loop...")
        task_count = 1  # single coordinator task
        success_count = 0
        failure_count = 0
        crew_output = None

        self._emit("task_started", {
            "task_id": f"build_coordinator_iter_{i}",
            "agent_role": "BUILD Coordinator",
            "objective": f"BUILD phase iteration {i} (coordinator dispatch)",
        })
        try:
            ensure_litellm_tracing()
            crew_output = build_crew.kickoff()
            success_count = 1

            if _get_dispatch_count() == 0:
                logger.info("Coordinator completed without dispatching any agents")

        except Exception as exc:
            logger.error(f"BUILD coordinator failed: {exc}")
            failure_count = 1

        self._emit("task_completed", {
            "task_id": f"build_coordinator_iter_{i}",
            "task_status": "success" if crew_output else "failed",
            "success_count": success_count,
            "failure_count": failure_count,
        })

        # Deterministic QA gate
        self.state.qa_result = self._run_quality_gate()
        self.state.qa_passed = self._qa_passed()

        # Surface architecture findings in build result so learn phase sees them
        arch = self.state.qa_result.get("architecture", {})
        if arch:
            arch_lines = []
            if arch.get("duplicated_css"):
                files = list(arch.get("inline_css_files", {}).keys())
                arch_lines.append(
                    f"DRY VIOLATION: {len(files)} files have large inline <style> blocks "
                    f"with no shared CSS file. Files: {', '.join(files)}. "
                    f"Extract common styles into styles.css."
                )
            if arch.get("placeholder_link_count", 0) > 0:
                for p in arch.get("placeholder_links", []):
                    arch_lines.append(
                        f"BROKEN LINKS: {p['file']} has {p['count']} href=\"#\" placeholder links."
                    )
            if arch_lines:
                self.state.build_result_text = (
                    f"{self.state.build_result_text}\n\n"
                    f"[ARCHITECTURE ISSUES]\n" + "\n".join(arch_lines)
                )

        # Run remediation BEFORE customer testing so personas see the best
        # content this iteration can produce (not a placeholder page).
        if not self.state.qa_passed:
            logger.warning("QA gate failed; running coordinator remediation")
            self._run_coordinator_remediation(i, coordinator_llm, ws_product_tools)
            self.state.qa_result = self._run_quality_gate()
            self.state.qa_passed = self._qa_passed()

        # LLM-powered customer testing (after remediation, so personas see real content)
        if self.state.workspace_enabled:
            self._run_customer_testing()

        # Collect current cycle's feedback from feedback.db
        if self.state.workspace_enabled:
            feedback_summary = self._collect_user_feedback()
            if feedback_summary and "No user feedback" not in feedback_summary:
                self.state.user_feedback_summary = feedback_summary

        self.state.build_task_count = task_count
        self.state.build_success_count = success_count
        self.state.build_failure_count = failure_count
        if not self.state.build_result_text:
            self.state.build_result_text = str(crew_output) if crew_output else ""
        qa_summary = json.dumps(self.state.qa_result or {}, indent=2, ensure_ascii=True)
        self.state.build_result_text = (
            f"{self.state.build_result_text}\n\n[QA_GATE]\n{qa_summary}"
            if self.state.build_result_text
            else f"[QA_GATE]\n{qa_summary}"
        )
        if crew_output and hasattr(crew_output, "pydantic") and crew_output.pydantic is not None:
            self.state.build_output = crew_output.pydantic
        else:
            self.state.build_output = None

    # -- EVALUATE gate ----------------------------------------------------

    @listen(build)
    def evaluate(self):
        """Run framework evaluation gates against QA and build metrics."""
        logger.info("EVALUATE: Checking gates...")

        self.state.gate_recommendation = "continue"

        try:
            from src.framework.contracts import CycleMetrics
            procedure_score = self.state.build_success_count / max(1, self.state.build_task_count)
            metrics = CycleMetrics(
                cycle_id=self.state.iteration,
                task_count=self.state.build_task_count,
                success_count=self.state.build_success_count,
                failure_count=self.state.build_failure_count,
                domain_metrics={
                    "qa_gate_passed": bool(self.state.qa_passed),
                    "determinism_variance": 0.0,
                    "procedure_score": procedure_score,
                },
            )

            # Reconstruct previous CycleMetrics for trend analysis
            previous_metrics = None
            if self.state.previous_cycle_metrics:
                previous_metrics = CycleMetrics(**self.state.previous_cycle_metrics)

            evaluator = self._get_evaluator()
            result = evaluator.evaluate(metrics, previous_metrics=previous_metrics)
            self.state.gate_recommendation = result.recommended_action
            logger.info(
                f"  Gate result: {result.overall_status} -> {result.recommended_action}"
            )

            # Run policy updater on gate failures
            if result.overall_status != "pass":
                try:
                    pu = self._get_policy_updater()
                    patches = pu.propose_patches(result, self.state.active_policies)
                    if patches:
                        version = pu.apply_patches(self.state.active_policies, patches)
                        self.state.active_policies = dict(version.policies)
                        logger.info(f"  PolicyUpdater applied {len(patches)} patches")
                except Exception as exc:
                    logger.warning(f"  PolicyUpdater skipped: {exc}")

            # Save current metrics for next iteration's trend analysis
            self.state.previous_cycle_metrics = metrics.model_dump()

        except Exception as exc:
            logger.warning(f"  Evaluation skipped: {exc}")

        # Collect user feedback if not already collected in build()
        if self.state.workspace_enabled and not self.state.user_feedback_summary:
            feedback_summary = self._collect_user_feedback()
            if feedback_summary and "No user feedback" not in feedback_summary:
                self.state.user_feedback_summary = feedback_summary

    # -- LEARN phase ------------------------------------------------------

    @listen(evaluate)
    def learn(self):
        """Execute the LEARN phase and feed results back into next iteration."""
        logger.info("LEARN PHASE: Extracting insights...")

        # Append QA status to build results so the LEARN coordinator can reflect on it
        if not self.state.qa_passed:
            qa_report = self._format_qa_failures(self.state.qa_result)
            self.state.build_result_text = (
                f"{self.state.build_result_text}\n\n[QA_STATUS: FAILED]\n{qa_report}"
            )

        # Collect real user feedback (simulation feedback available from cycle 1)
        feedback_summary = self._collect_user_feedback()
        if feedback_summary and "No user feedback" not in feedback_summary:
            self.state.build_result_text = (
                f"{self.state.build_result_text}\n\n"
                f"[USER_FEEDBACK]\n{feedback_summary}"
            )

        coordinator_llm = self.state.llm or get_llm("coordinator")
        coordinator = create_master_coordinator(coordinator_llm)

        learn_task = create_learn_phase_task(
            coordinator,
            self.state.build_result_text,
        )

        learn_crew = Crew(
            agents=[coordinator],
            tasks=[learn_task],
            process=Process.sequential,
            verbose=_verbose_flag(self.state.verbose),
            memory=False,
            cache=False,
        )

        ensure_litellm_tracing()
        learn_result = learn_crew.kickoff()

        if hasattr(learn_result, "pydantic") and learn_result.pydantic is not None:
            self.state.learn_output = learn_result.pydantic
        else:
            # Fallback: parse unstructured text into LearnPhaseOutput fields
            raw_text = str(learn_result)
            insights, recommendations = _parse_learn_text(raw_text)
            self.state.learn_output = LearnPhaseOutput(
                summary=raw_text,
                insights=insights,
                recommendations=recommendations,
            )

        self._apply_learning_feedback()
        self._record_iteration()

    # -- Recording & learning helpers -------------------------------------

    def _record_iteration(self) -> None:
        """Store iteration results in the accumulated state."""
        qa_metrics: Dict[str, Any] = {
            "qa_passed": bool(self.state.qa_passed),
            "task_count": self.state.build_task_count,
            "success_count": self.state.build_success_count,
            "failure_count": self.state.build_failure_count,
        }

        iteration_result = {
            "iteration": self.state.iteration,
            "build": self.state.build_result_text,
            "learn": self.state.learn_output.model_dump() if self.state.learn_output else {},
            "quality_assurance": {
                "qa_passed": bool(self.state.qa_passed),
                "qa_result": dict(self.state.qa_result or {}),
            },
            "user_feedback": dict(self.state.user_feedback or {}),
            "autonomy": {
                "prompt_overrides": dict(self.state.prompt_overrides),
            },
        }

        self.state.iterations_results.append(iteration_result)
        self.state.metrics_evolution.append(qa_metrics)

        self._emit("cycle_end", {
            "cycle_id": self.state.iteration,
            "total_tasks": self.state.build_task_count,
            "completed_count": self.state.build_success_count,
            "failed_count": self.state.build_failure_count,
            "evaluation_status": "pass" if self.state.qa_passed else "fail",
            "termination_action": self.state.gate_recommendation,
        })

        # Write cycle metrics to episodic memory for cross-run history
        try:
            from src.crewai_agents.tools import get_memory_store as _get_store_rec
            from src.framework.contracts import Episode
            from src.framework.types import EpisodeType as _EpType

            _rec_store = _get_store_rec()
            if _rec_store is not None:
                _rec_store.ep_record(Episode(
                    agent_id="bml_flow",
                    episode_type=_EpType.LEARNING,
                    action=f"bml_cycle_iteration_{self.state.iteration}",
                    iteration=self.state.iteration,
                    success=bool(self.state.qa_passed),
                    outcome={
                        "qa_passed": bool(self.state.qa_passed),
                        "task_count": self.state.build_task_count,
                        "success_count": self.state.build_success_count,
                        "failure_count": self.state.build_failure_count,
                        "gate_recommendation": self.state.gate_recommendation,
                    },
                    summary_text=(
                        f"Iteration {self.state.iteration}: "
                        f"QA={'PASS' if self.state.qa_passed else 'FAIL'}, "
                        f"{self.state.build_success_count}/{self.state.build_task_count} tasks succeeded"
                    ),
                ))
                logger.info("  Episodic memory: recorded cycle metrics")
        except Exception as _ep_rec_exc:
            logger.warning(f"  Episodic memory write skipped: {_ep_rec_exc}")

        logger.info(
            f"\nIteration {self.state.iteration} complete: "
            f"QA={'PASS' if self.state.qa_passed else 'FAIL'}, "
            f"{self.state.build_success_count}/{self.state.build_task_count} tasks succeeded"
        )

    def _apply_learning_feedback(self) -> None:
        """Use ProcedureUpdater to persist learnings and prepare hints."""
        lo = self.state.learn_output
        if lo is None:
            return

        hints_parts: List[str] = []
        if lo.insights:
            hints_parts.append("Insights: " + "; ".join(lo.insights))
        if lo.recommendations:
            for team, rec in lo.recommendations.items():
                hints_parts.append(f"{team}: {rec}")
        self.state.procedure_hints = "\n".join(hints_parts) if hints_parts else ""
        self.state.learnings.extend(lo.insights)
        self._update_prompt_overrides(lo)

        # Write insights and recommendations to consensus memory so the
        # team knowledge board grows across iterations.
        try:
            from src.crewai_agents.tools import get_memory_store
            from src.framework.contracts import ConsensusEntry

            _learn_store = get_memory_store()
            if _learn_store is not None:
                iteration = self.state.iteration
                for idx, insight in enumerate(lo.insights[:5]):
                    _learn_store.cons_set(ConsensusEntry(
                        key=f"learn.insight.iter{iteration}.{idx}",
                        value=str(insight)[:500],
                        source_agent_id="coordinator",
                    ))
                for team, rec in (lo.recommendations or {}).items():
                    _learn_store.cons_set(ConsensusEntry(
                        key=f"learn.recommendation.{team}",
                        value=str(rec)[:500],
                        source_agent_id="coordinator",
                    ))
                logger.info("  Consensus memory: wrote learn-phase insights")
        except Exception as _cons_learn_exc:
            logger.warning(f"  Consensus memory write skipped: {_cons_learn_exc}")

        try:
            proc_updater = self._get_procedure_updater()
            if proc_updater is not None:
                workflow = {
                    "insights": lo.insights,
                    "recommendations": lo.recommendations,
                    "successes": lo.successes,
                    "failures": lo.failures,
                }
                proposal = proc_updater.propose_update(
                    task_type="bml_cycle",
                    workflow=workflow,
                    score=lo.predicted_improvement,
                )
                proc_updater.apply_update(proposal)
                logger.info("  ProcedureUpdater: saved cycle learnings")
        except Exception as exc:
            logger.warning(f"  ProcedureUpdater skipped: {exc}")

    def _update_prompt_overrides(self, learn_output: LearnPhaseOutput) -> None:
        """Refine role prompts from LEARN recommendations/failures."""

        def _role_key(raw_text: str) -> str:
            text = str(raw_text or "").lower()
            if "reviewer" in text or "qa" in text or "quality" in text:
                return "reviewer"
            if "developer" in text or "engineering" in text or "implement" in text:
                return "developer"
            if "product" in text or "tool" in text:
                return "product"
            if "data" in text:
                return "developer"
            if "coord" in text or "strategy" in text:
                return "coordinator"
            return ""

        updated = dict(self.state.prompt_overrides or {})

        for team, recommendation in (learn_output.recommendations or {}).items():
            key = _role_key(team)
            rec = str(recommendation or "").strip()
            if not key or not rec:
                continue
            previous = str(updated.get(key, "")).strip()
            updated[key] = rec if not previous else f"{previous} | {rec}"

        if learn_output.failures:
            for failure in learn_output.failures:
                key = _role_key(failure)
                if not key or key in updated:
                    continue
                updated[key] = f"Address failure signal: {failure}"

        # Keep overrides bounded for deterministic prompt size.
        for key, value in list(updated.items()):
            text = str(value).strip()
            if len(text) > 3000:
                updated[key] = text[-3000:]

        self.state.prompt_overrides = updated

    # -- Public entry point -----------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Execute the full multi-iteration BML flow.

        Each call to ``kickoff()`` runs one BUILD -> EVALUATE -> LEARN
        pipeline.  We loop externally so that learnings from iteration *N*
        feed into iteration *N+1* via ``procedure_hints``.

        Returns:
            Aggregated results dict matching the existing public interface.
        """
        self._emit("run_start", {
            "run_id": self.state.id,
            "max_iterations": self.state.max_iterations,
        })

        for _ in range(self.state.max_iterations):
            self.kickoff()

            # Respect gate recommendation: stop early if evaluation says to.
            rec = self.state.gate_recommendation
            if rec == "stop":
                logger.info("  Gate recommended STOP — halting iterations.")
                break
            if rec == "rollback":
                logger.info("  Gate recommended ROLLBACK — halting iterations.")
                break

        logger.info(f"\n{'='*60}")
        logger.info("ALL ITERATIONS COMPLETE")
        logger.info(f"{'='*60}\n")

        self._emit("run_end", {
            "run_id": self.state.id,
            "iterations_completed": self.state.iteration,
        })

        return {
            "iterations": self.state.iterations_results,
            "metrics_evolution": self.state.metrics_evolution,
            "learnings": self.state.learnings,
        }

