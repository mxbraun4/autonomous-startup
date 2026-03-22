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
        build_results: Results from BUILD phase (includes customer feedback)

    Returns:
        LEARN phase task
    """
    return Task(
        description=f'''Analyze results from this Build-Measure-Learn iteration and extract learnings.

        BUILD Phase Results (including customer feedback):
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
    1. Call list_workspace_files, then read_workspace_file on key files (app.py, templates).
    2. Call dispatch_task_to_agent to assign work. You MUST dispatch at least one agent — do NOT give a Final Answer without dispatching.
    3. Review dispatch results and dispatch follow-up tasks if needed.
    4. After fixing issues from user feedback, call mark_feedback_addressed with the resolved IDs.
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
    max_iterations: int = 400
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
    # Gate recommendation from the MEASURE phase
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
    """Event-driven Build-Measure-Learn cycle using CrewAI Flows.

    Each call to :meth:`kickoff` runs one complete BUILD -> MEASURE -> LEARN
    pipeline.  :meth:`run` loops over multiple iterations, feeding learnings
    from one iteration into the next.
    """

    def __init__(
        self,
        max_iterations: int = 400,
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
        """Run a minimal syntax check and let customer feedback drive QA.

        Only checks Python syntax (if syntax is broken the app won't
        start and customer testing can't run).  All other quality
        signals come from the LLM-powered customer personas.
        """
        from src.crewai_agents.tools import run_quality_checks_tool

        result: Dict[str, Any] = {}

        # Python syntax check only
        try:
            raw = run_quality_checks_tool.run(
                paths_csv="workspace",
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

        syntax_ok = bool((result.get("syntax") or {}).get("syntax_ok", True))
        result["syntax_ok"] = syntax_ok

        # Count open customer bugs to determine pass/fail
        bug_count = 0
        try:
            from src.workspace_tools.file_tools import _get_open_feedback
            open_items = _get_open_feedback(exclude_cycle=0)
            bug_count = sum(1 for it in open_items if it.get("feedback_type") == "bug")
        except Exception:
            pass

        result["open_bug_count"] = bug_count
        gate_passed = syntax_ok and bug_count == 0
        result["qa_gate_passed"] = gate_passed
        result["status"] = "passed" if gate_passed else "failed"

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
        """Build a lightweight workspace overview (file names + structure).

        Never includes full file contents — agents use
        ``read_workspace_file`` to inspect specific files on demand.
        """
        try:
            import re as _re_snap
            from src.workspace_tools.file_tools import _list_impl, _read_impl

            listing = _list_impl()
            files = listing.get("files", [])
            if not files:
                return "[Workspace is empty — no files yet]"

            _SKIP_EXTS = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3",
                          ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}
            readable_files = [
                f for f in files
                if not any(f.lower().endswith(ext) for ext in _SKIP_EXTS)
                and "__pycache__" not in f
            ]

            sections = [f"Files ({len(readable_files)}):"]
            sections.append("\n".join(f"  {f}" for f in sorted(readable_files)))

            # Extract routes from app.py if it exists
            app_result = _read_impl("app.py")
            if app_result.get("status") == "ok":
                app_source = app_result.get("content", "")
                route_matches = _re_snap.findall(
                    r"@app\.route\(\s*['\"]([^'\"]+)['\"]"
                    r"(?:\s*,\s*methods\s*=\s*\[([^\]]*)\])?\s*\)",
                    app_source,
                )
                if route_matches:
                    route_lines = []
                    for path, methods in route_matches:
                        methods_str = methods.strip().replace("'", "").replace('"', '') if methods else "GET"
                        route_lines.append(f"  {path} [{methods_str}]")
                    sections.append(f"\nRoutes ({len(route_matches)}):")
                    sections.append("\n".join(route_lines))

            sections.append("\nUse read_workspace_file to view file contents.")
            return "\n".join(sections)
        except Exception as exc:
            logger.warning("Workspace snapshot failed: %s", exc)
            return "[Workspace snapshot unavailable]"

    # Feedback older than this many cycles is auto-addressed to keep
    # the backlog manageable and prevent prompt bloat.
    _FEEDBACK_STALE_CYCLES = 5

    def _get_unresolved_feedback(self) -> str:
        """Collect open feedback from prior cycles as a formatted summary.

        Returns a string listing unresolved feedback items with their IDs
        so the BUILD coordinator can address them and mark them resolved
        via the mark_feedback_addressed tool.

        Feedback older than ``_FEEDBACK_STALE_CYCLES`` iterations is
        automatically marked as addressed to prevent infinite accumulation.
        """
        try:
            from src.workspace_tools.file_tools import (
                _get_open_feedback,
                _mark_feedback_addressed,
            )

            # Auto-expire stale feedback
            cutoff = self.state.iteration - self._FEEDBACK_STALE_CYCLES
            if cutoff > 0:
                all_open = _get_open_feedback(exclude_cycle=0)  # get everything
                stale_ids = [
                    it["id"] for it in all_open
                    if (it.get("cycle_id") or 0) < cutoff
                ]
                if stale_ids:
                    _mark_feedback_addressed(stale_ids, addressed_in_cycle=self.state.iteration)
                    logger.info(
                        "Auto-expired %d stale feedback items (older than %d cycles)",
                        len(stale_ids), self._FEEDBACK_STALE_CYCLES,
                    )

            open_items = _get_open_feedback(exclude_cycle=self.state.iteration)
            if not open_items:
                return ""

            # Enrich signal: count by type, compute age, detect recurrence
            from collections import Counter
            type_counts = Counter(it.get("feedback_type", "?") for it in open_items)
            oldest_cycle = min(it.get("cycle_id", self.state.iteration) for it in open_items)
            age = self.state.iteration - oldest_cycle

            summary_parts = [f"{c} {t}s" for t, c in type_counts.most_common()]
            lines = [
                f"UNRESOLVED USER FEEDBACK ({len(open_items)} open items: {', '.join(summary_parts)}; oldest from {age} cycles ago):",
                "Use mark_feedback_addressed after resolving items.",
                "",
            ]
            for item in open_items[:10]:  # cap to avoid prompt bloat
                fid = item.get("id", "?")
                cycle = item.get("cycle_id", "?")
                ftype = item.get("feedback_type", "?")
                msg = item.get("message", "")
                item_age = self.state.iteration - (item.get("cycle_id") or self.state.iteration)
                lines.append(f"  [{fid}] [cycle {cycle}, {item_age} iters open][{ftype}] {msg}")

            if len(open_items) > 10:
                lines.append(f"  ... and {len(open_items) - 10} more")

            return "\n".join(lines)
        except Exception:
            return ""

    def _build_idle_cycle_fallback_task(self) -> str:
        """Build a developer task description for idle-cycle recovery.

        Uses unresolved feedback if available; otherwise a generic
        improvement task.
        """
        try:
            from src.workspace_tools.file_tools import _get_open_feedback

            open_items = _get_open_feedback(exclude_cycle=self.state.iteration)
            if open_items:
                bugs = [it for it in open_items if it.get("feedback_type") == "bug"]
                target_items = bugs[:3] if bugs else open_items[:3]
                lines = [
                    "FIX the following open issues reported by users:\n",
                ]
                for it in target_items:
                    lines.append(f"- [{it.get('feedback_type','bug')}] {it.get('page','?')}: {it.get('message','')[:200]}")
                lines.append("\nRead the relevant files and apply fixes.")
                return "\n".join(lines)
        except Exception:
            pass
        return (
            "Review the current workspace files and make one concrete improvement: "
            "fix any broken HTML, add missing form submit buttons, or improve the homepage. "
            "Read files first, then write fixes."
        )

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
        """Format QA failures into a human-readable report.

        Only two failure sources: syntax errors and customer-reported bugs.
        """
        if not qa_result:
            return "No QA results available."

        sections: List[str] = []
        failure_num = 0

        # 1. Syntax failures
        syntax = qa_result.get("syntax") or {}
        if not syntax.get("syntax_ok", True):
            failure_num += 1
            lines = [f"{failure_num}. SYNTAX ERRORS"]
            for entry in syntax.get("syntax_failures", []):
                f_path = entry.get("file", "unknown")
                error = entry.get("error", "unknown error")
                lines.append(f"   - {f_path}: {error}")
            lines.append("   Fix: correct the Python syntax errors above.")
            sections.append("\n".join(lines))

        # 2. Customer-reported bugs
        try:
            from src.workspace_tools.file_tools import _get_open_feedback

            open_items = _get_open_feedback(exclude_cycle=0)
            bug_items = [it for it in open_items if it.get("feedback_type") == "bug"]
            friction_items = [it for it in open_items if it.get("feedback_type") == "friction"]
            actionable = bug_items + friction_items
            if actionable:
                failure_num += 1
                lines = [f"{failure_num}. CUSTOMER FEEDBACK ({len(actionable)} bugs/friction items)"]
                for item in actionable[:8]:
                    fid = item.get("id", "?")
                    ftype = item.get("feedback_type", "?")
                    msg = item.get("message", "")
                    lines.append(f"   [{fid}][{ftype}] {msg}")
                if len(actionable) > 8:
                    lines.append(f"   ... and {len(actionable) - 8} more")
                lines.append("   Fix: dispatch developer to address these issues, then call mark_feedback_addressed with the resolved IDs.")
                sections.append("\n".join(lines))
        except Exception:
            pass

        if not sections:
            return "QA gate passed - no failures detected."

        return f"QA FAILURE REPORT ({failure_num} issue(s)):\n\n" + "\n\n".join(sections)

    # -- BUILD phase ------------------------------------------------------

    def _summarize_context(self, raw_context: str) -> str:
        """Use a single LLM call to compress raw accumulated context.

        Replaces blind truncation with intelligent curation: the LLM
        identifies the most actionable items, discards stale/resolved
        issues, and produces a focused brief for the next BUILD phase.

        Uses the same model as the product strategist agent (via
        ``get_llm("product")``).  Falls back to hard cap on error.
        """
        if not raw_context.strip():
            return raw_context

        try:
            import litellm

            # Resolve model the same way CrewAI agents do
            product_llm = self.state.llm or get_llm("product")
            model = product_llm.model
            # Build kwargs from the LLM config
            kwargs: dict = {}
            if hasattr(product_llm, "api_key") and product_llm.api_key:
                kwargs["api_key"] = product_llm.api_key
            if hasattr(product_llm, "base_url") and product_llm.base_url:
                kwargs["api_base"] = product_llm.base_url

            iteration = self.state.iteration
            total_iters = self.state.max_iterations
            completed = len(self.state.metrics_evolution) if self.state.metrics_evolution else 0

            # Detect stale bugs: if feedback has been open for 3+ iterations,
            # the agents are stuck in a loop and need to try a different approach.
            stale_bug_warning = ""
            try:
                from src.workspace_tools.file_tools import _get_open_feedback
                open_items = _get_open_feedback(exclude_cycle=iteration)
                if open_items:
                    oldest_cycle = min(it.get("cycle_id", iteration) for it in open_items)
                    age = iteration - oldest_cycle
                    if age >= 3:
                        stale_bug_warning = (
                            f"\n\nCRITICAL: The same bugs have persisted for {age} iterations. "
                            f"Patching the same code has NOT worked. "
                            f"The developer MUST take a completely different approach:\n"
                            f"- REWRITE the broken feature from scratch instead of patching\n"
                            f"- If auth/session is broken, delete all auth code and rebuild it simply\n"
                            f"- Do NOT make small edits to the same code region that failed before\n"
                        )
            except Exception:
                pass

            prompt = f"""You are the product strategist for an autonomous startup-VC matching platform.
The platform is built with Flask + SQLite + Jinja templates by AI agents in a Build-Measure-Learn loop.

CURRENT STATUS:
- About to start iteration {iteration} of {total_iters} ({completed} completed so far)

HOW THE SYSTEM WORKS:
- BUILD phase: coordinator dispatches developer, product_strategist, and reviewer agents
- Customer testing: 3 LLM personas (founder, VC partner, journalist) visit the live app and report bugs/friction
- LEARN phase: insights and recommendations are stored for the next iteration
- Customer feedback is stored in feedback.db and fed back to the build coordinator
{stale_bug_warning}
Below is the RAW ACCUMULATED CONTEXT from all memory stores (prior learnings, episodic history, team knowledge board, customer feedback, procedural memory). Much of it may be stale, redundant, or already resolved.

YOUR JOB: Produce an ACTION BRIEF (max 1200 chars) containing:
1. What exists now and what's working
2. Top 3-5 unresolved issues (specific: route names, errors, customer feedback)
3. What was tried before and failed (so agents try something different)
4. If bugs have persisted for 3+ iterations: tell the developer to REWRITE the broken feature from scratch, not patch it

No resolved issues, no praise, no repetition. Be specific.

RAW CONTEXT:
{raw_context[:12000]}"""

            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
                **kwargs,
            )
            summary = response.choices[0].message.content or ""
            if summary and len(summary) > 100:
                logger.info(
                    "Context summarized: %d -> %d chars",
                    len(raw_context), len(summary),
                )
                return f"\n\n[Strategist Brief — iteration {self.state.iteration}]\n{summary}\n"
        except Exception as exc:
            logger.warning("Context summarization failed: %s", exc)

        # Fallback: hard cap
        _MAX = 12_000
        if len(raw_context) > _MAX:
            return raw_context[:_MAX] + "\n\n[... context truncated]\n"
        return raw_context

    def _build_extra_context(self) -> str:
        """Collect learning context from prior iterations and memory stores.

        Gathers procedure hints, procedural memory, episodic memory, and
        consensus memory into a single string appended to BUILD task
        descriptions.  On iteration 2+, the accumulated raw context is
        compressed by a lightweight LLM summarization call to keep the
        coordinator focused and prevent context window saturation.
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
                    if wf.get("failures"):
                        parts.append("AVOID (failed before): " + "; ".join(str(x) for x in wf["failures"]))
                    if wf.get("successes"):
                        parts.append("REPEAT (worked before): " + "; ".join(str(x) for x in wf["successes"]))
                    if wf.get("recommendations"):
                        for _team, _rec in wf["recommendations"].items():
                            parts.append(f"ACTION for {_team}: {_rec}")
                    if parts:
                        extra_context += (
                            f"\n\n[Procedural Memory — v{_latest.version}, "
                            f"score {_latest.score:.0%}]\n"
                            + "\n".join(parts)
                            + "\n"
                        )
        except Exception as _proc_exc:
            logger.debug(f"Procedural memory read skipped: {_proc_exc}")

        # Inject episodic memory (enriched history from prior cycles/runs)
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
                        # Use the enriched summary_text if available
                        if _ep.summary_text and len(_ep.summary_text) > 30:
                            ep_lines.append(f"- {_ep.summary_text}")
                        else:
                            m = _ep.outcome or {}
                            it = _ep.iteration or "?"
                            dispatches = m.get("dispatches", [])
                            bugs = m.get("open_bugs", 0)
                            line = f"- Cycle {it}"
                            if dispatches:
                                line += f": {'; '.join(dispatches[:3])}"
                            if bugs:
                                line += f" (bugs: {bugs})"
                            ep_lines.append(line)
                    extra_context += (
                        "\n\n[Episodic Memory — recent cycle history]\n"
                        + "\n".join(ep_lines)
                        + "\n"
                    )
        except Exception as _ep_exc:
            logger.debug(f"Episodic memory read skipped: {_ep_exc}")

        # Inject consensus memory (team knowledge board)
        # Auto-expire stale per-iteration insights and deduplicate values.
        try:
            from src.crewai_agents.tools import get_memory_store
            _cons_store = get_memory_store()
            if _cons_store is not None:
                _cons_entries = _cons_store.cons_list()

                # --- Auto-expire old per-iteration insights ---
                # Keys like "learn.insight.iter3.0" pile up; keep only
                # recent iterations (last _CONSENSUS_STALE_CYCLES).
                import re as _re_cons
                _CONSENSUS_STALE_CYCLES = 5
                cutoff_iter = self.state.iteration - _CONSENSUS_STALE_CYCLES
                fresh_entries = []
                for _ce in _cons_entries:
                    m = _re_cons.match(r"learn\.insight\.iter(\d+)\.", _ce.key)
                    if m and int(m.group(1)) < cutoff_iter:
                        continue  # skip stale per-iteration insight
                    fresh_entries.append(_ce)

                # --- Deduplicate by value ---
                # Different keys can hold the same insight text (e.g.
                # route X shows login form repeated across iterations).
                seen_values: set = set()
                deduped_entries = []
                for _ce in fresh_entries:
                    val_norm = str(_ce.value or "").strip().lower()[:150]
                    if val_norm in seen_values:
                        continue
                    seen_values.add(val_norm)
                    deduped_entries.append(_ce)

                # Cap to most recent 15 entries
                _cons_entries = deduped_entries[-15:] if len(deduped_entries) > 15 else deduped_entries
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

        # Architecture issues are now caught by customer personas, not hardcoded checks.

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
                    edit_workspace_file,
                    write_workspace_file,
                    delete_workspace_file,
                    list_workspace_files,
                    review_workspace_files,
                    check_workspace_http,
                    run_workspace_sql,
                )
                from src.crewai_agents.tools import list_installed_packages
                ws_dev_tools = [
                    read_workspace_file, edit_workspace_file,
                    write_workspace_file, delete_workspace_file,
                    list_workspace_files,
                    check_workspace_http,
                    run_workspace_sql,
                    list_installed_packages,
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
            registry, self._emit, max_dispatches=12, result_truncation=4000,
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

        # Reset per-cycle read cache so agents start with fresh file data
        try:
            from src.workspace_tools.file_tools import reset_read_cache
            reset_read_cache()
        except Exception:
            pass
        shared_llm = self.state.llm
        coordinator_llm = shared_llm or get_llm("coordinator")
        developer_llm = shared_llm or get_llm("developer")
        reviewer_llm = shared_llm or get_llm("reviewer")
        product_llm = shared_llm or get_llm("product")
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

        # Collect learning context from prior iterations (memory stores).
        memory_context = self._build_extra_context()

        # Unresolved feedback from prior cycles
        unresolved = self._get_unresolved_feedback()

        # Smart context curation: on iteration 2+, the strategist LLM
        # always summarizes accumulated memory + feedback into a focused brief.
        if i > 1 and memory_context.strip():
            summarizer_input = memory_context
            if unresolved:
                summarizer_input += f"\n\n{unresolved}"
            memory_context = self._summarize_context(summarizer_input)
            unresolved = ""

        # Assemble final context with a lightweight workspace overview
        # (file names + structure only — agents use read_workspace_file
        # to see actual contents when they need them).
        extra_context = memory_context
        if self.state.workspace_enabled:
            snapshot = self._take_workspace_snapshot()
            extra_context += f"\n\n[Workspace overview]\n{snapshot}\n"
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
        # Store dispatch accessors so _record_iteration can enrich episodic memory
        self._get_dispatch_count = _get_dispatch_count
        self._get_dispatch_history = _get_dispatch_history
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

            # -- Idle-cycle guardrail ------------------------------------------
            # If the coordinator finished without dispatching any agent, it
            # wasted the cycle.  Force a minimal developer dispatch so every
            # iteration produces at least one code-level action.
            if _get_dispatch_count() == 0:
                logger.warning(
                    "IDLE CYCLE DETECTED (iter %d): coordinator dispatched 0 agents — "
                    "forcing a developer dispatch to address open feedback or improve the product.",
                    i,
                )
                # Build a fallback task from unresolved feedback or a generic improvement
                fallback_desc = self._build_idle_cycle_fallback_task()
                try:
                    from src.crewai_agents.tools import _execute_dispatch_fallback
                    _execute_dispatch_fallback(
                        agent_registry, self._emit, "developer", fallback_desc, extra_context,
                    )
                except Exception as fb_exc:
                    logger.warning("Idle-cycle fallback dispatch failed: %s", fb_exc)

        except Exception as exc:
            logger.error(f"BUILD coordinator failed: {exc}")
            failure_count = 1

        self._emit("task_completed", {
            "task_id": f"build_coordinator_iter_{i}",
            "task_status": "success" if crew_output else "failed",
            "success_count": success_count,
            "failure_count": failure_count,
        })

        # Refresh workspace snapshot AFTER build so QA, remediation, and
        # learn phases all see the actual files the developer produced.
        if self.state.workspace_enabled:
            try:
                from src.workspace_tools.file_tools import reset_read_cache
                reset_read_cache()
            except Exception:
                pass
            post_build_snapshot = self._take_workspace_snapshot()
            self.state.build_result_text = (
                f"{self.state.build_result_text}\n\n"
                f"[Post-build workspace snapshot]\n{post_build_snapshot}"
            )
            logger.info("POST-BUILD snapshot captured (%d chars)", len(post_build_snapshot))

        # LLM-powered customer testing — personas visit the live app
        # and report bugs/friction.  Their feedback flows to the next
        # iteration's build coordinator via the strategist brief.
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
        if crew_output and hasattr(crew_output, "pydantic") and crew_output.pydantic is not None:
            self.state.build_output = crew_output.pydantic
        else:
            self.state.build_output = None

    # -- MEASURE phase -----------------------------------------------------

    @listen(build)
    def measure(self):
        """Measure phase — customer feedback was already collected in build().

        This step exists to maintain the BUILD -> MEASURE -> LEARN flow
        structure required by the CrewAI Flow listener chain.
        """
        logger.info("MEASURE: Customer feedback collected, proceeding to learn...")
        self.state.gate_recommendation = "continue"

    # -- LEARN phase ------------------------------------------------------

    @listen(measure)
    def learn(self):
        """Execute the LEARN phase and feed results back into next iteration."""
        logger.info("LEARN PHASE: Extracting insights...")

        # Collect user feedback (customer personas' feedback from this cycle)
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

        # Derive a score from dispatch success when the LLM doesn't provide one
        if self.state.learn_output.predicted_improvement == 0.0:
            dispatched = self.state.build_success_count
            total = max(1, self.state.build_task_count)
            self.state.learn_output.predicted_improvement = dispatched / total

        self._apply_learning_feedback()
        self._record_iteration()

    # -- Recording & learning helpers -------------------------------------

    def _record_iteration(self) -> None:
        """Store iteration results in the accumulated state."""
        qa_metrics: Dict[str, Any] = {
            "task_count": self.state.build_task_count,
            "success_count": self.state.build_success_count,
            "failure_count": self.state.build_failure_count,
        }

        iteration_result = {
            "iteration": self.state.iteration,
            "build": self.state.build_result_text,
            "learn": self.state.learn_output.model_dump() if self.state.learn_output else {},
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
            "evaluation_status": "continue",
            "termination_action": self.state.gate_recommendation,
        })

        # Write enriched cycle record to episodic memory for cross-run history.
        # Include what was dispatched, what was tried, and why QA failed —
        # not just "QA=FAIL" — so future iterations have real signal.
        try:
            from src.crewai_agents.tools import get_memory_store as _get_store_rec
            from src.framework.contracts import Episode
            from src.framework.types import EpisodeType as _EpType

            _rec_store = _get_store_rec()
            if _rec_store is not None:
                # Collect dispatch history if available
                dispatch_hist = []
                dispatch_count = 0
                try:
                    dispatch_hist = self._get_dispatch_history()
                    dispatch_count = self._get_dispatch_count()
                except Exception:
                    pass

                # Summarise what agents did this cycle
                dispatch_summary = []
                for d in dispatch_hist[:6]:
                    role = d.get("agent_role", "?")
                    task = d.get("task_summary", "?")
                    dispatch_summary.append(f"{role}: {task}")

                # Count open customer bugs for the summary
                bug_count = 0
                try:
                    from src.workspace_tools.file_tools import _get_open_feedback
                    bug_count = sum(1 for it in _get_open_feedback(exclude_cycle=0)
                                    if it.get("feedback_type") == "bug")
                except Exception:
                    pass

                # Build a rich summary
                parts = [
                    f"Iteration {self.state.iteration}",
                    f"Dispatched {dispatch_count} agents",
                ]
                if dispatch_summary:
                    parts.append("Actions: " + "; ".join(dispatch_summary))
                if bug_count:
                    parts.append(f"Customer bugs open: {bug_count}")

                _rec_store.ep_record(Episode(
                    agent_id="bml_flow",
                    episode_type=_EpType.LEARNING,
                    action=f"bml_cycle_iteration_{self.state.iteration}",
                    iteration=self.state.iteration,
                    success=dispatch_count > 0,
                    outcome={
                        "task_count": self.state.build_task_count,
                        "success_count": self.state.build_success_count,
                        "failure_count": self.state.build_failure_count,
                        "dispatch_count": dispatch_count,
                        "dispatches": dispatch_summary[:4],
                        "open_bugs": bug_count,
                    },
                    summary_text=". ".join(parts),
                ))
                logger.info("  Episodic memory: recorded enriched cycle metrics")
        except Exception as _ep_rec_exc:
            logger.warning(f"  Episodic memory write skipped: {_ep_rec_exc}")

        logger.info(
            f"\nIteration {self.state.iteration} complete: "
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

        Each call to ``kickoff()`` runs one BUILD -> MEASURE -> LEARN
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

