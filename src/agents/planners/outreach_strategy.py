"""Outreach Strategy Planner - Manages outreach campaigns."""
from typing import Dict, Any, List
from src.agents.base import BasePlanner
from src.llm.client import LLMClient
from src.llm.prompts import PromptTemplates
from src.utils.logging import get_logger

logger = get_logger(__name__)


class OutreachStrategyPlanner(BasePlanner):
    """Planner for outreach strategy - optimizes communication campaigns."""

    def __init__(self, llm_client: LLMClient, memory_system: Dict[str, Any]):
        """Initialize Outreach Strategy Planner.

        Args:
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__("outreach_strategy_planner", llm_client, memory_system)
        self.generated_outreach: List[Dict[str, Any]] = []

    def analyze(self) -> Dict[str, Any]:
        """Analyze outreach opportunities and past performance.

        Returns:
            Analysis dict
        """
        self.log("Analyzing outreach opportunities")

        # Get available startup data
        startup_data = self.semantic_memory.search("startup fundraising", top_k=20)

        # Get VC interests
        vc_interests = self.semantic_memory.search("VC interests sectors", top_k=10)

        # Get previous campaign results from episodic memory
        previous_campaigns = self.episodic_memory.search_similar(
            agent_id=self.agent_id,
            episode_type='outreach_campaign',
            success_only=True,
            limit=10
        )

        # Use LLM to analyze opportunities
        prompt = f"""Analyze outreach opportunities:

Available startups: {len(startup_data)}
VC interests: {len(vc_interests)}

Previous campaign results:
{self._format_campaigns(previous_campaigns)}

Identify best opportunities and approach."""

        analysis = self.llm.generate(
            prompt,
            system="You are an outreach strategy expert."
        )

        return {
            'goal': self.current_goal,
            'startup_data': startup_data,
            'vc_interests': vc_interests,
            'previous_campaigns': previous_campaigns,
            'analysis': analysis
        }

    def plan(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Create outreach campaign plan.

        Args:
            analysis: Analysis dict

        Returns:
            Plan dict
        """
        self.log("Creating outreach campaign plan")

        # Check for successful outreach workflows
        workflow = self.procedural_memory.get_workflow('outreach_campaign')

        if workflow and workflow.get('score', 0) > 0.7:
            self.log("Using proven outreach workflow")
            base_plan = workflow['workflow']
        else:
            base_plan = {}

        # Generate campaign plan using LLM
        prompt = PromptTemplates.OUTREACH_CAMPAIGN_PLAN.format(
            startup_data_summary=f"{len(analysis['startup_data'])} startups available",
            vc_interests=self._format_vc_interests(analysis['vc_interests']),
            previous_results=self._format_campaigns(analysis['previous_campaigns'])
        )

        plan_text = self.llm.generate(prompt)

        # Extract learnings from previous campaigns
        learnings = self._extract_learnings(analysis['previous_campaigns'])

        return {
            'description': plan_text,
            'tasks': self._extract_outreach_tasks(plan_text),
            'learnings': learnings,
            'target_metrics': {
                'response_rate': 0.25,  # Target 25% response rate
                'meeting_conversion': 0.40  # Target 40% meeting conversion
            }
        }

    def _format_campaigns(self, campaigns: list) -> str:
        """Format campaigns for LLM.

        Args:
            campaigns: List of campaign episodes

        Returns:
            Formatted string
        """
        if not campaigns:
            return "No previous campaigns"

        formatted = []
        for campaign in campaigns:
            outcome = campaign.get('outcome', {})
            formatted.append(
                f"- Response rate: {outcome.get('response_rate', 0):.1%}, "
                f"Meetings: {outcome.get('meetings', 0)}"
            )

        return "\n".join(formatted)

    def _format_vc_interests(self, vc_docs: list) -> str:
        """Format VC interests for LLM.

        Args:
            vc_docs: List of VC documents

        Returns:
            Formatted string
        """
        if not vc_docs:
            return "No VC data available"

        formatted = []
        for doc in vc_docs:
            metadata = doc.get('metadata', {})
            sectors = metadata.get('sectors', [])
            if sectors:
                formatted.append(f"- Interested in: {', '.join(sectors)}")

        return "\n".join(formatted[:10])

    def _extract_learnings(self, campaigns: list) -> list:
        """Extract learnings from previous campaigns.

        Args:
            campaigns: List of campaign episodes

        Returns:
            List of learning dicts
        """
        learnings = []

        for campaign in campaigns:
            context = campaign.get('context', {})
            outcome = campaign.get('outcome', {})

            if outcome.get('response_rate', 0) > 0.25:  # Above 25% is good
                learnings.append({
                    'what_worked': context.get('approach', 'Unknown'),
                    'response_rate': outcome.get('response_rate', 0)
                })

        return learnings

    def _extract_outreach_tasks(self, plan_text: str) -> list:
        """Extract outreach tasks from plan.

        Args:
            plan_text: Plan text

        Returns:
            List of task dicts
        """
        tasks = []

        # Look for key outreach phases
        phases = ['identify', 'personalize', 'send', 'follow-up', 'track']

        for line in plan_text.split('\n'):
            line = line.strip()
            if any(phase in line.lower() for phase in phases) or line[0:1].isdigit():
                tasks.append({
                    'description': line.lstrip('0123456789.-'),
                    'type': 'outreach',
                    'status': 'pending'
                })

        # Default tasks
        if not tasks:
            tasks = [
                {'description': 'Identify target startups', 'type': 'outreach', 'status': 'pending'},
                {'description': 'Generate personalized messages', 'type': 'outreach', 'status': 'pending'},
                {'description': 'Send outreach campaign', 'type': 'outreach', 'status': 'pending'},
                {'description': 'Track responses', 'type': 'outreach', 'status': 'pending'}
            ]

        return tasks

    def get_generated_outreach(self) -> List[Dict[str, Any]]:
        """Get generated outreach messages.

        Returns:
            List of outreach messages
        """
        return self.generated_outreach

    def record_campaign_results(
        self,
        campaign_id: str,
        results: Dict[str, Any],
        iteration: int
    ) -> None:
        """Record campaign results in episodic memory.

        Args:
            campaign_id: Campaign identifier
            results: Results dict
            iteration: Iteration number
        """
        response_rate = results.get('response_rate', 0)

        self.episodic_memory.record(
            agent_id=self.agent_id,
            episode_type='outreach_campaign',
            context={
                'campaign_id': campaign_id,
                'target_count': results.get('total_sent', 0)
            },
            outcome={
                'response_rate': response_rate,
                'interested': results.get('interested', 0),
                'meetings': results.get('meetings', 0)
            },
            success=response_rate > 0.20,  # 20% response rate is successful
            iteration=iteration
        )

        self.log(f"Recorded campaign results: {response_rate:.1%} response rate")
