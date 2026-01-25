"""CrewAI Crews - Orchestration of agents and tasks."""
from typing import Dict, Any, List
from crewai import Crew, Task, Process, LLM
from src.crewai_agents.agents import (
    create_master_coordinator,
    create_data_strategist,
    create_product_strategist,
    create_outreach_strategist,
    get_llm
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


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
        4. Compile the 5 messages into a campaign plan
        5. Report on campaign readiness and personalization quality

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
        - Campaign quality metrics (avg personalization score, avg word count)
        - Predicted response rate based on past learnings
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


def create_autonomous_startup_crew(
    llm: LLM = None,
    verbose: int = 2
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
        iteration=1
    )

    # Create crew with hierarchical process
    crew = Crew(
        agents=[coordinator, data_strategist, product_strategist, outreach_strategist],
        tasks=tasks,
        process=Process.hierarchical,  # Coordinator delegates to specialists
        manager_llm=llm or get_llm(),
        verbose=verbose,
        memory=True,  # Enable memory across iterations
        cache=True,   # Cache results for efficiency
        max_rpm=10    # Rate limiting
    )

    logger.info("Crew created successfully")
    return crew


def run_build_measure_learn_cycle(
    iterations: int = 3,
    verbose: int = 2
) -> Dict[str, Any]:
    """Run multiple Build-Measure-Learn iterations.

    Args:
        iterations: Number of iterations to run
        verbose: Verbosity level

    Returns:
        Results from all iterations
    """
    logger.info(f"Starting {iterations} Build-Measure-Learn cycles")

    all_results = {
        'iterations': [],
        'metrics_evolution': [],
        'learnings': []
    }

    llm = get_llm()

    for i in range(1, iterations + 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {i}/{iterations}")
        logger.info(f"{'='*60}\n")

        # CREATE AGENTS (fresh each iteration to use updated memory)
        coordinator = create_master_coordinator(llm)
        data_strategist = create_data_strategist(llm)
        product_strategist = create_product_strategist(llm)
        outreach_strategist = create_outreach_strategist(llm)

        # BUILD PHASE
        logger.info("BUILD PHASE: Creating tasks...")
        build_tasks = create_build_phase_tasks(
            data_strategist,
            product_strategist,
            outreach_strategist,
            iteration=i
        )

        build_crew = Crew(
            agents=[data_strategist, product_strategist, outreach_strategist],
            tasks=build_tasks,
            process=Process.sequential,
            verbose=verbose,
            memory=True
        )

        logger.info("BUILD PHASE: Executing...")
        build_result = build_crew.kickoff()

        # MEASURE PHASE (simulated for now)
        logger.info("MEASURE PHASE: Collecting metrics...")
        # In real implementation, this would be actual user interactions
        # For now, simulate improving metrics
        base_response_rate = 0.15 + (i * 0.10)  # Improves each iteration
        base_meeting_rate = 0.05 + (i * 0.05)

        measure_result = {
            'response_rate': min(base_response_rate, 0.45),
            'meeting_rate': min(base_meeting_rate, 0.20),
            'total_sent': 5,
            'responses': int(5 * base_response_rate),
            'meetings': int(5 * base_meeting_rate)
        }

        # LEARN PHASE
        logger.info("LEARN PHASE: Extracting insights...")
        learn_task = create_learn_phase_task(
            coordinator,
            str(build_result),
            str(measure_result)
        )

        learn_crew = Crew(
            agents=[coordinator],
            tasks=[learn_task],
            process=Process.sequential,
            verbose=verbose,
            memory=True
        )

        learn_result = learn_crew.kickoff()

        # Store results
        iteration_result = {
            'iteration': i,
            'build': str(build_result),
            'measure': measure_result,
            'learn': str(learn_result)
        }

        all_results['iterations'].append(iteration_result)
        all_results['metrics_evolution'].append(measure_result)

        logger.info(f"\nIteration {i} complete:")
        logger.info(f"  Response rate: {measure_result['response_rate']:.1%}")
        logger.info(f"  Meeting rate: {measure_result['meeting_rate']:.1%}")

    logger.info(f"\n{'='*60}")
    logger.info("ALL ITERATIONS COMPLETE")
    logger.info(f"{'='*60}\n")

    return all_results
