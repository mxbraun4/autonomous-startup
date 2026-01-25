"""Content Generator Actor - Generates personalized outreach content."""
import random
from typing import Dict, Any, List
from src.agents.base import BaseActor
from src.llm.client import LLMClient
from src.llm.prompts import PromptTemplates
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ContentGeneratorActor(BaseActor):
    """Actor that generates personalized outreach content."""

    def __init__(self, llm_client: LLMClient, memory_system: Dict[str, Any]):
        """Initialize Content Generator Actor.

        Args:
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__("content_generator_actor", llm_client, memory_system)
        self.generated_messages: List[Dict[str, Any]] = []

    def execute(self, task: Dict[str, Any]) -> Any:
        """Execute content generation task.

        Args:
            task: Task dict with target startups and matched VCs

        Returns:
            Generated outreach messages
        """
        self.log(f"Generating outreach content: {task.get('description', 'Unknown')}")

        # Get target startups from semantic memory
        startup_docs = self.semantic_memory.search("startup fundraising active", top_k=10)

        # Get learnings from episodic memory
        successful_outreach = self.episodic_memory.search_similar(
            episode_type='outreach_campaign',
            success_only=True,
            limit=5
        )

        learnings = self._extract_learnings(successful_outreach)

        # Generate messages for each startup
        messages = []
        for i, doc in enumerate(startup_docs[:5]):  # Generate 5 messages for demo
            startup_profile = doc.get('metadata', {})

            # Find matched VCs (simulated)
            matched_vcs = self._find_matched_vcs(startup_profile)

            # Generate personalized message
            prompt = PromptTemplates.OUTREACH_MESSAGE_TEMPLATE.format(
                startup_profile=startup_profile,
                matched_vcs=matched_vcs,
                learnings=learnings
            )

            message_text = self.llm.generate(
                prompt,
                system="You are an expert at startup-VC matchmaking and outreach."
            )

            message = {
                'id': f"msg_{i+1}",
                'startup': startup_profile.get('name', 'Unknown'),
                'message': message_text,
                'matched_vcs': matched_vcs,
                'personalization_score': self._calculate_personalization(message_text)
            }

            messages.append(message)

        self.generated_messages = messages
        self.log(f"Generated {len(messages)} personalized messages")

        return {
            'status': 'completed',
            'messages': messages,
            'count': len(messages)
        }

    def validate(self, result: Any) -> bool:
        """Validate generated content.

        Args:
            result: Execution result

        Returns:
            True if valid
        """
        if not result or result.get('status') != 'completed':
            return False

        messages = result.get('messages', [])

        if not messages:
            self.log("Validation failed: No messages generated", level="warning")
            return False

        # Check message quality
        for msg in messages:
            # Check length (should be under 150 words per best practices)
            word_count = len(msg['message'].split())
            if word_count > 200:
                self.log(
                    f"Warning: Message too long ({word_count} words)",
                    level="warning"
                )

            # Check personalization score
            if msg.get('personalization_score', 0) < 0.3:
                self.log(
                    "Warning: Low personalization score",
                    level="warning"
                )

        self.log("Content validation: PASS")
        return True

    def get_generated_messages(self) -> List[Dict[str, Any]]:
        """Get generated messages.

        Returns:
            List of message dicts
        """
        return self.generated_messages

    def _find_matched_vcs(self, startup_profile: Dict[str, Any]) -> List[Dict[str, str]]:
        """Find matched VCs for a startup (simulated).

        Args:
            startup_profile: Startup profile dict

        Returns:
            List of matched VC dicts
        """
        # Search semantic memory for matching VCs
        sector = startup_profile.get('sector', 'unknown')
        vc_docs = self.semantic_memory.search(f"VC {sector}", top_k=3)

        matches = []
        for doc in vc_docs:
            vc_data = doc.get('metadata', {})
            if vc_data:
                matches.append({
                    'name': vc_data.get('name', 'Unknown VC'),
                    'sector_match': sector in vc_data.get('sectors', []),
                    'stage_match': vc_data.get('stage_focus') == startup_profile.get('stage')
                })

        return matches[:2]  # Top 2 matches

    def _extract_learnings(self, episodes: List[Dict[str, Any]]) -> str:
        """Extract learnings from successful episodes.

        Args:
            episodes: List of episode dicts

        Returns:
            Learnings summary
        """
        if not episodes:
            return "No previous learnings available"

        insights = []
        for ep in episodes[:3]:
            outcome = ep.get('outcome', {})
            if outcome.get('response_rate', 0) > 0.25:
                insights.append(f"- High response rate achieved with personalized approach")

        if not insights:
            insights.append("- Use personalization and reference recent news")
            insights.append("- Keep messages concise (under 150 words)")

        return "\n".join(insights)

    def _calculate_personalization(self, message_text: str) -> float:
        """Calculate personalization score for message.

        Args:
            message_text: Message text

        Returns:
            Personalization score (0-1)
        """
        # Simple heuristic: check for personalization indicators
        indicators = [
            'recent', 'funding', 'product', 'team', 'news',
            'congratulations', 'noticed', 'saw', 'impressed'
        ]

        message_lower = message_text.lower()
        score = 0.0

        for indicator in indicators:
            if indicator in message_lower:
                score += 0.15

        # Cap at 1.0
        return min(score, 1.0)
