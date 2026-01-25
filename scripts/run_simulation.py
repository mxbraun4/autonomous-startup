"""Main script to run the autonomous startup simulation."""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.client import LLMClient
from src.memory import SemanticMemory, EpisodicMemory, ProceduralMemory
from src.agents.master_planner import MasterPlanner
from src.agents.planners import (
    DataStrategyPlanner,
    ProductStrategyPlanner,
    OutreachStrategyPlanner
)
from src.agents.actors import ScraperActor, ToolBuilderActor, ContentGeneratorActor
from src.simulation import SimulatedStartup, SimulatedVC
from src.utils.config import settings
from src.utils.logging import setup_logging, get_logger

setup_logging(settings.log_level)
logger = get_logger(__name__)


def load_json_file(path: str) -> list:
    """Load JSON file.

    Args:
        path: Path to file

    Returns:
        List of items
    """
    with open(path, 'r') as f:
        return json.load(f)


def simulate_interactions(
    startups: list,
    vcs: list,
    outreach_planner: OutreachStrategyPlanner,
    content_generator: ContentGeneratorActor
) -> dict:
    """Simulate outreach campaign results.

    Args:
        startups: List of SimulatedStartup instances
        vcs: List of SimulatedVC instances
        outreach_planner: Outreach planner
        content_generator: Content generator actor

    Returns:
        Metrics dict
    """
    logger.info("Simulating startup interactions...")

    # Get generated outreach messages
    messages = content_generator.get_generated_messages()

    if not messages:
        logger.warning("No outreach messages generated")
        return {
            'total_sent': 0,
            'responses': 0,
            'interested': 0,
            'meetings': 0,
            'response_rate': 0.0,
            'meeting_rate': 0.0
        }

    # Simulate sending to startups
    responses = []
    for msg in messages:
        # Pick a random startup (or match by sector)
        startup = startups[len(responses) % len(startups)]

        response = startup.receive_outreach(msg)
        responses.append(response)

        logger.debug(
            f"Startup {startup.profile.get('name')}: "
            f"{response.get('response', 'no_response')}"
        )

    # Calculate metrics
    total_sent = len(messages)
    responded = sum(1 for r in responses if r['response'] != 'no_response')
    interested = sum(1 for r in responses if r['response'] == 'interested')
    meetings = sum(1 for r in responses if r.get('wants_meeting', False))

    response_rate = responded / total_sent if total_sent > 0 else 0.0
    meeting_rate = meetings / total_sent if total_sent > 0 else 0.0

    return {
        'total_sent': total_sent,
        'responses': responded,
        'interested': interested,
        'meetings': meetings,
        'response_rate': response_rate,
        'meeting_rate': meeting_rate,
        'overall_success': response_rate > 0.20
    }


def display_iteration_results(iteration: int, metrics: dict) -> None:
    """Display results for an iteration.

    Args:
        iteration: Iteration number
        metrics: Metrics dict
    """
    print(f"\n{'='*60}")
    print(f"ITERATION {iteration} RESULTS")
    print(f"{'='*60}")
    print(f"Outreach Campaign:")
    print(f"  - Messages sent: {metrics.get('total_sent', 0)}")
    print(f"  - Responses: {metrics.get('responses', 0)}")
    print(f"  - Interested: {metrics.get('interested', 0)}")
    print(f"  - Meeting requests: {metrics.get('meetings', 0)}")
    print(f"\nMetrics:")
    print(f"  - Response rate: {metrics.get('response_rate', 0):.1%}")
    print(f"  - Meeting rate: {metrics.get('meeting_rate', 0):.1%}")
    print(f"{'='*60}\n")


