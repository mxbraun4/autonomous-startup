"""Data Strategy Planner - Manages data collection and quality."""
from typing import Dict, Any
from src.agents.base import BasePlanner
from src.llm.client import LLMClient
from src.llm.prompts import PromptTemplates
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DataStrategyPlanner(BasePlanner):
    """Planner for data strategy - identifies gaps and coordinates data collection."""

    def __init__(self, llm_client: LLMClient, memory_system: Dict[str, Any]):
        """Initialize Data Strategy Planner.

        Args:
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__("data_strategy_planner", llm_client, memory_system)

    def analyze(self) -> Dict[str, Any]:
        """Analyze data gaps and opportunities.

        Returns:
            Analysis dict
        """
        self.log("Analyzing data gaps")

        # Get current data inventory from semantic memory
        data_inventory = self._get_data_inventory()

        # Get VC preferences to identify gaps
        vc_preferences = self._get_vc_preferences()

        # Use LLM to identify gaps
        prompt = PromptTemplates.DATA_IDENTIFY_GAPS.format(
            data_summary=data_inventory,
            vc_preferences=vc_preferences
        )

        gaps_analysis = self.llm.generate(
            prompt,
            system="You are a data strategy expert."
        )

        return {
            'goal': self.current_goal,
            'data_inventory': data_inventory,
            'vc_preferences': vc_preferences,
            'gaps_analysis': gaps_analysis
        }

    def plan(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Create data collection plan.

        Args:
            analysis: Analysis dict

        Returns:
            Plan dict
        """
        self.log("Creating data collection plan")

        # Check procedural memory for existing scraping workflows
        workflow = self.procedural_memory.get_workflow('data_collection')

        if workflow and workflow.get('score', 0) > 0.7:
            self.log("Using high-performing workflow from procedural memory")
            return workflow['workflow']

        # Generate new plan using LLM
        prompt = PromptTemplates.DATA_SCRAPING_PLAN.format(
            gaps=analysis['gaps_analysis']
        )

        plan_text = self.llm.generate(prompt)

        return {
            'description': plan_text,
            'tasks': self._extract_scraping_tasks(plan_text),
            'priority_gaps': self._extract_priority_gaps(analysis['gaps_analysis'])
        }

    def _get_data_inventory(self) -> str:
        """Get summary of current data.

        Returns:
            Data inventory string
        """
        # Search semantic memory for startup and VC data
        startup_docs = self.semantic_memory.search("startup", top_k=10)
        vc_docs = self.semantic_memory.search("venture capital VC", top_k=10)

        # Count by sector (simplified)
        sectors = {}
        for doc in startup_docs:
            metadata = doc.get('metadata', {})
            sector = metadata.get('sector', 'unknown')
            sectors[sector] = sectors.get(sector, 0) + 1

        inventory = "Current Startup Data:\n"
        for sector, count in sectors.items():
            inventory += f"- {sector}: {count} startups\n"

        inventory += f"\nTotal VCs: {len(vc_docs)}"

        return inventory

    def _get_vc_preferences(self) -> str:
        """Get summary of VC preferences.

        Returns:
            VC preferences string
        """
        vc_docs = self.semantic_memory.search("venture capital sectors", top_k=10)

        # Aggregate sector preferences
        sectors = {}
        for doc in vc_docs:
            metadata = doc.get('metadata', {})
            if 'sectors' in metadata:
                for sector in metadata['sectors']:
                    sectors[sector] = sectors.get(sector, 0) + 1

        prefs = "VC Sector Preferences:\n"
        for sector, count in sorted(sectors.items(), key=lambda x: x[1], reverse=True):
            prefs += f"- {sector}: {count} VCs\n"

        return prefs

    def _extract_scraping_tasks(self, plan_text: str) -> list:
        """Extract scraping tasks from plan.

        Args:
            plan_text: Plan text

        Returns:
            List of task dicts
        """
        tasks = []

        # Parse plan text for targets
        for line in plan_text.split('\n'):
            line = line.strip()
            if 'target:' in line.lower() or line.startswith('1.') or line.startswith('2.') or line.startswith('3.'):
                tasks.append({
                    'description': line,
                    'type': 'scraping',
                    'status': 'pending'
                })

        # Default tasks if parsing failed
        if not tasks:
            tasks = [
                {'description': 'Collect fintech startup data', 'type': 'scraping', 'status': 'pending'},
                {'description': 'Collect late-stage startup data', 'type': 'scraping', 'status': 'pending'}
            ]

        return tasks

    def _extract_priority_gaps(self, gaps_analysis: str) -> list:
        """Extract priority gaps from analysis.

        Args:
            gaps_analysis: Gaps analysis text

        Returns:
            List of priority gaps
        """
        # Simple extraction of mentioned sectors/categories
        priority_keywords = ['fintech', 'healthtech', 'ai', 'series a', 'series b', 'late-stage']
        gaps = []

        gaps_lower = gaps_analysis.lower()
        for keyword in priority_keywords:
            if keyword in gaps_lower:
                gaps.append(keyword)

        return gaps[:3]  # Top 3 priorities
