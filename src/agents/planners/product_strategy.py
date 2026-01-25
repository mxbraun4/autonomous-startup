"""Product Strategy Planner - Manages tool building and platform features."""
from typing import Dict, Any
from src.agents.base import BasePlanner
from src.llm.client import LLMClient
from src.llm.prompts import PromptTemplates
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ProductStrategyPlanner(BasePlanner):
    """Planner for product strategy - identifies tool needs and coordinates building."""

    def __init__(self, llm_client: LLMClient, memory_system: Dict[str, Any]):
        """Initialize Product Strategy Planner.

        Args:
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__("product_strategy_planner", llm_client, memory_system)
        self.tool_registry = []

    def analyze(self) -> Dict[str, Any]:
        """Analyze product needs and opportunities.

        Returns:
            Analysis dict
        """
        self.log("Analyzing product needs")

        # Get user interaction patterns from episodic memory
        user_interactions = self.episodic_memory.search_similar(
            episode_type='user_interaction',
            limit=20
        )

        # Get current tool inventory
        tools_docs = self.semantic_memory.search("tool feature platform", top_k=10)

        # Use LLM to identify unmet needs
        prompt = PromptTemplates.PRODUCT_IDENTIFY_NEEDS.format(
            user_interactions=self._format_interactions(user_interactions),
            tools=self._format_tools(tools_docs)
        )

        needs_analysis = self.llm.generate(
            prompt,
            system="You are a product strategy expert."
        )

        return {
            'goal': self.current_goal,
            'user_interactions': user_interactions,
            'current_tools': tools_docs,
            'needs_analysis': needs_analysis
        }

    def plan(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Create product development plan.

        Args:
            analysis: Analysis dict

        Returns:
            Plan dict
        """
        self.log("Creating product development plan")

        # Check for existing tool building workflows
        workflow = self.procedural_memory.get_workflow('tool_building')

        if workflow and workflow.get('score', 0) > 0.7:
            self.log("Using proven tool building workflow")
            return workflow['workflow']

        # Generate new plan
        prompt = f"""Based on this needs analysis:
{analysis['needs_analysis']}

Create a plan for building the most impactful tool or feature.
Include: specification, implementation approach, testing strategy."""

        plan_text = self.llm.generate(prompt)

        return {
            'description': plan_text,
            'tasks': self._extract_building_tasks(plan_text),
            'tool_spec': self._extract_tool_spec(plan_text)
        }

    def _format_interactions(self, interactions: list) -> str:
        """Format user interactions for LLM.

        Args:
            interactions: List of interaction episodes

        Returns:
            Formatted string
        """
        if not interactions:
            return "No recent user interactions"

        formatted = []
        for interaction in interactions[:10]:
            context = interaction.get('context', {})
            formatted.append(
                f"- User action: {context.get('action', 'unknown')}, "
                f"outcome: {interaction.get('outcome', {})}"
            )

        return "\n".join(formatted)

    def _format_tools(self, tools_docs: list) -> str:
        """Format tools for LLM.

        Args:
            tools_docs: List of tool documents

        Returns:
            Formatted string
        """
        if not tools_docs:
            return "No tools in inventory"

        formatted = []
        for doc in tools_docs:
            formatted.append(f"- {doc.get('text', '')[:100]}")

        return "\n".join(formatted)

    def _extract_building_tasks(self, plan_text: str) -> list:
        """Extract building tasks from plan.

        Args:
            plan_text: Plan text

        Returns:
            List of task dicts
        """
        tasks = []

        # Common tool building phases
        phases = ['specification', 'implementation', 'testing', 'deployment']

        for line in plan_text.split('\n'):
            line = line.strip()
            if any(phase in line.lower() for phase in phases):
                tasks.append({
                    'description': line,
                    'type': 'tool_building',
                    'status': 'pending'
                })

        # Default tasks
        if not tasks:
            tasks = [
                {'description': 'Create tool specification', 'type': 'tool_building', 'status': 'pending'},
                {'description': 'Implement tool', 'type': 'tool_building', 'status': 'pending'},
                {'description': 'Test tool', 'type': 'tool_building', 'status': 'pending'}
            ]

        return tasks

    def _extract_tool_spec(self, plan_text: str) -> dict:
        """Extract tool specification from plan.

        Args:
            plan_text: Plan text

        Returns:
            Tool spec dict
        """
        # Simple extraction
        return {
            'name': 'New Tool',
            'description': plan_text[:200],
            'status': 'planned'
        }

    def register_tool(self, tool: Dict[str, Any]) -> None:
        """Register a completed tool.

        Args:
            tool: Tool dict
        """
        self.tool_registry.append(tool)
        self.log(f"Registered tool: {tool.get('name', 'Unknown')}")

        # Add to semantic memory
        self.semantic_memory.add(
            text=f"Tool: {tool.get('name')} - {tool.get('description')}",
            metadata={'type': 'tool', 'name': tool.get('name')}
        )
