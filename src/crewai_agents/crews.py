"""CrewAI Crews - Orchestration of agents and tasks.

Provides both the public ``run_build_measure_learn_cycle`` function and the
``BuildMeasureLearnFlow`` (CrewAI Flows) for typed, event-driven BML
execution with evaluation gates and learning feedback.
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
    create_developer_agent,
    create_reviewer_agent,
    create_product_strategist,
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
    summary: str = ""


class MeasurementOutput(BaseModel):
    """Structured metrics collected during the MEASURE phase."""

    response_rate: float = 0.0
    meeting_rate: float = 0.0
    total_sent: int = 0
    responses: int = 0
    meetings: int = 0
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


def _collect_measure_metrics(
    iteration: int,
    build_result_text: str,
) -> Dict[str, Any]:
    """Collect MEASURE metrics for this iteration.

    Outreach has been removed; return a no-signal baseline.  The evaluator
    already handles this gracefully.
    """
    del build_result_text
    return {
        "response_rate": 0.0,
        "meeting_rate": 0.0,
        "total_sent": 0,
        "responses": 0,
        "meetings": 0,
        "measurement_source": "no_signal",
    }


def create_build_phase_tasks(
    developer_agent,
    product_strategist,
    iteration: int = 1,
    reviewer_agent: Any = None,
) -> List[Task]:
    """Create tasks for the BUILD phase.

    Args:
        developer_agent: Developer/implementation agent
        product_strategist: Product strategy agent
        iteration: Current iteration number
        reviewer_agent: Optional QA reviewer agent

    Returns:
        List of BUILD phase tasks
    """

    product_task = Task(
        description=f'''[Iteration {iteration}] Define product improvement and provide developer feedback.

        Steps:
        1. Analyze user workflows and identify friction points
        2. Review prior team insights (use get_team_insights) to see what changed recently
        3. Identify one high-impact tool or feature improvement to prioritize next
        4. Use tool_builder_tool to create a detailed specification / acceptance criteria
        5. Use share_insight to send implementation feedback and priorities to the Developer Agent
        6. Report the spec plus expected user impact and handoff notes

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

    developer_task = Task(
        description=f'''[Iteration {iteration}] Implement or refine one high-impact platform capability.

        Steps:
        1. Use get_team_insights to review product feedback and prior learnings for this cycle
        2. Identify one concrete implementation task with highest expected product impact
        3. Use available build/registration tools to implement or refine a tool/feature incrementally
        4. Validate the resulting behavior (execution path, output quality, or analytics signal)
        5. Use share_insight to report implementation status, tradeoffs, and any blockers back to the team

        Focus on small, testable improvements that improve matching quality, explainability,
        operator workflow speed, or system reliability.
        ''',
        agent=developer_agent,
        context=[product_task],
        expected_output='''Developer implementation report including:
        - Capability/tool changed (name and purpose)
        - What was implemented or refined this iteration
        - Validation/test evidence or execution results
        - Risks, limitations, and next implementation steps
        '''
    )

    reviewer_task: Optional[Task] = None
    if reviewer_agent is not None:
        reviewer_task = Task(
            description=f'''[Iteration {iteration}] Perform QA review on developer output before coordinator review.

        Steps:
        1. Use get_team_insights to review the latest product/developer notes for this cycle
        2. Run run_quality_checks_tool to check Python syntax and execute the QA test path
        3. If checks fail, summarize exact blocking defects for the Developer Agent
        4. Use share_insight to publish QA status and blocking items
        5. Report a strict PASS/FAIL recommendation for this iteration's implementation

        You are the quality gate. Do not approve broken code.
        ''',
            agent=reviewer_agent,
            context=[developer_task],
            expected_output='''QA review report including:
        - QA gate status (PASS/FAIL)
        - Syntax check results summary
        - Test execution results summary
        - Blocking defects (if any)
        - Actionable fix instructions for the Developer Agent
        '''
        )

    tasks = [product_task, developer_task]
    if reviewer_task is not None:
        tasks.append(reviewer_task)
    return tasks


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
        1. Review what was built/done in each area (developer implementation, product strategy)
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
        - Recommendations for next iteration (coordinator, product, developer as applicable)
        - Predicted improvement in key metrics
        '''
    )


def _verbose_flag(verbose: int) -> bool:
    """Convert integer verbosity to CrewAI v1.9 boolean flag."""
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

    # Create initial tasks (will be updated per iteration)
    tasks = create_build_phase_tasks(
        developer_agent,
        product_strategist,
        iteration=1,
        reviewer_agent=reviewer_agent,
    )

    # NOTE: memory=False because we use our own five-tier UnifiedStore rather
    # than CrewAI's built-in memory (which requires an OpenAI API key for
    # embeddings). Our memory is injected into tools via set_memory_store().
    crew = Crew(
        agents=[coordinator, product_strategist, developer_agent, reviewer_agent],
        tasks=tasks,
        process=Process.hierarchical,
        manager_llm=coordinator_llm,
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
    enable_dynamic_agent_factory: bool = True
    max_agents_per_cycle: int = 6

    # Per-iteration outputs
    build_result_text: str = ""
    build_output: Optional[BuildPhaseOutput] = None
    build_task_count: int = 0
    build_success_count: int = 0
    build_failure_count: int = 0
    qa_passed: bool = True
    qa_result: Dict[str, Any] = Field(default_factory=dict)
    measure_output: Optional[MeasurementOutput] = None
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

    model_config = {"arbitrary_types_allowed": True}


class BuildMeasureLearnFlow(Flow[_FlowState]):
    """Event-driven Build-Measure-Learn cycle using CrewAI Flows.

    Each call to :meth:`kickoff` runs one complete BUILD -> MEASURE ->
    EVALUATE -> LEARN pipeline.  :meth:`run` loops over multiple iterations,
    feeding learnings from one iteration into the next.
    """

    def __init__(
        self,
        max_iterations: int = 3,
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

    def _prompt_override(self, key: str) -> str:
        overrides = dict(self.state.prompt_overrides or {})
        return str(overrides.get(key, "")).strip()

    def _run_quality_gate(self) -> Dict[str, Any]:
        """Run deterministic QA checks and return parsed JSON output."""
        from src.crewai_agents.tools import run_quality_checks_tool

        try:
            raw = run_quality_checks_tool.run(
                paths_csv="src,scripts",
                pytest_targets_csv="tests/test_crewai_integration.py",
                run_pytest=True,
                timeout_seconds=120,
            )
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {
                "status": "failed",
                "qa_gate_passed": False,
                "reason": "qa_tool_non_object_response",
                "raw": raw,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "qa_gate_passed": False,
                "reason": "qa_tool_exception",
                "error": str(exc),
            }

    def _qa_passed(self) -> bool:
        return bool((self.state.qa_result or {}).get("qa_gate_passed"))

    # -- BUILD phase ------------------------------------------------------

    @start()
    def build(self):
        """Execute the BUILD phase: product feedback + developer implementation."""
        self.state.iteration += 1
        i = self.state.iteration
        shared_llm = self.state.llm
        developer_llm = shared_llm or get_llm("developer")
        reviewer_llm = shared_llm or get_llm("reviewer")
        product_llm = shared_llm or get_llm("product")
        self.state.qa_passed = True
        self.state.qa_result = {}

        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {i}/{self.state.max_iterations}")
        logger.info(f"{'='*60}\n")
        logger.info("BUILD PHASE: Creating tasks...")

        developer_agent = create_developer_agent(
            developer_llm,
            prompt_override=self._prompt_override("developer"),
        )
        reviewer_agent = create_reviewer_agent(
            reviewer_llm,
            prompt_override=self._prompt_override("reviewer"),
        )
        product_strategist = create_product_strategist(
            product_llm,
            prompt_override=self._prompt_override("product"),
        )
        # Inject learning hints from previous iteration
        extra_context = ""
        if self.state.procedure_hints:
            extra_context = (
                f"\n\n[Previous iteration learnings]\n{self.state.procedure_hints}\n"
            )

        # Inject consensus memory (team knowledge board) into every task
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

        build_tasks = create_build_phase_tasks(
            developer_agent,
            product_strategist,
            iteration=i,
            reviewer_agent=reviewer_agent,
        )

        if extra_context:
            for task in build_tasks:
                task.description += extra_context

        build_crew = Crew(
            agents=[product_strategist, developer_agent, reviewer_agent],
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

        # Deterministic QA gate: enforce checks before coordinator review.
        self.state.qa_result = self._run_quality_gate()
        self.state.qa_passed = self._qa_passed()
        if not self.state.qa_passed:
            logger.warning("QA gate failed; requesting developer remediation before coordinator review")

            qa_findings_json = json.dumps(self.state.qa_result, indent=2, ensure_ascii=True)
            fix_task = Task(
                description=f'''[Iteration {i}] QA remediation required before coordinator review.

            QA gate findings:
            {qa_findings_json}

            Steps:
            1. Identify the root cause(s) of the QA failures
            2. Implement the minimal fix required to pass QA
            3. Share a concise fix summary and remaining risks via share_insight

            Do not start new feature work. Fix only the blocking defects.
            ''',
                agent=developer_agent,
                expected_output='''QA remediation summary including:
            - Root cause(s)
            - Fix applied
            - Remaining risks (if any)
            '''
            )

            recheck_task = Task(
                description=f'''[Iteration {i}] Re-run QA quality gate after developer remediation.

            Steps:
            1. Run run_quality_checks_tool again
            2. Share PASS/FAIL status with blocking issues (if any)
            3. State whether this iteration can proceed to coordinator review
            ''',
                agent=reviewer_agent,
                context=[fix_task],
                expected_output='''QA recheck result with PASS/FAIL and blocking defects if any.'''
            )

            remediation_crew = Crew(
                agents=[developer_agent, reviewer_agent],
                tasks=[fix_task, recheck_task],
                process=Process.sequential,
                verbose=_verbose_flag(self.state.verbose),
                memory=False,
            )
            try:
                remediation_output = remediation_crew.kickoff()
                if remediation_output:
                    extra = str(remediation_output)
                    if crew_output:
                        self.state.build_result_text = f"{self.state.build_result_text}\n\n[QA_REMEDIATION]\n{extra}"
                    else:
                        self.state.build_result_text = f"[QA_REMEDIATION]\n{extra}"
            except Exception as exc:
                logger.warning(f"QA remediation sub-crew failed: {exc}")

            self.state.qa_result = self._run_quality_gate()
            self.state.qa_passed = self._qa_passed()

        self.state.build_task_count = task_count
        self.state.build_success_count = success_count
        if not self.state.qa_passed:
            failure_count = max(1, failure_count)
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

    # -- MEASURE phase ----------------------------------------------------

    @listen(build)
    def measure(self):
        """Collect MEASURE metrics from outreach logs or parsed predictions."""
        logger.info("MEASURE PHASE: Collecting metrics from available artifacts...")

        raw = _collect_measure_metrics(
            self.state.iteration,
            self.state.build_result_text,
        )

        self.state.measure_output = MeasurementOutput(
            response_rate=raw["response_rate"],
            meeting_rate=raw["meeting_rate"],
            total_sent=raw.get("total_sent", 0),
            responses=raw.get("responses", 0),
            meetings=raw.get("meetings", 0),
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
        if not self.state.qa_passed:
            self.state.gate_recommendation = "pause"

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
                    "qa_gate_passed": bool(self.state.qa_passed),
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

        if not self.state.qa_passed:
            self.state.gate_recommendation = "pause"

    # -- LEARN phase ------------------------------------------------------

    @listen(evaluate)
    def learn(self):
        """Execute the LEARN phase and feed results back into next iteration."""
        logger.info("LEARN PHASE: Extracting insights...")

        if not self.state.qa_passed:
            logger.warning("LEARN PHASE blocked: QA gate did not pass; skipping coordinator")
            qa = dict(self.state.qa_result or {})
            syntax = dict(qa.get("syntax") or {})
            pytest_result = dict(qa.get("pytest") or {})
            failures: List[str] = []
            if not bool(qa.get("qa_gate_passed")):
                failures.append("QA gate failed")
            if not bool(syntax.get("syntax_ok", True)):
                failures.append(
                    f"Syntax errors: {int(syntax.get('syntax_error_count', 0))}"
                )
            pytest_status = str(pytest_result.get("pytest_status", "unknown"))
            if pytest_status not in {"passed", "disabled", "no_targets", "skipped_nested_pytest"}:
                failures.append(f"Pytest status: {pytest_status}")

            self.state.learn_output = LearnPhaseOutput(
                successes=[],
                failures=failures or ["QA gate failed"],
                insights=[
                    "Coordinator review skipped because QA did not pass",
                    "Developer remediation is required before strategic learning/decision steps",
                ],
                recommendations={
                    "developer": "Fix blocking QA defects reported in QA_GATE and rerun checks before continuing.",
                    "reviewer": "Re-run syntax/test checks after developer fixes and publish PASS/FAIL evidence.",
                },
                predicted_improvement=0.0,
                summary="Coordinator skipped due to QA gate failure. QA must pass before strategic review.",
            )
            self._apply_learning_feedback()
            self._record_iteration()
            return

        coordinator_llm = self.state.llm or get_llm("coordinator")
        coordinator = create_master_coordinator(coordinator_llm)

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
            "quality_assurance": {
                "qa_passed": bool(self.state.qa_passed),
                "qa_result": dict(self.state.qa_result or {}),
            },
            "autonomy": {
                "prompt_overrides": dict(self.state.prompt_overrides),
            },
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
        self._update_prompt_overrides(lo)

        # Write insights and recommendations to consensus memory so the
        # team knowledge board grows across iterations.
        try:
            from src.crewai_agents.tools import get_memory_store
            from src.framework.contracts import ConsensusEntry

            _learn_store = get_memory_store()
            if _learn_store is not None:
                iteration = self.state.iteration
                for idx, insight in enumerate(lo.insights):
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
            if len(text) > 1200:
                updated[key] = text[-1200:]

        self.state.prompt_overrides = updated

    # -- Public entry point -----------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Execute the full multi-iteration BML flow.

        Each call to ``kickoff()`` runs one BUILD -> MEASURE -> EVALUATE ->
        LEARN pipeline.  We loop externally so that learnings from iteration
        *N* feed into iteration *N+1* via ``procedure_hints``.

        Returns:
            Aggregated results dict matching the existing public interface.
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
