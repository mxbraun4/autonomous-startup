"""CrewAI Crews - Orchestration of agents and tasks.

Provides both the legacy ``run_build_measure_learn_cycle`` function and the
new ``BuildMeasureLearnFlow`` (CrewAI Flows) for typed, event-driven BML
execution with evaluation gates and learning feedback.
"""

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.crewai_agents.runtime_env import (
    configure_runtime_environment,
    crewai_db_storage_path,
)

configure_runtime_environment()
from crewai import Crew, Task, Process, LLM
from crewai.flow.flow import Flow, start, listen, router

# Patch DB storage path to project-local writable directory so that CrewAI's
# internal kickoff_task_outputs.db doesn't land in a read-only system folder.
def _patch_crewai_db_storage_path() -> None:
    from pathlib import Path

    storage_path = crewai_db_storage_path()
    Path(storage_path).mkdir(parents=True, exist_ok=True)

    try:
        from crewai.utilities import paths as crewai_paths
        crewai_paths.db_storage_path = lambda: storage_path  # type: ignore[attr-defined]
    except Exception:
        pass

    try:
        from crewai.memory.storage import kickoff_task_outputs_storage
        kickoff_task_outputs_storage.db_storage_path = lambda: storage_path  # type: ignore[attr-defined]
    except Exception:
        pass

_patch_crewai_db_storage_path()

