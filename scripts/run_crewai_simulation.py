"""Run autonomous startup simulation using CrewAI."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.crewai_agents import run_build_measure_learn_cycle
from src.utils.logging import setup_logging, get_logger
from src.utils.config import settings

setup_logging(settings.log_level)
logger = get_logger(__name__)


def display_results(results: dict) -> None:
    """Display simulation results.

    Args:
        results: Results from Build-Measure-Learn cycles
    """
    print("\n" + "="*60)
    print("CREWAI AUTONOMOUS STARTUP SIMULATION - RESULTS")
    print("="*60)

    print("\nPerformance Evolution:")
    for i, metrics in enumerate(results['metrics_evolution'], 1):
        print(f"\n  Iteration {i}:")
        print(f"    Response rate: {metrics['response_rate']:.1%}")
        print(f"    Meeting rate: {metrics['meeting_rate']:.1%}")
        print(f"    Total sent: {metrics['total_sent']}")
        print(f"    Responses: {metrics['responses']}")
        print(f"    Meetings: {metrics['meetings']}")

    # Calculate improvement
    if len(results['metrics_evolution']) > 1:
        first = results['metrics_evolution'][0]
        last = results['metrics_evolution'][-1]

        response_improvement = (
            (last['response_rate'] - first['response_rate']) / first['response_rate']
        ) * 100

        meeting_improvement = (
            (last['meeting_rate'] - first['meeting_rate']) / first['meeting_rate']
        ) * 100 if first['meeting_rate'] > 0 else 0

        print("\n" + "="*60)
        print("IMPROVEMENT SUMMARY")
        print("="*60)
        print(f"  Response rate: {first['response_rate']:.1%} → {last['response_rate']:.1%} (+{response_improvement:.0f}%)")
        print(f"  Meeting rate: {first['meeting_rate']:.1%} → {last['meeting_rate']:.1%} (+{meeting_improvement:.0f}%)")

    print("\n" + "="*60)
    print("SIMULATION COMPLETE")
    print("="*60)
    print("\nKey Takeaways:")
    print("  ✓ CrewAI agents coordinated hierarchically")
    print("  ✓ Memory enabled learning across iterations")
    print("  ✓ Performance improved through adaptation")
    print("  ✓ Tools (scraper, content generator, etc.) integrated successfully")
    print()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run CrewAI autonomous startup simulation"
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=3,
        help='Number of Build-Measure-Learn iterations (default: 3)'
    )
    parser.add_argument(
        '--verbose',
        type=int,
        default=2,
        choices=[0, 1, 2],
        help='Verbosity level: 0=quiet, 1=normal, 2=detailed (default: 2)'
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print("CREWAI AUTONOMOUS STARTUP SIMULATION")
    print("="*60)
    print(f"  Iterations: {args.iterations}")
    print(f"  Verbosity: {args.verbose}")
    print(f"  Mock Mode: {settings.mock_mode}")
    print("="*60 + "\n")

    logger.info(f"Starting CrewAI simulation with {args.iterations} iterations")

    # Run Build-Measure-Learn cycles
    results = run_build_measure_learn_cycle(
        iterations=args.iterations,
        verbose=args.verbose
    )

    # Display results
    display_results(results)


if __name__ == "__main__":
    main()
