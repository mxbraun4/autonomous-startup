"""Run pre-defined demo scenarios."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.simulation.scenarios import run_scenario
from src.utils.logging import setup_logging, get_logger
from src.utils.config import settings

setup_logging(settings.log_level)
logger = get_logger(__name__)


def display_scenario_info(scenario_data: dict) -> None:
    """Display scenario information.

    Args:
        scenario_data: Scenario data dict
    """
    print("\n" + "="*60)
    print(f"SCENARIO: {scenario_data['scenario'].upper().replace('_', ' ')}")
    print("="*60)
    print(f"\nDescription:")
    print(f"  {scenario_data['description']}")

    if 'steps' in scenario_data:
        print(f"\nSteps:")
        for i, step in enumerate(scenario_data['steps'], 1):
            print(f"  {i}. {step}")

    if 'expected_outcome' in scenario_data:
        print(f"\nExpected Outcome:")
        print(f"  {scenario_data['expected_outcome']}")

    if 'expected_metrics' in scenario_data:
        print(f"\nExpected Metrics:")
        for iteration, metrics in scenario_data['expected_metrics'].items():
            print(f"  {iteration}:")
            for key, value in metrics.items():
                if isinstance(value, float):
                    print(f"    - {key}: {value:.1%}")
                else:
                    print(f"    - {key}: {value}")

    if 'components' in scenario_data:
        print(f"\nComponents Involved:")
        for component in scenario_data['components']:
            print(f"  - {component}")

    print("="*60 + "\n")


def scenario_1_data_collection():
    """Run data collection scenario."""
    scenario_data = run_scenario('data_collection')
    display_scenario_info(scenario_data)

    print("Simulating data collection process...\n")

    # Simulate the scenario steps
    print("Step 1: Analyzing current data distribution...")
    print("  Current: 10% fintech, 20% healthtech, 30% AI/ML, 40% other")
    print("  VC interests: 30% fintech, 20% healthtech, 25% AI/ML, 25% other")
    print("  GAP IDENTIFIED: Need 20% more fintech coverage\n")

    print("Step 2: Data Strategy Planner creates scraping plan...")
    print("  Target: Fintech startups")
    print("  Sources: Crunchbase, Product Hunt, AngelList")
    print("  Filter: Seed to Series A, founded 2020-2024\n")

    print("Step 3: Scraper Actor collects data...")
    print("  Collected: 50 fintech startups")
    print("  Quality validation: PASS (95% completeness)\n")

    print("Step 4: Data added to semantic memory...")
    print("  New total: 60 startups (40% fintech)\n")

    print("Step 5: Episode recorded in episodic memory")
    print("  Agent: data_strategy_planner")
    print("  Success: True")
    print("  Performance: High\n")

    print("RESULT: Successfully closed data gap!")
    print("  Before: 10% fintech coverage")
    print("  After: 40% fintech coverage")
    print("  VC alignment: Improved from 0.45 to 0.85\n")


def scenario_2_tool_building():
    """Run tool building scenario."""
    scenario_data = run_scenario('tool_building')
    display_scenario_info(scenario_data)

    print("Simulating tool building process...\n")

    print("Step 1: Analyzing user interaction patterns...")
    print("  Pattern detected: 15 requests for pitch deck analysis")
    print("  Pattern detected: 8 requests for deck quality scoring")
    print("  NEED IDENTIFIED: Pitch deck analyzer tool\n")

    print("Step 2: Product Strategy Planner generates specification...")
    print("  Tool: Pitch Deck Analyzer")
    print("  Features:")
    print("    - Slide structure analysis")
    print("    - Content quality scoring")
    print("    - VC alignment matching")
    print("    - Recommendations generation\n")

    print("Step 3: Tool Builder Actor implements tool...")
    print("  Code generated: 250 lines")
    print("  Test cases created: 15")
    print("  Build time: ~2 hours (simulated)\n")

    print("Step 4: Tool testing and validation...")
    print("  Tests passed: 14/15 (93%)")
    print("  Quality score: 0.90")
    print("  Validation: PASS\n")

    print("Step 5: Tool registered and workflow saved...")
    print("  Tool added to registry")
    print("  Workflow saved to procedural memory (score: 0.90)\n")

    print("RESULT: New pitch deck analyzer tool available!")
    print("  Status: Production-ready")
    print("  Expected impact: Reduces manual deck review time by 60%\n")


def scenario_3_outreach_campaign():
    """Run outreach campaign scenario."""
    scenario_data = run_scenario('outreach_campaign')
    display_scenario_info(scenario_data)

    print("Simulating multi-iteration outreach campaign...\n")

    # Iteration 1
    print("ITERATION 1: Baseline")
    print("  Approach: Standard templates, minimal personalization")
    print("  Messages sent: 20")
    print("  Responses: 3 (15% response rate)")
    print("  Meetings scheduled: 1 (5% meeting rate)")
    print("  Learning: Personalization matters, generic messages fail\n")

    # Iteration 2
    print("ITERATION 2: Adapted Strategy")
    print("  Approach: Personalized messages, reference recent news")
    print("  Messages sent: 20")
    print("  Responses: 5 (25% response rate)")
    print("  Meetings scheduled: 2 (10% meeting rate)")
    print("  Learning: Tuesday-Thursday mornings work best\n")

    # Iteration 3
    print("ITERATION 3: Optimized Strategy")
    print("  Approach: High personalization + optimal timing + VC matches")
    print("  Messages sent: 20")
    print("  Responses: 7 (35% response rate)")
    print("  Meetings scheduled: 3 (15% meeting rate)")
    print("  Learning: Workflow saved to procedural memory (score: 0.85)\n")

    print("RESULT: Clear improvement through learning!")
    print("  Response rate: 15% → 25% → 35% (2.3x improvement)")
    print("  Meeting rate: 5% → 10% → 15% (3x improvement)")
    print("  Successful workflow saved for future campaigns\n")


def scenario_4_full_cycle():
    """Run full Build-Measure-Learn cycle scenario."""
    print("\n" + "="*60)
    print("SCENARIO: FULL BUILD-MEASURE-LEARN CYCLE")
    print("="*60)
    print("\nThis scenario runs the complete simulation.")
    print("Running main simulation script...\n")

    # Import and run the main simulation
    from scripts.run_simulation import run_simulation
    run_simulation(iterations=3)


def main():
    """Main entry point for demo scenarios."""
    scenarios = {
        '1': ('Data Collection', scenario_1_data_collection),
        '2': ('Tool Building', scenario_2_tool_building),
        '3': ('Outreach Campaign', scenario_3_outreach_campaign),
        '4': ('Full Build-Measure-Learn Cycle', scenario_4_full_cycle)
    }

    print("\n" + "="*60)
    print("AUTONOMOUS STARTUP SIMULATION - DEMO SCENARIOS")
    print("="*60)
    print("\nSelect a scenario to run:\n")

    for key, (name, _) in scenarios.items():
        print(f"  {key}. {name}")

    print("\n" + "="*60)

    choice = input("\nEnter scenario number (1-4): ").strip()

    if choice in scenarios:
        name, func = scenarios[choice]
        print(f"\nRunning scenario: {name}\n")
        func()
    else:
        print("Invalid choice. Please run again and select 1-4.")


if __name__ == "__main__":
    main()