from src.crewai_agents.agents import (
    create_master_coordinator,
    create_data_strategist,
    create_product_strategist,
    create_outreach_strategist,
    get_llm,
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
    outreach_messages_sent: int = 0
    campaign_id: str = ""
    personalization_score: float = 0.0
    predicted_response_rate: float = 0.0
    predicted_meeting_rate: float = 0.0
    summary: str = ""


class MeasurementOutput(BaseModel):
    """Structured metrics collected during the MEASURE phase."""

    response_rate: float = 0.0
    meeting_rate: float = 0.0
    total_sent: int = 0
    responses: int = 0
    meetings: int = 0
    campaign_id: str = ""
    measurement_source: str = "no_signal"
    insights: List[str] = Field(default_factory=list)


class LearnPhaseOutput(BaseModel):
    """Structured output from the LEARN phase."""

    successes: List[str] = Field(default_factory=list)
    failures: List[str] = Field(default_factory=list)
    insights: List[str] = Field(default_factory=list)
    recommendations: Dict[str, str] = Field(default_factory=dict)
    predicted_improvement: float = 0.0
    summary: str = ""


# ---------------------------------------------------------------------------


def _campaign_id_for_iteration(iteration: int) -> str:
    """Deterministic outreach campaign id used for measurement."""
    return f"iteration_{iteration}"


def _normalize_rate(raw_value: float, has_percent_symbol: bool = False) -> float:
    """Normalize rate-like values to [0.0, 1.0]."""
    if has_percent_symbol or raw_value > 1.0:
        raw_value = raw_value / 100.0
    return max(0.0, min(raw_value, 1.0))


def _extract_rate(text: str, prefix: str) -> Optional[float]:
    """Extract a response/meeting rate from free-form text."""
    pattern = re.compile(
        rf"{prefix}[_\s-]*rate[^0-9]*(\d+(?:\.\d+)?)\s*(%)?",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None

    raw_value = float(match.group(1))
    has_percent_symbol = bool(match.group(2))
    return _normalize_rate(raw_value, has_percent_symbol)


def _extract_predicted_rates(build_result_text: str) -> Dict[str, Any]:
    """Fallback when no outreach logs exist.

    Returns zero-valued metrics with ``measurement_source='no_signal'``.
    We intentionally do NOT parse agent text for predicted rates because
    that would be self-referential: an agent's guess is not a measurement.
    """
    return {
        "response_rate": 0.0,
        "meeting_rate": 0.0,
        "measurement_source": "no_signal",
    }


def _collect_measure_metrics(iteration: int, build_result_text: str) -> Dict[str, Any]:
    """Collect MEASURE metrics from logged outreach, with deterministic fallback."""
    from src.crewai_agents.tools import get_database

    campaign_id = _campaign_id_for_iteration(iteration)
    db = get_database()

    history = db.get_outreach_history(campaign_id=campaign_id, limit=500)
    total_sent = len(history)

    responded_statuses = {
        "responded",
        "interested",
        "meeting",
        "meeting_scheduled",
        "meeting_booked",
    }
    meeting_statuses = {"meeting", "meeting_scheduled", "meeting_booked"}

    responses = sum(
        1 for record in history if str(record.get("status", "")).lower() in responded_statuses
    )
    meetings = sum(
        1 for record in history if str(record.get("status", "")).lower() in meeting_statuses
    )

    if total_sent > 0:
        return {
            "response_rate": responses / total_sent,
            "meeting_rate": meetings / total_sent,
            "total_sent": total_sent,
            "responses": responses,
            "meetings": meetings,
            "campaign_id": campaign_id,
            "measurement_source": "outreach_logs",
        }

    fallback = _extract_predicted_rates(build_result_text)
    fallback.update(
        {
            "total_sent": 0,
            "responses": 0,
            "meetings": 0,
            "campaign_id": campaign_id,
        }
    )
    return fallback


def create_build_phase_tasks(
    data_strategist,
    product_strategist,
    outreach_strategist,
    iteration: int = 1
) -> List[Task]:
    """Create tasks for the BUILD phase.

    Args:
        data_strategist: Data strategy agent
        product_strategist: Product strategy agent
        outreach_strategist: Outreach strategy agent
        iteration: Current iteration number

    Returns:
        List of BUILD phase tasks
    """

    data_task = Task(
        description=f'''[Iteration {iteration}] Analyze the current startup database for coverage gaps.

        Steps:
        1. Review current startup data coverage by sector
        2. Compare against VC investment interests and preferences
        3. Identify top 3 priority gaps based on:
           - Number of VCs interested in that sector
           - Current coverage percentage
           - Business impact
        4. For the highest priority gap:
           - Use scraper_tool to collect startup data for that sector
           - Use data_validator_tool to ensure quality
        5. Report results with metrics (gap identified, data collected, quality score)

        Focus on actionable gaps that will improve VC-startup matching quality.
        ''',
        agent=data_strategist,
        expected_output='''Data collection report including:
        - Top 3 priority gaps identified (sector, coverage %, VC interest %)
        - Data collection results for #1 priority (sector, count collected, quality score)
        - Impact assessment (how this improves matching)
        '''
    )

    product_task = Task(
        description=f'''[Iteration {iteration}] Identify platform improvement opportunities.

        Steps:
        1. Analyze user workflows and identify friction points
        2. Review most common user requests or needs
        3. Identify one high-impact tool or feature to build
        4. Use tool_builder_tool to create a detailed specification
        5. Report the spec with expected impact

        Prioritize tools that:
        - Automate repetitive tasks
        - Improve matching quality
        - Reduce time to value for users
        ''',
        agent=product_strategist,
        expected_output='''Product specification including:
        - Tool/feature name and description
        - Key features and capabilities
        - Implementation approach
        - Expected impact on user workflow
        '''
    )

    outreach_task = Task(
        description=f'''[Iteration {iteration}] Create and execute outreach campaign.

        Steps:
        1. Review learnings from past campaigns (if any) - what worked, what didn't
        2. Select 5 high-potential startups from the database
        3. For each startup:
           - Research recent news/achievements
           - Identify 1-2 matching VCs
           - Use content_generator_tool to create personalized message
        4. Use send_outreach_email for each message and set campaign_id to "{_campaign_id_for_iteration(iteration)}"
        5. If any responses are simulated/available, record them using record_outreach_response
        6. Report on campaign readiness and personalization quality using get_outreach_history for that campaign_id

        Best practices to apply:
        - Reference specific recent achievements
        - Keep messages under 150 words
        - Include clear, low-friction call-to-action
        - Mention specific VC matches
        ''',
        agent=outreach_strategist,
        expected_output='''Outreach campaign plan including:
        - 5 personalized messages (startup name, message text, personalization score)
        - Matched VCs for each startup
        - Campaign quality metrics (avg personalization score, avg word count, outreach_logged_count)
        - Campaign ID used for tracking
        - Predicted response rate based on past learnings (if available)
        '''
    )

    return [data_task, product_task, outreach_task]


def create_learn_phase_task(coordinator, build_results: str, measure_results: str) -> Task:
    """Create task for the LEARN phase.

    Args:
        coordinator: Master coordinator agent
        build_results: Results from BUILD phase
        measure_results: Results from MEASURE phase

    Returns:
        LEARN phase task
    """
    return Task(
        description=f'''Analyze results from this Build-Measure-Learn iteration and extract learnings.

        BUILD Phase Results:
        {build_results}

        MEASURE Phase Results:
        {measure_results}

        Steps:
        1. Review what was built/done in each area (data, product, outreach)
        2. Analyze the measured outcomes and metrics
        3. Identify what worked well (keep doing)
        4. Identify what didn't work (stop or change)
        5. Extract specific, actionable insights for next iteration
        6. Formulate recommendations for each team

        Focus on concrete, measurable insights that can drive improvement.
        ''',
        agent=coordinator,
        expected_output='''Learning report including:
        - Key successes (what worked and why)
        - Areas for improvement (what didn't work and why)
        - Specific insights (3-5 concrete learnings)
        - Recommendations for next iteration (one per team)
        - Predicted improvement in key metrics
        '''
    )


def _verbose_flag(verbose: int) -> bool:
    """Convert legacy integer verbosity to CrewAI v1.9 boolean flag."""
    return verbose > 0


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
    coordinator = create_master_coordinator(llm)
    data_strategist = create_data_strategist(llm)
    product_strategist = create_product_strategist(llm)
    outreach_strategist = create_outreach_strategist(llm)

    # Create initial tasks (will be updated per iteration)
    tasks = create_build_phase_tasks(
        data_strategist,
        product_strategist,
        outreach_strategist,
        iteration=1,
    )

    # NOTE: memory=False because we use our own five-tier UnifiedStore rather
    # than CrewAI's built-in memory (which requires an OpenAI API key for
    # embeddings). Our memory is injected into tools via set_memory_store().
    crew = Crew(
        agents=[coordinator, data_strategist, product_strategist, outreach_strategist],
        tasks=tasks,
        process=Process.hierarchical,
        manager_llm=llm or get_llm(),
        verbose=_verbose_flag(verbose),
        memory=False,
        cache=True,
        max_rpm=10,
    )

    logger.info("Crew created successfully")
    return crew


def run_build_measure_learn_cycle(
    iterations: int = 3,
    verbose: int = 2,
) -> Dict[str, Any]:
    """Run multiple Build-Measure-Learn iterations (legacy compatibility path).

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


# ---------------------------------------------------------------------------
# CrewAI Flow: Build-Measure-Learn with evaluation gates & learning feedback
# ---------------------------------------------------------------------------

class _FlowState(BaseModel):
    """Mutable state threaded through the BML Flow."""

    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:16])

    iteration: int = 0
    max_iterations: int = 3
    verbose: int = 2
    llm: Any = None

    # Per-iteration outputs
    build_result_text: str = ""
    build_output: Optional[BuildPhaseOutput] = None
    build_task_count: int = 0
    build_success_count: int = 0
    build_failure_count: int = 0
    measure_output: Optional[MeasurementOutput] = None
    learn_output: Optional[LearnPhaseOutput] = None

    # Gate recommendation from the EVALUATE phase
    gate_recommendation: str = "continue"  # continue / pause / rollback / stop

    # Accumulated results across all iterations
    iterations_results: List[Dict[str, Any]] = Field(default_factory=list)
    metrics_evolution: List[Dict[str, Any]] = Field(default_factory=list)
    learnings: List[str] = Field(default_factory=list)

    # Learning feedback: procedure hints injected into next BUILD
    procedure_hints: str = ""

    model_config = {"arbitrary_types_allowed": True}


class BuildMeasureLearnFlow(Flow[_FlowState]):
    """Event-driven Build-Measure-Learn cycle using CrewAI Flows.

    Each call to :meth:`kickoff` runs one complete BUILD -> MEASURE ->
    EVALUATE -> LEARN pipeline.  :meth:`run` loops over multiple iterations,
    feeding learnings from one iteration into the next.
    """

    def __init__(self, max_iterations: int = 3, verbose: int = 2) -> None:
        super().__init__(
            max_iterations=max_iterations,
            verbose=verbose,
            llm=get_llm(),
        )

    # -- helpers ----------------------------------------------------------

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
        """Lazy import of PolicyUpdater."""
        from src.framework.learning import PolicyUpdater
        return PolicyUpdater()

    # -- BUILD phase ------------------------------------------------------

    @start()
    def build(self):
        """Execute the BUILD phase: data collection, product spec, outreach."""
        self.state.iteration += 1
        i = self.state.iteration
        llm = self.state.llm

        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {i}/{self.state.max_iterations}")
        logger.info(f"{'='*60}\n")
        logger.info("BUILD PHASE: Creating tasks...")

        data_strategist = create_data_strategist(llm)
        product_strategist = create_product_strategist(llm)
        outreach_strategist = create_outreach_strategist(llm)

        # Inject learning hints from previous iteration
        extra_context = ""
        if self.state.procedure_hints:
            extra_context = (
                f"\n\n[Previous iteration learnings]\n{self.state.procedure_hints}\n"
            )

        build_tasks = create_build_phase_tasks(
            data_strategist,
            product_strategist,
            outreach_strategist,
            iteration=i,
        )

        if extra_context:
            build_tasks[-1].description += extra_context

        build_crew = Crew(
            agents=[data_strategist, product_strategist, outreach_strategist],
            tasks=build_tasks,
            process=Process.sequential,
            verbose=_verbose_flag(self.state.verbose),
            memory=False,
        )

        logger.info("BUILD PHASE: Executing...")
        task_count = len(build_tasks)
        success_count = 0
        failure_count = 0
        try:
            crew_output = build_crew.kickoff()
            # CrewAI v1.9 CrewOutput exposes per-task results
            if hasattr(crew_output, "tasks_output"):
                for to in crew_output.tasks_output:
                    status = getattr(to, "status", "success")
                    if status == "success" or status is None:
                        success_count += 1
                    else:
                        failure_count += 1
            else:
                # Assume all succeeded if no per-task info
                success_count = task_count
        except Exception as exc:
            logger.warning(f"BUILD PHASE failed: {exc}")
            crew_output = None
            failure_count = task_count

        self.state.build_task_count = task_count
        self.state.build_success_count = success_count
        self.state.build_failure_count = failure_count
        self.state.build_result_text = str(crew_output) if crew_output else ""
        if crew_output and hasattr(crew_output, "pydantic") and crew_output.pydantic is not None:
            self.state.build_output = crew_output.pydantic
        else:
            self.state.build_output = None

    # -- MEASURE phase ----------------------------------------------------

    @listen(build)
    def measure(self):
        """Collect MEASURE metrics from outreach logs or parsed predictions."""
        logger.info("MEASURE PHASE: Collecting metrics from outreach artifacts...")

        raw = _collect_measure_metrics(
            self.state.iteration, self.state.build_result_text,
        )

        self.state.measure_output = MeasurementOutput(
            response_rate=raw["response_rate"],
            meeting_rate=raw["meeting_rate"],
            total_sent=raw.get("total_sent", 0),
            responses=raw.get("responses", 0),
            meetings=raw.get("meetings", 0),
            campaign_id=raw.get("campaign_id", ""),
            measurement_source=raw.get("measurement_source", "no_signal"),
        )

    # -- EVALUATE gate ----------------------------------------------------

    @listen(measure)
    def evaluate(self):
        """Run framework evaluation gates against actual cycle metrics."""
        logger.info("EVALUATE: Checking gates...")

        m = self.state.measure_output
        assert m is not None

        self.state.gate_recommendation = "continue"

        try:
            from src.framework.contracts import CycleMetrics
            metrics = CycleMetrics(
                cycle_id=self.state.iteration,
                task_count=self.state.build_task_count,
                success_count=self.state.build_success_count,
                failure_count=self.state.build_failure_count,
                domain_metrics={
                    "response_rate": m.response_rate,
                    "meeting_rate": m.meeting_rate,
                    "total_sent": m.total_sent,
                    "measurement_source": m.measurement_source,
                },
            )
            evaluator = self._get_evaluator()
            result = evaluator.evaluate(metrics)
            self.state.gate_recommendation = result.recommended_action
            logger.info(
                f"  Gate result: {result.overall_status} -> {result.recommended_action}"
            )

            # Run policy updater on gate failures
            if result.overall_status != "pass":
                try:
                    pu = self._get_policy_updater()
                    patches = pu.propose_patches(result, {})
                    if patches:
                        pu.apply_patches({}, patches, {})
                        logger.info(f"  PolicyUpdater applied {len(patches)} patches")
                except Exception as exc:
                    logger.warning(f"  PolicyUpdater skipped: {exc}")

        except Exception as exc:
            logger.warning(f"  Evaluation skipped: {exc}")

    # -- LEARN phase ------------------------------------------------------

    @listen(evaluate)
    def learn(self):
        """Execute the LEARN phase and feed results back into next iteration."""
        logger.info("LEARN PHASE: Extracting insights...")

        llm = self.state.llm
        coordinator = create_master_coordinator(llm)

        learn_task = create_learn_phase_task(
            coordinator,
            self.state.build_result_text,
            str(self.state.measure_output.model_dump() if self.state.measure_output else {}),
        )

        learn_crew = Crew(
            agents=[coordinator],
            tasks=[learn_task],
            process=Process.sequential,
            verbose=_verbose_flag(self.state.verbose),
            memory=False,
        )

        learn_result = learn_crew.kickoff()

        if hasattr(learn_result, "pydantic") and learn_result.pydantic is not None:
            self.state.learn_output = learn_result.pydantic
        else:
            self.state.learn_output = LearnPhaseOutput(summary=str(learn_result))

        self._apply_learning_feedback()
        self._record_iteration()

    # -- Recording & learning helpers -------------------------------------

    def _record_iteration(self) -> None:
        """Store iteration results in the accumulated state."""
        m = self.state.measure_output
        measure_dict: Dict[str, Any] = m.model_dump() if m else {}

        iteration_result = {
            "iteration": self.state.iteration,
            "build": self.state.build_result_text,
            "measure": measure_dict,
            "learn": self.state.learn_output.model_dump() if self.state.learn_output else {},
        }

        self.state.iterations_results.append(iteration_result)
        self.state.metrics_evolution.append(measure_dict)

        if m:
            logger.info(f"\nIteration {self.state.iteration} complete:")
            logger.info(f"  Response rate: {m.response_rate:.1%}")
            logger.info(f"  Meeting rate: {m.meeting_rate:.1%}")

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

    # -- Public entry point -----------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Execute the full multi-iteration BML flow.

        Each call to ``kickoff()`` runs one BUILD -> MEASURE -> EVALUATE ->
        LEARN pipeline.  We loop externally so that learnings from iteration
        *N* feed into iteration *N+1* via ``procedure_hints``.

        Returns:
            Aggregated results dict compatible with the legacy interface.
        """
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

        return {
            "iterations": self.state.iterations_results,
            "metrics_evolution": self.state.metrics_evolution,
            "learnings": self.state.learnings,
        }
