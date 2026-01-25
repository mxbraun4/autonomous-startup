"""Master Planner - Orchestrates the Build-Measure-Learn cycle."""
from typing import Dict, Any, List
from src.agents.base import BasePlanner
from src.llm.client import LLMClient
from src.llm.prompts import PromptTemplates
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MasterPlanner(BasePlanner):
    """Master Planner orchestrates high-level Build-Measure-Learn cycles."""

    def __init__(self, llm_client: LLMClient, memory_system: Dict[str, Any]):
        """Initialize Master Planner.

        Args:
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__("master_planner", llm_client, memory_system)
        self.specialized_planners: List[BasePlanner] = []

    def add_planners(self, planners: List[BasePlanner]) -> None:
        """Add specialized planner agents.

        Args:
            planners: List of planner agents
        """
        self.specialized_planners.extend(planners)
        self.log(f"Added {len(planners)} specialized planners")

    def run_build_measure_learn_cycle(
        self,
        iteration: int = 0,
        metrics: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Run complete Build-Measure-Learn cycle.

        Args:
            iteration: Iteration number
            metrics: Metrics from previous iteration

        Returns:
            Cycle results
        """
        self.log(f"=== Starting Build-Measure-Learn Cycle {iteration} ===")

        # BUILD Phase
        self.log("BUILD phase: Coordinating specialized planners")
        build_results = self.run_build_phase(iteration)

        # MEASURE Phase (handled externally, passed as metrics)
        self.log("MEASURE phase: Collecting metrics")
        measure_results = metrics or {}

        # LEARN Phase
        self.log("LEARN phase: Updating memories")
        learn_results = self.run_learn_phase(measure_results, iteration)

        cycle_results = {
            'iteration': iteration,
            'build': build_results,
            'measure': measure_results,
            'learn': learn_results
        }

        self.log(f"=== Completed Build-Measure-Learn Cycle {iteration} ===")
        return cycle_results

    def run_build_phase(self, iteration: int = 0) -> Dict[str, Any]:
        """Run BUILD phase - coordinate specialized planners.

        Args:
            iteration: Iteration number

        Returns:
            Build phase results
        """
        # Analyze overall state
        state_summary = self._get_state_summary()
        recent_episodes = self.episodic_memory.get_recent(limit=10)

        # Use LLM to analyze state
        prompt = PromptTemplates.MASTER_ANALYZE_STATE.format(
            state_summary=state_summary,
            metrics=self._format_metrics(),
            episodic_context=self._format_episodes(recent_episodes)
        )

        analysis = self.llm.generate(prompt, system="You are the Master Planner.")

        # Decompose into goals for specialized planners
        goals_prompt = PromptTemplates.MASTER_DECOMPOSE_GOALS.format(analysis=analysis)
        goals_text = self.llm.generate(goals_prompt)

        # Parse goals and assign to planners
        goals = self._parse_goals(goals_text)
        planner_results = []

        for i, planner in enumerate(self.specialized_planners):
            if i < len(goals):
                planner.assign_goal(goals[i])
                result = planner.run_cycle(iteration)
                planner_results.append({
                    'planner_id': planner.agent_id,
                    'goal': goals[i],
                    'result': result
                })

        return {
            'analysis': analysis,
            'goals': goals,
            'planner_results': planner_results
        }

    def run_learn_phase(
        self,
        metrics: Dict[str, Any],
        iteration: int
    ) -> Dict[str, Any]:
        """Run LEARN phase - update memories based on outcomes.

        Args:
            metrics: Metrics from MEASURE phase
            iteration: Iteration number

        Returns:
            Learning results
        """
        # Use LLM to analyze what worked and what didn't
        prompt = f"""Analyze these metrics from iteration {iteration}:

Metrics:
{metrics}

Recent episodes:
{self._format_episodes(self.episodic_memory.get_recent(limit=10))}

Identify:
1. What worked well
2. What didn't work
3. Key learnings
4. Recommendations for next iteration"""

        insights = self.llm.generate(prompt, system="You are analyzing system performance.")

        # Record in episodic memory
        self.episodic_memory.record(
            agent_id=self.agent_id,
            episode_type='build_measure_learn_cycle',
            context={
                'iteration': iteration,
                'specialized_planners': [p.agent_id for p in self.specialized_planners]
            },
            outcome={
                'metrics': metrics,
                'insights': insights
            },
            success=metrics.get('overall_success', True),
            iteration=iteration
        )

        return {
            'insights': insights,
            'metrics_recorded': True
        }

    def _get_state_summary(self) -> str:
        """Get summary of current system state.

        Returns:
            State summary string
        """
        semantic_size = self.semantic_memory.size()
        recent_episodes = len(self.episodic_memory.get_recent(limit=100))
        workflows = len(self.procedural_memory.get_all_workflows())

        return f"""System State:
- Semantic memory: {semantic_size} documents
- Recent episodes: {recent_episodes}
- Learned workflows: {workflows}
- Specialized planners: {len(self.specialized_planners)}
"""

    def _format_metrics(self) -> str:
        """Format metrics for LLM.

        Returns:
            Formatted metrics string
        """
        # Get recent performance data
        success_rate = self.episodic_memory.get_success_rate(agent_id=self.agent_id)

        return f"""Recent Performance:
- Overall success rate: {success_rate:.2%}
"""

    def _format_episodes(self, episodes: List[Dict[str, Any]]) -> str:
        """Format episodes for LLM.

        Args:
            episodes: List of episode dicts

        Returns:
            Formatted string
        """
        if not episodes:
            return "No recent episodes"

        formatted = []
        for ep in episodes[:5]:  # Limit to 5 most recent
            formatted.append(
                f"- {ep['agent_id']}/{ep['episode_type']}: "
                f"success={ep['success']}, "
                f"outcome={ep['outcome']}"
            )

        return "\n".join(formatted)

    def _parse_goals(self, goals_text: str) -> List[Dict[str, str]]:
        """Parse goals from LLM output.

        Args:
            goals_text: Goals text from LLM

        Returns:
            List of goal dicts
        """
        goals = []

        # Extract goals for each planner type
        planner_types = ['Data Strategy', 'Product Strategy', 'Outreach Strategy']

        for planner_type in planner_types:
            # Simple extraction: find lines mentioning the planner type
            for line in goals_text.split('\n'):
                if planner_type.lower() in line.lower():
                    goal_text = line.split(':', 1)[1].strip() if ':' in line else line
                    goals.append({
                        'type': planner_type.lower().replace(' ', '_'),
                        'description': goal_text
                    })
                    break

        # If parsing failed, create default goals
        if not goals:
            goals = [
                {'type': 'data_strategy', 'description': 'Improve data coverage and quality'},
                {'type': 'product_strategy', 'description': 'Enhance platform tools and features'},
                {'type': 'outreach_strategy', 'description': 'Optimize outreach campaigns'}
            ]

        return goals