def run_simulation(iterations: int = 3):
    """Run the complete simulation.

    Args:
        iterations: Number of Build-Measure-Learn iterations
    """
    logger.info("Initializing autonomous startup simulation...")

    # Initialize LLM client (mock mode)
    llm_client = LLMClient(mock_mode=settings.mock_mode)

    # Initialize memory systems
    semantic_mem = SemanticMemory()
    episodic_mem = EpisodicMemory(settings.episodic_db_path)
    procedural_mem = ProceduralMemory(settings.procedural_json_path)

    memory_system = {
        'semantic': semantic_mem,
        'episodic': episodic_mem,
        'procedural': procedural_mem
    }

    logger.info(f"Memory systems initialized:")
    logger.info(f"  - Semantic: {semantic_mem.size()} documents")
    logger.info(f"  - Episodic: {len(episodic_mem.get_recent(limit=100))} episodes")
    logger.info(f"  - Procedural: {len(procedural_mem.get_all_workflows())} workflows")

    # Initialize Master Planner
    master_planner = MasterPlanner(llm_client, memory_system)

    # Initialize specialized planners
    data_planner = DataStrategyPlanner(llm_client, memory_system)
    product_planner = ProductStrategyPlanner(llm_client, memory_system)
    outreach_planner = OutreachStrategyPlanner(llm_client, memory_system)

    master_planner.add_planners([data_planner, product_planner, outreach_planner])

    # Initialize actor agents
    scraper = ScraperActor(llm_client, memory_system)
    tool_builder = ToolBuilderActor(llm_client, memory_system)
    content_gen = ContentGeneratorActor(llm_client, memory_system)

    data_planner.add_actors([scraper])
    product_planner.add_actors([tool_builder])
    outreach_planner.add_actors([content_gen])

    logger.info("Agent hierarchy initialized")

    # Load simulated external actors
    startup_profiles = load_json_file(settings.seed_startups_path)
    vc_profiles = load_json_file(settings.seed_vcs_path)

    startups = [SimulatedStartup(s) for s in startup_profiles]
    vcs = [SimulatedVC(v) for v in vc_profiles]

    logger.info(f"Simulated ecosystem: {len(startups)} startups, {len(vcs)} VCs")

    print("\n" + "="*60)
    print("AUTONOMOUS STARTUP MULTI-AGENT SIMULATION")
    print("="*60)
    print(f"Iterations: {iterations}")
    print(f"Mock Mode: {settings.mock_mode}")
    print(f"Startups: {len(startups)}")
    print(f"VCs: {len(vcs)}")
    print("="*60 + "\n")

    # Run Build-Measure-Learn cycles
    all_metrics = []

    for iteration in range(1, iterations + 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"STARTING ITERATION {iteration}")
        logger.info(f"{'='*60}")

        # Get metrics from previous iteration for learning
        prev_metrics = all_metrics[-1] if all_metrics else None

        # Run Build-Measure-Learn cycle
        cycle_results = master_planner.run_build_measure_learn_cycle(
            iteration=iteration,
            metrics=prev_metrics
        )

        # Simulate interactions to measure results
        metrics = simulate_interactions(
            startups,
            vcs,
            outreach_planner,
            content_gen
        )

        # Record campaign results
        outreach_planner.record_campaign_results(
            campaign_id=f"campaign_{iteration}",
            results=metrics,
            iteration=iteration
        )

        all_metrics.append(metrics)

        # Display results
        display_iteration_results(iteration, metrics)

    # Display final summary
    print("\n" + "="*60)
    print("SIMULATION COMPLETE - FINAL SUMMARY")
    print("="*60)
    print("\nPerformance Evolution:")
    for i, metrics in enumerate(all_metrics, 1):
        print(
            f"  Iteration {i}: "
            f"Response rate {metrics['response_rate']:.1%}, "
            f"Meeting rate {metrics['meeting_rate']:.1%}"
        )

    print("\nMemory Systems Final State:")
    print(f"  - Semantic: {semantic_mem.size()} documents")
    print(f"  - Episodic: {len(episodic_mem.get_recent(limit=100))} episodes")
    print(f"  - Procedural: {len(procedural_mem.get_all_workflows())} workflows")

    print("\nLearning Insights:")
    insights = episodic_mem.get_learning_insights('outreach_campaign')
    print(f"  - Total campaigns: {insights['total']}")
    print(f"  - Success rate: {insights['success_rate']:.1%}")

    print("="*60 + "\n")

    # Close database connection
    episodic_mem.close()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run autonomous startup simulation"
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=3,
        help='Number of Build-Measure-Learn iterations (default: 3)'
    )

    args = parser.parse_args()

    run_simulation(iterations=args.iterations)


if __name__ == "__main__":
    main()
